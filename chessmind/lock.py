"""Instancia unica: so um coach pode controlar a tela/o Chrome por vez.

Duas instancias (ex.: coach.bat antigo + interface) disputavam as setas e faziam a tela
piscar. O lock e um trava de arquivo do Windows: some sozinho se o processo morrer.
"""
import msvcrt
import os

from .config import ROOT

_LOCK_PATH = ROOT / ".coach.lock"
_handle = None


def acquire():
    """True se esta e a unica instancia; False se outra ja esta rodando."""
    global _handle
    f = open(_LOCK_PATH, "a+")
    try:
        f.seek(0)       # sempre o mesmo byte (a+ abre no fim do arquivo)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        f.close()
        return False
    f.seek(0)
    f.truncate()
    f.write(str(os.getpid()))
    f.flush()
    _handle = f          # mantem aberto (e travado) ate o processo terminar
    return True


def owner_pid():
    try:
        return int(_LOCK_PATH.read_text().strip())
    except Exception:
        return None
