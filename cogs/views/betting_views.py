from __future__ import annotations
from typing import Optional

import discord
from discord import ui
import logging

from database.models import Prediction, PredictionOption
from services.prediction_market_service import (
    PredictionMarketService,
    InsufficientLiquidityError,
    InvalidBetError,
    MarketStateError
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
        economy: str,
        bot: discord.Client
    ):
        super().__init__()
        self.service = service
        self.prediction = prediction
        self.option = option
        self.user_id = user_id
        self.economy = economy
        self.logger = bot.logger.getChild('bet_modal')

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle bet submission."""
        try:
            amount = int(self.amount.value)
            if amount <= 0:
                raise ValueError("Bet amount must be positive")

            success, message = await self.service.place_bet(
                prediction=self.prediction,
                option=self.option,
                user_id=self.user_id,
                amount=amount,
                economy=self.economy
            )

            await interaction.response.send_message(
                message,
                ephemeral=True
            )

        except ValueError:
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

class BettingView(ui.View):
    """View for placing bets on predictions."""
    
    def __init__(
        self,
        service: PredictionMarketService,
        prediction: Prediction,
        user_id: int,
        economy: str,
        bot: discord.Client,
        timeout: float = 180.0
    ):
        super().__init__(timeout=timeout)
        self.service = service
        self.prediction = prediction
        self.user_id = user_id
        self.economy = economy
        self.bot = bot
        self.logger = bot.logger.getChild('betting_view')
        self.add_betting_options()

    def add_betting_options(self) -> None:
        """Add betting options to the view."""
        select = ui.Select(
            placeholder="Select an option to bet on",
            options=[
                discord.SelectOption(
                    label=option.text[:100],  # Discord limit
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
            
            modal = BetAmountModal(
                self.service,
                self.prediction,
                option,
                self.user_id,
                self.economy,
                self.bot
            )
            await interaction.response.send_modal(modal)
            
        except Exception as e:
            self.logger.error(f"Error in option selection: {e}", exc_info=True)
            await interaction.response.send_message(
                "An error occurred while processing your selection.",
                ephemeral=True
            )
