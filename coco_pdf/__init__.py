import sys
from pathlib import Path

__version__ = "0.2.0"


def asset(name: str) -> Path:
    # PyInstaller unpacks data files under sys._MEIPASS.
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "assets" / name
