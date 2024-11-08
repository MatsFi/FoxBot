import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from contextlib import asynccontextmanager

Base = declarative_base()

class Database:
    def __init__(self, database_url: str):
        """Initialize database connection.
        
        Args:
            database_url: Path to the SQLite database file
        """
        # Ensure the database directory exists
        db_path = Path(database_url)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Convert to absolute path and create sqlite URL
        db_url = f"sqlite+aiosqlite:///{db_path.absolute()}"
        
        self._engine = create_async_engine(
            db_url,
            echo=False,  # Set to True for SQL query logging
            connect_args={"check_same_thread": False}
        )
        
        self._session_factory = sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False
        )

    async def create_all(self):
        """Create all database tables."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    @asynccontextmanager
    async def session(self):
        """Provide a transactional scope around a series of operations."""
        session: AsyncSession = self._session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

# config/settings.py
from dataclasses import dataclass
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv
import os

@dataclass
class BotConfig:
    """Immutable configuration settings."""
    token: str
    api_base_url: str
    api_key: str
    realm_id: str
    hackathon_api_key: str
    hackathon_realm_id: str
    database_url: str

    @classmethod
    def from_env(cls) -> 'BotConfig':
        """Load configuration from environment variables."""
        load_dotenv(override=True)
        
        # Get the project root directory
        project_root = Path(__file__).parent.parent
        
        # Create data directory if it doesn't exist
        data_dir = project_root / "data"
        data_dir.mkdir(exist_ok=True)
        
        # Default database path
        default_db_path = str(data_dir / "bot.db")
        
        required_vars = {
            'token': 'TOKEN',
            'api_base_url': 'API_BASE_URL',
            'api_key': 'API_KEY',
            'realm_id': 'REALM_ID',
            'hackathon_api_key': 'HACKATHON_API_KEY',
            'hackathon_realm_id': 'HACKATHON_REALM_ID',
            'database_url': ('PLAYER_DB_PATH', default_db_path)
        }
        
        config_values = {}
        for key, env_var in required_vars.items():
            # Handle tuple case for default values
            if isinstance(env_var, tuple):
                env_var, default = env_var
                value = os.getenv(env_var, default)
            else:
                value = os.getenv(env_var)
                
            if not value:
                raise ValueError(f"Missing required environment variable: {env_var}")
            config_values[key] = value
            
        return cls(**config_values)