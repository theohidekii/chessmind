"""Estatisticas das suas partidas salvas (games/*.json)."""
import json
import time
from collections import defaultdict

from .review import GAMES_DIR


def load_games(games_dir=None):
    """Partidas salvas, da mais antiga para a mais nova."""
    games_dir = games_dir or GAMES_DIR
    out = []
    for path in sorted(games_dir.glob("*.json")) if games_dir.exists() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["summary"]["moves"]
        except (OSError, ValueError, KeyError):
            continue
        out.append(data)
    return out


def _bucket():
    return dict(games=0, win=0, draw=0, loss=0, unknown=0, acc=[])


def _add(b, summary):
    b["games"] += 1
    b[summary.get("outcome") or "unknown"] += 1
    if summary.get("accuracy") is not None:
        b["acc"].append(summary["accuracy"])


def _finish(b):
    acc = b.pop("acc")
    b["accuracy"] = round(sum(acc) / len(acc), 1) if acc else None
    return b


def compute(games):
    """Resumo geral, tendencia de precisao, resultado por adversario e por abertura."""
    total, by_opp, by_open = _bucket(), defaultdict(_bucket), defaultdict(_bucket)
    trend, errors = [], dict(inaccuracy=0, mistake=0, blunder=0)
    ratings = {}
    for g in games:
        s = g["summary"]
        _add(total, s)
        opp = s.get("opponent") or {}
        name = opp.get("name") or "Desconhecido"
        _add(by_opp[name], s)
        if opp.get("rating"):
            ratings[name] = opp["rating"]
        _add(by_open[s.get("opening") or "Abertura nao identificada"], s)
        if s.get("accuracy") is not None:
            trend.append((g.get("date", ""), s["accuracy"]))
        for k in errors:
            errors[k] += s.get("counts", {}).get(k, 0)
    opponents = []
    for name, b in by_opp.items():
        row = _finish(b)
        row["name"], row["rating"] = name, ratings.get(name)
        opponents.append(row)
    openings = []
    for name, b in by_open.items():
        row = _finish(b)
        row["name"] = name
        openings.append(row)
    return dict(total=_finish(total), trend=trend, errors=errors,
                opponents=sorted(opponents, key=lambda r: -r["games"]),
                openings=sorted(openings, key=lambda r: -r["games"]))


def pretty_date(stamp):
    """'20261007-182230' -> '07/10 18:22'"""
    try:
        return time.strftime("%d/%m %H:%M", time.strptime(stamp, "%Y%m%d-%H%M%S"))
    except ValueError:
        return stamp
