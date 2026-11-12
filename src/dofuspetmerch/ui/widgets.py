"""Small reusable Tk widgets."""
from __future__ import annotations

import ctypes
import tkinter as tk
from ctypes import wintypes
from tkinter import ttk

FONT = "Segoe UI"


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


def _monitor_bottom(x: int, y: int) -> int:
    """Bottom of the work area (above the taskbar) of the monitor containing screen point x, y."""
    try:
        user32 = ctypes.windll.user32
        user32.MonitorFromPoint.restype = ctypes.c_void_p
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MonitorInfo)]
        mon = user32.MonitorFromPoint(wintypes.POINT(x, y), 2)  # MONITOR_DEFAULTTONEAREST
        info = _MonitorInfo(cbSize=ctypes.sizeof(_MonitorInfo))
        if mon and user32.GetMonitorInfoW(mon, ctypes.byref(info)):
            return info.rcWork.bottom
    except (AttributeError, OSError):
        pass
    return 1 << 30  # unknown: never flip


class Tooltip:
    """Small Windows-style hint shown just below the mouse pointer (so it never covers the
    neighbouring buttons) after a short pause over the widget."""

    DELAY_MS = 450
    OFFSET = (2, 22)  # px from the pointer: below the cursor arrow

    def __init__(self, widget: tk.Widget, text: str, width: int = 320):
        self.widget, self.text, self.width = widget, text, width
        self.tip: tk.Toplevel | None = None
        self._job = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        # Also close it if the widget disappears under the mouse (section collapsed, window hidden).
        widget.bind("<Unmap>", self._hide, add="+")
        widget.bind("<Destroy>", self._hide, add="+")
        widget.winfo_toplevel().bind("<Unmap>", self._hide, add="+")

    def _schedule(self, _e=None) -> None:
        self._cancel()
        self._job = self.widget.after(self.DELAY_MS, self._show)

    def _cancel(self) -> None:
        if self._job:
            try:
                self.widget.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def _show(self) -> None:
        self._job = None
        if self.tip or not self.text.strip():
            return
        try:
            px, py = self.widget.winfo_pointerxy()
        except tk.TclError:
            return
        self.tip = tk.Toplevel(self.widget)
        self.tip.overrideredirect(True)
        self.tip.attributes("-topmost", True)
        border = tk.Frame(self.tip, bg="#a0a0a0", padx=1, pady=1)
        border.pack()
        tk.Label(border, text=self.text, justify="left", wraplength=self.width, bg="#ffffff", fg="#1a1a1a",
                 padx=7, pady=3, font=(FONT, 9)).pack()
        self.tip.update_idletasks()
        # Keep it within the app window horizontally; above the pointer if it would leave the screen.
        x = px + self.OFFSET[0]
        top = self.widget.winfo_toplevel()
        left, right = top.winfo_rootx(), top.winfo_rootx() + top.winfo_width()
        x = max(min(x, max(right, px + 40) - self.tip.winfo_reqwidth()), min(left, px))
        y = py + self.OFFSET[1]
        if y + self.tip.winfo_reqheight() > _monitor_bottom(px, py):
            y = py - 8 - self.tip.winfo_reqheight()
        self.tip.geometry(f"{x:+d}{y:+d}")

    def _hide(self, _e=None) -> None:
        self._cancel()
        if self.tip:
            self.tip.destroy()
            self.tip = None


def info_icon(parent, text: str) -> ttk.Label:
    """ⓘ with a tooltip: the only place where the UI explains things."""
    info = ttk.Label(parent, text="ⓘ", foreground="#2563eb", cursor="question_arrow", font=(FONT, 11))
    Tooltip(info, text)
    return info


def entry_rows(frame: ttk.Frame, variables: dict, rows: list[tuple]) -> int:
    """'Label | Entry [| unit]' grid rows for (label, variable key[, unit]) tuples.
    Returns the next free row."""
    for i, (label, key, *unit) in enumerate(rows):
        ttk.Label(frame, text=label).grid(row=i, column=0, sticky="w", padx=(0, 8), pady=2)
        cell = ttk.Frame(frame)  # entry and unit together: a wide row below must not push the unit away
        cell.grid(row=i, column=1, sticky="w", pady=2)
        ttk.Entry(cell, textvariable=variables[key], width=18).pack(side="left")
        if unit:
            ttk.Label(cell, text=unit[0]).pack(side="left", padx=(4, 0))
    return len(rows)


class Collapsible(ttk.Frame):
    """Section with a clickable header (▾ open / ▸ closed) that shows or hides ``body``."""

    def __init__(self, parent, key: str, title: str, expanded: bool = True, on_toggle=None):
        super().__init__(parent)
        self.key, self.title, self.on_toggle = key, title, on_toggle
        self.header = ttk.Label(self, cursor="hand2", font=(FONT, 10, "bold"))
        self.header.pack(fill="x")
        ttk.Separator(self).pack(fill="x", pady=(2, 4))
        self.body = ttk.Frame(self, padding=(14, 0, 0, 4))
        self.expanded = not expanded
        self._set(expanded)
        self.header.bind("<Button-1>", lambda _e: self.toggle())

    def _set(self, expanded: bool) -> None:
        if expanded == self.expanded:
            return
        self.expanded = expanded
        self.header.config(text=("▾  " if expanded else "▸  ") + self.title)
        if expanded:
            self.body.pack(fill="x")
        else:
            self.body.pack_forget()

    def toggle(self) -> None:
        self._set(not self.expanded)
        if self.on_toggle:
            self.on_toggle()

    def expand(self) -> None:
        if not self.expanded:
            self.toggle()
