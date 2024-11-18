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

class BetModal(discord.ui.Modal, title="Place Your Bet"):
    def __init__(
        self,
        predictions: list[tuple[str, str]],  # List of (id, title)
        options: list[str],
        economies: list[str],
        *args,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        
        # Prediction selector
        self.prediction_select = discord.ui.Select(
            custom_id="prediction_select",
            placeholder="Select prediction",
            options=[
                discord.SelectOption(label=title, value=id) 
                for id, title in predictions
            ]
        )
        self.add_item(self.prediction_select)
        
        # Option selector
        self.option_select = discord.ui.Select(
            custom_id="option_select",
            placeholder="Select option",
            options=[discord.SelectOption(label=opt) for opt in options]
        )
        self.add_item(self.option_select)

        # Amount input
        self.amount = discord.ui.TextInput(
            label="Amount",
            placeholder="Enter bet amount",
            min_length=1,
            max_length=10,
            required=True
        )
        self.add_item(self.amount)

        # Only add economy selector if multiple economies exist
        if len(economies) > 1:
            self.economy_select = discord.ui.Select(
                custom_id="economy_select",
                placeholder="Select economy",
                options=[discord.SelectOption(label=e) for e in economies]
            )
            self.add_item(self.economy_select)
        else:
            # Store the single economy if only one exists
            self.single_economy = economies[0] if economies else None

    async def callback(self, interaction: discord.Interaction):
        try:
            prediction_id = self.prediction_select.values[0]
            selected_option = self.option_select.values[0]
            amount = int(self.amount.value)
            
            # Get economy selection or use default
            economy = (self.economy_select.values[0] 
                      if len(self.children) > 3 
                      else self.single_economy)
            
            if not economy:
                await interaction.response.send_message(
                    "No external economies available for betting.",
                    ephemeral=True
                )
                return

            # Place bet using prediction market service
            success = await interaction.client.prediction_market_service.place_bet(
                prediction_id=prediction_id,
                user_id=interaction.user.id,
                option=selected_option,
                amount=amount,
                economy=economy
            )

            if success:
                await interaction.response.send_message(
                    f"Bet placed successfully! You bet {amount} {economy} tokens on {selected_option}",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "Failed to place bet. Please check your balance and try again.",
                    ephemeral=True
                )

        except ValueError:
            await interaction.response.send_message(
                "Please enter a valid number for the bet amount.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"An error occurred: {str(e)}",
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

class ResolutionView(BaseMarketView):
    def __init__(self, cog, predictions: List[Prediction]):
        super().__init__(cog)
        self.predictions = {str(p.id): p for p in predictions}
        self.selected_prediction: Optional[Prediction] = None
        self.selected_result: Optional[str] = None
        self.logger = logging.getLogger(__name__)
        
        self.setup_view()

    def setup_view(self):
        """Set up the resolution view."""
        # Prediction Select
        self.prediction_select = discord.ui.Select(
            placeholder="Select a prediction to resolve...",
            options=[
                discord.SelectOption(
                    label=p.question[:100] + "..." if len(p.question) > 100 else p.question,
                    description=f"Pool: {p.total_pool:,} points | ID: {p_id}",
                    value=p_id,
                    emoji="🎯"
                )
                for p_id, p in self.predictions.items()
            ],
            row=0
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
            row=1
        )
        self.result_select.callback = self.on_result_select
        self.add_item(self.result_select)

        # Resolve Button (initially disabled)
        self.resolve_button = discord.ui.Button(
            label="Resolve Prediction",
            style=discord.ButtonStyle.primary,
            disabled=True,
            row=2,
            emoji="✅"
        )
        self.resolve_button.callback = self.on_resolve_click
        self.add_item(self.resolve_button)

        # Initial embed
        self.current_embed = discord.Embed(
            title="🎯 Resolve Prediction",
            description="Select a prediction to resolve from the dropdown menu below.",
            color=discord.Color.blue()
        )

    def update_embed(self):
        """Update embed with current selection state."""
        embed = discord.Embed(
            title="🎯 Resolve Prediction",
            color=discord.Color.blue()
        )
        
        if self.selected_prediction:
            embed.add_field(
                name="📋 Prediction",
                value=self.selected_prediction.question,
                inline=False
            )
            
            # Show betting details
            total_bets = len(self.selected_prediction.bets)
            embed.add_field(
                name="💰 Pool Details",
                value=f"Total Bets: {total_bets}\nTotal Pool: {self.selected_prediction.total_pool:,} points",
                inline=True
            )
            
            # Show options and their current pools
            options_text = []
            for option in self.selected_prediction.options:
                option_total = self.selected_prediction.get_option_total(option)
                options_text.append(f"• {option}: {option_total:,} points")
            
            embed.add_field(
                name="🎯 Options",
                value="\n".join(options_text),
                inline=False
            )
            
            if self.selected_result:
                embed.add_field(
                    name="✅ Selected Result",
                    value=self.selected_result,
                    inline=True
                )
        
        return embed

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
        # 1. Prediction Select (First)
        self.prediction_select = discord.ui.Select(
            placeholder="Select a prediction to bet on...",
            options=[
                discord.SelectOption(
                    label=p.question[:100] + "..." if len(p.question) > 100 else p.question,
                    description=f"Pool: {p.total_pool:,} points | Ends <t:{int(p.end_time.timestamp())}:R>",
                    value=str(p.id),
                    emoji="🎯"
                )
                for p in self.predictions
            ],
            row=0
        )
        self.prediction_select.callback = self.on_prediction_select
        self.add_item(self.prediction_select)

        # 2. Option Select (Initially disabled)
        self.option_select = discord.ui.Select(
            placeholder="First select a prediction...",
            options=[discord.SelectOption(label="Select prediction first", value="placeholder")],
            disabled=True,
            row=1
        )
        self.option_select.callback = self.on_option_select
        self.add_item(self.option_select)

        # Get external economies once
        external_economies = list(self.cog.bot.transfer_service._external_services.keys())
        
        # Only create economy select if multiple economies exist
        if len(external_economies) > 1:
            self.economy_select = discord.ui.Select(
                placeholder="First select your prediction...",
                options=[discord.SelectOption(label="Select option first", value="placeholder")],
                disabled=True,
                row=2
            )
            self.economy_select.callback = self.on_economy_select
            self.add_item(self.economy_select)
        else:
            # Store the single economy
            self.selected_economy = external_economies[0]

        # Initial embed
        self.current_embed = discord.Embed(
            title="🎲 Place Your Bet",
            description="Select a prediction from the dropdown menu below.",
            color=discord.Color.blue()
        )

    async def on_prediction_select(self, interaction: discord.Interaction):
        """Handle prediction selection."""
        try:
            pred_id = int(interaction.data['values'][0])
            self.selected_prediction = next(p for p in self.predictions if p.id == pred_id)
            
            # Update prediction select to show selection
            for option in self.prediction_select.options:
                option.default = (option.value == str(pred_id))
            
            # Enable and update option select with context
            self.option_select.disabled = False
            self.option_select.placeholder = "What's your prediction?"
            self.option_select.options = [
                discord.SelectOption(
                    label=option,
                    description=f"Current Pool: {self.selected_prediction.get_option_total(option):,} points",
                    value=option,
                    emoji="🎯"
                )
                for option in self.selected_prediction.options
            ]
            
            # Update message with new embed
            embed = discord.Embed(
                title="🎲 Place Your Bet",
                description=self.selected_prediction.question,
                color=discord.Color.blue()
            )
            
            end_time = f"<t:{int(self.selected_prediction.end_time.timestamp())}:R>"
            embed.add_field(
                name="💰 Current Pool",
                value=f"{self.selected_prediction.total_pool:,} points",
                inline=True
            )
            embed.add_field(
                name="⏰ Ends",
                value=end_time,
                inline=True
            )
            
            await interaction.response.edit_message(embed=embed, view=self)
            
        except Exception as e:
            self.logger.error(f"Error in prediction selection: {e}")
            await interaction.response.send_message("An error occurred. Please try again.", ephemeral=True)

    async def on_option_select(self, interaction: discord.Interaction):
        """Handle option selection."""
        try:
            self.selected_option = interaction.data['values'][0]
            
            # Get available economies
            external_economies = list(self.cog.bot.transfer_service._external_services.keys())
            
            # Create modal with available economies
            modal = BetAmountModal(
                self.cog,
                self.selected_prediction,
                self.selected_option,
                available_economies=external_economies
            )
            await interaction.response.send_modal(modal)
            
        except Exception as e:
            self.logger.error(f"Error in option selection: {e}")
            await interaction.response.send_message("An error occurred. Please try again.", ephemeral=True)

    async def on_economy_select(self, interaction: discord.Interaction):
        """Handle economy selection."""
        try:
            self.selected_economy = interaction.data['values'][0]
            
            # Create and show modal
            modal = BetAmountModal(
                self.cog,
                self.selected_prediction,
                self.selected_option,
                self.selected_economy
            )
            await interaction.response.send_modal(modal)
            
        except Exception as e:
            self.logger.error(f"Error in economy selection: {e}")
            await interaction.response.send_message("An error occurred. Please try again.", ephemeral=True)

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
    @app_commands.command()
    async def bet(self, interaction: discord.Interaction):
        """Place a bet on an active prediction"""
        try:
            # Get available external economies
            external_economies = list(self.bot.transfer_service._external_services.keys())
            
            if not external_economies:
                await interaction.response.send_message(
                    "No external economies are currently available for betting.",
                    ephemeral=True
                )
                return

            # Get active predictions
            active_predictions = await self.bot.prediction_market_service.get_active_predictions()
            
            if not active_predictions:
                await interaction.response.send_message(
                    "No active predictions available.",
                    ephemeral=True
                )
                return

            # Show BettingView
            view = BettingView(self, active_predictions)
            await interaction.response.send_message(
                "🎲 Place Your Bet",
                view=view,
                ephemeral=True
            )

        except Exception as e:
            self.logger.error(f"Error in bet command: {e}")
            await interaction.response.send_message(
                f"An error occurred: {str(e)}",
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

class BetAmountModal(discord.ui.Modal, title="Enter Bet Amount"):
    def __init__(
        self,
        cog,
        prediction: Prediction,
        selected_option: str,
        available_economies: list[str]
    ):
        super().__init__()
        self.cog = cog
        self.prediction = prediction
        self.selected_option = selected_option
        
        # Determine economy handling
        self.single_economy = available_economies[0] if len(available_economies) == 1 else None
        self.multiple_economies = len(available_economies) > 1

        # Amount input - label changes based on economy context
        amount_label = (
            f"Amount ({self.single_economy} points)" 
            if self.single_economy 
            else "Amount"
        )
        self.amount = discord.ui.TextInput(
            label=amount_label,
            placeholder="Enter bet amount",
            min_length=1,
            max_length=10,
            required=True
        )
        self.add_item(self.amount)

        # Only add economy selector if multiple economies exist
        if self.multiple_economies:
            self.economy = discord.ui.Select(
                placeholder="Select economy",
                options=[
                    discord.SelectOption(
                        label=f"{economy.upper()} Points",
                        value=economy,
                        emoji="💎"
                    )
                    for economy in available_economies
                ]
            )
            self.add_item(self.economy)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.amount.value)
            
            # Get economy based on UI state
            economy = (
                self.single_economy if self.single_economy 
                else self.economy.values[0] if self.multiple_economies
                else None
            )
            
            if not economy:
                await interaction.response.send_message(
                    "❌ No economy selected or available.",
                    ephemeral=True
                )
                return

            success = await self.cog.service.place_bet(
                prediction_id=self.prediction.id,
                user_id=str(interaction.user.id),
                option=self.selected_option,
                amount=amount,
                economy=economy
            )

            if success:
                await interaction.response.send_message(
                    f"✅ Bet placed successfully! You bet {amount:,} {economy} points on {self.selected_option}",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "❌ Failed to place bet. Please check your balance and try again.",
                    ephemeral=True
                )

        except ValueError:
            await interaction.response.send_message(
                "❌ Please enter a valid number for the bet amount.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ An error occurred: {str(e)}",
                ephemeral=True
            )

async def setup(bot: commands.Bot) -> None:
    """Set up the prediction market cog."""
    logger = setup_logger(__name__)
    logger.info("Setting up Prediction Market cog...")
    await bot.add_cog(PredictionMarket(bot))
    logger.info("Prediction Market cog setup complete")