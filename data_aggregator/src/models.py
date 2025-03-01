"""
Database models for the data aggregator application.
"""
from sqlalchemy import Column, Integer, String, Float, JSON, DateTime, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()


class Game(Base):
    """
    Represents a chess game.
    """
    __tablename__ = 'games'
    
    id = Column(Integer, primary_key=True)
    game_id = Column(String(20), unique=True, nullable=False, index=True)
    white_player = Column(String(255), nullable=True)
    black_player = Column(String(255), nullable=True)
    white_title = Column(String(10), nullable=True)
    black_title = Column(String(10), nullable=True)
    white_rating = Column(Integer, nullable=True)
    black_rating = Column(Integer, nullable=True)
    start_time = Column(DateTime, nullable=False, default=datetime.now)
    
    # Relationship to moves
    moves = relationship("Move", back_populates="game", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Game(game_id='{self.game_id}', white='{self.white_player}', black='{self.black_player}')>"


class Move(Base):
    """
    Represents a move in a chess game.
    """
    __tablename__ = 'moves'
    
    id = Column(Integer, primary_key=True)
    game_id = Column(String(20), ForeignKey('games.game_id'), nullable=False, index=True)
    last_move = Column(String(10), nullable=True)
    white_time = Column(Integer, nullable=True)  # Remaining time in seconds
    black_time = Column(Integer, nullable=True)  # Remaining time in seconds
    white_piece_count = Column(Integer, nullable=True)
    black_piece_count = Column(Integer, nullable=True)
    fen_position = Column(Text, nullable=True)  # Current board position in FEN notation
    timestamp = Column(DateTime, nullable=False, default=datetime.now, index=True)
    
    # Relationship to game
    game = relationship("Game", back_populates="moves")
    
    def __repr__(self):
        return f"<Move(game_id='{self.game_id}', last_move='{self.last_move}', timestamp='{self.timestamp}')>"


class RawData(Base):
    """
    Stores the original JSON data received.
    This keeps a record of all data even if the schema changes.
    """
    __tablename__ = 'raw_data'
    
    id = Column(Integer, primary_key=True)
    measurement = Column(String(255), nullable=True, index=True)
    data = Column(JSON, nullable=False)
    received_timestamp = Column(DateTime, nullable=False, default=datetime.now, index=True)
    system_timestamp = Column(DateTime, nullable=True)  # Original timestamp from the data if available
    
    def __repr__(self):
        return f"<RawData(id={self.id}, measurement='{self.measurement}', received_at='{self.received_timestamp}')>"
