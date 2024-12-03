import discord
import logging
from discord.ext import commands
from discord import app_commands
from services.prediction_market_service import (
    PredictionMarketError,
    InsufficientLiquidityError,
    InvalidBetError,
    MarketStateError
)

class BettingView(discord.ui.View):
    def __init__(self, cog, prediction_id: int):
        super().__init__(timeout=180)  # 3 minute timeout
        self.cog = cog
        self.prediction_id = prediction_id
        self.logger = logging.getLogger(__name__)
        self.amount = None
        self.selected_option = None
        self.selected_economy = None
        self._init_selects()
        
    def _init_selects(self):
        """Initialize select menus with options"""
        # Will be populated when view is shown
        self.option_select = discord.ui.Select(
            placeholder="Select an option",
            custom_id="option_select",
            row=0
        )
        self.option_select.callback = self.option_select_callback
        
        self.economy_select = discord.ui.Select(
            placeholder="Select economy",
            custom_id="economy_select",
            row=1
        )
        self.economy_select.callback = self.economy_select_callback
        
        self.add_item(self.option_select)
        self.add_item(self.economy_select)

    async def setup_options(self):
        """Setup prediction options and economies with logging context"""
        log_context = {
            'prediction_id': self.prediction_id,
            'channel_id': None  # Will be set when interaction occurs
        }
        
        try:
            # Get prediction options
            prediction = await self.cog.service.get_prediction(self.prediction_id)
            self.option_select.options = [
                discord.SelectOption(label=option['text'], value=option['text'])
                for option in prediction['options']
            ]
            
            # Setup economy options
            self.economy_select.options = [
                discord.SelectOption(label=economy, value=economy)
                for economy in self.cog.service.available_economies
            ]
            
        except Exception as e:
            self.logger.error(
                f"Error setting up options: {e}",
                exc_info=True,
                extra=log_context
            )
            raise

    async def update_message(self, interaction: discord.Interaction):
        """Update the betting interface message"""
        try:
            prediction = await self.cog.service.get_prediction(self.prediction_id)
            prices = await self.cog.service.get_current_prices(self.prediction_id)
            
            embed = discord.Embed(
                title="🎲 Place Your Bet",
                description=prediction['question'],
                color=discord.Color.blue()
            )
            
            # Show current market prices
            market_status = ""
            for option_text, price_info in prices.items():
                market_status += (
                    f"\n{option_text}\n"
                    f"Price: {price_info['price_per_share']:.2f} Points/Share\n"
                    f"Prob:  {price_info['probability']:.1f}%\n"
                )
            
            embed.add_field(
                name="Current Market Status",
                value=f"```{market_status}```",
                inline=False
            )
            
            # Show selected options if any
            if self.selected_option:
                embed.add_field(
                    name="Selected Option",
                    value=self.selected_option,
                    inline=True
                )
            
            if self.amount:
                embed.add_field(
                    name="Bet Amount",
                    value=f"{self.amount:,} Points",
                    inline=True
                )
                
                # Calculate potential shares/payout if both option and amount are selected
                if self.selected_option:
                    try:
                        shares = await self.cog.service.calculate_amm_shares(
                            self.prediction_id,
                            self.selected_option,
                            self.amount
                        )
                        embed.add_field(
                            name="Potential Shares",
                            value=f"{shares:.2f} Shares",
                            inline=True
                        )
                    except Exception as e:
                        self.logger.error(f"Error calculating shares: {e}")
            
            if self.selected_economy:
                embed.add_field(
                    name="Selected Economy",
                    value=self.selected_economy,
                    inline=True
                )
            
            await interaction.response.edit_message(embed=embed, view=self)
            
        except Exception as e:
            self.logger.error(f"Error updating betting message: {e}", exc_info=True)
            await interaction.response.send_message(
                "An error occurred while updating the betting interface.",
                ephemeral=True
            )

    async def option_select_callback(self, interaction: discord.Interaction):
        """Handle option selection with logging context"""
        log_context = {
            'user_id': interaction.user.id,
            'prediction_id': self.prediction_id,
            'channel_id': interaction.channel_id,
            'economy': self.selected_economy
        }
        
        self.logger.debug(
            f"Option selected: {self.option_select.values[0]}",
            extra=log_context
        )
        self.selected_option = self.option_select.values[0]
        await self.update_message(interaction)

    async def economy_select_callback(self, interaction: discord.Interaction):
        """Handle economy selection"""
        self.selected_economy = self.economy_select.values[0]
        await self.update_message(interaction)

    @discord.ui.button(label="Bet 100", style=discord.ButtonStyle.secondary, row=2)
    async def bet_100(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.amount = 100
        await self.update_message(interaction)

    @discord.ui.button(label="Bet 500", style=discord.ButtonStyle.secondary, row=2)
    async def bet_500(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.amount = 500
        await self.update_message(interaction)

    @discord.ui.button(label="Bet 1000", style=discord.ButtonStyle.secondary, row=2)
    async def bet_1000(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.amount = 1000
        await self.update_message(interaction)

    @discord.ui.button(label="Custom Amount", style=discord.ButtonStyle.secondary, row=2)
    async def custom_amount(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle custom amount input"""
        await interaction.response.send_modal(CustomAmountModal(self))

    @discord.ui.button(label="Place Bet", style=discord.ButtonStyle.success, row=3)
    async def place_bet(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle bet placement"""
        if not all([self.selected_option, self.amount, self.selected_economy]):
            await interaction.response.send_message(
                "Please select an option, amount, and economy before placing your bet.",
                ephemeral=True
            )
            return

        try:
            success, error_message = await self.cog.service.place_bet(
                prediction_id=self.prediction_id,
                option_text=self.selected_option,
                user_id=interaction.user.id,
                amount=self.amount,
                economy=self.selected_economy
            )

            if success:
                embed = discord.Embed(
                    title="Bet Placed Successfully!",
                    description=(
                        f"Option: {self.selected_option}\n"
                        f"Amount: {self.amount:,} Points\n"
                        f"Economy: {self.selected_economy}"
                    ),
                    color=discord.Color.green()
                )
                await interaction.response.edit_message(
                    embed=embed,
                    view=None
                )
            else:
                await interaction.response.send_message(
                    f"Failed to place bet: {error_message}",
                    ephemeral=True
                )

        except Exception as e:
            self.logger.error(f"Error placing bet: {e}", exc_info=True)
            await interaction.response.send_message(
                "An error occurred while placing your bet.",
                ephemeral=True
            )

class CustomAmountModal(discord.ui.Modal, title="Enter Bet Amount"):
    def __init__(self, betting_view: BettingView):
        super().__init__()
        self.betting_view = betting_view

    amount = discord.ui.TextInput(
        label="Amount",
        placeholder="Enter amount to bet...",
        min_length=1,
        max_length=10
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.amount.value)
            if amount <= 0:
                raise ValueError("Amount must be positive")
            
            self.betting_view.amount = amount
            await self.betting_view.update_message(interaction)
            
        except ValueError:
            await interaction.response.send_message(
                "Please enter a valid positive number.",
                ephemeral=True
            )

class ResolutionView(discord.ui.View):
    def __init__(self, cog, prediction_id: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.prediction_id = prediction_id
        self.logger = logging.getLogger(__name__)
        self._init_select()

    def _init_select(self):
        """Initialize the winning option select menu"""
        self.winner_select = discord.ui.Select(
            placeholder="Select winning option",
            custom_id="winner_select",
            row=0
        )
        self.winner_select.callback = self.winner_select_callback
        self.add_item(self.winner_select)

    async def setup_options(self):
        """Setup prediction options"""
        try:
            prediction = await self.cog.service.get_prediction(self.prediction_id)
            self.winner_select.options = [
                discord.SelectOption(label=option['text'], value=option['text'])
                for option in prediction['options']
            ]
            # Add cancel option
            self.winner_select.options.append(
                discord.SelectOption(label="Cancel Prediction", value="CANCEL")
            )
        except Exception as e:
            self.logger.error(f"Error setting up resolution options: {e}", exc_info=True)
            raise

    async def winner_select_callback(self, interaction: discord.Interaction):
        """Handle winner selection"""
        try:
            selected_option = self.winner_select.values[0]
            
            if selected_option == "CANCEL":
                success = await self.cog.service.cancel_prediction(
                    prediction_id=self.prediction_id,
                    resolver_id=interaction.user.id
                )
                message = "Prediction cancelled and bets refunded"
            else:
                success = await self.cog.service.resolve_prediction(
                    prediction_id=self.prediction_id,
                    winning_option=selected_option,
                    resolver_id=interaction.user.id
                )
                message = f"Prediction resolved with winner: {selected_option}"

            if success:
                # Send resolution notification to channel
                await self.cog.service.send_resolution_notification(
                    prediction_id=self.prediction_id,
                    channel_id=interaction.channel_id
                )
                
                # Send DM notifications to winners
                if selected_option != "CANCEL":
                    await self.cog.service.send_winner_notifications(
                        prediction_id=self.prediction_id
                    )
                
                embed = discord.Embed(
                    title="Resolution Complete",
                    description=message,
                    color=discord.Color.green()
                )
                await interaction.response.edit_message(
                    embed=embed,
                    view=None
                )
            else:
                await interaction.response.send_message(
                    "Failed to resolve prediction.",
                    ephemeral=True
                )

        except Exception as e:
            self.logger.error(f"Error in winner selection: {e}", exc_info=True)
            await interaction.response.send_message(
                "An error occurred while resolving the prediction.",
                ephemeral=True
            )

class PredictionMarketCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.service = None  # Set up in setup()

    @app_commands.command(
        name="create_prediction",
        description="Create a new prediction market"
    )
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
        category: str = None
    ):
        """Create a new prediction market"""
        await interaction.response.defer(ephemeral=True)
        # ... rest of create_prediction implementation ...

    @app_commands.command(
        name="bet",
        description="Place a bet on a prediction"
    )
    async def bet(
        self,
        interaction: discord.Interaction
    ):
        """Place a bet on a prediction"""
        await interaction.response.defer(ephemeral=True)
        # ... implement category-based betting UI ...

    @app_commands.command(
        name="list_predictions",
        description="List all active predictions"
    )
    async def list_predictions(
        self,
        interaction: discord.Interaction,
        show_all: bool = False
    ):
        """List active predictions"""
        await interaction.response.defer(ephemeral=True)
        # ... implement prediction listing ...

    @app_commands.command(
        name="resolve",
        description="Resolve a prediction market"
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    async def resolve(
        self,
        interaction: discord.Interaction,
        prediction_id: int
    ):
        """Resolve a prediction market"""
        self.logger.debug(
            f"Resolve command invoked",
            extra={
                'user_id': interaction.user.id,
                'prediction_id': prediction_id
            }
        )
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            prediction = await self.service.get_prediction(prediction_id)
            if not prediction:
                await interaction.followup.send(
                    "❌ Prediction not found.",
                    ephemeral=True
                )
                return
                
            if prediction['resolved']:
                await interaction.followup.send(
                    "❌ This prediction has already been resolved.",
                    ephemeral=True
                )
                return

            view = ResolutionView(self, prediction_id)
            await view.setup_options()
            
            embed = discord.Embed(
                title="Resolve Prediction",
                description=(
                    f"Question: {prediction['question']}\n\n"
                    "Select the winning option or cancel the prediction."
                ),
                color=discord.Color.blue()
            )
            
            await interaction.followup.send(
                embed=embed,
                view=view,
                ephemeral=True
            )
            
        except Exception as e:
            self.logger.error(
                "Error in resolve command",
                exc_info=True,
                extra={
                    'user_id': interaction.user.id,
                    'prediction_id': prediction_id
                }
            )
            await interaction.followup.send(
                "❌ An error occurred while setting up the resolution interface.",
                ephemeral=True
            )

    @bet.error
    @resolve.error
    async def on_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError
    ):
        """Handle command errors"""
        if isinstance(error, app_commands.CheckFailure):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.",
                ephemeral=True
            )
            return
            
        self.logger.error(
            "Command error",
            exc_info=error,
            extra={
                'user_id': interaction.user.id,
                'command': interaction.command.name
            }
        )
        
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ An error occurred while processing your command.",
                ephemeral=True
            )

async def setup(bot):
    """Set up the prediction market cog"""
    await bot.add_cog(PredictionMarketCog(bot))
