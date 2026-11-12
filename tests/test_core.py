import json

import pytest

from dofuspetmerch import items, net
from dofuspetmerch.hotkey import HotkeyError, parse_hotkey
from dofuspetmerch.parsing import format_kamas, format_number, format_unit, format_xp, parse_kamas, parse_number, parse_xp
from dofuspetmerch.profit import cookie_breakeven, cookie_max_price, evaluate, kamas_per_xp, max_unit_price
from dofuspetmerch.reading.extract import parse_popup
from dofuspetmerch.reading.ocr import Word
from dofuspetmerch.settings import Settings
from dofuspetmerch.sheets.layout import parse_xp_csv, table_tsv
from dofuspetmerch.xptable import XpTable


@pytest.mark.parametrize(
    "text,value",
    [("7.840", 7840), ("1.000", 1000), ("19", 19), ("7 840", 7840), ("7,840", 7840), ("7:840", 7840),
     ("7\u00a0840", 7840), ("1.2O0", 1200), ("1.234.567", 1234567)],
)
def test_parse_kamas(text, value):
    assert parse_kamas(text) == value


@pytest.mark.parametrize("text", ["", "COMPRAR", "Id", "x", "7a8"])
def test_parse_kamas_rejects(text):
    assert parse_kamas(text) is None


def test_format():
    assert format_kamas(7840) == "7.840"
    assert format_kamas(35000) == "35.000"
    assert format_unit(5.8) == "5,8"
    assert format_unit(350) == "350"


def test_factor_from_user_example():
    f = kamas_per_xp(20000, 500, 12.5)
    assert f == pytest.approx(35)
    assert max_unit_price(10, f) == pytest.approx(350)


def test_evaluate():
    evals = evaluate([(1, 19), (100, 739), (1000, 40000)], max_unit=35)
    assert [e.profitable for e in evals] == [True, True, False]
    assert evals[1].max_lot_price == pytest.approx(3500)
    assert evals[1].unit_price == pytest.approx(7.39)


def test_evaluate_boundary_is_profitable():
    assert evaluate([(10, 350)], 35)[0].profitable


def test_hotkey_parse():
    assert parse_hotkey("ctrl+alt+d") == (0x2 | 0x1, ord("D"))
    assert parse_hotkey("Shift+F9") == (0x4, 0x78)
    for bad in ("", "ctrl+alt", "ctrl+foo", "a+b"):
        with pytest.raises(HotkeyError):
            parse_hotkey(bad)


def test_settings_roundtrip(tmp_path):
    p = tmp_path / "c.json"
    s = Settings(hotkey="ctrl+shift+f9", cookie_price=18000)
    s.save(p)
    s2 = Settings.load(p)
    assert s2.hotkey == "ctrl+shift+f9" and s2.cookie_price == 18000 and s2.cookie_xp == 500
    p.write_text("{corrupt")
    assert Settings.load(p).hotkey == "ctrl+alt+d"


def test_xp_table(tmp_path):
    t = XpTable(path=tmp_path / "xp.json")
    t.set("Gobio", 10)
    t.set("Trucha de río", 25)
    t.save()
    t2 = XpTable.load(tmp_path / "xp.json")
    assert t2.lookup("gobio") == ("Gobio", 10)
    assert t2.lookup("Trucha de rio") == ("Trucha de río", 25)  # accents
    assert t2.lookup("Gobi0") == ("Gobio", 10)  # OCR typo, fuzzy
    assert t2.lookup("Galleta") is None
    t2.set("GOBIO", 12)  # same item, different case: replaces
    assert len(t2.entries) == 2 and t2.lookup("gobio")[1] == 12
    t2.remove("GOBIO")
    assert t2.lookup("gobio") is None


# ---- popup parsing on synthetic OCR words -----------------------------------
def _row(y, lot, *prices):
    """Synthetic OCR words for one popup row (geometry like the 2x fixture)."""
    ws = [Word(lot, 170, y, 20, 18)] if lot else []
    x = 500
    for p in prices:
        ws.append(Word(p, x, y, 10 * len(p), 18))
        x += 10 * len(p) + 25  # far apart: not merged
    ws.append(Word("COMPRAR", 622, y, 140, 18))
    return ws


def _popup(*rows):
    words = [Word("Lote", 138, 334, 50, 20), Word("Precio", 508, 332, 76, 20)]
    for i, r in enumerate(rows):
        words += _row(399 + 77 * i, *r)
    return words


def test_split_price_is_not_guessed():
    r = parse_popup(_popup(("1", "19"), ("1.000", "7", "840")))
    assert r.rows == [(1, 19)]
    assert any("ambiguo" in w for w in r.warnings)


def test_duplicate_lot_rows_are_dropped():
    r = parse_popup(_popup(("1", "19"), ("100", "58"), ("100", "739"), ("1.000", "7.840")))
    assert r.rows == [(1, 19), (1000, 7840)]
    assert any("repetido" in w for w in r.warnings)


