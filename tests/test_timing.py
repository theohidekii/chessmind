import random

import chess

from chessmind.timing import complexity_factor, ev_to_pawns, human_delay, think_budget


def test_ev_to_pawns():
    assert ev_to_pawns("+0.30") == 0.3 and ev_to_pawns("-1.5") == -1.5
    assert ev_to_pawns("#3") == 10 and ev_to_pawns("#-2") == -10 and ev_to_pawns("??") == 0


def test_single_legal_move_is_instant():
    b = chess.Board("7k/8/8/8/8/8/5q2/K7 w - - 0 1")     # unico lance legal: Kxa... (rei encurralado)
    assert b.legal_moves.count() == 1
    assert think_budget(2.0, None, b) == 0.1
    assert human_delay(1.0, b, [], None, None, random.Random(1)) <= 0.5


def test_clock_limits_thinking_time():
    b = chess.Board()
    assert think_budget(2.0, None, b) == 2.0
    assert think_budget(2.0, 20, b) == 0.5               # 20s / 40
    assert think_budget(2.0, 1, b) == 0.1                # nunca abaixo de 0.1


def test_opening_and_clear_best_are_faster_than_tight_middlegame():
    mid = chess.Board("r1bq1rk1/pp2bppp/2n1pn2/2pp4/3P1B2/2PBPN2/PP1N1PPP/R2QK2R w KQ - 0 9")
    sugg = [(chess.Move.from_uci("e1g1"), "+0.2", "O-O")]
    assert complexity_factor(chess.Board(), sugg, 0.1) < complexity_factor(mid, sugg, 0.1)
    clear, normal, tight = (complexity_factor(mid, sugg, g) for g in (2.5, 0.6, 0.1))
    assert clear < normal < tight


def test_recapture_is_faster():
    b = chess.Board()
    for m in ["e4", "d5", "exd5"]:
        b.push_san(m)
    best = [(chess.Move.from_uci("d8d5"), "+0.0", "Qxd5")]   # recaptura em d5
    other = [(chess.Move.from_uci("g8f6"), "+0.0", "Nf6")]
    assert complexity_factor(b, best, 0.6) < complexity_factor(b, other, 0.6)


def test_low_clock_forces_quick_moves_and_delay_is_bounded():
    b = chess.Board("r1bq1rk1/pp2bppp/2n1pn2/2pp4/3P1B2/2PBPN2/PP1N1PPP/R2QK2R w KQ - 0 9")
    sugg = [(chess.Move.from_uci("e1g1"), "+0.2", "O-O")]
    rng = random.Random(7)
    for _ in range(200):
        assert human_delay(2.0, b, sugg, 0.1, 10, rng) <= 0.4
        d = human_delay(2.0, b, sugg, 0.1, None, rng)
        assert 0.15 <= d <= 6.0
