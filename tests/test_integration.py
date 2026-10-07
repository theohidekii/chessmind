"""Integracao do ciclo inteiro (Runner + Stockfish + Chrome com CDP) numa partida simulada.
Pulado se faltar o Chrome ou o Stockfish."""
import json
import queue
import subprocess
import time
from pathlib import Path

import chess
import pytest

from chessmind import config, pwsource, review
from chessmind.runner import DEFAULT_SETTINGS, Runner
from chessmind.tracker import board_from_moves
from tests.test_dom import CHROME, chesscom_html

try:
    config.find_stockfish()
    HAS_ENGINE = True
except FileNotFoundError:
    HAS_ENGINE = False

pytestmark = pytest.mark.skipif(CHROME is None or not HAS_ENGINE, reason="precisa de Chrome e Stockfish")
PORT = 9444


@pytest.fixture(scope="module")
def browser_page(tmp_path_factory):
    """Um unico Chrome + Playwright para o modulo inteiro (reiniciar o Playwright a cada teste
    na mesma thread nao funciona)."""
    tmp = tmp_path_factory.mktemp("chrome")
    html = tmp / "game.html"
    html.write_text("<html><body></body></html>")
    proc = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={PORT}",
                             f"--user-data-dir={tmp / 'profile'}", "--no-first-run",
                             html.as_uri()], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = None
    for _ in range(40):
        try:
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
            break
        except Exception:
            time.sleep(0.25)
    assert browser is not None, "Chrome headless nao respondeu"
    yield browser.contexts[0].pages[0]
    pw.stop()
    proc.terminate()


@pytest.fixture()
def chrome(browser_page, tmp_path, monkeypatch):
    monkeypatch.setattr(pwsource, "CDP_URL", f"http://127.0.0.1:{PORT}")
    monkeypatch.setattr(config, "load_calibration", lambda: {"source": "playwright", "white_bottom": True})
    monkeypatch.setattr(review, "GAMES_DIR", tmp_path / "games")
    browser_page.set_content("<html><body></body></html>")
    return browser_page


def show(page, moves, **kw):
    b = board_from_moves(moves)
    page.set_content(chesscom_html(b, moves=moves, **kw))
    return b


def wait_for(q, kind, timeout=25, pred=lambda m: True):
    end, seen = time.time() + timeout, []
    while time.time() < end:
        try:
            m = q.get(timeout=0.5)
        except queue.Empty:
            continue
        seen.append(m)
        if m[0] == kind and pred(m):
            return m
        if m[0] == "error":
            pytest.fail(f"erro no Runner: {m[1]}")
    pytest.fail(f"nao chegou {kind!r}; mensagens: {[x[0] for x in seen][-15:]}")


def test_full_game_flow(chrome, tmp_path):
    page = chrome
    opening = ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6"]
    show(page, opening, clocks={"w": "5:00", "b": "5:00"}, turn="w")        # vez das brancas (voce)
    q = queue.Queue()
    settings = dict(DEFAULT_SETTINGS, show_arrows=True, ponder=True)
    r = Runner(q, "Rapida", 3, settings)
    r.start()
    try:
        # 1) entrou no meio da partida: estado exato pela lista de lances, sugestoes e linha prevista
        sugg = wait_for(q, "sugg")
        board = board_from_moves(opening)
        assert board.fen() == sugg[1]
        legal = {m.uci() for m in board.legal_moves}
        assert len(sugg[2]) == 3 and all(u in legal for u, _, _ in sugg[2])
        assert wait_for(q, "line")[1].startswith("5.")
        for _ in range(20):                                   # as setas sao desenhadas logo apos a linha
            n = page.evaluate("document.querySelectorAll('#__cm_arrows line').length")
            if n == 3:
                break
            time.sleep(0.2)
        assert n == 3                                         # setas na pagina

        # 2) voce joga o melhor lance; o adversario responde -> classificacao "melhor"
        best = chess.Move.from_uci(sugg[2][0][0])
        mine = board.san(best)
        board.push(best)
        show(page, opening + [mine], clocks={"w": "4:50", "b": "5:00"}, turn="b")
        opening2 = opening + [mine, "b5"]
        board.push_san("b5")
        show(page, opening2, clocks={"w": "4:50", "b": "4:55"}, turn="w")
        lm = wait_for(q, "lastmove")
        assert lm[2] == mine and lm[3] in ("best", "excellent")

        # 3) fim de jogo: a revisao e salva em disco
        wait_for(q, "sugg", pred=lambda m: m[1] == board.fen())
        show(page, opening2, clocks={"w": "4:50", "b": "4:55"}, turn="w", over=True)
        rv = wait_for(q, "review")
        assert rv[1]["moves"] == 1 and rv[1]["opening"] == "Ruy Lopez, Variante Morphy"
        data = json.loads(Path(rv[2]).read_text(encoding="utf-8"))
        assert data["moves"][0]["san"] == mine
    finally:
        r.stop()
        r.join(15)


# ---------------- livro de aberturas e ponder dentro do Runner ----------------
def run_runner(q, **settings):
    r = Runner(q, "Rapida", 3, dict(DEFAULT_SETTINGS, **settings))
    r.start()
    return r


