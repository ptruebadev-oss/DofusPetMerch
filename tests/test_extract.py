"""OCR tests against the real reference capture. Skipped if Windows OCR is unavailable."""
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageFilter

from dofuspetmerch import imgutil
from dofuspetmerch.analysis import analyze
from dofuspetmerch.reading.extract import PopupNotFound, read_market
from dofuspetmerch.settings import Settings
from dofuspetmerch.xptable import XpTable

FIXTURE = Path(__file__).parent / "fixtures" / "market_gobio.png"
EXPECTED = [(1, 19), (10, 58), (100, 739), (1000, 7840)]

try:
    from dofuspetmerch.reading.ocr import WinOcr

    OCR = WinOcr("es")
except Exception as e:  # pragma: no cover
    OCR = None
    REASON = str(e)
else:
    REASON = ""

pytestmark = pytest.mark.skipif(OCR is None, reason=f"Windows OCR no disponible: {REASON}")


@pytest.fixture(scope="module")
def popup():
    return imgutil.load(FIXTURE)


def _on_screen(img, scale, at=(900, 300), size=(1080, 1920), noise=False):
    canvas = np.full((*size, 3), 30, np.uint8)
    if noise:  # busy game-like background
        rng = np.random.default_rng(0)
        noise_img = Image.fromarray(rng.integers(0, 120, (*size, 3), dtype=np.uint8)).filter(ImageFilter.GaussianBlur(6))
        canvas = np.array(noise_img)
    f = imgutil.resize(img, scale)
    y, x = at[1], at[0]
    canvas[y : y + f.shape[0], x : x + f.shape[1]] = f
    return canvas


def test_reads_reference_popup(popup):
    r = read_market(popup, OCR)
    assert r.name == "Gobio"
    assert r.rows == EXPECTED
    assert r.icon is not None and r.icon.shape[0] > 40
    assert not r.warnings


@pytest.mark.parametrize("scale", [0.8, 1.0, 1.25, 1.5])
def test_reads_popup_inside_full_screen(popup, scale):
    r = read_market(_on_screen(popup, scale, noise=scale == 1.0), OCR)
    assert r.name == "Gobio"
    assert r.rows == EXPECTED
    x, y, w, h = r.bbox
    assert x <= 900 <= x + w and y <= 300 + 60 * scale <= y + h


def test_missing_first_row(popup):
    img = popup.copy()
    img[185:222, 20:410] = img[340:352, 20:410].mean(axis=(0, 1))  # blank out the "1" lot row
    r = read_market(img, OCR)
    assert r.name == "Gobio"
    assert r.rows == EXPECTED[1:]


def test_no_popup():
    with pytest.raises(PopupNotFound):
        read_market(np.full((600, 800, 3), 40, np.uint8), OCR)


def test_pipeline_profitability(popup, tmp_path):
    s = Settings(use_dofusdb=False)
    xp = XpTable({"Gobio": 0.5}, path=tmp_path / "xp.json")
    data = analyze(popup, s, xp, OCR)
    assert data.max_unit == pytest.approx(17.5)  # 0.5 XP * 35 k/XP
    # unit prices: 19, 5.8, 7.39, 7.84
    assert [e.profitable for e in data.evals] == [False, True, True, True]
    assert data.any_profitable


def test_pipeline_unknown_item(popup, tmp_path):
    data = analyze(popup, Settings(use_dofusdb=False), XpTable(path=tmp_path / "x.json"), OCR)
    assert data.max_unit is None and data.rows == EXPECTED and data.error is None
    assert data.name == data.read_name == "Gobio"
