"""Small always-on-top, click-through result panel that hides itself after a few seconds."""
from __future__ import annotations

import ctypes
import tkinter as tk

from ..analysis import Analysis
from ..parsing import format_kamas, format_unit, format_xp
from .images import photo, photo_from_file
from .widgets import FONT

BG, FG, MUTED = "#1b1e2b", "#e8e8f0", "#9aa0b4"
GREEN, RED, GOLD = "#4ade80", "#f87171", "#f5c542"

GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80000, 0x20, 0x80, 0x08000000


class Overlay:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.win: tk.Toplevel | None = None
        self._hide_job = None
        self._img = None

    def hide(self) -> None:
        if self._hide_job:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None
        if self.win is not None:
            self.win.destroy()
            self.win = None

    def show(self, data: Analysis, anchor: tuple[int, int, int, int], position: str, seconds: float) -> None:
        self.hide()
        w = tk.Toplevel(self.root, bg=BG)
        w.title("DofusPetMerch overlay")
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.attributes("-alpha", 0.93)
        self.win = w
        frame = tk.Frame(w, bg=BG, padx=12, pady=10, highlightthickness=1, highlightbackground="#3a3f55")
        frame.pack()
        self._build(frame, data)

        w.update_idletasks()
        ww, wh = w.winfo_reqwidth(), w.winfo_reqheight()
        ax, ay, aw, ah = anchor
        m = 16
        pos = {
            "arriba-derecha": (ax + aw - ww - m, ay + m),
            "arriba-izquierda": (ax + m, ay + m),
            "abajo-derecha": (ax + aw - ww - m, ay + ah - wh - m),
            "abajo-izquierda": (ax + m, ay + ah - wh - m),
            "centro": (ax + (aw - ww) // 2, ay + (ah - wh) // 2),
        }[position]
        w.geometry(f"+{int(pos[0])}+{int(pos[1])}")
        w.update_idletasks()
        self._click_through(w)
        self._hide_job = self.root.after(int(seconds * 1000), self.hide)

    @staticmethod
    def _click_through(w: tk.Toplevel) -> None:
        try:
            hwnd = int(w.wm_frame(), 16)
            u = ctypes.windll.user32
            style = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
            u.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        except Exception:
            pass

    def _build(self, f: tk.Frame, d: Analysis) -> None:
        def label(parent, text, fg=FG, size=10, bold=False, **grid):
            l = tk.Label(parent, text=text, fg=fg, bg=BG, font=(FONT, size, "bold" if bold else "normal"))
            l.grid(**grid) if grid else l.pack(anchor="w")
            return l

        if d.error:
            label(f, "DofusPetMerch", MUTED, 9)
            label(f, d.error, RED, 11, True)
            for wmsg in d.warnings:
                label(f, wmsg, MUTED, 9)
            return

        head = tk.Frame(f, bg=BG)
        head.pack(anchor="w", fill="x")
        self._img = photo_from_file(self.root, d.icon_file, 44, BG) or photo(self.root, d.icon_bgr, 44, BG)
        if self._img:
            tk.Label(head, image=self._img, bg=BG).pack(side="left", padx=(0, 8))
        info = tk.Frame(head, bg=BG)
        info.pack(side="left")
        label(info, d.name or "¿?", FG, 13, True)
        if d.item_xp is not None:
            label(info, f"{format_xp(d.item_xp)} XP/u", MUTED, 9)

        if d.max_unit is None:
            label(f, "XP desconocida: añádela en la tabla XP", GOLD, 10, True)
        else:
            color = GREEN if d.any_profitable else RED
            verdict = "¡RENTABLE!" if d.any_profitable else "No rentable"
            label(f, f"{verdict}  ·  Máx. {format_unit(d.max_unit)} K/u", color, 13, True)

        t = tk.Frame(f, bg=BG)
        t.pack(anchor="w", pady=(6, 0))
        hdr = ["Lote", "Precio", "K/u", "Máx lote", ""] if d.evals else ["Lote", "Precio", "K/u"]
        for c, h in enumerate(hdr):
            label(t, h, MUTED, 9, row=0, column=c, sticky="e", padx=5)
        if d.evals:
            for r, e in enumerate(d.evals, 1):
                col = GREEN if e.profitable else RED
                vals = [format_kamas(e.lot), format_kamas(e.price), format_unit(e.unit_price),
                        format_kamas(e.max_lot_price), "✔" if e.profitable else "✘"]
                for c, v in enumerate(vals):
                    label(t, v, col if c in (2, 4) else FG, 10, c == 4, row=r, column=c, sticky="e", padx=5)
        else:
            for r, (lot, price) in enumerate(d.rows, 1):
                for c, v in enumerate([format_kamas(lot), format_kamas(price), format_unit(price / lot)]):
                    label(t, v, FG, 10, row=r, column=c, sticky="e", padx=5)
        if not d.rows and not d.evals:
            label(f, "No se leyó ningún lote", RED, 10)
        for wmsg in d.warnings:
            label(f, "⚠ " + wmsg, GOLD, 8)
