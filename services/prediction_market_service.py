from datetime import datetime
from typing import List, Optional, Tuple, Literal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from database.models import Prediction, PredictionBet
from utils.exceptions import (
    PredictionNotFoundError,
    InsufficientPointsError,
    InvalidAmountError
)
from sqlalchemy.orm import selectinload
import logging

class PredictionMarketService:
    def __init__(self, session_factory: async_sessionmaker, transfer_service, config):
        self.session_factory = session_factory
        self.transfer_service = transfer_service
        self.config = config
        self._market_balance = {}
        self._running = False
        self.logger = logging.getLogger(__name__)

    async def start(self):
        """Initialize the service and load existing predictions."""
        self.logger.info("Starting prediction market service...")
        self._running = True
        
        # Load existing predictions into memory
        query = select(Prediction).where(Prediction.resolved == False)
        
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
        
        self.logger.info("Prediction market service stopped")

    async def create_prediction(
        self,
        question: str,
        options: List[str],
        creator_id: str,
        end_time: datetime,
        category: Optional[str] = None
    ) -> Prediction:
        """Create a new prediction market."""
        if len(options) < 2:
            raise ValueError("Prediction must have at least 2 options")
            
        async with self.session_factory() as session:
            async with session.begin():
                prediction = Prediction(
                    question=question,
                    options=options,
                    creator_id=creator_id,
                    end_time=end_time,
                    category=category,
                    resolved=False,
                    refunded=False,
                    created_at=datetime.utcnow()
                )
                
                session.add(prediction)
                await session.flush()
                
                self._market_balance[prediction.id] = {}
                
                return prediction

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
        async with self.session_factory() as session:
            stmt = (
                select(Prediction)
                .where(Prediction.creator_id == creator_id)
                .where(Prediction.resolved == False)
                .where(Prediction.end_time <= datetime.utcnow())
                .options(selectinload(Prediction.bets))
            )
            
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def place_bet(
        self,
        prediction_id: int,
        user_id: str,
        option: str,
        amount: int,
        economy: Literal["ffs", "hackathon"]
    ) -> PredictionBet:
        """Place a bet on a prediction."""
        async with self.session_factory() as session:
            async with session.begin():
                prediction = await self.get_prediction(prediction_id)
                if not prediction:
                    raise PredictionNotFoundError(prediction_id)

                if prediction.end_time <= datetime.utcnow():
                    raise BettingPeriodEndedError()

                if option not in prediction.options:
                    raise InvalidOptionError(option)

                if amount <= 0:
                    raise InvalidAmountError("Bet amount must be positive")

                # Create bet record
                bet = PredictionBet(
                    prediction_id=prediction_id,
                    user_id=user_id,
                    option=option,
                    amount=amount,
                    source_economy=economy
                )
                
                # Transfer points from user to prediction market
                success = await self.transfer_service.transfer(
                    from_id=user_id,
                    to_id=None,  # Prediction Market house account
                    amount=amount,
                    economy=economy
                )
                
                if not success:
                    raise InsufficientPointsError(user_id, amount)

                session.add(bet)
                await session.flush()

                # Track market balance
                if economy not in self._market_balance[prediction_id]:
                    self._market_balance[prediction_id][economy] = 0
                self._market_balance[prediction_id][economy] += amount

                return bet

    async def resolve_prediction(
        self,
        prediction_id: int,
        result: str,
        resolver_id: str
    ) -> Tuple[Prediction, List[Tuple[str, int, str]]]:
        """Resolve a prediction and distribute payouts."""
        async with self.session_factory() as session:
            async with session.begin():
                prediction = await self.get_prediction(prediction_id)
                if not prediction:
                    raise PredictionNotFoundError(prediction_id)

                if prediction.resolved:
                    raise PredictionAlreadyResolvedError()

                if prediction.creator_id != resolver_id:
                    raise UnauthorizedResolutionError()

                if result not in prediction.options:
                    raise InvalidOptionError(result)

                # Mark prediction as resolved
                prediction.resolved = True
                prediction.result = result

                # Calculate and distribute payouts
                payouts = []
                total_pool = prediction.total_pool
                winning_pool = prediction.get_option_total(result)

                if winning_pool > 0:
                    for bet in prediction.bets:
                        if bet.option == result:
                            payout = int((bet.amount / winning_pool) * total_pool)
                            await self.transfer_service.transfer(
                                from_id=None,  # Prediction Market house account
                                to_id=bet.user_id,
                                amount=payout,
                                economy=bet.source_economy
                            )
                            payouts.append((bet.user_id, payout, bet.source_economy))

                return prediction, payouts