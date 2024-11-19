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
from utils.logging import setup_logger

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
             
        # Set up logging with both console and file output
        self.logger = setup_logger('discord_bot', 'discord.log')
        
        # Health check attributes
        self.last_heartbeat = None
        self.web_app = web.Application()
        self.web_app.router.add_get("/health", self.health_check)
        self.web_app.router.add_get("/ping", self.ping)
        self.start_timestamp = None

        self.prediction_market_service = None

        # Define cog load order
        self.cog_load_order = [
            'cogs.local_economy',      # 1. Starts first, initializes transfer service
            'cogs.ffs_economy',
            'cogs.hackathon_economy',  # 2. Registers with transfer service
            'cogs.prediction_market'   # 3. Can now use transfer service and economies
                ]

    async def setup_hook(self):
        """Initialize bot systems."""
        try:
            self.logger.info("Initializing bot systems...")
            self.logger.info(f"Python version: {platform.python_version()}")
            self.logger.info(f"Discord.py version: {discord.__version__}")
            
            # Set start timestamp
            self.start_timestamp = discord.utils.utcnow()
            
            # Start health check server first
            try:
                await self.start_web_server()
                self.heartbeat.start()
                self.logger.info("Health check system initialized")
            except Exception as e:
                self.logger.error(f"Failed to start health check server: {e}")
                # Continue with bot startup even if health check fails
            
            # Initialize database
            self.logger.info(f"Connecting to database at {self.config.database.url}")
            self.database = Database(self.config.database.url)
            await self.database.create_all()
            
            # Get session factory
            self.db_session = self.database.session
            
            # Initialize local points service first
            self.logger.info("Initializing local points service...")
            self.points_service = LocalPointsService(self.db_session)
            
            # Load cogs FIRST - this sets up transfer service
            self.logger.info("Loading cogs in order...")
            for cog_name in self.cog_load_order:
                try:
                    await self.load_extension(cog_name)
                    self.logger.info(f"Loaded {cog_name}")
                except Exception as e:
                    self.logger.error(f"Failed to load {cog_name}: {e}")
                    raise
            
            # Debug: Log available economies
            if hasattr(self, 'transfer_service'):
                economies = list(self.transfer_service._external_services.keys())
                self.logger.info(f"Available external economies after setup: {economies}")
            else:
                self.logger.warning("Transfer service not initialized!")

            # THEN initialize prediction market service
            self.logger.info("Initializing prediction market service...")
            self.prediction_market_service = PredictionMarketService.from_bot(self)
            await self.prediction_market_service.start()

            # Sync commands with Discord
            self.logger.info("Syncing application commands...")
            await self.tree.sync()
            self.logger.info("Application commands synced")

        except Exception as e:
            self.logger.error(f"Error during setup: {e}")
            raise

    @tasks.loop(seconds=30)
    async def heartbeat(self):
        """Update heartbeat timestamp."""
        try:
            self.last_heartbeat = discord.utils.utcnow()
            self.logger.debug(f"Heartbeat updated at {self.last_heartbeat}")
        except Exception as e:
            self.logger.error(f"Error in heartbeat task: {e}")

    @tasks.loop(count=1)
    async def start_web_server(self):
        """Start the web server for health checks."""
        try:
            runner = web.AppRunner(self.web_app)
            await runner.setup()
            site = web.TCPSite(
                runner,
                host=self.config.web.host,
                port=self.config.web.port
            )
            await site.start()
            self.logger.info(
                f"Health check server started on "
                f"http://{self.config.web.host}:{self.config.web.port}/health"
            )
            # Store runner for cleanup
            self._web_runner = runner
        except Exception as e:
            self.logger.error(f"Failed to start web server: {e}")
            raise

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
                "version": "1.0.0"  # Update as needed
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
        """Close the bot and cleanup resources."""
        try:
            self.logger.info("Starting bot shutdown sequence...")

            # Stop tasks first
            if self.heartbeat.is_running():
                self.heartbeat.cancel()
            
            # Stop web server if it exists
            if hasattr(self, '_web_runner'):
                self.logger.info("Stopping health check server...")
                await self._web_runner.cleanup()
                self.logger.info("Health check server stopped")

            # 1. Unload cogs first (they might need database access during cleanup)
            self.logger.info("Unloading cogs...")
            for cog in reversed(self.cog_load_order):
                try:
                    await self.unload_extension(cog)
                    self.logger.info(f"Unloaded cog: {cog}")
                except Exception as e:
                    self.logger.error(f"Failed to unload cog {cog}: {e}")
            self.logger.info("All cogs unloaded")

            # 2. Stop services that depend on the database
            if hasattr(self, 'prediction_market_service'):
                self.logger.info("Stopping prediction market service...")
                await self.prediction_market_service.stop()
                self.logger.info("Prediction market service stopped")

            # 3. Clean up database sessions
            if hasattr(self, 'db_session'):
                self.logger.info("Cleaning up database sessions...")
                self.db_session = None
                self.logger.info("Database sessions cleaned up")

            # 4. Close database connection
            if hasattr(self, 'database'):
                self.logger.info("Closing database connection...")
                await self.database.close()
                self.logger.info("Database connection closed")

            # 5. Finally, close Discord connection
            self.logger.info("Closing Discord connection...")
            await super().close()
            self.logger.info("Discord connection closed")
            
            self.logger.info("Shutdown complete")
            
        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}")
            raise

def main():
    """Main entry point for the bot."""
    bot = DiscordBot()
    
    try:
        asyncio.run(bot.start(bot.config.token))
    except KeyboardInterrupt:
        bot.logger.info("Received keyboard interrupt, shutting down...")
        asyncio.run(bot.close())
    except Exception as e:
        bot.logger.error(f"Fatal error: {e}")
        raise

if __name__ == "__main__":
    main()