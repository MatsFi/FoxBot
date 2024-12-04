from __future__ import annotations
from typing import Optional, List, Tuple, Dict
from datetime import datetime
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload
from database.models import Prediction, PredictionOption, Bet, utc_now
import logging
import asyncio
class MarketStateError(Exception):
    """Raised when market is in invalid state for operation."""
    pass

class InvalidBetError(Exception):
    """Raised when bet parameters are invalid."""
    pass

class InsufficientLiquidityError(Exception):
    """Raised when market has insufficient liquidity."""
    pass

class PredictionMarketService:
    """Service for managing prediction market operations."""
    
    def __init__(self, database, bot) -> None:
        self.db = database
        self.bot = bot
        self.logger = logging.getLogger(__name__)

    @classmethod
    def from_bot(cls, bot) -> PredictionMarketService:
        """Create a PredictionMarketService instance from a bot instance."""
        return cls(database=bot.database, bot=bot)

    async def initialize(self) -> None:
        """Initialize the prediction market service."""
        self.logger.info("PredictionMarketService initialized successfully")

    async def create_prediction(
        self,
        question: str,
        options: List[str],
        end_time: datetime,
        creator_id: int,
        category: Optional[str] = None
    ) -> Tuple[bool, str, Optional[Prediction]]:
        """Create a new prediction market."""
        self.logger.debug(f"Creating prediction: {question} with options: {options}")
        async with self.db.session() as session:
            try:
                prediction = Prediction(
                    question=question,
                    end_time=end_time,
                    creator_id=creator_id,
                    category=category,
                    initial_liquidity=100
                )
                prediction.options = [
                    PredictionOption(text=option) for option in options
                ]
                session.add(prediction)
                await session.commit()
                self.logger.info(f"Created prediction {prediction.id}: {question}")
                
                # Schedule resolution
                asyncio.create_task(self.schedule_prediction_resolution(prediction))
                
                return True, "Prediction market created successfully.", prediction
            except Exception as e:
                await session.rollback()
                self.logger.error(f"Error creating prediction: {e}", exc_info=True)
                return False, f"Failed to create prediction market: {str(e)}", None

    async def get_active_markets(self, skip: int = 0, limit: int = 10) -> List[Prediction]:
        """Get active (unresolved) prediction markets."""
        self.logger.debug(f"Fetching active markets (skip={skip}, limit={limit})")
        async with self.db.session() as session:
            try:
                query = (
                    select(Prediction)
                    .options(
                        selectinload(Prediction.options),
                        selectinload(Prediction.bets)
                    )
                    .where(Prediction.resolved == False)
                    .order_by(Prediction.end_time.asc())
                    .offset(skip)
                    .limit(limit)
                )
                result = await session.execute(query)
                markets = list(result.scalars().all())
                self.logger.debug(f"Found {len(markets)} active markets")
                return markets
            except Exception as e:
                self.logger.error(f"Error fetching active markets: {e}", exc_info=True)
                return []

    async def get_prediction(self, prediction_id: int) -> Optional[Prediction]:
        """Fetch a prediction by ID with options and bets preloaded."""
        async with self.db.session() as session:
            try:
                stmt = (
                    select(Prediction)
                    .options(
                        selectinload(Prediction.options),
                        selectinload(Prediction.bets)
                    )
                    .where(Prediction.id == prediction_id)
                )
                result = await session.execute(stmt)
                return result.scalar_one_or_none()
            except Exception as e:
                self.logger.error(f"Error fetching prediction {prediction_id}: {e}", exc_info=True)
                return None

    async def stop(self):
        """Cleanup and stop the prediction market service."""
        self.logger.info("Stopping prediction market service...")
        # Add any cleanup needed here
        self.logger.info("Prediction market service stopped")

    async def place_bet(
        self,
        prediction_id: int,
        option_id: int,
        user_id: int,
        amount: int,
        economy: str
    ) -> Tuple[bool, str, Optional[Bet]]:
        """Place a bet on a prediction option."""
        self.logger.debug(f"Placing bet: {amount} on option {option_id} for prediction {prediction_id}")
        async with self.db.session() as session:
            try:
                prediction = await self.get_prediction(prediction_id)
                if not prediction:
                    return False, "Prediction not found.", None

                if prediction.resolved:
                    raise MarketStateError("This market has already been resolved.")
                if prediction.end_time <= utc_now():
                    raise MarketStateError("Betting period has ended for this market.")

                option = next((opt for opt in prediction.options if opt.id == option_id), None)
                if not option:
                    return False, "Invalid option selected.", None

                bet = Bet(
                    prediction_id=prediction_id,
                    option_id=option_id,
                    user_id=user_id,
                    amount=amount,
                    economy=economy
                )
                session.add(bet)
                await session.commit()
                
                self.logger.info(f"Bet placed: {amount} on option {option_id} for prediction {prediction_id}")
                return True, "Bet placed successfully!", bet

            except MarketStateError as e:
                await session.rollback()
                return False, str(e), None
            except Exception as e:
                await session.rollback()
                self.logger.error(f"Error placing bet: {e}", exc_info=True)
                return False, f"Failed to place bet: {str(e)}", None

    async def resolve_market(
        self,
        prediction_id: int,
        winning_option_id: int,
        resolver_id: int
    ) -> Tuple[bool, str, List[Tuple[int, int, str]]]:
        """Resolve a prediction market. Returns: (success, message, list of (user_id, payout, economy))"""
        async with self.db.session() as session:
            try:
                prediction = await self.get_prediction(prediction_id)
                if not prediction:
                    return False, "Prediction not found.", []

                if prediction.resolved:
                    return False, "Market already resolved.", []
                if prediction.creator_id != resolver_id:
                    return False, "Only the creator can resolve this market.", []
                if prediction.end_time > utc_now():
                    return False, "Cannot resolve market before betting period ends.", []

                winning_option = next(
                    (opt for opt in prediction.options if opt.id == winning_option_id),
                    None
                )
                if not winning_option:
                    return False, "Invalid winning option.", []

                payouts = []
                total_bets = sum(bet.amount for bet in prediction.bets)
                if total_bets > 0:
                    winning_bets = [
                        bet for bet in prediction.bets 
                        if bet.option_id == winning_option_id
                    ]
                    for bet in winning_bets:
                        payout = int(bet.amount * (total_bets / sum(
                            wb.amount for wb in winning_bets
                        )))
                        payouts.append((bet.user_id, payout, bet.economy))

                prediction.resolved = True
                prediction.resolved_at = utc_now()
                prediction.winning_option_id = winning_option_id
                await session.commit()

                return True, "Market resolved successfully!", payouts

            except Exception as e:
                await session.rollback()
                self.logger.error(f"Error resolving market: {e}", exc_info=True)
                return False, f"Failed to resolve market: {str(e)}", []

    async def schedule_prediction_resolution(self, prediction: Prediction) -> None:
        """Schedule automatic resolution notification for a prediction."""
        try:
            time_until_end = (prediction.end_time - utc_now()).total_seconds()
            if time_until_end > 0:
                self.logger.debug(f"Waiting {time_until_end} seconds for betting to end")
                await asyncio.sleep(time_until_end)

            prediction = await self.get_prediction(prediction.id)
            if prediction.resolved:
                self.logger.debug("Prediction already resolved before betting end")
                return

            self.logger.info(f"Betting period ended for prediction {prediction.id}")

            try:
                creator = await self.bot.fetch_user(prediction.creator_id)
                await creator.send(
                    "Betting has ended for your prediction: '{prediction.question}'\n"
                    "Please use /resolve_prediction to resolve the market.\n"
                    "If not resolved within 48 hours, all bets will be automatically refunded."
                )
            except Exception as e:
                self.logger.error(f"Error notifying creator: {e}", exc_info=True)

        except Exception as e:
            self.logger.error(f"Error in resolution scheduling: {e}", exc_info=True)
