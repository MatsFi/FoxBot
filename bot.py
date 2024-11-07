"""Main bot file that handles core functionality and cog loading."""
import logging
import os
import platform
from typing import Dict, Any

import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load environment variables at startup
load_dotenv(override=True)

def setup_logging() -> logging.Logger:
    """Set up logging configuration."""
    logger = logging.getLogger("discord_bot")
    logger.setLevel(logging.INFO)

    # Create console handler with formatting
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter(
            '[%(asctime)s] %(levelname)s: %(message)s',
            '%Y-%m-%d %H:%M:%S'
        )
    )

    # Create file handler with formatting
    file_handler = logging.FileHandler(
        filename="discord.log",
        encoding="utf-8",
        mode="w"
    )
    file_handler.setFormatter(
        logging.Formatter(
            '[%(asctime)s] %(levelname)s: %(message)s',
            '%Y-%m-%d %H:%M:%S'
        )
    )

    # Add both handlers to logger
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger

def load_config() -> Dict[str, Any]:
    """Load configuration from environment variables."""
    required_vars = [
        'TOKEN',
        'API_BASE_URL',
        'API_KEY',
        'REALM_ID',
        'PLAYER_DB_PATH',
        'HACKATHON_API_KEY',
        'HACKATHON_REALM_ID',
    ]
    
    config = {}
    for var in required_vars:
        value = os.getenv(var)
        if not value:
            raise ValueError(f"Missing required environment variable: {var}")
        config[var] = value
        
    return config

class DiscordBot(commands.Bot):
    """Main bot class with core functionality."""

    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize the bot with basic configuration.
        
        Args:
            config: Dictionary containing configuration values
        """

        # Set up intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix=commands.when_mentioned_or('!'),
            intents=intents,
            help_command=commands.DefaultHelpCommand()
        )

        self.config = config
        self.logger = setup_logging()

        # Core cogs to load
        self.core_cogs = [
#            "cogs.predictions", # this is also in cogs/__init__.py which seems redundant
#            "cogs.players",
#            "cogs.points",
            "cogs.drip_economy",
        ]

    async def load_cogs(self) -> None:
        """Load all core cogs."""
        for cog in self.core_cogs:
            try:
                await self.load_extension(cog)
                self.logger.info(f"Loaded extension '{cog}'")
            except Exception as e:
                self.logger.error(f"Failed to load extension {cog}: {str(e)}")
                if cog in ["cogs.drip_economy"]:#"cogs.points", "cogs.players"]:
                    # Critical cogs must load
                    raise

    async def setup_hook(self) -> None:
        """Initialize bot configuration and load cogs.
        
        This is called automatically by discord.py when the bot starts.
        """
        try:
            await self.load_cogs()
            await self.tree.sync()  # Sync slash commands
            
            self.logger.info(f"Logged in as {self.user.name}")
            self.logger.info(f"discord.py API version: {discord.__version__}")
            self.logger.info(f"Python version: {platform.python_version()}")
            self.logger.info(
                f"Running on: {platform.system()} {platform.release()} ({os.name})"
            )
            
        except Exception as e:
            self.logger.error(f"Error in setup: {str(e)}")
            raise

    async def cleanup_cogs(self) -> None:
        """Cleanup all loaded cogs."""
        for cog_name, cog in self.cogs.items():
            try:
                # Look for any cleanup methods
                if hasattr(cog, 'cog_unload'):
                    await cog.cog_unload()
                elif hasattr(cog, 'cleanup'):
                    await cog.cleanup()
            except Exception as e:
                self.logger.error(f"Error cleaning up cog {cog_name}: {str(e)}")

    async def close(self) -> None:
        """Clean up before the bot closes."""
        self.logger.info("Bot is shutting down...")
        await self.cleanup_cogs()
        await super().close()

def main():
    """Entry point for the bot."""
    try:
        # Load config first
        config = load_config()
        
        # Create and run bot
        bot = DiscordBot(config)
        bot.run(config["TOKEN"])
    except Exception as e:
        logger = logging.getLogger("discord_bot")
        logger.error(f"Failed to start bot: {str(e)}")
        raise

if __name__ == "__main__":
    main()