"""Interface do ChessMind: python gui.py  (ou gui.bat)"""
import json
import math
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import chess

from chessmind import config, explain, lock, log, stats, strength, training
from chessmind.review import GAMES_DIR, LABELS_PT
from chessmind.runner import DEFAULT_SETTINGS, PRESETS, Runner
from chessmind.timing import ev_to_pawns

config.make_dpi_aware()
L = log.get("gui")

# ---- paleta ----
BG, CARD, BORDER = "#14161a", "#1c1f25", "#2a2e36"
FG, MUTED, FAINT = "#e8eaed", "#8b93a1", "#5b6270"
GREEN, RED, AMBER, BLUE = "#3ecf8e", "#f16a6a", "#f5b94a", "#5aa9ff"
ORANGE = "#f58a4a"
LIGHT, DARK = "#ebecd0", "#739552"
TINT_LIGHT, TINT_DARK = "#f6f669", "#baca2b"
ARROWS = [GREEN, AMBER, ORANGE]
LABEL_COLORS = {"best": GREEN, "excellent": GREEN, "good": "#8fd3a8", "inaccuracy": AMBER,
                "mistake": ORANGE, "blunder": RED}
GLYPH = {"K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘", "P": "♙",
         "k": "♚", "q": "♛", "r": "♜", "b": "♝", "n": "♞", "p": "♟"}
SQ = 48                      # lado da casa em px
BOARD_PX = SQ * 8
FONT = "Segoe UI"
BAR_W = 34


class Card(tk.Frame):
    def __init__(self, master, title=None, **kw):
        super().__init__(master, bg=CARD, highlightbackground=BORDER, highlightthickness=1, **kw)
        if title:
            tk.Label(self, text=title.upper(), bg=CARD, fg=MUTED,
                     font=(FONT, 8, "bold")).pack(anchor="w", padx=14, pady=(8, 2))


class TextWindow(tk.Toplevel):
    """Janela simples com texto (explicacoes)."""

    def __init__(self, master, title, text):
        super().__init__(master, bg=BG)
        self.title(title)
        self.geometry("460x300")
        box = tk.Text(self, wrap="word", bg=CARD, fg=FG, bd=0, font=(FONT, 11), padx=14, pady=12,
                      highlightbackground=BORDER, highlightthickness=1)
        box.pack(fill="both", expand=True, padx=12, pady=12)
        box.insert("1.0", text)
        box.configure(state="disabled")


class ReviewWindow(tk.Toplevel):
    """Resumo da partida e os momentos criticos, com explicacao sob demanda."""

    def __init__(self, app, data):
        super().__init__(app.root, bg=BG)
        self.app, self.data = app, data
        s = data["summary"]
        self.title("Revisao da partida")
        self.geometry("560x560")
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=16, pady=14)

        head = Card(wrap)
        head.pack(fill="x")
        acc = s.get("accuracy")
        tk.Label(head, text=f"{acc:.0f}%" if acc is not None else "—", bg=CARD,
                 fg=GREEN if (acc or 0) >= 85 else AMBER if (acc or 0) >= 65 else RED,
                 font=(FONT, 28, "bold")).pack(side="left", padx=18, pady=10)
        info = tk.Frame(head, bg=CARD)
        info.pack(side="left", pady=10)
        tk.Label(info, text="Precisao dos seus lances", bg=CARD, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
        tk.Label(info, text=s.get("opening") or "Abertura nao identificada", bg=CARD, fg=FG,
                 font=(FONT, 11, "bold")).pack(anchor="w")
        tk.Label(info, text=f"{s['moves']} lances · resultado {s.get('result') or '?'}",
                 bg=CARD, fg=MUTED, font=(FONT, 9)).pack(anchor="w")

        counts = tk.Frame(wrap, bg=BG)
        counts.pack(fill="x", pady=10)
        for key in ("best", "excellent", "good", "inaccuracy", "mistake", "blunder"):
            c = Card(counts)
            c.pack(side="left", expand=True, fill="x", padx=2)
            tk.Label(c, text=str(s["counts"].get(key, 0)), bg=CARD, fg=LABEL_COLORS[key],
                     font=(FONT, 16, "bold")).pack(pady=(6, 0))
            tk.Label(c, text=LABELS_PT[key], bg=CARD, fg=MUTED, font=(FONT, 8)).pack(pady=(0, 6))

        tk.Label(wrap, text="MOMENTOS CRITICOS", bg=BG, fg=MUTED,
                 font=(FONT, 8, "bold")).pack(anchor="w", pady=(4, 4))
        bad = [m for m in data["moves"] if m["label"] in ("inaccuracy", "mistake", "blunder")]
        bad = sorted(bad, key=lambda m: -m["loss"])[:8]
        if not bad:
            tk.Label(wrap, text="Nenhuma imprecisao relevante. Partida limpa!", bg=BG, fg=GREEN,
                     font=(FONT, 11)).pack(anchor="w")
        for m in bad:
            row = Card(wrap)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=f"{m['number']} {m['san']}", bg=CARD, fg=FG,
                     font=(FONT, 12, "bold"), width=11, anchor="w").pack(side="left", padx=(12, 4), pady=8)
            tk.Label(row, text=LABELS_PT[m["label"]], bg=CARD, fg=LABEL_COLORS[m["label"]],
                     font=(FONT, 10, "bold"), width=11, anchor="w").pack(side="left")
            tk.Label(row, text=f"melhor: {m['best_san']} ({m['ev_best']:+.1f})", bg=CARD, fg=MUTED,
                     font=(FONT, 9)).pack(side="left", padx=6)
            ttk.Button(row, text="Explicar", style="Ghost.TButton",
                       command=lambda mm=m: self.explain_move(mm)).pack(side="right", padx=8, pady=4)

    def explain_move(self, m):
        side = "brancas" if " w " in m["fen_before"] else "pretas"
        line = m["line"][0] if m.get("line") else m["best_san"]
        prompt = explain.build_prompt(m["fen_before"], side, m["best_san"], line,
                                      f"{m['ev_best']:+.2f}", m["san"], LABELS_PT[m["label"]], m["loss"])
        self.app.run_explain(f"{m['number']} {m['san']}", prompt)


