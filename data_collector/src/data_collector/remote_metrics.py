"""Module for collecting remote metrics from Lichess"""
import logging
import berserk
import os
import asyncio
import socket
from dotenv import load_dotenv
from datetime import datetime
from typing import Optional, AsyncGenerator, Dict, Any, List, Tuple, Literal
from data_collector.models import Player, ChessGameMetrics, MetricsGenerator, GenericMetric

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)

class LichessMetricsCollector(MetricsGenerator):
    def __init__(self, mode: Literal["game", "system", "both"] = "both"):
        """Initialize the Lichess metrics collector.
        
        Args:
            mode: The mode of operation:
                - "game": Only yield chess game metrics
                - "system": Only yield system metrics (piece counts)
                - "both": Yield both types of metrics (default)
        """
        self._current_game_id = None
        self._white_player = None
        self._black_player = None
        self._hostname = socket.gethostname()
        self._mode = mode
        self._last_fen = None
        logger.info(f"Initialized LichessMetricsCollector in {mode} mode")
        
    async def generate_metrics(self) -> AsyncGenerator[dict, None]:
        """Generate metrics from Lichess TV stream.
        
        Yields:
            dict: Metric data in time series format
        """
        logger.info("Starting Lichess TV stream")
        session = berserk.TokenSession(os.getenv('LICHESS_API_TOKEN'))
        client = berserk.Client(session=session)

        tv_feed = client.tv.stream_current_game()
        games_processed = 0
        positions_processed = 0
        
        try:
            while True:  
                loop = asyncio.get_event_loop()
                position = await loop.run_in_executor(None, lambda: next(tv_feed))
                
                data = position['d']
                timestamp = datetime.utcnow()
                
                if position['t'] == 'featured':
                    # Handle end of previous game
                    if self._current_game_id and self._white_player and self._black_player:
                        logger.info("Game ended: %s", self._current_game_id)
                        if self._mode in ["game", "both"]:
                            metrics = await self._end_game(timestamp)
                            yield metrics
                        games_processed += 1
                    
                    # Setup new game
                    logger.info("New game starting")
                    if self._mode in ["game", "both"]:
                        metrics = await self._new_game(data, timestamp)
                        yield metrics
                    else:
                        # Even in system-only mode, we need to set up the game state
                        await self._setup_game_state(data)
                    
                    # Get piece counts from FEN and send as system metrics
                    fen = data.get('fen')
                    if fen and self._mode in ["system", "both"]:
                        white_pieces, black_pieces = fen_to_piece_count(fen)
                        # Yield white piece count metric
                        white_metric = self._create_piece_count_metric("white_pieces", white_pieces, timestamp)
                        yield white_metric.to_timeseries_format()
                        
                        # Yield black piece count metric
                        black_metric = self._create_piece_count_metric("black_pieces", black_pieces, timestamp)
                        yield black_metric.to_timeseries_format()
                    
                elif position['t'] == 'fen':
                    if not all([self._current_game_id, self._white_player, self._black_player]):
                        logger.warning("Received position update without active game")
                        continue
                    
                    if self._mode in ["game", "both"]:
                        metrics = await self._continued_game(data, timestamp)
                        yield metrics
                    else:
                        # Update player times even in system-only mode
                        self._update_player_times(data)
                    
                    # Get piece counts from FEN and send as system metrics
                    fen = data.get('fen')
                    if fen and self._mode in ["system", "both"]:
                        white_pieces, black_pieces = fen_to_piece_count(fen)
                        # Yield white piece count metric
                        white_metric = self._create_piece_count_metric("white_pieces", white_pieces, timestamp)
                        yield white_metric.to_timeseries_format()
                        
                        # Yield black piece count metric
                        black_metric = self._create_piece_count_metric("black_pieces", black_pieces, timestamp)
                        yield black_metric.to_timeseries_format()
                    
                    positions_processed += 1
                    
                    if positions_processed % 100 == 0:
                        logger.debug("Processed %d positions in current game", 
                                   positions_processed)

        except StopIteration:
            logger.warning("TV feed ended, reconnecting...")
            tv_feed = client.tv.stream_current_game()
        except Exception as e:
            logger.exception("Error processing Lichess TV stream")
            raise
        finally:
            logger.info("Metrics generation complete. Games: %d, Positions: %d", 
                       games_processed, positions_processed)

    def _create_piece_count_metric(self, metric_type: str, count: int, timestamp: datetime) -> GenericMetric:
        """Create a GenericMetric for piece count.
        
        Args:
            metric_type: Type of metric (white_pieces or black_pieces)
            count: Number of pieces
            timestamp: Time when the metric was collected
            
        Returns:
            GenericMetric: Metric object for the piece count
        """
        return GenericMetric(
            origin="lichess",
            metric_type=metric_type,
            value=float(count),
            timestamp=timestamp,
            metadata={"game_id": self._current_game_id}
        )

    async def _setup_game_state(self, data: Dict[str, Any]) -> None:
        """Set up the game state without creating metrics.
        
        Args:
            data: Game data from Lichess
        """
        white_data = data['players'][0]
        black_data = data['players'][1]
        
        self._white_player = Player(
            name=white_data['user']['name'],
            rating=white_data['rating'],
            title=white_data['user'].get('title'),
            remaining_time=white_data.get('seconds')
        )
        
        self._black_player = Player(
            name=black_data['user']['name'],
            rating=black_data['rating'],
            title=black_data['user'].get('title'),
            remaining_time=black_data.get('seconds')
        )
        
        self._current_game_id = data['id']
        
        logger.info("Game state set up: %s, White: %s (%d) vs Black: %s (%d)", 
                   self._current_game_id,
                   self._white_player.name, self._white_player.rating,
                   self._black_player.name, self._black_player.rating)

    def _update_player_times(self, data: Dict[str, Any]) -> None:
        """Update player times without creating metrics.
        
        Args:
            data: Game data from Lichess
        """
        self._white_player.remaining_time = data.get('wc')
        self._black_player.remaining_time = data.get('bc')

    async def _end_game(self, timestamp: datetime) -> Dict[str, Any]:
        """Handle an end game"""
        logger.debug("Processing end game: %s", self._current_game_id)
        # For end game, include the most recent FEN position if available
        last_fen = getattr(self, '_last_fen', None)
        metrics = ChessGameMetrics(
            timestamp=timestamp,
            game_id=self._current_game_id,
            white_player=self._white_player,
            black_player=self._black_player,
            game_ended=True,
            end_reason="game_complete",
            fen_position=last_fen
        )
        return metrics.to_timeseries_data()

    async def _new_game(self, data: Dict[str, Any], timestamp: datetime) -> Dict[str, Any]:
        """Handle a new game"""
        # Set up game state
        await self._setup_game_state(data)
        
        fen = data.get('fen')
        # Store the initial FEN position
        if fen:
            self._last_fen = fen
        
        # Get piece counts from FEN
        white_pieces, black_pieces = fen_to_piece_count(fen) if fen else (0, 0)
        
        metrics = ChessGameMetrics(
            timestamp=timestamp,
            game_id=self._current_game_id,
            white_player=self._white_player,
            black_player=self._black_player,
            new_game=True,
            fen_position=fen,
            white_piece_count=white_pieces,
            black_piece_count=black_pieces
        )
        return metrics.to_timeseries_data()
        
    async def _continued_game(self, data: Dict[str, Any], timestamp: datetime) -> Dict[str, Any]:
        """Handle a continued game"""
        # Update player times
        self._update_player_times(data)
        
        # Get piece counts from FEN
        fen = data.get('fen')
        # Store the last FEN position for later use (e.g., in end_game)
        if fen:
            self._last_fen = fen
            
        white_pieces, black_pieces = fen_to_piece_count(fen) if fen else (0, 0)
        
        metrics = ChessGameMetrics(
            timestamp=timestamp,
            game_id=self._current_game_id,
            white_player=self._white_player,
            black_player=self._black_player,
            new_game=False,
            last_move=data.get('lm'),
            fen_position=fen,
            white_piece_count=white_pieces,
            black_piece_count=black_pieces
        )
        return metrics.to_timeseries_data()


