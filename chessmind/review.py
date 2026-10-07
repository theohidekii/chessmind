"""Classificacao dos seus lances, revisao da partida e historico em disco."""
import json
import math
import re
import time
from dataclasses import asdict, dataclass, field

import chess
import chess.pgn

from . import config
from .openings import opening_name
from .timing import ev_to_pawns

GAMES_DIR = config.ROOT / "games"

LABELS_PT = {"best": "Melhor", "excellent": "Excelente", "good": "Bom",
             "inaccuracy": "Imprecisao", "mistake": "Erro", "blunder": "Gafe"}
NAG = {"inaccuracy": chess.pgn.NAG_DUBIOUS_MOVE, "mistake": chess.pgn.NAG_MISTAKE,
       "blunder": chess.pgn.NAG_BLUNDER}


WIN_WORDS = ("venceu", "ganhou", "vitoria", "vitória", "won", "victory", "vencedor")
LOSS_WORDS = ("perdeu", "lost", "derrota", "defeat")
DRAW_WORDS = ("empate", "draw", "stalemate", "afogamento")


def parse_opponent(text):
    """'Nora (2200) 5:41' -> {'name': 'Nora', 'rating': 2200}; None se vazio."""
    text = (text or "").strip()
    if not text:
        return None
    m = re.match(r"^\s*(.+?)\s*\((\d{2,4})\)", text)
    if m:
        return {"name": m.group(1).strip(), "rating": int(m.group(2))}
    return {"name": text.split()[0][:30], "rating": None}


def infer_outcome(text, opponent_name=None):
    """'win' | 'loss' | 'draw' | None a partir do texto da janela de fim de jogo (do SEU ponto
    de vista). Se o texto cita o adversario ('Nora venceu'), a leitura se inverte."""
    low = (text or "").lower()
    if not low:
        return None
    if any(w in low for w in DRAW_WORDS):
        return "draw"
    name = (opponent_name or "").lower()
    if name and name in low:
        if any(w in low for w in WIN_WORDS):
            return "loss"
        if any(w in low for w in LOSS_WORDS):
            return "win"
    if any(w in low for w in LOSS_WORDS):
        return "loss"
    if any(w in low for w in WIN_WORDS):
        return "win"
    return None


def outcome_from_result(result, user_is_white):
    """'1-0' etc. -> 'win' | 'loss' | 'draw' do ponto de vista do usuario; None se '*'."""
    if result == "1/2-1/2":
        return "draw"
    if result in ("1-0", "0-1"):
        return "win" if (result == "1-0") == user_is_white else "loss"
    return None


def win_percent(pawns):
    """Chance de vitoria (0-100) para uma avaliacao em peoes (formula do Lichess)."""
    cp = max(-1000.0, min(1000.0, pawns * 100.0))
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def classify(ev_best, ev_played, is_best_move):
    """(rotulo, perda_em_pontos_de_win%) comparando seu lance com o melhor do motor."""
    loss = max(0.0, win_percent(ev_best) - win_percent(ev_played))
    if is_best_move or loss <= 0.5:
        return "best", loss
    if loss <= 2:
        return "excellent", loss
    if loss <= 5:
        return "good", loss
    if loss <= 10:
        return "inaccuracy", loss
    if loss <= 20:
        return "mistake", loss
    return "blunder", loss


def move_accuracy(loss):
    """Precisao (0-100) de um lance dado a perda de win% (formula do Lichess)."""
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * loss) - 3.1669))


@dataclass
class MoveReview:
    number: str            # "12." ou "12..."
    san: str
    best_san: str
    ev_best: float
    ev_played: float
    loss: float
    label: str
    fen_before: str
    line: list = field(default_factory=list)      # linha do motor (SAN) a partir da posicao


