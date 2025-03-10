"""
Utility functions for chess operations, including FEN generation.
"""
import chess
import logging
import re

logger = logging.getLogger(__name__)

# Standard starting position FEN
DEFAULT_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

def is_valid_fen(fen):
    """
    Check if a FEN string appears to be valid.
    
    Args:
        fen: FEN string to validate
        
    Returns:
        bool: True if valid, False otherwise
    """
    if not fen or not isinstance(fen, str):
        logger.debug(f"Invalid FEN: null or not a string: '{fen}'")
        return False
    
    # Simple regex check for basic FEN format before attempting to create board
    # This helps avoid costly exceptions for obviously invalid strings
    basic_fen_pattern = r'^[1-8pnbrqkPNBRQK/]+ [wb] [KQkq-]+ [a-h36-]+ \d+ \d+$'
    if not re.match(basic_fen_pattern, fen):
        logger.debug(f"FEN failed basic format check: '{fen}'")
        return False
    
    try:
        # Use chess library's board validation
        chess.Board(fen)
        return True
    except ValueError as e:
        logger.debug(f"Invalid FEN (chess library): '{fen}', error: {str(e)}")
        return False
    except Exception as e:
        logger.warning(f"Unexpected error validating FEN: '{fen}', error: {str(e)}")
        return False

def derive_fen_from_moves(moves, initial_fen=DEFAULT_FEN):
    """
    Derive the current FEN position from a list of moves and an initial FEN.
    
    Args:
        moves: List of Move objects with last_move attribute
        initial_fen: Initial FEN position to start from (default: standard starting position)
    
    Returns:
        Current FEN position after applying all moves
    """
    if not moves:
        logger.debug("No moves provided to derive_fen_from_moves, returning initial FEN")
        return initial_fen
    
    # Check if any of the moves already has a valid FEN position
    # If so, use the most recent one as the starting point
    latest_fen = None
    for i in range(len(moves) - 1, -1, -1):
        if hasattr(moves[i], 'fen_position') and moves[i].fen_position and is_valid_fen(moves[i].fen_position):
            latest_fen = moves[i].fen_position
            # Only process moves after this one
            moves = moves[i+1:]
            logger.debug(f"Using FEN from move record as starting point: {latest_fen}")
            break
    
    # If we found a valid FEN in the moves, use it; otherwise use the provided initial_fen
    if latest_fen:
        initial_fen = latest_fen
    
    # Verify the initial FEN is valid before proceeding
    if not is_valid_fen(initial_fen):
        logger.warning(f"Invalid initial FEN provided: '{initial_fen}', using DEFAULT_FEN")
        initial_fen = DEFAULT_FEN
    
    try:
        # Create a board with the initial position
        board = chess.Board(initial_fen)
        
        # Track valid and invalid moves for debugging
        valid_moves = 0
        invalid_moves = 0
        
        # Apply each move in sequence
        for move in moves:
            if not move.last_move or not isinstance(move.last_move, str) or not move.last_move.strip():
                invalid_moves += 1
                continue
                
            # Clean up the move string (remove check/mate symbols, annotations)
            clean_move = re.sub(r'[+#!?]', '', move.last_move.strip())
            
            try:
                # Try to parse as UCI move first (e.g., 'f8g8')
                try:
                    chess_move = chess.Move.from_uci(clean_move)
                    if chess_move in board.legal_moves:
                        board.push(chess_move)
                        valid_moves += 1
                        continue
                except ValueError:
                    # Not a valid UCI move, try SAN format next
                    pass
                
                # Parse the move string as SAN and apply it to the board
                chess_move = board.parse_san(clean_move)
                board.push(chess_move)
                valid_moves += 1
            except ValueError as e:
                # If there's an error parsing the move, log it and continue
                logger.warning(f"Failed to parse move '{move.last_move}' (cleaned: '{clean_move}'): {str(e)}")
                invalid_moves += 1
                continue
            except Exception as e:
                logger.warning(f"Unexpected error applying move '{move.last_move}': {str(e)}")
                invalid_moves += 1
                continue
        
        # Log summary of move application
        logger.info(f"FEN derivation applied {valid_moves} valid moves, {invalid_moves} invalid moves")
        
        # Return the resulting FEN position
        result_fen = board.fen()
        
        # Final validation check
        if not is_valid_fen(result_fen):
            logger.error(f"Derived an invalid FEN: '{result_fen}', falling back to DEFAULT_FEN")
            return DEFAULT_FEN
            
        return result_fen
    except Exception as e:
        logger.error(f"Error deriving FEN from moves: {str(e)}")
        return DEFAULT_FEN
