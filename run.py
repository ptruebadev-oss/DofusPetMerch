"""Launcher used by PyInstaller (and handy for `python run.py`)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from dofuspetmerch.__main__ import _cli  # noqa: E402

if __name__ == "__main__":
    _cli()
