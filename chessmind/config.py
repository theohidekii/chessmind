import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "calibration.json"
TEMPLATES_PATH = ROOT / "templates.npz"


def make_dpi_aware():
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()


def find_stockfish():
    env = os.environ.get("STOCKFISH_PATH")
    if env and Path(env).exists():
        return env
    candidates = sorted((ROOT / "engine").glob("stockfish*/stockfish*.exe"))
    candidates.append(ROOT / "engine" / "stockfish.exe")
    for p in candidates:
        if p.exists():
            return str(p)
    raise FileNotFoundError(
        "Binario do Stockfish nao encontrado. Coloque em engine/stockfish.exe "
        "ou defina STOCKFISH_PATH."
    )


def save_calibration(data):
    CONFIG_PATH.write_text(json.dumps(data, indent=2))


def load_calibration():
    return json.loads(CONFIG_PATH.read_text())
