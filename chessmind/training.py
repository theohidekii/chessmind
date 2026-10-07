"""Treino a partir dos seus erros: exercicios tirados das partidas salvas + repeticao espacada."""
import hashlib
import json
import time
from dataclasses import dataclass

import chess

from . import config
from .review import GAMES_DIR, LABELS_PT

PROGRESS_PATH = config.ROOT / "training" / "progress.json"
# Caixas de Leitner: intervalo ate rever o exercicio apos acertar N vezes seguidas (segundos)
BOX_SECONDS = [600, 86400, 3 * 86400, 7 * 86400, 21 * 86400]
TRAIN_LABELS = ("inaccuracy", "mistake", "blunder")
GOOD_ALTERNATIVE = 0.3       # peoes: lance alternativo aceito se perder menos que isso


@dataclass
class Exercise:
    id: str
    fen: str
    white_to_move: bool
    best_san: str
    played_san: str
    label: str
    loss: float
    ev_best: float
    line: str
    game: str
    number: str

    @property
    def title(self):
        return f"{self.number} {self.played_san} — {LABELS_PT[self.label]}"


def _exercise_id(fen, best_san):
    return hashlib.sha1(f"{fen}|{best_san}".encode()).hexdigest()[:12]


def load_exercises(games_dir=None, labels=TRAIN_LABELS):
    """Todos os seus erros salvos em games/*.json, sem repetidos, dos mais graves aos menos."""
    games_dir = games_dir or GAMES_DIR
    out, seen = [], set()
    for path in sorted(games_dir.glob("*.json")) if games_dir.exists() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for m in data.get("moves", []):
            if m.get("label") not in labels or m.get("san") == m.get("best_san"):
                continue
            ex_id = _exercise_id(m["fen_before"], m["best_san"])
            if ex_id in seen:
                continue
            seen.add(ex_id)
            out.append(Exercise(
                id=ex_id, fen=m["fen_before"], white_to_move=" w " in m["fen_before"],
                best_san=m["best_san"], played_san=m["san"], label=m["label"], loss=m["loss"],
                ev_best=m["ev_best"], line=(m.get("line") or [m["best_san"]])[0],
                game=data.get("date", path.stem), number=m["number"]))
    return sorted(out, key=lambda e: -e.loss)


class Progress:
    """Acertos/erros por exercicio, em training/progress.json."""

    def __init__(self, path=None):
        self.path = path or PROGRESS_PATH
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def save(self):
        self.path.parent.mkdir(exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=1), encoding="utf-8")

    def record(self, ex_id, correct, now=None):
        now = now if now is not None else time.time()
        e = self.data.setdefault(ex_id, {"box": 0, "due": 0, "attempts": 0, "correct": 0})
        e["attempts"] += 1
        e["correct"] += int(correct)
        e["box"] = min(e["box"] + 1, len(BOX_SECONDS) - 1) if correct else 0
        e["due"] = now + BOX_SECONDS[e["box"]]
        self.save()

    def due_exercises(self, exercises, now=None):
        """Os que nunca foram feitos ou ja venceram: erradas recentes primeiro, depois novos."""
        now = now if now is not None else time.time()
        due = []
        for ex in exercises:
            e = self.data.get(ex.id)
            if e is None:
                due.append((1, 0, ex))                       # novo
            elif e["due"] <= now:
                due.append((0, e["box"], ex))                # vencido: caixas baixas antes
        return [ex for _, _, ex in sorted(due, key=lambda t: (t[0], t[1]))]

    def summary(self, exercises):
        done = [self.data[e.id] for e in exercises if e.id in self.data]
        att = sum(d["attempts"] for d in done)
        cor = sum(d["correct"] for d in done)
        mastered = sum(1 for d in done if d["box"] >= 3)
        return dict(total=len(exercises), practiced=len(done), attempts=att, correct=cor,
                    mastered=mastered)


def check_answer(ex, move, engine=None):
    """('correct'|'good'|'wrong', eval_do_lance_ou_None). `engine` (Coach) avalia lances alternativos."""
    board = chess.Board(ex.fen)
    best = board.parse_san(ex.best_san)
    if move == best:
        return "correct", ex.ev_best
    if engine is None:
        return "wrong", None
    ev = engine.eval_after(board, move)
    return ("good" if ex.ev_best - ev <= GOOD_ALTERNATIVE else "wrong"), ev
