from __future__ import annotations
from typing import Optional

import discord
from discord import ui
import logging

from database.models import Prediction, PredictionOption
from services.prediction_market_service import (
    PredictionMarketService,
    MarketStateError,
    InvalidBetError
)

class ResolutionView(ui.View):
    """View for resolving predictions."""
    
    def __init__(
        self,
        service: PredictionMarketService,
        prediction: Prediction,
        resolver_id: int,
        bot: discord.Client,
        timeout: float = 180.0
    ):
        super().__init__(timeout=timeout)
        self.service = service
        self.prediction = prediction
        self.resolver_id = resolver_id
        self.bot = bot
        self.logger = bot.logger.getChild('resolution_view')
        self.add_resolution_options()

    def add_resolution_options(self) -> None:
        """Add resolution options to the view."""
        select = ui.Select(
            placeholder="Select the winning option",
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

            if success:
                embed = discord.Embed(
                    title="Prediction Resolved",
                    description=(
                        f"Question: {self.prediction.question}\n"
                        f"Winner: {winning_option.text}"
                    ),
                    color=discord.Color.green()
                )
                await interaction.response.send_message(
                    embed=embed
                )
            else:
                await interaction.response.send_message(
                    message,
                    ephemeral=True
                )
            
        except (MarketStateError, InvalidBetError) as e:
            await interaction.response.send_message(
                str(e),
                ephemeral=True
            )
        except Exception as e:
            self.logger.error(f"Error in resolution: {e}", exc_info=True)
            await interaction.response.send_message(
                "An error occurred while resolving the prediction.",
                ephemeral=True
            )
