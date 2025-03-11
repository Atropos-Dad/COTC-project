"""
Database connection and management for the data aggregator.
"""
import os
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.exc import SQLAlchemyError
import logging

from models import Base, Game, Move, RawData, Metric, MetricOrigin, MetricType, TimeZoneSource, Player
from chess_utils import derive_fen_from_moves, is_valid_fen, DEFAULT_FEN
from lib_config.config import Config

# Set up logging
logger = logging.getLogger(__name__)

# Get the project root directory
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
config_path = os.path.join(project_root, "config.json")

# Initialize configuration
config = Config(config_path=config_path)

# Create engine and session based on configuration
def create_db_url():
    """Create database URL from configuration."""
    db_config = config.database
    if db_config.type == "postgresql":
        return f"postgresql://{db_config.user}:{db_config.password}@{db_config.host}:{db_config.port}/{db_config.name}"
    else:
        # Fallback to SQLite for development/testing
        DB_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
        os.makedirs(DB_DIR, exist_ok=True)
        DB_PATH = os.path.join(DB_DIR, 'chess_data.db')
        return f'sqlite:///{DB_PATH}'

# Create engine with appropriate configuration
def create_db_engine():
    """Create database engine with proper configuration."""
    db_url = create_db_url()
    if config.database.type == "postgresql":
        return create_engine(
            db_url,
            pool_size=config.database.pool_size,
            max_overflow=config.database.max_overflow,
            pool_timeout=config.database.pool_timeout,
            pool_pre_ping=True  # Enable connection health checks
        )
    else:
        return create_engine(db_url)

# Create engine and session
engine = create_db_engine()
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


