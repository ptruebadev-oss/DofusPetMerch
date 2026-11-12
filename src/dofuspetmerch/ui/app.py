"""Main window, wired to the hotkey, the screen reading and the overlay.

Threads: capture/OCR/network run on workers; they come back to Tk only through ``App.after``.
The XP table is only modified on the Tk thread.
"""
from __future__ import annotations

import threading
import tkinter as tk
import traceback
import winsound
from tkinter import ttk

from ..analysis import Analysis, analyze
from ..hotkey import GlobalHotkey, HotkeyError
from ..paths import asset_path
from ..reading.capture import capture, grab_virtual_screen
from ..reading.ocr import OcrUnavailable, WinOcr
from ..settings import Settings
from ..xptable import XpTable, now_ms
from .calculator import Calculator
from .images import icon
from .region_select import RegionSelector
from .overlay import Overlay
from .settings_window import SettingsWindow
from .sheet_sync import SheetSync
from .widgets import FONT, Tooltip
from .xp_panel import XpPanel


class App:
    def __init__(self, debug: bool = False):
        self.settings = Settings.load()
        self._cli_debug = debug  # --debug: this session only, never written to config.json
        self.xp = XpTable.load()
        self.root = tk.Tk()
        self.root.title("DofusPetMerch")
        self.root.resizable(False, False)
        self._set_icon()
        self.status = tk.StringVar()
        self.overlay = Overlay(self.root)
        self.hotkey: GlobalHotkey | None = None
        self._busy = threading.Lock()
        self.last_name = ""  # last item read from the screen this session
        self._last_read_at = 0
        self.sheets = SheetSync(self)
        self.calculator = Calculator(self)
        self.settings_window = SettingsWindow(self)
        self._build_main()
        self.register_hotkey()
        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        if self.settings.effective_gsheet_mode != "off" and self.settings.gsheet_on_start:
            self.root.after(800, self.sheets.run)

    def _set_icon(self) -> None:
        ico = asset_path("icon.ico")
        if ico.exists():
            try:
                self.root.iconbitmap(default=str(ico))
            except tk.TclError:
                pass

    def _build_main(self) -> None:
        main = ttk.Frame(self.root, padding=(10, 8, 10, 0))
        main.pack(fill="both", expand=True)
        top = ttk.Frame(main)
        top.pack(fill="x", pady=(0, 6))
        ttk.Label(top, text="XP Mascotas", font=(FONT, 11, "bold")).pack(side="left")
        # Left to right: camera, refresh | add, delete | copy, calculator, settings
        # (packed from the right). Only the less obvious buttons get a tooltip.
        self._imgs = {}

        def tool(name: str, command, tip: str = "") -> Tooltip | None:
            self._imgs[name] = icon(self.root, name)
            btn = ttk.Button(top, image=self._imgs[name], command=command)
            btn.pack(side="right", padx=(4, 0))
            return Tooltip(btn, tip) if tip else None

        def divider() -> None:
            ttk.Separator(top, orient="vertical").pack(side="right", fill="y", padx=(10, 6), pady=3)

        tool("gear", self.settings_window.open)
        tool("calculator", self.calculator.open, "Calculadora de galleta")
        tool("clipboard", lambda: self.panel.copy_table())
        divider()
        tool("minus", lambda: self.panel.delete_selected())
        tool("plus", lambda: self.panel.open_editor())
        divider()
        self._refresh_tip = tool("refresh", lambda: self.panel.reload(), " ")
        tool("camera", self.trigger_region, "Leer zona de la pantalla")
        table = ttk.Frame(main)
        table.pack(fill="both", expand=True)
        self.panel = XpPanel(table, self, factor=self.settings_window.form_factor)
        self.update_refresh_tooltip()
        ttk.Label(self.root, textvariable=self.status, wraplength=460, foreground="#555").pack(fill="x", padx=10, pady=(4, 8))

    def update_refresh_tooltip(self) -> None:
        self._refresh_tip.text = self.panel.refresh_tooltip()

    def after(self, fn) -> None:
        """Run ``fn`` on the Tk thread (callable from workers); ignored if the app was closed."""
        try:
            self.root.after(0, fn)
        except (RuntimeError, tk.TclError):
            pass

    def register_hotkey(self) -> None:
        if self.hotkey:
            self.hotkey.stop()
            self.hotkey = None
        try:
            self.hotkey = GlobalHotkey(self.settings.hotkey, lambda: self.after(self.trigger))
            self.hotkey.start()
            self.status.set(f"Escuchando {self.settings.hotkey.upper()} — abre la ventana de compra y púlsalo.")
        except HotkeyError as e:
            self.hotkey = None
            self.status.set(str(e))

    def trigger(self) -> None:
        """Hotkey: read the Dofus window, on the Tk thread. The heavy work runs on a worker."""
        if not self._busy.acquire(blocking=False):
            return
        anchor = (0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight())
        # Remove a previous result first so it does not end up in the new screenshot
        # (the compositor needs a frame to take it off the screen).
        delay = 80 if self.overlay.win is not None else 0
        self.overlay.hide()
        self.root.update_idletasks()
        self.root.after(delay, lambda: threading.Thread(target=self._work, args=(anchor,), daemon=True).start())

    def _work(self, anchor) -> None:
        try:
            img, anchor, _src = capture(self.settings.window_title)
        except Exception as e:  # never crash on a hotkey press
            traceback.print_exc()
            self._busy.release()
            data = Analysis(error=f"Error inesperado: {e}")
            self.after(lambda: self._present(data, anchor))
            return
        self._analyze(img, anchor)

    def _analyze(self, img, anchor) -> None:
        """Worker: analyse a screenshot covering screen rect ``anchor``; releases ``_busy``."""
        s = self.settings
        try:
            data = analyze(img, s, self.xp, WinOcr(s.lang), debug=s.debug or self._cli_debug)
        except OcrUnavailable as e:
            data = Analysis(error=str(e))
        except Exception as e:  # never crash on a read
            traceback.print_exc()
            data = Analysis(error=f"Error inesperado: {e}")
        finally:
            self._busy.release()
        self.after(lambda: self._present(data, anchor))

    def trigger_region(self) -> None:
        """Camera button: freeze the screen (without this window), let the user drag a region, read it."""
        if not self._busy.acquire(blocking=False):
            return
        self.overlay.hide()
        self.root.withdraw()

        def grab():
            try:
                shot = grab_virtual_screen()
            except Exception as e:
                traceback.print_exc()
                err = e
                self.after(lambda: self._region_failed(err))
                return
            self.after(lambda: self._select_region(*shot))

        self.root.after(250, lambda: threading.Thread(target=grab, name="region", daemon=True).start())

    def _region_failed(self, e: Exception) -> None:
        self._restore_window()
        self._busy.release()
        self.status.set(f"No se pudo capturar la pantalla: {e}")

    def _select_region(self, img, rect, monitors) -> None:
        def done(region):
            self._restore_window()
            if region is None:
                self._busy.release()
                return
            try:
                x, y, w, h = region
                vx, vy = rect[0], rect[1]
                crop = img[y - vy:y - vy + h, x - vx:x - vx + w].copy()
                threading.Thread(target=self._analyze, args=(crop, region), daemon=True).start()
            except Exception as e:  # _analyze releases _busy; if it never started, do it here
                traceback.print_exc()
                self._busy.release()
                self.status.set(f"No se pudo leer la zona: {e}")

        sel = RegionSelector(self.root)
        try:
            sel.select(img, rect, monitors, done)
        except Exception as e:  # never leave the main window hidden
            traceback.print_exc()
            if sel.cancel():  # done(None) already restored the window and freed _busy
                self.status.set(f"No se pudo mostrar la selección: {e}")
            else:
                self._region_failed(e)

    def _restore_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _present(self, data: Analysis, anchor) -> None:
        s = self.settings
        self.overlay.show(data, anchor, s.overlay_position, s.overlay_seconds)
        if s.sound:
            alias = "SystemAsterisk" if data.any_profitable else ("SystemHand" if data.error else None)
            if alias:
                winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC)
        if data.read_name:
            self.last_name = data.name or data.read_name
            self._last_read_at = now_ms()
        self.panel.after_read("" if data.error else data.name)

    def last_item(self) -> str:
        """The most recent of: the last item read from the screen, the last item added or
        updated in the table (kept in pet_xp.json, so it survives restarts). "" if none."""
        saved = self.xp.last_updated()
        if self.last_name and (saved is None or self._last_read_at >= saved[1]):
            return self.last_name
        return saved[0] if saved else ""

    def _quit(self) -> None:
        self.calculator.close()  # keeps valid pet prices
        if self.hotkey:
            self.hotkey.stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main(debug: bool = False) -> None:
    App(debug=debug).run()
