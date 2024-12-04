from __future__ import annotations
from typing import Optional, List, Dict
from datetime import datetime

import discord
from discord import ui
import asyncio
import logging

from database.models import Prediction, PredictionOption, utc_now, ensure_utc
from services.prediction_market_service import (
    PredictionMarketService,
    MarketStateError,
    InvalidBetError,
    InsufficientLiquidityError,
)
from utils.logging import PredictionMarketFilter

class MarketListView(ui.View):
    """View for displaying and auto-updating market listings."""
    
    def __init__(
        self, 
        service: PredictionMarketService,
        bot: discord.Client,
        timeout: float = 180.0
    ):
        super().__init__(timeout=timeout)
        self.service = service
        self.bot = bot
        self.logger = bot.logger.getChild('market_list_view')
        self.logger.addFilter(PredictionMarketFilter())  # Add market-specific context
        self.stored_interaction: Optional[discord.Interaction] = None
        self.update_task: Optional[asyncio.Task] = None

    async def start_auto_update(self) -> None:
        """Start the auto-update task."""
        if not self.update_task:
            self.update_task = asyncio.create_task(self.auto_update_markets())
            self.logger.debug("Started auto-update task")

    def stop_auto_update(self) -> None:
        """Stop the auto-update task."""
        if self.update_task:
            self.update_task.cancel()
            self.update_task = None
            self.logger.debug("Stopped auto-update task")

    async def auto_update_markets(self) -> None:
        """Auto-update markets every 30 seconds."""
        try:
            while True:
                await self.refresh_view()
                await asyncio.sleep(30)
        except asyncio.CancelledError:
            self.logger.debug("Auto-update task cancelled")
        except Exception as e:
            self.logger.error(f"Error in auto_update_markets: {e}", exc_info=True)

    def create_market_display(self, prediction: Prediction, prices: Dict) -> str:
        """Create a formatted market display."""
        market_text = (
            f"Category: {prediction.category or 'None'}\n"
            f"Total Volume: {sum(bet.amount for bet in prediction.bets):,} Points\n"
            f"Ends: <t:{int(prediction.end_time.timestamp())}:R>\n\n"
            "Current Market Status:\n"
        )

        for option in prediction.options:
            price_info = prices.get(option.text, {})
            vote_count = len(prediction.votes_per_option.get(option.text, []))
            market_text += (
                f"```\n"
                f"{option.text}\n"
                f"Price: {price_info.get('price_per_share', 0):.2f} Points/Share\n"
                f"Prob:  {price_info.get('probability', 0):.1f}%\n"
                f"Volume: {price_info.get('total_bets', 0):,} Points\n"
                f"Votes: {vote_count}\n"
                f"```\n"
            )

        return market_text

    async def refresh_view(self) -> None:
        """Refresh the market display."""
        if not self.stored_interaction:
            return

        try:
            current_embed = discord.Embed(
                title="Prediction Markets",
                description="Current prediction markets available for betting.",
                color=discord.Color.blue()
            )

            # Fetch and categorize markets
            active_markets = await self.service.get_active_predictions()
            pending_markets = await self.service.get_pending_resolution()

            # Add active markets
            if active_markets:
                current_embed.add_field(
                    name="Active Markets", 
                    value="\u200b", 
                    inline=False
                )
                for prediction in active_markets:
                    prices = await self.service.get_market_status(prediction)
                    creator = await self.bot.fetch_user(prediction.creator_id)
                    current_embed.add_field(
                        name=f"{prediction.question} (Created by: {creator.name})",
                        value=self.create_market_display(prediction, prices),
                        inline=False
                    )

            # Add pending resolution markets
            if pending_markets:
                current_embed.add_field(
                    name="Pending Resolution", 
                    value="\u200b", 
                    inline=False
                )
                for prediction in pending_markets:
                    prices = await self.service.get_market_status(prediction)
                    creator = await self.bot.fetch_user(prediction.creator_id)
                    current_embed.add_field(
                        name=f"{prediction.question} (Created by: {creator.name})",
                        value=self.create_market_display(prediction, prices),
                        inline=False
                    )

            current_embed.set_footer(text="Use /bet to place bets on active markets")
            
            await self.stored_interaction.edit_original_response(embed=current_embed)

        except discord.NotFound:
            self.logger.debug("Original message was deleted")
            self.stop_auto_update()
        except discord.HTTPException as e:
            if e.code == 50027:  # Invalid Webhook Token
                self.logger.debug("Interaction token expired")
                self.stop_auto_update()
            else:
                self.logger.error(f"HTTP Exception in refresh_view: {e}")
        except Exception as e:
            self.logger.error(f"Error refreshing view: {e}", exc_info=True)
            self.stop_auto_update()

    async def on_timeout(self) -> None:
        """Handle view timeout."""
        self.stop_auto_update()
        self.logger.debug("Market list view timed out")

    def __del__(self) -> None:
        """Cleanup when the view is destroyed."""
        self.stop_auto_update()

