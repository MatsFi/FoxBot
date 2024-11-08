"""Main bot file that handles core functionality and cog loading."""
import asyncio
import logging
import platform
import os
from pathlib import Path
from typing import Optional

import discord
from discord.ext import commands
from config.settings import BotConfig
from database.database import Database

class DiscordBot(commands.Bot):
    """Main bot class with core functionality."""

    def __init__(self):
        """Initialize the bot with basic configuration."""
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
            self.logger.info(f"Python version: {platform.python_version()}")
            self.logger.info(f"Discord.py version: {discord.__version__}")
            
            # Initialize database
            self.logger.info(f"Connecting to database at {self.config.database_url}")
            self.database = Database(self.config.database_url)
            await self.database.create_all()
            
            # Load cogs
            self.logger.info("Loading cogs...")
            await self.load_extension('cogs.economy')
            await self.tree.sync()
            
            self.logger.info(f"Bot initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Error during setup: {str(e)}")
            raise

    async def on_ready(self):
        """Handle the bot's ready event."""
        self.logger.info(f"Logged in as {self.user.name} (ID: {self.user.id})")
        self.logger.info(f"Running on: {platform.system()} {platform.release()} ({os.name})")
        
        # Set custom status
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="for /commands"
            )
        )

    async def close(self):
        """Clean up before the bot closes."""
        try:
            self.logger.info("Bot is shutting down...")
            
            # Cleanup cogs
            for extension in list(self.extensions.keys()):
                try:
                    await self.unload_extension(extension)
                    self.logger.info(f"Unloaded extension {extension}")
                except Exception as e:
                    self.logger.error(f"Error unloading extension {extension}: {e}")
            
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