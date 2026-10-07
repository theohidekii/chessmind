import json

import chess
import pytest

from chessmind import strength
from chessmind.strength import (DEFAULT_START, MAX_ELO, MIN_ELO, MID_MAX_BUMPS, START_MARGIN, STEP_DRAW,
                                STEP_LOSS, STEP_MID, StrengthManager)

NORA = {"name": "Nora", "rating": 2200}


@pytest.fixture()
def sm(tmp_path):
    return StrengthManager(tmp_path / "strength.json")


def test_starts_below_the_maximum_based_on_the_bot_rating(sm):
    assert sm.current(NORA) == 2200 + START_MARGIN                    # 2400
    assert sm.current({"name": "Wendy", "rating": 1500}) == 1700
    assert sm.current({"name": "Sem rating"}) == DEFAULT_START
    assert sm.current(None) == DEFAULT_START
    assert sm.current({"name": "Magnus", "rating": 3200}) == MAX_ELO - 100   # nunca comeca no maximo
    assert sm.current({"name": "Iniciante", "rating": 400}) == MIN_ELO       # nem abaixo do minimo


def test_rises_only_when_losing_or_drawing_never_on_wins(sm):
    start = sm.current(NORA)
    assert sm.record_game(NORA, "win") == start                        # venceu: mantem
    assert sm.record_game(NORA, "win") == start
    assert sm.record_game(NORA, "draw") == start + STEP_DRAW
    assert sm.record_game(NORA, "loss") == start + STEP_DRAW + STEP_LOSS
    assert sm.record_game(NORA, "win") == start + STEP_DRAW + STEP_LOSS    # nunca desce
    e = sm.data["nora"]
    assert (e["games"], e["wins"], e["draws"], e["losses"]) == (5, 3, 1, 1)


def test_unknown_outcome_changes_nothing(sm):
    start = sm.current(NORA)
    assert sm.record_game(NORA, None) == start and sm.data["nora"]["games"] == 0


def test_reaching_the_maximum_means_unlimited_strength(sm):
    sm.current(NORA)
    for _ in range(10):
        elo = sm.record_game(NORA, "loss")
    assert elo is None and sm.data["nora"]["elo"] == MAX_ELO
    assert sm.current(NORA) is None
    assert sm.record_game(NORA, "loss") is None                        # nao passa do maximo


def test_each_opponent_has_its_own_level(sm):
    sm.record_game(NORA, "loss")
    wendy = {"name": "Wendy", "rating": 1500}
    assert sm.current(wendy) == 1700
    assert sm.current({"name": "NORA"}) == sm.data["nora"]["elo"]       # nome sem diferenca de caixa


def test_midgame_bump_after_consecutive_bad_positions(sm):
    start = sm.current(NORA)
    assert sm.observe_eval(NORA, -3.0) is False                        # 1a posicao ruim: ainda nao
    assert sm.observe_eval(NORA, +0.5) is False                        # recuperou: zera a contagem
    assert sm.observe_eval(NORA, -2.5) is False
    assert sm.observe_eval(NORA, -2.5) == start + STEP_MID             # 2 seguidas: sobe na hora
    assert sm.current(NORA) == start + STEP_MID


def test_midgame_bumps_are_limited_per_game_and_reset_on_new_game(sm):
    start = sm.current(NORA)
    for _ in range(MID_MAX_BUMPS * 2 + 4):
        sm.observe_eval(NORA, -4.0)
    assert sm.current(NORA) == start + MID_MAX_BUMPS * STEP_MID        # limite de subidas
    sm.new_game()
    assert sm.observe_eval(NORA, -4.0) is False and sm.observe_eval(NORA, -4.0) is not False


def test_state_persists_and_reset_clears_it(tmp_path):
    p = tmp_path / "s.json"
    a = StrengthManager(p)
    a.record_game(NORA, "loss")
    expected = a.current(NORA)
    assert StrengthManager(p).current(NORA) == expected
    assert json.loads(p.read_text())["nora"]["losses"] == 1
    a.reset()
    assert StrengthManager(p).current(NORA) == 2400                     # recomeca do inicio


def test_corrupt_file_is_ignored(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{ nao e json")
    assert StrengthManager(p).current(NORA) == 2400


def test_custom_engine_range_is_respected(tmp_path):
    sm = StrengthManager(tmp_path / "s.json", lo=1500, hi=2500)
    assert sm.current({"name": "x", "rating": 800}) == 1500
    for _ in range(10):
        sm.record_game(NORA, "loss")
    assert sm.current(NORA) is None
