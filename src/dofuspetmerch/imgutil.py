"""Minimal image helpers on top of Pillow. Images are numpy uint8 arrays in BGR(A) order."""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image


def _to_pil(img: np.ndarray) -> Image.Image:
    if img.ndim == 2:
        return Image.fromarray(img)
    if img.shape[2] == 4:
        return Image.fromarray(np.ascontiguousarray(img[:, :, [2, 1, 0, 3]]), "RGBA")
    return Image.fromarray(np.ascontiguousarray(img[:, :, ::-1]), "RGB")


def _from_pil(im: Image.Image, keep_alpha: bool = False) -> np.ndarray:
    if keep_alpha and im.mode in ("RGBA", "LA", "P"):
        a = np.asarray(im.convert("RGBA"))
        return np.ascontiguousarray(a[:, :, [2, 1, 0, 3]])
    return np.ascontiguousarray(np.asarray(im.convert("RGB"))[:, :, ::-1])


def load(path: str | Path, keep_alpha: bool = False) -> np.ndarray | None:
    try:
        with Image.open(path) as im:
            return _from_pil(im, keep_alpha)
    except (OSError, ValueError):
        return None


def save(path: str | Path, img: np.ndarray) -> None:
    _to_pil(img).save(path)


def resize(img: np.ndarray, scale: float | None = None, size: tuple[int, int] | None = None) -> np.ndarray:
    """Resize by factor or to (w, h). Bicubic up, area-like (box/lanczos) down."""
    h, w = img.shape[:2]
    if size is None:
        size = (max(1, round(w * scale)), max(1, round(h * scale)))
    up = size[0] >= w
    out = _to_pil(img).resize(size, Image.Resampling.BICUBIC if up else Image.Resampling.LANCZOS)
    return _from_pil(out, keep_alpha=img.ndim == 3 and img.shape[2] == 4)


def png_bytes(img: np.ndarray) -> bytes:
    buf = io.BytesIO()
    _to_pil(img).save(buf, "PNG")
    return buf.getvalue()
