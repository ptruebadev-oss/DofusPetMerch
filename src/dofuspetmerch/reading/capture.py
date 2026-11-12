"""Passive screen capture of the Dofus window.

Only uses window enumeration, window titles and window rectangles (user32) plus a
plain screen grab (mss / BitBlt of the desktop). It never opens the game process,
reads its memory or sends it any input.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

import mss
import numpy as np

user32 = ctypes.WinDLL("user32", use_last_error=True)

_EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [_EnumWindowsProc, wintypes.LPARAM]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]

OWN_TITLES = ("dofuspetmerch",)
_MSS = getattr(mss, "MSS", None) or mss.mss


def enable_dpi_awareness() -> None:
    """Make window rects and screen pixels use the same (physical) coordinates."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware
    except (AttributeError, OSError):
        try:
            user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def window_title(hwnd) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _matches(hwnd, needle: str) -> bool:
    if not hwnd or not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
        return False
    t = window_title(hwnd).lower()
    return needle.lower() in t and not any(o in t for o in OWN_TITLES)


def find_game_window(title_substr: str = "Dofus"):
    """Prefer the foreground window (the user pressed the hotkey while playing)."""
    fg = user32.GetForegroundWindow()
    if _matches(fg, title_substr):
        return fg
    found = []

    def cb(hwnd, _):
        if _matches(hwnd, title_substr):
            found.append(hwnd)
        return True

    user32.EnumWindows(_EnumWindowsProc(cb), 0)
    return found[0] if found else None


def client_rect_on_screen(hwnd) -> tuple[int, int, int, int]:
    rc = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rc))
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, rc.right - rc.left, rc.bottom - rc.top


def _monitor_under_cursor(sct) -> dict:
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    for m in sct.monitors[1:]:
        if m["left"] <= pt.x < m["left"] + m["width"] and m["top"] <= pt.y < m["top"] + m["height"]:
            return m
    return sct.monitors[1]


def capture(title_substr: str = "Dofus") -> tuple[np.ndarray, tuple[int, int, int, int], str]:
    """Return (BGR image, screen rect (x, y, w, h), description of the source)."""
    hwnd = find_game_window(title_substr)
    with _MSS() as sct:
        if hwnd:
            x, y, w, h = client_rect_on_screen(hwnd)
            if w > 50 and h > 50:
                shot = sct.grab({"left": x, "top": y, "width": w, "height": h})
                return np.asarray(shot)[:, :, :3].copy(), (x, y, w, h), f"ventana '{window_title(hwnd)}'"
        m = _monitor_under_cursor(sct)
        shot = sct.grab(m)
        return np.asarray(shot)[:, :, :3].copy(), (m["left"], m["top"], m["width"], m["height"]), "pantalla (no se encontró la ventana de Dofus)"


MIN_REGION = 40  # px: smaller drags are treated as a click (cancel)


def grab_virtual_screen() -> tuple[np.ndarray, tuple[int, int, int, int], list[tuple[int, int, int, int]]]:
    """Every monitor in one BGR image, with its screen rect (x, y, w, h) (x/y can be negative)
    and the rect of each monitor."""
    with _MSS() as sct:
        m = sct.monitors[0]
        shot = sct.grab(m)
        monitors = [(d["left"], d["top"], d["width"], d["height"]) for d in sct.monitors[1:]]
        return np.asarray(shot)[:, :, :3].copy(), (m["left"], m["top"], m["width"], m["height"]), monitors


def normalize_rect(p0: tuple[int, int], p1: tuple[int, int], bounds: tuple[int, int, int, int],
                   min_size: int = MIN_REGION) -> tuple[int, int, int, int] | None:
    """Rect (x, y, w, h) between two dragged corners, clamped to ``bounds`` (x, y, w, h).
    None if it is smaller than ``min_size`` on either side."""
    bx, by, bw, bh = bounds
    x0, x1 = sorted((min(max(p0[0], bx), bx + bw), min(max(p1[0], bx), bx + bw)))
    y0, y1 = sorted((min(max(p0[1], by), by + bh), min(max(p1[1], by), by + bh)))
    if x1 - x0 < min_size or y1 - y0 < min_size:
        return None
    return x0, y0, x1 - x0, y1 - y0
