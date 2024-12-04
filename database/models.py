"""SQLAlchemy models for the database."""
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import Column, Integer, Boolean, String, Text, DateTime, ForeignKey, JSON
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

    id: Mapped[int] = mapped_column(primary_key=True)
    question: Mapped[str]
    category: Mapped[Optional[str]]
    creator_id: Mapped[int]  # Discord user ID
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    end_time: Mapped[datetime]  # Stored in UTC
    resolved: Mapped[bool] = mapped_column(default=False)
    refunded: Mapped[bool] = mapped_column(default=False)
    result: Mapped[Optional[str]]  # Winning option text
    total_bets: Mapped[int] = mapped_column(default=0)
    
    # Relationships
    options: Mapped[List["PredictionOption"]] = relationship(
        back_populates="prediction",
        cascade="all, delete-orphan"
    )
    bets: Mapped[List["Bet"]] = relationship(
        back_populates="prediction",
        cascade="all, delete-orphan"
    )

    def __init__(self, **kwargs):
        """Ensure end_time is UTC timezone-aware."""
        if 'end_time' in kwargs:
            kwargs['end_time'] = ensure_utc(kwargs['end_time'])
        super().__init__(**kwargs)

class PredictionOption(Base):
    """Model for prediction market options."""
    __tablename__ = "prediction_options"

    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"))
    text: Mapped[str]
    liquidity_pool: Mapped[int] = mapped_column(default=30000)
    k_constant: Mapped[int] = mapped_column(default=900000000)
    total_bet_amount: Mapped[int] = mapped_column(default=0)
    
    # Relationships
    prediction: Mapped["Prediction"] = relationship(back_populates="options")
    bets: Mapped[List["Bet"]] = relationship(back_populates="option")

class Bet(Base):
    """Model for tracking prediction market bets."""
    __tablename__ = "bets"

    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"))
    option_id: Mapped[int] = mapped_column(ForeignKey("prediction_options.id"))
    user_id: Mapped[int]  # Discord snowflake ID
    amount: Mapped[int]
    economy: Mapped[str]  # Track which economy the bet is from
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    
    # Relationships
    prediction: Mapped["Prediction"] = relationship(back_populates="bets")
    option: Mapped["PredictionOption"] = relationship(back_populates="bets")