class BettingView(ui.View):
    """View for placing bets on predictions."""
    
    def __init__(
        self,
        service: PredictionMarketService,
        prediction: Prediction,
        user_id: int,
        economy: str,
        timeout: float = 180.0
    ):
        super().__init__(timeout=timeout)
        self.service = service
        self.prediction = prediction
        self.user_id = user_id
        self.economy = economy
        self.logger = logging.getLogger(__name__)
        self.add_betting_options()

    def add_betting_options(self) -> None:
        """Add betting options to the view."""
        select = ui.Select(
            placeholder="Select an option to bet on",
            options=[
                discord.SelectOption(
                    label=option.text,
                    value=str(option.id)
                ) for option in self.prediction.options
            ]
        )
        select.callback = self.option_selected
        self.add_item(select)

    async def option_selected(
        self, 
        interaction: discord.Interaction
    ) -> None:
        """Handle option selection."""
        try:
            option_id = int(interaction.data["values"][0])
            option = next(
                opt for opt in self.prediction.options 
                if opt.id == option_id
            )
            
            # Create modal for amount input
            modal = BetAmountModal(
                self.service,
                self.prediction,
                option,
                self.user_id,
                self.economy
            )
            await interaction.response.send_modal(modal)
            
        except Exception as e:
            self.logger.error(f"Error in option selection: {e}", exc_info=True)
            await interaction.response.send_message(
                "An error occurred while processing your selection.",
                ephemeral=True
            )

class BetAmountModal(ui.Modal, title="Place Your Bet"):
    """Modal for entering bet amount."""
    
    amount = ui.TextInput(
        label="Bet Amount",
        placeholder="Enter amount of points to bet",
        min_length=1,
        max_length=10
    )

    def __init__(
        self,
        service: PredictionMarketService,
        prediction: Prediction,
        option: PredictionOption,
        user_id: int,
        economy: str
    ):
        super().__init__()
        self.service = service
        self.prediction = prediction
        self.option = option
        self.user_id = user_id
        self.economy = economy
        self.logger = logging.getLogger(__name__)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle bet submission."""
        try:
            amount = int(self.amount.value)
            if amount <= 0:
                raise ValueError("Bet amount must be positive")

            success, message = await self.service.place_bet(
                self.prediction,
                self.option,
                self.user_id,
                amount,
                self.economy
            )

            await interaction.response.send_message(
                message,
                ephemeral=True
            )

        except ValueError as e:
            await interaction.response.send_message(
                "Please enter a valid positive number for the bet amount.",
                ephemeral=True
            )
        except (MarketStateError, InvalidBetError, InsufficientLiquidityError) as e:
            await interaction.response.send_message(
                str(e),
                ephemeral=True
            )
        except Exception as e:
            self.logger.error(f"Error processing bet: {e}", exc_info=True)
            await interaction.response.send_message(
                "An error occurred while processing your bet.",
                ephemeral=True
            )

class ResolutionView(ui.View):
    """View for resolving predictions."""
    
    def __init__(
        self,
        service: PredictionMarketService,
        prediction: Prediction,
        resolver_id: int,
        timeout: float = 180.0
    ):
        super().__init__(timeout=timeout)
        self.service = service
        self.prediction = prediction
        self.resolver_id = resolver_id
        self.logger = logging.getLogger(__name__)
        self.add_resolution_options()

    def add_resolution_options(self) -> None:
        """Add resolution options to the view."""
        select = ui.Select(
            placeholder="Select the winning option",
            options=[
                discord.SelectOption(
                    label=option.text,
                    value=str(option.id)
                ) for option in self.prediction.options
            ]
        )
        select.callback = self.option_selected
        self.add_item(select)

    async def option_selected(
        self, 
        interaction: discord.Interaction
    ) -> None:
        """Handle resolution option selection."""
        try:
            option_id = int(interaction.data["values"][0])
            winning_option = next(
                opt for opt in self.prediction.options 
                if opt.id == option_id
            )
            
            success, message = await self.service.resolve_prediction(
                self.prediction,
                winning_option,
                self.resolver_id
            )

            await interaction.response.send_message(
                message,
                ephemeral=True
            )
            
        except Exception as e:
            self.logger.error(f"Error in resolution: {e}", exc_info=True)
            await interaction.response.send_message(
                "An error occurred while resolving the prediction.",
                ephemeral=True
            )
