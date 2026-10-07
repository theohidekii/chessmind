"""Baixa e prepara os dados opcionais do ChessMind.

    python scripts/get_data.py --eco             # tabela ECO (aberturas) e livro engine/books/eco.bin
    python scripts/get_data.py --syzygy 4        # tablebases de 3-4 pecas (~4,4 MB)
    python scripts/get_data.py --syzygy 5        # tablebases de 3-4-5 pecas (~984 MB, 290 arquivos)
    python scripts/get_data.py --eco --syzygy 4

Fontes:
  - ECO: https://github.com/lichess-org/chess-openings (dominio publico, CC0), ~395 KB
  - Syzygy: https://tablebase.lichess.ovh/tables/standard/ (3-4-5-wdl e 3-4-5-dtz)
Arquivos ja baixados (com o tamanho certo) sao pulados.
"""
import argparse
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from chessmind import book  # noqa: E402

ECO_URL = "https://raw.githubusercontent.com/lichess-org/chess-openings/master/{}.tsv"
TB_BASE = "https://tablebase.lichess.ovh/tables/standard/"
SYZYGY_DIR = ROOT / "engine" / "syzygy"


def fetch(url, dest, expected=None):
    dest = Path(dest)
    if expected is not None and dest.exists() and dest.stat().st_size == expected:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    if expected is not None and tmp.stat().st_size != expected:
        tmp.unlink()
        raise IOError(f"tamanho inesperado em {url}")
    tmp.replace(dest)
    return True


def get_eco():
    for letter in "abcde":
        fetch(ECO_URL.format(letter), book.ECO_DIR / f"{letter}.tsv")
        print(f"  ECO {letter}.tsv ok")
    n = book.build_eco_book()
    print(f"Livro gerado: {book.ECO_BOOK} ({n} entradas)")


def listing(kind):
    html = urllib.request.urlopen(f"{TB_BASE}{kind}/", timeout=60).read().decode("utf8", "ignore")
    return [(n, int(s)) for n, s in re.findall(r'<a href="([^"]+\.rtb[wz])">[^<]*</a>\s+\S+\s+\S+\s+(\d+)', html)]


def get_syzygy(max_pieces):
    files = []
    for kind in ("3-4-5-wdl", "3-4-5-dtz"):
        files += [(kind, n, s) for n, s in listing(kind)
                  if len(n.split(".")[0].replace("v", "")) <= max_pieces]
    total = sum(s for _, _, s in files)
    print(f"{len(files)} arquivos, {total / 1e6:.1f} MB")
    for i, (kind, name, size) in enumerate(files, 1):
        fetch(f"{TB_BASE}{kind}/{name}", SYZYGY_DIR / name, size)
        if i % 20 == 0 or i == len(files):
            print(f"  {i}/{len(files)}")
    print(f"Tablebases em {SYZYGY_DIR}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eco", action="store_true")
    ap.add_argument("--syzygy", type=int, choices=(4, 5), help="maximo de pecas (4 ou 5)")
    args = ap.parse_args()
    if not (args.eco or args.syzygy):
        ap.print_help()
    if args.eco:
        get_eco()
    if args.syzygy:
        get_syzygy(args.syzygy)
