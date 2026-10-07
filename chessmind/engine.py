import sys
import time

import chess
import chess.engine
import chess.syzygy

from .config import ROOT, find_stockfish

PONDER_MIN_DEPTH = 14
SYZYGY_DIR = ROOT / "engine" / "syzygy"


def position_key(board):
    """Chave da posicao (pecas, vez, roque, en passant), sem os contadores de lances."""
    return " ".join(board.fen().split()[:4])


class Coach:
    def __init__(self, think_time=0.4, lines=3, skill=None, threads=1, hash_mb=128, syzygy_dir=None):
        # Windows: prioridade abaixo do normal + sem janela de console. Com varias threads o
        # motor disputava a CPU com o Chrome e a tela engasgava quando ele comecava a calcular.
        flags = (0x00004000 | 0x08000000) if sys.platform == "win32" else 0
        kw = {"creationflags": flags} if flags else {}
        self.engine = chess.engine.SimpleEngine.popen_uci(find_stockfish(), **kw)
        opts = {"Threads": threads, "Hash": hash_mb}
        if skill is not None:
            opts["Skill Level"] = skill
        # Tablebases Syzygy: o Stockfish as usa na busca e nos tambem para jogar finais na hora
        self.tb = None
        tb_dir = syzygy_dir if syzygy_dir is not None else SYZYGY_DIR
        if tb_dir.exists() and any(tb_dir.glob("*.rtb?")):
            opts["SyzygyPath"] = str(tb_dir)
            try:
                self.tb = chess.syzygy.open_tablebase(str(tb_dir))
            except Exception:
                self.tb = None
        self.engine.configure(opts)
        elo_opt = self.engine.options.get("UCI_Elo")
        self.elo_range = (elo_opt.min, elo_opt.max) if elo_opt and elo_opt.min else (1320, 3190)
        self.think_time = think_time
        self.lines = lines
        self.last_pvs = []          # linha principal (lista de lances) de cada sugestao
        self.last_from_ponder = False
        self.last_from_tb = False
        self.last_gap = None
        self.last_full = []         # sugestoes em FORCA TOTAL (antes de qualquer enfraquecimento)
        self.last_full_pvs = []
        self.last_weakened = False  # o 1o lance foi escolhido com forca limitada
        self._ponder = None         # AnalysisResult em andamento
        self._ponder_key = None
        self._cands = []            # posicoes (vez NOSSA) apos cada resposta provavel do adversario
        self._cache = {}            # chave da posicao -> (profundidade, infos)
        self._idx = -1
        self._slice_end = 0.0

    # ---------- "pensar na vez do adversario" (varias respostas provaveis) ----------
    def start_multi_ponder(self, board, k=3, window=1.0):
        """Chame quando for a vez do ADVERSARIO em `board`: escolhe as k respostas mais provaveis
        (dentro de `window` peoes da melhor, do ponto de vista dele) e passa a analisar, em
        revezamento, a posicao resultante de cada uma. Chame `ponder_tick()` a cada ciclo."""
        self.reset_ponder()
        if board.is_game_over():
            return
        infos = self.engine.analyse(board, chess.engine.Limit(time=0.15), multipv=max(k, 2))
        best = infos[0]["score"].pov(board.turn).score(mate_score=1000)
        for info in infos[:k]:
            if best - info["score"].pov(board.turn).score(mate_score=1000) <= window * 100:
                after = board.copy()
                after.push(info["pv"][0])
                if not after.is_game_over():
                    self._cands.append(after)
        self.ponder_tick()

    def start_ponder(self, board):
        """Analisa em segundo plano uma unica posicao esperada."""
        self.reset_ponder()
        if not board.is_game_over():
            self._cands = [board.copy()]
            self.ponder_tick()

    def ponder_tick(self):
        """Revezamento das candidatas; barato quando nao ha troca (chamar a cada ciclo)."""
        if not self._cands:
            return
        now = time.time()
        if self._ponder is not None and (len(self._cands) == 1 or now < self._slice_end):
            return
        self._harvest()
        self._idx = (self._idx + 1) % len(self._cands)
        b = self._cands[self._idx]
        self._ponder = self.engine.analysis(b, multipv=max(self.lines, 2))
        self._ponder_key = position_key(b)
        self._slice_end = now + (2.5 if self._idx == 0 else 1.5)    # a mais provavel ganha mais tempo

    def _harvest(self):
        """Para a analise em andamento e guarda o resultado mais profundo de cada posicao."""
        key, infos = self.stop_ponder()
        if key and infos:
            depth = infos[0].get("depth", 0)
            old = self._cache.get(key)
            if old is None or depth >= old[0]:
                self._cache[key] = (depth, infos)

    def stop_ponder(self):
        """Para a analise e devolve (chave, lista_de_infos) do que ela achou."""
        if self._ponder is None:
            return None, []
        a, key = self._ponder, self._ponder_key
        self._ponder = self._ponder_key = None
        a.stop()
        a.wait()
        return key, [dict(i) for i in a.multipv if i and "pv" in i]

    def reset_ponder(self):
        self._harvest()
        self._cands, self._cache, self._idx = [], {}, -1

    # ---------- tablebases ----------
    def tablebase_suggest(self, board):
        """Finais de ate 5 pecas (se houver tabelas): lances ordenados do melhor ao pior,
        [(lance, 'TB+'/'TB='/'TB-', san)]. None se nao se aplica."""
        if self.tb is None or board.castling_rights or board.is_game_over():
            return None
        if chess.popcount(board.occupied) > 7:
            return None
        ranked = []
        try:
            for m in board.legal_moves:
                b = board.copy()
                b.push(m)
                wdl = -self.tb.probe_wdl(b)              # do ponto de vista de quem joga agora
                dtz = abs(self.tb.probe_dtz(b))
                # vitoria: menor DTZ; derrota: maior DTZ (resistir); empate/maldicao: indiferente
                key = (-wdl, dtz if wdl > 0 else -dtz if wdl < 0 else 0)
                ranked.append((key, m, wdl))
        except (KeyError, chess.syzygy.MissingTableError):
            return None
        if not ranked:
            return None
        ranked.sort(key=lambda t: t[0])
        out = []
        for _, m, wdl in ranked[:max(self.lines, 1)]:
            text = "TB+" if wdl == 2 else "TB-" if wdl == -2 else "TB="
            out.append((m, text, board.san(m)))
        return out

    # ---------- sugestoes ----------
    def suggest(self, board, elo=None):
        """Lista de (lance, avaliacao, san) do melhor ao pior. Linhas completas em self.last_pvs.

        Com `elo` (dentro da faixa do motor), o 1o lance e o escolhido por um Stockfish de forca
        LIMITADA (UCI_Elo) - e o que o bot deve jogar; as avaliacoes continuam em forca total e
        ficam em `last_full`/`last_full_pvs` (revisao e tempo usam o melhor lance de verdade)."""
        self.last_from_ponder = self.last_from_tb = self.last_weakened = False
        tb = self.tablebase_suggest(board)
        if tb:
            self.reset_ponder()
            self.last_from_tb, self.last_gap = True, None
            self.last_pvs = self.last_full_pvs = [[m] for m, _, _ in tb]
            self.last_full = tb
            return tb
        self._harvest()
        hit = self._cache.get(position_key(board))
        self._cands, self._cache, self._idx = [], {}, -1
        if hit and hit[0] >= PONDER_MIN_DEPTH:
            infos, self.last_from_ponder = hit[1], True      # o adversario jogou o previsto
        else:
            # multipv >= 2 mesmo com 1 linha: precisamos da diferenca entre o 1o e o 2o lance
            infos = self.engine.analyse(board, chess.engine.Limit(time=self.think_time),
                                        multipv=max(self.lines, 2))
        infos = [i for i in infos if "pv" in i]          # sem lances legais (mate/afogamento): vazio
        out, self.last_pvs, scores = [], [], []
        for info in infos:
            score = info["score"].pov(board.turn)
            scores.append(score.score(mate_score=1000) / 100)
            text = f"#{score.mate()}" if score.is_mate() else f"{score.score() / 100:+.2f}"
            out.append((info["pv"][0], text, board.san(info["pv"][0])))
            self.last_pvs.append(list(info["pv"]))
        # vantagem do melhor lance sobre o segundo (em peoes); None se so ha um lance legal
        self.last_gap = scores[0] - scores[1] if len(scores) > 1 else None
        self.last_pvs = self.last_pvs[:self.lines]
        out = out[:self.lines]
        self.last_full, self.last_full_pvs = list(out), list(self.last_pvs)
        if elo is not None and out and elo < self.elo_range[1]:
            out = self._weaken(board, out, int(elo))
        return out

    def _weaken(self, board, out, elo):
        """Troca o 1o lance pelo escolhido por um Stockfish de forca limitada (UCI_Elo)."""
        move = self.play_limited(board, elo)
        if move is None or move == out[0][0]:
            self.last_weakened = move is not None
            return out
        known = {m: ev for m, ev, _ in out}
        if move in known:
            ev = known[move]
        else:
            ev = f"{self.eval_after(board, move):+.2f}"
        pv = next((pv for pv, o in zip(self.last_pvs, out) if o[0] == move), [move])
        out = [(move, ev, board.san(move))] + [o for o in out if o[0] != move][:max(self.lines - 1, 0)]
        self.last_pvs = [pv] + [p for p in self.last_pvs if p and p[0] != move][:max(self.lines - 1, 0)]
        self.last_weakened = True
        return out

    def play_limited(self, board, elo, seconds=0.25):
        """Lance escolhido com UCI_LimitStrength/UCI_Elo; a analise em forca total nao muda."""
        lo, hi = self.elo_range
        if elo >= hi or board.is_game_over():
            return None
        self.reset_ponder()
        self.engine.configure({"UCI_LimitStrength": True, "UCI_Elo": max(lo, elo)})
        try:
            return self.engine.play(board, chess.engine.Limit(time=seconds)).move
        finally:
            self.engine.configure({"UCI_LimitStrength": False})

    def eval_after(self, board, move, seconds=0.25):
        """Avaliacao (em peoes, do ponto de vista de quem fez o lance) depois de `move`."""
        self.reset_ponder()
        mover = board.turn
        after = board.copy()
        after.push(move)
        info = self.engine.analyse(after, chess.engine.Limit(time=seconds))
        return info["score"].pov(mover).score(mate_score=1000) / 100

    def close(self):
        try:
            self.reset_ponder()
        except Exception:
            pass
        if self.tb is not None:
            self.tb.close()
        self.engine.quit()
