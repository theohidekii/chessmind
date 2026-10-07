"""Testes da leitura do DOM e das setas num Chrome real (headless), com paginas que imitam
a estrutura do chess.com e do Lichess. Pulados se o Chrome nao estiver instalado."""
import time
from pathlib import Path

import chess
import pytest

from chessmind import pwsource
from chessmind.pwsource import JS_DOM, JS_DRAW, JS_HIDE, JS_STATE, arrows_svg, square_center_xy
from chessmind.tracker import Tracker, board_from_moves, placement_of

CHROME = next((p for p in pwsource.CHROME_PATHS if Path(p).exists()), None)
needs_chrome = pytest.mark.skipif(CHROME is None, reason="Chrome nao encontrado")


@pytest.fixture(scope="module")
def page():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, headless=True)
        yield browser.new_page(viewport={"width": 900, "height": 700})
        browser.close()


# ---------- geradores de HTML ----------
def chesscom_html(board, highlights=(), clocks=None, turn=None, moves=None, over=False, flipped=False,
                  opponent=None, modal_text=""):
    pieces = "".join(
        f'<div class="piece {"w" if p.color else "b"}{p.symbol().lower()} '
        f'square-{chess.square_file(s) + 1}{chess.square_rank(s) + 1}"></div>'
        for s, p in board.piece_map().items())
    hl = "".join(f'<div class="highlight square-{chess.square_file(chess.parse_square(h)) + 1}'
                 f'{chess.square_rank(chess.parse_square(h)) + 1}"></div>' for h in highlights)
    clk = ""
    for col, secs in (clocks or {}).items():
        name = "white" if col == "w" else "black"
        cls = f"clock-component clock-{name}" + (" clock-player-turn" if turn == col else "")
        clk += f'<div class="{cls}">{secs}</div>'
    ml = ""
    for i, san in enumerate(moves or [], 1):
        letter = san[0] if san[0] in "NBRQK" else None
        body = san[1:] if letter else san
        fig = f' data-figurine="{letter}"' if letter else ""
        ml += (f'<div class="node" data-ply="{i}"><span class="node-highlight-content"></span>'
               f'<span class="move-text-component"{fig}>{body}</span><span class="t">1.2s</span></div>')
    modal = (f'<div class="game-over-modal-container"><h2>{modal_text}</h2><button>Nova partida</button></div>'
             if over else "")
    top = f'<div class="player-top">{opponent}</div>' if opponent else ""
    return (f'<html><body><wc-chess-board class="board{" flipped" if flipped else ""}" '
            f'style="display:block;width:400px;height:400px;position:relative">{pieces}{hl}</wc-chess-board>'
            f'{top}{clk}<div id="ml">{ml}</div>{modal}</body></html>')


def lichess_html(board, white_bottom=True, size=400):
    sq = size / 8
    pieces = ""
    names = {"p": "pawn", "n": "knight", "b": "bishop", "r": "rook", "q": "queen", "k": "king"}
    for s, p in board.piece_map().items():
        f, r = chess.square_file(s), chess.square_rank(s)
        x = (f if white_bottom else 7 - f) * sq
        y = ((7 - r) if white_bottom else r) * sq
        pieces += (f'<piece class="{"white" if p.color else "black"} {names[p.symbol().lower()]}" '
                   f'style="transform: translate({x}px, {y}px);"></piece>')
    cls = "cg-wrap" + ("" if white_bottom else " orientation-black")
    return (f'<html><body><div class="{cls}"><cg-container><cg-board '
            f'style="display:block;width:{size}px;height:{size}px">{pieces}</cg-board></cg-container>'
            f'</div></body></html>')


POSITIONS = [
    chess.Board(),
    chess.Board("r1bq1rk1/pp2bppp/2n1pn2/2pp4/3P1B2/2PBPN2/PP1N1PPP/R2QK2R w KQ - 0 9"),
    chess.Board("8/5pk1/6p1/8/3Q4/6P1/5PK1/7q b - - 0 1"),
]


# ---------- leitura das pecas ----------
@needs_chrome
@pytest.mark.parametrize("board", POSITIONS)
def test_chesscom_pieces_read_exactly(page, board):
    page.set_content(chesscom_html(board))
    assert page.evaluate(JS_DOM) == placement_of(board)


