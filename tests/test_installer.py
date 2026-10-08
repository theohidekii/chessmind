"""Installer and setup check, with a fake network: nothing is downloaded for real."""
import io
import json
import zipfile

import pytest

from chessmind import book, installer, setup_check


class FakeResponse(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def fake_opener(routes):
    """routes: {substring_of_url: bytes}. Records the requested URLs in .calls."""
    calls = []

    def opener(req, timeout=None):
        url = req.full_url
        calls.append(url)
        matches = [k for k in routes if k in url]
        if not matches:
            raise AssertionError(f"URL inesperada: {url}")
        return FakeResponse(routes[max(matches, key=len)])          # a rota mais especifica vence

    opener.calls = calls
    return opener


def make_zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


ASSETS = [
    {"name": "stockfish-windows-arm64-universal.zip", "browser_download_url": "http://x/arm"},
    {"name": "stockfish-ubuntu-x86-64-avx2.tar", "browser_download_url": "http://x/ubuntu"},
    {"name": "stockfish-windows-x86-64.zip", "browser_download_url": "http://x/plain"},
    {"name": "stockfish-windows-x86-64-avx2.zip", "browser_download_url": "http://x/avx2"},
    {"name": "stockfish-windows-x86-64-universal.zip", "browser_download_url": "http://x/universal"},
]


# ---------------- Stockfish ----------------
def test_asset_choice_prefers_universal_then_avx2_then_plain_and_skips_other_platforms():
    pick = installer.pick_stockfish_asset
    assert pick(ASSETS)["name"].endswith("x86-64-universal.zip")
    no_universal = [a for a in ASSETS if "universal" not in a["name"]]
    assert pick(no_universal, avx2=True)["name"].endswith("x86-64-avx2.zip")
    assert pick(no_universal, avx2=False)["name"] == "stockfish-windows-x86-64.zip"
    assert pick([a for a in ASSETS if "windows" not in a["name"] or "arm" in a["name"]]) is None
    assert pick([]) is None


def test_download_stockfish_extracts_the_exe_and_reports_progress(tmp_path):
    exe_bytes = b"MZ-fake-stockfish-binary" * 100
    pkg = make_zip({"stockfish/stockfish-windows-x86-64-universal.exe": exe_bytes, "stockfish/README.md": b"hi",
                    "stockfish/src/other.exe": b"x"})
    release = json.dumps({"assets": ASSETS}).encode()
    opener = fake_opener({"api.github.com": release, "x/universal": pkg})
    seen = []
    exe = installer.download_stockfish(progress=lambda m, f: seen.append((m, f)), opener=opener,
                                       dest_dir=tmp_path / "sf", validate=False)
    assert exe.name == "stockfish-windows-x86-64-universal.exe" and exe.read_bytes() == exe_bytes
    assert "x/universal" in opener.calls[-1]                       # baixou o build 'universal'
    assert any("Baixando" in m for m, _ in seen) and seen[-1][1] == 1.0


def test_download_stockfish_removes_a_binary_that_fails_the_uci_check(tmp_path, monkeypatch):
    pkg = make_zip({"stockfish-windows-x86-64-universal.exe": b"nao e um motor"})
    opener = fake_opener({"api.github.com": json.dumps({"assets": ASSETS}).encode(), "x/universal": pkg})
    monkeypatch.setattr(installer, "check_engine", lambda exe: False)
    with pytest.raises(RuntimeError, match="UCI"):
        installer.download_stockfish(opener=opener, dest_dir=tmp_path / "sf")
    assert not list((tmp_path / "sf").glob("*.exe"))               # nao deixa lixo


def test_download_stockfish_errors_are_clear(tmp_path):
    opener = fake_opener({"api.github.com": json.dumps({"assets": []}).encode()})
    with pytest.raises(RuntimeError, match="Nenhum build"):
        installer.download_stockfish(opener=opener, dest_dir=tmp_path)
    no_exe = make_zip({"readme.txt": b"x"})
    opener = fake_opener({"api.github.com": json.dumps({"assets": ASSETS}).encode(), "x/universal": no_exe})
    with pytest.raises(RuntimeError, match="executavel"):
        installer.download_stockfish(opener=opener, dest_dir=tmp_path, validate=False)


def test_check_engine_detects_a_real_uci_engine_and_rejects_garbage(tmp_path):
    from chessmind import config
    try:
        exe = config.find_stockfish()
    except FileNotFoundError:
        pytest.skip("Stockfish nao instalado")
    assert installer.check_engine(exe)
    assert not installer.check_engine(tmp_path / "nao-existe.exe")


# ---------------- ECO / book ----------------
def test_get_eco_downloads_five_tables_and_builds_the_book(tmp_path):
    tsv = "eco\tname\tpgn\nC60\tRuy Lopez\t1. e4 e5 2. Nf3 Nc6 3. Bb5\nB20\tSicilian\t1. e4 c5\n"
    opener = fake_opener({"chess-openings": tsv.encode()})
    seen = []
    n = installer.get_eco(lambda m, f: seen.append(f), opener, tmp_path / "eco", tmp_path / "eco.bin")
    assert n > 0 and (tmp_path / "eco.bin").exists()
    assert sorted(p.name for p in (tmp_path / "eco").glob("*.tsv")) == ["a.tsv", "b.tsv", "c.tsv", "d.tsv", "e.tsv"]
    assert len(opener.calls) == 5 and seen[-1] == 1.0
    assert book.Book([tmp_path / "eco.bin"]).available()


# ---------------- Syzygy ----------------
LISTING = (
    '<a href="KQvK.rtbw">KQvK.rtbw</a>   01-Jan-2020 00:00   272\n'
    '<a href="KRPvK.rtbw">KRPvK.rtbw</a>   01-Jan-2020 00:00   1000\n'
    '<a href="KQRvKR.rtbw">KQRvKR.rtbw</a>   01-Jan-2020 00:00   9999\n'
    '<a href="index.html">index.html</a>   01-Jan-2020 00:00   10\n'
)


def test_syzygy_listing_filters_by_piece_count():
    opener = fake_opener({"3-4-5-wdl": LISTING.encode(), "3-4-5-dtz": LISTING.replace("rtbw", "rtbz").encode()})
    only3 = installer.syzygy_files(3, opener)
    assert sorted(n for _, n, _ in only3) == ["KQvK.rtbw", "KQvK.rtbz"]
    up_to_4 = installer.syzygy_files(4, opener)
    assert {"KRPvK.rtbw", "KRPvK.rtbz"} <= {n for _, n, _ in up_to_4}
    assert not any("KQRvKR" in n for _, n, _ in up_to_4)             # 5 pecas ficam de fora


def test_get_syzygy_downloads_skips_complete_files_and_rejects_wrong_sizes(tmp_path):
    listing = '<a href="KQvK.rtbw">KQvK.rtbw</a>   x   y   8\n'
    routes = {"3-4-5-wdl/": listing.encode(), "3-4-5-dtz/": listing.replace("rtbw", "rtbz").encode(),
              "3-4-5-wdl/KQvK.rtbw": b"12345678", "3-4-5-dtz/KQvK.rtbz": b"12345678"}
    opener = fake_opener(routes)
    assert installer.get_syzygy(4, opener=opener, dest_dir=tmp_path) == 2
    assert (tmp_path / "KQvK.rtbw").read_bytes() == b"12345678"
    before = len(opener.calls)
    installer.get_syzygy(4, opener=opener, dest_dir=tmp_path)           # 2a vez: so as listagens, sem rebaixar
    assert len(opener.calls) - before == 2
    bad = fake_opener({**routes, "3-4-5-wdl/KQvK.rtbw": b"curto"})
    (tmp_path / "KQvK.rtbw").unlink()
    with pytest.raises(IOError, match="Tamanho"):
        installer.get_syzygy(4, opener=bad, dest_dir=tmp_path)
    assert not (tmp_path / "KQvK.rtbw").exists() and not list(tmp_path.glob("*.part"))


# ---------------- setup check ----------------
def test_setup_check_reports_required_and_optional_items(tmp_path, monkeypatch):
    from chessmind import config, pwsource
    monkeypatch.setattr(pwsource, "CHROME_PATHS", [str(tmp_path / "chrome.exe")])
    monkeypatch.setattr(config, "find_stockfish", lambda: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr(book, "ECO_BOOK", tmp_path / "eco.bin")
    monkeypatch.setattr(installer, "SYZYGY_DIR", tmp_path / "syzygy")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "calibration.json")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    checks = {c.key: c for c in setup_check.run_checks()}
    assert not checks["chrome"].ok and checks["chrome"].required
    assert not checks["stockfish"].ok and checks["stockfish"].fix == "stockfish"
    assert checks["book"].fix == "eco" and checks["syzygy"].fix == "syzygy"
    assert not setup_check.ready(list(checks.values()))
    # tudo no lugar
    (tmp_path / "chrome.exe").write_text("x")
    (tmp_path / "eco.bin").write_bytes(b"x")
    (tmp_path / "syzygy").mkdir()
    (tmp_path / "syzygy" / "KQvK.rtbw").write_bytes(b"x")
    (tmp_path / "calibration.json").write_text("{}")
    monkeypatch.setattr(config, "find_stockfish", lambda: "C:/sf.exe")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    checks = {c.key: c for c in setup_check.run_checks()}
    assert all(c.ok for c in checks.values()) and setup_check.ready(list(checks.values()))
    assert checks["syzygy"].detail == "1 arquivos" and not checks["book"].fix


def test_ready_only_depends_on_required_items():
    ok = setup_check.Check("a", "A", True, "", required=True)
    optional_missing = setup_check.Check("b", "B", False, "", required=False)
    required_missing = setup_check.Check("c", "C", False, "", required=True)
    assert setup_check.ready([ok, optional_missing])
    assert not setup_check.ready([ok, required_missing])


# ---------------- scripts / launcher helpers ----------------
def test_console_python_swaps_pythonw_for_python(tmp_path, monkeypatch):
    from chessmind import config
    (tmp_path / "python.exe").write_text("")
    (tmp_path / "pythonw.exe").write_text("")
    monkeypatch.setattr("sys.executable", str(tmp_path / "pythonw.exe"))
    assert config.console_python() == str(tmp_path / "python.exe")
    monkeypatch.setattr("sys.executable", str(tmp_path / "python.exe"))
    assert config.console_python() == str(tmp_path / "python.exe")


def test_get_data_all_skips_stockfish_that_is_already_installed(monkeypatch, capsys):
    import importlib.util
    from pathlib import Path
    from chessmind import config
    spec = importlib.util.spec_from_file_location("get_data", Path(__file__).parent.parent / "scripts" / "get_data.py")
    gd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gd)
    called = []
    monkeypatch.setattr(config, "find_stockfish", lambda: "C:/sf/stockfish.exe")
    monkeypatch.setattr(gd.installer, "download_stockfish", lambda p=None: called.append("sf"))
    monkeypatch.setattr(gd.installer, "get_eco", lambda p=None: called.append("eco") or 1)
    monkeypatch.setattr(gd.installer, "get_syzygy", lambda n, p=None: called.append("tb") or 1)
    assert gd.main(["--all"]) == 0
    assert called == ["eco", "tb"] and "already installed" in capsys.readouterr().out
    called.clear()
    monkeypatch.setattr(config, "find_stockfish", lambda: (_ for _ in ()).throw(FileNotFoundError()))
    assert gd.main(["--all"]) == 0 and called == ["sf", "eco", "tb"]
    called.clear()
    assert gd.main(["--stockfish"]) == 0 and called == ["sf"]               # pedido explicito: sempre baixa


def test_get_data_reports_failures_but_keeps_going(monkeypatch, capsys):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("get_data2", Path(__file__).parent.parent / "scripts" / "get_data.py")
    gd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gd)
    monkeypatch.setattr(gd.installer, "get_eco", lambda p=None: (_ for _ in ()).throw(OSError("sem internet")))
    ok = []
    monkeypatch.setattr(gd.installer, "get_syzygy", lambda n, p=None: ok.append(n) or 3)
    assert gd.main(["--eco", "--syzygy", "4"]) == 1                          # falhou, mas nao parou
    assert ok == [4] and "FAILED: OSError: sem internet" in capsys.readouterr().out
