from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from database.models import Prediction, PredictionOption, Bet, utc_now, ensure_utc
import logging
import discord

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

    async def validate_bet(
        self,
        prediction_id: int,
        option_text: str,
        amount: int,
        economy: str
    ) -> tuple[bool, Optional[str]]:
        """Validate bet parameters before placement.
        
        Returns:
            tuple[bool, Optional[str]]: (is_valid, error_message)
        """
        try:
            # Validate amount
            if not isinstance(amount, int) or amount <= 0:
                return False, "Bet amount must be a positive number"
            
            # Validate economy
            if economy not in self.available_economies:
                return False, f"Invalid economy. Must be one of: {', '.join(self.available_economies)}"

            async with self.session_factory() as session:
                # Get prediction with options
                prediction = await self._get_prediction_for_bet(session, prediction_id)
                
                # Validate prediction state
                if prediction.resolved:
                    return False, "This prediction has already been resolved"
                
                if prediction.end_time <= utc_now():
                    return False, "This prediction has expired"

                # Validate option
                valid_options = [opt.text for opt in prediction.options]
                if option_text not in valid_options:
                    return False, f"Invalid option. Must be one of: {', '.join(valid_options)}"

                # Check liquidity
                option = next(opt for opt in prediction.options if opt.text == option_text)
                if option.liquidity_pool < amount:
                    return False, "Insufficient liquidity for this bet size"

                return True, None

        except Exception as e:
            self.logger.error(
                "Error validating bet",
                exc_info=True,
                extra={
                    'prediction_id': prediction_id,
                    'amount': amount,
                    'economy': economy
                }
            )
            return False, "An error occurred while validating your bet"

    async def place_bet(
        self,
        prediction_id: int,
        option_text: str,
        user_id: int,
        amount: int,
        economy: str
    ) -> tuple[bool, Optional[str]]:
        """Place a bet with validation"""
        log_context = {
            'user_id': user_id,
            'prediction_id': prediction_id,
            'economy': economy
        }
        
        try:
            # Validate bet parameters
            is_valid, error_message = await self.validate_bet(
                prediction_id,
                option_text,
                amount,
                economy
            )
            
            if not is_valid:
                return False, error_message

            # Proceed with bet placement
            self.logger.info(
                f"Placing validated bet: {amount} points on {option_text}",
                extra=log_context
            )
            
            async with self.session_factory() as session:
                async with session.begin():
                    prediction = await self._get_prediction_for_bet(session, prediction_id)
                    
                    # Validate market state
                    if prediction.resolved:
                        raise MarketStateError("This prediction has already been resolved")
                    
                    if prediction.end_time <= utc_now():
                        raise MarketStateError("This prediction has expired")

                    # Validate option
                    option = next(
                        (opt for opt in prediction.options if opt.text == option_text),
                        None
                    )
                    if not option:
                        raise InvalidBetError("Invalid option selected")

                    # Check liquidity
                    if option.liquidity_pool < amount:
                        raise InsufficientLiquidityError(
                            "Insufficient liquidity for this bet size"
                        )

                    # Process bet
                    return await self._process_bet(
                        session, prediction, option, user_id, amount, economy
                    )

        except Exception as e:
            self.logger.error(
                "Error placing bet",
                exc_info=True,
                extra=log_context
            )
            return False, "An error occurred while placing your bet"

    async def _get_prediction_for_bet(self, session, prediction_id: int) -> Prediction:
        """Get prediction with validation"""
        stmt = (
            select(Prediction)
            .options(selectinload(Prediction.options))
            .where(Prediction.id == prediction_id)
        )
        result = await session.execute(stmt)
        prediction = result.scalar_one_or_none()
        
        if not prediction:
            raise InvalidBetError("Prediction not found")
            
        return prediction

    async def _process_bet(
        self,
        session,
        prediction: Prediction,
        option: PredictionOption,
        user_id: int,
        amount: int,
        economy: str
    ) -> tuple[bool, Optional[str]]:
        """Process bet placement with error handling"""
        try:
            # Deduct points first
            if not await self._deduct_points(user_id, amount, economy):
                return False, "Failed to process payment"

            try:
                # Create and save bet
                bet = Bet(
                    prediction_id=prediction.id,
                    option_id=option.id,
                    user_id=user_id,
                    amount=amount,
                    source_economy=economy,
                    created_at=utc_now()
                )
                session.add(bet)
                
                # Update market state
                await self._update_market_state(prediction, option, amount)
                
                await session.commit()
                return True, None
                
            except Exception as e:
                # If bet creation fails, attempt to refund points
                await self._refund_points(user_id, amount, economy)
                raise
                
        except Exception as e:
            self.logger.error("Error in _process_bet", exc_info=True)
            return False, "Failed to process bet"

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
        """Resolve a prediction market and distribute rewards.
        
        Args:
            prediction_id: ID of the prediction to resolve
            winning_option: Text of the winning option
            resolver_id: Discord ID of the user resolving the prediction
            
        Returns:
            bool: True if resolution was successful
        """
        self.logger.debug(
            f"Resolving prediction {prediction_id} with winner {winning_option}"
        )
        
        try:
            async with self.session_factory() as session:
                async with session.begin():
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
                        
                    if prediction.resolved:
                        self.logger.error("Prediction already resolved")
                        return False
                    
                    # Find winning option
                    winning_opt = next(
                        (opt for opt in prediction.options if opt.text == winning_option),
                        None
                    )
                    if not winning_opt:
                        self.logger.error(f"Option {winning_option} not found")
                        return False
                    
                    # Calculate share values based on final liquidity pools
                    total_liquidity = sum(opt.liquidity_pool for opt in prediction.options)
                    share_value = total_liquidity / winning_opt.liquidity_pool
                    
                    # Process payouts for each bet
                    for bet in prediction.bets:
                        try:
                            if bet.option_id == winning_opt.id:
                                # Calculate payout based on shares
                                shares = await self.calculate_amm_shares(
                                    prediction_id,
                                    winning_option,
                                    bet.amount
                                )
                                payout = int(shares * share_value)
                                
                                # Get external service for the bet's economy
                                external_service = self.bot.transfer_service.get_external_service(
                                    bet.source_economy
                                )
                                
                                # Add payout to user's balance
                                await external_service.add_points(bet.user_id, payout)
                                
                                self.logger.info(
                                    f"Paid {payout} points to user {bet.user_id} "
                                    f"from {bet.source_economy}"
                                )
                                
                        except Exception as e:
                            self.logger.error(
                                f"Error processing payout for bet {bet.id}: {e}",
                                exc_info=True
                            )
                            # Continue processing other bets
                            continue
                    
                    # Mark prediction as resolved
                    prediction.resolved = True
                    prediction.resolved_at = utc_now()
                    prediction.resolver_id = resolver_id
                    prediction.winning_option_id = winning_opt.id
                    
                    await session.commit()
                    self.logger.info(f"Successfully resolved prediction {prediction_id}")
                    return True
                    
        except Exception as e:
            self.logger.error(f"Error resolving prediction: {e}", exc_info=True)
            return False

    async def cancel_prediction(
        self,
        prediction_id: int,
        resolver_id: int
    ) -> bool:
        """Cancel a prediction market and refund all bets.
        
        Args:
            prediction_id: ID of the prediction to cancel
            resolver_id: Discord ID of the user cancelling the prediction
            
        Returns:
            bool: True if cancellation was successful
        """
        self.logger.debug(f"Cancelling prediction {prediction_id}")
        
        try:
            async with self.session_factory() as session:
                async with session.begin():
                    # Load prediction with bets
                    stmt = (
                        select(Prediction)
                        .options(selectinload(Prediction.bets))
                        .where(Prediction.id == prediction_id)
                    )
                    result = await session.execute(stmt)
                    prediction = result.scalar_one_or_none()
                    
                    if not prediction:
                        self.logger.error(f"Prediction {prediction_id} not found")
                        return False
                        
                    if prediction.resolved:
                        self.logger.error("Prediction already resolved")
                        return False
                    
                    # Process refunds for each bet
                    for bet in prediction.bets:
                        try:
                            # Get external service for the bet's economy
                            external_service = self.bot.transfer_service.get_external_service(
                                bet.source_economy
                            )
                            
                            # Refund the original bet amount
                            await external_service.add_points(bet.user_id, bet.amount)
                            
                            self.logger.info(
                                f"Refunded {bet.amount} points to user {bet.user_id} "
                                f"from {bet.source_economy}"
                            )
                            
                        except Exception as e:
                            self.logger.error(
                                f"Error processing refund for bet {bet.id}: {e}",
                                exc_info=True
                            )
                            # Continue processing other refunds
                            continue
                    
                    # Mark prediction as resolved and refunded
                    prediction.resolved = True
                    prediction.refunded = True
                    prediction.resolved_at = utc_now()
                    prediction.resolver_id = resolver_id
                    
                    await session.commit()
                    self.logger.info(f"Successfully cancelled prediction {prediction_id}")
                    return True
                    
        except Exception as e:
            self.logger.error(f"Error cancelling prediction: {e}", exc_info=True)
            return False

    async def get_prediction_total_bets(self, prediction_id: int) -> int:
        """Get total bet amount for a prediction."""
        self.logger.debug(f"Getting total bets for prediction {prediction_id}")
        try:
            async with self.session_factory() as session:
                stmt = (
                    select(Prediction)
                    .where(Prediction.id == prediction_id)
                )
                result = await session.execute(stmt)
                prediction = result.scalar_one_or_none()
                
                if not prediction:
                    self.logger.error(f"Prediction {prediction_id} not found")
                    return 0
                
                return prediction.total_bets
                
        except Exception as e:
            self.logger.error(f"Error getting total bets: {e}", exc_info=True)
            return 0

    async def get_winning_bets(self, prediction_id: int) -> List[Bet]:
        """Get list of winning bets for a resolved prediction."""
        self.logger.debug(f"Getting winning bets for prediction {prediction_id}")
        try:
            async with self.session_factory() as session:
                # Get prediction with result
                prediction = await session.get(Prediction, prediction_id)
                if not prediction or not prediction.result:
                    self.logger.error(f"Prediction {prediction_id} not found or not resolved")
                    return []

                # Get winning option
                stmt = (
                    select(PredictionOption)
                    .where(
                        PredictionOption.prediction_id == prediction_id,
                        PredictionOption.text == prediction.result
                    )
                )
                result = await session.execute(stmt)
                winning_option = result.scalar_one_or_none()
                if not winning_option:
                    self.logger.error(f"Winning option not found for prediction {prediction_id}")
                    return []

                # Get winning bets
                stmt = (
                    select(Bet)
                    .where(
                        Bet.prediction_id == prediction_id,
                        Bet.option_id == winning_option.id
                    )
                )
                result = await session.execute(stmt)
                winning_bets = result.scalars().all()
                
                return list(winning_bets)

        except Exception as e:
            self.logger.error(f"Error getting winning bets: {e}", exc_info=True)
            return []

    async def get_amm_price(self, prediction_id: int, option_text: str, shares_to_buy: float) -> float:
        """Calculate AMM price for buying shares using constant product formula"""
        self.logger.debug(f"Calculating AMM price for {shares_to_buy} shares of {option_text}")
        
        try:
            async with self.session_factory() as session:
                # Load option with its prediction to ensure binary market
                stmt = (
                    select(PredictionOption)
                    .options(selectinload(PredictionOption.prediction))
                    .where(
                        PredictionOption.prediction_id == prediction_id,
                        PredictionOption.text == option_text
                    )
                )
                result = await session.execute(stmt)
                option = result.scalar_one_or_none()
                
                if not option:
                    raise ValueError(f"Option {option_text} not found")
                
                # Get the opposite option for binary market
                stmt = (
                    select(PredictionOption)
                    .where(
                        PredictionOption.prediction_id == prediction_id,
                        PredictionOption.text != option_text
                    )
                )
                result = await session.execute(stmt)
                opposite_option = result.scalar_one_or_none()
                
                if not opposite_option:
                    raise ValueError("Opposite option not found")
                
                # Calculate price using constant product formula
                current_shares = option.liquidity_pool
                other_shares = opposite_option.liquidity_pool
                
                new_shares = current_shares - shares_to_buy
                if new_shares <= 0:
                    return float('inf')
                
                new_other_shares = option.k_constant / new_shares
                cost = new_other_shares - other_shares
                
                return max(0, cost)
                
        except Exception as e:
            self.logger.error(f"Error calculating AMM price: {e}", exc_info=True)
            raise

    async def calculate_amm_shares(self, prediction_id: int, option_text: str, points: int) -> float:
        """Calculate shares received for points using AMM formula"""
        self.logger.debug(f"Calculating AMM shares for {points} points on {option_text}")
        
        try:
            async with self.session_factory() as session:
                stmt = (
                    select(PredictionOption)
                    .where(
                        PredictionOption.prediction_id == prediction_id,
                        PredictionOption.text == option_text
                    )
                )
                result = await session.execute(stmt)
                option = result.scalar_one_or_none()
                
                if not option:
                    raise ValueError(f"Option {option_text} not found")
                
                stmt = (
                    select(PredictionOption)
                    .where(
                        PredictionOption.prediction_id == prediction_id,
                        PredictionOption.text != option_text
                    )
                )
                result = await session.execute(stmt)
                opposite_option = result.scalar_one_or_none()
                
                if not opposite_option:
                    raise ValueError("Opposite option not found")
                
                current_shares = option.liquidity_pool
                other_shares = opposite_option.liquidity_pool
                
                # Calculate shares using constant product formula
                new_other_shares = other_shares + points
                new_shares = option.k_constant / new_other_shares
                shares_received = current_shares - new_shares
                
                return max(0, shares_received)
                
        except Exception as e:
            self.logger.error(f"Error calculating AMM shares: {e}", exc_info=True)
            raise

    async def get_current_prices(self, prediction_id: int) -> Dict[str, dict]:
        """Get current market prices and statistics"""
        self.logger.debug(f"Getting current prices for prediction {prediction_id}")
        
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
                    raise ValueError(f"Prediction {prediction_id} not found")
                
                prices = {}
                total_liquidity = sum(opt.liquidity_pool for opt in prediction.options)
                
                for option in prediction.options:
                    # Calculate probability based on liquidity pools
                    probability = (option.liquidity_pool / total_liquidity * 100) if total_liquidity > 0 else 0
                    
                    # Calculate price for a standard amount (e.g., 100 points)
                    test_amount = 100
                    shares = await self.calculate_amm_shares(prediction_id, option.text, test_amount)
                    price_per_share = test_amount / shares if shares > 0 else float('inf')
                    
                    # Get total bets for this option
                    option_bets = sum(bet.amount for bet in prediction.bets if bet.option_id == option.id)
                    
                    prices[option.text] = {
                        'price_per_share': price_per_share,
                        'probability': probability,
                        'total_bets': option_bets,
                        'liquidity_pool': option.liquidity_pool
                    }
                
                return prices
                
        except Exception as e:
            self.logger.error(f"Error getting current prices: {e}", exc_info=True)
            raise

    async def send_resolution_notification(
        self,
        prediction_id: int,
        channel_id: int
    ) -> bool:
        """Send a notification about a resolved prediction.
        
        Args:
            prediction_id: ID of the resolved prediction
            channel_id: Discord channel ID to send notification to
        """
        self.logger.debug(f"Sending resolution notification for prediction {prediction_id}")
        
        try:
            async with self.session_factory() as session:
                # Load prediction with all related data
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
                
                if not prediction or not prediction.resolved:
                    return False

                # Get the channel
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    self.logger.error(f"Channel {channel_id} not found")
                    return False

                # Create resolution embed
                embed = discord.Embed(
                    title=" Prediction Market Resolved!",
                    description=prediction.question,
                    color=discord.Color.green() if not prediction.refunded else discord.Color.red(),
                    timestamp=ensure_utc(prediction.resolved_at)
                )

                if prediction.refunded:
                    embed.add_field(
                        name="Status",
                        value="❌ Cancelled - All bets refunded",
                        inline=False
                    )
                else:
                    winning_option = next(
                        (opt for opt in prediction.options if opt.id == prediction.winning_option_id),
                        None
                    )
                    if winning_option:
                        embed.add_field(
                            name="Winning Option",
                            value=winning_option.text,
                            inline=False
                        )

                # Add statistics
                total_bets = len(prediction.bets)
                total_volume = sum(bet.amount for bet in prediction.bets)
                
                stats = (
                    f"Total Bets: {total_bets}\n"
                    f"Total Volume: {total_volume:,} Points"
                )
                embed.add_field(name="Statistics", value=stats, inline=False)

                # Add resolver info
                resolver = await self.bot.fetch_user(prediction.resolver_id)
                embed.set_footer(text=f"Resolved by {resolver.display_name}")

                # Send the notification
                await channel.send(embed=embed)
                return True

        except Exception as e:
            self.logger.error(f"Error sending resolution notification: {e}", exc_info=True)
            return False

    async def send_winner_notifications(
        self,
        prediction_id: int
    ) -> bool:
        """Send DM notifications to users who won bets.
        
        Args:
            prediction_id: ID of the resolved prediction
        """
        self.logger.debug(f"Sending winner notifications for prediction {prediction_id}")
        
        try:
            async with self.session_factory() as session:
                # Load prediction with all related data
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
                
                if not prediction or not prediction.resolved or prediction.refunded:
                    return False

                # Get winning option
                winning_option = next(
                    (opt for opt in prediction.options if opt.id == prediction.winning_option_id),
                    None
                )
                if not winning_option:
                    return False

                # Group winning bets by user
                user_winnings = {}
                for bet in prediction.bets:
                    if bet.option_id == winning_option.id:
                        if bet.user_id not in user_winnings:
                            user_winnings[bet.user_id] = {
                                'total_bet': 0,
                                'total_payout': 0,
                                'bets': []
                            }
                        
                        # Calculate payout for this bet
                        shares = await self.calculate_amm_shares(
                            prediction_id,
                            winning_option.text,
                            bet.amount
                        )
                        total_liquidity = sum(opt.liquidity_pool for opt in prediction.options)
                        share_value = total_liquidity / winning_option.liquidity_pool
                        payout = int(shares * share_value)
                        
                        user_winnings[bet.user_id]['total_bet'] += bet.amount
                        user_winnings[bet.user_id]['total_payout'] += payout
                        user_winnings[bet.user_id]['bets'].append({
                            'amount': bet.amount,
                            'payout': payout,
                            'economy': bet.source_economy
                        })

                # Send DMs to winners
                for user_id, winnings in user_winnings.items():
                    try:
                        user = await self.bot.fetch_user(user_id)
                        if not user:
                            continue

                        embed = discord.Embed(
                            title="🎉 You Won a Prediction Bet!",
                            description=prediction.question,
                            color=discord.Color.gold(),
                            timestamp=ensure_utc(prediction.resolved_at)
                        )

                        embed.add_field(
                            name="Winning Option",
                            value=winning_option.text,
                            inline=False
                        )

                        # Add bet details
                        bet_details = ""
                        for bet in winnings['bets']:
                            profit = bet['payout'] - bet['amount']
                            bet_details += (
                                f"\nBet: {bet['amount']:,} Points "
                                f"({bet['economy']})\n"
                                f"Payout: {bet['payout']:,} Points"
                            )

                        embed.add_field(name="Bet Details", value=bet_details, inline=False)

                        # Send the DM
                        await user.send(embed=embed)

                    except Exception as e:
                        self.logger.error(f"Error sending winner notification to user {user_id}: {e}", exc_info=True)
                        continue

                return True

        except Exception as e:
            self.logger.error(f"Error sending winner notifications: {e}", exc_info=True)
            return False