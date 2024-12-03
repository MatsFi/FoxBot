from discord.ext import commands
import discord
from discord import app_commands
import datetime
import asyncio
import math
from tabulate import tabulate

def is_admin():
    def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.guild_permissions.administrator
    return app_commands.check(predicate)

class Prediction:
    def __init__(self, question, end_time, options, creator_id, category=None):
        self.question = question
        self.end_time = end_time
        self.options = options
        self.creator_id = creator_id
        self.category = category
        self.bets = {option: {} for option in options}
        self.resolved = False
        self.result = None
        self.refunded = False
        self.total_bets = 0
        # Increase initial liquidity significantly to reduce price impact
        self.initial_liquidity = 30000  # Increased from 100
        self.liquidity_pool = {option: self.initial_liquidity for option in options}
        self.k_constant = self.initial_liquidity * self.initial_liquidity  # Adjusted constant product

    def get_price(self, option, shares_to_buy):
        """Calculate price for buying shares using constant product formula"""
        if option not in self.liquidity_pool:
            return 0
        
        current_shares = self.liquidity_pool[option]
        other_shares = self.liquidity_pool[self.get_opposite_option(option)]
        
        # Using constant product formula: x * y = k
        new_shares = current_shares - shares_to_buy
        if new_shares <= 0:
            return float('inf')
        
        new_other_shares = self.k_constant / new_shares
        cost = new_other_shares - other_shares
        return max(0, cost)

    def get_opposite_option(self, option):
        """Get the opposite option in a binary market"""
        return [opt for opt in self.options if opt != option][0]

    def place_bet(self, user_id, option, points):
        """Place a bet using AMM pricing"""
        if option not in self.liquidity_pool:
            return False

        # Calculate shares user can buy with their points
        shares = self.calculate_shares_for_points(option, points)
        if shares <= 0:
            return False

        # Update liquidity pool
        self.liquidity_pool[option] -= shares
        opposite_option = self.get_opposite_option(option)
        self.liquidity_pool[opposite_option] += points

        # Record user's bet amount (not shares) for payout calculation
        if user_id in self.bets[option]:
            self.bets[option][user_id] += points
        else:
            self.bets[option][user_id] = points

        self.total_bets += points
        return True

    def calculate_shares_for_points(self, option, points):
        """Calculate how many shares user gets for their points"""
        current_shares = self.liquidity_pool[option]
        other_shares = self.liquidity_pool[self.get_opposite_option(option)]
        
        # Using constant product formula: x * y = k
        new_other_shares = other_shares + points
        new_shares = self.k_constant / new_other_shares
        shares_received = current_shares - new_shares
        return shares_received

    def get_odds(self):
        """Calculate odds based on total bets"""
        total_bets_per_option = {
            option: sum(self.bets[option].values())
            for option in self.options
        }
        total_all_bets = sum(total_bets_per_option.values())
        
        if total_all_bets == 0:
            return {option: 1/len(self.options) for option in self.options}
        
        return {
            option: total_bets_per_option[option] / total_all_bets
            for option in self.options
        }

    def get_user_payout(self, user_id):
        """Calculate payout based on shares owned and final pool state"""
        if not self.resolved or self.result is None:
            return 0
        
        shares = self.bets[self.result].get(user_id, 0)
        if shares == 0:
            return 0
            
        # Calculate payout based on final pool state
        total_pool = sum(sum(user_bets.values()) for user_bets in self.bets.values())
        share_value = total_pool / sum(self.bets[self.result].values())
        return int(shares * share_value)

    def resolve(self, result):
        if result in self.options and not self.resolved:
            self.resolved = True
            self.result = result
            return True
        return False

    def get_total_bets(self):
        return self.total_bets

    def get_option_total_bets(self, option):
        return sum(self.bets[option].values()) if option in self.bets else 0

    def get_bet_history(self):
        history = []
        for option, bets in self.bets.items():
            for user_id, amount in bets.items():
                history.append((user_id, option, amount))
        return history

    def mark_as_refunded(self):
        self.refunded = True
        self.resolved = True

    def get_current_prices(self, points_to_spend=100):
        """Calculate current prices and potential shares for a given point amount"""
        prices = {}
        
        # Calculate total bets for probability calculation
        total_bets = sum(sum(self.bets[option].values()) for option in self.options)
        if total_bets == 0:
            # If no bets yet, use equal probabilities
            base_probability = 100 / len(self.options)
            probabilities = {option: base_probability for option in self.options}
        else:
            # Calculate probabilities based on total bets per option
            probabilities = {
                option: (sum(self.bets[option].values()) / total_bets * 100)
                for option in self.options
            }
        
        for option in self.options:
            # Calculate actual shares user would get for their points
            shares = self.calculate_shares_for_points(option, points_to_spend)
            
            # Calculate actual price per share based on points spent and shares received
            price_per_share = points_to_spend / shares if shares > 0 else float('inf')
            
            prices[option] = {
                'price_per_share': price_per_share,
                'potential_shares': shares,
                'potential_payout': points_to_spend if shares > 0 else 0,
                'probability': probabilities[option],  # Now based on total bets
                'total_bets': sum(self.bets[option].values())
            }
        return prices

