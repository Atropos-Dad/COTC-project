import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

@dataclass
class Player:
    """Represents a player in a chess game."""
    name: str
    rating: int
    title: Optional[str] = None
    remaining_time: Optional[float] = None  # in seconds

@dataclass
class ChessGameMetrics:
    """Represents metrics for a chess game from Lichess TV."""
    timestamp: datetime
    game_id: str
    white_player: Player
    black_player: Player
    new_game: bool = False
    fen_position: Optional[str] = None
    last_move: Optional[str] = None
    game_ended: bool = False
    winner: Optional[str] = None  # 'white', 'black', or None for draw
    end_reason: Optional[str] = None  # 'checkmate', 'time', 'draw', etc.
    white_piece_count: Optional[int] = None
    black_piece_count: Optional[int] = None
    
    def to_timeseries_data(self) -> Dict[str, Any]:
        """Convert to a format suitable for time series DB.
        
        The data is structured in three ways:
        1. For new games: Includes full game metadata and initial position
        2. For moves: Only includes essential state changes
        3. For game endings: Includes outcome information
        """
        try:
            # Common tags for both new games and moves
            tags = {
                "game_id": self.game_id,
                "event_type": "new_game" if self.new_game else "move" if not self.game_ended else "game_end"
            }
            
            # Common fields for both types
            fields = {
                "white_time": self.white_player.remaining_time,
                "black_time": self.black_player.remaining_time
            }
            
            # Add piece counts if available
            if self.white_piece_count is not None:
                fields["white_piece_count"] = self.white_piece_count
            if self.black_piece_count is not None:
                fields["black_piece_count"] = self.black_piece_count
            
            if self.new_game:
                # For new games, include all metadata
                tags.update({
                    "white_player": self.white_player.name,
                    "black_player": self.black_player.name,
                    "white_title": self.white_player.title,
                    "black_title": self.black_player.title,
                    "white_rating": self.white_player.rating,
                    "black_rating": self.black_player.rating
                })
                
                if self.fen_position:
                    fields["fen_position"] = self.fen_position
                    logger.debug("New game FEN position: %s", self.fen_position)
                    
            elif self.game_ended:
                # For game endings, include outcome information
                if self.winner:
                    fields["winner"] = self.winner
                if self.end_reason:
                    fields["end_reason"] = self.end_reason
                logger.info("Game %s ended. Winner: %s, Reason: %s", 
                          self.game_id, self.winner, self.end_reason)
                    
            else:
                # For moves, include only the last move
                if self.last_move:
                    fields["last_move"] = self.last_move
                    logger.debug("Game %s move: %s", self.game_id, self.last_move)
            
            return {
                "measurement": "chess_game",
                "tags": tags,
                "fields": fields,
                "time": int(self.timestamp.timestamp() * 1e9)  # Convert to nanoseconds
            }
        except Exception as e:
            logger.exception("Error converting game metrics to timeseries data")
            raise

@dataclass
class SystemMetrics:
    """Represents system performance metrics."""
    timestamp: datetime
    cpu_percent: float
    memory_percent: float
    disk_usage_percent: float
    network_bytes_sent: int
    network_bytes_recv: int
    process_count: int
    
    def to_timeseries_data(self) -> Dict[str, Any]:
        """Convert to a format suitable for time series DB."""
        try:
            data = {
                "measurement": "system_metrics",
                "time": self.timestamp.isoformat(),
                "fields": {
                    "cpu_percent": self.cpu_percent,
                    "memory_percent": self.memory_percent,
                    "disk_usage_percent": self.disk_usage_percent,
                    "network_bytes_sent": self.network_bytes_sent,
                    "network_bytes_recv": self.network_bytes_recv,
                    "process_count": self.process_count
                }
            }
            logger.debug("System metrics: CPU: %.1f%%, Memory: %.1f%%, Disk: %.1f%%",
                      self.cpu_percent, self.memory_percent, self.disk_usage_percent)
            return data
        except Exception as e:
            logger.exception("Error converting system metrics to timeseries data")
            raise