def make_book(tmp_path, monkeypatch, san_line):
    from chessmind import book as bk
    d = tmp_path / "books"
    d.mkdir()
    bk.build_polyglot([("X", "teste", san_line)], d / "t.bin")
    monkeypatch.setattr(bk, "BOOKS_DIR", d)


def test_book_move_is_used_when_the_engine_agrees(chrome, tmp_path, monkeypatch):
    make_book(tmp_path, monkeypatch, ["d4"])                      # d4 e um bom lance (perda < 0.35)
    show(chrome, [], clocks={"w": "5:00", "b": "5:00"}, turn="w")
    q = queue.Queue()
    r = run_runner(q, book=True, ponder=False)
    try:
        sugg = wait_for(q, "sugg")
        assert sugg[2][0][0] == "d2d4"
        assert "(livro de aberturas)" in wait_for(q, "line")[1]
    finally:
        r.stop(); r.join(15)


def test_bad_book_move_is_rejected_by_the_engine(chrome, tmp_path, monkeypatch):
    make_book(tmp_path, monkeypatch, ["f3"])                      # 1.f3 e fraco: o motor veta
    show(chrome, [], clocks={"w": "5:00", "b": "5:00"}, turn="w")
    q = queue.Queue()
    r = run_runner(q, book=True, ponder=False)
    try:
        sugg = wait_for(q, "sugg")
        assert sugg[2][0][0] != "f2f3"
        assert "(livro de aberturas)" not in wait_for(q, "line")[1]
    finally:
        r.stop(); r.join(15)


def test_runner_ponders_on_the_opponents_likely_replies(chrome):
    show(chrome, ["e4"], clocks={"w": "5:00", "b": "5:00"}, turn="b")    # vez do adversario
    q = queue.Queue()
    r = run_runner(q, ponder=True, book=False)
    try:
        wait_for(q, "status", pred=lambda m: "adversario" in m[1])
        time.sleep(5)                                                     # o motor pensa nas respostas dele
        show(chrome, ["e4", "e5"], clocks={"w": "5:00", "b": "4:50"}, turn="w")
        line = wait_for(q, "line")
        assert "resposta pronta" in line[1], line
    finally:
        r.stop(); r.join(15)


# ---------------- forca adaptativa dentro do Runner ----------------
def test_adaptive_strength_starts_below_max_and_rises_after_a_loss(chrome, tmp_path, monkeypatch):
    from chessmind import strength
    monkeypatch.setattr(strength, "PATH", tmp_path / "strength.json")
    played = []
    monkeypatch.setattr(pwsource.PWBoard, "is_bot_page", lambda self: True)
    monkeypatch.setattr(pwsource.PWBoard, "play_move", lambda self, uci, wb, white: played.append(uci))
    opp = "Nora (2200) 5:00"
    show(chrome, [], clocks={"w": "5:00", "b": "5:00"}, turn="w", opponent=opp)        # sua vez, brancas
    q = queue.Queue()
    r = run_runner(q, autoplay=True, adaptive=True, book=False, ponder=False, humanize=False, delay=0.3)
    try:
        # 1) comeca em rating + 200 (bem abaixo do maximo) e o lance vem do motor de forca limitada
        assert wait_for(q, "strength")[1:] == (2400, "Nora")
        line = wait_for(q, "line")
        assert "forca limitada: 2400" in line[1]
        for _ in range(40):
            if played:
                break
            time.sleep(0.1)
        assert played and chess.Move.from_uci(played[0]) in chess.Board().legal_moves
        # 2) o lance aparece no tabuleiro; o adversario responde; ele vence (fim de jogo)
        b = chess.Board()
        san = b.san(chess.Move.from_uci(played[0]))
        b.push_uci(played[0])
        show(chrome, [san], clocks={"w": "4:55", "b": "5:00"}, turn="b", opponent=opp)
        time.sleep(1.0)
        reply = b.san(next(iter(b.legal_moves)))
        b.push_san(reply)
        show(chrome, [san, reply], clocks={"w": "4:55", "b": "4:58"}, turn="w", opponent=opp,
             over=True, modal_text="Nora venceu por abandono")
        # 3) perdeu: a forca sobe 250 e fica salva
        msg = wait_for(q, "strength", pred=lambda m: m[1] == 2650)
        assert msg[1:] == (2650, "Nora")
        saved = json.loads((tmp_path / "strength.json").read_text())
        assert saved["nora"]["elo"] == 2650 and saved["nora"]["losses"] == 1
    finally:
        r.stop(); r.join(15)


def test_adaptive_is_off_when_autoplay_is_off(chrome, tmp_path, monkeypatch):
    from chessmind import strength
    monkeypatch.setattr(strength, "PATH", tmp_path / "strength.json")
    show(chrome, [], clocks={"w": "5:00", "b": "5:00"}, turn="w", opponent="Nora (2200) 5:00")
    q = queue.Queue()
    r = run_runner(q, autoplay=False, adaptive=True, book=False, ponder=False)
    try:
        sugg = wait_for(q, "sugg")
        line = wait_for(q, "line")
        assert "forca limitada" not in line[1]                     # como coach, mostra sempre o melhor
        assert not (tmp_path / "strength.json").exists()
    finally:
        r.stop(); r.join(15)
