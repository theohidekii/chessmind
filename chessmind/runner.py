"""Loop do coach em thread: leitura da pagina -> Stockfish -> interface (e, opcional, jogar)."""
import os
import queue
import random
import threading
import time

import chess
import numpy as np

from . import collect, config, log, vision
from .book import Book
from .engine import Coach
from .review import GameReview, infer_outcome, parse_opponent
from .strength import StrengthManager
from .timing import ev_to_pawns, human_delay, think_budget
from .tracker import Tracker, placement_of

PRESETS = {
    "Maxima (bot mais forte)": dict(threads=4, hash_mb=1024, think=2.0),
    "Alta": dict(threads=2, hash_mb=256, think=1.0),
    "Rapida": dict(threads=1, hash_mb=128, think=0.3),
}

DEFAULT_SETTINGS = dict(show_arrows=True, autoplay=False, delay=1.0, ponder=True, plies=6,
                        humanize=True, next_game=False, collect=False, book=True, adaptive=True)
MAX_AUTO_GAMES = 10          # partidas seguidas no modo "proxima partida"
BOOK_TOLERANCE = 0.35        # peoes: o lance de livro so vale se o motor discordar menos que isso

L = log.get("runner")


class Runner(threading.Thread):
    """Mensagens enviadas em `out`:
    ("status", texto) | ("board", fen) | ("sugg", fen, [(uci, san, ev)]) | ("line", texto)
    ("clear",) | ("orient", brancas_embaixo) | ("auto", ligado) | ("alive",) | ("log", texto)
    ("lastmove", numero, san, rotulo, perda, melhor_san) | ("review", resumo, caminho)
    ("error", texto) | ("stopped",)

    `settings` e um dict compartilhado com a interface e lido a cada ciclo (vale em tempo real).
    """

    def __init__(self, out: queue.Queue, preset: str, lines: int, settings: dict = None):
        super().__init__(daemon=True)
        self.out, self.lines = out, lines
        self.settings = settings if settings is not None else dict(DEFAULT_SETTINGS)
        self.opts = dict(PRESETS[preset])
        self.opts["threads"] = max(1, min(self.opts["threads"], os.cpu_count() or 1))
        self.stop_event = threading.Event()
        self._awaiting = None
        self._review = None
        self._games_done = 0
        self._game_finished = False
        self._last_new_game = 0.0
        self._last_collect = None
        self._book = None
        self._strength = None
        self._opp = None                 # adversario atual {'name', 'rating'}
        self._adaptive_game = False      # nesta partida a forca foi limitada (conta para o ajuste)

    # ---------- util ----------
    def _sleep(self, seconds):
        """Dorme em fatias, mantendo o sinal de vida; False se mandaram parar/desligar."""
        end = time.time() + seconds
        while time.time() < end:
            if self.stop_event.is_set() or not self.settings["autoplay"]:
                return False
            self.out.put(("alive",))
            time.sleep(0.1)
        return True

    def _line_text(self, board, pv):
        n = max(1, int(self.settings["plies"]))
        try:
            return board.variation_san(pv[:n])
        except Exception:
            return ""

    def _disable_auto(self, why):
        L.warning("modo autonomo desligado: %s", why)
        self.settings["autoplay"] = False
        self.out.put(("auto", False))
        self.out.put(("log", why + "\n"))
        self.out.put(("status", why))

    # ---------- loop ----------
    def run(self):
        coach = pw = None
        try:
            cal = config.load_calibration()
            if cal.get("source") != "playwright":
                raise RuntimeError("Calibracao antiga: clique em Calibrar de novo.")
            try:        # so o plano B (sites sem leitura por DOM) usa os modelos de imagem
                templates = {k: v for k, v in np.load(config.TEMPLATES_PATH).items()}
            except OSError:
                templates = {}
            white_bottom = cal["white_bottom"]
            from .pwsource import PWBoard
            self.out.put(("status", "Conectando ao Chrome (Playwright)..."))
            pw = PWBoard()
            self.out.put(("status", "Iniciando o Stockfish..."))
            coach = Coach(self.opts["think"], self.lines, None,
                          self.opts["threads"], self.opts["hash_mb"])
            L.info("iniciado: preset=%s threads=%s hash=%s", self.opts, self.opts["threads"],
                   self.opts["hash_mb"])
            self._book = Book()
            self._strength = StrengthManager(lo=coach.elo_range[0], hi=coach.elo_range[1])
            L.info("livro de aberturas: %s | tablebases: %s | faixa de Elo: %s", self._book.available(),
                   coach.tb is not None, coach.elo_range)
            tracker = Tracker(white_bottom)
            self._review = GameReview(white_bottom)
            last, stable = None, None
            self.out.put(("orient", white_bottom))
            self.out.put(("status", "Ativo. Aguardando o tabuleiro no Chrome."))

            errors = 0
            last_sig, need, last_meta = None, 0, 0.0
            state, last_state = None, 0.0
            while not self.stop_event.is_set():
                self.out.put(("alive",))
                placement = None
                try:
                    dom = pw.dom_placement()            # leitura exata, sem screenshot
                    if dom is None and pw._board() is None:
                        self.out.put(("clear",))
                        self.out.put(("status", "Nenhum tabuleiro na pagina."))
                        time.sleep(1)
                        continue
                    if time.time() - last_meta > 1.0:
                        last_meta = time.time()
                        wb = pw.white_bottom()
                        if wb is not None and wb != white_bottom:   # lado trocado
                            white_bottom = wb
                            tracker = Tracker(white_bottom)
                            self._review = GameReview(white_bottom)
                            last = stable = None
                            last_sig, need = None, 0
                            self.out.put(("orient", white_bottom))
                        if pw._arrows and self.settings["show_arrows"]:
                            pw.refresh_arrows()             # so redesenha se o tabuleiro mudou
                        elif pw._arrows:
                            pw.hide_arrows()
                    if dom is not None:
                        placement = dict(dom)
                    else:
                        # Site desconhecido: cai para a leitura por imagem.
                        sig = pw.signature()
                        if sig != last_sig:
                            last_sig, need = sig, 2
                            pw.hide_arrows()                # setas fora da pagina antes de capturar
                        if need <= 0:
                            time.sleep(0.25)
                            continue
                        frame = pw.frame()
                        need -= 1
                        placement = vision.to_placement(
                            vision.classify(vision.split_squares(frame), templates), white_bottom)
                    errors = 0
                except Exception as e:      # timeout/aba recarregando: tenta de novo
                    errors += 1
                    L.warning("falha na leitura (%s): %s", errors, e)
                    self.out.put(("clear",))
                    self.out.put(("status", f"Falha na captura ({errors}): {type(e).__name__}"))
                    if errors >= 8:
                        raise
                    last_sig = None
                    time.sleep(1)
                    continue
                user_color = chess.WHITE if white_bottom else chess.BLACK

                self._check_awaiting(pw, placement, white_bottom)

                if placement != last or time.time() - last_state > 1.5:
                    state, last_state = pw.read_state(), time.time()   # sem poluir a pagina a cada ciclo
                if placement == stable and placement != last:
                    last = placement
                    prev_source = tracker.source
                    if tracker.update(placement, state):
                        board = tracker.board
                        fresh = tracker.source == "inicio" and not board.move_stack
                        if tracker.source != prev_source or fresh:
                            L.info("estado sincronizado via %s: %s", tracker.source, board.fen())
                        if fresh:                               # tabuleiro na posicao inicial: nova partida
                            self._new_game(white_bottom)
                        pw.hide_arrows()                # posicao mudou: setas antigas saem
                        if self.settings.get("collect") and dom is not None:
                            self._collect(pw, placement, white_bottom)
                        self.out.put(("board", board.fen()))
                        mr = self._review.observe(board, coach)
                        if mr:
                            L.info("seu lance %s%s: %s (perda %.1f, melhor %s)", mr.number, mr.san,
                                   mr.label, mr.loss, mr.best_san)
                            self.out.put(("lastmove", mr.number, mr.san, mr.label, mr.loss,
                                          mr.best_san))
                        if board.is_game_over():
                            self._finish_game(board, state)
                        elif board.turn == user_color:
                            self._my_turn(coach, pw, board, white_bottom, state)
                        else:
                            self.out.put(("clear",))      # a linha prevista continua visivel
                            self.out.put(("status", "Vez do adversario."))
                            if self.settings["ponder"]:   # pensa nas respostas mais provaveis dele
                                try:
                                    coach.start_multi_ponder(board)
                                except Exception as e:
                                    L.warning("ponder falhou: %s", e)
                    else:
                        self.out.put(("status", "Leitura instavel, tentando de novo..."))
                stable = placement

                # fim de jogo sinalizado pela pagina (xeque-mate, tempo, abandono...)
                if state and state.get("over") and tracker.board is not None:
                    self._finish_game(tracker.board, state)
                    self._maybe_next_game(pw)
                if self.settings["ponder"]:
                    coach.ponder_tick()         # revezamento entre as respostas candidatas
                else:
                    coach.reset_ponder()
                time.sleep(0.3)
        except Exception as e:  # mostra o erro na interface em vez de morrer calado
            L.exception("erro fatal no coach")
            self.out.put(("error", f"{type(e).__name__}: {e}"))
        finally:
            L.info("encerrando")
            if self._book:
                self._book.close()
            if coach:
                coach.close()
            if pw:
                try:
                    pw.hide_arrows()
                except Exception:
                    pass
                pw.close()
            self.out.put(("stopped",))

    def _collect(self, pw, placement, white_bottom):
        """Salva a imagem do tabuleiro com as casas rotuladas pelo DOM (dados p/ treinar a visao)."""
        key = frozenset(placement.items())
        if key == self._last_collect:
            return
        self._last_collect = key
        try:
            frame = pw.frame()
            if frame is not None:
                site = pw.page.url.split("/")[2] if "//" in pw.page.url else ""
                collect.save_sample(frame, placement, white_bottom, site=site)
                self.out.put(("log", f"Dados de treino coletados: {collect.count()} posicoes.\n"))
        except Exception as e:
            L.warning("coleta falhou: %s", e)

    # ---------- confirmacao do lance feito ----------
    def _check_awaiting(self, pw, placement, white_bottom):
        aw = self._awaiting
        if not aw:
            return
        if placement == aw["expected"]:
            self._awaiting = None
        elif time.time() > aw["deadline"]:
            if aw["retries"] < 1:
                aw["retries"] += 1
                aw["deadline"] = time.time() + 3
                L.warning("lance %s nao apareceu; tentando de novo", aw["uci"])
                self.out.put(("status", "Lance nao apareceu, tentando de novo..."))
                try:
                    pw.play_move(aw["uci"], white_bottom, aw["white"])
                except Exception as e:
                    self.out.put(("log", f"Falha ao jogar: {e}\n"))
            else:
                self._disable_auto("Lance nao confirmado no tabuleiro. Modo autonomo desligado.")
                self._awaiting = None

    # ---------- partidas ----------
    def _new_game(self, white_bottom):
        self._review = GameReview(white_bottom)
        self._adaptive_game = False
        if self._strength:
            self._strength.new_game()
        self._game_finished = False
        self._awaiting = None
        L.info("nova partida")

    def _finish_game(self, board, state=None):
        if self._game_finished:
            return
        self._game_finished = True
        review = self._review
        if review is None or not review.moves:
            return
        state = state or {}
        review.opponent = parse_opponent(state.get("opponent"))
        if not board.is_game_over():           # abandono/tempo/acordo: o resultado vem do texto da pagina
            name = (review.opponent or {}).get("name")
            review.outcome = infer_outcome(state.get("result_text"), name)
        path = review.save(board)
        summary = review.summary(board)
        L.info("partida encerrada: %s | arquivo %s", summary, path)
        if self._adaptive_game and self._strength:         # perdeu/empatou: a forca sobe
            opp = review.opponent or self._opp
            before = self._strength.current(opp)
            elo = self._strength.record_game(opp, summary.get("outcome"))
            L.info("forca vs %s: %s -> %s (%s)", (opp or {}).get("name"), before, elo, summary.get("outcome"))
            self.out.put(("strength", elo, (opp or {}).get("name")))
            if elo != before:
                self.out.put(("log", f"Resultado: {summary.get('outcome')}. Forca sobe para "
                                     f"{elo or 'maxima'}.\n"))
        self.out.put(("status", "Fim de jogo."))
        self.out.put(("review", summary, str(path)))

    def _maybe_next_game(self, pw):
        """Modo 'proxima partida': clica em Nova partida/Revanche na janela de fim de jogo."""
        s = self.settings
        if not (s["autoplay"] and s["next_game"]) or time.time() - self._last_new_game < 4:
            return
        if self._games_done >= MAX_AUTO_GAMES:
            self.settings["next_game"] = False
            self.out.put(("log", f"Limite de {MAX_AUTO_GAMES} partidas seguidas atingido.\n"))
            return
        if not pw.is_bot_page():
            return
        self._last_new_game = time.time()
        try:
            clicked = pw.click_new_game()
        except Exception as e:
            L.warning("falha ao iniciar nova partida: %s", e)
            clicked = None
        if clicked:
            self._games_done += 1
            L.info("nova partida iniciada pelo botao %r (%s/%s)", clicked, self._games_done,
                   MAX_AUTO_GAMES)
            self.out.put(("status", f"Nova partida: {clicked}"))
        else:
            self.out.put(("log", "Nao achei o botao de nova partida na janela de fim de jogo.\n"))

    # ---------- sua vez ----------
    def _my_turn(self, coach, pw, board, white_bottom, state):
        """Sua vez: calcula, mostra a linha prevista e (se ligado) joga o lance."""
        self.out.put(("status", "Calculando..."))
        white = board.turn == chess.WHITE
        my_clock = ((state or {}).get("clocks") or {}).get("w" if white else "b")
        coach.think_time = think_budget(self.opts["think"], my_clock, board)

        # Forca adaptativa (so no modo autonomo): o lance a jogar vem de um motor de forca limitada
        adaptive = self.settings["adaptive"] and self.settings["autoplay"]
        opp = parse_opponent((state or {}).get("opponent")) or self._opp
        self._opp = opp
        elo = self._strength.current(opp) if adaptive else None
        sugg = coach.suggest(board, elo=elo)
        full, full_pv = coach.last_full or sugg, (coach.last_full_pvs[0] if coach.last_full_pvs else [])
        pv = coach.last_pvs[0] if coach.last_pvs else []
        tag = "  (resposta pronta: o adversario jogou o previsto)" if coach.last_from_ponder else ""
        if coach.last_from_tb:
            tag = "  (tablebase: jogo perfeito)"
        else:
            sugg, from_book = self._apply_book(coach, board, sugg)
            if from_book:
                pv, tag = [sugg[0][0]], "  (livro de aberturas)"
            elif coach.last_weakened:
                tag += f"  (forca limitada: {elo})"
        if adaptive:
            self._adaptive_game = True
            raised = self._strength.observe_eval(opp, ev_to_pawns(full[0][1]))    # partida ruim: sobe ja
            if raised is not False:
                L.info("partida ruim (%s): forca sobe para %s", full[0][1], raised)
                self.out.put(("log", f"Posicao dificil: forca sobe para {raised or 'maxima'}.\n"))
            self.out.put(("strength", self._strength.current(opp), (opp or {}).get("name")))
        self.out.put(("sugg", board.fen(), [(m.uci(), san, ev) for m, ev, san in sugg]))
        self.out.put(("line", self._line_text(board, pv) + tag))
        self._review.start_turn(board, full, full_pv)      # a revisao compara com o MELHOR lance
        if self.settings["show_arrows"]:
            pw.show_arrows([m.uci() for m, _, _ in sugg], white_bottom)
        self.out.put(("status", "Sua vez."))

        if self.settings["autoplay"] and sugg:
            move = sugg[0][0]
            if not pw.is_bot_page():
                self._disable_auto("Modo autonomo so funciona em partidas contra bots do chess.com.")
            else:
                base = float(self.settings["delay"])
                if self.settings["humanize"]:
                    delay = human_delay(base, board, sugg, coach.last_gap, my_clock)
                else:
                    delay = base + random.uniform(0, base * 0.6)
                L.info("jogando %s apos %.2fs (gap=%s, relogio=%s)", sugg[0][2], delay,
                       coach.last_gap, my_clock)
                if self._sleep(delay):
                    self.out.put(("status", f"Jogando {sugg[0][2]}..."))
                    try:
                        pw.play_move(move.uci(), white_bottom, white)
                        after = board.copy()
                        after.push(move)
                        self._awaiting = dict(expected=placement_of(after), uci=move.uci(),
                                              white=white, deadline=time.time() + 3, retries=0)
                    except Exception as e:
                        self._disable_auto(f"Nao consegui jogar: {type(e).__name__}: {e}")

    def _apply_book(self, coach, board, sugg):
        """Livro de aberturas: se ele tem um lance e o motor concorda (perda <= BOOK_TOLERANCE),
        esse lance passa a ser o 1o. Retorna (sugestoes, usou_livro). Livro ruim nunca joga mal."""
        book = self._book
        if not (self.settings.get("book", True) and book and book.available() and sugg):
            return sugg, False
        bm = book.pick(board)
        if bm is None:
            return sugg, False
        if bm == sugg[0][0]:
            return sugg, True
        full = coach.last_full or sugg                      # comparacao sempre com a forca total
        known = {m: ev for m, ev, _ in full}
        ev_bm = ev_to_pawns(known[bm]) if bm in known else coach.eval_after(board, bm)
        if ev_to_pawns(full[0][1]) - ev_bm > BOOK_TOLERANCE:
            L.info("livro sugeriu %s mas o motor discorda (%.2f vs %.2f)", board.san(bm), ev_bm,
                   ev_to_pawns(full[0][1]))
            return sugg, False
        first = (bm, f"{ev_bm:+.2f}", board.san(bm))
        return [first] + [s for s in sugg if s[0] != bm][:max(self.lines - 1, 0)], True

    def stop(self):
        self.stop_event.set()