class OptionButton(discord.ui.Button):
    def __init__(self, label, prediction, cog, view):
        # Simplified button label - just the option name
        super().__init__(
            label=label,
            style=discord.ButtonStyle.primary,
            custom_id=f"bet_{label}"
        )
        self.prediction = prediction
        self.cog = cog
        self.option = label
        self.parent_view = view

    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.response.send_modal(AmountInput(self.prediction, self.option, self.cog))
        except Exception as e:
            print(f"Error in button callback: {e}")
            await interaction.response.send_message("An error occurred while processing your bet.", ephemeral=True)

class AmountInput(discord.ui.Modal, title="Place Your Bet"):
    def __init__(self, prediction, option, cog):
        super().__init__()
        self.prediction = prediction
        self.option = option
        self.cog = cog
        
        self.amount = discord.ui.TextInput(
            label=f"Enter amount to bet on {option}",
            style=discord.TextStyle.short,
            placeholder="Enter bet amount",
            required=True,
            min_length=1,
            max_length=10,
            default="100"
        )
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.amount.value)
            if amount <= 0:
                await interaction.response.send_message("Amount must be positive!", ephemeral=True)
                return

            # Check if prediction is still active
            if self.prediction.end_time <= datetime.datetime.utcnow():
                await interaction.response.send_message("This prediction has already ended!", ephemeral=True)
                return

            # Check user's balance
            balance = await self.cog.points_manager.get_balance(interaction.user.id)
            if balance < amount:
                await interaction.response.send_message(f"You don't have enough Points! Your balance: {balance:,} Points", ephemeral=True)
                return

            # Calculate potential shares and payout before placing bet
            shares = self.prediction.calculate_shares_for_points(self.option, amount)
            actual_price_per_share = amount / shares if shares > 0 else float('inf')

            # Transfer points and place bet
            await self.cog.points_manager.transfer_points(interaction.user.id, self.cog.bot.user.id, amount)
            if await self.cog.place_bet(interaction.user.id, self.prediction, self.option, amount):
                await interaction.response.send_message(
                    f"Bet placed successfully!\n"
                    f"Amount: {amount:,} Points\n"
                    f"Shares received: {shares:.2f}\n"
                    f"Actual price per share: {actual_price_per_share:.2f} Points",
                    ephemeral=True
                )
        except ValueError:
            await interaction.response.send_message("Invalid amount entered!", ephemeral=True)
        except Exception as e:
            print(f"Error in modal submit: {e}")
            await interaction.response.send_message("An error occurred while placing your bet.", ephemeral=True)

