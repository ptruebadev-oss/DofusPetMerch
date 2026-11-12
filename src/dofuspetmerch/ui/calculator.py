"""Cookie calculator window: maximum price of the cookie from the price of a pet at level 1 and 100."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from ..parsing import format_kamas, format_number, parse_number
from ..profit import COOKIES_PER_PET, cookie_max_price
from .widgets import FONT, entry_rows, info_icon

if TYPE_CHECKING:
    from .app import App


class Calculator:
    """Single instance; pet prices are remembered (saved settings) when valid."""

    def __init__(self, app: "App"):
        self.app = app
        self.win: tk.Toplevel | None = None

    def open(self, near: tk.Misc | None = None) -> None:
        """Show the calculator to the right of ``near`` (the main window by default)."""
        near = near or self.app.root
        if self.win is not None:
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()
            return
        app, s = self.app, self.app.settings
        w = self.win = tk.Toplevel(app.root)
        w.title("DofusPetMerch · Calculadora galleta")
        w.transient(app.root)
        w.resizable(False, False)
        w.protocol("WM_DELETE_WINDOW", self.close)
        w.bind("<Escape>", lambda _e: self.close())
        self.v = {"pet_price_100": tk.StringVar(value=format_number(s.pet_price_100)),
                  "pet_price_1": tk.StringVar(value=format_number(s.pet_price_1))}
        f = ttk.Frame(w, padding=12)
        f.pack(fill="both", expand=True)
        row = entry_rows(f, self.v, [("Mascota nvl. 100", "pet_price_100", "K"),
                                     ("Mascota nvl. 1", "pet_price_1", "K")])
        res = ttk.Frame(f)
        res.grid(row=row, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self.result = ttk.Label(res, font=(FONT, 11, "bold"))
        self.result.pack(side="left")
        info_icon(res, f"Precio máximo por galleta = (precio nivel 100 − precio nivel 1) / {COOKIES_PER_PET} "
                       f"galletas para subir de 1 a 100.\nSe redondea hacia abajo. El margen de la sección "
                       f"Galleta se aplica después.").pack(side="left", padx=(4, 0))
        self.use_btn = ttk.Button(f, text="Usar este valor", command=self._use_price)
        self.use_btn.grid(row=row + 1, column=0, columnspan=3, pady=(10, 0))  # centred
        for var in self.v.values():
            var.trace_add("write", lambda *_: self._update())
        self._update()
        w.update_idletasks()
        w.geometry(f"+{near.winfo_rootx() + near.winfo_width() + 12}+{near.winfo_rooty()}")
        w.focus_force()

    def _prices(self) -> tuple[float, float] | None:
        p100 = parse_number(self.v["pet_price_100"].get())
        p1 = parse_number(self.v["pet_price_1"].get())
        if p100 is None or p1 is None or cookie_max_price(p100, p1) is None:
            return None
        return p100, p1

    def _update(self) -> None:
        prices = self._prices()
        if prices is None:
            self.result.config(text="Precio máximo: valores no válidos")
            self.use_btn.state(["disabled"])
        else:
            self.result.config(text=f"Precio máximo: {format_kamas(cookie_max_price(*prices))} K / galleta")
            self.use_btn.state(["!disabled"])

    def _store_pet_prices(self) -> bool:
        """Put valid pet prices into the (saved-only) settings; nothing else is touched."""
        prices = self._prices()
        if prices is None:
            return False
        self.app.settings.pet_price_100, self.app.settings.pet_price_1 = prices
        return True

    def _use_price(self) -> None:
        prices = self._prices()
        if prices is None:
            return
        price = cookie_max_price(*prices)
        s = self.app.settings
        self._store_pet_prices()
        s.cookie_price = float(price)
        s.save()
        self.app.settings_window.show_saved("cookie_price")
        self.app.status.set(f"Precio de la galleta actualizado a {format_kamas(price)} K.")

    def close(self) -> None:
        """Also called when the app quits with the calculator open."""
        if self.win is None:
            return
        if self._store_pet_prices():
            self.app.settings.save()
        self.win.destroy()
        self.win = None
