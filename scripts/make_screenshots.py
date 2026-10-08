"""Renders the README screenshots (docs/images/*.png) from the real GUI with sample data.

    python scripts/make_screenshots.py

Needs `mss` (see requirements-dev.txt). The windows are briefly shown on top of everything while
they are captured. No real games or accounts are used: all data below is made up.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["CHESSMIND_DEBUG"] = "1"                       # keep the GUI visible to screen capture
os.environ.setdefault("CHESSMIND_LOG_DIR", tempfile.mkdtemp(prefix="chessmind-shots-"))

import chess  # noqa: E402
import cv2  # noqa: E402
import mss  # noqa: E402
import numpy as np  # noqa: E402

import gui  # noqa: E402
from chessmind import stats, training  # noqa: E402

OUT = ROOT / "docs" / "images"
FEN_MID = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3"
FEN_AFTER_E4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"


def pump(app, n=10):
    for _ in range(n):
        app.root.update()
        time.sleep(0.06)


def shot(app, win, name, x=20, y=10):
    win.geometry(f"+{x}+{y}")
    win.attributes("-topmost", True)
    pump(app)
    X, Y, W, H = win.winfo_rootx(), win.winfo_rooty(), win.winfo_width(), win.winfo_height()
    with mss.MSS() as s:
        img = np.array(s.grab({"left": X, "top": Y, "width": W, "height": H}))
    OUT.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUT / name), img)
    print(f"{name}: {W}x{H}")


def sample_games(directory):
    def mv(number, san, best, label, loss, fen, ev_best=0.8):
        return dict(number=number, san=san, best_san=best, ev_best=ev_best, ev_played=0.0, loss=loss,
                    label=label, fen_before=fen, line=[f"{number} {best} e5 Nf3"])

    def game(date, acc, outcome, opp, opening, moves, counts):
        return dict(date=date, summary=dict(moves=24, accuracy=acc, opening=opening, result=None,
                                            outcome=outcome, opponent=opp, counts=counts), moves=moves)

    rows = [
        (72, "loss", {"name": "Bot A", "rating": 2200}, "Ruy Lopez, Berlin Defense"),
        (81, "win", {"name": "Bot B", "rating": 1500}, "Sicilian Defense"),
        (65, "loss", {"name": "Bot A", "rating": 2200}, "Ruy Lopez, Berlin Defense"),
        (88, "win", {"name": "Bot B", "rating": 1500}, "Italian Game"),
        (91, "win", {"name": "Bot C", "rating": 1800}, "Queen's Gambit Declined"),
        (84, "win", {"name": "Bot A", "rating": 2200}, "Italian Game"),
    ]
    for i, (acc, outcome, opp, opening) in enumerate(rows):
        moves = []
        if i == 0:
            moves = [mv("3.", "Bb5", "Bc4", "mistake", 14.0, FEN_MID),
                     mv("12.", "h3", "Rfe1", "inaccuracy", 6.0, chess.STARTING_FEN, 0.5)]
        elif i == 1:
            moves = [mv("1...", "f6", "e5", "blunder", 25.0, FEN_AFTER_E4)]
        counts = dict(best=14, excellent=5, good=3, inaccuracy=1, mistake=int(i == 0), blunder=int(i == 1))
        date = f"2026100{i + 1}-1{i}0000"
        (directory / f"{date}.json").write_text(
            json.dumps(game(date, acc, outcome, opp, opening, moves, counts)), encoding="utf-8")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="chessmind-shots-"))
    games = tmp / "games"
    games.mkdir()
    sample_games(games)
    training.GAMES_DIR = stats.GAMES_DIR = games
    training.PROGRESS_PATH = tmp / "progress.json"

    app = gui.App()
    app.root.geometry("+20+10")

    # 1) main window, mid-game, autopilot with adaptive strength
    app.board = chess.Board(FEN_MID)
    app.set_sugg([("f1b5", "Bb5", "+0.42"), ("f1c4", "Bc4", "+0.35"), ("d2d4", "d4", "+0.28")])
    app.line_lbl.configure(text="3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7  (forca limitada: 2400)")
    app.last_lbl.configure(text="Seu lance 2. Nf3: Excelente", fg=gui.GREEN)
    app.set_state("live", "Sua vez.")
    app.cal_label.configure(text="✓ Calibrado · voce joga de brancas", fg=gui.GREEN)
    app.autoplay.set(True)
    app.chk_adaptive.configure(text="Forca adaptativa: 2400 (Bot A)")
    app.review_data = json.loads(next(games.glob("*.json")).read_text(encoding="utf-8"))
    app.btn_review.state(["!disabled"])
    app.sync_settings()
    shot(app, app.root, "main.png")

    # 2) post-game review
    rw = gui.ReviewWindow(app, app.review_data)
    shot(app, rw, "review.png", x=820)
    rw.destroy()

    # 3) trainer, after a wrong answer (arrow: best move green, played move red)
    tw = gui.TrainerWindow(app)
    ex = tw.ex
    best = chess.Board(ex.fen).parse_san(ex.best_san)
    wrong = chess.Move.from_uci("a7a6" if not ex.white_to_move else "a2a3")
    tw._answered = True
    tw._finish("wrong", -0.7, move=wrong)
    shot(app, tw, "trainer.png", x=60)
    tw.close()

    # 4) statistics
    sw = gui.StatsWindow(app)
    shot(app, sw, "stats.png", x=300)
    sw.destroy()

    # 5) installation check, in a "fresh machine" scenario (no Stockfish, no optional data)
    from chessmind import book, config, installer
    config.find_stockfish = lambda: (_ for _ in ()).throw(FileNotFoundError())
    book.ECO_BOOK = tmp / "no-book.bin"
    installer.SYZYGY_DIR = tmp / "no-tablebases"
    os.environ.pop("ANTHROPIC_API_KEY", None)
    setup = gui.SetupWindow(app)
    shot(app, setup, "setup.png", x=400)
    app.root.destroy()


if __name__ == "__main__":
    main()
