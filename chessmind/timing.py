"""Gerenciamento de tempo: quanto o motor calcula e quanto esperamos antes de jogar.

O atraso base (configuravel) e o tempo de um lance "normal". Em cima dele aplicamos:
  - dificuldade da posicao: lance unico/obvio sai rapido, decisao apertada demora mais;
  - recaptura e abertura saem mais rapido;
  - relogio: com pouco tempo sobrando, joga rapido;
  - variacao aleatoria (lognormal), para nao ter ritmo constante.
"""
import math
import random

import chess


def ev_to_pawns(text):
    """'+0.30' -> 0.3 ; '#3' -> +10 ; '#-2' -> -10 ; 'TB+' (tablebase: vitoria) -> +10 ; 'TB=' -> 0"""
    if text in ("TB+", "TB="):
        return 10.0 if text == "TB+" else 0.0
    if text == "TB-":
        return -10.0
    try:
        if text.startswith("#"):
            return 10.0 if int(text[1:]) > 0 else -10.0
        return float(text)
    except ValueError:
        return 0.0


def think_budget(base, clock_s, board):
    """Tempo (s) que o motor pode gastar neste lance."""
    legal = board.legal_moves.count()
    if legal <= 1:
        return 0.1
    t = base
    if clock_s is not None:
        t = min(t, max(0.1, clock_s / 40.0))     # nunca mais de 1/40 do relogio restante
    return max(0.1, t)


def complexity_factor(board, sugg, gap):
    """Multiplicador do atraso base (0.3 .. 1.8) conforme a posicao."""
    legal = board.legal_moves.count()
    if legal <= 1:
        return 0.15
    f = 1.0
    if board.fullmove_number <= 6:
        f *= 0.55                                   # abertura: lances de teoria
    if gap is not None:
        if gap >= 1.5:
            f *= 0.5                                # melhor lance claramente superior
        elif gap < 0.25:
            f *= 1.5                                # decisao apertada: "pensa mais"
    if sugg and board.move_stack:
        last, best = board.peek(), sugg[0][0]
        if board.is_capture(last) and best.to_square == last.to_square:
            f *= 0.6                                # recaptura
    return min(1.8, max(0.15, f))


def human_delay(base, board, sugg, gap, clock_s, rng=random):
    """Pausa (s) antes de fazer o lance."""
    d = base * complexity_factor(board, sugg, gap) * math.exp(rng.gauss(0, 0.35))
    if clock_s is not None:
        d = min(d, clock_s * 0.05)
        if clock_s < 15:
            d = min(d, 0.4)
    return max(0.15, min(d, base * 3))
