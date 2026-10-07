import chess
import cv2
import numpy as np
import pytest

from chessmind import collect, vision
from chessmind.tracker import placement_of


def render(board, white_bottom=True, px=400):
    """Tabuleiro sintetico simples: casas claras/escuras e uma letra por peca."""
    s = px // 8
    img = np.zeros((px, px, 3), np.uint8)
    for r in range(8):
        for c in range(8):
            img[r * s:(r + 1) * s, c * s:(c + 1) * s] = (181, 217, 240) if (r + c) % 2 == 0 else (99, 136, 181)
            f = c if white_bottom else 7 - c
            rank = 7 - r if white_bottom else r
            p = board.piece_at(chess.square(f, rank))
            if p:
                cv2.putText(img, p.symbol(), (c * s + s // 4, r * s + 3 * s // 4), cv2.FONT_HERSHEY_SIMPLEX,
                            1.2, (250, 250, 250) if p.color else (20, 20, 20), 3)
    return img


@pytest.mark.parametrize("white_bottom", [True, False])
def test_labels_match_the_squares_on_screen(white_bottom):
    b = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3")
    X, y = collect.labeled_squares(render(b, white_bottom), placement_of(b), white_bottom)
    assert X.shape == (64, vision.SZ, vision.SZ, 3) and y.shape == (64,)
    assert (y != ".").sum() == 32 - 0 and set(y) <= set("PNBRQKpnbrqk.")
    # a primeira casa da tela e a8 (brancas embaixo) ou h1 (pretas embaixo)
    assert y[0] == ("r" if white_bottom else "R")
    # a casa e4 (peao branco) esta onde a tela diz
    row, col = (4, 4) if white_bottom else (3, 3)
    assert y[row * 8 + col] == "P"


def test_save_and_count(tmp_path):
    b = chess.Board()
    path = collect.save_sample(render(b), placement_of(b), True, site="chess.com", directory=tmp_path)
    assert path.exists() and collect.count(tmp_path) == 1
    data = np.load(path)
    assert data["X"].shape == (64, vision.SZ, vision.SZ, 3) and str(data["site"]) == "chess.com"
    assert collect.count(tmp_path / "nao-existe") == 0
