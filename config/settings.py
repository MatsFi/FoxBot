"""Configuration management for the bot."""
import os
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass
class BotConfig:
    """Bot configuration class."""
    token: str
    database_url: str
    api_base_url: str
    ffs_api_key: str
    ffs_realm_id: str
    hackathon_api_key: str
    hackathon_realm_id: str
    web_port: int

    @classmethod
    def from_env(cls) -> 'BotConfig':
        """Create configuration from environment variables."""
        # Ensure data directory exists
        data_dir = Path("data")
        data_dir.mkdir(exist_ok=True)
        
        # Format SQLite URL for async operation
        database_path = data_dir / "players.db"
        database_url = f"sqlite+aiosqlite:///{database_path}"

        return cls(
            database_url=database_url,
            token=os.getenv('FOX_BOT_TOKEN'),
            api_base_url=os.getenv('API_BASE_URL'),
            ffs_api_key=os.getenv('FFS_API_KEY'),
            ffs_realm_id=os.getenv('FFS_REALM_ID'),
            hackathon_api_key=os.getenv('HACKATHON_API_KEY'),
            hackathon_realm_id=os.getenv('HACKATHON_REALM_ID'),
            web_port=int(os.getenv('WEB_PORT', '8080'))
        )