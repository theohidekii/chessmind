"""Downloads and prepares the third-party files ChessMind uses.

    python scripts/get_data.py --all              # Stockfish + opening book + 3-4 piece tablebases
    python scripts/get_data.py --stockfish        # official Stockfish build (~80 MB)
    python scripts/get_data.py --eco              # ECO table + opening book (~0.4 MB)
    python scripts/get_data.py --syzygy 4         # 3-4 piece tablebases (~4.4 MB)
    python scripts/get_data.py --syzygy 5         # 3-5 piece tablebases (~984 MB, 290 files)

Sources:
  - Stockfish: https://github.com/official-stockfish/Stockfish/releases (GPL-3.0)
  - ECO: https://github.com/lichess-org/chess-openings (CC0)
  - Syzygy: https://tablebase.lichess.ovh/tables/standard/
Files that are already complete are skipped. The same code powers the GUI's installation check.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chessmind import config, installer  # noqa: E402


def make_progress():
    last = {"msg": None, "pct": -1}

    def progress(message, fraction=None):
        pct = int(fraction * 100) if fraction is not None else -1
        if message != last["msg"] or (pct // 10 != last["pct"] // 10):
            print(f"  {message}" + (f" {pct}%" if pct >= 0 else ""), flush=True)
            last["msg"], last["pct"] = message, pct

    return progress


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="Stockfish + opening book + 3-4 piece tablebases")
    ap.add_argument("--stockfish", action="store_true")
    ap.add_argument("--eco", action="store_true")
    ap.add_argument("--syzygy", type=int, choices=(4, 5), help="maximum number of pieces (4 or 5)")
    args = ap.parse_args(argv)
    if not (args.all or args.stockfish or args.eco or args.syzygy):
        ap.print_help()
        return 0
    progress = make_progress()
    failed = False
    steps = []
    if args.all or args.stockfish:
        try:
            have = config.find_stockfish() if args.all and not args.stockfish else None
        except FileNotFoundError:
            have = None
        if have:
            print(f"[Stockfish]\n  already installed: {have}")
        else:
            steps.append(("Stockfish", lambda: installer.download_stockfish(progress)))
    if args.all or args.eco:
        steps.append(("Opening book", lambda: installer.get_eco(progress)))
    if args.all or args.syzygy:
        steps.append(("Tablebases", lambda: installer.get_syzygy(args.syzygy or 4, progress)))
    for name, run in steps:
        print(f"[{name}]")
        try:
            print(f"  OK: {run()}")
        except Exception as e:                      # keep going: the other steps are independent
            failed = True
            print(f"  FAILED: {type(e).__name__}: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