class OptionButtonView(discord.ui.View):
    def __init__(self, prediction, cog):
        super().__init__(timeout=None)
        self.prediction = prediction
        self.cog = cog
        self.stored_interaction = None
        self.update_buttons()
        self.update_task = None
        
        self.cog.active_views.add(self)
        # Start the auto-update task
        self.start_auto_update()

    def update_buttons(self):
        self.clear_items()
        for index, option in enumerate(self.prediction.options):
            button = OptionButton(
                option, 
                self.prediction, 
                self.cog, 
                self
            )
            button.row = index
            self.add_item(button)

    def start_auto_update(self):
        """Start the auto-update task"""
        if not self.update_task:
            self.update_task = asyncio.create_task(self.auto_update_prices())

    def stop_auto_update(self):
        """Stop the auto-update task"""
        if self.update_task:
            self.update_task.cancel()
            self.update_task = None

    async def auto_update_prices(self):
        """Auto-update prices every 5 seconds"""
        try:
            while True:
                await self.refresh_view()
                await asyncio.sleep(5)  # Wait 5 seconds before next update
        except asyncio.CancelledError:
            # Handle task cancellation
            pass
        except Exception as e:
            print(f"Error in auto_update_prices: {e}")

    async def refresh_view(self):
        """Refresh the view with current prices"""
        if self.stored_interaction:
            try:
                if self.prediction.end_time <= datetime.datetime.utcnow():
                    self.stop_auto_update()
                    await self.stored_interaction.edit(
                        content="This prediction has ended!",
                        view=None
                    )
                    return

                # Calculate prices for a small test amount to get accurate pricing
                test_amount = 10  # Use small amount for more accurate initial price
                prices = self.prediction.get_current_prices(test_amount)
                market_info = "**Current Market Status**\n\n"
                
                for option in self.prediction.options:
                    price_info = prices[option]
                    shares = price_info['potential_shares']
                    actual_price = test_amount / shares if shares > 0 else float('inf')
                    
                    market_info += f"**{option}**\n"
                    market_info += f"• Total Bets: {price_info['total_bets']:,} Points\n"
                    market_info += f"• Probability: {price_info['probability']:.1f}%\n"
                    market_info += f"• Current Price: {actual_price:.2f} Points/Share\n\n"
                
                # Add total volume
                total_volume = self.prediction.get_total_bets()
                market_info += f"\n**Total Volume**: {total_volume:,} Points"
                
                await self.stored_interaction.edit(
                    content=market_info,
                    view=self
                )
            except discord.NotFound:
                self.stop_auto_update()
                self.cog.active_views.discard(self)
            except Exception as e:
                print(f"Error refreshing view: {e}")
                self.stop_auto_update()
                self.cog.active_views.discard(self)

    def __del__(self):
        """Cleanup when the view is destroyed"""
        self.stop_auto_update()
        self.cog.active_views.discard(self)

