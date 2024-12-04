from __future__ import annotations
from typing import Optional, List, Tuple, Dict
from datetime import datetime
from sqlalchemy import select, and_, not_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from database.models import Prediction, PredictionOption, Bet, utc_now, ensure_utc
from services.transfer_service import CrossEconomyTransferService
import asyncio
import discord
from utils.logging import PredictionMarketFilter

class PredictionMarketError(Exception):
    """Base exception class for prediction market errors"""
    pass

class InsufficientLiquidityError(PredictionMarketError):
    """Raised when there's insufficient liquidity for a trade"""
    pass

class InvalidBetError(PredictionMarketError):
    """Raised when a bet is invalid (amount, timing, etc)"""
    pass

class MarketStateError(PredictionMarketError):
    """Raised when market state prevents an action (already resolved, expired, etc)"""
    pass

class PredictionMarketService:
    """Service for managing prediction market operations."""
    
    def __init__(
        self, 
        session: AsyncSession, 
        transfer_service: CrossEconomyTransferService,
        bot: discord.Client
    ) -> None:
        self._session = session
        self.transfer_service = transfer_service
        self.logger = bot.logger.getChild('prediction_market_service')
        self.logger.addFilter(PredictionMarketFilter())

    @classmethod
    def from_bot(cls, bot: discord.Client) -> PredictionMarketService:
        """Create service instance from bot context."""
        return cls(
            session=bot.db_session,
            transfer_service=bot.transfer_service,
            bot=bot
        )

    async def create_prediction(
        self, 
        question: str, 
        options: List[str], 
        end_time: datetime, 
        creator_id: int, 
        category: Optional[str] = None
    ) -> Tuple[bool, str, Optional[Prediction]]:
        """Create a new prediction market."""
        try:
            prediction = Prediction(
                question=question,
                end_time=ensure_utc(end_time),
                creator_id=creator_id,
                category=category
            )
            prediction.options = [
                PredictionOption(text=option) for option in options
            ]
            self._session.add(prediction)
            await self._session.commit()
            return True, "Prediction market created successfully.", prediction
        except Exception as e:
            await self._session.rollback()
            self.logger.error(f"Error creating prediction: {e}", exc_info=True)
            return False, f"Failed to create prediction market: {str(e)}", None

    async def get_prediction(self, prediction_id: int) -> Optional[Prediction]:
        """Fetch a prediction by ID with options and bets preloaded."""
        try:
            stmt = (
                select(Prediction)
                .options(
                    selectinload(Prediction.options),
                    selectinload(Prediction.bets)
                )
                .where(Prediction.id == prediction_id)
            )
            result = await self._session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as e:
            self.logger.error(f"Error fetching prediction {prediction_id}: {e}", exc_info=True)
            return None

    async def get_all_predictions(self) -> List[Prediction]:
        """Fetch all predictions with their options and bets."""
        try:
            stmt = (
                select(Prediction)
                .options(
                    selectinload(Prediction.options),
                    selectinload(Prediction.bets)
                )
            )
            result = await self._session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            self.logger.error(f"Error fetching all predictions: {e}", exc_info=True)
            return []

    async def get_active_predictions(self) -> List[Prediction]:
        """Fetch all active predictions."""
        try:
            current_time = utc_now()
            stmt = (
                select(Prediction)
                .options(
                    selectinload(Prediction.options),
                    selectinload(Prediction.bets)
                )
                .where(
                    and_(
                        Prediction.resolved == False,
                        Prediction.end_time > current_time,
                        not_(Prediction.refunded)
                    )
                )
            )
            result = await self._session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            self.logger.error(f"Error fetching active predictions: {e}", exc_info=True)
            return []

    async def get_pending_resolution(self) -> List[Prediction]:
        """Fetch predictions pending resolution."""
        try:
            current_time = utc_now()
            stmt = (
                select(Prediction)
                .options(
                    selectinload(Prediction.options),
                    selectinload(Prediction.bets)
                )
                .where(
                    and_(
                        Prediction.resolved == False,
                        Prediction.end_time <= current_time,
                        not_(Prediction.refunded)
                    )
                )
            )
            result = await self._session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            self.logger.error(f"Error fetching pending predictions: {e}", exc_info=True)
            return []

    async def place_bet(
        self,
        prediction: Prediction,
        option: PredictionOption,
        user_id: int,
        amount: int,
        economy: str
    ) -> Tuple[bool, str]:
        """Place a bet on a prediction option."""
        try:
            current_time = utc_now()
            if prediction.resolved or prediction.end_time <= current_time:
                raise MarketStateError("This prediction is no longer accepting bets.")

            has_balance = await self.transfer_service.check_balance(
                user_id, amount, economy
            )
            if not has_balance:
                raise InsufficientLiquidityError("Insufficient balance for this bet.")

            success = await self.transfer_service.process_bet(
                user_id, amount, prediction.id, option.id, economy
            )
            if not success:
                raise InvalidBetError("Failed to process bet transaction.")

            shares = self.calculate_shares_for_points(prediction, option, amount)
            if shares <= 0:
                raise InvalidBetError("Invalid share calculation.")

            new_bet = Bet(
                prediction_id=prediction.id,
                option_id=option.id,
                user_id=user_id,
                amount=amount,
                shares=shares,
                economy=economy
            )
            
            self._session.add(new_bet)
            await self._session.commit()
            
            return True, f"Successfully placed bet of {amount} points for {shares:.2f} shares."
            
        except PredictionMarketError as e:
            await self._session.rollback()
            return False, str(e)
        except Exception as e:
            await self._session.rollback()
            self.logger.error(f"Error placing bet: {e}", exc_info=True)
            return False, "An error occurred while placing your bet."

    def calculate_shares_for_points(
        self, 
        prediction: Prediction,
        option: PredictionOption,
        points: int
    ) -> float:
        """Calculate shares received for points invested."""
        try:
            current_shares = prediction.liquidity_pool[option.text]
            other_option = next(
                opt for opt in prediction.options 
                if opt.id != option.id
            )
            other_shares = prediction.liquidity_pool[other_option.text]
            
            new_other_shares = other_shares + points
            new_shares = prediction.k_constant / new_other_shares
            shares_received = current_shares - new_shares
            
            return max(0.0, shares_received)
        except Exception as e:
            self.logger.error(f"Error calculating shares: {e}", exc_info=True)
            return 0.0

    async def resolve_prediction(
        self, 
        prediction: Prediction, 
        winning_option: PredictionOption,
        resolver_id: int
    ) -> Tuple[bool, str]:
        """Resolve a prediction market and process payouts."""
        try:
            if prediction.resolved:
                raise MarketStateError("This prediction has already been resolved.")
                
            if resolver_id != prediction.creator_id:
                raise InvalidBetError("Only the creator can resolve this prediction.")

            prediction.resolved = True
            prediction.result = winning_option.text

            # Process payouts for winning bets
            winning_bets = [
                bet for bet in prediction.bets 
                if bet.option_id == winning_option.id
            ]
            
            for bet in winning_bets:
                payout = self.calculate_payout(bet, prediction)
                await self.transfer_service.process_payout(
                    user_id=bet.user_id,
                    amount=payout,
                    prediction_id=prediction.id,
                    economy=bet.economy
                )

            await self._session.commit()
            return True, f"Prediction resolved with winning option: {winning_option.text}"
            
        except PredictionMarketError as e:
            await self._session.rollback()
            return False, str(e)
        except Exception as e:
            await self._session.rollback()
            self.logger.error(f"Error resolving prediction: {e}", exc_info=True)
            return False, "An error occurred while resolving the prediction."

    def calculate_payout(self, bet: Bet, prediction: Prediction) -> int:
        """Calculate payout for a winning bet."""
        try:
            total_pool = sum(bet.amount for bet in prediction.bets)
            share_ratio = bet.shares / sum(
                b.shares for b in prediction.bets 
                if b.option_id == bet.option_id
            )
            return int(total_pool * share_ratio)
        except Exception as e:
            self.logger.error(f"Error calculating payout: {e}", exc_info=True)
            return 0

    async def get_market_status(
        self, 
        prediction: Prediction
    ) -> Dict[str, Dict[str, float]]:
        """Get current market status including prices and probabilities."""
        try:
            total_liquidity = sum(prediction.liquidity_pool.values())
            status = {}
            
            for option in prediction.options:
                liquidity = prediction.liquidity_pool[option.text]
                probability = liquidity / total_liquidity if total_liquidity > 0 else 0
                
                status[option.text] = {
                    "price_per_share": liquidity,
                    "probability": probability * 100,
                    "total_bets": sum(bet.amount for bet in option.bets),
                    "total_shares": sum(bet.shares for bet in option.bets)
                }
                
            return status
            
        except Exception as e:
            self.logger.error(f"Error getting market status: {e}", exc_info=True)
            return {}

    async def get_user_bets(
        self, 
        user_id: int
    ) -> List[Tuple[Prediction, Bet]]:
        """Get all bets placed by a user."""
        try:
            stmt = (
                select(Prediction, Bet)
                .join(Bet)
                .options(
                    selectinload(Prediction.options)
                )
                .where(Bet.user_id == user_id)
            )
            result = await self._session.execute(stmt)
            return list(result.all())
        except Exception as e:
            self.logger.error(f"Error fetching user bets: {e}", exc_info=True)
            return []

    async def schedule_prediction_resolution(self, prediction: Prediction) -> None:
        """Schedule automatic resolution/refund for a prediction."""
        try:
            self.logger.debug(f"Starting resolution schedule for prediction {prediction.id}")
            
            # Wait for betting period to end
            time_until_betting_ends = (prediction.end_time - utc_now()).total_seconds()
            if time_until_betting_ends > 0:
                self.logger.debug(f"Waiting {time_until_betting_ends} seconds for betting to end")
                await asyncio.sleep(time_until_betting_ends)
            
            # Check if already resolved
            if prediction.resolved:
                self.logger.debug("Prediction already resolved before betting end")
                return
                
            self.logger.debug(f"Betting period ended for prediction {prediction.id}")
            
            # Wait additional time for manual resolution
            await asyncio.sleep(120 * 3600)  # 120 hours
            
            # Process auto-refund if not resolved
            if not prediction.resolved:
                self.logger.debug("Starting auto-refund process")
                await self.process_refunds(prediction)
                
        except Exception as e:
            self.logger.error(f"Error in schedule_prediction_resolution: {e}", exc_info=True)

    async def process_refunds(self, prediction: Prediction) -> None:
        """Process refunds for an unresolved prediction."""
        try:
            prediction.refunded = True
            
            for bet in prediction.bets:
                await self.transfer_service.process_refund(
                    user_id=bet.user_id,
                    amount=bet.amount,
                    prediction_id=prediction.id,
                    economy=bet.economy
                )
            
            await self._session.commit()
            self.logger.info(f"Successfully processed refunds for prediction {prediction.id}")
            
        except Exception as e:
            await self._session.rollback()
            self.logger.error(f"Error processing refunds: {e}", exc_info=True)

    async def initialize(self) -> None:
        """Initialize the service."""
        try:
            # Initialize any required data
            self.logger.info("PredictionMarketService initialized successfully")
        except Exception as e:
            self.logger.error(f"Error initializing PredictionMarketService: {e}")
            raise
