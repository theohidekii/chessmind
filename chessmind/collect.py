"""Coletor de dados para treinar o reconhecimento por imagem (opcional, desligado por padrao).

O DOM da pagina da a posicao EXATA; a imagem do tabuleiro, capturada no mesmo instante, vira 64
exemplos rotulados automaticamente ('.' = casa vazia). Quanto mais temas de pecas e sites, melhor
sera o modelo treinado depois. Os arquivos ficam em dataset/ (nao vao para o git).
"""
import time

import numpy as np

from . import config, vision

DATASET_DIR = config.ROOT / "dataset"


def labeled_squares(frame, placement, white_bottom):
    """(X, y): X = (64, SZ, SZ, 3) uint8 com as casas na ordem da tela; y = 64 rotulos."""
    grid = vision.split_squares(frame)
    X, y = [], []
    for r in range(8):
        for c in range(8):
            rank = 8 - r if white_bottom else r + 1
            file_idx = c if white_bottom else 7 - c
            X.append(grid[r][c])
            y.append(placement.get("abcdefgh"[file_idx] + str(rank), "."))
    return np.stack(X).astype(np.uint8), np.array(y)


def save_sample(frame, placement, white_bottom, site="", directory=None):
    """Grava um exemplo (64 casas rotuladas). Retorna o caminho do arquivo."""
    directory = directory or DATASET_DIR
    directory.mkdir(exist_ok=True)
    X, y = labeled_squares(frame, placement, white_bottom)
    path = directory / f"{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000:03d}.npz"
    np.savez_compressed(path, X=X, y=y, site=site, board_px=frame.shape[0])
    return path


def count(directory=None):
    """Quantas posicoes ja foram coletadas."""
    directory = directory or DATASET_DIR
    return len(list(directory.glob("*.npz"))) if directory.exists() else 0
