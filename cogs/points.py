"""Points system cog for managing user points and transactions."""
from discord.ext import commands
import discord
from discord import app_commands
from typing import Optional

# Import PointsManager from models
from models.points_manager import PointsManager

class Points(commands.Cog):
    """Points management and transaction commands."""

    def __init__(self, bot: commands.Bot):
        """Initialize the Points cog.
        
        Args:
            bot: The bot instance
        """
        self.bot = bot
        self.points_manager = PointsManager(
            base_url=bot.config['API_BASE_URL'],
            api_key=bot.config['API_KEY'],
            realm_id=bot.config['REALM_ID'],
            hackathon_api_key=bot.config['HACKATHON_API_KEY'],
            hackathon_realm_id=bot.config['HACKATHON_REALM_ID'],
            db_path = bot.config["PLAYER_DB_PATH"],
        )

    async def cog_load(self) -> None:
        """Initialize the points manager when cog is loaded."""
        #await self.points_manager.initialize()

    async def cog_unload(self) -> None:
        """Cleanup the points manager when cog is unloaded."""
        #await self.points_manager.cleanup()

  
async def setup(bot: commands.Bot) -> None:
    """Setup the Points cog."""
    await bot.add_cog(Points(bot))