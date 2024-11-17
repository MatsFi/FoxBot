from datetime import datetime, timedelta, timezone
from typing import Optional, List, Literal
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
from utils.logging import setup_logger

class PredictionMarket(commands.Cog):
    """Prediction market commands for betting on outcomes."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.service = bot.prediction_market_service
        self.logger = setup_logger(__name__)
        self.logger.info("Prediction Market cog initialized")
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
            # Process options
            options_list = [opt.strip() for opt in options.split(",")]
            if len(options_list) < 2:
                await interaction.followup.send(
                    "You need at least two options for a prediction!", 
                    ephemeral=True
                )
                return

            # Process duration - store in UTC
            try:
                days, hours, minutes = [
                    int(x) if x.strip() else 0 
                    for x in duration.split(",")
                ]
                if days == 0 and hours == 0 and minutes == 0:
                    await interaction.followup.send(
                        "Duration must be greater than 0!", 
                        ephemeral=True
                    )
                    return
                    
                # Calculate end time in UTC
                now_utc = datetime.now(timezone.utc)
                end_time = now_utc + timedelta(
                    days=days,
                    hours=hours,
                    minutes=minutes
                )
            except ValueError:
                await interaction.followup.send(
                    "Invalid duration format! Use: days,hours,minutes (e.g., 1,2,30 or ,,30 or 1,,)", 
                    ephemeral=True
                )
                return

            # Create prediction with UTC timestamp
            prediction = await self.service.create_prediction(
                question=question,
                options=options_list,
                creator_id=str(interaction.user.id),
                end_time=end_time,
                category=category
            )

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
            
            # Format duration display
            duration_parts = []
            if days > 0:
                duration_parts.append(f"{days} day{'s' if days != 1 else ''}")
            if hours > 0:
                duration_parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
            if minutes > 0:
                duration_parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
            duration_str = ", ".join(duration_parts)
            
            # Use Discord's timestamp formatting for local time conversion
            embed.add_field(
                name="Duration",
                value=(
                    f"Ends in {duration_str}\n"
                    f"(<t:{int(end_time.timestamp())}:f> your local time)"
                ),
                inline=True
            )
            if category:
                embed.add_field(name="Category", value=category, inline=True)
            embed.set_footer(text=f"Created by {interaction.user.display_name}")

            await interaction.followup.send(embed=embed)

        except Exception as e:
            self.logger.error(f"Error creating prediction: {e}")
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
            # Get active predictions
            predictions = await self.service.get_active_predictions()
            if not predictions:
                await interaction.followup.send(
                    "No active predictions at the moment.",
                    ephemeral=True
                )
                return

            # Create prediction select menu
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
                    prediction = await self.view.cog.service.get_prediction(int(self.values[0]))
                    
                    class OptionSelect(discord.ui.Select):
                        def __init__(self, prediction: Prediction):
                            self.prediction = prediction
                            super().__init__(
                                placeholder="Select your option...",
                                options=[
                                    discord.SelectOption(label=option, value=option)
                                    for option in prediction.options
                                ]
                            )

                        async def callback(self, interaction: discord.Interaction):
                            class EconomySelect(discord.ui.Select):
                                def __init__(self, prediction: Prediction, selected_option: str):
                                    self.prediction = prediction
                                    self.selected_option = selected_option
                                    options = []
                                    if interaction.user.id in self.view.cog.bot.ffs_users:
                                        options.append(discord.SelectOption(
                                            label="FFS Points",
                                            value="ffs"
                                        ))
                                    if interaction.user.id in self.view.cog.bot.hackathon_users:
                                        options.append(discord.SelectOption(
                                            label="Hackathon Points",
                                            value="hackathon"
                                        ))
                                    super().__init__(
                                        placeholder="Select which points to bet with...",
                                        options=options
                                    )

                                async def callback(self, interaction: discord.Interaction):
                                    class AmountModal(discord.ui.Modal, title="Place Bet"):
                                        def __init__(self, prediction: Prediction, option: str, economy: str):
                                            super().__init__()
                                            self.prediction = prediction
                                            self.selected_option = option
                                            self.economy = economy
                                            self.amount = discord.ui.TextInput(
                                                label=f"Bet Amount ({economy.upper()} Points)",
                                                placeholder="Enter amount...",
                                                required=True
                                            )
                                            self.add_item(self.amount)

                                        async def on_submit(self, interaction: discord.Interaction):
                                            try:
                                                amount = int(self.amount.value)
                                                await self.view.cog.service.place_bet(
                                                    prediction_id=self.prediction.id,
                                                    user_id=str(interaction.user.id),
                                                    option=self.selected_option,
                                                    amount=amount,
                                                    economy=self.economy
                                                )
                                                
                                                await interaction.response.send_message(
                                                    f"Successfully placed bet of {amount:,} "
                                                    f"{self.economy.upper()} points on '{self.selected_option}'",
                                                    ephemeral=True
                                                )
                                            except Exception as e:
                                                await interaction.response.send_message(
                                                    f"Error placing bet: {str(e)}",
                                                    ephemeral=True
                                                )

                                    await interaction.response.send_modal(
                                        AmountModal(self.prediction, self.values[0], self.values[0])
                                    )

                            view = discord.ui.View()
                            economy_select = EconomySelect(prediction, self.values[0])
                            view.add_item(economy_select)
                            view.cog = self.view.cog
                            await interaction.response.send_message(
                                "Select which points to bet with:",
                                view=view,
                                ephemeral=True
                            )

                    view = discord.ui.View()
                    option_select = OptionSelect(prediction)
                    view.add_item(option_select)
                    view.cog = self.view.cog
                    await interaction.response.send_message(
                        f"Select your prediction for: {prediction.question}",
                        view=view,
                        ephemeral=True
                    )

            # Create and send prediction select view
            view = discord.ui.View()
            prediction_select = PredictionSelect(predictions)
            view.add_item(prediction_select)
            view.cog = self
            await interaction.followup.send(
                "Select a prediction to bet on:",
                view=view,
                ephemeral=True
            )

        except Exception as e:
            self.logger.error(f"Error in bet command: {e}")
            await interaction.followup.send(
                "An error occurred while processing your bet.",
                ephemeral=True
            )

    @app_commands.guild_only()
    @app_commands.command(name="predictions", description="List all predictions")
    async def predictions(self, interaction: discord.Interaction):
        """List all predictions."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            predictions = await self.service.get_active_predictions()
            
            if not predictions:
                await interaction.followup.send(
                    "No active predictions at the moment.",
                    ephemeral=True
                )
                return

            embed = discord.Embed(
                title="🎲 Active Predictions",
                color=discord.Color.blue()
            )

            for pred in predictions:
                # Calculate total pool and odds for each option
                total_pool = sum(bet.amount for bet in pred.bets)
                odds = {}
                for option in pred.options:
                    option_total = sum(
                        bet.amount for bet in pred.bets 
                        if bet.option == option
                    )
                    odds[option] = total_pool / option_total if option_total else 0

                # Format options and odds
                options_text = "\n".join(
                    f"• {option}: {odds[option]:.2f}x"
                    for option in pred.options
                )

                embed.add_field(
                    name=pred.question,
                    value=(
                        f"**Options:**\n{options_text}\n"
                        f"**Total Pool:** {total_pool:,} points\n"
                        f"**Ends:** <t:{int(pred.end_time.timestamp())}:R>"
                    ),
                    inline=False
                )

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error listing predictions: {e}")
            await interaction.followup.send(
                "An error occurred while listing predictions.",
                ephemeral=True
            )

    @app_commands.guild_only()
    @app_commands.command(name="resolve", description="Resolve a prediction")
    async def resolve(self, interaction: discord.Interaction):
        """Resolve a prediction."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            predictions = await self.service.get_resolvable_predictions(
                str(interaction.user.id)
            )
            
            if not predictions:
                await interaction.followup.send(
                    "You have no predictions to resolve.",
                    ephemeral=True
                )
                return

            class ResolveSelect(discord.ui.Select):
                def __init__(self, predictions: List[Prediction]):
                    options = [
                        discord.SelectOption(
                            label=f"{p.question[:95]}{'...' if len(p.question) > 95 else ''}",
                            description=f"Created {p.created_at.strftime('%Y-%m-%d %H:%M UTC')}",
                            value=str(p.id)
                        )
                        for p in predictions
                    ]
                    super().__init__(
                        placeholder="Select a prediction to resolve...",
                        options=options
                    )

                async def callback(self, interaction: discord.Interaction):
                    prediction = await self.view.cog.service.get_prediction(
                        int(self.values[0])
                    )
                    
                    class ResultSelect(discord.ui.Select):
                        def __init__(self, options: List[str]):
                            super().__init__(
                                placeholder="Select the winning option...",
                                options=[
                                    discord.SelectOption(label=option, value=option)
                                    for option in options
                                ]
                            )

                        async def callback(self, interaction: discord.Interaction):
                            try:
                                prediction, payouts = await self.view.cog.service.resolve_prediction(
                                    prediction_id=prediction.id,
                                    result=self.values[0],
                                    resolver_id=str(interaction.user.id)
                                )
                                
                                embed = discord.Embed(
                                    title="🎯 Prediction Resolved!",
                                    description=prediction.question,
                                    color=discord.Color.green()
                                )
                                embed.add_field(
                                    name="Winner",
                                    value=prediction.result,
                                    inline=False
                                )
                                
                                if payouts:
                                    payout_text = "\n".join(
                                        f"<@{user_id}>: {amount:,} {economy} points"
                                        for user_id, amount, economy in payouts
                                    )
                                    embed.add_field(
                                        name="Payouts",
                                        value=payout_text,
                                        inline=False
                                    )
                                else:
                                    embed.add_field(
                                        name="Payouts",
                                        value="No winning bets",
                                        inline=False
                                    )
                                
                                await interaction.response.send_message(
                                    embed=embed,
                                    ephemeral=False
                                )
                                
                            except Exception as e:
                                await interaction.response.send_message(
                                    f"Error resolving prediction: {str(e)}",
                                    ephemeral=True
                                )

                    view = discord.ui.View()
                    view.add_item(ResultSelect(prediction.options))
                    view.cog = self.view.cog
                    await interaction.response.send_message(
                        f"Select the winning option for: {prediction.question}",
                        view=view,
                        ephemeral=True
                    )

            view = discord.ui.View()
            view.add_item(ResolveSelect(predictions))
            view.cog = self
            await interaction.followup.send(
                "Select a prediction to resolve:",
                view=view,
                ephemeral=True
            )

        except Exception as e:
            self.logger.error(f"Error resolving prediction: {e}")
            await interaction.followup.send(
                "An error occurred while resolving the prediction.",
                ephemeral=True
            )

async def setup(bot: commands.Bot) -> None:
    """Set up the prediction market cog."""
    logger = setup_logger(__name__)
    logger.info("Setting up Prediction Market cog...")
    await bot.add_cog(PredictionMarket(bot))
    logger.info("Prediction Market cog setup complete") 