@pytest.mark.parametrize("lots,expected", [
    ((None, "10", "100", "1.000"), [1, 10, 100, 1000]),
    (("1", None, "100"), [1, 10, 100]),
    (("1", None, None, "1.000"), [1, 10, 100, 1000]),
    ((None, "100"), [100]),  # 1 or 10: ambiguous, the row is dropped
])
def test_unreadable_lots_are_inferred_only_when_unambiguous(lots, expected):
    r = parse_popup(_popup(*[(lot, "50") for lot in lots]))
    assert [lot for lot, _ in r.rows] == expected


# ---- numbers ----------------------------------------------------------------
def test_parse_xp_roundtrip():
    for v in (0.25, 0.5, 2.75, 10, 150.5, 1500):
        assert parse_xp(format_xp(v)) == v
    assert parse_xp("0,5") == 0.5 and parse_xp("1.5") == 1.5
    for bad in ("", "abc", "0", "-3", "nan", "inf", "1e3", "1_000", "1,2,3"):
        assert parse_xp(bad) is None
    assert parse_xp("1.500") == 1500  # Spanish thousands


def test_form_number_format():
    assert format_number(5_000_000.0) == "5.000.000"
    assert format_number(360.0) == "360"
    assert format_number(12.5) == "12,5"


@pytest.mark.parametrize("v", [1e-05, 1e-07, 0.25, 12.5, 0.0, 360.0, 999.5, 20000.0, 1e15 + 0.5, 5_000_000.0])
def test_form_format_roundtrips_and_never_uses_exponent(v):
    txt = format_number(v)
    assert "e" not in txt.lower()
    assert parse_number(txt) == pytest.approx(v, rel=1e-9, abs=1e-10)


# ---- dofusdb ----------------------------------------------------------------
def test_dofusdb_never_raises_and_backs_off(monkeypatch):
    calls = []

    def boom(req, timeout):
        calls.append(req)
        raise OSError("offline")

    monkeypatch.setattr(net, "open_url", boom)
    assert items.lookup("Gobio", "es", 1) is None
    assert items.lookup("Gobio", "es", 1) is None
    assert len(calls) == 1  # second call skipped by the offline back-off

    items.backoff.reset()
    monkeypatch.setattr(net, "open_url", lambda req, timeout: (b'{"data": [{"name": {"es": "Gobio"}}]}', ""))  # no id
    assert items.lookup("Gobio", "es", 1) is None


def test_dofusdb_hit_is_cached(monkeypatch):
    calls = []

    def answer(req, timeout):
        calls.append(req)
        return json.dumps({"data": [{"id": 7, "name": {"es": "Gobio", "fr": "Goujon"}, "img": "x"}]}).encode(), ""

    monkeypatch.setattr(net, "open_url", answer)
    assert items.lookup("gobio", "es", 1).name("es") == "Gobio"
    info = items.lookup("GOBIO", "es", 1)
    assert (info.id, info.name("fr")) == (7, "Goujon") and len(calls) == 1


def test_dofusdb_connection_cut_mid_answer_is_offline(monkeypatch):
    import http.client

    def cut(req, timeout):
        raise http.client.IncompleteRead(b"")

    monkeypatch.setattr(net, "open_url", cut)
    assert items.lookup("Gobio", "es", 1) is None
    assert items.backoff.active
    items.backoff.reset()
    assert items.download_icon(items.ItemInfo(id=1, names={}, img_url="https://x/1.png"), 1) is None


def test_table_tsv_roundtrips_through_sheet_parser():
    entries = {"Trucha de río": 3, "gobio": 0.25, "Pan\td'oro": 1500}
    tsv = table_tsv(entries)
    assert tsv.splitlines()[0] == "Objeto\tXP"
    assert "gobio\t0,25" in tsv and "Pan d'oro\t1500" in tsv
    rows, skipped = parse_xp_csv(tsv)
    assert rows == {"gobio": 0.25, "Pan d'oro": 1500, "Trucha de río": 3} and skipped == 0


# ------------------------------------------------- cookie price calculator
def test_cookie_price_from_user_example():
    assert cookie_breakeven(5_000_000, 1_000_000) == pytest.approx(11111.11, abs=0.01)
    assert cookie_max_price(5_000_000, 1_000_000) == 11111  # rounded down: maximum price to pay
    assert format_kamas(cookie_max_price(5_000_000, 1_000_000)) == "11.111"


@pytest.mark.parametrize("p100,p1", [(1_000_000, 1_000_000), (1_000_000, 5_000_000), (5_000_000, 0),
                                     (5_000_000, -1), (1_000_100, 1_000_000)])
def test_cookie_max_price_invalid(p100, p1):
    assert cookie_max_price(p100, p1) is None  # last case: < 1 kama per cookie


@pytest.mark.parametrize("args", [(1_000_000, 1_000_000), (1_000_000, 5_000_000)])
def test_cookie_breakeven_invalid(args):
    with pytest.raises(ValueError):
        cookie_breakeven(*args)


