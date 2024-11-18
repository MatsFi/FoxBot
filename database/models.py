"""SQLAlchemy models for the database."""
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import Column, Integer, Boolean, String, Text, DateTime, ForeignKey, JSON, Float
from sqlalchemy.orm import relationship, Mapped, mapped_column
from .database import Base

def update_timestamp(mapper, connection, target):
    target.updated_at = datetime.utcnow()

class Player(Base):
    """Model for players in the Local economy."""
    __tablename__ = 'players'

    discord_id = Column(String, primary_key=True)
    username = Column(String, nullable=False)
    balance = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    transactions = relationship("Transaction", back_populates="player", cascade="all, delete-orphan")

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

class Prediction(Base):
    """Model for prediction markets."""
    __tablename__ = 'predictions'

    id: Mapped[int] = mapped_column(primary_key=True)
    question: Mapped[str] = mapped_column(String)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    creator_id: Mapped[str] = mapped_column(String)
    category: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    result: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    # AMM-specific fields
    initial_liquidity: Mapped[int] = mapped_column(Integer, default=100)
    k_constant: Mapped[int] = mapped_column(Integer, default=10000)  # initial_liquidity^2
    
    # Relationships
    liquidity_pools: Mapped[List["LiquidityPool"]] = relationship(
        "LiquidityPool", 
        back_populates="prediction",
        cascade="all, delete-orphan"
    )
    bets: Mapped[List["PredictionBet"]] = relationship(
        "PredictionBet",
        back_populates="prediction",
        cascade="all, delete-orphan"
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if 'end_time' in kwargs and not kwargs['end_time'].tzinfo:
            self.end_time = kwargs['end_time'].replace(tzinfo=timezone.utc)

    @property
    def total_pool(self) -> int:
        """Calculate total amount bet on this prediction."""
        return sum(bet.amount for bet in self.bets)

    def get_option_total(self, option: str) -> int:
        """Calculate total amount bet on a specific option."""
        return sum(bet.amount for bet in self.bets if bet.option == option)

    def get_odds(self) -> dict:
        """Calculate current odds for each option."""
        total_pool = self.total_pool
        odds = {}
        for option in self.options:
            option_total = self.get_option_total(option)
            odds[option] = (total_pool / option_total) if option_total > 0 else float('inf')
        return odds

class LiquidityPool(Base):
    __tablename__ = "liquidity_pools"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"))
    option: Mapped[str] = mapped_column(String)
    shares: Mapped[float] = mapped_column(Float)
    
    # Relationship back to prediction
    prediction: Mapped["Prediction"] = relationship(back_populates="liquidity_pools")

class PredictionBet(Base):
    """Model for individual bets on predictions."""
    __tablename__ = 'prediction_bets'

    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"))
    user_id: Mapped[str] = mapped_column(String)
    option: Mapped[str] = mapped_column(String)
    amount: Mapped[int] = mapped_column(Integer)
    shares: Mapped[float] = mapped_column(Float)
    economy: Mapped[str] = mapped_column(String)  # Tracks which external economy the bet came from
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    
    # Relationship back to prediction
    prediction: Mapped["Prediction"] = relationship(back_populates="bets")

    @property
    def formatted_time(self) -> str:
        """Returns Discord-formatted timestamp"""
        return f"<t:{int(self.created_at.timestamp())}:R>"

    @property
    def user_mention(self) -> str:
        """Returns Discord user mention format"""
        return f"<@{self.user_id}>"

    def calculate_payout(self) -> int:
        """Calculate payout if this bet wins."""
        if not self.prediction.resolved or self.prediction.result != self.option:
            return 0
        
        winning_pool = self.prediction.get_option_total(self.option)
        if winning_pool == 0:
            return 0
            
        total_pool = self.prediction.total_pool
        return int(total_pool * (self.amount / winning_pool))
