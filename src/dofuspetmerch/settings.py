"""User settings persisted as config.json in the data folder."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .paths import app_dir, write_json_atomic

OVERLAY_POSITIONS = ("arriba-derecha", "arriba-izquierda", "abajo-derecha", "abajo-izquierda", "centro")
GSHEET_MODES = ("off", "read", "sync")
# Two-way sync (write to the sheet through Apps Script) is kept for the future but hidden for
# now: a saved "sync" mode is preserved in config.json but behaves as "off". Read it as
# ``settings.ENABLE_SHEET_SYNC`` (tests switch it on).
ENABLE_SHEET_SYNC = False

# Shared XP table read by default (read-only link; anyone can change it in Ajustes).
DEFAULT_SHEET_URL = "https://docs.google.com/spreadsheets/d/1mmbN39AI0xOQlO9SFoey4yE92hBd-cWNlsWxFy4TQtM/edit?gid=0#gid=0"
LANGS = ("es", "fr", "en", "de", "pt")  # the languages dofusdb.fr has names for
_CHOICES = {"overlay_position": OVERLAY_POSITIONS, "gsheet_mode": GSHEET_MODES, "lang": LANGS}


def visible_gsheet_modes() -> tuple[str, ...]:
    return tuple(m for m in GSHEET_MODES if m != "sync" or ENABLE_SHEET_SYNC)


def effective_gsheet_mode(stored: str) -> str:
    """Mode the app actually runs with (hidden "sync" -> "off")."""
    return "off" if stored == "sync" and not ENABLE_SHEET_SYNC else stored


def resolve_saved_gsheet_mode(ui_mode: str, stored: str) -> str:
    """Mode to save: keep a hidden stored mode ("sync") unless the user actually changed it."""
    return stored if ui_mode == effective_gsheet_mode(stored) else ui_mode


def _coerce(value, default):
    """Value from config.json with the type of its default; the default if it doesn't fit
    (a hand-edited file must never stop the app from starting)."""
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(default, (int, float)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return default
        return float(value) if math.isfinite(value) else default
    if isinstance(default, (str, list)):
        return value if isinstance(value, type(default)) else default
    return value


@dataclass
class Settings:
    hotkey: str = "ctrl+alt+d"
    cookie_price: float = 20000.0
    cookie_xp: float = 500.0
    margin_pct: float = 12.5
    pet_price_100: float = 5_000_000.0  # cookie price calculator
    pet_price_1: float = 1_000_000.0
    overlay_seconds: float = 8.0
    overlay_position: str = "arriba-derecha"
    sound: bool = True
    window_title: str = "Dofus"
    use_dofusdb: bool = True
    lang: str = "es"
    debug: bool = False
    gsheet_mode: str = "read"
    gsheet_url: str = DEFAULT_SHEET_URL
    gsheet_replace: bool = False
    gsheet_script_url: str = ""
    gsheet_token: str = ""
    gsheet_on_start: bool = True
    collapsed_sections: list = field(default_factory=list)  # keys of the settings window sections

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or app_dir() / "config.json"
        s = cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for f in fields(cls):
                    if f.name in data:
                        setattr(s, f.name, _coerce(data[f.name], getattr(s, f.name)))
        except (OSError, ValueError):
            pass  # missing or corrupt file -> defaults
        for name, allowed in _CHOICES.items():
            if getattr(s, name) not in allowed:
                setattr(s, name, getattr(cls(), name))
        return s

    @property
    def effective_gsheet_mode(self) -> str:
        return effective_gsheet_mode(self.gsheet_mode)

    def save(self, path: Path | None = None) -> None:
        write_json_atomic(path or app_dir() / "config.json", asdict(self))
