"""Screenshot -> market reading -> profitability. Independent from the GUI so it can be tested."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import imgutil, items
from .paths import app_dir
from .profit import LotEval, evaluate, kamas_per_xp, max_unit_price
from .reading.extract import MarketReading, PopupNotFound, read_market
from .settings import Settings
from .xptable import XpTable


@dataclass
class Analysis:
    name: str = ""
    icon_bgr: np.ndarray | None = None  # cropped from the screen
    icon_file: Path | None = None  # official icon, preferred when present
    item_xp: float | None = None
    max_unit: float | None = None  # None when the item is not in the XP table
    evals: list[LotEval] = field(default_factory=list)
    rows: list[tuple[int, int]] = field(default_factory=list)  # (lot, price) as read
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    read_name: str = ""  # name as read by the OCR, before any correction

    @property
    def any_profitable(self) -> bool:
        return any(e.profitable for e in self.evals)


def analyze(img: np.ndarray, settings: Settings, xp_table: XpTable, ocr, debug: bool = False) -> Analysis:
    """``debug`` saves the capture, the popup crop and the raw OCR in <data>/debug."""
    trace = {} if debug else None
    try:
        reading = read_market(img, ocr, trace)
    except PopupNotFound as e:
        if debug:
            _save_debug(img, None, trace)
        return Analysis(error=str(e), warnings=["Abre la ventana de compra del mercadillo y vuelve a pulsar el atajo."])

    data = Analysis(name=reading.name, read_name=reading.name, icon_bgr=reading.icon, rows=reading.rows,
                    warnings=list(reading.warnings))
    if settings.use_dofusdb and reading.name:
        info = items.lookup(reading.name, settings.lang, timeout=2.0)
        if info:
            data.name = info.name(settings.lang) or reading.name
            data.icon_file = items.download_icon(info, timeout=2.0)

    hit = xp_table.lookup(data.name) or xp_table.lookup(reading.name)
    if hit:
        data.name, data.item_xp = hit
        factor = kamas_per_xp(settings.cookie_price, settings.cookie_xp, settings.margin_pct)
        data.max_unit = max_unit_price(data.item_xp, factor)
        data.evals = evaluate(reading.rows, data.max_unit)

    if data.name:
        items.save_captured(data.name, reading.icon)  # shown later in the XP table

    if debug:
        _save_debug(img, reading, trace)
    return data


def _save_debug(img: np.ndarray, reading: MarketReading | None, trace: dict) -> None:
    d = app_dir() / "debug"
    d.mkdir(exist_ok=True)
    stem = time.strftime("%Y%m%d-%H%M%S")
    imgutil.save(d / f"{stem}_capture.png", img)
    if reading is not None:
        x, y, w, h = reading.bbox
        imgutil.save(d / f"{stem}_popup.png", img[y : y + h, x : x + w])
        trace["reading"] = {"name": reading.name, "rows": reading.rows, "warnings": reading.warnings}
    (d / f"{stem}_ocr.json").write_text(json.dumps(trace, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
