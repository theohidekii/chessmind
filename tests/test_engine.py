import time

import chess
import pytest

from chessmind import config
from chessmind.engine import SYZYGY_DIR, Coach, position_key

try:
    config.find_stockfish()
    HAS_ENGINE = True
except FileNotFoundError:
    HAS_ENGINE = False

needs_engine = pytest.mark.skipif(not HAS_ENGINE, reason="Stockfish nao encontrado")


@pytest.fixture()
def coach(tmp_path):
    c = Coach(0.3, 2, None, 2, 64, syzygy_dir=tmp_path / "sem-tabelas")
    yield c
    c.close()


@needs_engine
def test_multi_ponder_has_ready_answers_for_the_likely_replies(coach):
    b = chess.Board("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    b.push_san("e4")                                   # vez do adversario (pretas)
    coach.start_multi_ponder(b, k=3)
    assert 2 <= len(coach._cands) <= 3                 # mais de uma resposta provavel
    t = time.time()
    while time.time() - t < 6:                         # o runner chama isso a cada ciclo
        coach.ponder_tick()
        time.sleep(0.1)
    depths = {k: v[0] for k, v in coach._cache.items()}
    coach._harvest()
    assert len(coach._cache) >= 2                      # as duas primeiras candidatas ja foram analisadas
    # o adversario joga uma das candidatas: resposta pronta, quase instantanea
    cands = list(coach._cands)
    reply = cands[0].peek()
    after = b.copy(); after.push(reply)
    t = time.time()
    sugg = coach.suggest(after)
    assert coach.last_from_ponder and time.time() - t < 0.2 and sugg


@needs_engine
def test_unlikely_reply_is_computed_normally(coach):
    b = chess.Board()
    b.push_san("e4")
    coach.start_multi_ponder(b, k=3)
    for _ in range(30):
        coach.ponder_tick()
        time.sleep(0.1)
    after = b.copy(); after.push_san("a6")             # resposta fora das candidatas
    sugg = coach.suggest(after)
    assert not coach.last_from_ponder and len(sugg) == 2


@needs_engine
def test_suggest_resets_ponder_state_and_survives_new_position(coach):
    b = chess.Board(); b.push_san("d4")
    coach.start_ponder(b.copy())
    coach.ponder_tick()
    s1 = coach.suggest(chess.Board("8/8/8/8/8/5k2/6q1/K7 w - - 0 1"))     # posicao qualquer
    assert s1 and coach._cands == [] and coach._ponder is None
    assert coach.eval_after(chess.Board(), chess.Move.from_uci("e2e4")) > -1


@needs_engine
def test_position_key_ignores_move_counters():
    a = chess.Board()
    b = chess.Board("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 5 9")
    assert position_key(a) == position_key(b)


@needs_engine
@pytest.mark.skipif(not (SYZYGY_DIR / "KQvK.rtbw").exists(), reason="tablebases Syzygy nao instaladas")
def test_tablebase_plays_kqk_to_mate_by_shortest_path():
    c = Coach(0.2, 3, None, 1, 64)
    try:
        b = chess.Board("8/8/8/8/8/2k5/8/K6Q w - - 0 1")
        for _ in range(12):                                  # KQvK: vence sempre, no maximo em ~10 lances
            if b.is_game_over():
                break
            sugg = c.tablebase_suggest(b)
            assert sugg and sugg[0][1] == "TB+"
            b.push(sugg[0][0])
            if b.is_game_over():
                break
            b.push(next(iter(b.legal_moves)))               # defesa qualquer
        assert b.is_checkmate()
    finally:
        c.close()


@needs_engine
def test_suggest_on_finished_game_returns_empty_instead_of_crashing(coach):
    mate = chess.Board("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")   # mate do louco
    assert mate.is_checkmate()
    assert coach.suggest(mate) == [] and coach.last_gap is None


# ---------------- forca limitada (UCI_Elo) ----------------
MIDDLEGAMES = [
    "r1bqk2r/pp2bppp/2n1pn2/2pp4/3P1B2/2PBPN2/PP1N1PPP/R2QK2R w KQkq - 0 9",
    "r2q1rk1/pp1bbppp/2n1pn2/2pp4/3P4/2PBPN2/PPQN1PPP/R1B2RK1 w - - 0 10",
    "r1bq1rk1/ppp2ppp/2np1n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 0 7",
    "2rq1rk1/pp2bppp/2n1pn2/3p4/3P1B2/2NBPN2/PP3PPP/R2Q1RK1 b - - 0 11",
    "r1bqkb1r/pp3ppp/2n1pn2/2pp4/2PP4/2N1PN2/PP3PPP/R1BQKB1R w KQkq - 0 6",
    "rnbq1rk1/pp2bppp/4pn2/2pp4/2PP4/2N2NP1/PP2PPBP/R1BQ1RK1 b - - 0 7",
    "r2qkb1r/pp1b1ppp/2n1pn2/2pp4/3P1B2/2N1PN2/PPQ2PPP/R3KB1R w KQkq - 0 8",
    "r1bq1rk1/pp1nbppp/2p1pn2/3p4/2PP4/2N1PN2/PPQ1BPPP/R1B2RK1 w - - 0 9",
]


@pytest.fixture()
def coach_weak(tmp_path):
    c = Coach(0.15, 3, None, 2, 64, syzygy_dir=tmp_path / "sem-tabelas")
    yield c
    c.close()


@needs_engine
def test_elo_range_is_read_from_the_engine(coach_weak):
    assert coach_weak.elo_range == (1320, 3190)


@needs_engine
def test_limited_suggestions_keep_the_full_strength_analysis_intact(coach_weak):
    c = coach_weak
    for fen in MIDDLEGAMES[:4]:
        b = chess.Board(fen)
        sugg = c.suggest(b, elo=1320)
        best = c.last_full[0]
        assert sugg[0][0] in b.legal_moves and c.last_weakened
        assert c.last_full[0][0] == best[0] and len(c.last_full) == len(c.last_full_pvs)
        assert len({m for m, _, _ in sugg}) == len(sugg) <= 3          # sem repetidos, no maximo `lines`
        assert len(c.last_pvs) == len(sugg) and c.last_pvs[0][0] == sugg[0][0]


@needs_engine
def test_limited_engine_really_loses_to_full_strength(coach_weak):
    """O que importa e o resultado: o motor sem limite ganha do nivel 1320 (cp perdido em posicoes
    calmas nao separa os niveis; a fraqueza aparece nas taticas, ao longo da partida)."""
    e = coach_weak.engine
    score = 0.0
    for game in range(2):                                  # uma partida com cada cor
        b = chess.Board()
        limited_color = chess.BLACK if game == 0 else chess.WHITE
        while not b.is_game_over(claim_draw=True) and b.ply() < 240:
            weak = b.turn == limited_color
            e.configure({"UCI_LimitStrength": weak, **({"UCI_Elo": 1320} if weak else {})})
            b.push(e.play(b, chess.engine.Limit(time=0.05)).move)
        r = b.result(claim_draw=True)
        full_points = {"1-0": 1, "0-1": 0, "1/2-1/2": 0.5, "*": 0.5}[r]
        score += full_points if limited_color == chess.BLACK else 1 - full_points
    e.configure({"UCI_LimitStrength": False})
    assert score >= 1.5                                    # ganha pelo menos 1,5 de 2 pontos


@needs_engine
def test_max_elo_or_none_means_full_strength(coach_weak):
    b = chess.Board(MIDDLEGAMES[0])
    for elo in (None, 3190, 3500):
        sugg = coach_weak.suggest(b, elo=elo)
        assert not coach_weak.last_weakened and sugg[0][0] == coach_weak.last_full[0][0]


@needs_engine
def test_strength_option_is_restored_after_a_limited_move(coach_weak):
    b = chess.Board(MIDDLEGAMES[1])
    coach_weak.suggest(b, elo=1320)
    best = coach_weak.engine.analyse(b, chess.engine.Limit(time=0.3))["pv"][0]     # forca total de novo
    again = coach_weak.suggest(b)                                                   # sem elo
    assert not coach_weak.last_weakened and again[0][0] == coach_weak.last_full[0][0]
    assert best in b.legal_moves
