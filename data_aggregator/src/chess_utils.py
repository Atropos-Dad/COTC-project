"""
Utility functions for chess operations, including FEN generation.
"""
import chess
import logging
import re

logger = logging.getLogger(__name__)

# Standard starting position FEN
DEFAULT_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

def get_attribute_safe(obj, attr_name, default=None):
    """
    Safely get an attribute from an object or a key from a dictionary.
    
    Args:
        obj: The object or dictionary to get the attribute/key from
        attr_name: The name of the attribute or key
        default: Default value to return if attribute/key is not found
        
    Returns:
        The attribute/key value or default if not found
    """
    if isinstance(obj, dict):
        return obj.get(attr_name, default)
    elif hasattr(obj, attr_name):
        return getattr(obj, attr_name, default)
    return default

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
        moves: List of move dictionaries or objects with 'last_move' attribute/key
        initial_fen: Initial FEN position to start from (default: standard starting position)
    
    Returns:
        Current FEN position after applying all moves
    """
    # Enhanced logging for input debugging
    logger.debug(f"[DERIVE_FEN] Starting FEN derivation with initial FEN: {initial_fen}")
    logger.debug(f"[DERIVE_FEN] Input moves type: {type(moves)}, repr: {repr(moves)}")
    
    # Handle case where a single Move object is passed instead of a list
    if not isinstance(moves, list):
        if get_attribute_safe(moves, 'last_move') is not None:
            logger.warning(f"[DERIVE_FEN] Single move object received, converting to list: {repr(moves)}")
            moves = [moves]
        else:
            logger.error(f"[DERIVE_FEN] Invalid moves input, not a list or Move object: {type(moves)}")
            return initial_fen
    
    if not moves:
        logger.debug("[DERIVE_FEN] No moves provided to derive_fen_from_moves, returning initial FEN")
        return initial_fen
    
    # Log information about the moves we're working with
    logger.debug(f"[DERIVE_FEN] Processing {len(moves)} moves")
    
    # Check if any of the moves already has a valid FEN position
    # If so, use the most recent one as the starting point
    latest_fen = None
    for i in range(len(moves) - 1, -1, -1):
        fen_position = get_attribute_safe(moves[i], 'fen_position')
        if fen_position and is_valid_fen(fen_position):
            latest_fen = fen_position
            # Only process moves after this one
            moves = moves[i+1:]
            logger.debug(f"[DERIVE_FEN] Using FEN from move record as starting point: {latest_fen}")
            break
    
    # If we found a valid FEN in the moves, use it; otherwise use the provided initial_fen
    if latest_fen:
        initial_fen = latest_fen
    
    # Verify the initial FEN is valid before proceeding
    if not is_valid_fen(initial_fen):
        logger.warning(f"[DERIVE_FEN] Invalid initial FEN provided: '{initial_fen}', using DEFAULT_FEN")
        initial_fen = DEFAULT_FEN
    
    try:
        # Create a board with the initial position
        board = chess.Board(initial_fen)
        
        # Track valid and invalid moves for debugging
        valid_moves = 0
        invalid_moves = 0
        
        # Apply each move in sequence
        for move in moves:
            # Debug log the move details
            move_debug_info = f"Move type: {type(move)}"
            if isinstance(move, dict):
                move_debug_info += f", keys: {list(move.keys())}"
            else:
                move_debug_info += f", attributes: {[attr for attr in dir(move) if not attr.startswith('_')]}"
            
            logger.debug(f"[DERIVE_FEN] Processing move: {move_debug_info}")
            
            # Get the move text using our utility function
            move_text = get_attribute_safe(move, 'last_move')
            
            # Skip if move_text is missing or invalid
            if not move_text or not isinstance(move_text, str) or not move_text.strip():
                invalid_moves += 1
                logger.debug(f"[DERIVE_FEN] Skipping invalid move: missing or empty last_move")
                continue
                
            move_text = move_text.strip()
            
            # Clean up the move string (remove check/mate symbols, annotations)
            clean_move = re.sub(r'[+#!?]', '', move_text)
            logger.debug(f"[DERIVE_FEN] Processing move text: '{move_text}' -> '{clean_move}'")
            
            try:
                # Try to parse as UCI move first (e.g., 'f8g8')
                try:
                    chess_move = chess.Move.from_uci(clean_move)
                    if chess_move in board.legal_moves:
                        board.push(chess_move)
                        valid_moves += 1
                        logger.debug(f"[DERIVE_FEN] Applied UCI move: {clean_move}")
                        continue
                except ValueError:
                    # Not a valid UCI move, try SAN format next
                    pass
                
                # Parse the move string as SAN and apply it to the board
                chess_move = board.parse_san(clean_move)
                board.push(chess_move)
                valid_moves += 1
                logger.debug(f"[DERIVE_FEN] Applied SAN move: {clean_move}")
            except ValueError as e:
                # If there's an error parsing the move, log it and continue
                logger.warning(f"[DERIVE_FEN] Failed to parse move '{move_text}' (cleaned: '{clean_move}'): {str(e)}")
                invalid_moves += 1
                continue
            except Exception as e:
                logger.warning(f"[DERIVE_FEN] Unexpected error applying move '{move_text}': {str(e)}")
                invalid_moves += 1
                continue
        
        # Log summary of move application
        logger.info(f"[DERIVE_FEN] FEN derivation applied {valid_moves} valid moves, {invalid_moves} invalid moves")
        
        # Return the resulting FEN position
        result_fen = board.fen()
        
        # Final validation check
        if not is_valid_fen(result_fen):
            logger.error(f"[DERIVE_FEN] Derived an invalid FEN: '{result_fen}', falling back to DEFAULT_FEN")
            return DEFAULT_FEN
            
        logger.info(f"[DERIVE_FEN] Successfully derived FEN: {result_fen}")
        return result_fen
    except Exception as e:
        logger.error(f"[DERIVE_FEN] Error deriving FEN from moves: {str(e)}", exc_info=True)
        return DEFAULT_FEN
