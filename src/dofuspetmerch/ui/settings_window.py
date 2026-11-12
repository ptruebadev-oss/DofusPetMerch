"""Settings window (⚙): collapsible sections and a single all-or-nothing Guardar.

``app.settings`` only ever holds saved values; the form lives in ``self.v`` and unsaved
changes are detected against ``self._saved``.
"""
from __future__ import annotations

import os
import time
import tkinter as tk
from dataclasses import fields
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from .. import settings as settings_mod
from ..hotkey import HotkeyError, parse_hotkey
from ..parsing import format_number, format_unit, parse_number
from ..paths import app_dir
from ..profit import kamas_per_xp
from ..settings import OVERLAY_POSITIONS, Settings, resolve_saved_gsheet_mode
from ..sheets.client import apps_script_source, parse_sheet_url
from .images import icon
from .widgets import FONT, Collapsible, Tooltip, entry_rows, info_icon

if TYPE_CHECKING:
    from .app import App

GSHEET_MODE_LABELS = {"off": "Desactivado", "read": "Solo leer (enlace)", "sync": "Sincronizar (Apps Script)"}
LANG_LABELS = {"es": "Español", "fr": "Français", "en": "English", "de": "Deutsch", "pt": "Português"}
# Saved by other windows, or kept only in config.json (window_title: rarely needs changing).
_NOT_IN_FORM = {"pet_price_100", "pet_price_1", "collapsed_sections", "window_title"}
_FORM_FIELDS = [f.name for f in fields(Settings) if f.name not in _NOT_IN_FORM]


