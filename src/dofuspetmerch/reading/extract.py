"""Locate the HDV (market) buy popup in a screenshot and read item name + lot prices.

Two passes:
1. OCR the whole capture at 1x only to find the big "COMPRAR" buttons (reliable even
   when small digits are not).
2. Crop the popup around those buttons, upscale it and OCR again to read the
   name and the lot/price rows accurately.

All geometry is expressed relative to the width of the "COMPRAR" word, so it
works at any UI scale / resolution.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

import numpy as np
from rapidfuzz import fuzz

from .ocr import Word
from ..parsing import letters_only, parse_kamas

# Keywords per client language (letters only, upper-case).
BUY_WORDS = ("COMPRAR", "ACHETER", "BUY", "KAUFEN", "COMPRA")
PRICE_WORDS = ("PRECIO", "PRIX", "PRICE", "PREIS", "PRECO")
LEVEL_WORDS = ("NIV", "NV", "LVL", "LV", "STUFE")
VALID_LOTS = (1, 10, 100, 1000)

# Popup geometry measured on the reference capture, in units of the COMPRAR word width.
_CROP_LEFT = 4.9
_CROP_RIGHT = 0.6
_CROP_TOP = 3.4
_CROP_BOTTOM = 0.5
_TARGET_TEXT_H = 22  # px height we want small text to have for the 2nd OCR pass


class PopupNotFound(Exception):
    pass


@dataclass
class MarketReading:
    name: str
    rows: list[tuple[int, int]]  # (lot size, total price)
    icon: np.ndarray | None = None  # BGR crop of the item icon
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)  # popup crop in capture coords (x, y, w, h)
    warnings: list[str] = field(default_factory=list)


def _is_buy(w: Word) -> bool:
    t = letters_only(w.text)
    if len(t) < 3:
        return False
    return any(fuzz.partial_ratio(t, k) >= 80 and 0.6 <= len(t) / len(k) <= 1.6 for k in BUY_WORDS)


def _clean_buy(w: Word) -> bool:
    t = letters_only(w.text)
    return any(fuzz.ratio(t, k) >= 85 for k in BUY_WORDS)


def _button_width(buys: list[Word]) -> float:
    """Width of the COMPRAR word; guards against OCR returning a truncated word."""
    return max(statistics.median(b.w for b in buys), 6.5 * statistics.median(b.h for b in buys))


def _is_price_header(w: Word) -> bool:
    t = letters_only(w.text)
    return len(t) >= 4 and any(fuzz.ratio(t, k) >= 75 for k in PRICE_WORDS)


def _is_level(w: Word) -> bool:
    t = letters_only(w.text)
    return any(t.startswith(k) for k in LEVEL_WORDS) and len(t) <= 6


def find_buy_buttons(words: list[Word]) -> list[Word]:
    """Return the COMPRAR words belonging to the biggest vertically aligned column."""
    buys = [w for w in words if _is_buy(w)]
    if not buys:
        return []
    clusters: list[list[Word]] = []
    for b in sorted(buys, key=lambda w: w.x):
        for c in clusters:
            if abs(c[0].x - b.x) < 0.5 * c[0].w:
                c.append(b)
                break
        else:
            clusters.append([b])
    best = max(clusters, key=len)
    return sorted(best, key=lambda w: w.y)


def locate_popup(words: list[Word], img_shape) -> tuple[int, int, int, int]:
    buys = find_buy_buttons(words)
    if not buys:
        raise PopupNotFound("No se encontró la ventana de compra del mercadillo (botones COMPRAR)")
    W = _button_width(buys)
    H, Wimg = img_shape[:2]
    x0 = max(0, int(min(b.x for b in buys) - _CROP_LEFT * W))
    x1 = min(Wimg, int(max(b.right for b in buys) + _CROP_RIGHT * W))
    y0 = max(0, int(min(b.y for b in buys) - _CROP_TOP * W))
    y1 = min(H, int(max(b.bottom for b in buys) + _CROP_BOTTOM * W))
    return x0, y0, x1 - x0, y1 - y0


def _merge_numeric(tokens: list[Word], gap: float) -> list[Word]:
    """Join numbers the OCR split in two ('7' '840' -> '7840')."""
    out: list[Word] = []
    for t in sorted(tokens, key=lambda w: w.x):
        if out and t.x - out[-1].right < gap:
            p = out[-1]
            out[-1] = Word(p.text + t.text, p.x, min(p.y, t.y), t.right - p.x, max(p.bottom, t.bottom) - min(p.y, t.y))
        else:
            out.append(t)
    return out


def _infer_lots(lots: list[int | None]) -> list[int | None]:
    """Fill unknown lot sizes when the increasing 1/10/100/1000 order makes them unambiguous."""
    res = list(lots)
    for i, v in enumerate(res):
        if v is not None:
            continue
        lo = next((res[j] for j in range(i - 1, -1, -1) if res[j] is not None), None)
        hi = next((res[j] for j in range(i + 1, len(res)) if res[j] is not None), None)
        cands = [l for l in VALID_LOTS if (lo is None or l > lo) and (hi is None or l < hi)]
        # Count how many unknown slots share this gap: needs exactly that many candidates.
        start = i
        while start > 0 and res[start - 1] is None:
            start -= 1
        end = i
        while end + 1 < len(res) and res[end + 1] is None:
            end += 1
        if len(cands) == end - start + 1:
            res[i] = cands[i - start]
    return res


def parse_popup(words: list[Word], popup: np.ndarray | None = None) -> MarketReading:
    """Interpret OCR words of a cropped popup (coordinates in popup space)."""
    warnings: list[str] = []
    buys = find_buy_buttons(words)
    if not buys:
        raise PopupNotFound("No se encontraron filas de lotes (botones COMPRAR)")
    W = _button_width(buys)
    bh = statistics.median(b.h for b in buys)
    buy_left = min(b.x for b in buys)
    first_buy_y = buys[0].y

    # Header line ("Lote ... Precio"): the 'Precio' closest above the first row.
    headers = [w for w in words if _is_price_header(w) and w.bottom < first_buy_y and w.x > buy_left - 2.5 * W]
    header_y = max(headers, key=lambda w: w.y).y if headers else first_buy_y - 0.5 * W

    numeric = [w for w in words if w.right <= buy_left + 0.1 * W and w.y > header_y + 0.5 * bh and parse_kamas(w.text) is not None]
    raw_rows: list[tuple[int | None, int | None]] = []
    for b in buys:
        band = [w for w in numeric if abs(w.cy - b.cy) < max(bh, 0.9 * statistics.median([n.h for n in numeric] or [bh]))]
        # Merge only digit fragments that touch (thousands split by the OCR).
        band = _merge_numeric(band, gap=0.35 * bh)
        if not band:
            warnings.append("Fila sin números legibles")
            continue
        # Price is in the right column, just before the kama icon: closest to COMPRAR.
        price_col = [t for t in band if buy_left - t.right < 1.6 * W]
        lot_col = [t for t in band if t not in price_col]
        price = None
        if len(price_col) == 1:
            price = parse_kamas(price_col[0].text)
        elif len(price_col) > 1:
            # e.g. "7" + "840" too far apart to merge: guessing could invent a bargain.
            warnings.append("Precio ambiguo (" + " ".join(t.text for t in price_col) + ")")
        lot = parse_kamas(min(lot_col, key=lambda t: t.x).text) if lot_col else None
        if lot is not None and lot not in VALID_LOTS:
            warnings.append(f"Lote ilegible ({lot})")
            lot = None
        raw_rows.append((lot, price))

    lots = _infer_lots([l for l, _ in raw_rows])
    # Rows are shown in strictly increasing lot order; anything else is a misread
    # (e.g. "10" read as "100"). Drop every row involved rather than guess.
    suspicious = set()
    known = [(i, l) for i, l in enumerate(lots) if l is not None]
    for (i, a), (j, b) in zip(known, known[1:]):
        if b <= a:
            suspicious.update((i, j))
    rows: list[tuple[int, int]] = []
    for i, (lot, (_, price)) in enumerate(zip(lots, raw_rows)):
        if i in suspicious:
            warnings.append(f"Lote {lot} repetido o fuera de orden: fila descartada")
            continue
        if lot is None or price is None or price <= 0:
            warnings.append("Una fila no se pudo leer y se ha descartado")
            continue
        rows.append((lot, price))
    # A lot misread with an extra zero ("10" -> "100") makes its unit price 10x too cheap.
    for (l1, p1), (l2, p2) in zip(rows, rows[1:]):
        if p2 / l2 < (p1 / l1) / 8:
            warnings.append(f"Precio/u del lote {l2} sospechosamente bajo: revisa el lote en el juego")

    name, icon = _read_header(words, header_y, bh, popup)
    if not name:
        warnings.append("No se pudo leer el nombre del objeto")
    return MarketReading(name=name, rows=rows, icon=icon, warnings=warnings)


def _group_lines(words: list[Word]) -> list[list[Word]]:
    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: w.cy):
        if lines and abs(statistics.mean(x.cy for x in lines[-1]) - w.cy) < 0.5 * w.h:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(l, key=lambda w: w.x) for l in lines]


def _read_header(words, header_y, bh, popup):
    top_words = [w for w in words if w.bottom < header_y - 0.2 * bh]
    lines = _group_lines(top_words)
    if not lines:
        return "", None
    level_idx = next((i for i, l in enumerate(lines) if _is_level(l[0])), None)
    if level_idx is not None:
        col_x = lines[level_idx][0].x
    else:
        # Text column = the most common left edge among header lines.
        lefts = [l[0].x for l in lines]
        col_x = max(lefts, key=lambda x: sum(abs(x - o) < 1.5 * bh for o in lefts))
    col_lines = [l for l in lines if abs(l[0].x - col_x) < 1.5 * bh]
    if level_idx is not None:
        lvl = lines[level_idx]
        above = [l for l in col_lines if l[0].cy < lvl[0].cy - 0.5 * bh]
        # Keep only the contiguous block right above the level line (name may wrap).
        name_lines = []
        ref = lvl[0].y
        for l in reversed(above):
            if ref - l[0].bottom > 1.5 * l[0].h:
                break
            name_lines.insert(0, l)
            ref = l[0].y
    else:
        name_lines = col_lines[:1]
    if not name_lines:
        return "", None
    name = " ".join(w.text for l in name_lines for w in l).strip()

    icon = None
    if popup is not None:
        first = name_lines[0][0]
        pitch = (lines[level_idx][0].y - name_lines[-1][0].y) if level_idx is not None else first.h * 1.6
        pitch = max(pitch, first.h)
        size = 3.9 * pitch
        right = first.x - 0.3 * pitch
        top = first.y - 0.2 * pitch
        x0, y0 = int(max(0, right - size)), int(max(0, top))
        x1, y1 = int(max(0, right)), int(min(popup.shape[0], top + size))
        if x1 - x0 > 8 and y1 - y0 > 8:
            icon = popup[y0:y1, x0:x1].copy()
    return name, icon


def read_market(img: np.ndarray, ocr, debug: dict | None = None) -> MarketReading:
    """Full pipeline on a screenshot (BGR). ``ocr`` must provide ``recognize(img, scale)``."""
    words = ocr.recognize(img, 1.0)
    buys = find_buy_buttons(words)
    if len(buys) < 2 or not all(_clean_buy(b) for b in buys):
        # Small UI scale: the 1x pass misses or truncates buttons. Retry upscaled, keep the best.
        words2 = ocr.recognize(img, 1.6)
        buys2 = find_buy_buttons(words2)
        if (len(buys2), sum(map(_clean_buy, buys2))) > (len(buys), sum(map(_clean_buy, buys))):
            words, buys = words2, buys2
    x, y, w, h = locate_popup(words, img.shape)
    popup = img[y : y + h, x : x + w]
    text_h = statistics.median(b.h for b in buys)
    scale = min(4.0, max(1.5, _TARGET_TEXT_H / max(text_h, 1)))
    pwords = ocr.recognize(popup, scale)
    if debug is not None:
        debug["pass1"] = [wd.to_dict() for wd in words]
        debug["pass2"] = [wd.to_dict() for wd in pwords]
        debug["bbox"] = (x, y, w, h)
        debug["scale"] = scale
    reading = parse_popup(pwords, popup)
    reading.bbox = (x, y, w, h)
    return reading
