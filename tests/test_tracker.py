import chess

from chessmind.tracker import Tracker, board_from_moves, placement_of


def mid_game(san_moves):
    b = chess.Board()
    for m in san_moves:
        b.push_san(m)
    return b


def test_start_position_resyncs_to_initial_board():
    t = Tracker(True)
    assert t.update(placement_of(chess.Board()))
    assert t.board.fen() == chess.Board().fen() and t.source == "inicio"


def test_follows_normal_moves_and_two_plies_between_reads():
    t = Tracker(True)
    t.update(placement_of(chess.Board()))
    b = chess.Board()
    b.push_san("e4")
    assert t.update(placement_of(b))
    b.push_san("e5"); b.push_san("Nf3")          # dois lances entre duas leituras
    assert t.update(placement_of(b))
    assert t.board.fen() == b.fen()


def test_unchanged_position_returns_false():
    t = Tracker(True)
    t.update(placement_of(chess.Board()))
    assert t.update(placement_of(chess.Board())) is False


def test_join_midgame_with_move_list_is_exact():
    b = mid_game(["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6", "O-O"])   # roque ja feito
    t = Tracker(True)
    assert t.update(placement_of(b), {"moves": ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6", "O-O"]})
    assert t.source == "lances"
    assert t.board.fen() == b.fen()                       # vez, roque e contadores exatos
    assert t.board.turn == chess.BLACK


def test_move_list_that_does_not_match_board_is_ignored():
    b = mid_game(["e4", "e5", "Nf3"])
    t = Tracker(True)
    assert t.update(placement_of(b), {"moves": ["d4", "d5"], "turn": "b"})
    assert t.source != "lances" and t.board.turn == chess.BLACK


def test_invalid_san_in_move_list_returns_none():
    assert board_from_moves(["e4", "e5", "Qh9"]) is None


def test_turn_from_clock_when_both_turns_are_legal():
    b = mid_game(["e4", "e5", "Nf3", "Nc6"])             # vez das brancas
    t = Tracker(False)                                    # usuario de pretas: suposicao daria errado
    assert t.update(placement_of(b), {"turn": "w"})
    assert t.board.turn == chess.WHITE and t.source == "relogio"


def test_turn_from_last_move_highlight():
    b = mid_game(["e4", "e5", "Nf3", "Nc6"])
    t = Tracker(False)
    assert t.update(placement_of(b), {"highlights": ["b8", "c6"]})   # pretas acabaram de jogar
    assert t.board.turn == chess.WHITE and t.source == "destaque"


def test_legality_filter_decides_turn_when_black_is_in_check():
    b = mid_game(["e4", "f6", "Qh5"])                    # xeque: so as pretas podem jogar
    t = Tracker(True)                                     # suposicao (brancas) seria ilegal
    assert t.update(placement_of(b), {})
    assert t.board.turn == chess.BLACK and t.source == "legalidade"
    assert all(m for m in t.board.legal_moves)


def test_en_passant_inferred_from_double_push_highlight():
    b = mid_game(["e4", "a6", "e5", "d5"])
    t = Tracker(True)
    assert t.update(placement_of(b), {"highlights": ["d7", "d5"]})
    assert t.board.ep_square == chess.D6
    assert chess.Move.from_uci("e5d6") in t.board.legal_moves


def test_castling_rights_inferred_from_home_squares():
    b = mid_game(["e4", "e5", "Nf3", "Nc6"])
    t = Tracker(True)
    t.update(placement_of(b), {"turn": "w"})
    assert chess.Move.from_uci("e1g1") not in t.board.legal_moves     # f1/g1: bispo e cavalo? (g1 livre, f1 ocupado)
    b2 = mid_game(["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5"])
    t2 = Tracker(True)
    t2.update(placement_of(b2), {"turn": "w"})
    assert chess.Move.from_uci("e1g1") in t2.board.legal_moves        # pode rocar
    assert t2.board.has_kingside_castling_rights(chess.WHITE)


def test_no_castling_right_when_king_left_home():
    b = mid_game(["e4", "e5", "Ke2", "Ke7"])
    t = Tracker(True)
    t.update(placement_of(b), {"turn": "w"})
    assert not t.board.has_castling_rights(chess.WHITE)


def test_noisy_reading_without_kings_is_rejected():
    t = Tracker(True)
    assert t.update({"e4": "P", "e5": "p", "a1": "R"}) is False
