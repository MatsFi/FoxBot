"""Main bot file that handles core functionality and cog loading."""
import asyncio
import logging
import platform
import os
from pathlib import Path
from typing import Optional
from aiohttp import web
import discord
from discord.ext import commands, tasks
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

        # Health check attributes
        self.last_heartbeat = None
        self.web_app = web.Application()
        self.web_app.router.add_get("/health", self.health_check)
        self.web_app.router.add_get("/ping", self.ping)
        self.start_timestamp = None

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
            
            # Load cogs in specific order: local_economy must be first
            self.logger.info("Loading cogs...")
            await self.load_extension('cogs.local_economy')  # This sets up transfer_service
            await self.load_extension('cogs.hackathon_economy')
            await self.load_extension('cogs.ffs_economy')
            await self.load_extension('cogs.mixer_economy')
            await self.tree.sync()
            
            # Start health check tasks
            self.heartbeat.start()
            self.start_web_server.start()
            self.start_timestamp = discord.utils.utcnow()
            
            self.logger.info(f"Bot initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Error during setup: {str(e)}")
            raise

    @tasks.loop()
    async def heartbeat(self):
        """Update heartbeat timestamp."""
        self.last_heartbeat = discord.utils.utcnow()
        await asyncio.sleep(30)  # Update every 30 seconds

    @tasks.loop(count=1)
    async def start_web_server(self):
        """Start the web server for health checks."""
        runner = web.AppRunner(self.web_app)
        await runner.setup()
        site = web.TCPSite(runner, host='0.0.0.0', port=self.config.web_port)
        await site.start()
        self.logger.info(f"Health check server started on port {self.config.web_port}")

    async def health_check(self, request: web.Request) -> web.Response:
        """Handle health check requests."""
        try:
            # Basic health checks
            is_ready = self.is_ready()
            latency = self.latency
            uptime = (discord.utils.utcnow() - self.start_timestamp).total_seconds() if self.start_timestamp else 0
            connected_guilds = len(self.guilds)
            
            # Database check
            db_healthy = False
            try:
                async with self.database.session() as session:
                    await session.execute("SELECT 1")
                db_healthy = True
            except Exception as e:
                self.logger.error(f"Database health check failed: {e}")

            health_data = {
                "status": "healthy" if is_ready and db_healthy else "unhealthy",
                "uptime_seconds": uptime,
                "latency_ms": round(latency * 1000, 2),
                "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
                "connected_guilds": connected_guilds,
                "database_healthy": db_healthy,
                "version": "1.0.0",  # Update as needed
            }

            return web.json_response(health_data)
        except Exception as e:
            self.logger.error(f"Health check error: {e}")
            return web.json_response(
                {"status": "error", "message": str(e)},
                status=500
            )

    async def ping(self, request: web.Request) -> web.Response:
        """Simple ping endpoint."""
        return web.Response(text="pong")

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
            
            # Stop tasks
            self.heartbeat.cancel()
            self.start_web_server.cancel()
            
            # Cleanup cogs
            for extension in list(self.extensions.keys()):
                try:
                    await self.unload_extension(extension)
                    self.logger.info(f"Unloaded extension {extension}")
                except Exception as e:
                    self.logger.error(f"Error unloading extension {extension}: {e}")
            
            # Close database connections
            if hasattr(self, 'database') and self.database:
                try:
                    await self.database.close()
                    self.logger.info("Database connections closed")
                except Exception as e:
                    self.logger.error(f"Error closing database: {e}")
            
            # Call parent's close method
            try:
                await super().close()
                self.logger.info("Discord connection closed")
            except Exception as e:
                self.logger.error(f"Error closing Discord connection: {e}")
            
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