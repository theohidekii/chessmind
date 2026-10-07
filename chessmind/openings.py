"""Reconhecimento de aberturas por prefixo de lances. Lista compacta das mais comuns:
e uma aproximacao (o nome mais especifico que casa com o inicio da partida)."""

# (nome, lances em SAN)
_OPENINGS = [
    ("Abertura do Peao do Rei", "e4"),
    ("Abertura do Peao da Dama", "d4"),
    ("Abertura Inglesa", "c4"),
    ("Abertura Reti", "Nf3"),
    ("Defesa Siciliana", "e4 c5"),
    ("Siciliana Fechada", "e4 c5 Nc3"),
    ("Siciliana Aberta", "e4 c5 Nf3 d6 d4 cxd4 Nxd4"),
    ("Siciliana Najdorf", "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6"),
    ("Siciliana Dragao", "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 g6"),
    ("Defesa Francesa", "e4 e6"),
    ("Francesa, Variante do Avanco", "e4 e6 d4 d5 e5"),
    ("Francesa, Variante Winawer", "e4 e6 d4 d5 Nc3 Bb4"),
    ("Defesa Caro-Kann", "e4 c6"),
    ("Caro-Kann, Variante do Avanco", "e4 c6 d4 d5 e5"),
    ("Defesa Escandinava", "e4 d5"),
    ("Defesa Pirc", "e4 d6 d4 Nf6 Nc3 g6"),
    ("Defesa Alekhine", "e4 Nf6"),
    ("Jogo do Rei", "e4 e5"),
    ("Abertura Vienense", "e4 e5 Nc3"),
    ("Gambito do Rei", "e4 e5 f4"),
    ("Jogo Italiano", "e4 e5 Nf3 Nc6 Bc4"),
    ("Giuoco Piano", "e4 e5 Nf3 Nc6 Bc4 Bc5"),
    ("Defesa dos Dois Cavalos", "e4 e5 Nf3 Nc6 Bc4 Nf6"),
    ("Abertura Escocesa", "e4 e5 Nf3 Nc6 d4"),
    ("Ruy Lopez", "e4 e5 Nf3 Nc6 Bb5"),
    ("Ruy Lopez, Defesa Berlinense", "e4 e5 Nf3 Nc6 Bb5 Nf6"),
    ("Ruy Lopez, Variante Morphy", "e4 e5 Nf3 Nc6 Bb5 a6"),
    ("Defesa Petrov", "e4 e5 Nf3 Nf6"),
    ("Gambito da Dama", "d4 d5 c4"),
    ("Gambito da Dama Recusado", "d4 d5 c4 e6"),
    ("Gambito da Dama Aceito", "d4 d5 c4 dxc4"),
    ("Defesa Eslava", "d4 d5 c4 c6"),
    ("Sistema Londres", "d4 d5 Nf3 Nf6 Bf4"),
    ("Defesa Indio da Rainha", "d4 Nf6 c4 e6 Nf3 b6"),
    ("Defesa Nimzo-Indiana", "d4 Nf6 c4 e6 Nc3 Bb4"),
    ("Defesa Indio do Rei", "d4 Nf6 c4 g6"),
    ("Defesa Grunfeld", "d4 Nf6 c4 g6 Nc3 d5"),
    ("Defesa Holandesa", "d4 f5"),
    ("Inglesa Simetrica", "c4 c5"),
    ("Abertura Larsen", "b3"),
    ("Abertura Bird", "f4"),
]
_TABLE = {tuple(m.split()): n for n, m in _OPENINGS}
_ECO = None


def reset_cache():
    global _ECO
    _ECO = None


def _eco_table():
    """{lances: nome} da tabela ECO do Lichess (engine/books/eco/*.tsv), se instalada."""
    global _ECO
    if _ECO is None:
        _ECO = {}
        try:
            from . import book
            files = book.eco_files()
            if files:
                _ECO = {tuple(sans): name for _, name, sans in book.read_eco_tsv(files)}
        except Exception:
            _ECO = {}
    return _ECO


def opening_name(san_moves):
    """Nome da abertura mais especifica que casa com o inicio da lista de lances (ou None).
    Usa a tabela ECO completa se instalada; senao uma lista compacta embutida."""
    moves = tuple(san_moves)
    for table in (_eco_table(), _TABLE):
        for n in range(len(moves), 0, -1):
            name = table.get(moves[:n])
            if name:
                return name
    return None
