"""Captura do tabuleiro via Playwright (conectado ao Chrome por CDP).

Vantagens sobre capturar o monitor: funciona com o Chrome coberto, movido ou em outro
monitor; o recorte e sempre o elemento do tabuleiro; a orientacao (brancas/pretas
embaixo) e lida do DOM.
"""
import base64
import os
import random
import re
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np

PORT = int(os.environ.get("CHESSMIND_PORT", 9222))
CDP_URL = f"http://127.0.0.1:{PORT}"
PROFILE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ChessMind" / "chrome-profile"
START_URL = "https://www.chess.com/play/computer"
CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    str(Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe"),
]

# (seletor do tabuleiro, js que devolve true se as pretas estao embaixo)
SITES = [
    ("wc-chess-board, chess-board", "e => e.classList.contains('flipped')"),
    ("cg-board", "e => !!e.closest('.orientation-black')"),
]


def launch_chrome(url=START_URL):
    """Abre o Chrome com a porta de depuracao e um perfil separado (obrigatorio no Chrome 136+)."""
    exe = next((p for p in CHROME_PATHS if Path(p).exists()), None)
    if exe is None:
        raise FileNotFoundError("chrome.exe nao encontrado.")
    PROFILE.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([exe, f"--remote-debugging-port={PORT}", f"--user-data-dir={PROFILE}",
                      "--no-first-run", "--no-default-browser-check",
                      "--disable-backgrounding-occluded-windows",
                      "--disable-renderer-backgrounding",
                      "--disable-background-timer-throttling",
                      "--disable-features=CalculateNativeWinOcclusion", url])


JS_DRAW = """({svg, x, y, w, h}) => {
  let el = document.getElementById('__cm_arrows');
  if (!el) {
    el = document.createElement('div'); el.id = '__cm_arrows';
    el.style.cssText = 'position:absolute;pointer-events:none;z-index:2147483647';
    document.body.appendChild(el);
  }
  el.style.left = x + 'px'; el.style.top = y + 'px';
  el.style.width = w + 'px'; el.style.height = h + 'px';
  el.innerHTML = svg;
  window.__cmExp = Date.now() + 8000;
  if (!window.__cmTimer) window.__cmTimer = setInterval(() => {
    const e = document.getElementById('__cm_arrows');
    if (e && Date.now() > window.__cmExp) e.remove();   // coach parou: as setas somem sozinhas
  }, 1000);
}"""
JS_HIDE = "() => { const e = document.getElementById('__cm_arrows'); if (e) e.remove(); }"
ARROW_COLORS = ["#3ecf8e", "#f5b94a", "#f58a4a"]


def arrows_svg(moves_uci, white_bottom):
    """SVG (viewBox 8x8, uma unidade por casa) com as setas das jogadas."""
    import math
    parts = []
    for i, uci in enumerate(moves_uci[:3]):
        pts = []
        for sq in (uci[0:2], uci[2:4]):
            f, r = "abcdefgh".index(sq[0]), int(sq[1]) - 1
            pts.append(((f if white_bottom else 7 - f) + .5, (7 - r if white_bottom else r) + .5))
        (x1, y1), (x2, y2) = pts
        dx, dy = x2 - x1, y2 - y1
        d = math.hypot(dx, dy) or 1
        ux, uy = dx / d, dy / d
        width, head = .20 - .045 * i, .55 - .08 * i
        bx, by = x2 - ux * head, y2 - uy * head          # base da ponta
        px, py = -uy * head * .55, ux * head * .55
        col = ARROW_COLORS[i]
        parts.append(
            f'<line x1="{x1 + ux * .15:.3f}" y1="{y1 + uy * .15:.3f}" x2="{bx:.3f}" y2="{by:.3f}" '
            f'stroke="{col}" stroke-width="{width:.3f}" stroke-linecap="round" opacity=".9"/>'
            f'<polygon points="{x2:.3f},{y2:.3f} {bx + px:.3f},{by + py:.3f} {bx - px:.3f},{by - py:.3f}" '
            f'fill="{col}" opacity=".9"/>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8" width="100%" height="100%">'
            + "".join(parts) + "</svg>")


