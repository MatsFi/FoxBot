"""SQLAlchemy models for the database."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
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

    # Relationships
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

class MixerDraw(Base):
    """Represents a single mixer drawing."""
    __tablename__ = 'mixer_draws'

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    draw_time = Column(DateTime, nullable=False)
    is_completed = Column(Boolean, default=False)
    
    # Relationships
    tickets = relationship("MixerTicket", back_populates="draw")
    pot_entries = relationship("MixerPotEntry", back_populates="draw")

class MixerTicket(Base):
    """Represents a ticket in the mixer."""
    __tablename__ = 'mixer_tickets'

    id = Column(Integer, primary_key=True)
    draw_id = Column(Integer, ForeignKey('mixer_draws.id'), nullable=False)
    discord_id = Column(String, nullable=False)
    username = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationships
    draw = relationship("MixerDraw", back_populates="tickets")

class MixerPotEntry(Base):
    """Represents an entry in the mixer pot."""
    __tablename__ = 'mixer_pot_entries'

    id = Column(Integer, primary_key=True)
    draw_id = Column(Integer, ForeignKey('mixer_draws.id'), nullable=False)
    discord_id = Column(String, nullable=False)
    username = Column(String, nullable=False)
    token_type = Column(String, nullable=False)  # "FFS", "Hackathon", etc.
    amount = Column(Integer, nullable=False)
    is_donation = Column(Boolean, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationships
    draw = relationship("MixerDraw", back_populates="pot_entries")