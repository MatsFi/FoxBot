"""SQLAlchemy models for the database."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import List, Optional, Dict
from sqlalchemy import ForeignKey, JSON, String, Integer, Float, Boolean
from sqlalchemy.orm import relationship, Mapped, mapped_column
from .database import Base

def utc_now() -> datetime:
    """Helper function to get current UTC datetime."""
    return datetime.now(timezone.utc)

def ensure_utc(dt: datetime) -> datetime:
    """Helper function to ensure datetime is UTC timezone-aware."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

class Player(Base):
    """Model for tracking Discord users who interact with the bot."""
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    discord_id: Mapped[int]  # Discord snowflake ID
    username: Mapped[str]  # For audit/tracking only
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)

    # Relationships
    transactions: Mapped[List["Transaction"]] = relationship(
        back_populates="player",
        primaryjoin="Player.id==Transaction.player_id"
    )

class Transaction(Base):
    """Model for recording token movements between economies."""
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    from_id: Mapped[int]  # Discord snowflake ID
    to_id: Mapped[int]    # Discord snowflake ID
    amount: Mapped[int]
    timestamp: Mapped[datetime] = mapped_column(default=utc_now)

    # Relationship with player
    player: Mapped["Player"] = relationship(back_populates="transactions")

class Prediction(Base):
    """Model for prediction markets."""
    __tablename__ = 'predictions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question: Mapped[str]
    end_time: Mapped[datetime]
    creator_id: Mapped[int]
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    refunded: Mapped[bool] = mapped_column(Boolean, default=False)
    category: Mapped[Optional[str]]
    
    # New fields for liquidity management
    initial_liquidity: Mapped[int] = mapped_column(Integer, default=30000)
    liquidity_pool: Mapped[Dict] = mapped_column(JSON, default=dict)
    k_constant: Mapped[float]
    
    # New fields for voting
    user_votes: Mapped[Dict] = mapped_column(JSON, default=dict)
    votes_per_option: Mapped[Dict] = mapped_column(JSON, default=dict)
    
    # Relationships
    options: Mapped[List["PredictionOption"]] = relationship(
        back_populates="prediction",
        cascade="all, delete-orphan"
    )
    bets: Mapped[List["Bet"]] = relationship(
        back_populates="prediction",
        cascade="all, delete-orphan"
    )

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.k_constant = float(self.initial_liquidity * self.initial_liquidity)
        if hasattr(self, 'options'):
            self.liquidity_pool = {
                opt.text: self.initial_liquidity 
                for opt in self.options
            }
            self.votes_per_option = {
                opt.text: [] 
                for opt in self.options
            }
        self.user_votes = {}

class PredictionOption(Base):
    """Model for prediction market options."""
    __tablename__ = "prediction_options"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prediction_id: Mapped[int] = mapped_column(
        Integer, 
        ForeignKey("predictions.id", ondelete="CASCADE"),
        nullable=False
    )
    text: Mapped[str]
    
    prediction: Mapped[Prediction] = relationship(
        back_populates="options"
    )
    bets: Mapped[List["Bet"]] = relationship(
        back_populates="option",
        cascade="all, delete-orphan"
    )

class Bet(Base):
    """Model for tracking prediction market bets."""
    __tablename__ = "bets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prediction_id: Mapped[int] = mapped_column(
        Integer, 
        ForeignKey("predictions.id", ondelete="CASCADE"),
        nullable=False
    )
    option_id: Mapped[int] = mapped_column(
        Integer, 
        ForeignKey("prediction_options.id", ondelete="CASCADE"),
        nullable=False
    )
    user_id: Mapped[int]
    amount: Mapped[int]
    shares: Mapped[float] = mapped_column(Float, default=0.0)
    economy: Mapped[str]
    
    prediction: Mapped[Prediction] = relationship(
        back_populates="bets"
    )
    option: Mapped[PredictionOption] = relationship(
        back_populates="bets"
    )