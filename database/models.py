"""SQLAlchemy models for the database."""
from datetime import datetime, timezone
from typing import List
from sqlalchemy import Column, Integer, Boolean, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship, Mapped
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

    id: Mapped[int] = Column(Integer, primary_key=True)
    question: Mapped[str] = Column(String, nullable=False)
    options: Mapped[List[str]] = Column(JSON, nullable=False)
    creator_id: Mapped[str] = Column(String, nullable=False)
    category: Mapped[str] = Column(String, nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    end_time: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False)
    resolved: Mapped[bool] = Column(Boolean, default=False)
    refunded: Mapped[bool] = Column(Boolean, default=False)
    result: Mapped[str] = Column(String, nullable=True)
    
    # Relationship to bets
    bets: Mapped[List["PredictionBet"]] = relationship("PredictionBet", back_populates="prediction", cascade="all, delete-orphan")

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

class PredictionBet(Base):
    """Model for individual bets on predictions."""
    __tablename__ = 'prediction_bets'

    id: Mapped[int] = Column(Integer, primary_key=True)
    prediction_id: Mapped[int] = Column(ForeignKey('predictions.id'))
    user_id: Mapped[str] = Column(String, nullable=False)
    option: Mapped[str] = Column(String, nullable=False)
    amount: Mapped[int] = Column(Integer, nullable=False)
    source_economy: Mapped[str] = Column(String, nullable=False)  # Track bet's economy source
    placed_at: Mapped[datetime] = Column(DateTime, default=datetime.utcnow)
    
    # Relationship to prediction
    prediction: Mapped[Prediction] = relationship("Prediction", back_populates="bets")

    def calculate_payout(self) -> int:
        """Calculate payout if this bet wins."""
        if not self.prediction.resolved or self.prediction.result != self.option:
            return 0
        
        winning_pool = self.prediction.get_option_total(self.option)
        if winning_pool == 0:
            return 0
            
        total_pool = self.prediction.total_pool
        return int(total_pool * (self.amount / winning_pool))
