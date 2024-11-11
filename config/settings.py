from dataclasses import dataclass
from dotenv import load_dotenv
import os

@dataclass
class BotConfig:
    """Immutable configuration settings."""
    token: str
    api_base_url: str
    ffs_api_key: str
    ffs_realm_id: str
    hackathon_api_key: str
    hackathon_realm_id: str
    database_url: str

    @classmethod
    def from_env(cls) -> 'BotConfig':
        """Load configuration from environment variables."""
        load_dotenv(override=True)
        
        required_vars = {
            'token': 'FOX_BOT_TOKEN',
            'api_base_url': 'API_BASE_URL',
            'ffs_api_key': 'FFS_API_KEY',
            'ffs_realm_id': 'FFS_REALM_ID',
            'hackathon_api_key': 'HACKATHON_API_KEY',
            'hackathon_realm_id': 'HACKATHON_REALM_ID',
            'database_url': 'PLAYER_DB_PATH'
        }
        
        config_values = {}
        for key, env_var in required_vars.items():
            value = os.getenv(env_var)
            if not value:
                raise ValueError(f"Missing required environment variable: {env_var}")
            config_values[key] = value
            
        return cls(**config_values)