"""Downloads of the third-party files ChessMind needs or can use.

Used by `scripts/get_data.py` (command line), by `setup.bat` and by the GUI ("Verificar instalacao").

- Stockfish: the official Windows build from the Stockfish GitHub releases (GPL-3.0).
- Opening data: the ECO table from lichess-org/chess-openings (CC0) and the book built from it.
- Syzygy tablebases from tablebase.lichess.ovh.

Every function takes an optional `progress(message, fraction_or_None)` callback and an optional
`opener` (defaults to `urllib.request.urlopen`) so it can be tested without the network.
"""
import ctypes
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from . import book, config

ENGINE_DIR = config.ROOT / "engine"
STOCKFISH_DIR = ENGINE_DIR / "stockfish"
SYZYGY_DIR = ENGINE_DIR / "syzygy"
STOCKFISH_API = "https://api.github.com/repos/official-stockfish/Stockfish/releases/latest"
ECO_URL = "https://raw.githubusercontent.com/lichess-org/chess-openings/master/{}.tsv"
TB_BASE = "https://tablebase.lichess.ovh/tables/standard/"
HEADERS = {"User-Agent": "ChessMind-installer"}


def _open(url, opener=None):
    return (opener or urllib.request.urlopen)(urllib.request.Request(url, headers=HEADERS), timeout=60)


def _say(progress, message, fraction=None):
    if progress:
        progress(message, fraction)


def download(url, dest, progress=None, opener=None, expected=None, label=None):
    """Downloads `url` to `dest` (atomically, through a .part file). Returns False if `dest` already
    has the expected size and was skipped."""
    dest = Path(dest)
    if expected is not None and dest.exists() and dest.stat().st_size == expected:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    label = label or dest.name
    with _open(url, opener) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0) or expected or 0
        done = 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            _say(progress, f"Baixando {label}", (done / total) if total else None)
    if expected is not None and tmp.stat().st_size != expected:
        tmp.unlink()
        raise IOError(f"Tamanho inesperado ao baixar {url}")
    tmp.replace(dest)
    return True


# ---------------- Stockfish ----------------
def has_avx2():
    try:
        return bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(40))   # PF_AVX2_INSTRUCTIONS_AVAILABLE
    except Exception:
        return False


def pick_stockfish_asset(assets, avx2=True):
    """Best Windows x86-64 zip among the release assets: the 'universal' build (one binary that picks
    the best instruction set at run time) first, then AVX2, then the plain build."""
    best, best_score = None, 0
    for a in assets:
        name = a["name"].lower()
        if not (name.endswith(".zip") and "windows" in name and "arm" not in name):
            continue
        score = 3 if "universal" in name else 2 if ("avx2" in name and avx2) else 1 if name.endswith("x86-64.zip") else 0
        if score > best_score:
            best, best_score = a, score
    return best


def check_engine(exe):
    """True if `exe` answers the UCI handshake."""
    try:
        out = subprocess.run([str(exe)], input="uci\nquit\n", capture_output=True, text=True, timeout=20)
        return "uciok" in out.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


def download_stockfish(progress=None, opener=None, dest_dir=None, validate=True):
    """Installs the latest official Stockfish release into engine/stockfish/. Returns the exe path."""
    dest_dir = Path(dest_dir or STOCKFISH_DIR)
    _say(progress, "Procurando a versao mais recente do Stockfish...")
    with _open(STOCKFISH_API, opener) as r:
        release = json.loads(r.read().decode("utf-8"))
    asset = pick_stockfish_asset(release.get("assets", []), has_avx2())
    if asset is None:
        raise RuntimeError("Nenhum build do Stockfish para Windows x86-64 encontrado na release.")
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / asset["name"]
        download(asset["browser_download_url"], zip_path, progress, opener, label=asset["name"])
        _say(progress, "Extraindo...")
        with zipfile.ZipFile(zip_path) as zf:
            exes = [i for i in zf.infolist()
                    if i.filename.lower().endswith(".exe") and "stockfish" in i.filename.lower()]
            if not exes:
                raise RuntimeError("O pacote do Stockfish nao contem um executavel.")
            info = max(exes, key=lambda i: i.file_size)
            dest_dir.mkdir(parents=True, exist_ok=True)
            exe = dest_dir / Path(info.filename).name
            exe.write_bytes(zf.read(info))
    if validate:
        _say(progress, "Testando o motor...")
        if not check_engine(exe):
            exe.unlink(missing_ok=True)
            raise RuntimeError("O Stockfish baixado nao respondeu ao teste (UCI).")
    _say(progress, "Stockfish instalado.", 1.0)
    return exe


# ---------------- opening data ----------------
def get_eco(progress=None, opener=None, eco_dir=None, out_path=None):
    """Downloads the ECO table (a-e.tsv) and builds the opening book. Returns the number of entries."""
    eco_dir = Path(eco_dir or book.ECO_DIR)
    for i, letter in enumerate("abcde"):
        download(ECO_URL.format(letter), eco_dir / f"{letter}.tsv", None, opener, label=f"{letter}.tsv")
        _say(progress, "Baixando a tabela de aberturas", (i + 1) / 5)
    _say(progress, "Montando o livro de aberturas...")
    n = book.build_eco_book(eco_dir, out_path or book.ECO_BOOK)
    _say(progress, "Livro de aberturas pronto.", 1.0)
    return n


# ---------------- Syzygy tablebases ----------------
def syzygy_listing(kind, opener=None):
    """[(filename, size)] of a tablebase directory listing."""
    with _open(f"{TB_BASE}{kind}/", opener) as r:
        html = r.read().decode("utf8", "ignore")
    return [(n, int(s)) for n, s in
            re.findall(r'<a href="([^"]+\.rtb[wz])">[^<]*</a>\s+\S+\s+\S+\s+(\d+)', html)]


def syzygy_files(max_pieces, opener=None):
    """[(kind, filename, size)] for all WDL and DTZ tables of up to `max_pieces` pieces."""
    files = []
    for kind in ("3-4-5-wdl", "3-4-5-dtz"):
        files += [(kind, n, s) for n, s in syzygy_listing(kind, opener)
                  if len(n.split(".")[0].replace("v", "")) <= max_pieces]
    return files


def get_syzygy(max_pieces=4, progress=None, opener=None, dest_dir=None):
    dest_dir = Path(dest_dir or SYZYGY_DIR)
    files = syzygy_files(max_pieces, opener)
    for i, (kind, name, size) in enumerate(files, 1):
        download(f"{TB_BASE}{kind}/{name}", dest_dir / name, None, opener, expected=size, label=name)
        _say(progress, f"Baixando tablebases ({i}/{len(files)})", i / len(files))
    _say(progress, "Tablebases prontas.", 1.0)
    return len(files)
