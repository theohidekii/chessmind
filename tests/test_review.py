import json

import chess

from chessmind import review
from chessmind.openings import opening_name
from chessmind.review import GameReview, classify, move_accuracy, win_percent


class FakeCoach:
    def __init__(self, ev):
        self.ev, self.calls = ev, 0

    def eval_after(self, board, move):
        self.calls += 1
        return self.ev


def sugg_for(board, uci_evs):
    return [(chess.Move.from_uci(u), ev, board.san(chess.Move.from_uci(u))) for u, ev in uci_evs]


def test_win_percent_is_monotonic_and_bounded():
    assert win_percent(0) == 50
    assert win_percent(1) > 50 > win_percent(-1)
    assert 0 <= win_percent(-50) < win_percent(50) <= 100


def test_classification_thresholds():
    assert classify(0.3, 0.3, True) == ("best", 0)
    assert classify(0.3, 0.25, False)[0] in ("best", "excellent")
    assert classify(0.3, -0.5, False)[0] in ("good", "inaccuracy")
    assert classify(0.5, -1.5, False)[0] == "mistake"
    assert classify(1.0, -9.0, False)[0] == "blunder"
    assert classify(-5.0, -5.0, False)[0] == "best"          # sem perda


def test_accuracy_drops_with_loss():
    assert move_accuracy(0) > 99 and move_accuracy(30) < 40 and move_accuracy(100) >= 0


def test_known_move_uses_suggestion_eval_without_extra_analysis():
    b = chess.Board()
    rv = GameReview(True)
    rv.start_turn(b, sugg_for(b, [("e2e4", "+0.30"), ("d2d4", "+0.28")]), [chess.Move.from_uci("e2e4")])
    b.push_san("d4")                                          # jogou o 2o melhor
    coach = FakeCoach(9)
    mr = rv.observe(b, coach)
    assert mr.san == "d4" and mr.ev_played == 0.28 and coach.calls == 0
    assert mr.label in ("best", "excellent") and mr.number == "1."


def test_unknown_move_is_analysed_and_flagged_as_blunder():
    b = chess.Board("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2")
    rv = GameReview(True)
    rv.start_turn(b, sugg_for(b, [("g1f3", "+0.40")]), [])
    b.push_san("Qh5")
    b.push_san("Nc6")                                         # adversario ja respondeu
    mr = rv.observe(b, FakeCoach(-6.0))
    assert mr.san == "Qh5" and mr.label == "blunder" and mr.best_san == "Nf3"
    assert mr.number == "2."


def test_black_move_number_and_resync_drops_pending():
    b = chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")
    rv = GameReview(False)
    rv.start_turn(b, sugg_for(b, [("e7e5", "+0.2")]), [])
    b.push_san("e5")
    assert rv.observe(b, FakeCoach(0)).number == "1..."
    rv.start_turn(b, sugg_for(b, [("g1f3", "+0.2")]), [])
    assert rv.observe(chess.Board(), FakeCoach(0)) is None   # tabuleiro trocado: nao identifica
    assert rv.pending is None


def test_summary_save_and_pgn(tmp_path, monkeypatch):
    monkeypatch.setattr(review, "GAMES_DIR", tmp_path)
    b = chess.Board()
    rv = GameReview(True)
    for san, ev in (("e4", "+0.3"), ("Nf3", "+0.3"), ("Bb5", "+0.3")):
        uci = b.parse_san(san).uci()
        rv.start_turn(b, sugg_for(b, [(uci, ev)]), [])
        b.push_san(san)
        rv.observe(b, FakeCoach(0))
        reply = {"e4": "e5", "Nf3": "Nc6"}.get(san)
        if reply:
            b.push_san(reply)
    s = rv.summary(b)
    assert s["moves"] == 3 and s["opening"] == "Ruy Lopez" and s["accuracy"] > 90
    path = rv.save(b)
    assert path.exists() and (tmp_path / path.name.replace(".json", ".pgn")).exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["moves"]) == 3
    assert rv.save(b) == path                                # nao grava duas vezes


def test_opening_names_pick_most_specific():
    assert opening_name(["e4", "c5", "Nf3", "d6", "d4", "cxd4", "Nxd4", "Nf6", "Nc3", "a6"]) == "Siciliana Najdorf"
    assert opening_name(["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5", "c3"]) == "Giuoco Piano"
    assert opening_name(["a3"]) is None


def test_explain_prompt_and_availability(monkeypatch):
    from chessmind import explain
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ok, why = explain.available()
    assert not ok and "ANTHROPIC_API_KEY" in why
    p = explain.build_prompt("fen", "brancas", "Nf3", "1. Nf3 d5", "+0.3", "a3", "Gafe", 25)
    assert "Nf3" in p and "a3" in p and "Gafe" in p


def test_opening_uses_full_eco_table_when_installed(tmp_path, monkeypatch):
    from chessmind import book, openings
    d = tmp_path / "eco"
    d.mkdir()
    (d / "a.tsv").write_text(
        "eco\tname\tpgn\n"
        "C84\tRuy Lopez: Closed\t1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7\n",
        encoding="utf-8")
    monkeypatch.setattr(book, "ECO_DIR", d)
    openings.reset_cache()
    try:
        assert openings.opening_name("e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1".split()) == "Ruy Lopez: Closed"
        assert openings.opening_name(["e4", "c5"]) == "Defesa Siciliana"      # cai na lista embutida
    finally:
        openings.reset_cache()



def test_parse_opponent_and_infer_outcome():
    from chessmind.review import infer_outcome, outcome_from_result, parse_opponent
    assert parse_opponent("Nora (2200) 5:41") == {"name": "Nora", "rating": 2200}
    assert parse_opponent("  ") is None and parse_opponent("Stockfish")["rating"] is None
    assert infer_outcome("Você ganhou! por xeque-mate") == "win"
    assert infer_outcome("You lost on time") == "loss"
    assert infer_outcome("Empate por acordo") == "draw"
    assert infer_outcome("Nora Won by checkmate", "Nora") == "loss"          # cita o adversario: inverte
    assert infer_outcome("Nora perdeu", "Nora") == "win"
    assert infer_outcome("", "Nora") is None and infer_outcome("Nova partida") is None
    assert outcome_from_result("1-0", True) == "win" and outcome_from_result("1-0", False) == "loss"
    assert outcome_from_result("1/2-1/2", True) == "draw" and outcome_from_result("*", True) is None


def test_summary_includes_opponent_and_outcome(tmp_path, monkeypatch):
    monkeypatch.setattr(review, "GAMES_DIR", tmp_path)
    b = chess.Board()
    rv = GameReview(True)
    rv.start_turn(b, sugg_for(b, [("e2e4", "+0.3")]), [])
    b.push_san("e4")
    rv.observe(b, FakeCoach(0))
    rv.opponent = {"name": "Nora", "rating": 2200}
    rv.outcome = "loss"                      # partida sem final no tabuleiro (abandono/tempo)
    s = rv.summary(b)
    assert s["opponent"]["name"] == "Nora" and s["outcome"] == "loss" and s["result"] is None


def test_tablebase_eval_texts_map_to_pawns():
    from chessmind.timing import ev_to_pawns
    assert ev_to_pawns("TB+") == 10 and ev_to_pawns("TB=") == 0 and ev_to_pawns("TB-") == -10
