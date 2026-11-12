"""Reads / syncs the XP table with Google Sheets in the background.

Network calls run on worker threads that only return data; the XP table is merged and saved
on the Tk thread (``_done``).
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from .. import settings as settings_mod
from ..sheets import client
from ..sheets.layout import GSheetError

if TYPE_CHECKING:
    from .app import App

_SUMMARY_LABELS = {"added": "nuevos", "updated": "actualizados", "deleted": "borrados", "pushed": "cambios subidos"}


class SheetSync:
    def __init__(self, app: "App"):
        self.app = app
        self._running = False
        self._again: bool | None = None  # a run was requested meanwhile (value: was it manual)
        self._job = None
        self._gen = 0  # bumped when the sheet target changes: in-flight results are discarded
        self._import_pending = False  # new sheet saved by "Probar conexión" but not imported yet

    @property
    def mode(self) -> str:
        return self.app.settings.effective_gsheet_mode

    def target_changed(self, new_mode: str, old_script_url: str, new_script_url: str) -> None:
        """The sheet target (mode, link or script URL) is being changed: in-flight results
        belong to the old one."""
        self._gen += 1
        if settings_mod.ENABLE_SHEET_SYNC and new_mode == "sync" and new_script_url != old_script_url:
            # Nothing is known to be in the new sheet yet: push everything, delete nothing.
            self.app.xp.reset_sync_state()
            self.app.xp.save()

    def settings_saved(self, target_changed: bool) -> None:
        """After Guardar: import a new sheet, or one whose import is still pending."""
        if (target_changed or self._import_pending) and self.mode != "off":
            self._import_pending = False
            self.run(manual=True)

    def schedule(self) -> None:
        """Debounced background sync after a local edit (sync mode only)."""
        if self.mode == "sync":
            if self._job:
                self.app.root.after_cancel(self._job)
            self._job = self.app.root.after(1500, self.run)
        self.app.settings_window.update_sheet_info()

    @property
    def busy(self) -> bool:
        return self._running

    def run(self, manual: bool = False) -> None:
        """``manual`` (button press) reports progress and ignores the offline back-off."""
        if self._job:
            self.app.root.after_cancel(self._job)
            self._job = None
        mode = self.mode
        if mode == "off":
            return
        if self._running:
            self._again = bool(self._again) or manual
            return
        self._running = True
        if manual:
            self.app.status.set("Conectando con Google Sheets…")
        s = self.app.settings
        ops = self.app.xp.pending_ops() if mode == "sync" else []
        url, script, token, replace, gen = s.gsheet_url, s.gsheet_script_url, s.gsheet_token, s.gsheet_replace, self._gen

        def work():
            result, err = None, None
            try:
                if mode == "read":
                    result = client.fetch_sheet(url, manual=manual)
                else:
                    result = client.script_sync(script, token, ops, manual=manual)
            except GSheetError as e:
                err = str(e)
            except Exception as e:  # never crash a worker
                err = f"Error inesperado: {e}"
            self.app.after(lambda: self._done(mode, ops, replace, result, err, gen))

        threading.Thread(target=work, name="gsheet", daemon=True).start()

    def _done(self, mode: str, ops: list, replace: bool, result, err: str | None, gen: int) -> None:
        self._running = False
        xp, status = self.app.xp, self.app.status
        if mode != self.mode or gen != self._gen:
            result, err = None, None
            status.set("Google Sheets: la configuración cambió durante la conexión; resultado descartado.")
        elif err:
            pending = len(xp.pending_ops()) if mode == "sync" else 0
            status.set(f"Google Sheets: {err}. Se usa la tabla local" + (f" ({pending} cambios pendientes)." if pending else "."))
        else:
            before = set(xp.entries)
            try:
                if mode == "read":
                    rows, skipped = result
                    summary = xp.apply_read(rows, replace=replace)
                else:
                    skipped = 0
                    summary = xp.apply_sync_result(ops, result)
                xp.save()
                self._import_pending = False
                parts = [f"{summary[k]} {label}" for k, label in _SUMMARY_LABELS.items() if summary.get(k)]
                msg = "Google Sheets: " + (", ".join(parts) if parts else "todo al día")
                if skipped:
                    msg += f" ({skipped} filas no válidas ignoradas)"
                status.set(msg + ".")
            except ValueError as e:  # replace with an empty sheet, incomplete response
                status.set(f"Google Sheets: {e}.")
            except Exception as e:  # malformed response: the merges work on copies, the table is untouched
                status.set(f"Google Sheets: respuesta inesperada ({e}). Se usa la tabla local.")
            self.app.panel.table_replaced([n for n in xp.entries if n not in before])
        self.app.settings_window.update_sheet_info()
        if self._again is not None:
            manual, self._again = self._again, None
            self.run(manual=manual)
        elif mode == "sync" and not err and result is not None:
            sent = {(o["op"], o["name"]) for o in ops}
            if any((o["op"], o["name"]) not in sent for o in xp.pending_ops()):
                self.schedule()  # rows that became pending during the merge

    def test_connection(self, target_changed: bool) -> None:
        """Probe the saved sheet target; a new target that answers is imported right away."""
        mode, s = self.mode, self.app.settings
        if mode == "off":
            self.app.status.set("Google Sheets está desactivado.")
            return
        self.app.status.set("Probando conexión con Google Sheets…")
        url, script, token = s.gsheet_url, s.gsheet_script_url, s.gsheet_token

        def work():
            ok = False
            try:
                if mode == "read":
                    rows, skipped = client.fetch_sheet(url, manual=True)
                    msg = f"Conexión correcta: {len(rows)} objetos en la hoja" + (f" ({skipped} filas no válidas)" if skipped else "")
                else:
                    msg = f"Conexión correcta: {len(client.script_get(script, token, manual=True).get('rows', []))} objetos en la hoja"
                ok = True
            except GSheetError as e:
                msg = f"Error: {e}"
            except Exception as e:  # never crash a worker
                msg = f"Error inesperado: {e}"

            def done():
                self.app.status.set(msg)
                if target_changed and ok:
                    self.run(manual=True)
                elif target_changed:
                    self._import_pending = True  # retried on the next Guardar

            self.app.after(done)

        threading.Thread(target=work, name="gsheet-test", daemon=True).start()
