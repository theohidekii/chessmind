import json

import chess
import pytest

from chessmind import explain, stats, training
from chessmind.training import Exercise, Progress, check_answer, load_exercises


def make_game(date, moves, summary_extra=None):
    summary = dict(moves=len(moves), accuracy=80.0, opening="Ruy Lopez", result="1-0", outcome="win",
                   opponent={"name": "Nora", "rating": 2200},
                   counts=dict(best=1, excellent=0, good=0, inaccuracy=1, mistake=0, blunder=0))
    summary.update(summary_extra or {})
    return dict(date=date, summary=summary, moves=moves)


def mv(number, san, best, label, loss, fen=chess.STARTING_FEN, ev_best=0.3):
    return dict(number=number, san=san, best_san=best, ev_best=ev_best, ev_played=0.0, loss=loss,
                label=label, fen_before=fen, line=[f"{number} {best}"])


@pytest.fixture()
def games_dir(tmp_path):
    d = tmp_path / "games"
    d.mkdir()
    after_e4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
    g1 = make_game("20261001-100000", [mv("1.", "a3", "e4", "inaccuracy", 6.0),
                                       mv("1...", "f6", "e5", "blunder", 25.0, after_e4),
                                       mv("2.", "Nf3", "Nf3", "best", 0)])
    g2 = make_game("20261002-110000", [mv("1.", "a3", "e4", "inaccuracy", 6.0)],      # mesmo erro repetido
                   dict(accuracy=60.0, outcome="loss", opening="Defesa Siciliana",
                        opponent={"name": "Wendy", "rating": 1500}))
    (d / "20261001-100000.json").write_text(json.dumps(g1), encoding="utf-8")
    (d / "20261002-110000.json").write_text(json.dumps(g2), encoding="utf-8")
    (d / "lixo.json").write_text("{ nao e json", encoding="utf-8")
    return d


# ---------------- treino ----------------
def test_exercises_come_from_mistakes_deduped_and_sorted_by_severity(games_dir):
    ex = load_exercises(games_dir)
    assert [e.played_san for e in ex] == ["f6", "a3"]            # gafe antes da imprecisao; repetido some
    assert ex[0].white_to_move is False and ex[1].white_to_move is True
    assert ex[0].title.startswith("1... f6") and "Gafe" in ex[0].title
    assert load_exercises(games_dir, labels=("blunder",))[0].played_san == "f6"
    assert load_exercises(games_dir / "nao-existe") == []


def test_correct_alternative_and_wrong_answers():
    ex = Exercise("x", chess.STARTING_FEN, True, "e4", "a3", "inaccuracy", 6.0, 0.3, "1. e4", "d", "1.")
    assert check_answer(ex, chess.Move.from_uci("e2e4")) == ("correct", 0.3)
    assert check_answer(ex, chess.Move.from_uci("a2a3")) == ("wrong", None)       # sem motor

    class FakeEngine:
        def __init__(self, ev): self.ev = ev
        def eval_after(self, board, move): return self.ev

    assert check_answer(ex, chess.Move.from_uci("d2d4"), FakeEngine(0.2)) == ("good", 0.2)    # alternativa boa
    assert check_answer(ex, chess.Move.from_uci("f2f3"), FakeEngine(-0.8)) == ("wrong", -0.8)


def test_spaced_repetition_boxes(tmp_path, games_dir):
    ex = load_exercises(games_dir)
    p = Progress(tmp_path / "p.json")
    now = 1_000_000.0
    assert len(p.due_exercises(ex, now)) == 2                    # novos
    p.record(ex[0].id, True, now)                                # acerto: caixa 1, volta em 1 dia
    assert [e.id for e in p.due_exercises(ex, now + 3600)] == [ex[1].id]
    assert ex[0].id in [e.id for e in p.due_exercises(ex, now + 86400 + 1)]
    p.record(ex[0].id, True, now + 86401)                        # caixa 2: 3 dias
    p.record(ex[0].id, False, now + 90000)                       # erro: volta para a caixa 0 (10 min)
    assert p.data[ex[0].id]["box"] == 0 and p.data[ex[0].id]["attempts"] == 3
    assert ex[0].id in [e.id for e in p.due_exercises(ex, now + 90000 + 601)]
    assert Progress(tmp_path / "p.json").data == p.data          # persistiu em disco
    s = p.summary(ex)
    assert s["total"] == 2 and s["practiced"] == 1 and s["attempts"] == 3 and s["correct"] == 2