@needs_chrome
@pytest.mark.parametrize("board", POSITIONS)
@pytest.mark.parametrize("white_bottom", [True, False])
def test_lichess_pieces_read_exactly_in_both_orientations(page, board, white_bottom):
    page.set_content(lichess_html(board, white_bottom))
    assert page.evaluate(JS_DOM) == placement_of(board)


@needs_chrome
def test_unknown_site_returns_null(page):
    page.set_content("<html><body><div>nada de xadrez</div></body></html>")
    assert page.evaluate(JS_DOM) is None


# ---------- estado da partida ----------
@needs_chrome
def test_state_reads_clocks_turn_highlights(page):
    b = board_from_moves(["e4", "e5", "Nf3"])
    page.set_content(chesscom_html(b, highlights=["g1", "f3"], clocks={"w": "1:02:03", "b": "4:07.5"}, turn="b"))
    st = page.evaluate(JS_STATE)
    assert st["clocks"]["w"] == 3723 and abs(st["clocks"]["b"] - 247.5) < 1e-6
    assert st["turn"] == "b" and sorted(st["highlights"]) == ["f3", "g1"] and st["over"] is False


@needs_chrome
def test_state_move_list_with_figurines_reproduces_the_game(page):
    moves = ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Bxc6", "dxc6", "O-O", "Bg4", "h3", "Bh5"]
    b = board_from_moves(moves)
    page.set_content(chesscom_html(b, moves=moves))
    st = page.evaluate(JS_STATE)
    assert st["moves"] == moves
    t = Tracker(True)
    assert t.update(placement_of(b), st) and t.source == "lances" and t.board.fen() == b.fen()


@needs_chrome
def test_non_contiguous_move_list_is_discarded(page):
    b = board_from_moves(["e4", "e5"])
    page.set_content(chesscom_html(b).replace('<div id="ml"></div>',
                     '<div id="ml"><div data-ply="1"><span class="move-text-component">e4</span></div>'
                     '<div data-ply="3"><span class="move-text-component">Nf3</span></div></div>'))
    assert page.evaluate(JS_STATE)["moves"] is None


@needs_chrome
def test_game_over_modal_detected(page):
    page.set_content(chesscom_html(chess.Board(), over=True))
    assert page.evaluate(JS_STATE)["over"] is True
    page.set_content(chesscom_html(chess.Board(), over=False))
    assert page.evaluate(JS_STATE)["over"] is False


# ---------- setas ----------
@needs_chrome
def test_arrows_draw_hide_and_expire_by_themselves(page):
    page.set_content(chesscom_html(chess.Board()))
    page.evaluate(JS_DRAW, {"svg": arrows_svg(["e2e4", "g1f3"], True), "x": 8, "y": 8, "w": 400, "h": 400})
    assert page.evaluate("document.querySelectorAll('#__cm_arrows line').length") == 2
    page.evaluate(JS_HIDE)
    assert page.evaluate("!!document.getElementById('__cm_arrows')") is False
    # sem renovacao, as setas somem sozinhas (protege contra coach travado)
    page.evaluate(JS_DRAW, {"svg": arrows_svg(["e2e4"], True), "x": 8, "y": 8, "w": 400, "h": 400})
    page.evaluate("window.__cmExp = Date.now() - 1")
    time.sleep(1.3)
    assert page.evaluate("!!document.getElementById('__cm_arrows')") is False


# ---------- geometria (sem navegador) ----------
RECT = {"x": 40, "y": 40, "w": 400}


def test_square_centers_white_and_black_bottom():
    x, y, sq = square_center_xy(RECT, "a1", True)
    assert (x, y, sq) == (40 + 25, 40 + 7 * 50 + 25, 50)
    assert square_center_xy(RECT, "h8", True)[:2] == (40 + 7 * 50 + 25, 40 + 25)
    assert square_center_xy(RECT, "a1", False)[:2] == (40 + 7 * 50 + 25, 40 + 25)   # tabuleiro girado
    assert square_center_xy(RECT, "e4", True)[:2] == (40 + 4 * 50 + 25, 40 + 4 * 50 + 25)
    assert square_center_xy(RECT, "e4", False)[:2] == (40 + 3 * 50 + 25, 40 + 3 * 50 + 25)


def test_arrows_svg_has_a_line_and_head_per_move_and_caps_at_three():
    svg = arrows_svg(["e2e4", "g1f3", "d2d4", "b1c3"], True)
    assert svg.count("<line") == 3 and svg.count("<polygon") == 3
