"""
Database models for the data aggregator application.
"""
from sqlalchemy import Column, Integer, String, Float, JSON, DateTime, ForeignKey, Text, Index, Table, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta

Base = declarative_base()


class Player(Base):
    """
    Represents a chess player.
    """
    __tablename__ = 'players'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, index=True)
    title = Column(String(10), nullable=True)
    # We'll track the current rating, which can be updated
    current_rating = Column(Integer, nullable=True)
    
    # Relationships
    white_games = relationship("Game", foreign_keys="Game.white_player_id", back_populates="white_player")
    black_games = relationship("Game", foreign_keys="Game.black_player_id", back_populates="black_player")
    
    def __repr__(self):
        return f"<Player(id={self.id}, name='{self.name}', title='{self.title}')>"


class TimeZoneSource(Base):
    """
    Represents a timezone source to avoid duplication.
    """
    __tablename__ = 'timezone_sources'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, unique=True, index=True)
    
    # Relationships
    moves = relationship("Move", back_populates="timezone")
    raw_data = relationship("RawData", back_populates="timezone")
    metrics = relationship("Metric", back_populates="timezone")
    
    def __repr__(self):
        return f"<TimeZoneSource(id={self.id}, name='{self.name}')>"


class Game(Base):
    """
    Represents a chess game.
    """
    __tablename__ = 'games'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    game_id = Column(String(20), unique=True, nullable=False, index=True)
    white_player_id = Column(Integer, ForeignKey('players.id'), nullable=True)
    black_player_id = Column(Integer, ForeignKey('players.id'), nullable=True)
    start_time = Column(DateTime, nullable=False, default=datetime.now)
    
    # Relationships
    white_player = relationship("Player", foreign_keys=[white_player_id], back_populates="white_games")
    black_player = relationship("Player", foreign_keys=[black_player_id], back_populates="black_games")
    moves = relationship("Move", back_populates="game", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Game(game_id='{self.game_id}', white='{self.white_player.name if self.white_player else None}', black='{self.black_player.name if self.black_player else None}')>"


class Move(Base):
    """
    Represents a move in a chess game.
    """
    __tablename__ = 'moves'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    game_id = Column(String(20), ForeignKey('games.game_id'), nullable=False, index=True)
    last_move = Column(String(10), nullable=True)
    white_time = Column(Integer, nullable=True)  # Remaining time in seconds
    black_time = Column(Integer, nullable=True)  # Remaining time in seconds
    white_piece_count = Column(Integer, nullable=True)
    black_piece_count = Column(Integer, nullable=True)
    fen_position = Column(Text, nullable=True)  # Current board position in FEN notation
    # Non-unique timestamp to be compatible with TimescaleDB hypertables
    timestamp = Column(DateTime(timezone=True), nullable=False, default=datetime.now, index=True)  # Changed to timezone-aware
    timezone_id = Column(Integer, ForeignKey('timezone_sources.id'), nullable=True)
    
    # Relationships
    game = relationship("Game", back_populates="moves")
    timezone = relationship("TimeZoneSource", back_populates="moves")
    
    def __repr__(self):
        return f"<Move(game_id='{self.game_id}', timestamp='{self.timestamp}', last_move='{self.last_move}')>"


class RawData(Base):
    """
    Stores the original JSON data received.
    This keeps a record of all data even if the schema changes.
    """
    __tablename__ = 'raw_data'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    measurement = Column(String(255), nullable=True, index=True)
    data = Column(JSON, nullable=False)
    # Non-unique timestamps to be compatible with TimescaleDB hypertables
    received_timestamp = Column(DateTime(timezone=True), nullable=False, default=datetime.now, index=True)
    system_timestamp = Column(DateTime(timezone=True), nullable=True)  # Original timestamp from the data if available
    timezone_id = Column(Integer, ForeignKey('timezone_sources.id'), nullable=True)
    
    # Add composite index for common query patterns
    __table_args__ = (
        Index('idx_raw_data_measurement_time', 'measurement', 'received_timestamp'),
    )
    
    # Relationships
    timezone = relationship("TimeZoneSource", back_populates="raw_data")
    
    def __repr__(self):
        return f"<RawData(id={self.id}, measurement='{self.measurement}', received_timestamp='{self.received_timestamp}')>"


class MetricType(Base):
    """
    Defines the types of metrics that can be collected.
    """
    __tablename__ = 'metric_types'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True, index=True)
    
    # Relationships
    metrics = relationship("Metric", back_populates="metric_type_rel")
    
    def __repr__(self):
        return f"<MetricType(id={self.id}, name='{self.name}')>"


class MetricOrigin(Base):
    """
    Defines the origins of metrics.
    """
    __tablename__ = 'metric_origins'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True, index=True)
    
    # Relationships
    metrics = relationship("Metric", back_populates="origin_rel")
    
    def __repr__(self):
        return f"<MetricOrigin(id={self.id}, name='{self.name}')>"


class Metric(Base):
    """
    Generic model for storing any type of metric data.
    Normalized to reference separate origin and metric type tables.
    """
    __tablename__ = 'metrics'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    origin_id = Column(Integer, ForeignKey('metric_origins.id'), nullable=False, index=True)
    metric_type_id = Column(Integer, ForeignKey('metric_types.id'), nullable=False, index=True)
    value = Column(Float, nullable=False)  # Actual numeric value of the metric
    timestamp = Column(DateTime(timezone=True), nullable=False, default=datetime.now, index=True)  # When the metric was recorded
    timezone_id = Column(Integer, ForeignKey('timezone_sources.id'), nullable=True)
    additional_metadata = Column(JSON, nullable=True)  # Optional additional context data related to the metric
    
    # Relationships
    origin_rel = relationship("MetricOrigin", back_populates="metrics")
    metric_type_rel = relationship("MetricType", back_populates="metrics")
    timezone = relationship("TimeZoneSource", back_populates="metrics")
    
    # Replace unique constraint with a non-unique composite index for query performance
    __table_args__ = (
        Index('idx_metric_origin_type_time', 'origin_id', 'metric_type_id', 'timestamp'),
    )
    
    def __repr__(self):
        return f"<Metric(id={self.id}, origin='{self.origin_rel.name if self.origin_rel else None}', type='{self.metric_type_rel.name if self.metric_type_rel else None}', value={self.value}, timestamp='{self.timestamp}')>"
