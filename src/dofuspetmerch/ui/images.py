"""Tk images from numpy images, PNG files and small icons drawn with Pillow."""
from __future__ import annotations

import base64
import io
import math
import tkinter as tk
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageTk

from .. import imgutil


def _photo_png(master, png: bytes) -> tk.PhotoImage:
    return tk.PhotoImage(master=master, data=base64.b64encode(png))


def photo(master, img: np.ndarray | None, size: int, bg: str | None = None) -> tk.PhotoImage | None:
    """size x size Tk image. With ``bg`` ("#rrggbb") transparency is flattened onto that colour,
    otherwise kept. None for an empty or unusable image (an icon is never worth an error)."""
    if img is None or img.size == 0:
        return None
    if bg and img.ndim == 3 and img.shape[2] == 4:
        a = img[:, :, 3:4] / 255.0
        bgr = np.array([int(bg[5:7], 16), int(bg[3:5], 16), int(bg[1:3], 16)], float)
        img = (img[:, :, :3] * a + bgr * (1 - a)).astype(np.uint8)
    try:
        return _photo_png(master, imgutil.png_bytes(imgutil.resize(img, size=(size, size))))
    except (OSError, ValueError, tk.TclError):
        return None


def photo_from_file(master, path: Path | None, size: int, bg: str | None = None) -> tk.PhotoImage | None:
    """Like ``photo`` for a PNG on disk. None if it cannot be read."""
    if not path:
        return None
    return photo(master, imgutil.load(path, keep_alpha=True), size, bg)


def screen_photo(master, img: np.ndarray, brightness: float = 1.0) -> ImageTk.PhotoImage:
    """Full-size Tk image of a BGR screenshot (no PNG round trip: screens can be huge)."""
    im = Image.fromarray(np.ascontiguousarray(img[:, :, ::-1]))
    if brightness != 1.0:
        im = im.point(lambda v: int(v * brightness))
    return ImageTk.PhotoImage(im, master=master)


K = 4  # icons are drawn K times bigger, then downscaled for smooth edges
INK = (60, 64, 72, 255)
ICON_SIZE = 18


