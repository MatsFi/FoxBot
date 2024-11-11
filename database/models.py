"""SQLAlchemy models for the database."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from .database import Base

class Player(Base):
    """Model for players in the Local economy."""
    __tablename__ = 'players'

    discord_id = Column(String, primary_key=True)
    username = Column(String, nullable=False)
    balance = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship with transactions
    transactions = relationship("Transaction", back_populates="player")

class Transaction(Base):
    """Model for recording point transactions."""
    __tablename__ = 'transactions'

    id = Column(Integer, primary_key=True)
    player_id = Column(String, ForeignKey('players.discord_id'), nullable=False)
    amount = Column(Integer, nullable=False)
    description = Column(Text, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationship with player
    player = relationship("Player", back_populates="transactions")