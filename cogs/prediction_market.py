from discord.ext import commands
import discord
from discord import app_commands
from typing import Optional
from datetime import datetime, timezone, timedelta
import logging
from services import PredictionMarketService

def is_admin():
    def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.guild_permissions.administrator
    return app_commands.check(predicate)

class PredictionMarket(commands.Cog):
    """Prediction market commands for betting on outcomes."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.service = None  # Initialize as None
        self.logger = logging.getLogger(__name__)
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
                embed = discord.Embed(
                    title="🎲 Prediction Market",
                    description=prediction['question'],
                    color=discord.Color.blue(),
                    timestamp=prediction['created_at']
                )
                
                self.logger.debug(f"Getting prices for prediction {prediction['id']}")
                prices = await self.service.get_current_prices(prediction['id'])
                
                # Status field
                status = "🟢 Active" if not prediction['resolved'] else "✅ Resolved"
                if prediction['refunded']:
                    status = "💰 Refunded"
                embed.add_field(name="Status", value=status, inline=True)
                
                # Time fields
                embed.add_field(
                    name="Ends",
                    value=discord.utils.format_dt(prediction['end_time'], 'R'),
                    inline=True
                )
                
                # Options and odds
                options_text = ""
                for option_text, price_info in prices.items():
                    prob = (1 / price_info['price_per_share']) * 100 if price_info['price_per_share'] > 0 else 0
                    options_text += f"\n{option_text}: {prob:.1f}%"
                embed.add_field(name="Options", value=options_text, inline=False)
                
                # Volume
                embed.add_field(
                    name="Total Volume",
                    value=f"{prediction['total_bets']:,} points",
                    inline=True
                )
                
                if prediction['category']:
                    embed.add_field(name="Category", value=prediction['category'], inline=True)
                
                self.logger.debug(f"Fetching creator user for prediction {prediction['id']}")
                creator = await self.bot.fetch_user(prediction['creator_id'])
                embed.set_footer(text=f"Created by {creator.display_name}")
                
                pages.append(embed)

            self.logger.debug("Creating and starting paginated view")
            view = PaginatedPredictionView(pages)
            await view.start(interaction)

        except Exception as e:
            self.logger.error(f"Error listing predictions: {e}", exc_info=True)
            await interaction.followup.send(
                "An error occurred while listing predictions.",
                ephemeral=True
            )
    
    @app_commands.guild_only()
    @app_commands.command(name="create_prediction", description="Create a new prediction market")
    async def create_prediction(
        self, 
        interaction: discord.Interaction, 
        question: str, 
        options: str, 
        duration: str,
        category: Optional[str] = None
    ):
        await interaction.response.defer(ephemeral=False)
        
        try:
            # Process options
            options_list = [opt.strip() for opt in options.split(",")]
            if len(options_list) != 2:  # AMM currently supports binary markets only
                await interaction.followup.send(
                    "Currently only binary predictions (exactly 2 options) are supported!", 
                    ephemeral=True
                )
                return
            
            # Process duration
            duration_parts = duration.split(",")
            if len(duration_parts) != 3:
                await interaction.followup.send(
                    "Duration must be in format: days,hours,minutes (e.g., 1,2,30 or ,,30 or 1,,)", 
                    ephemeral=True
                )
                return
            
            days = int(duration_parts[0]) if duration_parts[0].strip() else 0
            hours = int(duration_parts[1]) if duration_parts[1].strip() else 0
            minutes = int(duration_parts[2]) if duration_parts[2].strip() else 0
            
            total_minutes = (days * 24 * 60) + (hours * 60) + minutes
            if total_minutes <= 0:
                await interaction.followup.send(
                    "Duration must be greater than 0!", 
                    ephemeral=True
                )
                return
            
            # Calculate end time in UTC
            end_time = datetime.now(timezone.utc) + timedelta(minutes=total_minutes)
            
            # Create prediction through service
            prediction = await self.service.create_prediction(
                question=question,
                options=options_list,
                end_time=end_time,
                creator_id=interaction.user.id,
                category=category
            )
            
            # Format duration string for display
            duration_parts = []
            if days > 0:
                duration_parts.append(f"{days} day{'s' if days != 1 else ''}")
            if hours > 0:
                duration_parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
            if minutes > 0:
                duration_parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
            duration_str = ", ".join(duration_parts)
            
            # Create embed for response
            embed = discord.Embed(
                title="🎲 New Prediction Market Created",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="Question", value=question, inline=False)
            embed.add_field(name="Options", value="\n".join(options_list), inline=False)
            embed.add_field(name="Duration", value=duration_str, inline=True)
            embed.add_field(name="Ends", value=f"<t:{int(end_time.timestamp())}:R>", inline=True)
            if category:
                embed.add_field(name="Category", value=category, inline=True)
            embed.set_footer(text=f"Created by {interaction.user.display_name}")
            
            await interaction.followup.send(embed=embed)
            
        except ValueError as e:
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
        except Exception as e:
            self.logger.error(f"Error creating prediction: {e}")
            await interaction.followup.send(
                "An error occurred while creating the prediction.", 
                ephemeral=True
            )

    @app_commands.guild_only()
    @app_commands.command(name="bet", description="Place a bet on a prediction")
    async def bet(self, interaction: discord.Interaction):
        self.logger.debug("Starting bet command")
        await interaction.response.defer(ephemeral=True)

        try:
            self.logger.debug(f"Checking service state in bet command:")
            self.logger.debug(f"Self service: {self.service}")
            self.logger.debug(f"Bot prediction_market_service: {self.bot.prediction_market_service}")
            self.logger.debug(f"Bot service type: {type(self.bot.prediction_market_service)}")
            
            if self.service is None:
                self.logger.error("Prediction market service is None!")
                if hasattr(self.bot, 'prediction_market_service'):
                    self.logger.debug("Bot has prediction_market_service attribute")
                    self.service = self.bot.prediction_market_service
                    self.logger.debug(f"Reattached service: {self.service}")
                else:
                    self.logger.error("Bot missing prediction_market_service attribute!")
                    await interaction.followup.send(
                        "Prediction market service not available. Please try again later.",
                        ephemeral=True
                    )
                    return

            self.logger.debug("Fetching active predictions")
            active_predictions = await self.service.get_active_predictions()
            self.logger.debug(f"Found {len(active_predictions) if active_predictions else 0} active predictions")

            if not active_predictions:
                self.logger.debug("No active predictions found")
                await interaction.followup.send("No active predictions at the moment.", ephemeral=True)
                return

            self.logger.debug("Creating prediction selection view")
            view = PredictionSelectView(active_predictions, self)
            self.logger.debug("Sending selection view to user")
            await interaction.followup.send(
                "Select a prediction to bet on:", 
                view=view, 
                ephemeral=True
            )

        except Exception as e:
            self.logger.error(f"Error in bet command: {e}", exc_info=True)
            await interaction.followup.send(
                "An error occurred while processing the bet command.",
                ephemeral=True
            )

    @app_commands.guild_only()
    @app_commands.command(name="resolve_prediction", description="Resolve a prediction")
    async def resolve_prediction_command(self, interaction: discord.Interaction):
        self.logger.debug("Starting resolve_prediction_command")
        await interaction.response.defer(ephemeral=True)

        try:
            self.logger.debug("Fetching unresolved predictions for user")
            unresolved_predictions = await self.service.get_resolvable_predictions(interaction.user.id)
            self.logger.debug(f"Found {len(unresolved_predictions) if unresolved_predictions else 0} unresolved predictions")

            if not unresolved_predictions:
                self.logger.debug("No unresolved predictions found for user")
                await interaction.followup.send(
                    "You don't have any unresolved predictions to resolve. "
                    "Only the creator of a prediction can resolve it.", 
                    ephemeral=True
                )
                return

            self.logger.debug("Creating prediction selection view")
            view = ResolvePredictionView(unresolved_predictions, self)
            self.logger.debug("Sending selection view to user")
            await interaction.followup.send(
                "Select a prediction to resolve:",
                view=view,
                ephemeral=True
            )

        except Exception as e:
            self.logger.error(f"Error in resolve_prediction_command: {e}", exc_info=True)
            await interaction.followup.send(
                "An error occurred while processing the resolve prediction command.",
                ephemeral=True
            )

    async def cleanup_old_views(self):
        """Remove views for resolved or expired predictions."""
        for prediction_id in list(self.active_views.keys()):
            prediction = await self.service.get_prediction(prediction_id)
            if (prediction.resolved or 
                prediction.end_time <= datetime.now(timezone.utc)):
                del self.active_views[prediction_id]

class PredictionSelectView(discord.ui.View):
    def __init__(self, predictions, cog):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self.logger.debug("Initializing PredictionSelectView")
        self.add_item(PredictionSelect(predictions, cog))

class PredictionSelect(discord.ui.Select):
    def __init__(self, predictions, cog):
        self.logger = logging.getLogger(__name__)
        self.logger.debug("Initializing PredictionSelect")
        self.cog = cog
        
        try:
            options = [
                discord.SelectOption(
                    label=pred.question[:100],
                    description=f"Ends {discord.utils.format_dt(pred.end_time, 'R')}",
                    value=str(pred.id)
                )
                for pred in predictions
            ]
            self.logger.debug(f"Created {len(options)} select options")
            
            super().__init__(
                placeholder="Choose a prediction...",
                min_values=1,
                max_values=1,
                options=options
            )
        except Exception as e:
            self.logger.error(f"Error creating PredictionSelect: {e}", exc_info=True)
            raise

    async def callback(self, interaction: discord.Interaction):
        self.logger.debug("PredictionSelect callback triggered")
        try:
            prediction_id = int(self.values[0])
            self.logger.debug(f"Selected prediction ID: {prediction_id}")
            
            self.logger.debug("Getting current prices")
            prices = await self.cog.service.get_current_prices(prediction_id)
            self.logger.debug(f"Retrieved prices: {prices}")
            
            self.logger.debug("Creating betting options view")
            view = BettingOptionsView(prediction_id, prices, self.cog)
            self.logger.debug("Updating interaction with betting options")
            await interaction.response.edit_message(
                content="Select an option to bet on:",
                view=view
            )
            
        except Exception as e:
            self.logger.error(f"Error in PredictionSelect callback: {e}", exc_info=True)
            await interaction.response.send_message(
                "An error occurred while processing your selection.",
                ephemeral=True
            )

class BettingOptionsView(discord.ui.View):
    def __init__(self, prediction_id: int, prices: dict, cog):
        super().__init__()
        self.prediction_id = prediction_id
        self.cog = cog
        
        # Only add economy selector if multiple economies are available
        available_economies = cog.service.available_economies
        if len(available_economies) > 1:
            self.add_item(EconomySelect(available_economies))
        
        # Then add betting options
        for option_text, price_info in prices.items():
            button = BettingOptionButton(
                option_text,
                price_info,
                prediction_id,
                cog,
                # If only one economy, pass it directly
                economy=available_economies[0] if len(available_economies) == 1 else None
            )
            self.add_item(button)

class EconomySelect(discord.ui.Select):
    def __init__(self, available_economies):
        options = [
            discord.SelectOption(
                label=economy,
                description=f"Bet using {economy} points"
            )
            for economy in available_economies
        ]
        super().__init__(
            placeholder="Select economy to bet with",
            min_values=1,
            max_values=1,
            options=options
        )

class BettingOptionButton(discord.ui.Button):
    def __init__(self, option_text: str, price_info: dict, prediction_id: int, cog, economy=None):
        # Format price info for display
        price = price_info['price_per_share']
        prob = (1 / price) * 100 if price > 0 else 0
        
        super().__init__(
            label=f"{option_text}\n{prob:.1f}% ({price:.2f} pts/share)",
            style=discord.ButtonStyle.primary
        )
        self.option_text = option_text
        self.prediction_id = prediction_id
        self.cog = cog
        self.price_info = price_info
        self.economy = economy  # Store single economy if provided

    async def callback(self, interaction: discord.Interaction):
        # Get economy from select if multiple economies, or use the single economy
        if self.economy is None:
            # Find the economy select in the view
            economy_select = [item for item in self.view.children if isinstance(item, EconomySelect)][0]
            if not economy_select.values:
                await interaction.response.send_message(
                    "Please select an economy first!",
                    ephemeral=True
                )
                return
            economy = economy_select.values[0]
        else:
            economy = self.economy

        # Show bet amount modal with the determined economy
        modal = BetAmountModal(
            self.prediction_id,
            self.option_text,
            self.price_info,
            self.cog,
            economy
        )
        await interaction.response.send_modal(modal)

class BetAmountModal(discord.ui.Modal, title="Place Your Bet"):
    def __init__(self, prediction_id: int, option_text: str, price_info: dict, cog, economy: str):
        super().__init__()
        self.prediction_id = prediction_id
        self.option_text = option_text
        self.price_info = price_info
        self.cog = cog
        self.economy = economy

        self.amount = discord.ui.TextInput(
            label=f"Bet amount ({economy} points)",
            placeholder="Enter amount to bet",
            required=True,
            min_length=1,
            max_length=10
        )
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.amount.value)
            if amount <= 0:
                await interaction.response.send_message(
                    "Bet amount must be positive!",
                    ephemeral=True
                )
                return

            success = await self.cog.service.place_bet(
                prediction_id=self.prediction_id,
                option_text=self.option_text,
                user_id=interaction.user.id,
                amount=amount,
                economy=self.economy
            )

            if success:
                # Calculate potential payout
                shares = self.price_info['potential_shares']
                potential_payout = self.price_info['potential_payout']
                
                embed = discord.Embed(
                    title="🎲 Bet Placed Successfully",
                    color=discord.Color.green(),
                    timestamp=datetime.now(timezone.utc)
                )
                embed.add_field(name="Amount", value=f"{amount:,} points", inline=True)
                embed.add_field(name="Option", value=self.option_text, inline=True)
                embed.add_field(name="Shares", value=f"{shares:.2f}", inline=True)
                embed.add_field(name="Potential Payout", value=f"{potential_payout:.2f} points", inline=True)
                
                await interaction.response.send_message(
                    embed=embed,
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "Failed to place bet. Please try again.",
                    ephemeral=True
                )

        except ValueError:
            await interaction.response.send_message(
                "Please enter a valid number!",
                ephemeral=True
            )
        except Exception as e:
            self.cog.logger.error(f"Error placing bet: {e}")
            await interaction.response.send_message(
                "An error occurred while placing your bet.",
                ephemeral=True
            )

class PaginatedPredictionView(discord.ui.View):
    def __init__(self, pages):
        super().__init__()
        self.pages = pages
        self.current_page = 0

    async def start(self, interaction: discord.Interaction):
        await interaction.followup.send(
            embed=self.pages[0],
            view=self,
            ephemeral=True
        )

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.gray)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = (self.current_page - 1) % len(self.pages)
        await interaction.response.edit_message(
            embed=self.pages[self.current_page],
            view=self
        )

    @discord.ui.button(label="Next", style=discord.ButtonStyle.gray)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = (self.current_page + 1) % len(self.pages)
        await interaction.response.edit_message(
            embed=self.pages[self.current_page],
            view=self
        )

class ResolvePredictionView(discord.ui.View):
    def __init__(self, predictions, cog):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self.logger.debug("Initializing ResolvePredictionView")
        self.add_item(ResolvePredictionSelect(predictions, cog))

class ResolvePredictionSelect(discord.ui.Select):
    def __init__(self, predictions, cog):
        self.logger = logging.getLogger(__name__)
        self.logger.debug("Initializing ResolvePredictionSelect")
        self.cog = cog
        options = [
            discord.SelectOption(
                label=pred.question[:100],
                description=f"Ended {discord.utils.format_dt(pred.end_time, 'R')}",
                value=str(pred.id)
            )
            for pred in predictions
        ]
        self.logger.debug(f"Created {len(options)} select options")
        super().__init__(
            placeholder="Select a prediction to resolve...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        self.logger.debug("ResolvePredictionSelect callback triggered")
        try:
            prediction_id = int(self.values[0])
            self.logger.debug(f"Selected prediction ID: {prediction_id}")
            
            # Get prediction options
            prediction = await self.cog.service.get_prediction(prediction_id)
            if not prediction:
                self.logger.error(f"Prediction {prediction_id} not found")
                await interaction.response.send_message(
                    "Prediction not found.",
                    ephemeral=True
                )
                return

            # Create resolution options view
            self.logger.debug("Creating resolution options view")
            view = ResolveOptionsView(prediction, self.cog)
            self.logger.debug("Updating interaction with resolution options")
            await interaction.response.edit_message(
                content="Select the winning option:",
                view=view
            )
            
        except Exception as e:
            self.logger.error(f"Error in ResolvePredictionSelect callback: {e}", exc_info=True)
            await interaction.response.send_message(
                "An error occurred while processing your selection.",
                ephemeral=True
            )

class ResolveOptionsView(discord.ui.View):
    def __init__(self, prediction, cog):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self.logger.debug(f"Initializing ResolveOptionsView for prediction {prediction.id}")
        self.prediction = prediction
        self.cog = cog
        
        # Add button for each option
        for option in prediction.options:
            self.logger.debug(f"Adding resolution button for option: {option.text}")
            button = ResolveOptionButton(option.text, prediction.id, cog)
            self.add_item(button)

class ResolveOptionButton(discord.ui.Button):
    def __init__(self, option_text: str, prediction_id: int, cog):
        super().__init__(
            label=option_text,
            style=discord.ButtonStyle.primary
        )
        self.logger = logging.getLogger(__name__)
        self.option_text = option_text
        self.prediction_id = prediction_id
        self.cog = cog
        self.logger.debug(f"Initialized resolution button for option: {option_text}")

    async def callback(self, interaction: discord.Interaction):
        self.logger.debug(f"Resolution button callback triggered for option: {self.option_text}")
        try:
            # Resolve the prediction through service
            self.logger.debug(f"Attempting to resolve prediction {self.prediction_id} with winner: {self.option_text}")
            success = await self.cog.service.resolve_prediction(
                prediction_id=self.prediction_id,
                winning_option=self.option_text,
                resolver_id=interaction.user.id
            )

            if success:
                self.logger.debug("Resolution successful, getting payout information")
                # Get payout information
                total_bets = await self.cog.service.get_prediction_total_bets(self.prediction_id)
                winning_bets = await self.cog.service.get_winning_bets(self.prediction_id)
                
                embed = discord.Embed(
                    title="Prediction Resolved",
                    color=discord.Color.green(),
                    timestamp=datetime.now(timezone.utc)
                )
                embed.add_field(name="Winning Option", value=self.option_text, inline=False)
                embed.add_field(name="Total Pool", value=f"{total_bets:,} points", inline=True)
                embed.add_field(name="Winning Bets", value=f"{len(winning_bets)} bets", inline=True)
                
                self.logger.debug("Sending resolution success message")
                await interaction.response.edit_message(
                    content=None,
                    embed=embed,
                    view=None
                )
                
                self.logger.info(f"Prediction {self.prediction_id} resolved with winner: {self.option_text}")
            else:
                self.logger.error(f"Failed to resolve prediction {self.prediction_id}")
                await interaction.response.send_message(
                    "Failed to resolve prediction. It may have already been resolved.",
                    ephemeral=True
                )

        except Exception as e:
            self.logger.error(f"Error resolving prediction: {e}", exc_info=True)
            await interaction.response.send_message(
                "An error occurred while resolving the prediction.",
                ephemeral=True
            )

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PredictionMarket(bot))
    
