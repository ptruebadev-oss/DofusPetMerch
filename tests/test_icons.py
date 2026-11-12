import json

import numpy as np

from dofuspetmerch import items as icons


def test_icon_filename():
    a = icons.icon_filename("Pan d'oro")
    assert a == icons.icon_filename("pan  d'ORO")
    assert icons.icon_filename("Trucha de río").isascii()
    assert icons.icon_filename("Trucha de río") == icons.icon_filename("trucha de rio")
    assert icons.icon_filename("Gobio") != icons.icon_filename("Gobion")
    assert a.endswith(".png")


def _official(home, name="Gobio", id_=1782, png=True):
    (home / "cache" / "icons").mkdir(parents=True, exist_ok=True)
    (home / "cache" / "items_es.json").write_text(json.dumps({name.lower(): {"id": id_}, "nada": {"miss_at": 1}}))
    p = home / "cache" / "icons" / f"{id_}.png"
    if png:
        p.write_bytes(b"x")
    return p


def test_official_icon_path(home):
    assert icons.official_icon_path("Gobio", "es") is None  # no cache
    (home / "cache").mkdir()
    (home / "cache" / "items_es.json").write_text("{corrupt")
    assert icons.official_icon_path("Gobio", "es") is None
    p = _official(home)
    assert icons.official_icon_path("GOBIO", "es") == p
    assert icons.official_icon_path("nada", "es") is None  # negative cache entry


def test_official_without_png(home):
    _official(home, png=False)
    assert icons.official_icon_path("Gobio", "es") is None


def test_priority_and_captured_roundtrip(home):
    img = np.full((30, 30, 3), 120, np.uint8)
    icons.save_captured("Gobio", img)
    icons.save_captured("Gobio", None)  # no-op, no error
    cap = icons.captured_icon_path("Gobio")
    assert cap.exists()
    assert icons.resolve_icon("Gobio", "es", True) == cap
    official = _official(home)
    assert icons.resolve_icon("Gobio", "es", True) == official
    assert icons.resolve_icon("Gobio", "es", False) == cap
    assert icons.resolve_icon("Otro", "es", True) is None
