"""Thin wrapper over the OCR engine built into Windows 10/11 (Windows.Media.Ocr).

No extra installs are needed beyond the `winrt-*` wheels. The recogniser language
is the user profile language (or a specific one if installed).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import numpy as np

from .. import imgutil


@dataclass(frozen=True)
class Word:
    text: str
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def to_dict(self) -> dict:
        return {"text": self.text, "x": self.x, "y": self.y, "w": self.w, "h": self.h}


class OcrUnavailable(RuntimeError):
    pass


def _bgra(img: np.ndarray) -> np.ndarray:
    """BGR -> opaque BGRA, the pixel format SoftwareBitmap takes."""
    h, w = img.shape[:2]
    out = np.empty((h, w, 4), np.uint8)
    out[:, :, :3] = img[:, :, :3]
    out[:, :, 3] = 255
    return out


class WinOcr:
    def __init__(self, lang_tag: str | None = None):
        try:
            from winrt.windows.globalization import Language
            from winrt.windows.media.ocr import OcrEngine
        except ImportError as e:  # pragma: no cover - depends on platform
            raise OcrUnavailable(f"Windows OCR no disponible: {e}") from e
        engine = None
        if lang_tag:
            lang = Language(lang_tag)
            if OcrEngine.is_language_supported(lang):
                engine = OcrEngine.try_create_from_language(lang)
        if engine is None:
            engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise OcrUnavailable("No hay ningún idioma de OCR instalado en Windows")
        self._engine = engine
        self.max_dim = int(OcrEngine.max_image_dimension)

    def recognize(self, img_bgr: np.ndarray, scale: float = 1.0) -> list[Word]:
        """OCR an image. Coordinates are returned in the *input* image space."""
        img = img_bgr
        h, w = img.shape[:2]
        scale = min(scale, self.max_dim / max(h, w))
        if abs(scale - 1.0) > 1e-3:
            img = imgutil.resize(img, scale)
        return [Word(t, x / scale, y / scale, ww / scale, hh / scale) for t, x, y, ww, hh in self._run(img)]

    def _run(self, img_bgr: np.ndarray) -> list[tuple]:
        from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.storage.streams import DataWriter

        bgra = _bgra(img_bgr)
        h, w = bgra.shape[:2]

        async def go():
            dw = DataWriter()
            dw.write_bytes(bgra.tobytes())
            bmp = SoftwareBitmap.create_copy_from_buffer(
                dw.detach_buffer(), BitmapPixelFormat.BGRA8, w, h, BitmapAlphaMode.PREMULTIPLIED
            )
            res = await self._engine.recognize_async(bmp)
            out = []
            for line in res.lines:
                for wd in line.words:
                    r = wd.bounding_rect
                    out.append((wd.text, r.x, r.y, r.width, r.height))
            return out

        return asyncio.run(go())
