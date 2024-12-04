from __future__ import annotations
from typing import Optional, List
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands
import logging

from database.models import Prediction, PredictionOption, utc_now, ensure_utc
from services.prediction_market_service import (
    PredictionMarketService,
    MarketStateError,
    InvalidBetError,
    InsufficientLiquidityError
)
from .views.prediction_market_views import (
    MarketListView,
    BettingView,
    ResolutionView
)

class PredictionMarket(commands.Cog):
    """Prediction market commands and event handlers."""

    def __init__(
        self, 
        bot: commands.Bot,
        service: PredictionMarketService
    ):
        self.bot = bot
        self.service = service
        self.logger = bot.logger.getChild('prediction_market')
        self.active_views = set()

    @app_commands.guild_only()
    @app_commands.command(
        name="create_prediction",
        description="Create a new prediction market"
    )
    @app_commands.describe(
        question="The question for the prediction",
        options="Comma-separated list of prediction options",
        duration="Duration format: days,hours,minutes (e.g., 1,2,30 or ,,30 or 1,,)",
        category="Optional category for the prediction"
    )
    async def create_prediction(
        self,
        interaction: discord.Interaction,
        question: str,
        options: str,
        duration: str,
        category: Optional[str] = None
    ):
        """Create a new prediction market."""
        self.logger.debug("Starting create_prediction command")
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Parse duration
            self.logger.debug("Parsing duration")
            duration_parts = duration.split(',')
            if len(duration_parts) != 3:
                await interaction.followup.send(
                    "Duration must be in format: days,hours,minutes (e.g., 1,2,30 or ,,30 or 1,,)",
                    ephemeral=True
                )
                return
                
            days = int(duration_parts[0]) if duration_parts[0].strip() else 0
            hours = int(duration_parts[1]) if duration_parts[1].strip() else 0
            minutes = int(duration_parts[2]) if duration_parts[2].strip() else 0
            
            total_minutes = (days * 24 * 60) + (hours * 60) + minutes
            if total_minutes <= 0:
                await interaction.followup.send(
                    "Duration must be greater than 0! Please specify days, hours, or minutes.",
                    ephemeral=True
                )
                return

            # Parse options
            self.logger.debug("Parsing options")
            options_list = [opt.strip() for opt in options.split(',')]
            if len(options_list) < 2:
                await interaction.followup.send(
                    "You must provide at least 2 options.",
                    ephemeral=True
                )
                return

            end_time = utc_now() + timedelta(minutes=total_minutes)
            
            success, message, prediction = await self.service.create_prediction(
                question=question,
                options=options_list,
                end_time=end_time,
                creator_id=interaction.user.id,
                category=category
            )

            if success and prediction:
                # Format duration string for display
                duration_parts = []
                if days > 0:
                    duration_parts.append(f"{days} day{'s' if days != 1 else ''}")
                if hours > 0:
                    duration_parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
                if minutes > 0:
                    duration_parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
                duration_str = ", ".join(duration_parts)

                await interaction.followup.send(
                    f"Created prediction: {question}\n"
                    f"Category: {category or 'None'}\n"
                    f"Options: {', '.join(options_list)}\n"
                    f"Duration: {duration_str}\n"
                    f"Ends: {discord.utils.format_dt(end_time, style='R')}"
                )
                
                self.bot.loop.create_task(
                    self.service.schedule_prediction_resolution(prediction)
                )
            else:
                await interaction.followup.send(
                    f"Failed to create prediction market: {message}",
                    ephemeral=True
                )

        except ValueError as e:
            await interaction.followup.send(
                "Invalid duration format. Please use numbers for days, hours, and minutes.",
                ephemeral=True
            )
        except Exception as e:
            self.logger.error(f"Error creating prediction: {e}", exc_info=True)
            await interaction.followup.send(
                "An error occurred while creating the prediction.",
                ephemeral=True
            )

    # ... [rest of the file remains unchanged]

async def setup(bot):
    """Set up the prediction market cog."""
    logger = bot.logger.getChild('prediction_market')
    logger.info("Setting up Prediction Market cog...")
    service = PredictionMarketService.from_bot(bot)
    await bot.add_cog(PredictionMarket(bot, service))
    logger.info("Prediction Market cog setup complete")