def print_raw_lichess_data():
    """Stream and print raw data from Lichess TV without any processing."""
    logger.info("Starting raw Lichess TV data stream")
    session = berserk.TokenSession(os.getenv('LICHESS_API_TOKEN'))
    client = berserk.Client(session=session)

    try:
        tv_feed = client.tv.stream_current_game()
        for position in tv_feed:
            logger.debug("Raw position data: %s", position)
    except Exception as e:
        logger.exception("Error streaming raw Lichess data")
        raise


def fen_to_piece_count(fen: str) -> (int, int):
    """Count white and black pieces in a FEN string."""
    # Get the piece placement part of FEN (before the first space)
    fen = fen.split(' ')[0]
    white_count = sum(c in 'PRNBQK' for c in fen)
    black_count = sum(c in 'prnbqk' for c in fen)
    return white_count, black_count


# convert FEN string to a unicode board
def fen_to_board(fen: str) -> str:
    """Convert FEN to board notation with consistent 8-row output."""
    unicode_pieces = {
        'r': '', 'n': '', 'b': '', 'q': '', 'k': '', 'p': '',
        'R': '', 'N': '', 'B': '', 'Q': '', 'K': '', 'P': ''
    }

    ranks = fen.split(' ')[0].split('/')
    board_lines = []
    
    try:
        for rank in ranks:
            line = ''
            for char in rank:
                if char.isdigit():
                    line += ' ' * int(char)
                else:
                    line += unicode_pieces.get(char, char)
            # Ensure each piece has a space after it for consistent spacing
            board_lines.append(' '.join(line))
        
        board = '\n'.join(board_lines)
        board += '\n' + '=' * 20  # Add separator line
        return board
    except Exception as e:
        logger.error("Error converting FEN to board: %s", fen)
        logger.exception("Conversion error details")
        raise
