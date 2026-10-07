"""Le o tabuleiro da tela e devolve a colocacao das pecas.

Sem rede neural: para cada casa, o fundo e estimado pela mediana dos cantos
(funciona com casas destacadas) e a peca e a mascara de pixels diferentes do
fundo. A mascara e comparada (IoU) com modelos aprendidos na calibracao a
partir da posicao inicial.
"""
import cv2
import numpy as np

SZ = 40
PIECES = "PNBRQKpnbrqk"  # um modelo por peca/cor; a cor final vem do brilho
START_BACK = "RNBQKBNR"


def find_board(roi):
    """Acha as bordas exatas do tabuleiro dentro de uma selecao aproximada.

    As duas cores mais frequentes (casas claras/escuras) delimitam o tabuleiro.
    Retorna (x, y, lado) relativo ao roi, ou None."""
    q = (roi // 8).astype(np.int32)
    key = q[..., 0] * 1024 + q[..., 1] * 32 + q[..., 2]
    vals, counts = np.unique(key, return_counts=True)
    top = vals[np.argsort(counts)[::-1][:8]]
    # As cores das casas sao as que mais alternam entre si na horizontal
    # (o fundo da pagina so encosta no tabuleiro numa borda).
    left, right = key[:, :-1], key[:, 1:]
    best, pair = 0, None
    for i, ca in enumerate(top):
        for cb in top[i + 1:]:
            n = np.count_nonzero(((left == ca) & (right == cb)) | ((left == cb) & (right == ca)))
            if n > best:
                best, pair = n, (ca, cb)
    if pair is None:
        return None
    mask = np.isin(key, pair)
    cols = np.where(mask.mean(axis=0) > 0.35)[0]
    rows = np.where(mask.mean(axis=1) > 0.35)[0]
    if len(cols) < 40 or len(rows) < 40:
        return None
    x0, x1, y0, y1 = cols[0], cols[-1] + 1, rows[0], rows[-1] + 1
    return int(x0), int(y0), int(min(x1 - x0, y1 - y0))


def split_squares(board_img):
    """Devolve grid[row][col] (row 0 = topo da tela) com cada casa em SZxSZ."""
    h, w = board_img.shape[:2]
    out = []
    for r in range(8):
        row = []
        for c in range(8):
            sq = board_img[r * h // 8:(r + 1) * h // 8, c * w // 8:(c + 1) * w // 8]
            row.append(cv2.resize(sq, (SZ, SZ), interpolation=cv2.INTER_AREA))
        out.append(row)
    return out


def square_mask(sq):
    k = 6
    corners = np.concatenate([
        sq[:k, :k].reshape(-1, 3), sq[:k, -k:].reshape(-1, 3),
        sq[-k:, :k].reshape(-1, 3), sq[-k:, -k:].reshape(-1, 3)])
    bg = np.median(corners, axis=0)
    dist = np.linalg.norm(sq.astype(np.float32) - bg, axis=2)
    mask = (dist > 45).astype(np.uint8)
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))


def iou(a, b):
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    return inter / union if union else 0.0


def learn_templates(grid, white_bottom=True):
    """grid vem de uma tela com a posicao inicial. Retorna {simbolo: mascara media}."""
    acc = {p: [] for p in PIECES}
    for r in range(8):
        for c in range(8):
            if r in (2, 3, 4, 5):
                continue
            rank_from_top = r if white_bottom else 7 - r
            file_idx = c if white_bottom else 7 - c
            if rank_from_top == 0:
                sym = START_BACK[file_idx].lower()
            elif rank_from_top == 1:
                sym = "p"
            elif rank_from_top == 6:
                sym = "P"
            else:
                sym = START_BACK[file_idx]
            acc[sym].append(square_mask(grid[r][c]).astype(np.float32))
    return {p: (np.mean(v, axis=0) > 0.5) for p, v in acc.items() if v}


def classify(grid, templates, min_fill=0.06):
    """Retorna matriz 8x8 de simbolos ('.' = vazio) na orientacao da tela."""
    result = []
    for r in range(8):
        row = []
        for c in range(8):
            mask = square_mask(grid[r][c])
            if mask.mean() < min_fill:
                row.append(".")
                continue
            kind = max(templates, key=lambda p: iou(mask > 0, templates[p])).lower()
            core = cv2.erode(mask, np.ones((5, 5), np.uint8)).astype(bool)
            if core.sum() < 10:
                core = mask.astype(bool)
            gray = cv2.cvtColor(grid[r][c], cv2.COLOR_BGR2GRAY)
            row.append(kind.upper() if np.median(gray[core]) > 128 else kind)
        result.append(row)
    return result


def to_placement(matrix, white_bottom=True):
    """Matriz da tela -> dict {square_name: simbolo} (a1..h8)."""
    out = {}
    for r in range(8):
        for c in range(8):
            if matrix[r][c] == ".":
                continue
            rank = 8 - r if white_bottom else r + 1
            file_idx = c if white_bottom else 7 - c
            out["abcdefgh"[file_idx] + str(rank)] = matrix[r][c]
    return out
