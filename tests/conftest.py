"""Os testes nao devem escrever no log real do usuario (logs/chessmind.log)."""
import os
import tempfile

os.environ.setdefault("CHESSMIND_LOG_DIR", tempfile.mkdtemp(prefix="chessmind-testlogs-"))
