"""SQLAlchemy models for the database."""
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import Column, Integer, Boolean, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship, Mapped, mapped_column
from .database import Base

def update_timestamp(mapper, connection, target):
    target.updated_at = datetime.utcnow()

class Player(Base):
    """Model for tracking Discord users who interact with the bot."""
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    discord_id: Mapped[int]  # Discord snowflake ID
    username: Mapped[str]  # For audit/tracking only
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))

    # Relationships
    transactions: Mapped[List["Transaction"]] = relationship(
        back_populates="player",
        primaryjoin="Player.id==Transaction.player_id"
    )

class Transaction(Base):
    """Model for recording token movements between economies."""
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))  # Added this
    from_id: Mapped[int]  # Discord snowflake ID
    to_id: Mapped[int]    # Discord snowflake ID
    amount: Mapped[int]
    timestamp: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))

    # Relationship with player
    player: Mapped["Player"] = relationship(back_populates="transactions")

class Prediction(Base):
    """Model for prediction markets."""
    __tablename__ = 'predictions'

    id: Mapped[int] = mapped_column(primary_key=True)
    question: Mapped[str]
    category: Mapped[Optional[str]]
    creator_id: Mapped[int]  # Discord user ID
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    end_time: Mapped[datetime]  # When betting period ends
    resolved: Mapped[bool] = mapped_column(default=False)
    refunded: Mapped[bool] = mapped_column(default=False)
    result: Mapped[Optional[str]]  # Winning option text
    total_bets: Mapped[int] = mapped_column(default=0)
    
    options: Mapped[List["PredictionOption"]] = relationship(back_populates="prediction", cascade="all, delete-orphan")
    bets: Mapped[List["Bet"]] = relationship(back_populates="prediction", cascade="all, delete-orphan")

class PredictionOption(Base):
    """Model for prediction market options."""
    __tablename__ = "prediction_options"

    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"))
    text: Mapped[str]
    liquidity_pool: Mapped[int] = mapped_column(default=100)
    
    # Relationships
    prediction: Mapped["Prediction"] = relationship(back_populates="options")
    bets: Mapped[List["Bet"]] = relationship(back_populates="option")  # Changed from 'options'

class Bet(Base):
    """Model for tracking prediction market bets."""
    __tablename__ = "bets"

    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"))
    option_id: Mapped[int] = mapped_column(ForeignKey("prediction_options.id"))
    user_id: Mapped[int]  # Discord snowflake ID
    amount: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    
    # Relationships
    prediction: Mapped["Prediction"] = relationship(back_populates="bets")
    option: Mapped["PredictionOption"] = relationship(back_populates="bets")  # Changed from 'option'