from datetime import datetime
from typing import List, Optional, Tuple, Literal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from database.models import Prediction, PredictionBet
from utils.exceptions import (
    PredictionNotFoundError,
    InsufficientPointsError,
    InvalidAmountError,
    PredictionMarketError,
    PredictionAlreadyResolvedError,
    UnauthorizedResolutionError,
    InvalidOptionError
)
from sqlalchemy.orm import selectinload
import logging
import asyncio
import discord
from datetime import datetime, timezone

class PredictionMarketService:
    def __init__(self, session_factory, bot, points_service=None):
        self.session_factory = session_factory
        self.bot = bot
        self.points_service = points_service
        self.logger = logging.getLogger(__name__)
        self._market_balance = {}
        self._running = False
        self._notification_tasks = {}  # Track notification tasks by prediction ID

    async def start(self):
        """Initialize the service and load existing predictions."""
        self.logger.info("Starting prediction market service...")
        self._running = True
        
        # Load existing predictions with bets using joinedload
        query = (
            select(Prediction)
            .options(selectinload(Prediction.bets))
            .where(Prediction.resolved == False)
        )
        
        async with self.session_factory() as session:
            result = await session.execute(query)
            active_predictions = result.scalars().all()
            
            # Initialize market balances
            for pred in active_predictions:
                self._market_balance[pred.id] = {}
                for bet in pred.bets:
                    if bet.source_economy not in self._market_balance[pred.id]:
                        self._market_balance[pred.id][bet.source_economy] = 0
                    self._market_balance[pred.id][bet.source_economy] += bet.amount
                    
        self.logger.info(f"Loaded {len(active_predictions)} active predictions")
        self.logger.info("Prediction market service started")

    async def stop(self):
        """Cleanup service resources."""
        self.logger.info("Stopping prediction market service...")
        self._running = False
        
        # Clear market balance cache
        self._market_balance.clear()
        self.logger.info("Market balance cache cleared")
        
        # Cancel all pending notifications
        for task in self._notification_tasks.values():
            task.cancel()
        self._notification_tasks.clear()
        
        self.logger.info("Prediction market service stopped")

    async def create_prediction(
        self,
        question: str,
        options: List[str],
        creator_id: str,
        end_time: datetime,
        category: Optional[str] = None,
        channel_id: Optional[str] = None
    ) -> Prediction:
        """Create a new prediction market."""
        async with self.session_factory() as session:
            prediction = Prediction(
                question=question,
                options=options,
                creator_id=creator_id,
                end_time=end_time,
                category=category,
                channel_id=channel_id
            )
            session.add(prediction)
            await session.commit()
            await session.refresh(prediction)

            # Schedule end notification
            if channel_id:
                self._schedule_end_notification(prediction)
            
            return prediction

    def _schedule_end_notification(self, prediction: Prediction):
        """Schedule a notification for when the prediction ends."""
        async def notify_end():
            try:
                # Wait until end time
                now = datetime.utcnow()
                if prediction.end_time > now:
                    delay = (prediction.end_time - now).total_seconds()
                    await asyncio.sleep(delay)
                
                # Send channel notification
                channel = self.bot.get_channel(int(prediction.channel_id))
                if channel:
                    embed = discord.Embed(
                        title="🎯 Prediction Ended!",
                        description=f"The following prediction has ended and is ready to be resolved:\n\n"
                                  f"**{prediction.question}**",
                        color=discord.Color.blue()
                    )
                    embed.add_field(
                        name="Options",
                        value="\n".join(f"• {option}" for option in prediction.options)
                    )
                    embed.add_field(
                        name="Creator",
                        value=f"<@{prediction.creator_id}>"
                    )
                    await channel.send(
                        f"<@{prediction.creator_id}> Your prediction has ended!",
                        embed=embed
                    )
                
                # Also send DM to creator
                creator = await self.bot.fetch_user(int(prediction.creator_id))
                if creator:
                    try:
                        await creator.send(
                            f"🎯 Your prediction has ended and is ready to be resolved:\n"
                            f"'{prediction.question}'\n\n"
                            f"Use `/resolve` in the server to select the winning option!"
                        )
                    except discord.Forbidden:
                        self.logger.warning(f"Could not DM user {prediction.creator_id}")

            except Exception as e:
                self.logger.error(f"Error in end notification for prediction {prediction.id}: {e}")

        # Start notification task
        task = asyncio.create_task(notify_end())
        self._notification_tasks[prediction.id] = task

    async def get_prediction(self, prediction_id: int) -> Optional[Prediction]:
        """Get a prediction by ID."""
        async with self.session_factory() as session:
            stmt = (
                select(Prediction)
                .where(Prediction.id == prediction_id)
                .options(selectinload(Prediction.bets))
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_active_predictions(
        self,
        category: Optional[str] = None
    ) -> List[Prediction]:
        """Get all active predictions, optionally filtered by category."""
        async with self.session_factory() as session:
            stmt = (
                select(Prediction)
                .where(Prediction.resolved == False)
                .where(Prediction.end_time > datetime.utcnow())
                .options(
                    selectinload(Prediction.bets)  # Eagerly load bets relationship
                )
            )
            
            if category:
                stmt = stmt.where(Prediction.category == category)
            
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_resolvable_predictions(
        self,
        creator_id: str
    ) -> List[Prediction]:
        """Get predictions that can be resolved by this user."""
        try:
            async with self.session_factory() as session:
                stmt = (
                    select(Prediction)
                    .where(Prediction.creator_id == creator_id)
                    .where(Prediction.resolved == False)
                    .where(Prediction.end_time <= datetime.now(timezone.utc))
                    .options(selectinload(Prediction.bets))  # Eagerly load bets
                )
                
                result = await session.execute(stmt)
                predictions = list(result.scalars().all())
                
                self.logger.info(
                    f"Found {len(predictions)} resolvable predictions for user {creator_id}"
                )
                
                return predictions
                
        except Exception as e:
            self.logger.error(f"Error getting resolvable predictions: {e}")
            return []

    def get_available_economies(self) -> List[str]:
        """Get list of available external economies."""
        # Get registered external economies from transfer service
        if not hasattr(self.bot, 'transfer_service'):
            self.logger.warning("Transfer service not initialized")
            return []
            
        return list(self.bot.transfer_service._external_services.keys())

    async def place_bet(
        self,
        prediction_id: int,
        user_id: str,
        option: str,
        amount: int,
        economy: str
    ) -> PredictionBet:
        """Place a bet on a prediction."""
        try:
            # Get the external service through transfer service
            external_service = self.bot.transfer_service.get_external_service(economy)
            
            # Attempt to deduct points using the external service interface
            if not await external_service.remove_points(int(user_id), amount):
                raise InsufficientPointsError(f"Insufficient {economy} points")

            # Create and save the bet using 2.0 style
            async with self.session_factory() as session:
                bet = PredictionBet(
                    prediction_id=prediction_id,
                    user_id=user_id,
                    option=option,
                    amount=amount,
                    source_economy=economy
                )
                session.add(bet)
                await session.commit()
                await session.refresh(bet)

                # Update market balance
                if prediction_id not in self._market_balance:
                    self._market_balance[prediction_id] = {}
                if economy not in self._market_balance[prediction_id]:
                    self._market_balance[prediction_id][economy] = 0
                self._market_balance[prediction_id][economy] += amount

                return bet

        except ValueError as e:
            raise PredictionMarketError(f"Unknown economy: {economy}")
        except InsufficientPointsError:
            raise
        except Exception as e:
            self.logger.error(f"Error placing bet: {e}")
            raise

    async def resolve_prediction(
        self,
        prediction_id: int,
        result: str,
        resolver_id: str
    ) -> Tuple[Prediction, List[Tuple[str, int, str]]]:
        """Resolve a prediction and process payouts."""
        try:
            async with self.session_factory() as session:
                async with session.begin():
                    # Get prediction with bets eagerly loaded
                    stmt = (
                        select(Prediction)
                        .where(Prediction.id == prediction_id)
                        .options(selectinload(Prediction.bets))  # Eagerly load bets
                        .with_for_update()
                    )
                    result_proxy = await session.execute(stmt)
                    prediction = result_proxy.scalar_one_or_none()
                    
                    if not prediction:
                        raise PredictionNotFoundError(prediction_id)

                    if prediction.resolved:
                        raise PredictionAlreadyResolvedError("This prediction has already been resolved")

                    if prediction.creator_id != resolver_id:
                        raise UnauthorizedResolutionError()

                    if result not in prediction.options:
                        raise InvalidOptionError(result)

                    # Calculate total pool and winning pool
                    total_pool = prediction.total_pool  # Now safe to access
                    winning_pool = prediction.get_option_total(result)  # Now safe to access

                    # Process payouts
                    payouts = []
                    if winning_pool > 0:
                        for bet in prediction.bets:
                            if bet.option == result:
                                payout = int((bet.amount / winning_pool) * total_pool)
                                
                                if bet.source_economy != 'local':
                                    try:
                                        external_service = self.bot.transfer_service.get_external_service(bet.source_economy)
                                        if await external_service.add_points(int(bet.user_id), payout):
                                            payouts.append((bet.user_id, payout, bet.source_economy))
                                    except ValueError as e:
                                        self.logger.error(f"Error during payout: {e}")
                                else:
                                    if await self.points_service.transfer(
                                        from_id="HOUSE",
                                        to_id=bet.user_id,
                                        amount=payout,
                                        economy='local'
                                    ):
                                        payouts.append((bet.user_id, payout, 'local'))

                    # Mark as resolved
                    prediction.resolved = True
                    prediction.result = result
                    await session.commit()

                    return prediction, payouts

        except Exception as e:
            self.logger.error(f"Error resolving prediction: {e}")
            raise