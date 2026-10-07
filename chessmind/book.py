"""Livro de aberturas (formato Polyglot) e tabela ECO.

- `Book` le qualquer `engine/books/*.bin` (Polyglot) e sorteia lances ponderados.
- `build_eco_book()` gera `engine/books/eco.bin` a partir da tabela ECO do Lichess
  (lichess-org/chess-openings, dominio publico): o peso de cada lance e quantas linhas nomeadas
  passam por ele, entao as linhas principais saem mais.
- Todo lance de livro e conferido pelo motor antes de ser usado (ver `runner`): um livro ruim
  nunca joga um lance claramente fraco.
"""
import random
import re
import struct
from collections import Counter, defaultdict
from pathlib import Path

import chess
import chess.polyglot

from .config import ROOT

BOOKS_DIR = ROOT / "engine" / "books"
ECO_DIR = BOOKS_DIR / "eco"
ECO_BOOK = BOOKS_DIR / "eco.bin"
MAX_BOOK_PLY = 24            # nao usa o livro depois de 12 lances de cada lado


# ---------------- tabela ECO ----------------
def parse_pgn_moves(pgn):
    """'1. e4 e5 2. Nf3' -> ['e4', 'e5', 'Nf3']"""
    pgn = re.sub(r"\d+\.(\.\.)?", " ", pgn)
    return [t for t in pgn.split() if t not in ("1-0", "0-1", "1/2-1/2", "*")]


def read_eco_tsv(paths):
    """[(eco, nome, [san...])] das planilhas TSV (cabecalho: eco, name, pgn). Linhas invalidas sao puladas."""
    out = []
    for path in paths:
        for i, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines()):
            parts = line.split("\t")
            if i == 0 and parts[0].lower() == "eco" or len(parts) < 3:
                continue
            eco, name, pgn = parts[0], parts[1], parts[2]
            sans = parse_pgn_moves(pgn)
            b = chess.Board()
            try:
                for s in sans:
                    b.push_san(s)
            except ValueError:
                continue
            out.append((eco, name, sans))
    return out


def eco_files(directory=None):
    return sorted((directory or ECO_DIR).glob("*.tsv"))


# ---------------- construcao do livro Polyglot ----------------
def _encode(board, move):
    """Lance no formato Polyglot (roque = rei 'captura' a propria torre)."""
    to_sq = move.to_square
    if board.is_castling(move):
        to_sq = chess.square(7 if chess.square_file(move.to_square) == 6 else 0,
                             chess.square_rank(move.from_square))
    promo = {None: 0, chess.KNIGHT: 1, chess.BISHOP: 2, chess.ROOK: 3, chess.QUEEN: 4}[move.promotion]
    return to_sq | (move.from_square << 6) | (promo << 12)


def build_polyglot(entries, out_path, max_plies=MAX_BOOK_PLY):
    """Grava um .bin Polyglot com os primeiros `max_plies` lances de cada linha de `entries`
    ([(eco, nome, [san...])]). Peso do lance = numero de linhas que passam por ele."""
    weights = defaultdict(Counter)       # chave da posicao -> {lance_codificado: peso}
    for _, _, sans in entries:
        b = chess.Board()
        for san in sans[:max_plies]:
            m = b.parse_san(san)
            weights[chess.polyglot.zobrist_hash(b)][_encode(b, m)] += 1
            b.push(m)
    rows = []
    for key in sorted(weights):
        for raw, w in weights[key].items():
            rows.append(struct.pack(">QHHI", key, raw, min(w, 65535), 0))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_bytes(b"".join(rows))
    return len(rows)


def build_eco_book(eco_dir=None, out_path=None):
    """Gera engine/books/eco.bin a partir de engine/books/eco/*.tsv. Retorna o n. de entradas."""
    files = eco_files(eco_dir)
    if not files:
        raise FileNotFoundError("Planilhas ECO nao encontradas em engine/books/eco/*.tsv")
    return build_polyglot(read_eco_tsv(files), out_path or ECO_BOOK)


# ---------------- uso ----------------
class Book:
    def __init__(self, paths=None, rng=random):
        paths = list(paths) if paths is not None else sorted(BOOKS_DIR.glob("*.bin"))
        self.rng = rng
        self.readers = [chess.polyglot.open_reader(str(p)) for p in paths if Path(p).exists()]

    def available(self):
        return bool(self.readers)

    def moves(self, board):
        """{lance: peso} somando todos os livros."""
        out = Counter()
        for r in self.readers:
            for e in r.find_all(board):
                if e.move in board.legal_moves:
                    out[e.move] += e.weight
        return out

    def pick(self, board):
        """Lance de livro sorteado (ponderado) ou None; nao usa o livro apos MAX_BOOK_PLY."""
        if not self.readers or board.ply() >= MAX_BOOK_PLY:
            return None
        opts = self.moves(board)
        if not opts:
            return None
        moves, weights = zip(*opts.items())
        return self.rng.choices(moves, weights=weights)[0]

    def close(self):
        for r in self.readers:
            r.close()
        self.readers = []
