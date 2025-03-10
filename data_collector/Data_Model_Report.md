# Data Model Analysis Report

## Overview

This report provides a comprehensive analysis of the data models used throughout the Chess on the Cloud (COTC) project, including the data collection system and data aggregation components. The system consists of two main components:

1. **Data Collector** - Responsible for collecting metrics from various sources (system performance metrics and chess game data) and sending them to the data aggregator.
2. **Data Aggregator** - Receives, processes, and stores the metrics in a database for retrieval and visualization.

## Data Flow Architecture

```
┌─────────────────┐    WebSocket     ┌─────────────────┐       ┌─────────────┐
│  Data Collector │ ───────────────► │ Data Aggregator │ ◄───► │  Database   │
└─────────────────┘                  └─────────────────┘       └─────────────┘
       │                                     │                        │
       ▼                                     ▼                        ▼
┌─────────────────┐                 ┌─────────────────┐      ┌─────────────────┐
│ Metrics Sources │                 │ Web Dashboard   │      │ SQL Tables      │
│ - System Metrics│                 │ - Visualizations│      │ - players       │
│ - Chess Games   │                 │ - Real-time Data│      │ - games         │
└─────────────────┘                 └─────────────────┘      │ - moves         │
                                                             │ - raw_data      │
                                                             │ - metrics       │
                                                             └─────────────────┘
```

## Data Models

### Data Collector Models

The data collector uses Python dataclasses to represent various types of metrics:

#### 1. GenericMetric

A standardized representation for any type of metric:

```python
@dataclass
class GenericMetric:
    origin: str                  # Source of the metric (e.g., hostname, 'lichess')
    metric_type: str             # Type of metric (e.g., 'cpu_percent', 'game_state')
    value: float                 # Numeric value
    timestamp: datetime          # When the metric was collected
    metadata: Optional[Dict[str, Any]] = None  # Additional context
```

#### 2. Player

Represents a chess player in a game:

```python
@dataclass
class Player:
    name: str
    rating: int
    title: Optional[str] = None
    remaining_time: Optional[float] = None  # in seconds
```

#### 3. ChessGameMetrics

Represents metrics for a chess game:

```python
@dataclass
class ChessGameMetrics:
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
```

#### 4. SystemMetrics

Comprehensive system performance metrics:

```python
@dataclass
class SystemMetrics:
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
```

### Data Aggregator Models (SQLAlchemy ORM Models)

The data aggregator uses SQLAlchemy ORM models to represent database tables:

#### 1. Player

```python
class Player(Base):
    __tablename__ = 'players'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, index=True)
    title = Column(String(10), nullable=True)
    current_rating = Column(Integer, nullable=True)
    
    # Relationships
    white_games = relationship("Game", foreign_keys="Game.white_player_id", back_populates="white_player")
    black_games = relationship("Game", foreign_keys="Game.black_player_id", back_populates="black_player")
```

#### 2. TimeZoneSource

```python
class TimeZoneSource(Base):
    __tablename__ = 'timezone_sources'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False, unique=True, index=True)
    
    # Relationships
    moves = relationship("Move", back_populates="timezone")
    raw_data = relationship("RawData", back_populates="timezone")
    metrics = relationship("Metric", back_populates="timezone")
```

#### 3. Game

```python
class Game(Base):
    __tablename__ = 'games'
    
    id = Column(Integer, primary_key=True)
    game_id = Column(String(20), unique=True, nullable=False, index=True)
    white_player_id = Column(Integer, ForeignKey('players.id'), nullable=True)
    black_player_id = Column(Integer, ForeignKey('players.id'), nullable=True)
    start_time = Column(DateTime, nullable=False, default=datetime.now)
    
    # Relationships
    white_player = relationship("Player", foreign_keys=[white_player_id], back_populates="white_games")
    black_player = relationship("Player", foreign_keys=[black_player_id], back_populates="black_games")
    moves = relationship("Move", back_populates="game", cascade="all, delete-orphan")
```

#### 4. Move

```python
class Move(Base):
    __tablename__ = 'moves'
    
    id = Column(Integer, primary_key=True)
    game_id = Column(String(20), ForeignKey('games.game_id'), nullable=False, index=True)
    last_move = Column(String(10), nullable=True)
    white_time = Column(Integer, nullable=True)  # Remaining time in seconds
    black_time = Column(Integer, nullable=True)  # Remaining time in seconds
    white_piece_count = Column(Integer, nullable=True)
    black_piece_count = Column(Integer, nullable=True)
    fen_position = Column(Text, nullable=True)  # Current board position in FEN notation
    timestamp = Column(DateTime(timezone=True), nullable=False, default=datetime.now, index=True)
    timezone_id = Column(Integer, ForeignKey('timezone_sources.id'), nullable=True)
    
    # Relationships
    game = relationship("Game", back_populates="moves")
    timezone = relationship("TimeZoneSource", back_populates="moves")
```

#### 5. RawData

```python
class RawData(Base):
    __tablename__ = 'raw_data'
    
    id = Column(Integer, primary_key=True)
    measurement = Column(String(255), nullable=True, index=True)
    data = Column(JSON, nullable=False)
    received_timestamp = Column(DateTime(timezone=True), nullable=False, default=datetime.now, index=True)
    system_timestamp = Column(DateTime(timezone=True), nullable=True)
    timezone_id = Column(Integer, ForeignKey('timezone_sources.id'), nullable=True)
    
    # Relationships
    timezone = relationship("TimeZoneSource", back_populates="raw_data")
```

