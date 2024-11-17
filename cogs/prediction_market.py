from datetime import datetime, timedelta
from typing import Optional, List
import discord
from discord import app_commands
from discord.ext import commands
from database.models import Prediction, PredictionBet
from services.prediction_market_service import PredictionMarketService
from utils.exceptions import (
    PredictionMarketError,
    InsufficientPointsError,
    InvalidAmountError
)
from utils.permissions import PredictionMarketPermissions

class PredictionMarket(commands.Cog):
    """Prediction market commands for betting on outcomes."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.service = PredictionMarketService(
            bot.db_session,
            bot.points_service,
            bot.config.prediction_market
        )
        self.permissions = PredictionMarketPermissions(bot)

    async def cog_load(self):
        """Called when the cog is loaded."""
        await self.service.start()

    async def cog_unload(self):
        """Called when the cog is unloaded."""
        await self.service.stop()

    @app_commands.guild_only()
    @app_commands.command(name="create_prediction", description="Create a new prediction market")
    @app_commands.describe(
        question="The question for the prediction",
        duration="Duration format: days,hours,minutes (e.g., 1,2,30 or ,,30 or 1,,)",
        options="Comma-separated list of prediction options",
        category="Category for the prediction (optional)"
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
        await interaction.response.defer(ephemeral=False)
        
        try:
            if not await self.permissions.can_create_prediction(interaction):
                await interaction.response.send_message(
                    "You don't have permission to create predictions.",
                    ephemeral=True
                )
                return

            # Process options
            options_list = [opt.strip() for opt in options.split(",")]
            if len(options_list) < 2:
                await interaction.followup.send(
                    "You need at least two options for a prediction!", 
                    ephemeral=True
                )
                return

            # Process duration
            try:
                days, hours, minutes = [
                    int(x) if x.strip() else 0 
                    for x in duration.split(",")
                ]
                total_minutes = (days * 24 * 60) + (hours * 60) + minutes
                end_time = datetime.utcnow() + timedelta(minutes=total_minutes)
            except ValueError:
                await interaction.followup.send(
                    "Invalid duration format! Use: days,hours,minutes (e.g., 1,2,30 or ,,30 or 1,,)", 
                    ephemeral=True
                )
                return

            # Create prediction
            prediction = await self.service.create_prediction(
                question=question,
                options=options_list,
                creator_id=str(interaction.user.id),
                end_time=end_time,
                category=category
            )

            # Format duration string
            duration_parts = []
            if days > 0:
                duration_parts.append(f"{days} day{'s' if days != 1 else ''}")
            if hours > 0:
                duration_parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
            if minutes > 0:
                duration_parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
            duration_str = ", ".join(duration_parts)

            # Create embed response
            embed = discord.Embed(
                title="🎲 New Prediction Market Created!",
                description=question,
                color=discord.Color.blue()
            )
            embed.add_field(
                name="Options",
                value="\n".join(f"• {opt}" for opt in options_list),
                inline=False
            )
            embed.add_field(
                name="Duration",
                value=f"Ends in {duration_str}\n(<t:{int(end_time.timestamp())}:R>)",
                inline=True
            )
            if category:
                embed.add_field(name="Category", value=category, inline=True)
            embed.set_footer(text=f"Created by {interaction.user.display_name}")

            await interaction.followup.send(embed=embed)

        except PredictionMarketError as e:
            await interaction.followup.send(str(e), ephemeral=True)
        except Exception as e:
            self.bot.logger.error(f"Error creating prediction: {e}")
            await interaction.followup.send(
                "An error occurred while creating the prediction.", 
                ephemeral=True
            )

    @app_commands.guild_only()
    @app_commands.command(name="bet", description="Place a bet on a prediction")
    async def bet(self, interaction: discord.Interaction):
        """Place a bet on a prediction."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            if not await self.permissions.can_bet(interaction):
                await interaction.response.send_message(
                    "You don't have permission to place bets.",
                    ephemeral=True
                )
                return

            # Get active predictions
            predictions = await self.service.get_active_predictions()
            if not predictions:
                await interaction.followup.send(
                    "There are no active predictions to bet on.", 
                    ephemeral=True
                )
                return

            # Create prediction selection view
            class PredictionSelect(discord.ui.Select):
                def __init__(self, predictions: List[Prediction]):
                    options = [
                        discord.SelectOption(
                            label=f"{p.question[:95]}{'...' if len(p.question) > 95 else ''}",
                            description=f"Ends {p.end_time.strftime('%Y-%m-%d %H:%M UTC')}",
                            value=str(p.id)
                        )
                        for p in predictions
                    ]
                    super().__init__(
                        placeholder="Select a prediction to bet on...",
                        options=options
                    )

                async def callback(self, interaction: discord.Interaction):
                    self.view.prediction_id = self.values[0]
                    self.view.prediction = next(p for p in predictions if str(p.id) == self.values[0])
                    # Add option select after prediction is chosen
                    self.view.add_item(OptionSelect(self.view.prediction.options))
                    await interaction.response.edit_message(view=self.view)

            class OptionSelect(discord.ui.Select):
                async def callback(self, interaction: discord.Interaction):
                    option = self.values[0]
                    await self.view.cog.service.place_bet(
                        prediction_id=self.view.prediction_id,
                        user_id=str(interaction.user.id),
                        option=option
                    )
                    await interaction.response.send_message(
                        f"You have placed a bet on the prediction: {self.view.prediction.question[:95]}{'...' if len(self.view.prediction.question) > 95 else ''}",
                        ephemeral=True
                    )

            view = discord.ui.View()
            view.add_item(PredictionSelect(predictions))

            await interaction.followup.send(view=view, ephemeral=True)

        except PredictionMarketError as e:
            await interaction.followup.send(str(e), ephemeral=True)
        except Exception as e:
            self.bot.logger.error(f"Error placing bet: {e}")
            await interaction.followup.send(
                "An error occurred while placing the bet.", 
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(PredictionMarket(bot)) 