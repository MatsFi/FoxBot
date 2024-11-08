import asyncio
from pathlib import Path
import logging
from typing import Optional
import discord
from discord.ext import commands
from config.settings import BotConfig
from database.database import Database
from services.points_service import PointsService

class DiscordBot(commands.Bot):
    def __init__(self):
        # Load configuration first
        self.config = BotConfig.from_env()
        
        # Set up intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix=commands.when_mentioned_or('!'),
            intents=intents,
            help_command=commands.DefaultHelpCommand()
        )
        
        # Initialize as None - will be set up in setup_hook
        self.database: Optional[Database] = None
        self.points_service: Optional[PointsService] = None
        
        # Set up logging
        self.logger = logging.getLogger('discord_bot')
        self.logger.setLevel(logging.INFO)
        
        # Create logs directory
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        # File handler
        file_handler = logging.FileHandler(
            filename=log_dir / "discord.log",
            encoding="utf-8",
            mode="a"  # Append mode instead of write
        )
        file_handler.setFormatter(
            logging.Formatter(
                '[%(asctime)s] %(levelname)s: %(message)s',
                '%Y-%m-%d %H:%M:%S'
            )
        )
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(
            logging.Formatter(
                '[%(asctime)s] %(levelname)s: %(message)s',
                '%Y-%m-%d %H:%M:%S'
            )
        )
        
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

    async def setup_hook(self):
        """Initialize bot systems."""
        try:
            self.logger.info("Initializing bot systems...")
            
            # Initialize database
            self.logger.info(f"Connecting to database at {self.config.database_url}")
            self.database = Database(self.config.database_url)
            await self.database.create_all()
            
            # Initialize services
            self.logger.info("Initializing points service...")
            self.points_service = PointsService(
                database=self.database,
                api_config={
                    'base_url': self.config.api_base_url,
                    'api_key': self.config.api_key,
                    'realm_id': self.config.realm_id
                }
            )
            await self.points_service.initialize()
            
            # Load cogs
            self.logger.info("Loading cogs...")
            await self.load_extension('cogs.economy')
            await self.tree.sync()
            
            self.logger.info(f"Bot initialized successfully")
            self.logger.info(f"Logged in as {self.user.name}")
            self.logger.info(f"discord.py API version: {discord.__version__}")
     
        except Exception as e:
            self.logger.error(f"Error during setup: {str(e)}")
            raise

    async def close(self):
        """Cleanup before shutdown."""
        try:
            if self.points_service:
                await self.points_service.cleanup()
            self.logger.info("Bot is shutting down...")
            await super().close()
        except Exception as e:
            self.logger.error(f"Error during shutdown: {str(e)}")
            raise

def main():
    """Entry point for the bot."""
    bot = DiscordBot()
    
    try:
        asyncio.run(bot.start(bot.config.token))
    except KeyboardInterrupt:
        bot.logger.info("Received keyboard interrupt, shutting down...")
        asyncio.run(bot.close())
    except Exception as e:
        bot.logger.error(f"Fatal error: {str(e)}")
        raise

if __name__ == "__main__":
    main()