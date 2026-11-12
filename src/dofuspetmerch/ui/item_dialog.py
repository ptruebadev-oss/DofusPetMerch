"""Small modal window to add an item to the XP table or update one."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, Callable

from ..parsing import format_xp, parse_xp
from .images import icon_states
from .widgets import Tooltip

if TYPE_CHECKING:
    from .app import App


class ItemDialog:
    """``on_save(old_name, name, xp) -> bool`` stores the item; ``old_name`` is the row being
    updated ("" when adding). The window closes when it returns True."""

    def __init__(self, app: "App", on_save: Callable[[str, str, float], bool], name: str = "", xp: float | None = None):
        self.app, self._on_save, self._old = app, on_save, name
        title = "Actualizar" if name else "Añadir"
        w = self.win = tk.Toplevel(app.root)
        w.title(title)
        w.resizable(False, False)
        w.transient(app.root)
        f = ttk.Frame(w, padding=12)
        f.pack(fill="both", expand=True)
        self.v_name = tk.StringVar(value=name)
        self.v_xp = tk.StringVar(value=format_xp(xp) if xp is not None else "")
        ttk.Label(f, text="Objeto").grid(row=0, column=0, sticky="w")
        row = ttk.Frame(f)
        row.grid(row=1, column=0, sticky="we")
        self.name_entry = ttk.Entry(row, textvariable=self.v_name, width=30)
        self.name_entry.pack(side="left")
        self._last_img = icon_states(w, "arrow_up", 14)
        last = ttk.Button(row, image=self._last_img, command=self._use_last)
        last.pack(side="left", padx=(4, 0))
        # Enabled once there is a last item (re-checked on hover: a read can happen meanwhile).
        last.bind("<Enter>", lambda _e: last.state(["!disabled" if app.last_item() else "disabled"]), add="+")
        last.state(["!disabled" if app.last_item() else "disabled"])
        Tooltip(last, "Actualizar último objeto")
        ttk.Label(f, text="XP / unidad").grid(row=2, column=0, sticky="w", pady=(8, 0))
        xp_entry = ttk.Entry(f, textvariable=self.v_xp, width=12)
        xp_entry.grid(row=3, column=0, sticky="w")
        b = ttk.Frame(f)
        b.grid(row=4, column=0, sticky="e", pady=(12, 0))
        ttk.Button(b, text=title, command=self._save).pack(side="left")
        ttk.Button(b, text="Cancelar", command=self.close).pack(side="left", padx=(6, 0))
        w.bind("<Return>", lambda _e: self._save())
        w.bind("<Escape>", lambda _e: self.close())
        w.protocol("WM_DELETE_WINDOW", self.close)
        w.update_idletasks()
        x = app.root.winfo_rootx() + (app.root.winfo_width() - w.winfo_reqwidth()) // 2
        y = app.root.winfo_rooty() + 60
        w.geometry(f"+{x}+{y}")
        (xp_entry if name else self.name_entry).focus_set()
        try:
            w.grab_set()
        except tk.TclError:
            pass

    def _use_last(self) -> None:
        name = self.app.last_item()
        if not name:
            return
        hit = self.app.xp.lookup(name)
        self.v_name.set(hit[0] if hit else name)
        if hit:
            self.v_xp.set(format_xp(hit[1]))

    def _save(self) -> None:
        name = self.v_name.get().strip()
        xp = parse_xp(self.v_xp.get())
        if not name or xp is None:
            messagebox.showerror("DofusPetMerch", "Introduce un nombre y una XP mayor que 0.", parent=self.win)
            return
        if self._on_save(self._old, name, xp):
            self.close()

    def close(self) -> None:
        try:
            self.win.grab_release()
            self.win.destroy()
        except tk.TclError:
            pass