class MiniBoard(tk.Canvas):
    """Tabuleiro clicavel (clique na peca e depois na casa) para os exercicios."""

    def __init__(self, master, sq=50, on_move=None):
        super().__init__(master, width=sq * 8 + 22, height=sq * 8 + 22, bg=BG, highlightthickness=0)
        self.sq, self.on_move = sq, on_move
        self.board, self.white_bottom = chess.Board(), True
        self.selected, self.marks, self.arrows, self.locked = None, {}, [], False
        self.bind("<Button-1>", self._click)

    def set_position(self, board, white_bottom, locked=False):
        self.board, self.white_bottom, self.locked = board, white_bottom, locked
        self.selected, self.marks, self.arrows = None, {}, []
        self.redraw()

    def _xy(self, sq):
        f, r = chess.square_file(sq), chess.square_rank(sq)
        return (f if self.white_bottom else 7 - f) * self.sq, ((7 - r) if self.white_bottom else r) * self.sq

    def _at(self, x, y):
        col, row = int(x // self.sq), int(y // self.sq)
        if not (0 <= col < 8 and 0 <= row < 8):
            return None
        f = col if self.white_bottom else 7 - col
        r = 7 - row if self.white_bottom else row
        return chess.square(f, r)

    def _click(self, e):
        if self.locked:
            return
        sq = self._at(e.x, e.y)
        if sq is None:
            return
        piece = self.board.piece_at(sq)
        mine = piece is not None and piece.color == self.board.turn
        if self.selected is None:
            if mine:
                self.selected = sq
        elif sq == self.selected:
            self.selected = None
        elif mine:
            self.selected = sq
        else:
            move = chess.Move(self.selected, sq)
            p = self.board.piece_at(self.selected)
            if p and p.piece_type == chess.PAWN and chess.square_rank(sq) in (0, 7):
                move.promotion = chess.QUEEN
            if move in self.board.legal_moves:
                self.selected = None
                self.redraw()
                if self.on_move:
                    self.on_move(move)
                return
            self.selected = None
        self.redraw()

    def redraw(self):
        c, s = self, self.sq
        c.addtag_all("old")
        for sq in chess.SQUARES:
            x, y = self._xy(sq)
            light = (chess.square_file(sq) + chess.square_rank(sq)) % 2 == 1
            col = LIGHT if light else DARK
            if sq == self.selected:
                col = TINT_LIGHT if light else TINT_DARK
            c.create_rectangle(x, y, x + s, y + s, fill=col, width=0)
            if sq in self.marks:
                c.create_rectangle(x + 2, y + 2, x + s - 2, y + s - 2, outline=self.marks[sq], width=4)
        files = "abcdefgh" if self.white_bottom else "hgfedcba"
        ranks = "87654321" if self.white_bottom else "12345678"
        for i in range(8):
            c.create_text(i * s + s / 2, s * 8 + 11, text=files[i], fill=MUTED, font=(FONT, 8, "bold"))
            c.create_text(s * 8 + 11, i * s + s / 2, text=ranks[i], fill=MUTED, font=(FONT, 8, "bold"))
        font = ("Segoe UI Symbol", int(s * 0.72))
        for sq in chess.SQUARES:
            p = self.board.piece_at(sq)
            if p:
                x, y = self._xy(sq)
                cx, cy = x + s / 2, y + s / 2 + 2
                c.create_text(cx, cy, text=GLYPH[p.symbol().lower()], font=font,
                              fill="#fbfbfb" if p.color else "#1b1b1b")
                c.create_text(cx, cy, text=GLYPH[p.symbol().upper()], font=font, fill="#000")
        for mv, color in self.arrows:
            x1, y1 = self._xy(mv.from_square)
            x2, y2 = self._xy(mv.to_square)
            c.create_line(x1 + s / 2, y1 + s / 2, x2 + s / 2, y2 + s / 2, fill=color, width=8,
                          arrow=tk.LAST, arrowshape=(13, 16, 6), capstyle=tk.ROUND)
        c.delete("old")


class TrainerWindow(tk.Toplevel):
    """Exercicios a partir dos seus erros, com repeticao espacada."""

    def __init__(self, app):
        super().__init__(app.root, bg=BG)
        self.app = app
        self.title("Treino a partir dos erros")
        self.progress = training.Progress()
        self.all = training.load_exercises()
        self.queue = self.progress.due_exercises(self.all)
        self.i, self.session = 0, [0, 0]       # indice, [acertos, tentativas]
        self.ex = None
        self.engine = None
        self.results = queue.Queue()
        self.protocol("WM_DELETE_WINDOW", self.close)

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(padx=16, pady=14)
        self.board = MiniBoard(wrap, 50, on_move=self.on_move)
        self.board.grid(row=0, column=0, rowspan=2)
        side = tk.Frame(wrap, bg=BG, width=300)
        side.grid(row=0, column=1, sticky="nw", padx=(16, 0))
        self.head = tk.Label(side, text="", bg=BG, fg=FG, font=(FONT, 13, "bold"), anchor="w",
                             wraplength=290, justify="left")
        self.head.pack(fill="x")
        self.sub = tk.Label(side, text="", bg=BG, fg=MUTED, font=(FONT, 10), anchor="w",
                            wraplength=290, justify="left")
        self.sub.pack(fill="x", pady=(2, 10))
        self.msg = tk.Label(side, text="", bg=BG, fg=FG, font=(FONT, 11), anchor="w",
                            wraplength=290, justify="left")
        self.msg.pack(fill="x", pady=(0, 10))
        row = tk.Frame(side, bg=BG)
        row.pack(fill="x")
        self.btn_hint = ttk.Button(row, text="Dica", style="Ghost.TButton", command=self.hint)
        self.btn_show = ttk.Button(row, text="Ver resposta", style="Ghost.TButton", command=self.give_up)
        self.btn_hint.pack(side="left", expand=True, fill="x", padx=(0, 6))
        self.btn_show.pack(side="left", expand=True, fill="x")
        row2 = tk.Frame(side, bg=BG)
        row2.pack(fill="x", pady=(6, 0))
        self.btn_explain = ttk.Button(row2, text="Explicar", style="Ghost.TButton", command=self.explain)
        self.btn_next = ttk.Button(row2, text="Proximo \u25B6", style="Go.TButton", command=self.next)
        self.btn_explain.pack(side="left", expand=True, fill="x", padx=(0, 6))
        self.btn_next.pack(side="left", expand=True, fill="x")
        self.score = tk.Label(side, text="", bg=BG, fg=FAINT, font=(FONT, 9), anchor="w",
                              wraplength=290, justify="left")
        self.score.pack(fill="x", pady=(14, 0))
        self.after(100, self._poll)
        self.next(first=True)

    # ---- fluxo ----
    def next(self, first=False):
        if not first:
            self.i += 1
        if not self.all:
            return self._empty("Nenhum erro salvo ainda.\nJogue algumas partidas: as imprecisoes, "
                               "erros e gafes viram exercicios aqui.")
        if self.i >= len(self.queue):
            if self.queue or not first:
                msg = f"Sessao concluida: {self.session[0]} acertos em {self.session[1]} tentativas."
            else:
                msg = "Tudo em dia! Nenhum exercicio vencido agora."
            self.queue, self.i = [], 0
            return self._empty(msg + "\nVolte mais tarde: os exercicios reaparecem conforme a repeticao espacada.",
                               allow_all=True)
        self.ex = self.queue[self.i]
        ex = self.ex
        board = chess.Board(ex.fen)
        self.board.set_position(board, ex.white_to_move)
        self.head.configure(text=f"Exercicio {self.i + 1} de {len(self.queue)}", fg=FG)
        self.sub.configure(text=f"Vez das {'brancas' if ex.white_to_move else 'pretas'}. Na partida "
                                f"({stats.pretty_date(ex.game)}) voce jogou {ex.number} {ex.played_san}: "
                                f"{LABELS_PT[ex.label].lower()}. Qual era o melhor lance?")
        self.msg.configure(text="Clique na peca e depois na casa de destino.", fg=MUTED)
        for b in (self.btn_hint, self.btn_show):
            b.state(["!disabled"])
        self.btn_explain.state(["disabled"])
        self.btn_next.state(["disabled"])
        self._answered = False
        self._update_score()

    def _empty(self, text, allow_all=False):
        self.ex = None
        self.board.set_position(chess.Board(), True, locked=True)
        self.head.configure(text="Treino", fg=FG)
        self.sub.configure(text=text)
        self.msg.configure(text="")
        for b in (self.btn_hint, self.btn_show, self.btn_explain, self.btn_next):
            b.state(["disabled"])
        if allow_all and self.all:
            self.btn_next.configure(text="Praticar todos", command=self._practice_all)
            self.btn_next.state(["!disabled"])
        self._update_score()

    def _practice_all(self):
        self.queue, self.i = list(self.all), 0
        self.btn_next.configure(text="Proximo \u25B6", command=self.next)
        self.next(first=True)

    def _update_score(self):
        sm = self.progress.summary(self.all)
        self.score.configure(text=f"Seus erros salvos: {sm['total']} \u00b7 ja praticados: {sm['practiced']} "
                                  f"\u00b7 dominados: {sm['mastered']}\nNesta sessao: {self.session[0]}/{self.session[1]}")

    def hint(self):
        if self.ex:
            best = chess.Board(self.ex.fen).parse_san(self.ex.best_san)
            self.board.marks = {best.from_square: AMBER}
            self.board.redraw()
            self.msg.configure(text="Dica: mexa a peca marcada.", fg=AMBER)

    def give_up(self):
        if self.ex and not self._answered:
            self._finish("wrong", None, gave_up=True)

    def on_move(self, move):
        if not self.ex or self._answered:
            return
        self._answered = True
        board = chess.Board(self.ex.fen)
        if move == board.parse_san(self.ex.best_san):
            self._finish("correct", self.ex.ev_best, move=move)
            return
        self.msg.configure(text="Avaliando o seu lance...", fg=BLUE)
        self.board.locked = True
        ex = self.ex

        def work():
            try:
                if self.engine is None:
                    from chessmind.engine import Coach
                    self.engine = Coach(0.4, 1, None, 1, 64)
                verdict, ev = training.check_answer(ex, move, self.engine)
            except Exception as e:
                L.warning("treino: falha ao avaliar: %s", e)
                verdict, ev = "wrong", None
            self.results.put((ex, verdict, ev, move))

        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            while True:
                ex, verdict, ev, move = self.results.get_nowait()
                if ex is self.ex:
                    self._finish(verdict, ev, move=move)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _finish(self, verdict, ev, move=None, gave_up=False):
        ex = self.ex
        self._answered = True
        board = chess.Board(ex.fen)
        best = board.parse_san(ex.best_san)
        self.board.locked = True
        self.board.arrows = [(best, GREEN)]
        if move is not None and move != best:
            self.board.arrows.append((move, AMBER if verdict == "good" else RED))
        self.board.marks = {}
        self.board.redraw()
        ok = verdict in ("correct", "good")
        if not gave_up:
            self.session[1] += 1
            self.session[0] += int(ok)
            self.progress.record(ex.id, ok)
        text = {"correct": f"Correto! {ex.best_san} era o melhor.",
                "good": f"Boa alternativa (avaliacao {ev:+.1f}), mas o melhor era {ex.best_san}."
                        if ev is not None else f"Boa alternativa, mas o melhor era {ex.best_san}.",
                "wrong": (f"O melhor era {ex.best_san} ({ex.ev_best:+.1f})."
                          + (f" O seu lance valia {ev:+.1f}." if ev is not None else ""))}[verdict]
        if gave_up:
            text = f"Resposta: {ex.best_san} ({ex.ev_best:+.1f}). Nao conta como tentativa."
        self.msg.configure(text=text + f"\nLinha: {ex.line}", fg=GREEN if ok else RED if not gave_up else MUTED)
        for b in (self.btn_hint, self.btn_show):
            b.state(["disabled"])
        self.btn_explain.state(["!disabled"])
        self.btn_next.state(["!disabled"])
        self._update_score()

    def explain(self):
        ex = self.ex
        if not ex:
            return
        prompt = explain.build_prompt(ex.fen, "brancas" if ex.white_to_move else "pretas", ex.best_san,
                                      ex.line, f"{ex.ev_best:+.2f}", ex.played_san, LABELS_PT[ex.label], ex.loss)
        self.app.run_explain(f"{ex.number} {ex.played_san}", prompt)

    def close(self):
        if self.engine is not None:
            try:
                self.engine.close()
            except Exception:
                pass
        self.destroy()


class StatsWindow(tk.Toplevel):
    """Resultados, precisao ao longo do tempo, adversarios e aberturas."""

    def __init__(self, app):
        super().__init__(app.root, bg=BG)
        self.title("Estatisticas")
        r = stats.compute(stats.load_games())
        t = r["total"]
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(padx=16, pady=14)

        top = tk.Frame(wrap, bg=BG)
        top.pack(fill="x")
        for label, value, color in (
                ("Partidas", t["games"], FG), ("Vitorias", t["win"], GREEN), ("Empates", t["draw"], AMBER),
                ("Derrotas", t["loss"], RED),
                ("Precisao media", f"{t['accuracy']:.0f}%" if t["accuracy"] is not None else "\u2014", BLUE)):
            c = Card(top)
            c.pack(side="left", expand=True, fill="x", padx=2)
            tk.Label(c, text=str(value), bg=CARD, fg=color, font=(FONT, 18, "bold")).pack(pady=(8, 0), padx=14)
            tk.Label(c, text=label, bg=CARD, fg=MUTED, font=(FONT, 8)).pack(pady=(0, 8))

        tk.Label(wrap, text="PRECISAO AO LONGO DO TEMPO", bg=BG, fg=MUTED,
                 font=(FONT, 8, "bold")).pack(anchor="w", pady=(12, 4))
        self.chart = tk.Canvas(wrap, width=560, height=150, bg=CARD, highlightbackground=BORDER,
                               highlightthickness=1)
        self.chart.pack()
        self._draw_chart(r["trend"])

        cols = tk.Frame(wrap, bg=BG)
        cols.pack(fill="x", pady=(12, 0))
        self._table(cols, "POR ADVERSARIO", r["opponents"][:8],
                    lambda o: o["name"] + (f" ({o['rating']})" if o.get("rating") else ""))
        self._table(cols, "POR ABERTURA", r["openings"][:8], lambda o: o["name"])
        e = r["errors"]
        tk.Label(wrap, text=f"Erros acumulados: {e['inaccuracy']} imprecisoes \u00b7 {e['mistake']} erros "
                            f"\u00b7 {e['blunder']} gafes", bg=BG, fg=MUTED, font=(FONT, 9)).pack(anchor="w", pady=(10, 0))

    def _draw_chart(self, trend):
        c, W, H, pad = self.chart, 560, 150, 28
        for v in (0, 50, 100):
            y = H - pad - (H - 2 * pad) * v / 100
            c.create_line(pad, y, W - 10, y, fill=BORDER)
            c.create_text(14, y, text=str(v), fill=FAINT, font=(FONT, 8))
        if len(trend) < 2:
            c.create_text(W / 2, H / 2, text="Jogue ao menos 2 partidas para ver a tendencia.",
                          fill=MUTED, font=(FONT, 10))
            return
        pts = []
        for i, (_, acc) in enumerate(trend[-30:]):
            n = len(trend[-30:])
            pts.append((pad + (W - pad - 14) * i / (n - 1), H - pad - (H - 2 * pad) * acc / 100))
        c.create_line(*[v for p in pts for v in p], fill=GREEN, width=2, smooth=True)
        for x, y in pts:
            c.create_oval(x - 3, y - 3, x + 3, y + 3, fill=GREEN, outline="")

    def _table(self, parent, title, rows, name_of):
        box = Card(parent)
        box.pack(side="left", expand=True, fill="both", padx=2, anchor="n")
        tk.Label(box, text=title, bg=CARD, fg=MUTED, font=(FONT, 8, "bold")).pack(anchor="w", padx=12, pady=(8, 4))
        if not rows:
            tk.Label(box, text="\u2014", bg=CARD, fg=FAINT).pack(padx=12, pady=(0, 8))
        for o in rows:
            row = tk.Frame(box, bg=CARD)
            row.pack(fill="x", padx=12, pady=1)
            tk.Label(row, text=name_of(o)[:26], bg=CARD, fg=FG, font=(FONT, 9), anchor="w", width=26).pack(side="left")
            tk.Label(row, text=f"{o['win']}-{o['draw']}-{o['loss']}", bg=CARD, fg=MUTED, font=("Consolas", 9),
                     width=7).pack(side="left")
            tk.Label(row, text=f"{o['accuracy']:.0f}%" if o["accuracy"] is not None else "\u2014", bg=CARD,
                     fg=BLUE, font=("Consolas", 9), width=5).pack(side="left")
        tk.Frame(box, bg=CARD, height=6).pack()


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("ChessMind")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.q = queue.Queue()
        self.runner = None
        self.board = chess.Board()
        self.sugg = []
        self.line_text = ""
        self.white_bottom = True
        self.last_alive = time.time()
        self._drawn = None
        self._paint_pending = False
        self.review_data = None
        self.settings = dict(DEFAULT_SETTINGS)   # compartilhado com o Runner (vale em tempo real)
        self._style()
        self._build()
        self._menu()
        self._refresh_calibration_label()
        self._load_last_review()
        self.draw_board()
        self.draw_bar(None)
        self.set_state("idle")
        self._exclude_from_capture()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self.poll)

    # ================= estilo =================
    def _style(self):
        st = ttk.Style()
        st.theme_use("clam")
        base = dict(background=CARD, foreground=FG, borderwidth=0, focusthickness=0,
                    padding=(12, 7), font=(FONT, 10))
        st.configure("TButton", **base)
        st.map("TButton", background=[("active", "#272b33"), ("disabled", "#181b20")],
               foreground=[("disabled", FAINT)])
        st.configure("Ghost.TButton", **{**base, "background": "#242830"})
        st.map("Ghost.TButton", background=[("active", "#2e333d"), ("disabled", "#181b20")],
               foreground=[("disabled", FAINT)])
        st.configure("Go.TButton", **{**base, "background": "#1f9d6b", "foreground": "white",
                                      "font": (FONT, 12, "bold"), "padding": (12, 10)})
        st.map("Go.TButton", background=[("active", "#27b27c"), ("disabled", "#1a3a2f")])
        st.configure("Stop.TButton", **{**base, "background": "#b13a3a", "foreground": "white",
                                        "font": (FONT, 12, "bold"), "padding": (12, 10)})
        st.map("Stop.TButton", background=[("active", "#cc4848"), ("disabled", "#3a2323")])
        st.configure("TCombobox", fieldbackground="#242830", background="#242830", foreground=FG,
                     arrowcolor=MUTED, bordercolor=BORDER, lightcolor="#242830",
                     darkcolor="#242830", padding=4)
        st.map("TCombobox", fieldbackground=[("readonly", "#242830")],
               foreground=[("readonly", FG)], selectbackground=[("readonly", "#242830")],
               selectforeground=[("readonly", FG)])
        st.configure("TSpinbox", fieldbackground="#242830", foreground=FG, arrowcolor=MUTED,
                     bordercolor=BORDER, lightcolor="#242830", darkcolor="#242830", padding=2)
        self.root.option_add("*TCombobox*Listbox.background", "#242830")
        self.root.option_add("*TCombobox*Listbox.foreground", FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#1f9d6b")

    # ================= layout =================
    def _check(self, parent, text, var, command=None, fg=FG):
        return tk.Checkbutton(parent, text=text, variable=var, bg=CARD, fg=fg,
                              selectcolor="#242830", activebackground=CARD, activeforeground=fg,
                              font=(FONT, 10), highlightthickness=0, bd=0, command=command)

    def _spin_row(self, parent, label, var, lo, hi, inc=1, fmt=None):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", padx=14, pady=1)
        tk.Label(row, text=label, bg=CARD, fg=FG, font=(FONT, 10)).pack(side="left")
        sp = ttk.Spinbox(row, from_=lo, to=hi, increment=inc, width=5, textvariable=var,
                         format=fmt or "%.0f", command=self.sync_settings)
        sp.pack(side="right")
        sp.bind("<FocusOut>", lambda e: self.sync_settings())
        return sp

    def _build(self):
        wrap = tk.Frame(self.root, bg=BG)
        wrap.pack(padx=16, pady=12)

        # ---- coluna do tabuleiro ----
        left = tk.Frame(wrap, bg=BG)
        left.grid(row=0, column=0, sticky="n")
        self.pill = tk.Label(left, text="", bg=CARD, fg=FG, font=(FONT, 10, "bold"),
                             padx=14, pady=6, anchor="w", highlightbackground=BORDER,
                             highlightthickness=1)
        self.pill.pack(fill="x", pady=(0, 8))
        stage = tk.Frame(left, bg=BG)
        stage.pack()
        self.bar = tk.Canvas(stage, width=BAR_W, height=BOARD_PX + 22, bg=BG, highlightthickness=0)
        self.bar.pack(side="left", padx=(0, 6))
        self.canvas = tk.Canvas(stage, width=BOARD_PX + 22, height=BOARD_PX + 22, bg=BG,
                                highlightthickness=0)
        self.canvas.pack(side="left")

        line = Card(left, "Linha prevista")
        line.pack(fill="x", pady=(6, 0))
        self.line_lbl = tk.Label(line, text="—", bg=CARD, fg=FG, font=("Consolas", 10),
                                 anchor="w", justify="left", wraplength=BOARD_PX + BAR_W - 8)
        self.line_lbl.pack(fill="x", padx=14)
        self.last_lbl = tk.Label(line, text="", bg=CARD, fg=MUTED, font=(FONT, 10, "bold"), anchor="w")
        self.last_lbl.pack(fill="x", padx=14, pady=(2, 8))

        tools = tk.Frame(left, bg=BG)
        tools.pack(fill="x", pady=(6, 0))
        self.btn_explain = ttk.Button(tools, text="Explicar jogada", style="Ghost.TButton",
                                      command=self.on_explain)
        self.btn_review = ttk.Button(tools, text="Revisao da partida", style="Ghost.TButton",
                                     command=self.open_review)
        self.btn_explain.pack(side="left", expand=True, fill="x", padx=(0, 6))
        self.btn_review.pack(side="left", expand=True, fill="x")

        self.log_open = False
        self.log_btn = tk.Label(left, text="▸ Mostrar log", bg=BG, fg=FAINT,
                                font=(FONT, 9), cursor="hand2")
        self.log_btn.pack(anchor="w", pady=(4, 0))
        self.log_btn.bind("<Button-1>", self.toggle_log)
        self.log = tk.Text(left, width=58, height=5, bg=CARD, fg=MUTED, bd=0, font=("Consolas", 9),
                           state="disabled", highlightbackground=BORDER, highlightthickness=1)

        # ---- coluna de controles ----
        right = tk.Frame(wrap, bg=BG, width=330)
        right.grid(row=0, column=1, sticky="n", padx=(16, 0))

        head = tk.Frame(right, bg=BG)
        head.pack(fill="x", pady=(0, 6))
        logo = tk.Canvas(head, width=36, height=36, bg=BG, highlightthickness=0)
        logo.create_oval(1, 1, 35, 35, fill="#1f9d6b", outline="")
        logo.create_text(18, 19, text="♞", font=("Segoe UI Symbol", 18), fill="white")
        logo.pack(side="left")
        tt = tk.Frame(head, bg=BG)
        tt.pack(side="left", padx=10)
        tk.Label(tt, text="ChessMind", bg=BG, fg=FG, font=(FONT, 15, "bold")).pack(anchor="w")
        tk.Label(tt, text="Coach e bot de xadrez", bg=BG, fg=MUTED, font=(FONT, 9)).pack(anchor="w")

        row = tk.Frame(right, bg=BG)
        row.pack(fill="x")
        self.btn_chrome = ttk.Button(row, text="Abrir Chrome", style="Ghost.TButton",
                                     command=self.open_chrome)
        self.btn_cal = ttk.Button(row, text="Calibrar", style="Ghost.TButton",
                                  command=self.calibrate)
        self.btn_chrome.pack(side="left", expand=True, fill="x", padx=(0, 6))
        self.btn_cal.pack(side="left", expand=True, fill="x")
        self.cal_label = tk.Label(right, text="", bg=BG, fg=MUTED, font=(FONT, 9), anchor="w")
        self.cal_label.pack(fill="x", pady=(2, 6))

        c2 = Card(right, "Motor")
        c2.pack(fill="x", pady=(0, 6))
        self.preset = ttk.Combobox(c2, values=list(PRESETS), state="readonly", font=(FONT, 10))
        self.preset.set(list(PRESETS)[0])
        self.preset.pack(fill="x", padx=14, pady=(2, 3))
        self.lines = tk.IntVar(value=3)
        self._spin_row(c2, "Jogadas sugeridas", self.lines, 1, 3)
        self.plies = tk.IntVar(value=self.settings["plies"])
        self._spin_row(c2, "Previsao (lances a frente)", self.plies, 2, 12)
        two = tk.Frame(c2, bg=CARD)
        two.pack(fill="x", padx=10)
        self.use_arrows = tk.BooleanVar(value=True)
        self._check(two, "Setas no Chrome", self.use_arrows, self.sync_settings).pack(side="left")
        self.ponder = tk.BooleanVar(value=True)
        self._check(two, "Pensar na vez dele", self.ponder, self.sync_settings).pack(side="left", padx=(10, 0))
        self.use_book = tk.BooleanVar(value=True)
        self._check(c2, "Livro de aberturas e tablebases", self.use_book,
                    self.sync_settings).pack(anchor="w", padx=10)
        self.collect = tk.BooleanVar(value=False)       # opcao no menu Ferramentas
        tk.Frame(c2, bg=CARD, height=4).pack()

        c3 = Card(right, "Jogar sozinho")
        c3.pack(fill="x", pady=(0, 6))
        self.autoplay = tk.BooleanVar(value=False)
        self._check(c3, "Ativar (somente contra bots)", self.autoplay, self.on_autoplay,
                    fg=AMBER).pack(anchor="w", padx=10)
        self.delay = tk.DoubleVar(value=self.settings["delay"])
        self._spin_row(c3, "Atraso base (s)", self.delay, 0.3, 8, 0.1, "%.1f")
        self.humanize = tk.BooleanVar(value=True)
        self._check(c3, "Ritmo humano (posicao e relogio)", self.humanize,
                    self.sync_settings).pack(anchor="w", padx=10)
        self.adaptive = tk.BooleanVar(value=True)
        self.chk_adaptive = self._check(c3, "Forca adaptativa (sobe se perder)", self.adaptive,
                                        self.sync_settings)
        self.chk_adaptive.pack(anchor="w", padx=10)
        self.next_game = tk.BooleanVar(value=False)
        self._check(c3, "Iniciar a proxima partida sozinho", self.next_game,
                    self.on_next_game).pack(anchor="w", padx=10, pady=(0, 4))

        self.btn_run = ttk.Button(right, text="Iniciar", style="Go.TButton", command=self.toggle)
        self.btn_run.pack(fill="x", pady=(0, 6))

        c4 = Card(right, "Melhores jogadas")
        c4.pack(fill="x")
        self.rows = []
        for i in range(3):
            r = tk.Frame(c4, bg=CARD)
            r.pack(fill="x", padx=14, pady=1)
            dot = tk.Canvas(r, width=14, height=14, bg=CARD, highlightthickness=0)
            dot.create_oval(1, 1, 13, 13, fill=ARROWS[i], outline="")
            dot.pack(side="left")
            mv = tk.Label(r, text="", bg=CARD, fg=FG, font=(FONT, 13, "bold"), anchor="w", width=8)
            mv.pack(side="left", padx=10)
            ev = tk.Label(r, text="", bg=CARD, fg=MUTED, font=("Consolas", 12, "bold"), anchor="e")
            ev.pack(side="right")
            self.rows.append((r, mv, ev))
        tk.Label(c4, text="+ favorece voce   ·   #N = mate em N", bg=CARD, fg=FAINT,
                 font=(FONT, 8)).pack(anchor="w", padx=14, pady=(1, 6))

    def _menu(self):
        m = tk.Menu(self.root, tearoff=0)
        tools = tk.Menu(m, tearoff=0)
        tools.add_command(label="Treino a partir dos erros", command=lambda: TrainerWindow(self))
        tools.add_command(label="Estatisticas", command=lambda: StatsWindow(self))
        tools.add_command(label="Revisao da ultima partida", command=self.open_review)
        tools.add_separator()
        tools.add_command(label="Redefinir a forca aprendida (por adversario)", command=self.reset_strength)
        tools.add_checkbutton(label="Coletar imagens para treinar a visao", variable=self.collect,
                              command=self.sync_settings)
        tools.add_command(label="Abrir pasta das partidas", command=lambda: self._open_dir(GAMES_DIR))
        tools.add_command(label="Abrir pasta de logs", command=lambda: self._open_dir(log.LOG_DIR))
        m.add_cascade(label="Ferramentas", menu=tools)
        self.root.config(menu=m)

    def reset_strength(self):
        if messagebox.askyesno("Redefinir forca", "Apagar o nivel de forca aprendido contra cada bot? "
                               "O ajuste recomeca abaixo do maximo.", icon="warning"):
            strength.StrengthManager().reset()
            self.chk_adaptive.configure(text="Forca adaptativa (sobe se perder)")
            self.write_log("Forca aprendida redefinida.")

    def _open_dir(self, path):
        path.mkdir(exist_ok=True)
        os.startfile(str(path))

    def toggle_log(self, _=None):
        self.log_open = not self.log_open
        if self.log_open:
            self.log.pack(fill="x", pady=(4, 0))
            self.log_btn.configure(text="▾ Ocultar log")
        else:
            self.log.pack_forget()
            self.log_btn.configure(text="▸ Mostrar log")

    def _exclude_from_capture(self):
        if os.environ.get("CHESSMIND_DEBUG"):
            return
        try:  # a interface nao entra na captura de tela
            import ctypes
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x11)
        except Exception:
            pass

    # ================= configuracoes =================
    def sync_settings(self):
        """Copia os controles para o dict que o Runner le a cada ciclo."""
        try:
            self.settings["plies"] = max(2, min(12, int(float(self.plies.get()))))
            self.settings["delay"] = max(0.3, min(8.0, float(self.delay.get())))
        except (tk.TclError, ValueError):
            pass
        self.settings["show_arrows"] = bool(self.use_arrows.get())
        self.settings["ponder"] = bool(self.ponder.get())
        self.settings["autoplay"] = bool(self.autoplay.get())
        self.settings["humanize"] = bool(self.humanize.get())
        self.settings["next_game"] = bool(self.next_game.get())
        self.settings["collect"] = bool(self.collect.get())
        self.settings["book"] = bool(self.use_book.get())
        self.settings["adaptive"] = bool(self.adaptive.get())

    def on_autoplay(self):
        if self.autoplay.get():
            ok = messagebox.askyesno(
                "Jogar sozinho",
                "O ChessMind vai clicar no tabuleiro do Chrome e jogar por voce.\n\n"
                "Use somente em partidas contra bots. Ativar?", icon="warning")
            if not ok:
                self.autoplay.set(False)
        self.sync_settings()

    def on_next_game(self):
        if self.next_game.get():
            ok = messagebox.askyesno(
                "Proxima partida",
                "Ao fim de cada partida contra bot, o ChessMind vai clicar em Nova partida/Revanche "
                "e continuar jogando (ate 10 partidas seguidas).\n\nSo age com 'Jogar sozinho' ligado. "
                "Ativar?", icon="warning")
            if not ok:
                self.next_game.set(False)
        self.sync_settings()

    # ================= util =================
    def write_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def set_state(self, state, text=None):
        """state: idle | live | wait | warn | error  -> cor do indicador."""
        colors = {"idle": FAINT, "live": GREEN, "wait": BLUE, "warn": AMBER, "error": RED}
        label = text or {"idle": "Parado"}.get(state, "")
        self.pill.configure(text="●  " + label, fg=colors[state])

    def _refresh_calibration_label(self):
        if config.CONFIG_PATH.exists() and config.TEMPLATES_PATH.exists():
            cal = config.load_calibration()
            self.white_bottom = cal["white_bottom"]
            side = "brancas" if self.white_bottom else "pretas"
            self.cal_label.configure(text=f"✓ Calibrado · voce joga de {side}", fg=GREEN)
        else:
            self.cal_label.configure(text="Ainda nao calibrado", fg=RED)

    def _load_last_review(self):
        files = sorted(GAMES_DIR.glob("*.json")) if GAMES_DIR.exists() else []
        if files:
            try:
                self.review_data = json.loads(files[-1].read_text(encoding="utf-8"))
            except Exception:
                self.review_data = None
        self.btn_review.state(["!disabled"] if self.review_data else ["disabled"])

    # ================= acoes =================
    def open_chrome(self):
        from chessmind import pwsource
        try:
            pwsource.launch_chrome()
            self.write_log("Chrome do coach aberto. Entre numa partida contra o bot (posicao inicial).")
        except Exception as e:
            self.write_log(f"Erro ao abrir o Chrome: {e}")

    def calibrate(self):
        if self.runner:
            self.write_log("Pare antes de calibrar.")
            return
        self.btn_cal.state(["disabled"])
        self.set_state("wait", "Calibrando...")

        def work():
            p = subprocess.Popen([sys.executable, "calibrate_pw.py"], cwd=str(config.ROOT),
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in p.stdout:
                self.q.put(("log", line))
            p.wait()
            self.q.put(("calibrated", p.returncode))

        threading.Thread(target=work, daemon=True).start()

    def toggle(self):
        if self.runner:
            self.runner.stop()
            self.btn_run.state(["disabled"])
            self.set_state("wait", "Parando...")
            self.root.after(4000, self._force_stop, self.runner)
            return
        if not (config.CONFIG_PATH.exists() and config.TEMPLATES_PATH.exists()):
            self.write_log("Calibre primeiro.")
            self.set_state("warn", "Calibre antes de iniciar")
            return
        self.sync_settings()
        self.last_alive = time.time()
        self.runner = Runner(self.q, self.preset.get(), int(self.lines.get()), self.settings)
        self.runner.start()
        self.btn_run.configure(text="Parar", style="Stop.TButton")
        self.btn_cal.state(["disabled"])
        self.btn_chrome.state(["disabled"])

    def _force_stop(self, runner):
        if self.runner is runner:
            self.write_log("O motor nao respondeu ao parar; interface liberada.")
            self.on_stopped()

    def on_stopped(self):
        self.runner = None
        self.last_alive = time.time()
        self.btn_run.state(["!disabled"])
        self.btn_run.configure(text="Iniciar", style="Go.TButton")
        self.btn_cal.state(["!disabled"])
        self.btn_chrome.state(["!disabled"])
        self.set_state("idle")
        self.set_sugg([])

    # ---- explicacoes (Claude) e revisao ----
    def on_explain(self):
        if not self.sugg:
            self.write_log("Nao ha sugestao para explicar agora.")
            return
        _, san, ev = self.sugg[0]
        side = "brancas" if self.board.turn == chess.WHITE else "pretas"
        prompt = explain.build_prompt(self.board.fen(), side, san, self.line_text or san, ev)
        self.run_explain(f"Por que {san}?", prompt)

    def run_explain(self, title, prompt):
        ok, why = explain.available()
        if not ok and not explain.is_cached(prompt):       # explicacao ja em cache funciona sem chave
            messagebox.showinfo("Explicacao indisponivel", why)
            return
        self.set_state("wait", "Pedindo explicacao ao Claude...")

        def work():
            try:
                self.q.put(("explain", title, explain.explain(prompt)))
            except Exception as e:
                L.warning("explicacao falhou: %s", e)
                self.q.put(("explain", title, f"Nao foi possivel obter a explicacao:\n{type(e).__name__}: {e}"))

        threading.Thread(target=work, daemon=True).start()

    def open_review(self):
        if self.review_data:
            ReviewWindow(self, self.review_data)

    # ================= desenho =================
    def sq_xy(self, sq):
        f, r = chess.square_file(sq), chess.square_rank(sq)
        col = f if self.white_bottom else 7 - f
        row = 7 - r if self.white_bottom else r
        return col * SQ, row * SQ

    def draw_board(self):
        """Agenda UM redesenho por rodada de eventos: varias mensagens seguidas viram 1 desenho."""
        if not self._paint_pending:
            self._paint_pending = True
            self.root.after_idle(self._paint_board)

    def _paint_board(self):
        self._paint_pending = False
        key = (self.board.fen(), tuple(u for u, _, _ in self.sugg), self.white_bottom)
        if key == self._drawn:           # nada mudou: nao redesenha (evita piscar)
            return
        self._drawn = key
        c = self.canvas
        c.addtag_all("old")              # desenha o novo e so depois apaga o antigo: sem quadro em branco
        best = chess.Move.from_uci(self.sugg[0][0]) if self.sugg else None
        for sq in chess.SQUARES:
            x, y = self.sq_xy(sq)
            light = (chess.square_file(sq) + chess.square_rank(sq)) % 2 == 1
            col = LIGHT if light else DARK
            if best and sq in (best.from_square, best.to_square):
                col = TINT_LIGHT if light else TINT_DARK
            c.create_rectangle(x, y, x + SQ, y + SQ, fill=col, width=0)
        files = "abcdefgh" if self.white_bottom else "hgfedcba"
        ranks = "87654321" if self.white_bottom else "12345678"
        for i in range(8):
            c.create_text(i * SQ + SQ / 2, BOARD_PX + 11, text=files[i], fill=MUTED,
                          font=(FONT, 8, "bold"))
            c.create_text(BOARD_PX + 11, i * SQ + SQ / 2, text=ranks[i], fill=MUTED,
                          font=(FONT, 8, "bold"))
        font = ("Segoe UI Symbol", int(SQ * 0.72))
        for sq in chess.SQUARES:
            p = self.board.piece_at(sq)
            if not p:
                continue
            x, y = self.sq_xy(sq)
            cx, cy = x + SQ / 2, y + SQ / 2 + 2
            c.create_text(cx, cy, text=GLYPH[p.symbol().lower()], font=font,
                          fill="#fbfbfb" if p.color else "#1b1b1b")
            c.create_text(cx, cy, text=GLYPH[p.symbol().upper()], font=font, fill="#000")
        for i, (uci, _, _) in enumerate(self.sugg):
            mv = chess.Move.from_uci(uci)
            x1, y1 = self.sq_xy(mv.from_square)
            x2, y2 = self.sq_xy(mv.to_square)
            w = 9 - 3 * i
            c.create_line(x1 + SQ / 2, y1 + SQ / 2, x2 + SQ / 2, y2 + SQ / 2, fill=ARROWS[i], width=w,
                          arrow=tk.LAST, arrowshape=(w * 1.5, w * 1.8, w * .8), capstyle=tk.ROUND)
        c.delete("old")

    def draw_bar(self, value):
        """Barra de vantagem do ponto de vista de quem joga (voce)."""
        b = self.bar
        b.addtag_all("old")
        h = BOARD_PX
        frac = 1 / (1 + math.exp(-value / 1.6)) if value is not None else 0.5
        top_col = "#2b2b2b" if self.white_bottom else "#f2f2f2"
        bot_col = "#f2f2f2" if self.white_bottom else "#2b2b2b"
        b.create_rectangle(0, 0, BAR_W, h, fill=top_col, width=0)
        b.create_rectangle(0, h * (1 - frac), BAR_W, h, fill=bot_col, width=0)
        b.create_line(0, h / 2, BAR_W, h / 2, fill=GREEN, width=1)
        if value is not None:
            txt = f"{value:+.1f}" if abs(value) < 10 else "M"
            b.create_text(BAR_W / 2, h + 11, text=txt, fill=FG, font=(FONT, 8, "bold"))
        b.delete("old")

    def set_sugg(self, sugg):
        self.sugg = sugg
        for i, (_, mv, ev) in enumerate(self.rows):
            if i < len(sugg):
                _, san, e = sugg[i]
                v = ev_to_pawns(e)
                mv.configure(text=san)
                ev.configure(text=e, fg=GREEN if v > 0.3 else RED if v < -0.3 else MUTED)
            else:
                mv.configure(text="—" if i == 0 else "")
                ev.configure(text="")
        self.draw_bar(ev_to_pawns(sugg[0][2]) if sugg else None)
        self.draw_board()

    # ================= mensagens =================
    def poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self.write_log(msg[1])
                elif kind == "calibrated":
                    self.btn_cal.state(["!disabled"])
                    self._refresh_calibration_label()
                    ok = msg[1] == 0
                    self.set_state("idle" if ok else "warn",
                                   None if ok else "Calibracao falhou (veja o log)")
                    if not ok and not self.log_open:
                        self.toggle_log()
                    self.draw_board()
                elif kind == "alive":
                    self.last_alive = time.time()
                elif kind == "orient":
                    self.white_bottom = msg[1]
                    self.draw_board()
                    self.draw_bar(None)
                elif kind == "strength":
                    _, elo, name = msg
                    self.chk_adaptive.configure(
                        text=f"Forca adaptativa: {elo if elo else 'maxima'}" + (f" ({name})" if name else ""))
                elif kind == "line":
                    self.line_text = msg[1].split("  (")[0]
                    self.line_lbl.configure(text=msg[1] or "—")
                elif kind == "lastmove":
                    _, number, san, label, loss, best = msg
                    extra = "" if label in ("best", "excellent") else f"  · melhor: {best}"
                    self.last_lbl.configure(text=f"Seu lance {number} {san}: {LABELS_PT[label]}{extra}",
                                            fg=LABEL_COLORS[label])
                elif kind == "review":
                    try:
                        self.review_data = json.loads(open(msg[2], encoding="utf-8").read())
                    except Exception:
                        self.review_data = None
                    self.btn_review.state(["!disabled"] if self.review_data else ["disabled"])
                    acc = msg[1].get("accuracy")
                    self.write_log(f"Partida salva ({msg[2]}). Precisao: {acc}%")
                elif kind == "explain":
                    TextWindow(self.root, msg[1], msg[2])
                    self.set_state("live" if self.runner else "idle", None if self.runner else None)
                elif kind == "auto":
                    self.autoplay.set(bool(msg[1]))
                    self.sync_settings()
                    if not msg[1] and not self.log_open:
                        self.toggle_log()
                elif kind == "status":
                    text = msg[1]
                    state = "live" if text.startswith(("Sua vez", "Jogando", "Jogou")) else \
                        "warn" if text.startswith(("Falha", "Nenhum", "Chrome", "Leitura", "Lance",
                                                   "Modo")) else "wait"
                    self.set_state(state, text)
                elif kind == "board":
                    self.board = chess.Board(msg[1])
                    self.draw_board()
                elif kind == "sugg":
                    self.board = chess.Board(msg[1])
                    self.set_sugg(msg[2])
                elif kind == "clear":
                    if self.sugg:
                        self.set_sugg([])
                elif kind == "error":
                    self.write_log("ERRO: " + msg[1])
                    self.set_state("error", "Erro: " + msg[1][:60])
                    if not self.log_open:
                        self.toggle_log()
                elif kind == "stopped":
                    self.on_stopped()
        except queue.Empty:
            pass
        if self.runner and time.time() - self.last_alive > 6 and self.sugg:
            self.set_sugg([])
            self.set_state("error", "Sem resposta do motor")
            self.write_log("Sem resposta ha 6s. Pare e inicie de novo se continuar.")
        self.root.after(100, self.poll)

    def on_close(self):
        self.settings["autoplay"] = False
        if self.runner:
            self.runner.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if not lock.acquire():
        import tkinter.messagebox as mb
        mb.showerror("ChessMind", "Ja existe outro ChessMind em execucao (PID %s).\n"
                     "Feche-o antes de abrir este: duas instancias disputam as setas e "
                     "fazem a tela piscar." % lock.owner_pid())
        sys.exit(1)
    App().run()
