"""Installation check: what is ready, what is missing and how to fix it."""
import os
from dataclasses import dataclass
from typing import Optional

from . import book, config, installer, pwsource


@dataclass
class Check:
    key: str
    label: str
    ok: bool
    detail: str
    required: bool = False
    fix: Optional[str] = None       # 'stockfish' | 'eco' | 'syzygy' | None (what the GUI can download)


def _count_tables():
    d = installer.SYZYGY_DIR
    return len(list(d.glob("*.rtb?"))) if d.exists() else 0


def run_checks():
    checks = []
    chrome = next((p for p in pwsource.CHROME_PATHS if p and os.path.exists(p)), None)
    checks.append(Check("chrome", "Google Chrome", bool(chrome), chrome or "Nao encontrado. Instale o Chrome.",
                        required=True))
    try:
        sf = config.find_stockfish()
        checks.append(Check("stockfish", "Stockfish (motor)", True, sf, required=True))
    except FileNotFoundError:
        checks.append(Check("stockfish", "Stockfish (motor)", False,
                            "Nao encontrado. Baixe automaticamente ou use STOCKFISH_PATH.",
                            required=True, fix="stockfish"))
    has_book = book.ECO_BOOK.exists()
    checks.append(Check("book", "Livro de aberturas (opcional)", has_book,
                        str(book.ECO_BOOK) if has_book else "Nao instalado (~0,4 MB).", fix=None if has_book else "eco"))
    n = _count_tables()
    checks.append(Check("syzygy", "Tablebases de finais (opcional)", n > 0,
                        f"{n} arquivos" if n else "Nao instaladas (3-4 pecas: ~4,4 MB).",
                        fix=None if n else "syzygy"))
    checks.append(Check("calibration", "Calibracao", config.CONFIG_PATH.exists(),
                        "Pronta." if config.CONFIG_PATH.exists() else "Abra o Chrome, comece uma partida e clique em Calibrar."))
    key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    checks.append(Check("api", "Explicacoes com o Claude (opcional)", key,
                        "Chave encontrada." if key else "Defina ANTHROPIC_API_KEY para ativar."))
    return checks


def ready(checks=None):
    """True if every REQUIRED item is OK (Chrome and Stockfish)."""
    return all(c.ok for c in (checks or run_checks()) if c.required)
