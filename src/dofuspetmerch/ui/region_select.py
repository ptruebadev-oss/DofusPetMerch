"""Screen region selection like Win+Shift+S: a frozen, dimmed screenshot of every monitor
on which the user drags a rectangle. Esc or right click cancels.

One borderless window per monitor (a single window spanning monitors of different sizes or
with a negative origin is not placed reliably by Windows); they all show the same image.
"""
from __future__ import annotations

import ctypes
import tkinter as tk
from typing import Callable

import numpy as np

from ..reading.capture import normalize_rect
from .images import screen_photo

DIM = 0.55  # brightness of the frozen screen outside the selection
OUTLINE = "#4ade80"

Rect = tuple[int, int, int, int]

_user32 = ctypes.windll.user32
_user32.GetParent.restype = ctypes.c_void_p
_user32.GetParent.argtypes = [ctypes.c_void_p]
_user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p] + [ctypes.c_int] * 4 + [ctypes.c_uint]
HWND_TOPMOST, SWP_NOACTIVATE = ctypes.c_void_p(-1), 0x0010


def _place(win: tk.Toplevel, rect: Rect) -> None:
    """Put one of our own windows exactly over ``rect``. Tk's geometry misplaces windows on
    monitors that are taller than the primary one or have a negative origin."""
    win.update_idletasks()
    hwnd = _user32.GetParent(win.winfo_id()) or win.winfo_id()
    x, y, w, h = rect
    _user32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE)


class RegionSelector:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.wins: list[tk.Toplevel] = []
        self._on_done = None

    def select(self, img: np.ndarray, rect: Rect, monitors: list[Rect],
               on_done: Callable[[Rect | None], None]) -> None:
        """Show ``img`` (BGR, covering screen ``rect``) and call ``on_done`` once with the chosen
        screen rect (x, y, w, h), or None if cancelled."""
        self._rect, self._on_done, self._p0 = rect, on_done, None
        self._full = screen_photo(self.root, img)
        self._dim = screen_photo(self.root, img, DIM)
        self._crop = tk.PhotoImage(master=self.root)
        self._items = []  # (canvas, lit image item, outline item, monitor)
        vx, vy = rect[0], rect[1]
        for m in monitors or [rect]:
            mx, my, mw, mh = m
            w = tk.Toplevel(self.root)
            w.title("DofusPetMerch selección")
            w.overrideredirect(True)
            w.attributes("-topmost", True)
            w.geometry(f"{mw}x{mh}{mx:+d}{my:+d}")
            c = tk.Canvas(w, width=mw, height=mh, highlightthickness=0, cursor="crosshair", bd=0)
            c.pack()
            # The shared image is placed so this monitor's part lands on the canvas (the rest is clipped).
            c.create_image(vx - mx, vy - my, image=self._dim, anchor="nw")
            lit = c.create_image(0, 0, image=self._crop, anchor="nw", state="hidden")
            box = c.create_rectangle(0, 0, 0, 0, outline=OUTLINE, width=2, state="hidden")
            c.bind("<ButtonPress-1>", self._press)
            c.bind("<B1-Motion>", self._drag)
            c.bind("<ButtonRelease-1>", self._release)
            c.bind("<ButtonPress-3>", lambda _e: self._finish(None))
            w.bind("<Escape>", lambda _e: self._finish(None))
            self.wins.append(w)
            self._items.append((c, lit, box, m))
        self.root.update_idletasks()
        for w, (_c, _lit, _box, m) in zip(self.wins, self._items):
            _place(w, m)
            w.lift()
        self.wins[0].focus_force()

    def _press(self, e) -> None:
        self._p0 = (e.x_root, e.y_root)  # screen coordinates (physical px: the process is DPI aware)
        e.widget.focus_set()

    def _drag(self, e) -> None:
        if self._p0 is None:
            return
        vx, vy, vw, vh = self._rect
        (x0, y0), (x1, y1) = self._p0, (e.x_root, e.y_root)
        # Selection in screen coordinates, clamped to the screenshot.
        l, t = max(min(x0, x1), vx), max(min(y0, y1), vy)
        r, b = min(max(x0, x1), vx + vw), min(max(y0, y1), vy + vh)
        if r - l <= 0 or b - t <= 0:
            return
        self._crop.configure(width=r - l, height=b - t)
        self._crop.tk.call(self._crop, "copy", str(self._full), "-from", l - vx, t - vy, r - vx, b - vy, "-to", 0, 0)
        for c, lit, box, (mx, my, _mw, _mh) in self._items:
            c.coords(lit, l - mx, t - my)
            c.coords(box, l - mx, t - my, r - mx, b - my)
            c.itemconfigure(lit, state="normal")
            c.itemconfigure(box, state="normal")

    def _release(self, e) -> None:
        if self._p0 is None:
            return
        self._finish(normalize_rect(self._p0, (e.x_root, e.y_root), self._rect))

    def cancel(self) -> bool:
        """Close everything as if cancelled. False if ``on_done`` had already run (or never set)."""
        pending = self._on_done is not None
        self._finish(None)
        return pending

    def _finish(self, region: Rect | None) -> None:
        on_done, self._on_done = self._on_done, None
        for w in self.wins:
            try:
                w.destroy()
            except tk.TclError:
                pass
        self.wins = []
        self._full = self._dim = self._crop = None
        if on_done:
            on_done(region)
