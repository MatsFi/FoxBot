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
from config.settings import load_config
from database.database import Database
from sqlalchemy import text
from services.prediction_market_service import PredictionMarketService
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from services.local_points_service import LocalPointsService


class DiscordBot(commands.Bot):
    """Main bot class with core functionality."""

    def __init__(self):
        """Initialize the bot with basic configuration."""
        # Load configuration first
        self.config = load_config()
        
        # Set up intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix=commands.when_mentioned_or(self.config.command_prefix),
            intents=intents,
            help_command=commands.DefaultHelpCommand()
        )
        
        # Initialize database and db_session as None - will be set up in setup_hook
        self.database: Optional[Database] = None
        self.db_session = None  
             
        # Set up logging
        self.logger = logging.getLogger('discord_bot')
        self.logger.setLevel(self.config.logging.level)
        
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
            logging.Formatter(self.config.logging.format)
        )
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(
            logging.Formatter(self.config.logging.format)
        )
        
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

        # Health check attributes
        self.last_heartbeat = None
        self.web_app = web.Application()
        self.web_app.router.add_get("/health", self.health_check)
        self.web_app.router.add_get("/ping", self.ping)
        self.start_timestamp = None

        self.prediction_market_service = None

    async def setup_hook(self):
        """Initialize bot systems."""
        try:
            self.logger.info("Initializing bot systems...")
            self.logger.info(f"Python version: {platform.python_version()}")
            self.logger.info(f"Discord.py version: {discord.__version__}")
            
            # Initialize database
            self.logger.info(f"Connecting to database at {self.config.database.url}")
            self.database = Database(self.config.database.url)
            await self.database.create_all()
            
            # Create engine and session
            engine = create_async_engine(self.config.database.url)
            async_session = sessionmaker(engine, class_=AsyncSession)
            self.db_session = async_session()
            
            # Initialize points_service BEFORE prediction_market_service
            self.points_service = LocalPointsService(self.db_session)
            
            # Now initialize prediction_market_service
            self.prediction_market_service = PredictionMarketService(
                self.db_session,
                self.points_service,
                self.config
            )
            
            # Load cogs in specific order: local_economy must be first
            self.logger.info("Loading cogs...")
            await self.load_extension('cogs.local_economy')  # This sets up transfer_service         
            await self.load_extension('cogs.hackathon_economy')
            await self.load_extension('cogs.ffs_economy')
            await self.load_extension('cogs.prediction_market')
            
            # Sync commands if guild_id is set
            if self.config.guild_id:
                guild = discord.Object(id=int(self.config.guild_id))
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
            else:
                await self.tree.sync()
            
            # Start health check tasks if web server is enabled
            if self.config.web.enabled:
                self.heartbeat.start()
                self.start_web_server.start()
            
            self.start_timestamp = discord.utils.utcnow()
            self.logger.info("Bot initialized successfully")
            
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
        site = web.TCPSite(
            runner,
            host=self.config.web.host,
            port=self.config.web.port
        )
        await site.start()
        self.logger.info(f"Health check server started on {self.config.web.host}:{self.config.web.port}")

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
                    await session.execute(text("SELECT 1"))
                    await session.commit()
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
            if self.config.web.enabled:
                self.heartbeat.cancel()
                self.start_web_server.cancel()
            
            # Close database session first
            if hasattr(self, 'db_session') and self.db_session:
                try:
                    await self.db_session.close()
                    self.logger.info("Database session closed")
                except Exception as e:
                    self.logger.error(f"Error closing database session: {e}")
            
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
            
            # Add null check before stopping prediction market service
            if hasattr(self, 'prediction_market_service') and self.prediction_market_service:
                await self.prediction_market_service.stop()
            
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