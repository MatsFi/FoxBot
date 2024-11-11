"""Database connection handling."""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
import logging

# Import all models so they're registered with Base
#from .models import Player, Transaction
#from .mixer_models import MixerDraw, MixerTicket, MixerPotEntry 

logger = logging.getLogger(__name__)

class Base(DeclarativeBase):
    """Base class for database models."""
    pass

class Database:
    """Database connection manager."""
    
    def __init__(self, url: str):
        """Initialize database connection.
        
        Args:
            url (str): Database connection URL
        """
        self.engine = create_async_engine(
            url,
            echo=False,  # Set to True for SQL debugging
            pool_pre_ping=True
        )
        self.sessionmaker = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        self.logger = logging.getLogger(__name__)

    async def create_all(self):
        """Create all database tables."""
        try:
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            self.logger.info("Database tables created successfully")
        except Exception as e:
            self.logger.error(f"Error creating database tables: {e}")
            raise

    def session(self) -> AsyncSession:
        """Get a database session.
        
        Returns:
            AsyncSession: Database session
        """
        return self.sessionmaker()

    async def close(self):
        """Close database connections."""
        try:
            await self.engine.dispose()
            self.logger.info("Database connections closed")
        except Exception as e:
            self.logger.error(f"Error closing database connections: {e}")
            raise