class GameReview:
    def __init__(self, user_is_white):
        self.user_is_white = user_is_white
        self.moves = []
        self.pending = None
        self.saved_path = None
        self.finished = False
        self.opponent = None        # {'name', 'rating'} lido da pagina
        self.outcome = None         # 'win' | 'loss' | 'draw' (se o tabuleiro nao decidir sozinho)

    # ---- durante a partida ----
    def start_turn(self, board, sugg, pv):
        """Chame na sua vez, com as sugestoes [(move, ev_texto, san)] e a linha principal."""
        if not sugg:
            self.pending = None
            return
        self.pending = dict(
            board=board.copy(stack=True), n=len(board.move_stack),
            top=[(m, ev_to_pawns(ev)) for m, ev, _ in sugg], best_san=sugg[0][2],
            line=[board.variation_san(pv[:6])] if pv else [])

    def observe(self, board, coach=None):
        """Chame quando a posicao mudar. Identifica o lance que voce fez e o classifica.
        Retorna o MoveReview, ou None."""
        p = self.pending
        if not p:
            return None
        n = p["n"]
        stack = board.move_stack
        if len(stack) < n or stack[:n] != p["board"].move_stack:
            self.pending = None        # tabuleiro foi ressincronizado: nao da para identificar
            return None
        if len(stack) == n:
            return None                # ainda nao jogou
        self.pending = None
        move = stack[n]
        before = p["board"]
        known = {m: ev for m, ev in p["top"]}
        if move in known:
            ev_played = known[move]
        elif coach is not None:
            ev_played = coach.eval_after(before, move)
        else:
            return None
        ev_best = p["top"][0][1]
        label, loss = classify(ev_best, ev_played, move == p["top"][0][0])
        number = f"{before.fullmove_number}." if before.turn == chess.WHITE else f"{before.fullmove_number}..."
        mr = MoveReview(number=number, san=before.san(move), best_san=p["best_san"],
                        ev_best=round(ev_best, 2), ev_played=round(ev_played, 2),
                        loss=round(loss, 1), label=label, fen_before=before.fen(),
                        line=p["line"])
        self.moves.append(mr)
        return mr

    # ---- fim da partida ----
    def summary(self, board=None):
        n = len(self.moves)
        counts = {k: 0 for k in LABELS_PT}
        for m in self.moves:
            counts[m.label] += 1
        acc = sum(move_accuracy(m.loss) for m in self.moves) / n if n else None
        worst = sorted(self.moves, key=lambda m: -m.loss)[:3]
        worst = [m for m in worst if m.label in ("inaccuracy", "mistake", "blunder")]
        sans = None
        if board is not None and board.move_stack:
            root = board.root() if hasattr(board, "root") else chess.Board()
            if root.fen() == chess.STARTING_FEN:
                replay, sans = chess.Board(), []
                for mv in board.move_stack:
                    sans.append(replay.san(mv))
                    replay.push(mv)
        result = board.result(claim_draw=True) if board is not None else None
        outcome = outcome_from_result(result, self.user_is_white) or self.outcome
        return dict(moves=n, accuracy=None if acc is None else round(acc, 1), counts=counts,
                    worst=[asdict(m) for m in worst], opening=opening_name(sans) if sans else None,
                    result=result if result != "*" else None, outcome=outcome,
                    opponent=self.opponent, user_color="white" if self.user_is_white else "black")

    def save(self, board=None):
        """Grava games/<data>.json (e .pgn se a partida inteira for conhecida). Retorna o caminho."""
        if self.finished or not self.moves:
            return self.saved_path
        self.finished = True
        GAMES_DIR.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        data = dict(date=stamp, summary=self.summary(board), moves=[asdict(m) for m in self.moves])
        path = GAMES_DIR / f"{stamp}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        if board is not None and board.move_stack and board.root().fen() == chess.STARTING_FEN:
            game = chess.pgn.Game.from_board(board)
            game.headers["Event"] = "ChessMind"
            game.headers["Date"] = time.strftime("%Y.%m.%d")
            game.headers["White" if self.user_is_white else "Black"] = "ChessMind"
            game.headers["Result"] = board.result(claim_draw=True)
            by_ply = {m.fen_before: m for m in self.moves}
            node, b = game, chess.Board()
            while node.variations:
                node = node.variations[0]
                mr = by_ply.get(b.fen())
                if mr and mr.san == b.san(node.move):
                    node.comment = f"[%eval {mr.ev_played:+.2f}] {LABELS_PT[mr.label]}"
                    if mr.label in NAG:
                        node.nags.add(NAG[mr.label])
                b.push(node.move)
            (GAMES_DIR / f"{stamp}.pgn").write_text(str(game), encoding="utf-8")
        self.saved_path = path
        return path
