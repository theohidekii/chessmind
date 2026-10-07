"""Explicacoes em linguagem natural via API do Claude (opcional), com cache em disco.

Precisa do pacote `anthropic` e da variavel de ambiente ANTHROPIC_API_KEY. A chave nunca e
pedida nem gravada pelo programa: defina-a no Windows (setx ANTHROPIC_API_KEY ...) e reabra.

Cache: cada explicacao fica em cache/explain.json (chave = hash do modelo + prompt). Pedir de
novo a mesma explicacao nao chama a API (e funciona ate sem chave).
"""
import hashlib
import json
import os
import threading
import time

from . import config

MODEL = os.environ.get("CHESSMIND_EXPLAIN_MODEL", "claude-haiku-4-5-20251001")
CACHE_PATH = config.ROOT / "cache" / "explain.json"
CACHE_MAX = 500
_lock = threading.Lock()

SYSTEM = (
    "Voce e um treinador de xadrez paciente. Responda em portugues do Brasil, em 3 a 5 frases "
    "curtas, para um jogador intermediario. Explique a IDEIA do lance (tatica, estrutura, "
    "atividade das pecas, seguranca do rei) com base APENAS na avaliacao e na linha do motor "
    "fornecidas. Nao invente variantes que nao estejam na linha. Nao use markdown."
)


class ExplainUnavailable(Exception):
    pass


def available():
    """(ok, motivo) - se da para pedir explicacoes agora."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False, "Defina a variavel de ambiente ANTHROPIC_API_KEY e reabra o programa."
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False, "Instale o pacote: .venv\\Scripts\\python -m pip install anthropic"
    return True, ""


def build_prompt(fen, side, best_san, line_san, eval_text, played_san=None, label=None, loss=None):
    lines = [f"Posicao (FEN): {fen}", f"Vez das {side}.",
             f"Melhor lance do motor: {best_san} (avaliacao {eval_text} do ponto de vista de quem joga).",
             f"Linha principal do motor: {line_san}"]
    if played_san:
        lines.append(f"O jogador jogou {played_san}, classificado como {label}"
                     + (f" (perdeu cerca de {loss:.0f} pontos de chance de vitoria)." if loss else "."))
        lines.append("Explique por que o lance do jogador foi pior e o que o melhor lance faz.")
    else:
        lines.append("Explique por que esse e um bom lance.")
    return "\n".join(lines)


# ---------------- cache ----------------
def _key(prompt):
    return hashlib.sha256(f"{MODEL}\n{prompt}".encode("utf-8")).hexdigest()


def _load():
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def is_cached(prompt):
    return _key(prompt) in _load()


def cached(prompt):
    entry = _load().get(_key(prompt))
    return entry["text"] if entry else None


def _store(prompt, text):
    with _lock:
        data = _load()
        data[_key(prompt)] = {"text": text, "ts": time.time()}
        if len(data) > CACHE_MAX:                       # descarta as mais antigas
            for k in sorted(data, key=lambda k: data[k]["ts"])[:len(data) - CACHE_MAX]:
                del data[k]
        CACHE_PATH.parent.mkdir(exist_ok=True)
        tmp = CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(CACHE_PATH)                         # gravacao atomica


def explain(prompt, timeout=30):
    """Texto da explicacao; do cache se ja foi pedida antes."""
    hit = cached(prompt)
    if hit is not None:
        return hit
    ok, why = available()
    if not ok:
        raise ExplainUnavailable(why)
    import anthropic
    client = anthropic.Anthropic(timeout=timeout)
    msg = client.messages.create(model=MODEL, max_tokens=400, system=SYSTEM,
                                 messages=[{"role": "user", "content": prompt}])
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    if text:
        _store(prompt, text)
    return text