JS_DOM = """() => {
  if (document.getElementById('__cm_arrows')) window.__cmExp = Date.now() + 8000;
  const out = {};
  const cc = document.querySelector('wc-chess-board, chess-board');
  if (cc) {                                   // chess.com: <div class="piece wp square-52">
    cc.querySelectorAll('.piece').forEach(p => {
      let t = null, m = null;
      p.classList.forEach(c => {
        if (/^[wb][pnbrqk]$/.test(c)) t = c;
        const q = c.match(/^square-([1-8])([1-8])$/); if (q) m = q;
      });
      if (t && m) out[String.fromCharCode(96 + +m[1]) + m[2]] = t[0] === 'w' ? t[1].toUpperCase() : t[1];
    });
    return out;
  }
  const lb = document.querySelector('cg-board');
  if (lb) {                                   // lichess: <piece class="white pawn" style="transform: translate(Xpx, Ypx)">
    const sq = lb.clientWidth / 8, flip = !!lb.closest('.orientation-black');
    const role = {pawn: 'p', knight: 'n', bishop: 'b', rook: 'r', queen: 'q', king: 'k'};
    lb.querySelectorAll('piece').forEach(p => {
      const m = (p.style.transform || '').match(/translate\\(([\\d.]+)px,\\s*([\\d.]+)px\\)/);
      const cl = [...p.classList];
      const r = cl.map(c => role[c]).find(x => x);
      const col = cl.includes('white') ? 'w' : cl.includes('black') ? 'b' : null;
      if (!m || !r || !col || cl.includes('ghost')) return;
      let f = Math.round(m[1] / sq), top = Math.round(m[2] / sq);
      if (flip) { f = 7 - f; top = 7 - top; }
      out[String.fromCharCode(97 + f) + (8 - top)] = col === 'w' ? r.toUpperCase() : r;
    });
    return out;
  }
  return null;
}"""


JS_STATE = """() => {
  const st = {moves: null, clocks: {w: null, b: null}, turn: null, highlights: [], over: false};
  const secs = t => {
    const m = (t || '').trim().match(/^(?:(\\d+):)?(\\d+):(\\d+)(?:\\.(\\d+))?$/);
    if (!m) return null;
    return (m[1] ? +m[1] * 3600 : 0) + +m[2] * 60 + +m[3] + (m[4] ? +('0.' + m[4]) : 0);
  };
  // relogios: a classe clock-player-turn marca quem joga
  document.querySelectorAll('.clock-component').forEach(c => {
    const col = c.classList.contains('clock-white') ? 'w' : c.classList.contains('clock-black') ? 'b' : null;
    if (!col) return;
    st.clocks[col] = secs((c.textContent.trim().split(/\\s+/)[0]) || '');
    if (c.classList.contains('clock-player-turn')) st.turn = col;
  });
  // ultimo lance destacado
  document.querySelectorAll('wc-chess-board .highlight, chess-board .highlight').forEach(h => {
    h.classList.forEach(c => { const q = c.match(/^square-([1-8])([1-8])$/);
      if (q) st.highlights.push(String.fromCharCode(96 + +q[1]) + q[2]); });
  });
  // lista de lances (SAN): precisa ser contigua 1..N, senao descartamos
  const byPly = {};
  document.querySelectorAll('[data-ply]').forEach(n => {
    const ply = +n.getAttribute('data-ply');
    if (!ply || byPly[ply]) return;
    const span = n.querySelector('.move-text-component') || n;
    const tok = (span.textContent || '').trim().match(
      /(O-O-O|O-O|[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?)/);
    let text = tok ? tok[1] : '';
    const f = n.querySelector('[data-figurine]');
    let letter = f ? f.getAttribute('data-figurine') : null;
    if (!letter) {
      const ic = n.querySelector('.icon-font-chess');
      const m = ic && [...ic.classList].join(' ').match(/(knight|bishop|rook|queen|king)/);
      if (m) letter = {knight: 'N', bishop: 'B', rook: 'R', queen: 'Q', king: 'K'}[m[1]];
    }
    if (letter && /^[a-hx]/.test(text)) text = letter + text;
    byPly[ply] = text;
  });
  const plies = Object.keys(byPly).map(Number).sort((a, b) => a - b);
  if (plies.length && plies[0] === 1 && plies.every((p, i) => p === i + 1) && plies.every(p => byPly[p]))
    st.moves = plies.map(p => byPly[p]);
  const modal = document.querySelector('.game-over-modal-container, [class*="game-over-modal"]');
  st.over = !!modal;
  st.result_text = modal ? (modal.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 120) : null;
  // adversario = jogador de cima (voce fica embaixo): "Nora (2200) 5:41"
  const top = document.querySelector('.player-top, [class*="player-top"]');
  st.opponent = top ? (top.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 60) : null;
  return st;
}"""