#### 6. MetricType

```python
class MetricType(Base):
    __tablename__ = 'metric_types'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True, index=True)
    
    # Relationships
    metrics = relationship("Metric", back_populates="metric_type_rel")
```

#### 7. MetricOrigin

```python
class MetricOrigin(Base):
    __tablename__ = 'metric_origins'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True, index=True)
    
    # Relationships
    metrics = relationship("Metric", back_populates="origin_rel")
```

#### 8. Metric

```python
class Metric(Base):
    __tablename__ = 'metrics'
    
    id = Column(Integer, primary_key=True)
    origin_id = Column(Integer, ForeignKey('metric_origins.id'), nullable=False, index=True)
    metric_type_id = Column(Integer, ForeignKey('metric_types.id'), nullable=False, index=True)
    value = Column(Float, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=datetime.now, index=True)
    timezone_id = Column(Integer, ForeignKey('timezone_sources.id'), nullable=True)
    additional_metadata = Column(JSON, nullable=True)
    
    # Relationships
    origin_rel = relationship("MetricOrigin", back_populates="metrics")
    metric_type_rel = relationship("MetricType", back_populates="metrics")
    timezone = relationship("TimeZoneSource", back_populates="metrics")
```

## Data Transformation Flow

The system follows this flow for data transformation:

1. **Collection**: Data is collected from various sources (system metrics, chess games) using the appropriate collector classes.
2. **Standardization**: Collected data is converted into standardized formats:
   - `GenericMetric` for system metrics 
   - `ChessGameMetrics` for chess game data
3. **Serialization**: Data is serialized to a time-series compatible format with methods like `to_timeseries_data()` or `to_timeseries_format()`
4. **Transmission**: Data is sent to the data aggregator via WebSocket connections
5. **Processing**: The data aggregator processes incoming data and stores it in the appropriate database tables
6. **Storage**: Data is stored in the relational database using the SQLAlchemy ORM models

## Dashboard Communication Model

The system includes a real-time communication feature that allows administrators to send messages from the dashboard to all connected clients. This feature uses a combination of HTTP API endpoints and WebSocket broadcasts.

### Message Flow Architecture

```
┌─────────────────┐    HTTP POST     ┌─────────────────┐    WebSocket    ┌──────────────────┐
│  Web Dashboard  │ ───────────────► │ Data Aggregator │ ───────────────►│ Connected Clients│
└─────────────────┘                  └─────────────────┘                 └──────────────────┘
```

## Key Entity Relationships

### Player Relationships
- Players can participate in multiple games as either white or black
- A game has exactly one white player and one black player
- Players have ratings that can be updated over time

### Game Relationships
- Each game has a unique game_id
- Games contain multiple moves in sequence
- Games reference their white and black players

### Move Relationships
- Moves belong to a specific game
- Moves capture the state of a game at a specific point in time
- Moves include details like piece counts, remaining time, and board positions

### Metrics Relationships
- Metrics have an origin (source) and a type
- Metrics store numerical values with timestamps
- Metrics can include additional metadata in JSON format

## Data Consistency and Integrity

The system ensures data consistency and integrity through:

1. **Foreign Key Constraints**: Ensuring relationships between tables are maintained
2. **Unique Constraints**: Preventing duplicate entries (e.g., game_id is unique)
3. **Nullable Constraints**: Specifying which fields can be null
4. **Raw Data Storage**: Keeping original data in the RawData table for auditability
5. **Timezone Awareness**: Using timezone-aware datetime fields for consistent timestamps

## Conclusion

The data model for the Chess on the Cloud project is well-structured, with clear separation between the data collection and aggregation components. The collector uses flexible dataclasses to represent various metrics, while the aggregator uses SQLAlchemy ORM models to enforce a relational database schema.

This architecture allows for:
- Collection of diverse metrics (system performance, chess games)
- Real-time transmission of data using WebSockets
- Structured storage in a relational database
- Flexible querying and analysis of the stored data

The separation of concerns between collection and aggregation makes the system modular and maintainable, allowing for future extensions and enhancements. 

# Stretch goal
## Dashboard Message Model

Messages sent from the dashboard follow this structure:

```python
{
    "message": str,            # The text content of the message
    "timestamp": str,          # ISO-formatted datetime when message was sent
    "type": "dashboard_message", # Message type identifier
    "user_ip": str             # IP address of the dashboard user (added by server)
}
```

## Communication Flow

1. **Message Input**: The dashboard UI provides an input field ("client-message") and a send button ("send-message-button").

2. **Message Sending Process**:
   - When an administrator clicks the send button, a Dash callback function `send_message_to_clients` is triggered
   - The function validates the message content and creates a payload with message text, timestamp, and type
   - The payload is sent as a POST request to the server endpoint `/api/send_message`

3. **Server Processing**:
   - The server receives the POST request at the `/api/send_message` endpoint
   - It validates the message data and adds the sender's IP address to the payload
   - Using Socket.IO, it broadcasts the message to all clients connected to the `/ws/metrics` WebSocket namespace

4. **Client Reception**:
   - Clients connected to the `/ws/metrics` namespace receive the message as a 'dashboard_message' event
   - Client applications can then display the message to their users

This communication model enables real-time administrative messaging from the central dashboard to all monitoring clients, facilitating system-wide announcements and notifications without requiring database storage of the messages.
