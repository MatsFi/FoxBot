from discord.ext import commands
import discord
from discord import app_commands
from typing import Optional, List
from datetime import timedelta
import logging
from services import PredictionMarketService
from database.models import utc_now, ensure_utc, Prediction
from discord.ui import View, Select
from services.prediction_market_service import InsufficientLiquidityError, InvalidBetError

class PredictionMarket(commands.Cog):
    """Prediction market commands for betting on outcomes."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.service = PredictionMarketService.from_bot(bot)
        
        # Setup logging
        self.logger = logging.getLogger('foxbot.prediction_market')
        self.logger.setLevel(logging.DEBUG)  # Ensure DEBUG level messages are captured
        
        # Create console handler if it doesn't exist
        if not self.logger.handlers:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.DEBUG)
            
            # Create formatter
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            console_handler.setFormatter(formatter)
            
            # Add handler to logger
            self.logger.addHandler(console_handler)

        self.active_views = {}
        self.logger.info("PredictionMarket cog initialized")

    async def cog_load(self):
        """Called when the cog is loaded."""
        self.logger.info("PredictionMarket cog loading...")
        if not self.service:
            self.logger.debug("Initializing prediction market service...")
            self.service = PredictionMarketService.from_bot(self.bot)
            await self.service.start()
            self.logger.info(f"Prediction market service initialized: {self.service}")

    async def cog_unload(self):
        """Called when the cog is unloaded."""
        if self.service:
            await self.service.stop()
            self.logger.info("Prediction market service stopped")

    @app_commands.guild_only()
    @app_commands.command(name="list_predictions", description="List all predictions")
    async def list_predictions(self, interaction: discord.Interaction):
        self.logger.debug("Starting list_predictions command")
        await interaction.response.defer(ephemeral=True)
        
        try:
            self.logger.debug("Calling service.get_all_predictions()")
            predictions = await self.service.get_all_predictions()
            self.logger.debug(f"Retrieved {len(predictions) if predictions else 0} predictions")

            if not predictions:
                self.logger.debug("No predictions found, sending response")
                await interaction.followup.send(
                    "No predictions found.",
                    ephemeral=True
                )
                return

            self.logger.debug("Creating embed pages")
            pages = []
            for i, prediction in enumerate(predictions):
                self.logger.debug(f"Processing prediction {i+1}/{len(predictions)}")
                
                # Debug bets information
                self.logger.debug(f"Prediction {prediction.id} has {len(prediction.bets)} bets")
                for bet in prediction.bets:
                    self.logger.debug(f"Bet: amount={bet.amount}, economy={bet.economy}")
                
                # Calculate total volume from external economy bets only
                total_volume = sum(bet.amount for bet in prediction.bets 
                                 if bet.economy != 'local_points')
                self.logger.debug(f"Calculated total volume: {total_volume}")
                
                embed = discord.Embed(
                    title="Prediction Market",
                    description=prediction.question,
                    color=discord.Color.blue(),
                    timestamp=ensure_utc(prediction.created_at)
                )
                
                self.logger.debug(f"Getting prices for prediction {prediction.id}")
                prices = await self.service.get_current_prices(prediction.id)
                
                # Status field using plain text
                status = "Active" if not prediction.resolved else "Resolved"
                if prediction.refunded:
                    status = "Refunded"
                embed.add_field(name="Status", value=status, inline=True)
                
                embed.add_field(
                    name="Ends",
                    value=discord.utils.format_dt(
                        ensure_utc(prediction.end_time),
                        style='R'
                    ),
                    inline=True
                )
                
                # Options and odds
                options_text = ""
                for option_text, price_info in prices.items():
                    probability = price_info['probability']
                    options_text += f"\n{option_text}: {probability:.1f}%"
                embed.add_field(name="Options", value=options_text, inline=False)
                
                embed.add_field(
                    name="Total Volume",
                    value=f"{total_volume:,} points",
                    inline=True
                )
                
                if prediction.category:
                    embed.add_field(name="Category", value=prediction.category, inline=True)
                
                if prediction.creator_id:
                    self.logger.debug(f"Fetching creator user for prediction {prediction.id}")
                    creator = await self.bot.fetch_user(prediction.creator_id)
                    embed.set_footer(text=f"Created by {creator.display_name}")
                
                pages.append(embed)

            self.logger.debug("Creating and starting paginated view")
            view = PaginatedPredictionView(pages)
            await view.start(interaction)

        except Exception as e:
            self.logger.error(f"Error listing predictions: {str(e)}", exc_info=True)
            await interaction.followup.send(
                "An error occurred while listing predictions.",
                ephemeral=True
            )

    @app_commands.guild_only()
    @app_commands.command(name="create_prediction", description="Create a new prediction market")
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
            days, hours, minutes = map(
                lambda x: int(x) if x else 0,
                duration.split(',')
            )
            
            total_minutes = (days * 24 * 60) + (hours * 60) + minutes
            if total_minutes <= 0:
                await interaction.followup.send(
                    "Duration must be greater than 0 minutes.",
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
            
            self.logger.debug("Calculating end time")
            end_time = utc_now() + timedelta(minutes=total_minutes)
            
            self.logger.debug("Creating prediction through service")
            prediction = await self.service.create_prediction(
                question=question,
                options=options_list,
                creator_id=interaction.user.id,
                end_time=end_time,
                category=category
            )
            
            if prediction:
                self.logger.info(
                    "Prediction created successfully",
                    extra={
                        'prediction_id': prediction.id,
                        'creator_id': interaction.user.id,
                        'category': category
                    }
                )
                
                await interaction.followup.send(
                    f"Created prediction: {question}\n"
                    f"Category: {category or 'None'}\n"
                    f"Options: {', '.join(options_list)}\n"
                    f"Ends: {discord.utils.format_dt(end_time, style='R')}",
                    ephemeral=True
                )
            else:
                self.logger.error("Failed to create prediction")
                await interaction.followup.send(
                    "Failed to create prediction. Please try again.",
                    ephemeral=True
                )

        except Exception as exc:
            self.logger.error(
                "Error in create_prediction command",
                extra={'error': str(exc)},
                exc_info=True
            )
            await interaction.followup.send(
                "An error occurred while creating the prediction.",
                ephemeral=True
            )

    @app_commands.guild_only()
    @app_commands.command(name="bet", description="Place a bet on a prediction")
    async def bet(self, interaction: discord.Interaction):
        """Interactive command to place a bet on a prediction."""
        self.logger.debug("Starting bet command")
        await interaction.response.defer(ephemeral=True)
        
        try:
            self.logger.debug("Getting active predictions")
            predictions = await self.service.get_active_predictions()
            
            if not predictions:
                self.logger.debug("No active predictions found")
                await interaction.followup.send(
                    "No active predictions available to bet on.",
                    ephemeral=True
                )
                return
            
            # Debug log the predictions
            self.logger.debug(f"Found {len(predictions)} active predictions")
            for pred in predictions:
                self.logger.debug(f"Prediction {pred.id}: {pred.question} with {len(pred.options)} options")
            
            # Create view only if we have predictions
            if predictions:
                view = BettingView(predictions, self)
                embed = discord.Embed(
                    title="Place a Bet",
                    description="Select a prediction to bet on:",
                    color=discord.Color.blue()
                )
                
                self.logger.debug("Sending betting interface")
                await interaction.followup.send(
                    embed=embed,
                    view=view,
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "No active predictions found.",
                    ephemeral=True
                )

        except Exception as exc:
            self.logger.error(
                "Error in bet command",
                extra={'error': str(exc)},
                exc_info=True
            )
            await interaction.followup.send(
                "An error occurred while setting up the betting interface.",
                ephemeral=True
            )

    @app_commands.guild_only()
    @app_commands.command(name="resolve_prediction", description="Resolve a prediction")
    async def resolve_prediction(self, interaction: discord.Interaction):
        """Resolve a prediction using a two-step selection process."""
        self.logger.debug("Starting resolve_prediction command")
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Get predictions that the user can resolve
            predictions = await self.service.get_unresolved_predictions_by_creator(interaction.user.id)
            
            if not predictions:
                await interaction.followup.send(
                    "You have no unresolved predictions to resolve.",
                    ephemeral=True
                )
                return

            # Create the initial selection view
            view = ResolvePredictionView(predictions, self)
            await interaction.followup.send(
                "Select a prediction to resolve:",
                view=view,
                ephemeral=True
            )
                
        except Exception as e:
            self.logger.error(f"Error in resolve_prediction: {str(e)}", exc_info=True)
            await interaction.followup.send(
                "An error occurred while starting the resolution process.",
                ephemeral=True
            )

    async def prediction_id_autocomplete(
        self,
        interaction: discord.Interaction,
        _: str,  # Renamed from current to _ since it's unused
    ) -> List[app_commands.Choice[int]]:
        """Autocomplete for prediction IDs."""
        try:
            predictions = await self.service.get_unresolved_predictions_by_creator(interaction.user.id)
            
            return [
                app_commands.Choice(
                    name=f"#{p.id}: {p.question[:50]}{'...' if len(p.question) > 50 else ''}", 
                    value=p.id
                )
                for p in predictions
            ][:25]
        except Exception as e:
            self.logger.error(f"Error in prediction autocomplete: {str(e)}", exc_info=True)
            return []

    async def winning_option_autocomplete(
        self,
        interaction: discord.Interaction,
        _: str,  # Renamed from current to _ since it's unused
    ) -> List[app_commands.Choice[str]]:
        """Autocomplete for winning options."""
        try:
            prediction_id = interaction.namespace.prediction_id
            if not prediction_id:
                return []

            prediction = await self.service.get_prediction(prediction_id)
            if not prediction:
                return []

            return [
                app_commands.Choice(name=option.text, value=option.text)
                for option in prediction.options
            ]
        except Exception as e:
            self.logger.error(f"Error in option autocomplete: {str(e)}", exc_info=True)
            return []

    async def display_prediction(self, interaction: discord.Interaction, prediction: Prediction):
        embed = discord.Embed(
            title=prediction.question,
            description=f"Ends at: {discord.utils.format_dt(prediction.end_time, style='R')}",
            color=discord.Color.blue()
        )
        if prediction.category:
            embed.add_field(name="Category", value=prediction.category, inline=True)
        # ... other fields ...
        await interaction.response.send_message(embed=embed)

class PredictionSelectMenu(discord.ui.Select):
    def __init__(self, predictions, cog):
        self.cog = cog
        self.logger = logging.getLogger(__name__)
        
        options = [
            discord.SelectOption(
                label=f"{pred.question[:80]}",
                description=f"Ends {discord.utils.format_dt(pred.end_time, style='R')}",
                value=str(pred.id)
            ) for pred in predictions
        ]
        
        self.logger.debug(f"Populating predictions dropdown with {len(options)} items")
        
        super().__init__(
            placeholder="Choose a prediction...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            self.logger.debug(f"Prediction selected: {self.values[0]}")
            selected_prediction = await self.cog.service.get_prediction(int(self.values[0]))
            
            if not selected_prediction:
                self.logger.error(f"Could not find prediction {self.values[0]}")
                await interaction.response.send_message(
                    "Error: Could not find the selected prediction.",
                    ephemeral=True
                )
                return

            view = BettingOptionsView(selected_prediction, self.cog)
            await interaction.response.edit_message(
                content=f"**{selected_prediction.question}**\nSelect an option to bet on:",
                view=view
            )
            
        except Exception:
            self.logger.error("Error in prediction selection", exc_info=True)
            await interaction.response.send_message(
                "An error occurred while processing your selection.",
                ephemeral=True
            )

class BettingView(discord.ui.View):
    def __init__(self, predictions, cog):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        
        if not predictions:
            self.logger.debug("No predictions available for betting")
            return
            
        self.logger.debug(f"Creating select menu with {len(predictions)} options")
        self.add_item(PredictionSelectMenu(predictions, cog))

class PaginatedPredictionView(discord.ui.View):
    def __init__(self, pages):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self.logger.debug(f"Initializing PaginatedPredictionView with {len(pages)} pages")
        self.pages = pages
        self.current_page = 0

    async def start(self, interaction: discord.Interaction):
        self.logger.debug("Starting paginated view")
        await interaction.followup.send(
            embed=self.pages[0],
            view=self,
            ephemeral=True
        )

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.gray)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.logger.debug("Previous button clicked")
        self.current_page = (self.current_page - 1) % len(self.pages)
        self.logger.debug(f"Moving to page {self.current_page + 1}/{len(self.pages)}")
        await interaction.response.edit_message(
            embed=self.pages[self.current_page],
            view=self
        )

    @discord.ui.button(label="Next", style=discord.ButtonStyle.gray)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.logger.debug("Next button clicked")
        self.current_page = (self.current_page + 1) % len(self.pages)
        self.logger.debug(f"Moving to page {self.current_page + 1}/{len(self.pages)}")
        await interaction.response.edit_message(
            embed=self.pages[self.current_page],
            view=self
        )

class ResolvePredictionView(discord.ui.View):
    def __init__(self, predictions: List[Prediction], cog):
        super().__init__()
        self.predictions = predictions
        self.cog = cog
        
        # Create the prediction select menu
        options = [
            discord.SelectOption(
                label=f"#{p.id}: {p.question[:50]}{'...' if len(p.question) > 50 else ''}",
                description=f"Created: {p.created_at.strftime('%Y-%m-%d')}",
                value=str(p.id)
            )
            for p in predictions
        ]
        
        self.prediction_select = discord.ui.Select(
            placeholder="Choose a prediction to resolve...",
            options=options,
            custom_id="prediction_select"
        )
        self.prediction_select.callback = self.prediction_selected
        self.add_item(self.prediction_select)
    
    async def prediction_selected(self, interaction: discord.Interaction):
        """Handle prediction selection."""
        try:
            prediction_id = int(self.prediction_select.values[0])
            selected_prediction = next(p for p in self.predictions if p.id == prediction_id)
            
            # Create the options view
            view = ResolveOptionsView(selected_prediction, self.cog)
            
            await interaction.response.edit_message(
                content=f"Select the winning option for: {selected_prediction.question}",
                view=view
            )
            
        except Exception as e:
            self.cog.logger.error(f"Error in prediction selection: {str(e)}", exc_info=True)
            await interaction.response.send_message(
                "An error occurred while selecting the prediction.",
                ephemeral=True
            )

class ResolveOptionsView(discord.ui.View):
    def __init__(self, prediction, cog):
        super().__init__()
        self.prediction = prediction
        self.cog = cog
        self.logger = logging.getLogger(__name__)
        
        # Add buttons for each option
        for option in prediction.options:
            button = discord.ui.Button(
                style=discord.ButtonStyle.primary,
                label=option.text,
                custom_id=f"resolve_{prediction.id}_{option.id}"
            )
            button.callback = self.create_callback(option)
            self.add_item(button)
            
        self.logger.debug(
            f"Created resolution view for prediction {prediction.id} "
            f"with {len(prediction.options)} options"
        )

    def create_callback(self, option):
        """Create a callback for the option button."""
        async def button_callback(interaction: discord.Interaction):
            self.logger.debug(
                f"Resolution button clicked - Prediction: {self.prediction.id}, "
                f"Option: {option.id}"
            )
            
            try:
                # Resolve the prediction with the selected option
                success = await self.cog.service.resolve_prediction(
                    self.prediction.id,
                    option.id
                )
                
                if success:
                    self.logger.debug(
                        f"Successfully resolved prediction {self.prediction.id} "
                        f"with winning option {option.id}"
                    )
                    # Disable all buttons
                    for item in self.children:
                        item.disabled = True
                    
                    try:
                        # Try to edit the message with disabled buttons
                        await interaction.message.edit(view=self)
                    except discord.errors.Forbidden:
                        self.logger.warning(
                            "Could not edit message due to permissions, continuing with resolution"
                        )
                    
                    await interaction.response.send_message(
                        f"Prediction resolved! The winning option was: {option.text}",
                        ephemeral=True
                    )
                else:
                    self.logger.error(
                        f"Failed to resolve prediction {self.prediction.id}"
                    )
                    await interaction.response.send_message(
                        "Failed to resolve prediction. Please try again.",
                        ephemeral=True
                    )
                
            except Exception as e:
                self.logger.error(
                    "Error in resolution button callback: ",
                    exc_info=True
                )
                await interaction.response.send_message(
                    "An error occurred while resolving the prediction.",
                    ephemeral=True
                )
        
        return button_callback

class EconomySelectView(discord.ui.View):
    def __init__(self, prediction, option, amount, cog):
        super().__init__(timeout=180.0)
        self.prediction = prediction
        self.option = option
        self.amount = amount
        self.cog = cog
        self.logger = logging.getLogger(__name__)
        
        economies = ["Hackathon", "LocalPoints"]
        for economy in economies:
            button = discord.ui.Button(
                style=discord.ButtonStyle.primary,
                label=economy,
                custom_id=f"economy_{economy}"
            )
            button.callback = self.create_callback(economy)
            self.add_item(button)
            
        self.logger.debug(
            f"Created economy selection view for prediction {prediction.id} "
            f"with {len(economies)} economies"
        )

    def create_callback(self, economy):
        async def button_callback(interaction: discord.Interaction):
            self.logger.debug(
                f"Economy button clicked - Prediction: {self.prediction.id}, "
                f"Option: {self.option.id}, Economy: {economy}"
            )
            
            try:
                success = await self.cog.service.place_bet(
                    self.prediction.id,
                    self.option.id,
                    interaction.user.id,
                    self.amount,
                    economy
                )
                
                if success:
                    self.logger.debug(
                        f"Successfully placed bet for prediction {self.prediction.id} "
                        f"on option {self.option.id} using {economy}"
                    )
                    await interaction.response.send_message(
                        f"Bet placed on: {self.option.text} using {economy}",
                        ephemeral=True
                    )
                else:
                    self.logger.error(
                        f"Failed to place bet for prediction {self.prediction.id}"
                    )
                    await interaction.response.send_message(
                        "Failed to place bet. Please try again.",
                        ephemeral=True
                    )
                
            except Exception:
                self.logger.error(
                    "Error in economy button callback",
                    exc_info=True
                )
                await interaction.response.send_message(
                    "An error occurred while placing the bet.",
                    ephemeral=True
                )
        
        return button_callback

class BettingOptionsView(discord.ui.View):
    def __init__(self, prediction, cog):
        super().__init__()
        self.prediction = prediction
        self.cog = cog
        self.logger = logging.getLogger(__name__)
        
        # Add buttons for each option
        for option in prediction.options:
            button = discord.ui.Button(
                style=discord.ButtonStyle.primary,
                label=option.text,
                custom_id=f"bet_{prediction.id}_{option.id}"
            )
            button.callback = self.create_callback(option)
            self.add_item(button)
            
        self.logger.debug(
            f"Created betting options view for prediction {prediction.id} "
            f"with {len(prediction.options)} options"
        )

    def create_callback(self, option):
        """Create a callback for the option button."""
        async def button_callback(interaction: discord.Interaction):
            self.logger.debug(
                f"Option selected for betting - Prediction: {self.prediction.id}, "
                f"Option: {option.id}"
            )
            
            try:
                # Create a new view with the bet amount selection
                bet_amount_view = discord.ui.View()
                bet_amount_view.add_item(BetAmountSelect(
                    self.prediction,
                    option,
                    self.cog
                ))
                
                # Show the bet amount selection view
                await interaction.response.edit_message(
                    content=f"Selected: {option.text}\nChoose your bet amount:",
                    view=bet_amount_view
                )
                
            except Exception:
                self.logger.error(
                    "Error showing bet amount selection",
                    exc_info=True
                )
                await interaction.response.send_message(
                    "An error occurred while processing your selection.",
                    ephemeral=True
                )
        
        return button_callback

class BetAmountSelect(discord.ui.Select):
    def __init__(self, prediction, option, cog):
        self.prediction = prediction
        self.option = option
        self.cog = cog
        self.logger = logging.getLogger(__name__)
        
        options = [
            discord.SelectOption(label="100 points", value="100"),
            discord.SelectOption(label="500 points", value="500"),
            discord.SelectOption(label="1000 points", value="1000"),
            discord.SelectOption(label="Custom amount", value="custom")
        ]
        
        super().__init__(
            placeholder="Select bet amount...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            if self.values[0] == "custom":
                modal = CustomBetModal(self.prediction, self.option, self.cog)
                await interaction.response.send_modal(modal)
            else:
                amount = int(self.values[0])
                view = EconomySelectView(self.prediction, self.option, amount, self.cog)
                await interaction.response.edit_message(
                    content=f"Selected amount: {amount} points\nChoose economy:",
                    view=view
                )
                
        except Exception:
            self.logger.error("Error in bet amount selection", exc_info=True)
            await interaction.response.send_message(
                "An error occurred while processing your selection.",
                ephemeral=True
            )

class CustomBetModal(discord.ui.Modal):
    def __init__(self, prediction, option, cog):
        super().__init__(title="Place Custom Bet")
        self.prediction = prediction
        self.option = option
        self.cog = cog
        self.logger = logging.getLogger(__name__)
        
        self.amount = discord.ui.TextInput(
            label="Bet Amount",
            placeholder="Enter amount (e.g., 750)",
            min_length=1,
            max_length=10,
            required=True
        )
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.amount.value)
            if amount <= 0:
                await interaction.response.send_message(
                    "Bet amount must be positive.",
                    ephemeral=True
                )
                return
                
            view = EconomySelectView(self.prediction, self.option, amount, self.cog)
            await interaction.response.send_message(
                f"Selected amount: {amount} points\nChoose economy:",
                view=view,
                ephemeral=True
            )
            
        except ValueError:
            await interaction.response.send_message(
                "Please enter a valid number.",
                ephemeral=True
            )
        except Exception:
            self.logger.error("Error in custom bet modal", exc_info=True)
            await interaction.response.send_message(
                "An error occurred while processing your bet amount.",
                ephemeral=True
            )

async def setup(bot: commands.Bot) -> None:
    """Set up the prediction market cog"""
    await bot.add_cog(PredictionMarket(bot))
