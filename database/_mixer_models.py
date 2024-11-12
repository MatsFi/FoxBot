"""Database models for the Mixer/Lottery system."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from .database import Base 

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