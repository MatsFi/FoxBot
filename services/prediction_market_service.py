from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from database.models import Prediction, PredictionOption, Bet, utc_now, ensure_utc
import logging

class PredictionMarketService:
    @classmethod
    def from_bot(cls, bot):
        """Create a PredictionMarketService instance from a bot instance."""
        return cls(
            session_factory=bot.db_session,
            bot=bot
        )

    def __init__(self, session_factory, bot):
        self.session_factory = session_factory
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self._market_balance = {}
        self._running = False
        self._notification_tasks = {}
        self.k_constant = 100 * 100
        
        # Get available economies from transfer service
        self.available_economies = list(bot.transfer_service._external_services.keys())
        self.logger.info(f"Prediction Market initialized with economies: {self.available_economies}")

    async def place_bet(
        self,
        prediction_id: int,
        option_text: str,
        user_id: int,
        amount: int,
        economy: str
    ) -> bool:
        """Place a bet on a prediction option."""
        self.logger.debug(f"Placing bet: prediction={prediction_id}, option={option_text}, user={user_id}, amount={amount}, economy={economy}")
        
        if economy not in self.available_economies:
            self.logger.error(f"Invalid economy {economy}. Must be one of: {self.available_economies}")
            return False

        try:
            async with self.session_factory() as session:
                # Load prediction with options
                stmt = (
                    select(Prediction)
                    .options(selectinload(Prediction.options))
                    .where(Prediction.id == prediction_id)
                )
                result = await session.execute(stmt)
                prediction = result.scalar_one_or_none()
                
                if not prediction:
                    self.logger.error(f"Prediction {prediction_id} not found")
                    return False
                    
                if prediction.resolved:
                    self.logger.error("Cannot bet on resolved prediction")
                    return False
                    
                # Ensure end_time comparison is timezone-aware
                prediction_end_time = ensure_utc(prediction.end_time)
                current_time = utc_now()
                    
                if prediction_end_time <= current_time:
                    self.logger.error("Cannot bet on expired prediction")
                    return False
                
                # Find the matching option
                option = next(
                    (opt for opt in prediction.options if opt.text == option_text),
                    None
                )
                if not option:
                    self.logger.error(f"Option {option_text} not found")
                    return False
                
                # Get the external service and verify balance
                external_service = self.bot.transfer_service.get_external_service(economy)
                balance = await external_service.get_balance(user_id)
                if balance < amount:
                    self.logger.error(f"Insufficient {economy} balance: {balance} < {amount}")
                    return False

                # Remove points from external economy
                if not await external_service.remove_points(user_id, amount):
                    self.logger.error(f"Failed to remove points from {economy} economy")
                    return False

                # Create the bet with UTC timestamp
                bet = Bet(
                    prediction_id=prediction_id,
                    option_id=option.id,
                    user_id=user_id,
                    amount=amount,
                    economy=economy,
                    created_at=utc_now()
                )
                session.add(bet)
                
                # Update prediction total bets
                prediction.total_bets += amount
                
                # Deduct points from user
                await external_service.remove_points(user_id, amount)
                
                # Update liquidity pools using AMM formula
                shares = await self.calculate_shares_for_points(prediction_id, option.id, amount)
                option.liquidity_pool -= shares
                
                # Get opposite option and update its pool
                opposite_option = next(
                    (opt for opt in prediction.options if opt.id != option.id),
                    None
                )
                if opposite_option:
                    opposite_option.liquidity_pool += amount
                
                await session.commit()
                self.logger.info(f"Successfully placed {economy} bet for user {user_id} on prediction {prediction_id}")
                return True

        except Exception as e:
            self.logger.error(f"Error placing bet: {e}", exc_info=True)
            return False

    async def start(self):
        """Initialize the service and load existing predictions."""
        self.logger.info("Starting prediction market service...")
        self._running = True
        
        # Load existing predictions with bets and options using joinedload
        query = (
            select(Prediction)
            .options(
                selectinload(Prediction.bets),
                selectinload(Prediction.options)
            )
            .where(Prediction.resolved == False)
        )
        
        async with self.session_factory() as session:
            result = await session.execute(query)
            active_predictions = result.scalars().all()
            
            # Initialize market balances
            for pred in active_predictions:
                self._market_balance[pred.id] = {}
                for bet in pred.bets:
                    if bet.user_id not in self._market_balance[pred.id]:
                        self._market_balance[pred.id][bet.user_id] = 0
                    self._market_balance[pred.id][bet.user_id] += bet.amount
                    
                # Schedule end notification for active predictions
                # Ensure end_time is timezone-aware before comparison
                now = datetime.now(timezone.utc)
                if not pred.resolved and pred.end_time.replace(tzinfo=timezone.utc) > now:
                    self._schedule_end_notification(pred)
                    
        self.logger.info(f"Loaded {len(active_predictions)} active predictions")
        
    async def get_price(self, prediction_id: int, option_id: int, shares_to_buy: float) -> float:
        """Calculate price for buying shares using constant product formula."""
        async with self.session_factory() as session:
            option = await session.get(PredictionOption, option_id)
            if not option:
                return float('inf')
            
            current_shares = option.liquidity_pool
            # Get the opposite option in binary market
            other_option = await session.execute(
                select(PredictionOption)
                .where(
                    PredictionOption.prediction_id == prediction_id,
                    PredictionOption.id != option_id
                )
            )
            other_option = other_option.scalar_one_or_none()
            if not other_option:
                return float('inf')
            
            other_shares = other_option.liquidity_pool
            
            # Using constant product formula: x * y = k
            new_shares = current_shares - shares_to_buy
            if new_shares <= 0:
                return float('inf')
            
            new_other_shares = self.k_constant / new_shares
            cost = new_other_shares - other_shares
            return max(0, cost)

    async def calculate_shares_for_points(
        self,
        prediction_id: int,
        option_id: int,
        points: int
    ) -> float:
        """Calculate how many shares user gets for their points."""
        async with self.session_factory() as session:
            option = await session.get(PredictionOption, option_id)
            if not option:
                return 0
            
            current_shares = option.liquidity_pool
            other_option = await session.execute(
                select(PredictionOption)
                .where(
                    PredictionOption.prediction_id == prediction_id,
                    PredictionOption.id != option_id
                )
            )
            other_option = other_option.scalar_one_or_none()
            if not other_option:
                return 0
            
            other_shares = other_option.liquidity_pool
            
            # Using constant product formula: x * y = k
            new_other_shares = other_shares + points
            new_shares = self.k_constant / new_other_shares
            shares_received = current_shares - new_shares
            return shares_received

    async def get_current_prices(
        self,
        prediction_id: int,
        points_to_spend: int = 100
    ) -> Dict[str, Dict]:
        """Calculate current prices and potential shares for a given point amount."""
        self.logger.debug(f"Getting current prices for prediction {prediction_id}")
        try:
            async with self.session_factory() as session:
                # Load prediction with options in a single query
                stmt = (
                    select(Prediction)
                    .options(selectinload(Prediction.options))
                    .where(Prediction.id == prediction_id)
                )
                result = await session.execute(stmt)
                prediction = result.scalar_one_or_none()
                
                if not prediction:
                    raise ValueError(f"Prediction {prediction_id} not found")
                
                prices = {}
                for option in prediction.options:
                    shares = await self.calculate_shares_for_points(
                        prediction_id,
                        option.id,
                        points_to_spend
                    )
                    price_per_share = points_to_spend / shares if shares > 0 else float('inf')
                    potential_payout = points_to_spend * (1 / price_per_share) if price_per_share > 0 else 0
                    
                    prices[option.text] = {
                        'price_per_share': price_per_share,
                        'potential_shares': shares,
                        'potential_payout': potential_payout
                    }
                
                return prices
                
        except Exception as e:
            self.logger.error(f"Error getting current prices: {e}", exc_info=True)
            raise

    async def get_user_payout(self, prediction_id: int, user_id: int) -> int:
        """Calculate payout based on shares owned and final pool state."""
        async with self.session_factory() as session:
            prediction = await session.get(Prediction, prediction_id)
            if not prediction or not prediction.resolved or not prediction.result:
                return 0
            
            # Get winning bets
            winning_bets = await session.execute(
                select(Bet)
                .join(PredictionOption)
                .where(
                    Bet.prediction_id == prediction_id,
                    PredictionOption.text == prediction.result,
                    Bet.user_id == user_id
                )
            )
            winning_bet = winning_bets.scalar_one_or_none()
            if not winning_bet:
                return 0
            
            # Calculate payout based on share of winning pool
            total_pool = prediction.total_bets
            winning_pool = await session.execute(
                select(func.sum(Bet.amount))
                .join(PredictionOption)
                .where(
                    Bet.prediction_id == prediction_id,
                    PredictionOption.text == prediction.result
                )
            )
            winning_pool = winning_pool.scalar_one() or 0
            
            if winning_pool == 0:
                return 0
                
            share_value = total_pool / winning_pool
            return int(winning_bet.amount * share_value)

    async def get_all_predictions(self) -> List[Prediction]:
        """Get all predictions ordered by creation date."""
        self.logger.debug("Starting get_all_predictions()")
        try:
            async with self.session_factory() as session:
                # Load everything we need in a single query
                stmt = (
                    select(Prediction)
                    .options(
                        selectinload(Prediction.options),
                        selectinload(Prediction.bets)
                    )
                    .order_by(Prediction.created_at.desc())
                )
                
                result = await session.execute(stmt)
                predictions = result.scalars().unique().all()
                
                # Explicitly load all the data we need before session closes
                loaded_predictions = []
                for pred in predictions:
                    loaded_pred = {
                        'id': pred.id,
                        'question': pred.question,
                        'category': pred.category,
                        'creator_id': pred.creator_id,
                        'created_at': pred.created_at,
                        'end_time': pred.end_time,
                        'resolved': pred.resolved,
                        'refunded': pred.refunded,
                        'total_bets': pred.total_bets,
                        'options': [
                            {'id': opt.id, 'text': opt.text, 'liquidity_pool': opt.liquidity_pool}
                            for opt in pred.options
                        ]
                    }
                    loaded_predictions.append(loaded_pred)
                
                return loaded_predictions
                
        except Exception as e:
            self.logger.error(f"Error fetching predictions: {e}", exc_info=True)
            raise

    async def create_prediction(
        self,
        question: str,
        options: List[str],
        end_time: datetime,
        creator_id: int,
        category: Optional[str] = None
    ) -> Prediction:
        """Create a new prediction market."""
        self.logger.info(f"Creating prediction: {question}")
        
        # Ensure end_time is UTC
        end_time = ensure_utc(end_time)
        
        async with self.session_factory() as session:
            async with session.begin():
                prediction = Prediction(
                    question=question,
                    end_time=end_time,
                    creator_id=creator_id,
                    category=category,
                    created_at=utc_now()
                )
                session.add(prediction)
                
                # Create options with initial liquidity pools
                for option_text in options:
                    option = PredictionOption(
                        prediction=prediction,
                        text=option_text,
                        liquidity_pool=100  # Initial liquidity
                    )
                    session.add(option)
                
                await session.commit()
                
                # Initialize market balance tracking
                self._market_balance[prediction.id] = {}
                
                # Schedule end notification
                self._schedule_end_notification(prediction)
                
                self.logger.info(f"Created prediction {prediction.id}: {question}")
                return prediction
            
    async def stop(self):
        """Cleanup service resources."""
        self.logger.info("Stopping prediction market service...")
        self._running = False
        
        # Cancel all pending notifications
        for task in self._notification_tasks.values():
            task.cancel()
        self._notification_tasks.clear()
        
        self._market_balance.clear()
        self.logger.info("Prediction market service stopped")

    def _schedule_end_notification(self, prediction: Prediction):
        """Schedule a notification for when the prediction ends."""
        # Existing notification logic...

    async def get_active_predictions(self) -> List[Prediction]:
        """Get all active (unresolved) predictions."""
        self.logger.debug("Starting get_active_predictions")
        try:
            async with self.session_factory() as session:
                current_time = utc_now()
                stmt = (
                    select(Prediction)
                    .options(
                        selectinload(Prediction.options),
                        selectinload(Prediction.bets)
                    )
                    .where(
                        Prediction.resolved == False,
                        Prediction.end_time > current_time
                    )
                    .order_by(Prediction.created_at.desc())
                )
                
                result = await session.execute(stmt)
                predictions = result.scalars().unique().all()
                return list(predictions)
                
        except Exception as e:
            self.logger.error(f"Error getting active predictions: {e}", exc_info=True)
            raise

    async def get_resolvable_predictions(self, user_id: int) -> List[Prediction]:
        """Get predictions that can be resolved by the given user."""
        self.logger.debug(f"Getting resolvable predictions for user {user_id}")
        try:
            async with self.session_factory() as session:
                current_time = utc_now()
                stmt = (
                    select(Prediction)
                    .options(
                        selectinload(Prediction.options),
                        selectinload(Prediction.bets)
                    )
                    .where(
                        Prediction.creator_id == user_id,
                        Prediction.resolved == False,
                        Prediction.end_time <= current_time
                    )
                    .order_by(Prediction.created_at.desc())
                )
                
                result = await session.execute(stmt)
                predictions = result.scalars().unique().all()
                return list(predictions)
                
        except Exception as e:
            self.logger.error(f"Error getting resolvable predictions: {e}", exc_info=True)
            raise

    async def get_prediction(self, prediction_id: int) -> Optional[Prediction]:
        """Get a single prediction with all its related data."""
        self.logger.debug(f"Getting prediction {prediction_id}")
        try:
            async with self.session_factory() as session:
                # Load prediction with options and bets in a single query
                stmt = (
                    select(Prediction)
                    .options(
                        selectinload(Prediction.options),
                        selectinload(Prediction.bets)
                    )
                    .where(Prediction.id == prediction_id)
                )
                
                result = await session.execute(stmt)
                prediction = result.scalar_one_or_none()
                
                if prediction is None:
                    self.logger.error(f"Prediction {prediction_id} not found")
                    return None
                
                self.logger.debug(f"Found prediction: {prediction.question}")
                return prediction
                
        except Exception as e:
            self.logger.error(f"Error getting prediction: {e}", exc_info=True)
            raise

    async def resolve_prediction(
        self,
        prediction_id: int,
        winning_option: str,
        resolver_id: int
    ) -> bool:
        """Resolve a prediction and process payouts."""
        self.logger.debug(f"Resolving prediction {prediction_id} with winner: {winning_option}")
        
        try:
            async with self.session_factory() as session:
                # Load prediction with options and bets
                stmt = (
                    select(Prediction)
                    .options(
                        selectinload(Prediction.options),
                        selectinload(Prediction.bets)
                    )
                    .where(Prediction.id == prediction_id)
                )
                result = await session.execute(stmt)
                prediction = result.scalar_one_or_none()
                
                if not prediction:
                    self.logger.error(f"Prediction {prediction_id} not found")
                    return False
                
                # Verify resolver is the creator
                if prediction.creator_id != resolver_id:
                    self.logger.error(f"User {resolver_id} is not the creator of prediction {prediction_id}")
                    return False
                
                # Verify prediction can be resolved
                if prediction.resolved:
                    self.logger.error(f"Prediction {prediction_id} is already resolved")
                    return False
                
                # Ensure timezone-aware comparison
                current_time = utc_now()
                prediction_end_time = ensure_utc(prediction.end_time)
                
                if prediction_end_time > current_time:
                    self.logger.error(f"Prediction {prediction_id} hasn't ended yet")
                    return False
                
                # Find winning option
                winning_opt = next(
                    (opt for opt in prediction.options if opt.text == winning_option),
                    None
                )
                if not winning_opt:
                    self.logger.error(f"Option {winning_option} not found for prediction {prediction_id}")
                    return False
                
                # Mark prediction as resolved
                prediction.resolved = True
                prediction.result = winning_option
                
                # Process payouts for winning bets
                winning_bets = [
                    bet for bet in prediction.bets 
                    if bet.option_id == winning_opt.id
                ]
                
                total_pool = prediction.total_bets
                winning_pool = sum(bet.amount for bet in winning_bets)
                
                if winning_pool > 0:
                    payout_multiplier = total_pool / winning_pool
                    
                    # Process payouts through appropriate external economies
                    for bet in winning_bets:
                        payout = int(bet.amount * payout_multiplier)
                        external_service = self.bot.transfer_service.get_external_service(bet.economy)
                        await external_service.add_points(bet.user_id, payout)
                        self.logger.info(
                            f"Paid {payout} points to user {bet.user_id} "
                            f"from {bet.economy} economy for winning bet"
                        )
                
                await session.commit()
                self.logger.info(
                    f"Successfully resolved prediction {prediction_id} "
                    f"with winner: {winning_option}"
                )
                return True
                
        except Exception as e:
            self.logger.error(f"Error resolving prediction: {e}", exc_info=True)
            return False