class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.points_manager = bot.points_manager
        self.predictions = []
        self.active_views = set()

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
        category: str = None
    ):
        # Immediately acknowledge the interaction
        await interaction.response.defer(ephemeral=False)
        
        try:
            # Process options
            options_list = [opt.strip() for opt in options.split(",")]
            
            # Validate options
            if len(options_list) < 2:
                await interaction.followup.send("You need at least two options for a prediction!", ephemeral=True)
                return
            
            # Process duration
            duration_parts = duration.split(",")
            if len(duration_parts) != 3:
                await interaction.followup.send("Duration must be in format: days,hours,minutes (e.g., 1,2,30 or ,,30 or 1,,)", ephemeral=True)
                return
            
            days = int(duration_parts[0]) if duration_parts[0].strip() else 0
            hours = int(duration_parts[1]) if duration_parts[1].strip() else 0
            minutes = int(duration_parts[2]) if duration_parts[2].strip() else 0
            
            # Calculate total minutes
            total_minutes = (days * 24 * 60) + (hours * 60) + minutes
            if total_minutes <= 0:
                await interaction.followup.send("Duration must be greater than 0! Please specify days, hours, or minutes.", ephemeral=True)
                return
            
            # Create prediction object
            end_time = datetime.datetime.utcnow() + datetime.timedelta(minutes=total_minutes)
            new_prediction = Prediction(question, end_time, options_list, interaction.user.id, category)
            
            # Add to predictions list
            self.predictions.append(new_prediction)
            
            # Schedule prediction resolution
            asyncio.create_task(self.schedule_prediction_resolution(new_prediction))
            
            # Format duration string
            duration_parts = []
            if days > 0:
                duration_parts.append(f"{days} day{'s' if days != 1 else ''}")
            if hours > 0:
                duration_parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
            if minutes > 0:
                duration_parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
            duration_str = ", ".join(duration_parts)
            
            # Send confirmation message
            await interaction.followup.send(
                f"Prediction created by {interaction.user.name}:\n"
                f"Question: {question}\n"
                f"Options: {', '.join(options_list)}\n"
                f"Duration: {duration_str}\n"
                f"Category: {category if category else 'None'}",
                ephemeral=True
            )
            
        except ValueError:
            await interaction.followup.send("Invalid duration format! Please use numbers in format: days,hours,minutes (e.g., 1,2,30 or ,,30 or 1,,)", ephemeral=True)
        except Exception as e:
            try:
                await interaction.followup.send(f"Error creating prediction: {str(e)}", ephemeral=True)
            except:
                print(f"Failed to send error message: {str(e)}")

    async def schedule_prediction_resolution(self, prediction: Prediction):
        try:
            # Wait for betting period to end
            time_until_betting_ends = (prediction.end_time - datetime.datetime.utcnow()).total_seconds()
            if time_until_betting_ends > 0:
                print(f"DEBUG: Waiting {time_until_betting_ends} seconds for betting to end")
                await asyncio.sleep(time_until_betting_ends)
            
            # Don't proceed if already resolved
            if prediction.resolved:
                print("DEBUG: Prediction already resolved before betting end")
                return
                
            print(f"DEBUG: Betting period ended for {prediction.question}")
            
            # Notify creator that betting period has ended
            try:
                creator = await self.bot.fetch_user(prediction.creator_id)
                await creator.send(
                    f"🎲 Betting has ended for your prediction: '{prediction.question}'\n"
                    f"Please use `/resolve_prediction` to resolve the market.\n"
                    f"If not resolved within 48 hours, all bets will be automatically refunded."
                )
                print(f"DEBUG: Sent notification to creator {prediction.creator_id}")
            except Exception as e:
                print(f"DEBUG: Error notifying creator: {e}")

            # Wait 48 hours
            print("DEBUG: Starting 48-hour wait")
            await asyncio.sleep(48 * 3600)  # 48 hours in seconds
            
            # Check if resolved during wait
            if prediction.resolved:
                print("DEBUG: Prediction resolved during 48-hour wait")
                return
                
            print("DEBUG: Starting auto-refund process")
            
            # If we reach here, it's time to auto-refund
            prediction.mark_as_refunded()
            
            # Return all bets to users
            for option in prediction.bets:
                for user_id, amount in prediction.bets[option].items():
                    await self.points_manager.add_points(user_id, amount)
                    try:
                        user = await self.bot.fetch_user(user_id)
                        await user.send(
                            f"💰 Your bet of {amount:,} Points has been refunded for the expired market:\n"
                            f"'{prediction.question}'"
                        )
                    except Exception as e:
                        print(f"DEBUG: Error sending refund notification: {e}")
                    
        except Exception as e:
            print(f"DEBUG: Error in schedule_prediction_resolution: {e}")

    @app_commands.guild_only()
    @app_commands.command(name="bet", description="Place a bet on a prediction")
    async def bet(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # If there are no active predictions, inform the user
        active_predictions = [prediction for prediction in self.predictions if not prediction.resolved and prediction.end_time > datetime.datetime.utcnow()]
        if not active_predictions:
            await interaction.followup.send("No active predictions at the moment.", ephemeral=True)
            return

        # Get all unique categories
        categories = list(set(prediction.category for prediction in active_predictions if prediction.category))
        categories.append("All")

        # Create buttons for each category
        class CategoryButton(discord.ui.Button):
            def __init__(self, label, cog):
                super().__init__(label=label, style=discord.ButtonStyle.primary)
                self.cog = cog
                self.category = label

            async def callback(self, button_interaction: discord.Interaction):
                await button_interaction.response.defer(ephemeral=True)  # Defer the response first

                if self.category == "All":
                    filtered_predictions = active_predictions
                else:
                    filtered_predictions = [prediction for prediction in active_predictions if prediction.category == self.category]

                if not filtered_predictions:
                    await button_interaction.followup.send("No predictions available for this category.", ephemeral=True)
                    return

                # Create a Select menu to allow the user to choose an active prediction
                class PredictionSelect(discord.ui.Select):
                    def __init__(self, predictions, cog):
                        self.cog = cog
                        options = [
                            discord.SelectOption(
                                label=prediction.question, 
                                description=f"Ends at {prediction.end_time.strftime('%Y-%m-%d %H:%M:%S UTC')}", 
                                value=str(index)
                            )
                            for index, prediction in enumerate(predictions)
                        ]
                        super().__init__(placeholder="Select a prediction to bet on...", min_values=1, max_values=1, options=options)

                    async def callback(self, interaction: discord.Interaction):
                        await interaction.response.defer(ephemeral=True)
                        
                        selected_index = int(self.values[0])
                        selected_prediction = filtered_predictions[selected_index]

                        # Check if prediction has ended
                        if selected_prediction.end_time <= datetime.datetime.utcnow():
                            await interaction.followup.send("This prediction has already ended!", ephemeral=True)
                            return

                        view = OptionButtonView(selected_prediction, self.cog)
                        prices = selected_prediction.get_current_prices(100)
                        
                        market_info = "**Current Market Prices**\n\n"
                        for option in selected_prediction.options:
                            price = prices[option]['price_per_share']
                            market_info += f"{option}: {price:.2f} Points/Share\n"
                        
                        message = await interaction.followup.send(
                            content=market_info,
                            view=view, 
                            ephemeral=True,
                            wait=True  # Make sure we wait for the message to be sent
                        )
                        view.stored_interaction = message  # Store the message, not the interaction

                class PredictionSelectView(discord.ui.View):
                    def __init__(self, predictions, cog):
                        super().__init__()
                        select = PredictionSelect(predictions, cog)
                        self.add_item(select)

                await button_interaction.followup.send(  # Use followup instead of response
                    content="Please select a prediction to bet on:", 
                    view=PredictionSelectView(filtered_predictions, self.cog),
                    ephemeral=True
                )

        class CategoryButtonView(discord.ui.View):
            def __init__(self, categories, cog):
                super().__init__()
                for category in categories:
                    button = CategoryButton(label=category, cog=cog)
                    self.add_item(button)

        await interaction.followup.send("Please select a category:", view=CategoryButtonView(categories, self))

    @app_commands.guild_only()
    @app_commands.command(name="list_predictions", description="List all active predictions")
    async def list_predictions(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
            
            # Remove any existing view for this user
            for view in list(self.active_views):
                if isinstance(view, ListPredictionsView):
                    view.stop_auto_update()
                    self.active_views.discard(view)

            view = ListPredictionsView(self)
            self.active_views.add(view)  # Add to set of active views

            current_embed = discord.Embed(
                title="🎲 Prediction Markets",
                description="Current prediction markets available for betting.",
                color=discord.Color.blue()
            )

            # Initial display of markets
            active_markets = []
            inactive_markets = []
            resolved_markets = []
            refunded_markets = []
            pending_resolution_markets = []  # New list for pending resolution

            for prediction in self.predictions:
                prices = prediction.get_current_prices(100)
                combined_data = (prediction.question, prediction, prices, prediction.creator_id)

                if prediction.resolved:
                    if prediction.refunded:
                        refunded_markets.append(combined_data)
                    else:
                        resolved_markets.append(combined_data)
                elif prediction.end_time <= datetime.datetime.utcnow():
                    inactive_markets.append(combined_data)
                else:
                    active_markets.append(combined_data)

                # Check for pending resolution
                if prediction.end_time <= datetime.datetime.utcnow() and not prediction.resolved:
                    pending_resolution_markets.append(combined_data)  # Add to pending resolution

            # Add markets to embed using the same create_market_display method
            if active_markets:
                current_embed.add_field(name="🟢 Active Markets", value="\u200b", inline=False)
                for question, prediction, prices, creator_id in active_markets:
                    creator_name = (await self.bot.fetch_user(creator_id)).name
                    current_embed.add_field(
                        name=f"📊 {question} (Created by: {creator_name})",
                        value=view.create_market_display(prediction, prices),
                        inline=False
                    )

            # Add pending resolution markets
            if pending_resolution_markets:
                current_embed.add_field(name="🟡 Pending Resolution", value="\u200b", inline=False)
                for question, prediction, prices, creator_id in pending_resolution_markets:
                    creator_name = (await self.bot.fetch_user(creator_id)).name
                    current_embed.add_field(
                        name=f"📊 {question} (Created by: {creator_name})",
                        value=view.create_market_display(prediction, prices),
                        inline=False
                    )

            # Add other sections similarly...

            current_embed.set_footer(text="Use /bet to place bets on active markets")
            message = await interaction.followup.send(embed=current_embed, ephemeral=True)
            view.stored_interaction = message
            
        except Exception as e:
            await interaction.followup.send(f"An error occurred: {str(e)}", ephemeral=True)

        # Optional: Auto-cleanup after a certain time
        await asyncio.sleep(300)  # 5 minutes
        if view in self.active_views:
            view.stop_auto_update()
            self.active_views.discard(view)

    @app_commands.guild_only()
    @app_commands.command(name="resolve_prediction", description="Vote to resolve a prediction")
    async def resolve_prediction_command(self, interaction: discord.Interaction):
        # Check if the user has the required roles
        allowed_role_ids = {1301959367536672838, 1301958607046443018, 1301958999092236389}
        user_roles = {role.id for role in interaction.user.roles}

        if not user_roles.intersection(allowed_role_ids):
            await interaction.response.send_message("You do not have permission to resolve predictions.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        # Show all unresolved predictions that have ended
        unresolved_predictions = [
            pred for pred in self.predictions 
            if not pred.resolved and pred.end_time <= datetime.datetime.utcnow()
        ]
        
        if not unresolved_predictions:
            await interaction.followup.send(
                "There are no predictions ready to be resolved.", 
                ephemeral=True
            )
            return

        # Create selection menu for predictions
        class PredictionSelect(discord.ui.Select):
            def __init__(self, predictions):
                options = [
                    discord.SelectOption(
                        label=prediction.question[:100], 
                        description=f"Ended {prediction.end_time.strftime('%Y-%m-%d %H:%M:%S UTC')}", 
                        value=str(index)
                    )
                    for index, prediction in enumerate(predictions)
                ]
                super().__init__(
                    placeholder="Select a prediction to resolve...", 
                    min_values=1, 
                    max_values=1, 
                    options=options
                )

            async def callback(self, interaction: discord.Interaction):
                selected_index = int(self.values[0])
                selected_prediction = unresolved_predictions[selected_index]
                
                view = ResolutionView(selected_prediction)
                await interaction.response.send_message(
                    f"Vote for the winning option for:\n**{selected_prediction.question}**\n"
                    f"(Requires 2 votes to resolve)",
                    view=view,
                    ephemeral=False  # Make voting public
                )

        view = discord.ui.View()
        view.add_item(PredictionSelect(unresolved_predictions))
        await interaction.followup.send("Select a prediction to resolve:", view=view, ephemeral=True)

    @commands.Cog.listener()
    async def on_prediction_update(self, prediction: Prediction):
        """Event listener for when a prediction is updated"""
        if prediction in self.active_views:
            view = self.active_views[prediction]
            if view.stored_interaction:
                try:
                    await view.refresh_view(view.stored_interaction)
                except:
                    # If update fails, clean up the view
                    self.active_views.discard(prediction)

    async def update_prediction(self, prediction: Prediction):
        """Call this method whenever a bet is placed"""
        await self.on_prediction_update(prediction)

    # Modify the bet placement logic to trigger updates
    async def place_bet(self, user_id, prediction, option, amount):
        """Place a bet on a prediction"""
        try:
            success = prediction.place_bet(user_id, option, amount)
            if success:
                await self.update_prediction(prediction)
            return success
        except Exception as e:
            print(f"Error placing bet: {e}")
            return False

    async def cleanup_old_views(self):
        """Remove expired views"""
        for view in list(self.active_views):
            if hasattr(view, 'prediction'):
                if view.prediction.resolved or view.prediction.end_time <= datetime.datetime.utcnow():
                    view.stop_auto_update()
                    self.active_views.discard(view)

class ListPredictionsView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
        self.stored_interaction = None
        self.update_task = None
        self.start_auto_update()

    def start_auto_update(self):
        """Start the auto-update task"""
        if not self.update_task:
            self.update_task = asyncio.create_task(self.auto_update_markets())

    def stop_auto_update(self):
        """Stop the auto-update task"""
        if self.update_task:
            self.update_task.cancel()
            self.update_task = None

    async def auto_update_markets(self):
        """Auto-update markets every 5 seconds"""
        try:
            while True:
                await self.refresh_view()
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Error in auto_update_markets: {e}")

    def create_market_display(self, prediction, prices):
        """Create a PolyMarket-style display for a prediction"""
        market_text = (
            f"**Category:** {prediction.category or 'None'}\n"
            f"**Total Volume:** {prediction.get_total_bets():,} Points\n"
            f"**Ends:** <t:{int(prediction.end_time.timestamp())}:R>\n\n"
            "**Current Market Status:**\n"
        )

        for option in prediction.options:
            price_info = prices[option]
            market_text += (
                f"```\n"
                f"{option}\n"
                f"Price: {price_info['price_per_share']:.2f} Points/Share\n"
                f"Prob:  {price_info['probability']:.1f}%\n"
                f"Volume: {price_info['total_bets']:,} Points\n"
                f"```\n"
            )

        return market_text

    async def refresh_view(self):
        if not self.stored_interaction:
            return

        try:
            current_embed = discord.Embed(
                title="🎲 Prediction Markets",
                description="Current prediction markets available for betting.",
                color=discord.Color.blue()
            )

            active_markets = []
            inactive_markets = []
            resolved_markets = []
            refunded_markets = []
            pending_resolution_markets = []  # New list for pending resolution

            # Process each prediction
            for prediction in self.cog.predictions:
                prices = prediction.get_current_prices(100)
                combined_data = (prediction.question, prediction, prices, prediction.creator_id)

                if prediction.resolved:
                    if prediction.refunded:
                        refunded_markets.append(combined_data)
                    else:
                        resolved_markets.append(combined_data)
                elif prediction.end_time <= datetime.datetime.utcnow():
                    inactive_markets.append(combined_data)
                else:
                    active_markets.append(combined_data)

                # Check for pending resolution
                if prediction.end_time <= datetime.datetime.utcnow() and not prediction.resolved:
                    pending_resolution_markets.append(combined_data)  # Add to pending resolution

            # Add markets to embed
            if active_markets:
                current_embed.add_field(name="🟢 Active Markets", value="\u200b", inline=False)
                for question, prediction, prices, creator_id in active_markets:
                    creator_name = (await self.bot.fetch_user(creator_id)).name
                    current_embed.add_field(
                        name=f"📊 {question} (Created by: {creator_name})",
                        value=self.create_market_display(prediction, prices),
                        inline=False
                    )

            # Add pending resolution markets
            if pending_resolution_markets:
                current_embed.add_field(name="🟡 Pending Resolution", value="\u200b", inline=False)
                for question, prediction, prices, creator_id in pending_resolution_markets:
                    creator_name = (await self.bot.fetch_user(creator_id)).name
                    current_embed.add_field(
                        name=f"📊 {question} (Created by: {creator_name})",
                        value=self.create_market_display(prediction, prices),
                        inline=False
                    )

            # Add other market sections as needed...

            current_embed.set_footer(text="Use /bet to place bets on active markets")
            await self.stored_interaction.edit(embed=current_embed)

        except discord.NotFound:
            # Message was deleted
            self.stop_auto_update()
            if self in self.cog.active_views:
                self.cog.active_views.discard(self)
        except discord.HTTPException as e:
            if e.code == 50027:  # Invalid Webhook Token
                # Token expired, stop updates
                print("Interaction token expired, stopping updates")
                self.stop_auto_update()
                if self in self.cog.active_views:
                    self.cog.active_views.discard(self)
            else:
                print(f"HTTP Exception in refresh_view: {e}")
        except Exception as e:
            print(f"Error refreshing list view: {e}")
            self.stop_auto_update()

    def __del__(self):
        """Cleanup when the view is destroyed"""
        self.stop_auto_update()
        self.cog.active_views.discard(self)

class ResolutionButton(discord.ui.Button):
    def __init__(self, option: str, prediction: Prediction):
        super().__init__(
            label=option,
            style=discord.ButtonStyle.primary,
            custom_id=f"resolve_{option}"
        )
        self.option = option
        self.prediction = prediction
        self.votes = set()  # Store user IDs who voted for this option
        self.user_votes = set()  # Store user IDs who voted for any option in this prediction
        
    async def callback(self, interaction: discord.Interaction):
        # Check if the user has the required roles
        allowed_role_ids = {1301959367536672838, 1301958607046443018, 1301958999092236389}
        user_roles = {role.id for role in interaction.user.roles}

        if not user_roles.intersection(allowed_role_ids):
            await interaction.response.send_message("You do not have permission to vote.", ephemeral=True)
            return

        # Check if the user has already voted for any option
        if interaction.user.id in self.user_votes:
            await interaction.response.send_message("You have already voted on this prediction!", ephemeral=True)
            return

        # Mark the user as having voted
        self.user_votes.add(interaction.user.id)

        # Allow the user to vote for this option
        self.votes.add(interaction.user.id)
        await interaction.response.send_message(f"You have voted for {self.option}.", ephemeral=True)

        # Disable all buttons after voting
        for child in self.view.children:
            child.disabled = True
        
        # Check if threshold reached (2 votes)
        if len(self.votes) >= 2:
            if not self.prediction.resolved:
                self.prediction.resolve(self.option)
                
                # Process payouts and notifications
                total_payout = self.prediction.get_total_bets()
                winning_users = self.prediction.bets[self.option].items()
                
                for user_id, original_bet in winning_users:
                    payout = self.prediction.get_user_payout(user_id)
                    if payout > 0:
                        payout_amount = int(payout)
                        await interaction.client.points_manager.add_points(user_id, payout_amount)
                        profit = payout_amount - original_bet
                        
                        try:
                            user = await interaction.client.fetch_user(user_id)
                            await user.send(
                                f"🎉 You won {profit:,} Points on '{self.prediction.question}'!\n"
                                f"Bet: {original_bet:,} → Payout: {payout_amount:,}"
                            )
                        except Exception as e:
                            print(f"Error sending winning notification to user {user_id}: {e}")
        
            # Send a message announcing the winning option
            await interaction.channel.send(
                f"Market resolved! The winning option is: {self.option}"
            )
        
        # Update the message to show resolution
        view = self.view
        for child in view.children:
            if child.custom_id == f"resolve_{self.option}":
                child.style = discord.ButtonStyle.success
            else:
                child.style = discord.ButtonStyle.danger
        
        await interaction.message.edit(
            content=f"Voting has ended for this market.",
            view=view
        )

class ResolutionView(discord.ui.View):
    def __init__(self, prediction: Prediction):
        super().__init__(timeout=None)
        for option in prediction.options:
            self.add_item(ResolutionButton(option, prediction))

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Economy(bot))