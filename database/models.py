"""SQLAlchemy models for the database."""
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
    question: Mapped[str] = mapped_column(String, nullable=False)
    end_time: Mapped[datetime] = mapped_column(nullable=False)
    creator_id: Mapped[int] = mapped_column(Integer, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    refunded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    # New fields for liquidity management
    initial_liquidity: Mapped[int] = mapped_column(Integer, default=30000, nullable=False)
    liquidity_pool: Mapped[Dict] = mapped_column(JSON, default=dict, nullable=False)
    k_constant: Mapped[float] = mapped_column(Float, nullable=False)
    
    # New fields for voting
    user_votes: Mapped[Dict] = mapped_column(JSON, default=dict, nullable=False)
    votes_per_option: Mapped[Dict] = mapped_column(JSON, default=dict, nullable=False)
    
    # Relationships with explicit join conditions and back references
    options: Mapped[List["PredictionOption"]] = relationship(
        back_populates="prediction",
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    bets: Mapped[List["Bet"]] = relationship(
        back_populates="prediction",
        cascade="all, delete-orphan",
        lazy="selectin"
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
    text: Mapped[str] = mapped_column(String, nullable=False)
    
    prediction: Mapped["Prediction"] = relationship(
        back_populates="options",
        lazy="selectin"
    )
    bets: Mapped[List["Bet"]] = relationship(
        back_populates="option",
        cascade="all, delete-orphan",
        lazy="selectin"
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
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    shares: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    economy: Mapped[str] = mapped_column(String, nullable=False)
    
    prediction: Mapped["Prediction"] = relationship(
        back_populates="bets",
        lazy="selectin"
    )
    option: Mapped["PredictionOption"] = relationship(
        back_populates="bets",
        lazy="selectin"
    )