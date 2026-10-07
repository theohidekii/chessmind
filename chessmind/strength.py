"""Ajuste automatico de forca: comeca abaixo do maximo e so sobe quando voce perde.

Estado por adversario (nome do bot) em training/strength.json:
  - nivel inicial: rating do bot + START_MARGIN (ou DEFAULT_START se o rating for desconhecido),
    sempre bem abaixo do maximo do motor;
  - perdeu a partida: sobe STEP_LOSS; empatou: sobe STEP_DRAW; venceu: mantem;
  - durante a partida, se a posicao fica ruim por alguns lances seguidos, sobe STEP_MID na hora.
O nivel nunca desce sozinho (use "Redefinir forca" no menu para recomecar). Ao chegar ao maximo
do motor, deixa de limitar a forca.
"""
import json

from . import config

MIN_ELO, MAX_ELO = 1320, 3190          # faixa do UCI_Elo do Stockfish
DEFAULT_START = 2000
START_MARGIN = 200                     # as escalas de rating diferem: comeca um pouco acima do rating do bot
STEP_LOSS, STEP_DRAW, STEP_MID = 250, 100, 200
MID_LOSING_EVAL = -2.0                 # peoes (do seu ponto de vista)
MID_LOSING_TURNS = 2                   # lances seguidos nessa situacao
MID_MAX_BUMPS = 2                      # subidas por partida
PATH = config.ROOT / "training" / "strength.json"


def key(opponent):
    name = (opponent or {}).get("name") if isinstance(opponent, dict) else opponent
    return (name or "default").strip().lower()


class StrengthManager:
    def __init__(self, path=None, lo=MIN_ELO, hi=MAX_ELO):
        self.path, self.lo, self.hi = path or PATH, lo, hi
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        self._losing = 0
        self._bumps = 0

    # ---------- estado ----------
    def _save(self):
        self.path.parent.mkdir(exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=1), encoding="utf-8")

    def _entry(self, opponent):
        k = key(opponent)
        e = self.data.get(k)
        if e is None:
            rating = opponent.get("rating") if isinstance(opponent, dict) else None
            start = rating + START_MARGIN if rating else DEFAULT_START
            start = max(self.lo, min(round(start / 10) * 10, self.hi - 100))   # nunca comeca no maximo
            e = self.data[k] = dict(elo=start, start=start, games=0, wins=0, draws=0, losses=0)
            self._save()
        return e

    def current(self, opponent):
        """Elo a usar contra este adversario, ou None (= forca total, sem limite)."""
        elo = self._entry(opponent)["elo"]
        return None if elo >= self.hi else elo

    def _raise(self, opponent, step):
        e = self._entry(opponent)
        e["elo"] = min(self.hi, e["elo"] + step)
        self._save()
        return self.current(opponent)

    # ---------- eventos ----------
    def new_game(self):
        self._losing = self._bumps = 0

    def observe_eval(self, opponent, ev_pawns):
        """Chame na sua vez com a avaliacao (forca total) da posicao. Se a partida esta ruim por
        MID_LOSING_TURNS lances seguidos, sobe a forca na hora. Retorna o novo elo (ou None=maximo)
        quando subiu, senao False."""
        self._entry(opponent)
        self._losing = self._losing + 1 if ev_pawns <= MID_LOSING_EVAL else 0
        if self._losing >= MID_LOSING_TURNS and self._bumps < MID_MAX_BUMPS \
                and self._entry(opponent)["elo"] < self.hi:
            self._losing, self._bumps = 0, self._bumps + 1
            return self._raise(opponent, STEP_MID)
        return False

    def record_game(self, opponent, outcome):
        """Registra o resultado ('win'|'loss'|'draw'); perdeu/empatou sobe. Retorna o elo atual."""
        e = self._entry(opponent)
        if outcome in ("win", "loss", "draw"):
            e["games"] += 1
            e[{"win": "wins", "loss": "losses", "draw": "draws"}[outcome]] += 1
            self._save()
        self.new_game()
        if outcome == "loss":
            return self._raise(opponent, STEP_LOSS)
        if outcome == "draw":
            return self._raise(opponent, STEP_DRAW)
        return self.current(opponent)

    def reset(self):
        self.data = {}
        self._losing = self._bumps = 0
        self._save()
