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

class MarketListView(discord.ui.View):
    """View for displaying and navigating prediction markets."""
    
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
        self.current_page = 0
        self.markets_per_page = 5

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.gray)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle previous page button click."""
        if self.current_page > 0:
            self.current_page -= 1
            await self.update_market_list(interaction)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.gray)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle next page button click."""
        # Service will tell us if there are more pages
        self.current_page += 1
        await self.update_market_list(interaction)

    async def update_market_list(self, interaction: discord.Interaction):
        """Update the market list embed."""
        try:
            markets = await self.service.get_active_markets(
                skip=self.current_page * self.markets_per_page,
                limit=self.markets_per_page
            )
            
            embed = discord.Embed(
                title="Active Prediction Markets",
                color=discord.Color.blue()
            )

            if not markets:
                embed.description = "No active prediction markets found!"
                self.current_page = max(0, self.current_page - 1)
            else:
                for market in markets:
                    embed.add_field(
                        name=f"#{market.id}: {market.question}",
                        value=(
                            f"Options: {', '.join(opt.text for opt in market.options)}\n"
                            f"Ends: <t:{int(market.end_time.timestamp())}:R>\n"
                            f"Created by: <@{market.creator_id}>"
                        ),
                        inline=False
                    )

            embed.set_footer(text=f"Page {self.current_page + 1}")
            await interaction.response.edit_message(embed=embed, view=self)

        except Exception as e:
            self.logger.error(f"Error updating market list: {e}", exc_info=True)
            await interaction.response.send_message(
                "Error updating market list. Please try again.",
                ephemeral=True
            )

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
