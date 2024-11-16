"""Database connection handling."""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
import logging 

logger = logging.getLogger(__name__)

class Base(DeclarativeBase):
    """Base class for all database models."""
    pass

class Database:
    """Database connection and session management."""
    
    def __init__(self, database_url: str):
        """Initialize database connection.
        
        Args:
            database_url (str): Database connection URL
        """
        self.engine = create_async_engine(database_url)
        self.async_session = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        self.logger = logging.getLogger(__name__)

    @property
    def session(self):
        """Get a session factory for creating new database sessions."""
        return self.async_session

    async def create_all(self):
        """Create all database tables."""
        try:
            # Import all models to ensure they're registered with Base
            from .models import (
                Player,  # existing model
                Prediction,  # new model
                PredictionBet,  # new model
            )
            
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            self.logger.info("Database tables created successfully")
        except Exception as e:
            self.logger.error(f"Error creating database tables: {e}")
            raise

    async def close(self):
        """Close database connection."""
        await self.engine.dispose()