from datetime import datetime, timedelta, timezone
from typing import Optional, List, Literal, Callable
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
import logging
import math

# TODO: Consider adding configuration values for:
# - Minimum bet amount
# - Maximum bet amount
# - Betting timeframe restrictions
# - Economy-specific limits

class BetAmountModal(discord.ui.Modal, title="Place Your Bet"):
    def __init__(self, cog, prediction: Prediction, option: str, economy: str):
        super().__init__()
        self.cog = cog
        self.prediction = prediction
        self.selected_option = option
        self.economy = economy
        self.logger = logging.getLogger(__name__)
        
        # Update min/max bet limits
        self.min_bet = 1
        self.max_bet = 500
        
        self.amount = discord.ui.TextInput(
            label="Bet Amount",
            placeholder=f"Enter amount between {self.min_bet:,} and {self.max_bet:,}",
            min_length=1,
            max_length=10,
            required=True
        )
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle the modal submission."""
        try:
            # Validate amount
            amount = int(self.amount.value)
            if amount < self.min_bet or amount > self.max_bet:
                raise ValueError(
                    f"Bet amount must be between {self.min_bet:,} and {self.max_bet:,}"
                )

            # Place the bet
            await self.cog.service.place_bet(
                prediction_id=self.prediction.id,
                user_id=str(interaction.user.id),
                option=self.selected_option,
                amount=amount,
                economy=self.economy
            )
            
            await interaction.response.send_message(
                f"✅ Successfully placed bet of {amount:,} {self.economy.upper()} points "
                f"on '{self.selected_option}' for prediction:\n"
                f"'{self.prediction.question}'",
                ephemeral=True
            )
            
        except ValueError as e:
            await interaction.response.send_message(
                f"❌ Invalid bet amount: {str(e)}",
                ephemeral=True
            )
        except InsufficientPointsError:
            await interaction.response.send_message(
                "❌ You don't have enough points for this bet!",
                ephemeral=True
            )
        except Exception as e:
            self.logger.error(f"Error placing bet: {e}")
            await interaction.response.send_message(
                "❌ An error occurred while placing your bet.",
                ephemeral=True
            )

class BaseMarketView(discord.ui.View):
    """Base view for prediction market interactions."""
    def __init__(self, cog, timeout=300):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.logger = logging.getLogger(__name__)

    async def handle_interaction(self, interaction: discord.Interaction, action: Callable):
        """Generic interaction handler with error handling."""
        try:
            self.logger.info(f"Starting interaction handler for {interaction.command}")
            self.logger.debug(f"Interaction type: {interaction.type}")
            self.logger.debug(f"Interaction data: {interaction.data}")
            
            # Try to defer first
            try:
                self.logger.debug("Attempting to defer interaction")
                await interaction.response.defer(ephemeral=True)
                self.logger.debug("Successfully deferred interaction")
            except Exception as defer_error:
                self.logger.warning(f"Could not defer interaction: {defer_error}")
                # If we can't defer, the interaction might already be responded to
                pass

            # Execute the action
            self.logger.debug("Executing interaction action")
            await action()
            
            # Update the view
            self.logger.debug("Updating message with new view state")
            if interaction.message:
                try:
                    await interaction.message.edit(view=self)
                    self.logger.debug("Successfully updated message")
                except discord.errors.InteractionResponded:
                    self.logger.debug("Using followup to update message")
                    await interaction.followup.edit_message('@original', view=self)
                
        except Exception as e:
            self.logger.error(f"Error in interaction handler: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ An error occurred. Please try again.",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "❌ An error occurred. Please try again.",
                        ephemeral=True
                    )
            except Exception as notify_error:
                self.logger.error(f"Failed to send error message: {notify_error}")

    async def update_message(self, interaction: discord.Interaction, **kwargs):
        """Update the message with new content/embed."""
        try:
            if interaction.message:
                await interaction.message.edit(**kwargs)
        except Exception as e:
            self.logger.error(f"Error updating message: {e}")
            await interaction.followup.send(
                "❌ Failed to update display.",
                ephemeral=True
            )

class ResolutionView(discord.ui.View):
    def __init__(self, cog, predictions: List[Prediction]):
        super().__init__(timeout=300)
        self.cog = cog
        self.predictions = {str(p.id): p for p in predictions}
        self.selected_prediction: Optional[Prediction] = None
        self.selected_result: Optional[str] = None
        self.logger = logging.getLogger(__name__)
        
        self.logger.info("Initializing ResolutionView")
        self.setup_view()

    def setup_view(self):
        """Set up all view components."""
        # Prediction Select
        self.prediction_select = discord.ui.Select(
            placeholder="Select a prediction to resolve...",
            options=[
                discord.SelectOption(
                    label=f"ID {p_id} | {len(p.bets)} bets | {p.total_pool:,} points",
                    description=f"Q: {p.question[:50]}..." if len(p.question) > 50 else f"Q: {p.question}",
                    value=p_id
                )
                for p_id, p in self.predictions.items()
            ],
            row=0,
            custom_id="prediction_select"
        )
        self.prediction_select.callback = self.on_prediction_select
        self.add_item(self.prediction_select)

        # Result Select (initially disabled)
        self.result_select = discord.ui.Select(
            placeholder="First select a prediction...",
            options=[
                discord.SelectOption(
                    label="Select prediction first",
                    value="placeholder"
                )
            ],
            disabled=True,
            row=1,
            custom_id="result_select"
        )
        self.result_select.callback = self.on_result_select
        self.add_item(self.result_select)

        # Resolve Button (initially disabled)
        self.resolve_button = discord.ui.Button(
            label="Resolve Prediction",
            style=discord.ButtonStyle.primary,
            disabled=True,
            row=2,
            custom_id="resolve_button"
        )
        self.resolve_button.callback = self.on_resolve_click
        self.add_item(self.resolve_button)

    async def on_prediction_select(self, interaction: discord.Interaction):
        """Handle prediction selection."""
        self.logger.info(f"Prediction select interaction received")
        try:
            # Get the selected prediction
            pred_id = interaction.data['values'][0]
            self.selected_prediction = self.predictions[pred_id]
            
            # Update prediction select to show selected value
            for option in self.prediction_select.options:
                option.default = (option.value == pred_id)
            
            # Update result select
            self.result_select.disabled = False
            self.result_select.placeholder = "Select winning option..."
            self.result_select.options = [
                discord.SelectOption(
                    label=option,
                    value=option,
                    description=f"Option for: {self.selected_prediction.question[:50]}..."
                )
                for option in self.selected_prediction.options
            ]
            
            # Update the message
            await interaction.response.edit_message(view=self)
            
        except Exception as e:
            self.logger.error(f"Error in prediction selection: {e}", exc_info=True)
            await interaction.response.send_message("An error occurred. Please try again.", ephemeral=True)

    async def on_result_select(self, interaction: discord.Interaction):
        """Handle result selection."""
        self.logger.info(f"Result select interaction received")
        try:
            selected_value = interaction.data['values'][0]
            self.selected_result = selected_value
            
            # Update result select to show selected value
            for option in self.result_select.options:
                option.default = (option.value == selected_value)
            
            self.resolve_button.disabled = False
            await interaction.response.edit_message(view=self)
            
        except Exception as e:
            self.logger.error(f"Error in result selection: {e}", exc_info=True)
            await interaction.response.send_message("An error occurred. Please try again.", ephemeral=True)

    async def on_resolve_click(self, interaction: discord.Interaction):
        """Handle resolve button click."""
        self.logger.info(f"Resolve button interaction received")
        try:
            if not self.selected_prediction or not self.selected_result:
                await interaction.response.send_message(
                    "Please select both a prediction and a result first.",
                    ephemeral=True
                )
                return

            prediction, payouts = await self.cog.service.resolve_prediction(
                prediction_id=self.selected_prediction.id,
                result=self.selected_result,
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

            await interaction.response.edit_message(content=None, embed=embed, view=None)
            self.stop()

        except Exception as e:
            self.logger.error(f"Error in resolve button click: {e}", exc_info=True)
            await interaction.response.send_message(f"Error resolving prediction: {str(e)}", ephemeral=True)

class BettingView(BaseMarketView):
    def __init__(self, cog, predictions: List[Prediction]):
        super().__init__(cog)
        self.predictions = predictions
        self.selected_prediction: Optional[Prediction] = None
        self.selected_option: Optional[str] = None
        self.selected_economy: Optional[str] = None
        
        self.setup_view()

    def setup_view(self):
        """Initial view setup with prediction select."""
        prediction_select = discord.ui.Select(
            placeholder="Select a prediction...",
            options=[
                discord.SelectOption(
                    label=f"ID {p.id} | Pool: {p.total_pool:,}",
                    description=f"Q: {p.question[:50]}...",
                    value=str(p.id)
                )
                for p in self.predictions
            ],
            row=0
        )
        prediction_select.callback = self.on_prediction_select
        self.add_item(prediction_select)

    async def on_prediction_select(self, interaction: discord.Interaction):
        """Handle prediction selection."""
        try:
            # Get selected prediction
            pred_id = int(interaction.data['values'][0])
            self.selected_prediction = next(p for p in self.predictions if p.id == pred_id)
            
            # Clear current items
            self.clear_items()
            
            # Add option select
            option_select = discord.ui.Select(
                placeholder="Select your prediction...",
                options=[
                    discord.SelectOption(label=option, value=option)
                    for option in self.selected_prediction.options
                ],
                row=0
            )
            option_select.callback = self.on_option_select
            self.add_item(option_select)
            
            await interaction.response.edit_message(view=self)
            
        except Exception as e:
            self.logger.error(f"Error in prediction selection: {e}")
            await interaction.response.send_message(
                "An error occurred. Please try again.",
                ephemeral=True
            )

    async def on_option_select(self, interaction: discord.Interaction):
        """Handle option selection."""
        try:
            self.selected_option = interaction.data['values'][0]
            self.clear_items()
            
            # Get available economies
            available_economies = self.cog.service.get_available_economies()
            if not available_economies:
                await interaction.response.send_message(
                    "❌ No external economies are available for betting.",
                    ephemeral=True
                )
                return
            
            # Add economy select
            economy_select = discord.ui.Select(
                placeholder="Select which points to bet with...",
                options=[
                    discord.SelectOption(
                        label=f"{economy.upper()} Points",
                        value=economy
                    )
                    for economy in available_economies
                ],
                row=0
            )
            economy_select.callback = self.on_economy_select
            self.add_item(economy_select)
            
            await interaction.response.edit_message(view=self)
            
        except Exception as e:
            self.logger.error(f"Error in option selection: {e}")
            await interaction.response.send_message(
                "An error occurred. Please try again.",
                ephemeral=True
            )

    async def on_economy_select(self, interaction: discord.Interaction):
        """Handle economy selection."""
        try:
            self.selected_economy = interaction.data['values'][0]
            
            # Show amount modal
            modal = BetAmountModal(
                self.cog,
                self.selected_prediction,
                self.selected_option,
                self.selected_economy
            )
            await interaction.response.send_modal(modal)
            
        except Exception as e:
            self.logger.error(f"Error in economy selection: {e}")
            await interaction.response.send_message(
                "An error occurred. Please try again.",
                ephemeral=True
            )

class PredictionsListView(BaseMarketView):
    """View for listing predictions."""
    def __init__(self, cog, predictions: List[Prediction], show_all: bool = False):
        super().__init__(cog)
        self.predictions = predictions
        self.current_page = 0
        self.items_per_page = 5
        self.show_all = show_all
        self.setup_view()

    def setup_view(self):
        """Set up navigation buttons."""
        # Previous page button
        self.prev_button = discord.ui.Button(
            label="Previous",
            style=discord.ButtonStyle.gray,
            disabled=True,
            row=1
        )
        self.prev_button.callback = self.on_prev_click
        self.add_item(self.prev_button)

        # Next page button
        self.next_button = discord.ui.Button(
            label="Next",
            style=discord.ButtonStyle.gray,
            disabled=len(self.predictions) <= self.items_per_page,
            row=1
        )
        self.next_button.callback = self.on_next_click
        self.add_item(self.next_button)

    def get_current_embed(self) -> discord.Embed:
        """Get embed for current page."""
        start_idx = self.current_page * self.items_per_page
        end_idx = start_idx + self.items_per_page
        current_items = self.predictions[start_idx:end_idx]

        embed = discord.Embed(
            title="🎯 Active Predictions" if not self.show_all else "🎯 All Predictions",
            color=discord.Color.blue()
        )

        for pred in current_items:
            status = "🟢 Active" if not pred.resolved else "🔴 Resolved"
            time_left = "Ended" if pred.end_time <= datetime.now(timezone.utc) else \
                       f"Ends <t:{int(pred.end_time.timestamp())}:R>"
            
            field_value = (
                f"Status: {status}\n"
                f"Options: {', '.join(pred.options)}\n"
                f"Total Pool: {pred.total_pool:,} points\n"
                f"{time_left}"
            )
            if pred.resolved:
                field_value += f"\nWinner: {pred.result}"

            embed.add_field(
                name=f"ID {pred.id}: {pred.question}",
                value=field_value,
                inline=False
            )

        embed.set_footer(text=f"Page {self.current_page + 1}/{self.get_max_pages()}")
        return embed

    def get_max_pages(self) -> int:
        """Get maximum number of pages."""
        return max(1, math.ceil(len(self.predictions) / self.items_per_page))

    async def on_prev_click(self, interaction: discord.Interaction):
        """Handle previous page button click."""
        try:
            self.current_page = max(0, self.current_page - 1)
            self.update_button_states()
            await interaction.response.edit_message(embed=self.get_current_embed(), view=self)
        except Exception as e:
            self.logger.error(f"Error handling previous page: {e}")
            await interaction.response.send_message("An error occurred. Please try again.", ephemeral=True)

    async def on_next_click(self, interaction: discord.Interaction):
        """Handle next page button click."""
        try:
            self.current_page = min(self.get_max_pages() - 1, self.current_page + 1)
            self.update_button_states()
            await interaction.response.edit_message(embed=self.get_current_embed(), view=self)
        except Exception as e:
            self.logger.error(f"Error handling next page: {e}")
            await interaction.response.send_message("An error occurred. Please try again.", ephemeral=True)

    def update_button_states(self):
        """Update button disabled states."""
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.get_max_pages() - 1

class RefundView(BaseMarketView):
    """View for refunding predictions."""
    def __init__(self, cog, predictions: List[Prediction]):
        super().__init__(cog)
        self.predictions = {str(p.id): p for p in predictions}
        self.selected_prediction: Optional[Prediction] = None
        self.setup_view()

    def setup_view(self):
        """Set up the refund selection view."""
        # Prediction Select
        self.prediction_select = discord.ui.Select(
            placeholder="Select a prediction to refund...",
            options=[
                discord.SelectOption(
                    label=f"ID {p_id} | {len(p.bets)} bets | {p.total_pool:,} points",
                    description=f"Q: {p.question[:50]}..." if len(p.question) > 50 else f"Q: {p.question}",
                    value=p_id
                )
                for p_id, p in self.predictions.items()
            ],
            row=0
        )
        self.prediction_select.callback = self.on_prediction_select
        self.add_item(self.prediction_select)

        # Refund Button (initially disabled)
        self.refund_button = discord.ui.Button(
            label="Refund Prediction",
            style=discord.ButtonStyle.danger,
            disabled=True,
            row=1
        )
        self.refund_button.callback = self.on_refund_click
        self.add_item(self.refund_button)

    async def on_prediction_select(self, interaction: discord.Interaction):
        """Handle prediction selection."""
        try:
            pred_id = interaction.data['values'][0]
            self.selected_prediction = self.predictions[pred_id]
            
            # Update prediction select to show selected value
            for option in self.prediction_select.options:
                option.default = (option.value == pred_id)
            
            self.refund_button.disabled = False
            await interaction.response.edit_message(view=self)
        except Exception as e:
            self.logger.error(f"Error in prediction selection: {e}")
            await interaction.response.send_message("An error occurred. Please try again.", ephemeral=True)

    async def on_refund_click(self, interaction: discord.Interaction):
        """Handle refund button click."""
        try:
            if not self.selected_prediction:
                await interaction.response.send_message(
                    "Please select a prediction first.",
                    ephemeral=True
                )
                return

            refunds = await self.cog.service.refund_prediction(
                prediction_id=self.selected_prediction.id,
                refunder_id=str(interaction.user.id)
            )

            embed = discord.Embed(
                title="🔄 Prediction Refunded!",
                description=self.selected_prediction.question,
                color=discord.Color.orange()
            )

            if refunds:
                refund_text = "\n".join(
                    f"<@{user_id}>: {amount:,} {economy} points"
                    for user_id, amount, economy in refunds
                )
                embed.add_field(
                    name="Refunds",
                    value=refund_text,
                    inline=False
                )
            else:
                embed.add_field(
                    name="Refunds",
                    value="No bets to refund",
                    inline=False
                )

            await interaction.response.edit_message(content=None, embed=embed, view=None)
            self.stop()

        except Exception as e:
            self.logger.error(f"Error in refund button click: {e}")
            await interaction.response.send_message(f"Error refunding prediction: {str(e)}", ephemeral=True)

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
    @app_commands.command(name="bet", description="Place a bet on a prediction")
    async def bet(self, interaction: discord.Interaction):
        """Place a bet on a prediction."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            predictions = await self.service.get_active_predictions()
            if not predictions:
                await interaction.followup.send(
                    "No active predictions at the moment.",
                    ephemeral=True
                )
                return

            view = BettingView(self, predictions)
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
                category=category,
                channel_id=str(interaction.channel_id)
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
    @app_commands.command(name="predictions", description="List active predictions")
    async def predictions(
        self,
        interaction: discord.Interaction,
        category: Optional[str] = None
    ):
        """List active predictions."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            predictions = await self.service.get_active_predictions(category)
            
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
                options_text = []
                total_bets = sum(bet.amount for bet in pred.bets)
                
                for option in pred.options:
                    option_bets = sum(
                        bet.amount 
                        for bet in pred.bets 
                        if bet.option == option
                    )
                    percentage = (
                        (option_bets / total_bets * 100) 
                        if total_bets > 0 
                        else 0
                    )
                    options_text.append(
                        f"• {option}: {option_bets:,} points ({percentage:.1f}%)"
                    )

                # Ensure end_time is timezone-aware UTC
                if pred.end_time.tzinfo is None:
                    end_time = pred.end_time.replace(tzinfo=timezone.utc)
                else:
                    end_time = pred.end_time

                unix_timestamp = int(end_time.timestamp())

                embed.add_field(
                    name=f"#{pred.id}: {pred.question}",
                    value=(
                        f"{chr(10).join(options_text)}\n"
                        f"**Ends <t:{unix_timestamp}:R>**\n"
                        f"Total Pool: {total_bets:,} points"
                    ),
                    inline=False
                )

            if category:
                embed.set_footer(text=f"Category: {category}")

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
        try:
            # Get only predictions that can be resolved
            predictions = await self.service.get_resolvable_predictions(str(interaction.user.id))
            
            if not predictions:
                await interaction.response.send_message(
                    "🎯 You have no predictions available to resolve at this time.\n"
                    "Predictions can only be resolved after they have ended.",
                    ephemeral=True
                )
                return

            # Continue with resolution UI only if we have resolvable predictions
            view = ResolutionView(self, predictions)
            await interaction.response.send_message(
                f"You have {len(predictions)} prediction(s) ready to resolve:",
                view=view,
                ephemeral=True
            )

        except Exception as e:
            self.logger.error(f"Error in resolve command: {e}")
            await interaction.response.send_message(
                "❌ Something went wrong while checking your resolvable predictions. "
                "Please try again later or contact an administrator if the problem persists.",
                ephemeral=True
            )

async def setup(bot: commands.Bot) -> None:
    """Set up the prediction market cog."""
    logger = setup_logger(__name__)
    logger.info("Setting up Prediction Market cog...")
    await bot.add_cog(PredictionMarket(bot))
    logger.info("Prediction Market cog setup complete")