"""Configuration management for the Discord bot."""
from typing import Optional
import os
from pydantic import BaseModel, Field
from dotenv import load_dotenv

class DatabaseConfig(BaseModel):
    """Database configuration settings."""
    url: str = Field(
        default="sqlite+aiosqlite:///bot.db",
        description="Database connection URL"
    )

class LoggingConfig(BaseModel):
    """Logging configuration settings."""
    level: str = Field(
        default="INFO",
        description="Logging level"
    )
    format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log message format"
    )

class WebConfig(BaseModel):
    """Web server configuration settings."""
    host: str = Field(
        default="0.0.0.0",
        description="Web server host"
    )
    port: int = Field(
        default=8080,
        description="Web server port"
    )
    enabled: bool = Field(
        default=True,
        description="Whether to enable the web server"
    )

class PredictionMarketConfig(BaseModel):
    """Prediction market configuration settings."""
    min_bet: int = Field(
        default=10,
        description="Minimum bet amount"
    )
    max_bet: int = Field(
        default=10000,
        description="Maximum bet amount"
    )
    min_duration_minutes: int = Field(
        default=5,
        description="Minimum prediction duration in minutes"
    )
    max_duration_minutes: int = Field(
        default=20160,  # 14 days
        description="Maximum prediction duration in minutes"
    )
    resolution_window_hours: int = Field(
        default=48,
        description="Window for resolving predictions in hours"
    )
    creator_role_id: Optional[str] = Field(
        default=None,
        description="Role ID required to create predictions"
    )

class BotConfig(BaseModel):
    """Main bot configuration."""
    token: str = Field(
        description="Discord bot token"
    )
    database: DatabaseConfig = Field(
        default_factory=DatabaseConfig,
        description="Database settings"
    )
    logging: LoggingConfig = Field(
        default_factory=LoggingConfig,
        description="Logging settings"
    )
    web: WebConfig = Field(
        default_factory=WebConfig,
        description="Web server settings"
    )
    prediction_market: PredictionMarketConfig = Field(
        default_factory=PredictionMarketConfig,
        description="Prediction market settings"
    )
    command_prefix: str = Field(
        default="!",
        description="Command prefix for text commands"
    )
    app_id: Optional[str] = Field(
        default=None,
        description="Main App ID for slash command registration"
    )
    api_base_url: Optional[str] = Field(
        default=None,
        description="API BASEURL"
    )
    public_key: Optional[str] = Field(
        default=None,
        description="Bot Public key"
    )
    guild_id: Optional[str] = Field(
        default=None,
        description="Main guild ID for slash command registration"
    )
    ffs_realm_id: Optional[str] = Field(
        default=None,
        description="FFS Realm Id"
    )
    ffs_api_key: Optional[str] = Field(
        default=None,
        description="FFS API URL"
    )
    hackathon_realm_id: Optional[str] = Field(
        default=None,
        description="Hackathon Realm Id"
    )
    hackathon_api_key: Optional[str] = Field(
        default=None,
        description="Hackathon API key"
    )

def load_config() -> BotConfig:
    """Load configuration from environment variables."""
    # Load environment variables from .env file
    load_dotenv()
    
    return BotConfig(
        token=os.getenv("TOKEN"),
        database=DatabaseConfig(
            url="sqlite+aiosqlite:///" +os.getenv("PLAYER_DB_PATH")
        ),
        logging=LoggingConfig(
            level=os.getenv("LOG_LEVEL", "INFO"),
            format=os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        ),
        web=WebConfig(
            host=os.getenv("WEB_HOST", "0.0.0.0"),
            port=int(os.getenv("WEB_PORT", "8080")),
            enabled=os.getenv("WEB_ENABLED", "true").lower() == "true"
        ),
        prediction_market=PredictionMarketConfig(
            min_bet=int(os.getenv("PREDICTION_MIN_BET", "10")),
            max_bet=int(os.getenv("PREDICTION_MAX_BET", "10000")),
            min_duration_minutes=int(os.getenv("PREDICTION_MIN_DURATION", "5")),
            max_duration_minutes=int(os.getenv("PREDICTION_MAX_DURATION", "20160")),
            resolution_window_hours=int(os.getenv("PREDICTION_RESOLUTION_WINDOW", "48")),
            creator_role_id=os.getenv("PREDICTION_CREATOR_ROLE_ID")
        ),
        command_prefix=os.getenv("COMMAND_PREFIX", "!"),
        app_id=os.getenv("APP_ID"),
        api_base_url=os.getenv("API_BASE_URL"),
        public_key=os.getenv("PUBLIC_KEY"),
        guild_id=os.getenv("GUILD_ID"),
        ffs_realm_id=os.getenv("FFS_REALM_ID"),
        ffs_api_key=os.getenv("FFS_API_KEY"),
        hackathon_realm_id=os.getenv("HACKATHON_REALM_ID"),
        hackathon_api_key=os.getenv("HACKATHON_API_KEY")
    )