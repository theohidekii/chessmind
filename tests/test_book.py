import random

import chess
import pytest

from chessmind import book as bk
from chessmind.book import Book, build_eco_book, build_polyglot, parse_pgn_moves, read_eco_tsv

TSV = (
    "eco\tname\tpgn\n"
    "C60\tRuy Lopez\t1. e4 e5 2. Nf3 Nc6 3. Bb5\n"
    "C65\tRuy Lopez: Berlin Defense\t1. e4 e5 2. Nf3 Nc6 3. Bb5 Nf6\n"
    "C78\tRuy Lopez: Morphy Defense\t1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O\n"
    "C50\tItalian Game\t1. e4 e5 2. Nf3 Nc6 3. Bc4\n"
    "B20\tSicilian Defense\t1. e4 c5\n"
    "D00\tQueen's Pawn Game\t1. d4 d5\n"
    "X99\tLinha invalida\t1. e4 e5 2. Qh9\n"
)


@pytest.fixture()
def eco_dir(tmp_path):
    d = tmp_path / "eco"
    d.mkdir()
    (d / "a.tsv").write_text(TSV, encoding="utf-8")
    return d


def test_parse_pgn_moves():
    assert parse_pgn_moves("1. e4 e5 2. Nf3 Nc6 3. Bb5 a6") == ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"]
    assert parse_pgn_moves("1. e4 c5 1-0") == ["e4", "c5"]


def test_read_eco_skips_header_and_invalid_lines(eco_dir):
    rows = read_eco_tsv(bk.eco_files(eco_dir))
    assert len(rows) == 6 and all(n != "Linha invalida" for _, n, _ in rows)


def test_build_and_read_book_roundtrip(eco_dir, tmp_path):
    out = tmp_path / "eco.bin"
    n = build_eco_book(eco_dir, out)
    assert n > 10
    book = Book([out], rng=random.Random(0))
    assert book.available()
    start = chess.Board()
    opts = book.moves(start)
    assert {chess.Move.from_uci("e2e4"), chess.Move.from_uci("d2d4")} == set(opts)
    assert opts[chess.Move.from_uci("e2e4")] > opts[chess.Move.from_uci("d2d4")]   # mais linhas passam por e4
    book.close()


def test_book_follows_lines_including_castling_and_stops_when_out_of_book(eco_dir, tmp_path):
    out = tmp_path / "eco.bin"
    build_eco_book(eco_dir, out)
    book = Book([out], rng=random.Random(1))
    b = chess.Board()
    for san in "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6".split():
        b.push_san(san)
    assert book.pick(b) == chess.Move.from_uci("e1g1")            # roque lido corretamente
    off = chess.Board()
    off.push_san("a3")
    assert book.pick(off) is None                                 # fora do livro
    book.close()


def test_pick_is_weighted_and_varies(eco_dir, tmp_path):
    out = tmp_path / "eco.bin"
    build_eco_book(eco_dir, out)
    book = Book([out], rng=random.Random(5))
    b = chess.Board()
    b.push_san("e4"); b.push_san("e5"); b.push_san("Nf3"); b.push_san("Nc6")
    seen = {book.pick(b) for _ in range(60)}
    assert seen == {chess.Move.from_uci("f1b5"), chess.Move.from_uci("f1c4")}


def test_book_not_used_after_max_ply(tmp_path):
    line = ["Nf3", "Nf6", "Ng1", "Ng8"] * 8                         # 32 lances, com livro ate o fim
    out = tmp_path / "long.bin"
    build_polyglot([("X", "longa", line)], out, max_plies=40)
    book = Book([out], rng=random.Random(0))
    b = chess.Board()
    for san in line[:bk.MAX_BOOK_PLY - 1]:
        b.push_san(san)
    assert book.pick(b) is not None                                # ainda dentro do limite
    b.push_san(line[bk.MAX_BOOK_PLY - 1])
    assert b.ply() == bk.MAX_BOOK_PLY
    assert book.moves(b) and book.pick(b) is None                  # o livro tem lance, mas passou do limite
    book.close()
    assert not Book([], rng=random.Random(0)).available()


def test_build_without_tsv_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_eco_book(tmp_path / "vazio", tmp_path / "x.bin")


def test_polyglot_handles_promotion_and_black_castling(tmp_path):
    entries = [("X", "teste", ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5", "O-O", "Nf6", "d3", "O-O"])]
    out = tmp_path / "t.bin"
    build_polyglot(entries, out)
    book = Book([out])
    b = chess.Board()
    for san in "e4 e5 Nf3 Nc6 Bc4 Bc5 O-O Nf6 d3".split():
        b.push_san(san)
    assert book.moves(b) == {chess.Move.from_uci("e8g8"): 1}       # roque preto
    book.close()
