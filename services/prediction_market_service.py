from datetime import datetime, timedelta
import asyncio
from typing import List, Optional, Tuple, Dict
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import Prediction, PredictionBet
from utils.exceptions import (
    PredictionNotFoundError,
    PredictionAlreadyResolvedError,
    BettingPeriodEndedError,
    InvalidOptionError,
    UnauthorizedResolutionError,
    PredictionAlreadyRefundedError,
    InvalidPredictionDurationError,
)
from .local_points_service import LocalPointsService
from config.settings import PredictionMarketConfig

class PredictionMarketService:
    def __init__(self, session: AsyncSession, points_service: LocalPointsService, config: PredictionMarketConfig):
        self.session = session
        self.points_service = points_service
        self.config = config
        self._active_predictions: Dict[int, Prediction] = {}
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start(self):
        """Initialize the service and start background tasks."""
        # Load active predictions into memory
        query = select(Prediction).where(
            and_(
                Prediction.resolved == False,
                Prediction.end_time > datetime.utcnow()
            )
        )
        result = await self.session.execute(query)
        predictions = result.scalars().all()
        
        for prediction in predictions:
            self._active_predictions[prediction.id] = prediction

        # Start cleanup task
        if not self._cleanup_task:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self):
        """Cleanup and stop background tasks."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        self._active_predictions.clear()

    async def _cleanup_loop(self):
        """Background task to cleanup expired predictions."""
        while True:
            try:
                now = datetime.utcnow()
                refund_threshold = now - timedelta(
                    hours=self.config.resolution_window_hours
                )

                # Find predictions needing cleanup
                to_remove = []
                for pred_id, prediction in self._active_predictions.items():
                    if prediction.end_time <= refund_threshold:
                        # Auto-refund if not resolved
                        if not prediction.resolved:
                            await self.refund_prediction(pred_id)
                        to_remove.append(pred_id)
                    elif prediction.resolved:
                        to_remove.append(pred_id)

                # Remove from memory
                for pred_id in to_remove:
                    self._active_predictions.pop(pred_id, None)

                # Sleep until next check
                await asyncio.sleep(300)  # Check every 5 minutes

            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.bot.logger.error(f"Error in prediction cleanup: {e}")
                await asyncio.sleep(60)  # Retry after 1 minute on error

    async def create_prediction(
        self,
        question: str,
        options: List[str],
        creator_id: str,
        end_time: datetime,
        category: Optional[str] = None
    ) -> Prediction:
        """Create a new prediction and cache it."""
        prediction = await super().create_prediction(
            question, options, creator_id, end_time, category
        )
        self._active_predictions[prediction.id] = prediction
        return prediction

    async def place_bet(
        self,
        prediction_id: int,
        user_id: str,
        option: str,
        amount: int
    ) -> PredictionBet:
        """Place a bet on a prediction."""
        if amount < self.config.min_bet:
            raise InvalidAmountError(f"Bet must be at least {self.config.min_bet} points")
            
        if amount > self.config.max_bet:
            raise InvalidAmountError(f"Bet cannot exceed {self.config.max_bet} points")
            
        # Get prediction
        prediction = await self.get_prediction(prediction_id)
        if not prediction:
            raise PredictionNotFoundError(prediction_id)
            
        # Validate prediction state
        if prediction.resolved:
            raise PredictionAlreadyResolvedError(prediction_id)
        if prediction.end_time <= datetime.utcnow():
            raise BettingPeriodEndedError(prediction_id, prediction.end_time)
        if option not in prediction.options:
            raise InvalidOptionError(option, prediction.options)

        # Check user balance and transfer points
        balance = await self.points_service.get_balance(user_id)
        if balance < amount:
            raise InsufficientPointsError(user_id, amount, balance)

        async with self.session.begin_nested():  # Create savepoint
            # Transfer points to house
            await self.points_service.transfer_points(
                from_user_id=user_id,
                to_user_id=None,  # House account
                amount=amount
            )

            # Record bet
            bet = PredictionBet(
                prediction_id=prediction_id,
                user_id=user_id,
                option=option,
                amount=amount
            )
            self.session.add(bet)
            await self.session.commit()

        return bet

    async def resolve_prediction(
        self,
        prediction_id: int,
        result: str,
        resolver_id: str
    ) -> Tuple[Prediction, List[Tuple[str, int]]]:
        """Resolve prediction and remove from cache."""
        prediction, payouts = await super().resolve_prediction(
            prediction_id, result, resolver_id
        )
        self._active_predictions.pop(prediction_id, None)
        return prediction, payouts

    async def refund_prediction(self, prediction_id: int) -> List[Tuple[str, int]]:
        """Refund all bets for a prediction."""
        prediction = await self.get_prediction(prediction_id)
        if not prediction:
            raise ValueError("Prediction not found")
            
        if prediction.refunded:
            raise ValueError("Prediction already refunded")

        async with self.session.begin_nested():
            prediction.refunded = True
            prediction.resolved = True
            
            refunds = []
            for bet in prediction.bets:
                await self.points_service.add_points(bet.user_id, bet.amount)
                refunds.append((bet.user_id, bet.amount))

            await self.session.commit()
            return refunds

    async def get_prediction(self, prediction_id: int) -> Optional[Prediction]:
        """Get prediction from cache or database."""
        # Check cache first
        prediction = self._active_predictions.get(prediction_id)
        if prediction:
            return prediction

        # Fall back to database
        result = await self.session.execute(
            select(Prediction).where(Prediction.id == prediction_id)
        )
        return result.scalar_one_or_none()

    async def get_active_predictions(
        self,
        category: Optional[str] = None
    ) -> List[Prediction]:
        """Get all active predictions, optionally filtered by category."""
        query = select(Prediction).where(
            Prediction.resolved == False,
            Prediction.end_time > datetime.utcnow()
        )
        
        if category:
            query = query.where(Prediction.category == category)
            
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_user_bets(
        self,
        user_id: str,
        active_only: bool = False
    ) -> List[PredictionBet]:
        """Get all bets placed by a user."""
        query = select(PredictionBet).where(PredictionBet.user_id == user_id)
        
        if active_only:
            query = query.join(Prediction).where(
                Prediction.resolved == False,
                Prediction.end_time > datetime.utcnow()
            )
            
        result = await self.session.execute(query)
        return result.scalars().all() 