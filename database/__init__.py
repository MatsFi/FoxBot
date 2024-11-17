"""Initialize database package."""
from .database import Base, Database
from .models import Player, Transaction
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

__all__ = [
    'Base',
    'Database',
    'Player',
    'Transaction',
]

async def init_db(database_url: str):
    engine = create_async_engine(
        database_url,
        echo=False,
    )
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    return async_sessionmaker(
        engine,
        expire_on_commit=False,
    )