import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Dict, Any, List, Protocol, runtime_checkable
import json
import socket

logger = logging.getLogger(__name__)

@runtime_checkable
class MetricsGenerator(Protocol):
    """Protocol for all metrics generators."""
    async def generate_metrics(self):
        """Generate metrics asynchronously.
        
        This method should be an async generator that yields metric data
        in the common metric format.
        """
        ...

@dataclass
class GenericMetric:
    """Standard representation of a metric for all collectors."""
    origin: str                  # Source of the metric (e.g., hostname, 'lichess')
    metric_type: str             # Type of metric (e.g., 'cpu_percent', 'game_state')
    value: float                 # Numeric value
    timestamp: datetime          # When the metric was collected
    metadata: Optional[Dict[str, Any]] = None  # Additional context
    
    def to_timeseries_format(self) -> Dict[str, Any]:
        """Convert to a format suitable for time series DB."""
        fields = {'value': self.value}
        if self.metadata:
            # Add metadata as additional fields if they are numeric types
            for key, value in self.metadata.items():
                if isinstance(value, (int, float, bool)):
                    fields[key] = value
        
        return {
            'measurement': 'system_metrics',
            'tags': {
                'origin': self.origin,
                'metric_type': self.metric_type
            },
            'fields': fields,
            'timestamp': self.timestamp.isoformat()
        }

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
    """Comprehensive system performance metrics."""
    timestamp: datetime
    cpu_count_physical: int
    cpu_count_logical: int
    cpu_percent: float
    memory_total: int
    memory_available: int
    memory_percent: float
    network_bytes_sent: int
    network_bytes_recv: int
    process_count: int
    platform_info: str
    python_version: str
    cpu_temp: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the SystemMetrics instance to a dictionary."""
        return asdict(self)
    
    def to_json(self) -> str:
        """Convert the SystemMetrics instance to a JSON string."""
        return json.dumps(self.to_dict(), default=str)
    
    def to_timeseries_data(self) -> Dict[str, Any]:
        """Convert to a format suitable for time series DB."""
        try:
            data = {
                "measurement": "system_metrics",
                "time": self.timestamp.isoformat(),
                "fields": {
                    "cpu_percent": self.cpu_percent,
                    "memory_percent": self.memory_percent,
                    "network_bytes_sent": self.network_bytes_sent,
                    "network_bytes_recv": self.network_bytes_recv,
                    "process_count": self.process_count
                }
            }
            
            # Add CPU temperature if available
            if self.cpu_temp is not None:
                data["fields"]["cpu_temp"] = self.cpu_temp
                
            logger.debug("System metrics: CPU: %.1f%%, Memory: %.1f%%",
                      self.cpu_percent, self.memory_percent)
            return data
        except Exception as e:
            logger.exception("Error converting system metrics to timeseries data")
            raise
    
    def to_generic_metrics(self) -> List[GenericMetric]:
        """Convert to a list of GenericMetric objects."""
        hostname = socket.gethostname()
        
        # Define basic metrics mapping
        basic_metrics = {
            'cpu_percent': self.cpu_percent,
            'memory_percent': self.memory_percent,
            'process_count': self.process_count,
            'network_bytes_sent': self.network_bytes_sent,
            'network_bytes_recv': self.network_bytes_recv,
            'cpu_temp': self.cpu_temp
        }
        
        # Generate metrics for non-None values
        metrics = [
            GenericMetric(origin=hostname, metric_type=metric_type, value=value, timestamp=self.timestamp)
            for metric_type, value in basic_metrics.items()
            if value is not None
        ]
        
        return metrics
    
    @classmethod
    def from_json(cls, json_str: str) -> 'SystemMetrics':
        """Create a SystemMetrics instance from a JSON string."""
        data = json.loads(json_str)
        return cls(**data)
