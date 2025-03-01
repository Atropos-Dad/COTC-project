"""
Database connection and management for the data aggregator.
"""
import os
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.exc import SQLAlchemyError
import logging

from models import Base, Game, Move, RawData
from chess_utils import derive_fen_from_moves, is_valid_fen, DEFAULT_FEN

# Set up logging
logger = logging.getLogger(__name__)

# Database configuration
DB_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, 'chess_data.db')

# Create engine and session
engine = create_engine(f'sqlite:///{DB_PATH}')
SessionFactory = sessionmaker(bind=engine)
Session = scoped_session(SessionFactory)


def init_db():
    """Initialize the database schema."""
    try:
        Base.metadata.create_all(engine)
        logger.info("Database initialized successfully")
    except SQLAlchemyError as e:
        logger.error(f"Error initializing database: {str(e)}")
        raise


def save_chess_data(data):
    """
    Save chess data to the database.
    
    Args:
        data (dict): The chess data to save
        
    Returns:
        dict: Response with status information
    """
    session = Session()
    try:
        # Log the start of the database operation
        logger.info(f"[DB_OPERATION_START] Saving data to database")
        
        # Always save raw data
        raw_data = RawData(
            measurement=data.get('measurement'),
            data=data,
            received_timestamp=datetime.now()
        )
        
        # Try to parse the time field as a system timestamp
        if 'time' in data:
            try:
                # Convert nanoseconds to seconds and create datetime
                timestamp_ns = int(data['time'])
                timestamp_s = timestamp_ns / 1_000_000_000
                raw_data.system_timestamp = datetime.fromtimestamp(timestamp_s)
                logger.debug(f"[DB_TIMESTAMP] Parsed system timestamp: {raw_data.system_timestamp.isoformat()}")
            except (ValueError, TypeError) as e:
                logger.warning(f"[DB_TIMESTAMP_ERROR] Could not parse timestamp: {str(e)}")
                pass
                
        session.add(raw_data)
        
        # Process chess game data if applicable
        if data.get('measurement') == 'chess_game' and 'tags' in data:
            tags = data['tags']
            fields = data.get('fields', {})
            game_id = tags.get('game_id')
            event_type = tags.get('event_type')
            
            logger.info(f"[DB_CHESS_DATA] Processing chess data | Game ID: {game_id} | Event: {event_type}")
            
            if not game_id:
                logger.warning("[DB_MISSING_ID] Missing game_id in chess data")
                session.commit()
                return {'message': 'Raw data saved, but missing game_id'}
            
            # For new games, create game record
            if event_type == 'new_game':
                # Check if game already exists
                existing_game = session.query(Game).filter_by(game_id=game_id).first()
                
                if existing_game:
                    logger.info(f"[DB_GAME_UPDATE] Game {game_id} already exists, updating")
                    game = existing_game
                else:
                    logger.info(f"[DB_GAME_CREATE] Creating new game record for {game_id}")
                    logger.debug(f"[DB_GAME_DETAILS] White: {tags.get('white_player')} ({tags.get('white_rating')}) | Black: {tags.get('black_player')} ({tags.get('black_rating')})")
                    game = Game(
                        game_id=game_id,
                        white_player=tags.get('white_player'),
                        black_player=tags.get('black_player'),
                        white_title=tags.get('white_title'),
                        black_title=tags.get('black_title'),
                        white_rating=tags.get('white_rating'),
                        black_rating=tags.get('black_rating'),
                        start_time=datetime.now()
                    )
                    session.add(game)
            
            # For all events, record move if applicable
            if fields:
                logger.info(f"[DB_MOVE_RECORD] Recording move for game {game_id}")
                
                # Log move details at debug level
                last_move = fields.get('last_move')
                fen_position = fields.get('fen_position')
                white_time = fields.get('white_time')
                black_time = fields.get('black_time')
                
                # Check if FEN position is missing but we have a last_move
                if (not fen_position or not is_valid_fen(fen_position)) and last_move:
                    logger.info(f"[DB_FEN_DERIVE] Deriving FEN for game {game_id} move {last_move}")
                    
                    try:
                        # Get previous moves to derive the current FEN
                        previous_moves = session.query(Move).filter(
                            Move.game_id == game_id
                        ).order_by(Move.timestamp).all()
                        
                        # Create a new list with all previous moves plus the current one
                        # This is needed because the current move is not yet in the database
                        current_move = Move(
                            game_id=game_id,
                            last_move=last_move,
                            fen_position=None  # We're calculating this
                        )
                        
                        all_moves = previous_moves + [current_move]
                        
                        # Derive the FEN from the moves
                        calculated_fen = derive_fen_from_moves(all_moves)
                        fen_position = calculated_fen
                        
                        logger.info(f"[DB_FEN_DERIVED] Successfully derived FEN: {fen_position}")
                    except Exception as e:
                        logger.error(f"[DB_FEN_ERROR] Could not derive FEN: {str(e)}")
                        # Use default FEN if we can't derive one (better than nothing)
                        if not fen_position:
                            fen_position = DEFAULT_FEN
                
                logger.debug(f"[DB_MOVE_DETAILS] Last move: {last_move} | FEN: {fen_position}")
                logger.debug(f"[DB_MOVE_CLOCK] White time: {white_time} | Black time: {black_time}")
                
                move = Move(
                    game_id=game_id,
                    last_move=last_move,
                    white_time=white_time,
                    black_time=black_time,
                    white_piece_count=fields.get('white_piece_count'),
                    black_piece_count=fields.get('black_piece_count'),
                    fen_position=fen_position,
                    timestamp=datetime.now()
                )
                session.add(move)
        
        session.commit()
        logger.info(f"[DB_OPERATION_END] Successfully saved data to database")
        
        return {
            'message': 'Data saved successfully to database',
            'timestamp': datetime.now().isoformat(),
            'id': raw_data.id
        }
        
    except SQLAlchemyError as e:
        session.rollback()
        error_msg = str(e)
        logger.error(f"[DB_ERROR] Database error: {error_msg}")
        return {'error': error_msg}
    except Exception as e:
        session.rollback()
        error_msg = str(e)
        logger.error(f"[DB_ERROR] Error processing data: {error_msg}")
        return {'error': error_msg}
    finally:
        session.close()