def _canvas(size: int):
    im = Image.new("RGBA", (size * K, size * K), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def _finish(im: Image.Image, size: int) -> Image.Image:
    return im.resize((size, size), Image.Resampling.LANCZOS)


def draw_calculator(size: int = ICON_SIZE) -> Image.Image:
    im, d = _canvas(size)
    k = K
    d.rounded_rectangle((2 * k, 0, (size - 2) * k - 1, size * k - 1), radius=3 * k, outline=INK, width=int(1.6 * k))
    d.rectangle((4.5 * k, 2.5 * k, (size - 4.5) * k, 6.5 * k), fill=INK)  # display
    for row in range(3):
        for col in range(3):
            x = (5 + col * 3.2) * k
            y = (9 + row * 2.8) * k
            d.rectangle((x, y, x + 1.8 * k, y + 1.6 * k), fill=INK)  # keys
    return _finish(im, size)


def draw_plus(size: int = ICON_SIZE) -> Image.Image:
    im, d = _canvas(size)
    c, a, t = size * K / 2, size * K * 0.36, 1.2 * K
    d.rectangle((c - a, c - t, c + a, c + t), fill=INK)
    d.rectangle((c - t, c - a, c + t, c + a), fill=INK)
    return _finish(im, size)


def draw_minus(size: int = ICON_SIZE) -> Image.Image:
    im, d = _canvas(size)
    c, a, t = size * K / 2, size * K * 0.36, 1.2 * K
    d.rectangle((c - a, c - t, c + a, c + t), fill=INK)
    return _finish(im, size)


def draw_refresh(size: int = ICON_SIZE) -> Image.Image:
    im, d = _canvas(size)
    s, w = size * K, int(1.8 * K)
    m = s * 0.2
    end = 290  # degrees, clockwise from 3 o'clock; the gap is at the top right
    d.arc((m, m, s - m, s - m), start=10, end=end, fill=INK, width=w)
    r, c, t = (s - 2 * m) / 2, s / 2, math.radians(end)
    x, y = c + r * math.cos(t), c + r * math.sin(t)
    dx, dy = -math.sin(t), math.cos(t)  # clockwise direction
    nx, ny = math.cos(t), math.sin(t)
    h = s * 0.2
    d.polygon([(x + dx * h, y + dy * h), (x + nx * h * 0.8, y + ny * h * 0.8), (x - nx * h * 0.8, y - ny * h * 0.8)], fill=INK)
    return _finish(im, size)


def draw_clipboard(size: int = ICON_SIZE) -> Image.Image:
    im, d = _canvas(size)
    k, s = K, size * K
    d.rounded_rectangle((3 * k, 2.5 * k, s - 3 * k, s - 0.8 * k), radius=1.6 * k, outline=INK, width=int(1.6 * k))
    d.rounded_rectangle((6 * k, 0.8 * k, s - 6 * k, 4.6 * k), radius=1 * k, fill=INK)  # clip
    for y in (8, 11, 14):
        d.rectangle((6 * k, y * k, s - 6 * k, (y + 1.2) * k), fill=INK)  # text lines
    return _finish(im, size)


def draw_camera(size: int = ICON_SIZE) -> Image.Image:
    im, d = _canvas(size)
    k, s = K, size * K
    d.rounded_rectangle((6 * k, 3 * k, 11.5 * k, 6 * k), radius=1 * k, fill=INK)  # viewfinder bump
    d.rounded_rectangle((1 * k, 5 * k, s - 1 * k, s - 2.5 * k), radius=2.2 * k, outline=INK, width=int(1.6 * k))
    c = (s / 2, 10.2 * k)
    r = 3.3 * k
    d.ellipse((c[0] - r, c[1] - r, c[0] + r, c[1] + r), outline=INK, width=int(1.6 * k))  # lens
    return _finish(im, size)


def draw_arrow_up(size: int = ICON_SIZE) -> Image.Image:
    im, d = _canvas(size)
    s, t = size * K, 1.2 * K
    c = s / 2
    d.polygon([(c, s * 0.12), (s * 0.85, s * 0.52), (s * 0.15, s * 0.52)], fill=INK)
    d.rectangle((c - t, s * 0.45, c + t, s * 0.88), fill=INK)
    return _finish(im, size)


def draw_gear(size: int = ICON_SIZE) -> Image.Image:
    im, d = _canvas(size)
    s = size * K
    c, r_out, r_in, teeth = s / 2, s * 0.47, s * 0.34, 8
    pts = []
    for i in range(teeth * 4):  # square-ish teeth: out, out, in, in
        a = math.radians(i * 360 / (teeth * 4) - 360 / (teeth * 8))
        r = r_out if i % 4 in (0, 1) else r_in
        pts.append((c + r * math.cos(a), c + r * math.sin(a)))
    d.polygon(pts, fill=INK)
    h = s * 0.15
    d.ellipse((c - h, c - h, c + h, c + h), fill=(0, 0, 0, 0))  # hole
    return _finish(im, size)


def draw_search(size: int = ICON_SIZE) -> Image.Image:
    im, d = _canvas(size)
    s, w = size * K, int(1.7 * K)
    r, c = s * 0.27, s * 0.40
    d.ellipse((c - r, c - r, c + r, c + r), outline=INK, width=w)
    a = c + r * 0.7
    d.line((a, a, s * 0.88, s * 0.88), fill=INK, width=int(2.2 * K))
    return _finish(im, size)


def draw_clear(size: int = ICON_SIZE) -> Image.Image:
    im, d = _canvas(size)
    s, w, m = size * K, int(1.6 * K), size * K * 0.28
    d.line((m, m, s - m, s - m), fill=INK, width=w)
    d.line((m, s - m, s - m, m), fill=INK, width=w)
    return _finish(im, size)


ICONS = {"calculator": draw_calculator, "plus": draw_plus, "minus": draw_minus, "refresh": draw_refresh,
         "clipboard": draw_clipboard, "camera": draw_camera, "gear": draw_gear, "search": draw_search, "clear": draw_clear, "arrow_up": draw_arrow_up}


def icon(master, name: str, size: int = ICON_SIZE, faded: bool = False) -> tk.PhotoImage:
    """Small icon drawn at runtime (emoji glyphs render tiny in Tk on Windows).
    ``faded``: the look of a disabled button."""
    im = ICONS[name](size)
    if faded:
        im.putalpha(im.getchannel("A").point(lambda a: a * 35 // 100))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return _photo_png(master, buf.getvalue())


def icon_states(master, name: str, size: int = ICON_SIZE) -> tuple:
    """``image=`` value for a ttk button that looks faded while disabled."""
    return (icon(master, name, size), "disabled", icon(master, name, size, faded=True))

