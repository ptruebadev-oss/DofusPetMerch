"""System-wide hotkey via RegisterHotKey (no keyboard hooks, no admin rights).

Windows delivers WM_HOTKEY to the thread that registered it, so the hotkey lives
on its own thread with a tiny message loop.
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012

_MODS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT, "win": MOD_WIN}
_NAMED = {
    "space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "insert": 0x2D, "delete": 0x2E,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22, "pause": 0x13,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "printscreen": 0x2C,
    **{f"num{i}": 0x60 + i for i in range(10)},
    **{f"f{i}": 0x6F + i for i in range(1, 25)},
}


class HotkeyError(ValueError):
    pass


def parse_hotkey(spec: str) -> tuple[int, int]:
    """'ctrl+alt+d' -> (modifiers, virtual key code)."""
    parts = [p.strip().lower() for p in spec.replace("-", "+").split("+") if p.strip()]
    if not parts:
        raise HotkeyError("Atajo vacío")
    mods, key = 0, None
    for p in parts:
        if p in _MODS:
            mods |= _MODS[p]
        elif key is not None:
            raise HotkeyError(f"Solo se permite una tecla además de los modificadores: '{spec}'")
        elif p in _NAMED:
            key = _NAMED[p]
        elif len(p) == 1 and p.isalnum():
            key = ord(p.upper())
        else:
            raise HotkeyError(f"Tecla desconocida: '{p}'")
    if key is None:
        raise HotkeyError("Falta la tecla principal: añade una letra, un número o una tecla F después de ctrl/alt/shift")
    return mods, key


class GlobalHotkey:
    def __init__(self, spec: str, callback: Callable[[], None]):
        self.mods, self.vk = parse_hotkey(spec)
        self.spec = spec
        self.callback = callback
        self._tid = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Register the hotkey; raises HotkeyError if Windows refuses (already in use)."""
        ready = threading.Event()
        result: dict = {}

        def loop():
            self._tid = kernel32.GetCurrentThreadId()
            ok = user32.RegisterHotKey(None, 1, self.mods | MOD_NOREPEAT, self.vk)
            result["ok"] = bool(ok)
            ready.set()
            if not ok:
                return
            msg = wintypes.MSG()
            try:
                while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                    if msg.message == WM_HOTKEY:
                        try:
                            self.callback()
                        except Exception:  # never kill the hotkey thread
                            pass
            finally:
                user32.UnregisterHotKey(None, 1)

        self._thread = threading.Thread(target=loop, name="hotkey", daemon=True)
        self._thread.start()
        ready.wait(2)
        if not result.get("ok"):
            raise HotkeyError(f"No se pudo registrar el atajo '{self.spec}' (¿lo usa otra aplicación?)")

    def stop(self) -> None:
        if self._thread and self._thread.is_alive() and self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._thread.join(1)
        self._thread = None