def test_box_never_exceeds_last_interval(tmp_path):
    p = Progress(tmp_path / "p.json")
    for i in range(10):
        p.record("a", True, 0)
    assert p.data["a"]["box"] == len(training.BOX_SECONDS) - 1


# ---------------- estatisticas ----------------
def test_stats_totals_trend_opponents_and_openings(games_dir):
    games = stats.load_games(games_dir)
    assert len(games) == 2                                       # arquivo invalido ignorado
    r = stats.compute(games)
    t = r["total"]
    assert (t["games"], t["win"], t["loss"], t["draw"]) == (2, 1, 1, 0) and t["accuracy"] == 70.0
    assert r["trend"] == [("20261001-100000", 80.0), ("20261002-110000", 60.0)]
    assert {o["name"]: (o["games"], o["win"], o["rating"]) for o in r["opponents"]} == {
        "Nora": (1, 1, 2200), "Wendy": (1, 0, 1500)}
    assert {o["name"] for o in r["openings"]} == {"Ruy Lopez", "Defesa Siciliana"}
    assert r["errors"]["inaccuracy"] == 2
    assert stats.pretty_date("20261007-182230") == "07/10 18:22" and stats.pretty_date("x") == "x"


def test_stats_with_no_games():
    r = stats.compute([])
    assert r["total"]["games"] == 0 and r["total"]["accuracy"] is None and r["opponents"] == []


def test_unknown_outcome_and_missing_opponent_are_counted_safely():
    g = make_game("20261003-120000", [mv("1.", "e4", "e4", "best", 0)],
                  dict(outcome=None, opponent=None, accuracy=None, opening=None))
    r = stats.compute([g])
    assert r["total"]["unknown"] == 1 and r["opponents"][0]["name"] == "Desconhecido"
    assert r["trend"] == []


# ---------------- cache das explicacoes ----------------
def test_explanation_cache_avoids_second_api_call(tmp_path, monkeypatch):
    monkeypatch.setattr(explain, "CACHE_PATH", tmp_path / "c" / "explain.json")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-falsa")
    calls = []

    class FakeMsg:
        content = [type("B", (), {"type": "text", "text": "Boa jogada: centraliza o peao."})()]

    class FakeClient:
        def __init__(self, **kw): pass
        class messages:
            @staticmethod
            def create(**kw):
                calls.append(kw)
                return FakeMsg

    import types, sys
    fake = types.ModuleType("anthropic"); fake.Anthropic = FakeClient
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    p = explain.build_prompt("fen", "brancas", "e4", "1. e4 e5", "+0.3")
    assert not explain.is_cached(p)
    assert explain.explain(p) == "Boa jogada: centraliza o peao."
    assert explain.is_cached(p) and len(calls) == 1
    monkeypatch.delenv("ANTHROPIC_API_KEY")                       # sem chave: o cache ainda atende
    assert explain.explain(p) == "Boa jogada: centraliza o peao." and len(calls) == 1
    other = explain.build_prompt("fen2", "pretas", "e5", "1... e5", "+0.1")
    with pytest.raises(explain.ExplainUnavailable):
        explain.explain(other)


def test_cache_drops_oldest_beyond_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(explain, "CACHE_PATH", tmp_path / "explain.json")
    monkeypatch.setattr(explain, "CACHE_MAX", 3)
    for i in range(6):
        explain._store(f"prompt {i}", f"texto {i}")
    assert len(explain._load()) == 3
    assert explain.cached("prompt 5") == "texto 5" and explain.cached("prompt 0") is None