class SettingsWindow:
    """Built once and kept hidden, so its widgets always exist."""

    def __init__(self, app: "App"):
        self.app = app
        defaults = Settings()
        self.v = {k: tk.BooleanVar() if isinstance(getattr(defaults, k), bool) else tk.StringVar() for k in _FORM_FIELDS}
        self._load_vars()

        w = self.win = tk.Toplevel(app.root)
        w.withdraw()
        w.title("DofusPetMerch · Ajustes")
        w.transient(app.root)
        w.resizable(False, False)
        w.protocol("WM_DELETE_WINDOW", self.close)
        w.bind("<Escape>", lambda _e: self.close())
        body = ttk.Frame(w, padding=10)
        body.pack(fill="both", expand=True)
        collapsed = set(app.settings.collapsed_sections)
        self.sections: dict[str, Collapsible] = {}
        # The keys are stored in config.json (collapsed_sections): keep them stable.
        for key, title, build in (("general", "General", self._build_general),
                                  ("galleta", "Galleta", self._build_profit),
                                  ("gsheets", "Google Sheets", self._build_gsheets)):
            sec = Collapsible(body, key, title, expanded=key not in collapsed, on_toggle=self._section_toggled)
            sec.pack(fill="x", pady=(0, 6))
            build(sec.body)
            self.sections[key] = sec
        buttons = ttk.Frame(w, padding=(10, 0, 10, 10))
        buttons.pack()  # centred
        ttk.Button(buttons, text="Guardar", command=self.save).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Cerrar", command=self.close).pack(side="left")
        self._saved = self._snapshot()

    def _form_value(self, key: str):
        val = getattr(self.app.settings, key)
        if key == "gsheet_mode":
            return GSHEET_MODE_LABELS[self.app.settings.effective_gsheet_mode]
        if key == "lang":
            return LANG_LABELS.get(val, LANG_LABELS["es"])
        if isinstance(val, float):
            return format_number(val)
        return val

    def _load_vars(self) -> None:
        """Saved settings -> form (also discards unsaved edits)."""
        for key in _FORM_FIELDS:
            self.v[key].set(self._form_value(key))

    def _snapshot(self) -> dict:
        return {k: var.get() for k, var in self.v.items()}

    def show_saved(self, *keys: str) -> None:
        """A setting was saved from outside the form: show it, and don't count it as unsaved."""
        for key in keys:
            self.v[key].set(self._form_value(key))
            self._saved[key] = self.v[key].get()

    def _num(self, key: str) -> float:
        v = parse_number(self.v[key].get())
        if v is None:
            raise ValueError(key)
        return v

    def form_factor(self) -> float | None:
        """Kamas per XP point with the values currently typed (the XP table previews them)."""
        try:
            return kamas_per_xp(self._num("cookie_price"), self._num("cookie_xp"), self._num("margin_pct"))
        except ValueError:
            return None

    def open(self) -> None:
        w, root = self.win, self.app.root
        if w.state() == "withdrawn":
            self._saved = self._snapshot()
            w.update_idletasks()
            w.geometry(f"+{root.winfo_rootx() + root.winfo_width() + 12}+{root.winfo_rooty()}")
        w.deiconify()
        w.lift()
        w.focus_force()

    def close(self) -> None:
        if self._snapshot() != self._saved:
            answer = messagebox.askyesnocancel("DofusPetMerch", "Hay cambios sin guardar. ¿Guardarlos?", parent=self.win)
            if answer is None:
                return
            if answer and not self.save():
                return
            if not answer:
                self._load_vars()  # the XP table must not keep previewing unsaved values
                self._update_sheet_fields()
        self.win.withdraw()

    def _section_toggled(self) -> None:
        s = self.app.settings
        s.collapsed_sections = sorted(k for k, c in self.sections.items() if not c.expanded)
        s.save()  # settings only ever holds saved values, so this saves nothing else

    def _build_general(self, g: ttk.Frame) -> None:
        i = entry_rows(g, self.v, [
            ("Atajo de teclado", "hotkey"),
            ("Duración de la alerta (s)", "overlay_seconds"),
        ])
        ttk.Label(g, text="Idioma").grid(row=i, column=0, sticky="w", pady=2)
        ttk.Combobox(g, textvariable=self.v["lang"], values=list(LANG_LABELS.values()), state="readonly",
                     width=16).grid(row=i, column=1, sticky="w", pady=2)
        i += 1
        ttk.Label(g, text="Posición del aviso").grid(row=i, column=0, sticky="w", pady=2)
        ttk.Combobox(g, textvariable=self.v["overlay_position"], values=OVERLAY_POSITIONS, state="readonly", width=16).grid(row=i, column=1, sticky="w")
        ttk.Checkbutton(g, text="Alerta cuando es rentable", variable=self.v["sound"]).grid(row=i + 1, column=0, columnspan=3, sticky="w")
        row = ttk.Frame(g)
        row.grid(row=i + 2, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(row, text="Usar dofusdb.fr (nombre oficial e icono)", variable=self.v["use_dofusdb"]).pack(side="left")
        info_icon(row, "Requiere internet. Corrige pequeños errores de lectura del nombre y descarga el icono "
                       "oficial del objeto (se guarda en local).\n\nDesactivado: no se conecta a internet; se usan "
                       "el nombre tal como se lee y el icono recortado de la pantalla.").pack(side="left", padx=(4, 0))
        ttk.Checkbutton(g, text="Modo depuración (guarda capturas)", variable=self.v["debug"]).grid(row=i + 3, column=0, columnspan=3, sticky="w")
        ttk.Button(g, text="Abrir carpeta de datos", command=lambda: os.startfile(app_dir())).grid(row=i + 4, column=0, sticky="w", pady=(6, 0))

    def _build_profit(self, p: ttk.Frame) -> None:
        i = entry_rows(p, self.v, [
            ("Precio galleta enriquecedora", "cookie_price", "K"),
            ("XP galleta enriquecedora", "cookie_xp"),
            ("Margen de rentabilidad (%)", "margin_pct"),
        ])
        self._calc_img = icon(p, "calculator")
        calc = ttk.Button(p, image=self._calc_img, command=lambda: self.app.calculator.open(near=self.win))
        calc.grid(row=0, column=2, sticky="w", padx=(4, 0))
        Tooltip(calc, "Calculadora de galleta")
        row = ttk.Frame(p)
        row.grid(row=i, column=0, columnspan=3, sticky="w", pady=(8, 2))
        self.factor_lbl = ttk.Label(row, font=(FONT, 10, "bold"))
        self.factor_lbl.pack(side="left")
        info_icon(row, "Máx. rentable por unidad = XP del objeto × factor.\n"
                       "Factor = precio galleta × (1 − margen) / XP galleta.").pack(side="left", padx=(4, 0))
        for key in ("cookie_price", "cookie_xp", "margin_pct"):
            self.v[key].trace_add("write", lambda *_: self._factor_changed())
        self._show_factor()

    def _show_factor(self) -> None:
        f = self.form_factor()
        self.factor_lbl.config(text=f"Factor: {format_unit(f)} kamas por punto de XP" if f else "Factor: valores no válidos")

    def _factor_changed(self) -> None:
        self._show_factor()
        self.app.panel.refresh()

    def _build_gsheets(self, f: ttk.Frame) -> None:
        ttk.Label(f, text="Modo").grid(row=0, column=0, sticky="w", pady=2)
        labels = [GSHEET_MODE_LABELS[m] for m in settings_mod.visible_gsheet_modes()]
        cb = ttk.Combobox(f, textvariable=self.v["gsheet_mode"], values=labels, state="readonly", width=26)
        cb.grid(row=0, column=1, columnspan=2, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda _e: self._update_sheet_fields())

        ttk.Label(f, text="Enlace de la hoja").grid(row=1, column=0, sticky="w", pady=2)
        self._gs_read = [ttk.Entry(f, textvariable=self.v["gsheet_url"], width=46)]
        self._gs_read[0].grid(row=1, column=1, columnspan=2, sticky="w")
        info_icon(f, "Una columna de nombres y otra de XP, con o sin cabecera y en cualquier orden.\n"
                     "Comparte la hoja como 'Cualquier persona con el enlace' (lector).").grid(row=1, column=3, sticky="w", padx=(4, 0))
        self._gs_read.append(ttk.Checkbutton(f, text="Reemplazar la tabla local (borra lo que no esté en la hoja)", variable=self.v["gsheet_replace"]))
        self._gs_read[1].grid(row=2, column=0, columnspan=3, sticky="w")

        self._gs_sync = []
        row = 3
        if settings_mod.ENABLE_SHEET_SYNC:
            ttk.Label(f, text="Sincronizar", font=(FONT, 9, "bold")).grid(row=3, column=0, sticky="w", pady=(10, 0))
            ttk.Label(f, text="URL de Apps Script (/exec)").grid(row=4, column=0, sticky="w", pady=2)
            self._gs_sync = [ttk.Entry(f, textvariable=self.v["gsheet_script_url"], width=46)]
            self._gs_sync[0].grid(row=4, column=1, columnspan=2, sticky="w")
            ttk.Label(f, text="Token").grid(row=5, column=0, sticky="w", pady=2)
            self._gs_sync.append(ttk.Entry(f, textvariable=self.v["gsheet_token"], width=24, show="•"))
            self._gs_sync[1].grid(row=5, column=1, sticky="w")
            self._gs_sync.append(ttk.Button(f, text="Copiar código Apps Script", command=self._copy_script))
            self._gs_sync[2].grid(row=6, column=0, sticky="w", pady=(4, 0))
            info_icon(f, "1) Copia el código y pégalo en tu hoja: Extensiones > Apps Script.\n2) Cambia TOKEN y escríbelo aquí.\n"
                         "3) Implementar > Nueva implementación > Aplicación web (Ejecutar como: Yo · Acceso: Cualquier usuario).\n"
                         "4) Pega aquí la URL que termina en /exec.").grid(row=6, column=1, sticky="w", padx=(4, 0))
            row = 7

        ttk.Checkbutton(f, text="Actualizar al iniciar la aplicación", variable=self.v["gsheet_on_start"]).grid(row=row, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Button(f, text="Probar conexión", command=self._test_gsheets).grid(row=row + 1, column=0, sticky="w", pady=(6, 0))
        self.gs_info = ttk.Label(f, foreground="#555")
        self.gs_info.grid(row=row + 2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self._update_sheet_fields()
        self.update_sheet_info()

    def _mode_from_ui(self) -> str:
        label = self.v["gsheet_mode"].get()
        return next((m for m in settings_mod.visible_gsheet_modes() if GSHEET_MODE_LABELS[m] == label), "off")

    def _update_sheet_fields(self) -> None:
        mode = self._mode_from_ui()
        for w in self._gs_read:
            w.state(["!disabled"] if mode == "read" else ["disabled"])
        for w in self._gs_sync:
            w.state(["!disabled"] if mode == "sync" else ["disabled"])

    def update_sheet_info(self) -> None:
        xp, parts = self.app.xp, []
        if xp.last_sync:
            parts.append("Última actualización: " + time.strftime("%d/%m %H:%M", time.localtime(xp.last_sync / 1000)))
        pending = len(xp.pending_ops()) if self.app.settings.effective_gsheet_mode == "sync" else 0
        if pending:
            parts.append(f"{pending} cambios pendientes de subir")
        self.gs_info.config(text="  ·  ".join(parts))

    def _copy_script(self) -> None:
        root = self.app.root
        root.clipboard_clear()
        root.clipboard_append(apps_script_source())
        self.app.status.set("Código de Apps Script copiado al portapapeles.")

    def _validate_general(self) -> tuple[dict, list[str]]:
        errors, vals = [], {}
        hotkey = self.v["hotkey"].get().strip().lower()
        try:
            parse_hotkey(hotkey)
            vals["hotkey"] = hotkey
        except HotkeyError as e:
            errors.append(f"Atajo de teclado: {e}")
        try:
            vals["overlay_seconds"] = max(1.0, self._num("overlay_seconds"))
        except ValueError:
            errors.append("La duración de la alerta debe ser un número")
        vals.update(
            overlay_position=self.v["overlay_position"].get(),
            lang=next((c for c, label in LANG_LABELS.items() if label == self.v["lang"].get()), "es"),
            sound=self.v["sound"].get(), use_dofusdb=self.v["use_dofusdb"].get(), debug=self.v["debug"].get(),
        )
        return vals, errors

    def _validate_profit(self) -> tuple[dict, list[str]]:
        try:
            price, xp, margin = self._num("cookie_price"), self._num("cookie_xp"), self._num("margin_pct")
        except ValueError:
            return {}, ["Galleta: introduce números válidos"]
        errors = []
        if price <= 0 or xp <= 0:
            errors.append("El precio y la XP de la galleta deben ser mayores que 0")
        if not 0 <= margin < 100:
            errors.append("El margen debe estar entre 0 y 100 %")
        return {"cookie_price": price, "cookie_xp": xp, "margin_pct": margin}, errors

    def _validate_gsheets(self) -> tuple[dict, list[str]]:
        mode = resolve_saved_gsheet_mode(self._mode_from_ui(), self.app.settings.gsheet_mode)
        url, script = self.v["gsheet_url"].get().strip(), self.v["gsheet_script_url"].get().strip()
        errors = []
        if settings_mod.effective_gsheet_mode(mode) == "read" and not parse_sheet_url(url):
            errors.append("Google Sheets: pega el enlace de la hoja")
        if settings_mod.ENABLE_SHEET_SYNC and mode == "sync" and not script:
            errors.append("Google Sheets: pega la URL de la aplicación web de Apps Script (/exec)")
        return {"gsheet_mode": mode, "gsheet_url": url, "gsheet_script_url": script,
                "gsheet_replace": self.v["gsheet_replace"].get(), "gsheet_token": self.v["gsheet_token"].get().strip(),
                "gsheet_on_start": self.v["gsheet_on_start"].get()}, errors

    def _apply_gsheets(self, vals: dict) -> bool:
        """Put the sheet values into settings; True if the sheet target changed."""
        s = self.app.settings
        target = (vals["gsheet_mode"], vals["gsheet_url"], vals["gsheet_script_url"])
        changed = target != (s.gsheet_mode, s.gsheet_url, s.gsheet_script_url)
        if changed:
            self.app.sheets.target_changed(vals["gsheet_mode"], s.gsheet_script_url, vals["gsheet_script_url"])
        for k, val in vals.items():
            setattr(s, k, val)
        return changed

    def _sheet_settings_saved(self) -> None:
        self.app.update_refresh_tooltip()
        self.update_sheet_info()
        self._update_sheet_fields()

    def save(self) -> bool:
        """Validate every section; save all or nothing. True when saved."""
        results = {"general": self._validate_general(), "galleta": self._validate_profit(),
                   "gsheets": self._validate_gsheets()}
        errors = [e for _, errs in results.values() for e in errs]
        if errors:
            for key, (_, errs) in results.items():
                if errs:
                    self.sections[key].expand()
            messagebox.showerror("DofusPetMerch", "No se ha guardado nada:\n\n• " + "\n• ".join(errors), parent=self.win)
            return False
        app, s = self.app, self.app.settings
        general = results["general"][0]
        hotkey_changed = general["hotkey"] != s.hotkey
        icons_changed = general["use_dofusdb"] != s.use_dofusdb or general["lang"] != s.lang
        for k, val in {**general, **results["galleta"][0]}.items():
            setattr(s, k, val)
        sheet_changed = self._apply_gsheets(results["gsheets"][0])
        s.save()
        self._load_vars()  # normalised values (lower-case hotkey...)
        self._saved = self._snapshot()
        if icons_changed:
            app.panel.table_replaced(list(app.xp.entries))
        else:
            app.panel.refresh()
        self._sheet_settings_saved()
        if hotkey_changed or app.hotkey is None:
            app.register_hotkey()  # sets its own status message
        else:
            app.status.set("Ajustes guardados.")
        app.sheets.settings_saved(sheet_changed)
        return True

    def _test_gsheets(self) -> None:
        """Save only the Google Sheets section, then test the connection."""
        vals, errors = self._validate_gsheets()
        if errors:
            messagebox.showerror("DofusPetMerch", "\n".join(errors), parent=self.win)
            return
        changed = self._apply_gsheets(vals)
        self.app.settings.save()
        self.show_saved(*vals)
        self._sheet_settings_saved()
        self.app.sheets.test_connection(target_changed=changed)
