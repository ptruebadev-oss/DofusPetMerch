"""Main window body: the pet-XP table and its actions (add, update, delete, reload, copy)."""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, Callable

from .. import items
from ..parsing import format_unit, format_xp, normalize_name
from ..profit import max_unit_price
from ..sheets.layout import table_tsv
from ..xptable import XpTable, table_view
from .images import icon, photo_from_file
from .item_dialog import ItemDialog

if TYPE_CHECKING:
    from .app import App

COLUMN_LINE = "#e3e3e3"
HEADINGS = {"#0": "Objeto", "xp": "XP / unidad", "max": "Máx. rentable (K/u)"}
SORT_BY = {"#0": "name", "xp": "xp", "max": "xp"}  # tree column -> table_view column


class XpPanel:
    def __init__(self, parent: ttk.Frame, app: "App", factor: Callable[[], float | None]):
        """``factor``: kamas per XP point to show the maximum price with (None if unknown)."""
        self.app, self._factor = app, factor
        self._icons: dict = {}  # normalized name -> PhotoImage | None
        self._blank_icon = tk.PhotoImage(master=app.root, width=24, height=24)  # keeps names aligned
        self._sort_col, self._sort_desc = "#0", False
        self._build_search(parent)
        ttk.Style(app.root).configure("Treeview", rowheight=30)
        self.tree = ttk.Treeview(parent, columns=("xp", "max"), height=12)
        for col in HEADINGS:  # click a header to sort by it; again to reverse
            self.tree.heading(col, command=lambda c=col: self._sort_by(c))
        self._update_headings()
        self.tree.column("#0", width=220)
        self.tree.column("xp", width=90, anchor="e")
        self.tree.column("max", width=130, anchor="e")
        self.tree.grid(row=1, column=0, sticky="nsew")
        bar = ttk.Scrollbar(parent, orient="vertical", command=self.tree.yview)
        bar.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=bar.set)
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)
        # Treeview has no grid lines: thin light lines placed over the column borders.
        self._col_lines = [tk.Frame(self.tree, bg=COLUMN_LINE, width=1) for _ in range(2)]
        for ev in ("<Configure>", "<ButtonRelease-1>", "<B1-Motion>"):
            self.tree.bind(ev, lambda _e: self.tree.after_idle(self._place_col_lines), add="+")
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Delete>", lambda _e: self.delete_selected())
        self.refresh()
        self.fetch_icons(list(app.xp.entries))  # backfill official icons in the background

    def _build_search(self, parent: ttk.Frame) -> None:
        row = ttk.Frame(parent)
        row.grid(row=0, column=0, columnspan=2, sticky="we", pady=(0, 6))
        self._search_img, self._clear_img = icon(parent, "search", 16), icon(parent, "clear", 12)
        ttk.Label(row, image=self._search_img).pack(side="left", padx=(2, 4))
        self.v_search = tk.StringVar()
        self.search_entry = ttk.Entry(row, textvariable=self.v_search)
        self.search_entry.pack(side="left", fill="x", expand=True)
        self._clear_btn = ttk.Button(row, image=self._clear_img, command=self.clear_search)
        self.count_lbl = ttk.Label(row, foreground="#666")
        self.count_lbl.pack(side="right", padx=(8, 0))
        self.v_search.trace_add("write", lambda *_: self.refresh())
        self.search_entry.bind("<Escape>", lambda _e: self.clear_search())
        for seq in ("<Control-f>", "<Control-F>"):  # F: with Caps Lock on
            self.app.root.bind(seq, lambda _e: self.focus_search())

    def focus_search(self) -> None:
        self.search_entry.focus_set()
        self.search_entry.select_range(0, "end")

    def clear_search(self) -> None:
        self.v_search.set("")
        self.search_entry.focus_set()

    def _sort_by(self, col: str) -> None:
        if col == self._sort_col:
            self._sort_desc = not self._sort_desc
        else:  # names A→Z first; numbers highest first
            self._sort_col, self._sort_desc = col, col != "#0"
        self._update_headings()
        self.refresh()

    def _update_headings(self) -> None:
        for col, text in HEADINGS.items():
            arrow = (" ▼" if self._sort_desc else " ▲") if col == self._sort_col else ""
            self.tree.heading(col, text=text + arrow)

    def _place_col_lines(self) -> None:
        x = 0
        for line, col in zip(self._col_lines, ("#0", "xp")):
            x += int(self.tree.column(col, "width"))
            line.place(x=x - 1, y=0, relheight=1)

    def refresh(self) -> None:
        """Rebuild the rows with the current search and sort (the selection is cleared)."""
        self.tree.delete(*self.tree.get_children())
        f = self._factor()
        entries = self.app.xp.entries
        query = self.v_search.get()
        rows = table_view(entries, query, SORT_BY[self._sort_col], self._sort_desc)
        filtering = bool(query.strip())
        self.count_lbl.config(text=f"{len(rows)} / {len(entries)}" if filtering else f"{len(entries)}")
        if filtering:
            self._clear_btn.pack(side="left", padx=(4, 0), after=self.search_entry)
        else:
            self._clear_btn.pack_forget()
        for name, xp in rows:
            max_unit = format_unit(max_unit_price(xp, f)) if f else "-"
            self.tree.insert("", "end", iid=name, text=" " + name, image=self._icon(name) or self._blank_icon,
                             values=(format_xp(xp), max_unit))

    def table_replaced(self, new_names: list[str]) -> None:
        """Entries or icon sources changed wholesale: reload every icon, fetch the new ones."""
        self._icons.clear()
        self.refresh()
        self.fetch_icons(new_names)

    def after_read(self, name: str) -> None:
        """After a read: show the (new) icon of ``name`` ("" when nothing was read)."""
        if not name:
            return
        self._icons.pop(normalize_name(name), None)  # a new screen icon may have been saved
        self.refresh()
        hit = self.app.xp.lookup(name)
        if hit:
            self.fetch_icons([hit[0]])

    def refresh_tooltip(self) -> str:
        mode = self.app.settings.effective_gsheet_mode
        return {"read": "Actualizar desde Google Sheets", "sync": "Sincronizar con Google Sheets"}.get(mode, "Recargar tabla")

    def reload(self) -> None:
        """Refresh button: read Google Sheets when configured, otherwise reload pet_xp.json
        (it may have been edited by hand) and the icons."""
        if self.app.settings.effective_gsheet_mode != "off":
            self.app.sheets.run(manual=True)
            return
        if self.app.sheets.busy:
            return
        try:
            table = XpTable.load(self.app.xp.path, strict=True)
        except ValueError as e:  # missing or broken file: keep the table in memory
            self.app.status.set(f"No se pudo recargar la tabla: {e}. Se mantiene la actual.")
            return
        self.app.xp = table
        self.table_replaced(list(self.app.xp.entries))
        self.app.status.set(f"Tabla recargada ({len(self.app.xp.entries)} objetos).")

    def _icon(self, name: str):
        key = normalize_name(name)
        if key not in self._icons:
            s = self.app.settings
            self._icons[key] = photo_from_file(self.app.root, items.resolve_icon(name, s.lang, s.use_dofusdb), 24)
        return self._icons[key]

    def fetch_icons(self, names: list[str]) -> None:
        """Download missing official icons on a worker thread, then refresh the table."""
        s = self.app.settings
        if not s.use_dofusdb:
            return
        lang = s.lang
        missing = [n for n in names if items.official_icon_path(n, lang) is None]
        if not missing:
            return

        def work():
            got = False
            for n in missing:
                info = items.lookup(n, lang, timeout=3.0)
                if info and items.download_icon(info, timeout=3.0):
                    got = True
            if got:
                self.app.after(lambda: self._icons_ready(missing))

        threading.Thread(target=work, name="icons", daemon=True).start()

    def _icons_ready(self, names: list[str]) -> None:
        for n in names:
            self._icons.pop(normalize_name(n), None)
        self.refresh()

    def _on_double_click(self, e) -> None:
        row = self.tree.identify_row(e.y)
        if row and row in self.app.xp.entries:
            self.open_editor(row)

    def open_editor(self, name: str = "") -> None:
        """"Añadir" window, or "Actualizar" for the row ``name``."""
        ItemDialog(self.app, self._save_item, name, self.app.xp.entries.get(name) if name else None)

    def _save_item(self, old: str, name: str, xp: float) -> bool:
        xp_table = self.app.xp
        if self.v_search.get().strip() and not table_view({name: xp}, self.v_search.get()):
            self.v_search.set("")  # otherwise the item just saved would be hidden by the search
        if old and old in xp_table.entries and normalize_name(old) != normalize_name(name):
            xp_table.remove(old)  # renamed
            self._icons.pop(normalize_name(old), None)
        xp_table.set(name, xp)
        xp_table.save()
        self._icons.pop(normalize_name(name), None)
        self.refresh()
        if self.tree.exists(name):
            self.tree.selection_set(name)
            self.tree.see(name)
        self.app.status.set(f"'{name}' guardado: {format_xp(xp)} XP/u")
        self.fetch_icons([name])
        self.app.sheets.schedule()
        return True

    def delete_selected(self) -> None:
        names = [n for n in self.tree.selection() if n in self.app.xp.entries]
        if not names:
            self.app.status.set("Selecciona en la tabla el objeto que quieres eliminar.")
            return
        what = f"'{names[0]}'" if len(names) == 1 else f"{len(names)} objetos"
        if not messagebox.askyesno("DofusPetMerch", f"¿Eliminar {what} de la tabla XP?", parent=self.app.root):
            return
        for name in names:
            self.app.xp.remove(name)
        self.app.xp.save()
        self.refresh()
        self.app.status.set(f"Eliminado: {what}.")
        self.app.sheets.schedule()

    def copy_table(self) -> None:
        """Tab-separated text: pasting it into Google Sheets fills the cells."""
        entries = self.app.xp.entries
        if not entries:
            self.app.status.set("La tabla XP está vacía: no hay nada que copiar.")
            return
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(table_tsv(entries))
        self.app.status.set(f"Tabla copiada ({len(entries)} objetos). Pégala en Google Sheets con Ctrl+V en la celda A1.")
