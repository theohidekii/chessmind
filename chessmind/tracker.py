"""Acompanha a partida: converte a colocacao lida da tela em lances validos e reconstroi o
estado exato (vez, roque, en passant) quando entramos numa partida em andamento."""
import chess

# Casa inicial do rei/torres -> bit de direito de roque
_CASTLING_HOMES = (
    (chess.WHITE, chess.E1, chess.H1, chess.BB_H1),
    (chess.WHITE, chess.E1, chess.A1, chess.BB_A1),
    (chess.BLACK, chess.E8, chess.H8, chess.BB_H8),
    (chess.BLACK, chess.E8, chess.A8, chess.BB_A8),
)


def placement_of(board):
    return {chess.square_name(s): p.symbol() for s, p in board.piece_map().items()}


def board_from_placement(placement):
    b = chess.Board(None)
    for sq, sym in placement.items():
        b.set_piece_at(chess.parse_square(sq), chess.Piece.from_symbol(sym))
    return b


def board_from_moves(san_list):
    """Reproduz a partida a partir da lista de lances (SAN). None se algum lance for invalido."""
    b = chess.Board()
    for san in san_list:
        try:
            b.push_san(san)
        except ValueError:
            return None
    return b


def infer_castling(b):
    """Direitos de roque plausiveis: rei e torre nas casas iniciais.

    So erra se rei/torre ja se moveram e voltaram (raro); sem a lista de lances nao ha como saber."""
    rights = 0
    for color, king_sq, rook_sq, bit in _CASTLING_HOMES:
        if (b.piece_at(king_sq) == chess.Piece(chess.KING, color)
                and b.piece_at(rook_sq) == chess.Piece(chess.ROOK, color)):
            rights |= bit
    b.castling_rights = rights


def _last_move_from_highlights(b, highlights):
    """(origem, destino) do ultimo lance, a partir das casas destacadas pelo site, ou None."""
    squares = []
    for name in highlights or []:
        try:
            squares.append(chess.parse_square(name))
        except ValueError:
            pass
    dests = [s for s in squares if b.piece_at(s) is not None]
    froms = [s for s in squares if b.piece_at(s) is None]
    if len(dests) == 1 and len(froms) == 1:      # lance normal
        return froms[0], dests[0]
    if len(dests) == 2 and not froms:            # roque (rei e torre) ou destaque ambiguo
        kings = [s for s in dests if b.piece_at(s).piece_type == chess.KING]
        if kings:
            return None, kings[0]
    return None


def infer_turn(b, state, user_color):
    """Devolve (cor_da_vez, fonte). Usa o que for mais confiavel disponivel."""
    valid = []
    for color in (chess.WHITE, chess.BLACK):
        b.turn = color
        if b.is_valid():
            valid.append(color)
    if len(valid) == 1:
        return valid[0], "legalidade"
    if not valid:
        return user_color, "suposicao"
    state = state or {}
    clock = state.get("turn")
    if clock in ("w", "b"):
        color = chess.WHITE if clock == "w" else chess.BLACK
        if color in valid:
            return color, "relogio"
    last = _last_move_from_highlights(b, state.get("highlights"))
    if last:
        moved = b.piece_at(last[1])
        if moved is not None and (not moved.color) in valid:
            return (not moved.color), "destaque"
    return user_color, "suposicao"


def infer_en_passant(b, state):
    """Casa de en passant se o ultimo lance (pelos destaques) foi um avanco duplo de peao."""
    last = _last_move_from_highlights(b, (state or {}).get("highlights"))
    if not last or last[0] is None:
        return None
    frm, to = last
    p = b.piece_at(to)
    if p and p.piece_type == chess.PAWN and abs(chess.square_rank(to) - chess.square_rank(frm)) == 2 \
            and chess.square_file(to) == chess.square_file(frm):
        return (frm + to) // 2
    return None


class Tracker:
    def __init__(self, user_is_white):
        self.user_is_white = user_is_white
        self.board = None
        self.source = None      # como o estado atual foi obtido (para log/diagnostico)

    @property
    def user_color(self):
        return chess.WHITE if self.user_is_white else chess.BLACK

    def update(self, placement, state=None):
        """Retorna True se a posicao mudou/foi sincronizada."""
        if self.board is not None:
            if placement == placement_of(self.board):
                return False
            for m1 in list(self.board.legal_moves):
                self.board.push(m1)
                if placement_of(self.board) == placement:
                    return True
                # dois lances entre leituras (o seu e a resposta do adversario)
                for m2 in list(self.board.legal_moves):
                    self.board.push(m2)
                    if placement_of(self.board) == placement:
                        return True
                    self.board.pop()
                self.board.pop()
        return self._resync(placement, state)

    def _resync(self, placement, state):
        start = chess.Board()
        if placement == placement_of(start):
            self.board, self.source = start, "inicio"
            return True
        # 1) lista de lances da pagina: exata, mas so vale se bater com o tabuleiro
        moves = (state or {}).get("moves")
        if moves:
            b = board_from_moves(moves)
            if b is not None and placement_of(b) == placement:
                self.board, self.source = b, "lances"
                return True
        # 2) sinais do tabuleiro: legalidade, relogio, destaque do ultimo lance
        b = board_from_placement(placement)
        if len(b.piece_map()) < 2:
            return False
        infer_castling(b)
        turn, how = infer_turn(b, state, self.user_color)
        b.turn = turn
        b.ep_square = infer_en_passant(b, state)
        if not b.is_valid():
            b.ep_square = None
            if not b.is_valid():
                return False        # leitura ruidosa; tenta de novo no proximo ciclo
        self.board, self.source = b, how
        return True
