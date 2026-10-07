"""Calibracao via Playwright: com a partida na posicao INICIAL no Chrome do coach, rode:
    python calibrate_pw.py
Nao precisa selecionar nada: o tabuleiro e a orientacao sao lidos da pagina.
"""
import cv2
import numpy as np

from chessmind import config, vision
from chessmind.pwsource import PWBoard

try:
    pw = PWBoard()
except Exception as e:
    raise SystemExit(f"Nao consegui conectar ao Chrome do coach ({e}). Use 'Abrir Chrome do coach'.")

img = pw.frame()
white_bottom = pw.white_bottom()
pw.close()
if img is None:
    raise SystemExit("Nenhum tabuleiro encontrado nas abas. Abra uma partida no chess.com ou lichess.")

grid = vision.split_squares(img)
templates = vision.learn_templates(grid, white_bottom)
np.savez(config.TEMPLATES_PATH, **templates)
config.save_calibration({"source": "playwright", "white_bottom": white_bottom})

placement = vision.to_placement(vision.classify(grid, templates), white_bottom)
cv2.imwrite(str(config.ROOT / "debug_board.png"), img)
print("Voce joga de", "brancas" if white_bottom else "pretas")
print("Calibrado. Pecas lidas:", len(placement), "(esperado 32)")
if len(placement) != 32:
    print("\n".join("".join(r) for r in vision.classify(grid, templates)))
    print("Leitura errada. A partida precisa estar na posicao inicial. Veja debug_board.png.")
