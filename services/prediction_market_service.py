from datetime import datetime
from typing import List, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import Prediction, PredictionBet
from utils.exceptions import InsufficientPointsError, InvalidAmountError
from .local_points_service import LocalPointsService

class PredictionMarketService:
    def __init__(self, session: AsyncSession, points_service: LocalPointsService):
        self.session = session
        self.points_service = points_service

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
            
        prediction = Prediction(
            question=question,
            options=options,
            creator_id=creator_id,
            end_time=end_time,
            category=category
        )
        self.session.add(prediction)
        await self.session.commit()
        return prediction

    async def place_bet(
        self,
        prediction_id: int,
        user_id: str,
        option: str,
        amount: int
    ) -> PredictionBet:
        """Place a bet on a prediction."""
        # Validate amount
        if amount <= 0:
            raise InvalidAmountError(amount)

        # Get prediction
        prediction = await self.get_prediction(prediction_id)
        if not prediction:
            raise ValueError("Prediction not found")
            
        # Validate prediction state
        if prediction.resolved:
            raise ValueError("Cannot bet on resolved prediction")
        if prediction.end_time <= datetime.utcnow():
            raise ValueError("Betting period has ended")
        if option not in prediction.options:
            raise ValueError("Invalid option")

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
        """Resolve a prediction and distribute payouts."""
        prediction = await self.get_prediction(prediction_id)
        if not prediction:
            raise ValueError("Prediction not found")
            
        if prediction.resolved:
            raise ValueError("Prediction already resolved")
        if prediction.creator_id != resolver_id:
            raise ValueError("Only the creator can resolve the prediction")
        if result not in prediction.options:
            raise ValueError("Invalid result option")

        async with self.session.begin_nested():
            # Mark prediction as resolved
            prediction.resolved = True
            prediction.result = result

            # Calculate and distribute payouts
            payouts = []  # List of (user_id, payout_amount)
            winning_bets = [bet for bet in prediction.bets if bet.option == result]
            
            if winning_bets:
                total_pool = prediction.total_pool
                winning_pool = sum(bet.amount for bet in winning_bets)
                
                for bet in winning_bets:
                    payout = int(total_pool * (bet.amount / winning_pool))
                    await self.points_service.add_points(bet.user_id, payout)
                    payouts.append((bet.user_id, payout))

            await self.session.commit()
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
        """Get a prediction by ID."""
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