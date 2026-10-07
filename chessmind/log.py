"""Log em arquivo (logs/chessmind.log, com rotacao) para investigar travamentos depois."""
import logging
import logging.handlers
import os
from pathlib import Path

from . import config

LOG_DIR = Path(os.environ.get("CHESSMIND_LOG_DIR") or config.ROOT / "logs")
_ready = False


def get(name="chessmind"):
    global _ready
    if not _ready:
        LOG_DIR.mkdir(exist_ok=True)
        h = logging.handlers.RotatingFileHandler(LOG_DIR / "chessmind.log", maxBytes=500_000,
                                                 backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root = logging.getLogger("chessmind")
        root.setLevel(logging.INFO)
        root.addHandler(h)
        _ready = True
    # tem de ser filho de "chessmind" (onde esta o handler); com o nome solto a mensagem se perdia
    return logging.getLogger(name if name == "chessmind" or name.startswith("chessmind.")
                             else f"chessmind.{name}")
