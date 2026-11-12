"""Where user data and bundled assets live on disk."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]  # repo root when running from source


def app_dir() -> Path:
    """%APPDATA%\\dofuspetmerch, or $DOFUSPETMERCH_HOME (tests and scripts use it to stay isolated)."""
    base = os.environ.get("DOFUSPETMERCH_HOME") or os.path.join(os.environ.get("APPDATA", str(Path.home())), "dofuspetmerch")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def asset_path(name: str) -> Path:
    """File under assets/: next to the sources, or inside the PyInstaller bundle."""
    return Path(getattr(sys, "_MEIPASS", _PACKAGE_ROOT)) / "assets" / name


def write_json_atomic(path: Path, data, indent: int | None = 2) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=indent, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