# ---------------------------------------------------------------- settings
def test_calculator_settings_defaults_and_roundtrip(tmp_path):
    p = tmp_path / "c.json"
    # old config: without the pet prices and with the removed fields
    p.write_text('{"cookie_price": 18000, "cookies_per_pet": 400, "cookie_target_profit_pct": 20}', encoding="utf-8")
    s = Settings.load(p)
    assert (s.pet_price_100, s.pet_price_1, s.cookie_price) == (5_000_000, 1_000_000, 18000)
    s.pet_price_100 = 6_000_000
    s.save(p)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["pet_price_100"] == 6_000_000
    assert "cookies_per_pet" not in data and "cookie_target_profit_pct" not in data


def test_hand_edited_config_never_breaks_startup(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"pet_price_100": "abc", "cookie_xp": null, "margin_pct": true, "sound": "si",'
                 ' "hotkey": 5, "collapsed_sections": "x", "overlay_position": "luna", "cookie_price": 18000}',
                 encoding="utf-8")
    s = Settings.load(p)
    d = Settings()
    assert (s.pet_price_100, s.cookie_xp, s.margin_pct, s.sound, s.hotkey, s.overlay_position) == \
        (d.pet_price_100, d.cookie_xp, d.margin_pct, d.sound, d.hotkey, d.overlay_position)
    assert s.collapsed_sections == [] and s.cookie_price == 18000
    p.write_text("[1, 2]", encoding="utf-8")
    assert Settings.load(p) == d


def test_normalize_rect():
    from dofuspetmerch.reading.capture import normalize_rect
    bounds = (-1920, 0, 3840, 1080)  # second monitor on the left
    assert normalize_rect((-1800, 100), (-1500, 400), bounds) == (-1800, 100, 300, 300)
    assert normalize_rect((-1500, 400), (-1800, 100), bounds) == (-1800, 100, 300, 300)  # dragged backwards
    assert normalize_rect((-2500, -50), (-1800, 100), bounds) == (-1920, 0, 120, 100)  # clamped
    assert normalize_rect((100, 100), (130, 400), bounds) is None  # too narrow
    assert normalize_rect((5, 5), (5, 5), bounds) is None  # a click


def test_drawn_icons():
    from dofuspetmerch.ui.images import ICON_SIZE, ICONS
    for name, draw in ICONS.items():
        im = draw()
        assert im.mode == "RGBA" and im.size == (ICON_SIZE, ICON_SIZE), name
        assert im.getchannel("A").getextrema()[1] > 200, name  # something visible was drawn


def test_xp_table_strict_load(tmp_path):
    path = tmp_path / "pet_xp.json"
    with pytest.raises(ValueError):
        XpTable.load(path, strict=True)  # missing
    path.write_text("{roto", encoding="utf-8")
    assert XpTable.load(path).entries == {}  # startup: tolerant
    with pytest.raises(ValueError):
        XpTable.load(path, strict=True)  # reload: must not wipe the table in memory


def test_xp_table_last_updated(tmp_path):
    t = XpTable.load(tmp_path / "pet_xp.json")
    assert t.last_updated() is None
    t.set("Gobio", 1)
    t.set("Trucha", 2)
    assert t.last_updated()[0] == "Trucha"
    t.apply_read({"Pez": 3.0}, replace=False)  # a Google Sheets import is not "added by the user"
    assert t.last_updated()[0] == "Trucha"
    t.set("trucha", 4)  # updated (renamed case): still the last one, under its current name
    assert t.last_updated()[0] == "trucha"
    t.save()
    assert XpTable.load(tmp_path / "pet_xp.json").last_updated()[0] == "trucha"  # survives restarts
    t.remove("trucha")
    assert t.last_updated() is None


def test_settings_lang_choices(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"lang": "klingon"}), encoding="utf-8")
    assert Settings.load(path).lang == "es"
    path.write_text(json.dumps({"lang": "pt"}), encoding="utf-8")
    assert Settings.load(path).lang == "pt"


def test_table_view_filter_and_sort():
    from dofuspetmerch.xptable import table_view
    e = {"Néctar del oriente": 10.0, "Gobio": 1.0, "piel de troz": 4.7, "Cola de mamatroz": 4.7, "Trucha": 3.0}
    assert [n for n, _ in table_view(e)] == ["Cola de mamatroz", "Gobio", "Néctar del oriente", "piel de troz", "Trucha"]
    assert [n for n, _ in table_view(e, descending=True)][0] == "Trucha"
    assert [n for n, _ in table_view(e, "NECTAR")] == ["Néctar del oriente"]  # case and accents ignored
    assert [n for n, _ in table_view(e, "troz de")] == ["Cola de mamatroz", "piel de troz"]  # every word, any order
    assert table_view(e, "xyz") == []
    assert table_view(e, "   ") == table_view(e)
    by_xp = [n for n, _ in table_view(e, column="xp", descending=True)]
    assert by_xp == ["Néctar del oriente", "Cola de mamatroz", "piel de troz", "Trucha", "Gobio"]  # ties by name
    assert [n for n, _ in table_view(e, column="xp")][:2] == ["Gobio", "Trucha"]