JS_NEW_GAME_RE = "(nova partida|new game|rematch|revanche|jogar novamente|play again|new bot)"


def square_center_xy(rect, name, white_bottom):
    """Centro (x, y) e lado da casa `name` ('e4') num tabuleiro com `rect` {x, y, w, h}."""
    sq = rect["w"] / 8
    f, rank = "abcdefgh".index(name[0]), int(name[1]) - 1
    col = f if white_bottom else 7 - f
    row = 7 - rank if white_bottom else rank
    return rect["x"] + (col + .5) * sq, rect["y"] + (row + .5) * sq, sq


class PWBoard:
    def __init__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.connect_over_cdp(CDP_URL)
        self.page = None
        self.selector = None
        self.flip_js = None
        self._cdp = self._cdp_page = None
        self._arrows = None
        self._drawn = None

    def close(self):
        try:
            self._pw.stop()
        except Exception:
            pass

    def _find(self):
        """Procura, em todas as abas, um tabuleiro conhecido."""
        for ctx in self.browser.contexts:
            for page in ctx.pages:
                for sel, js in SITES:
                    try:
                        if page.locator(sel).count() > 0:
                            self.page, self.selector, self.flip_js = page, sel, js
                            return True
                    except Exception:
                        continue
        return False

    def _board(self):
        if self.page is None or self.page.is_closed():
            self.page = None
            if not self._find():
                return None
        loc = self.page.locator(self.selector).first
        try:
            if loc.count() == 0:
                self.page = None
                return None
        except Exception:
            self.page = None
            return None
        return loc

    def white_bottom(self):
        loc = self._board()
        if loc is None:
            return None
        return not loc.evaluate(self.flip_js)

    def signature(self):
        """Hash do HTML do tabuleiro: muda quando uma peca se move. E barato e nao repinta nada,
        entao so tiramos screenshot quando ele muda (screenshots repetidos faziam a tela piscar)."""
        loc = self._board()
        if loc is None:
            return None
        return loc.evaluate(
            "e => { if (document.getElementById('__cm_arrows')) window.__cmExp = Date.now() + 8000;"
            "const s = e.innerHTML; let h = 0;"
            "for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;"
            "return s.length + ':' + h; }")

    def frame(self):
        """Imagem BGR do tabuleiro, ou None se nao houver tabuleiro na pagina.

        Captura CDP direta (Page.captureScreenshot com clip): sem rolar a pagina, sem
        injetar CSS e sem emular viewport."""
        loc = self._board()
        if loc is None:
            return None
        r = loc.evaluate("e => { const b = e.getBoundingClientRect();"
                         "return {x: b.x + scrollX, y: b.y + scrollY, width: b.width, height: b.height}; }")
        if r["width"] < 50 or r["height"] < 50:
            return None
        if self._cdp is None or self._cdp_page is not self.page:
            self._cdp = self.page.context.new_cdp_session(self.page)
            self._cdp_page = self.page
        res = self._cdp.send("Page.captureScreenshot", {
            "format": "png", "fromSurface": True, "captureBeyondViewport": False,
            "clip": {**r, "scale": 1}})
        return cv2.imdecode(np.frombuffer(base64.b64decode(res["data"]), np.uint8), cv2.IMREAD_COLOR)

    def dom_placement(self):
        """{casa: simbolo} lido das pecas do DOM (exato, sem screenshot), ou None se o site
        nao for reconhecido / ainda nao houver pecas. Tambem renova o prazo das setas."""
        if self.page is None or self.page.is_closed():
            self.page = None
            if not self._find():
                return None
        out = self.page.evaluate(JS_DOM)
        if not out or len(out) < 2:
            return None
        return out

    # ---------- jogar sozinho ----------
    BOT_URL = re.compile(r"chess\.com/(play/computer|game/computer|computer)", re.I)

    def is_bot_page(self):
        """Modo autonomo so e permitido em paginas de partida contra bot do chess.com."""
        if self.page is None:
            return False
        url = self.page.url
        if self.BOT_URL.search(url):
            return True
        # Alguns bots usam /game/<id>, o mesmo formato das partidas contra humanos:
        # so vale se o titulo da lateral da pagina mencionar bots ("Play Bots"/"Jogar Com Bots").
        if re.search(r"chess\.com/game/\d+", url, re.I):
            head = self.page.evaluate("() => (document.querySelector('#board-layout-sidebar')"
                                      " || document.body).innerText.slice(0, 60)")
            return bool(re.search(r"\bbots?\b", head, re.I))
        return False

    def square_center(self, name, white_bottom):
        """Centro da casa em coordenadas do viewport (as do mouse)."""
        loc = self._board()
        r = loc.evaluate("e => { const b = e.getBoundingClientRect();"
                         "return {x: b.x, y: b.y, w: b.width, h: b.height}; }")
        return square_center_xy(r, name, white_bottom)

    def play_move(self, uci, white_bottom, white_to_move):
        """Faz o lance clicando na casa de origem e depois na de destino (com pequena variacao
        humana). Promocao: escolhe a peca na janela de promocao (padrao: dama)."""
        loc = self._board()
        if loc is None:
            raise RuntimeError("tabuleiro nao encontrado")
        loc.scroll_into_view_if_needed(timeout=2000)
        m = self.page.mouse
        for i, name in enumerate((uci[0:2], uci[2:4])):
            x, y, sq = self.square_center(name, white_bottom)
            x += random.uniform(-.16, .16) * sq
            y += random.uniform(-.16, .16) * sq
            m.move(x + random.uniform(-25, 25), y + random.uniform(-25, 25))
            m.move(x, y, steps=random.randint(4, 9))
            time.sleep(random.uniform(.05, .15))
            m.click(x, y)
            if i == 0:
                time.sleep(random.uniform(.15, .35))
        if len(uci) == 5:
            piece = uci[4]
            color = "w" if white_to_move else "b"
            self.page.locator(f".promotion-piece.{color}{piece}").first.click(timeout=3000)

    def read_state(self):
        """Estado da partida lido da pagina: lista de lances, relogios, vez, destaque do ultimo
        lance e fim de jogo. Qualquer campo pode vir vazio (site desconhecido): quem usa deve
        validar. None se a leitura falhar."""
        if self.page is None or self.page.is_closed():
            return None
        try:
            return self.page.evaluate(JS_STATE)
        except Exception:
            return None

    def click_new_game(self):
        """Clica no botao de nova partida/revanche DENTRO da janela de fim de jogo.
        Retorna o texto do botao clicado ou None."""
        sel = ".game-over-modal-container button, [class*='game-over-modal'] button, " \
              ".game-over-modal-container a, [class*='game-over-modal'] a"
        btn = self.page.locator(sel).filter(has_text=re.compile(JS_NEW_GAME_RE, re.I)).first
        if btn.count() == 0:
            return None
        text = btn.inner_text().strip()
        btn.click(timeout=3000)
        return text

    def show_arrows(self, moves_uci, white_bottom):
        self._arrows = (list(moves_uci), white_bottom)
        self._draw_arrows()

    def _draw_arrows(self):
        if not self._arrows:
            return
        loc = self._board()
        if loc is None:
            return
        r = loc.evaluate("e => { const b = e.getBoundingClientRect();"
                         "return {x: b.x + scrollX, y: b.y + scrollY, w: b.width, h: b.height}; }")
        payload = {"svg": arrows_svg(*self._arrows), **r}
        if payload == self._drawn:      # nada mudou: nao toca na pagina
            return
        self._drawn = payload
        self.page.evaluate(JS_DRAW, payload)

    def refresh_arrows(self):
        """Reposiciona as setas se o tabuleiro mudou de lugar/tamanho (scroll, resize)."""
        self._draw_arrows()

    def hide_arrows(self):
        self._arrows = None
        self._drawn = None
        if self.page is not None and not self.page.is_closed():
            self.page.evaluate(JS_HIDE)
