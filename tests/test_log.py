import logging

from chessmind import log


def test_module_loggers_write_to_the_log_file(tmp_path, monkeypatch):
    monkeypatch.setattr(log, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(log, "_ready", False)
    root = logging.getLogger("chessmind")
    before = list(root.handlers)
    try:
        runner_log = log.get("runner")
        assert runner_log.name == "chessmind.runner" and log.get("chessmind.gui").name == "chessmind.gui"
        runner_log.info("mensagem de teste do runner")
        for h in root.handlers:
            h.flush()
        text = (tmp_path / "logs" / "chessmind.log").read_text(encoding="utf-8")
        assert "mensagem de teste do runner" in text and "chessmind.runner" in text
    finally:
        for h in list(root.handlers):
            if h not in before:
                root.removeHandler(h)
                h.close()