def save_metric_data(data):
    """
    Save generic metric data to the database.
    
    Args:
        data (dict): Metric data in either format:
            Format 1 (Flat):
            {
                'origin': str,          # Source of the metric
                'metric_type': str,     # Type of metric
                'value': float,         # Numeric value
                'timestamp': datetime,  # Optional, defaults to now
                'metadata': dict        # Optional additional context
            }
            
            Format 2 (Timeseries):
            {
                'measurement': str,     # e.g., 'system_metrics'
                'tags': {
                    'origin': str,      # Source of the metric
                    'metric_type': str  # Type of metric
                },
                'fields': {
                    'value': float,     # Numeric value
                    ...                 # Other fields
                },
                'timestamp': str        # ISO format timestamp
            }
            
    Returns:
        dict: Response with status information
    """
    session = Session()
    try:
        # Log the start of the database operation
        logger.info(f"[DB_OPERATION_START] Saving metric data to database")
        
        # Check if data is in timeseries format
        is_timeseries = all(key in data for key in ['measurement', 'tags', 'fields'])
        
        if is_timeseries:
            # Extract data from timeseries format
            tags = data.get('tags', {})
            fields = data.get('fields', {})
            
            origin_name = tags.get('origin')
            measurement = data.get('measurement')
            
            # Set default origin for chess_game if not provided
            if measurement == 'chess_game' and not origin_name:
                origin_name = 'lichess'  # Default origin for chess game data
                
            if measurement == 'chess_game':
                # For chess game data, use event_type as the metric_type
                metric_type_name = tags.get('event_type')
                if not metric_type_name:
                    metric_type_name = 'game_update'  # Default metric_type if event_type is missing
                
                # Extract game_id for debugging and reference
                game_id = tags.get('game_id')
                logger.debug(f"Processing chess game data: game_id={game_id}, event_type={metric_type_name}, tags={tags}")
                
                # For chess games, we might want to save specific fields
                # Check if this is a new game or an update to an existing game
                if metric_type_name == 'new_game':
                    # This might be handled by the save_chess_data function instead
                    logger.debug(f"New chess game detected: {game_id}")
            else:
                # For system metrics, the metric_type is the field name
                # since each field is a separate metric
                metric_type_name = tags.get('metric_type')
                
                # If metric_type is not in tags, use the field name as the metric_type
                # This handles the case where system metrics are sent with fields like 'cpu_percent'
                if not metric_type_name and 'value' in fields:
                    # For system metrics, we need to process each field as a separate metric
                    for field_name, field_value in fields.items():
                        if field_name != 'value' and isinstance(field_value, (int, float)):
                            # Get or create origin
                            origin = get_or_create_origin(session, origin_name)
                            
                            # Get or create metric type
                            metric_type = get_or_create_metric_type(session, field_name)
                            
                            # Create a new metric for each field
                            metric = Metric(
                                origin_id=origin.id,
                                metric_type_id=metric_type.id,
                                value=float(field_value),
                                timestamp=timestamp,
                                additional_metadata={'measurement': measurement}
                            )
                            session.add(metric)
                            logger.debug(f"Added system metric: {field_name}={field_value} from {origin_name}")
            
            # Get the primary value (either the 'value' field or the first numeric field)
            value = fields.get('value')
            if value is None and fields:
                # If no 'value' field, use the first numeric field
                for field_name, field_value in fields.items():
                    if isinstance(field_value, (int, float)):
                        value = field_value
                        if not metric_type_name:
                            metric_type_name = field_name
                        break
            
            # Convert ISO timestamp to datetime if present
            try:
                timestamp = datetime.fromisoformat(data.get('timestamp').replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                timestamp = datetime.now()
                
            # Include any additional fields as metadata
            metadata = {k: v for k, v in fields.items() if k != 'value'}
            if not metadata:
                metadata = None
        else:
            # Extract data from flat format
            origin_name = data.get('origin')
            metric_type_name = data.get('metric_type')
            value = data.get('value')
            timestamp = data.get('timestamp', datetime.now())
            metadata = data.get('metadata')
        
        # Validate required fields for the primary metric
        if is_timeseries and 'value' not in fields and not any(isinstance(v, (int, float)) for v in fields.values()):
            error_msg = "No numeric values found in metric data"
            logger.error(f"[DB_ERROR] {error_msg} - origin: {origin_name}, fields: {fields}")
            return {'error': error_msg}
        elif not is_timeseries and not all([origin_name, metric_type_name, value is not None]):
            error_msg = "Missing required metric data fields"
            logger.error(f"[DB_ERROR] {error_msg} - origin: {origin_name}, metric_type: {metric_type_name}, value: {value}")
            return {'error': error_msg}
        
        # Create primary metric record if we have the required fields
        if all([origin_name, metric_type_name, value is not None]):
            # Get or create origin
            origin = get_or_create_origin(session, origin_name)
            
            # Get or create metric type
            metric_type = get_or_create_metric_type(session, metric_type_name)
            
            # Get or create timezone if present in data
            timezone_id = None
            timezone_name = data.get('source_timezone')
            if timezone_name:
                timezone = get_or_create_timezone(session, timezone_name)
                timezone_id = timezone.id
            
            metric = Metric(
                origin_id=origin.id,
                metric_type_id=metric_type.id,
                value=float(value),
                timestamp=timestamp,
                timezone_id=timezone_id,
                additional_metadata=metadata
            )
            
            session.add(metric)
            logger.debug(f"Added primary metric: {metric_type_name}={value} from {origin_name}")
        
        # Save raw data for completeness
        raw_data = RawData(
            measurement='metric' if not is_timeseries else data.get('measurement'),
            data=data,
            received_timestamp=datetime.now(),
            system_timestamp=timestamp
        )
        session.add(raw_data)
        
        session.commit()
        logger.info(f"[DB_OPERATION_END] Successfully saved metric data to database")
        
        # Create response with basic information
        response = {
            'message': 'Metric data saved successfully to database',
            'timestamp': datetime.now().isoformat()
        }
        
        # Only include metric ID if a primary metric was created
        if locals().get('metric'):
            response['id'] = metric.id
            
        return response
        
    except SQLAlchemyError as e:
        session.rollback()
        error_msg = str(e)
        logger.error(f"[DB_ERROR] Database error: {error_msg}")
        return {'error': error_msg}
    except Exception as e:
        session.rollback()
        error_msg = str(e)
        logger.error(f"[DB_ERROR] Error processing metric data: {error_msg}")
        return {'error': error_msg}
    finally:
        session.close()

def get_or_create_origin(session, origin_name):
    """Helper function to get or create a MetricOrigin"""
    if not origin_name:
        origin_name = 'unknown'
        
    origin = session.query(MetricOrigin).filter_by(name=origin_name).first()
    if not origin:
        origin = MetricOrigin(name=origin_name)
        session.add(origin)
        session.flush()  # Flush to get the ID
    return origin

def get_or_create_metric_type(session, metric_type_name):
    """Helper function to get or create a MetricType"""
    if not metric_type_name:
        metric_type_name = 'unknown'
        
    metric_type = session.query(MetricType).filter_by(name=metric_type_name).first()
    if not metric_type:
        metric_type = MetricType(name=metric_type_name)
        session.add(metric_type)
        session.flush()  # Flush to get the ID
    return metric_type

def get_or_create_timezone(session, timezone_name):
    """Helper function to get or create a TimeZoneSource"""
    if not timezone_name:
        timezone_name = 'UTC'
        
    timezone = session.query(TimeZoneSource).filter_by(name=timezone_name).first()
    if not timezone:
        timezone = TimeZoneSource(name=timezone_name)
        session.add(timezone)
        session.flush()  # Flush to get the ID
    return timezone


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
        
        # Get or create timezone if present
        timezone_id = None
        timezone_name = data.get('source_timezone')
        if timezone_name:
            timezone = get_or_create_timezone(session, timezone_name)
            timezone_id = timezone.id
        
        # Always save raw data
        raw_data = RawData(
            measurement=data.get('measurement'),
            data=data,
            received_timestamp=datetime.now(),
            timezone_id=timezone_id
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
        
        # Handle system metrics data if applicable
        if data.get('measurement') == 'system_metrics' and 'fields' in data:
            fields = data.get('fields', {})
            system_timestamp = raw_data.system_timestamp or datetime.now()
            origin_name = data.get('tags', {}).get('host', 'unknown')
            
            # Convert each field to a metric record
            for metric_name, metric_value in fields.items():
                try:
                    # Skip non-numeric values
                    if not isinstance(metric_value, (int, float)):
                        continue
                    
                    # Get or create origin
                    origin = get_or_create_origin(session, origin_name)
                    
                    # Get or create metric type
                    metric_type = get_or_create_metric_type(session, metric_name)
                    
                    metric = Metric(
                        origin_id=origin.id,
                        metric_type_id=metric_type.id,
                        value=float(metric_value),
                        timestamp=system_timestamp,
                        timezone_id=timezone_id,
                        additional_metadata={'measurement': 'system_metrics'}
                    )
                    session.add(metric)
                except Exception as e:
                    logger.warning(f"[DB_METRIC_ERROR] Could not save metric {metric_name}: {str(e)}")
            
            logger.info(f"[DB_SYSTEM_METRICS] Processed system metrics for {origin_name}")
        
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
                    
                    # Get or create players
                    white_player_name = tags.get('white_player')
                    black_player_name = tags.get('black_player')
                    
                    white_player = None
                    black_player = None
                    
                    if white_player_name:
                        white_player = get_or_create_player(
                            session, 
                            white_player_name, 
                            tags.get('white_title'),
                            tags.get('white_rating')
                        )
                    
                    if black_player_name:
                        black_player = get_or_create_player(
                            session, 
                            black_player_name, 
                            tags.get('black_title'),
                            tags.get('black_rating')
                        )
                    
                    logger.debug(f"[DB_GAME_DETAILS] White: {white_player_name} ({tags.get('white_rating')}) | Black: {black_player_name} ({tags.get('black_rating')})")
                    
                    game = Game(
                        game_id=game_id,
                        white_player_id=white_player.id if white_player else None,
                        black_player_id=black_player.id if black_player else None,
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
                
                # Check if FEN position is missing (should be very rare now since we modified the client)
                if not fen_position or not is_valid_fen(fen_position):
                    logger.warning(f"[DB_FEN_MISSING] Missing or invalid FEN for game {game_id}, using DEFAULT_FEN")
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
                    timestamp=datetime.now(),
                    timezone_id=timezone_id
                )
                session.add(move)
        
        # Save data
        session.commit()
        logger.info(f"[DB_OPERATION_END] Successfully saved data to database")
        
        # Create response with basic information
        response = {
            'message': 'Data saved successfully to database',
            'timestamp': datetime.now().isoformat(),
            'id': raw_data.id
        }
            
        return response
        
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

def get_or_create_player(session, name, title=None, rating=None):
    """Helper function to get or create a Player"""
    if not name:
        return None
        
    player = session.query(Player).filter_by(name=name).first()
    if not player:
        player = Player(
            name=name,
            title=title,
            current_rating=rating
        )
        session.add(player)
        session.flush()  # Flush to get the ID
    else:
        # Update fields if they've changed
        if title and player.title != title:
            player.title = title
        if rating and player.current_rating != rating:
            player.current_rating = rating
            
    return player
