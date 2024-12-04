from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from sqlalchemy import select, func, and_, not_
from sqlalchemy.orm import selectinload
from database.models import Prediction, PredictionOption, Bet, utc_now, ensure_utc
import logging
import discord
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession

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

    def __init__(self, bot, session_factory):
        self.bot = bot
        self.session_factory = session_factory
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
        """Validate bet parameters before placement."""
        try:
            # Validate amount
            if not isinstance(amount, int) or amount <= 0:
                return False, "Bet amount must be a positive number"
            
            # Validate economy
            if economy not in self.available_economies:
                return False, f"Invalid economy. Must be one of: {', '.join(self.available_economies)}"

            async with self.session_factory() as session:
                prediction = await self._get_prediction_for_bet(session, prediction_id)
                if not prediction:
                    return False, "Prediction not found"
                
                # Validate prediction state
                if prediction.resolved:
                    return False, "This prediction has already been resolved"
                
                # Ensure both datetimes are UTC aware before comparison
                prediction_end = ensure_utc(prediction.end_time)
                current_time = utc_now()
                
                if prediction_end <= current_time:
                    return False, "This prediction has expired"

                # Validate option
                valid_options = [opt.text for opt in prediction.options]
                if option_text not in valid_options:
                    return False, f"Invalid option. Must be one of: {', '.join(valid_options)}"

                return True, None

        except Exception as e:
            self.logger.error(
                f"Error validating bet: {str(e)}",
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
        option_id: int,
        user_id: int,
        amount: int,
        economy: str = "points"
    ) -> bool:
        """Place a bet on a prediction option."""
        async with self.session_factory() as session:
            try:
                self.logger.debug(
                    f"Starting bet placement - User: {user_id}, "
                    f"Prediction: {prediction_id}, Option: {option_id}, "
                    f"Amount: {amount}, Economy: {economy}"
                )

                # Fetch the prediction and option with eager loading
                prediction = await session.execute(
                    select(Prediction)
                    .options(selectinload(Prediction.options))
                    .where(Prediction.id == prediction_id)
                )
                prediction = prediction.scalar_one_or_none()
                
                if not prediction:
                    raise InvalidBetError("Prediction not found.")

                option = next((o for o in prediction.options if o.id == option_id), None)
                if not option:
                    raise InvalidBetError("Option not found.")

                # Generate prediction market account ID
                prediction_account = f"prediction_{prediction_id}"
                self.logger.debug(f"Using prediction market account: {prediction_account}")

                # Transfer points from external economy directly to prediction market account
                transfer_result = await self.bot.transfer_service.deposit_to_local(
                    economy_name=economy,
                    discord_id=str(user_id),  # Source of funds
                    amount=amount,
                    username=prediction_account  # Destination account
                )

                if not transfer_result.success:
                    self.logger.debug(
                        f"Transfer failed - User: {user_id}, "
                        f"Amount: {amount}, Error: {transfer_result.message}"
                    )
                    raise InsufficientLiquidityError(transfer_result.message)

                self.logger.debug(
                    f"Transfer successful - {amount} points moved from "
                    f"{user_id} to {prediction_account}"
                )

                # Create and add the bet record
                bet = Bet(
                    user_id=user_id,
                    prediction_id=prediction_id,
                    option_id=option_id,
                    amount=amount,
                    economy=economy
                )
                session.add(bet)

                # Update the option's total bet amount
                option.total_bet_amount += amount
                session.add(option)

                await session.commit()

                self.logger.debug(
                    f"Bet placement complete - User: {user_id}, "
                    f"Prediction: {prediction_id}, Option: {option_id}"
                )
                return True

            except Exception as e:
                self.logger.error(f"Error placing bet: {str(e)}", exc_info=True)
                # If we need to refund, use withdraw_to_external
                if 'transfer_result' in locals() and transfer_result.success:
                    self.logger.debug(
                        f"Attempting to refund {amount} points to {user_id} "
                        f"from {prediction_account}"
                    )
                    try:
                        refund_result = await self.bot.transfer_service.withdraw_to_external(
                            economy_name=economy,
                            discord_id=prediction_account,  # Source (prediction market)
                            amount=amount,
                            username=str(user_id)  # Destination (user)
                        )
                        if not refund_result.success:
                            self.logger.error(
                                f"Failed to refund bet: {refund_result.message}"
                            )
                    except Exception as refund_error:
                        self.logger.error(
                            f"Error refunding bet: {str(refund_error)}", 
                            exc_info=True
                        )
                raise

    async def resolve_prediction(self, prediction_id: int, winning_option_id: int) -> bool:
        """Resolve a prediction and process payouts."""
        self.logger.debug(
            f"Starting prediction resolution - Prediction: {prediction_id}, "
            f"Winning Option: {winning_option_id}"
        )
        
        async with self.session_factory() as session:
            try:
                prediction = await session.execute(
                    select(Prediction)
                    .options(
                        selectinload(Prediction.options),
                        selectinload(Prediction.bets)
                    )
                    .where(Prediction.id == prediction_id)
                )
                prediction = prediction.scalar_one_or_none()

                if not prediction:
                    self.logger.error(f"Prediction {prediction_id} not found")
                    return False

                # Calculate pools
                total_pool = sum(bet.amount for bet in prediction.bets)
                winning_pool = sum(
                    bet.amount for bet in prediction.bets 
                    if bet.option_id == winning_option_id
                )

                prediction_account = f"prediction_{prediction_id}"

                # Process payouts for winning bets
                for bet in prediction.bets:
                    if bet.option_id == winning_option_id and winning_pool > 0:
                        payout_ratio = total_pool / winning_pool
                        payout_amount = int(bet.amount * payout_ratio)
                        
                        try:
                            # Add points to external economy first
                            external_success = await self.bot.transfer_service.get_external_service(
                                bet.economy
                            ).add_points(bet.user_id, payout_amount)
                            
                            if not external_success:
                                self.logger.error(
                                    f"Failed to transfer winnings - User: {bet.user_id}, "
                                    f"Amount: {payout_amount}"
                                )
                                continue

                            self.logger.debug(
                                f"Successfully paid out {payout_amount} to user {bet.user_id}"
                            )

                        except Exception:
                            self.logger.error(
                                f"Error processing payout - User: {bet.user_id}, "
                                f"Amount: {payout_amount}",
                                exc_info=True
                            )
                            continue

                # Mark prediction as resolved
                prediction.resolved = True
                prediction.winning_option_id = winning_option_id
                await session.commit()

                self.logger.debug(f"Successfully resolved prediction {prediction_id}")
                return True

            except Exception:
                self.logger.error(
                    f"Error resolving prediction {prediction_id}",
                    exc_info=True
                )
                await session.rollback()
                return False

    async def _get_prediction_for_bet(self, session, prediction_id: int) -> Optional[Prediction]:
        """Internal method to get prediction with relationships for betting."""
        stmt = select(Prediction).options(
            selectinload(Prediction.options),
            selectinload(Prediction.bets)
        ).where(Prediction.id == prediction_id)
        
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def _process_bet(
        self,
        session: AsyncSession,
        prediction: Prediction,
        option: PredictionOption,
        user_id: int,
        amount: int,
        economy: str = "points"
    ) -> bool:
        """Process a bet on a prediction option."""
        try:
            # Create bet
            bet = Bet(
                user_id=user_id,
                amount=amount,
                economy=economy,
                option=option
            )
            session.add(bet)
            
            # Update liquidity pool
            option.liquidity_pool = (option.liquidity_pool or 0) + amount
            
            try:
                await session.commit()
                self.logger.info(
                    "Bet processed successfully",
                    extra={
                        'prediction_id': prediction.id,
                        'user_id': user_id,
                        'amount': amount,
                        'option_id': option.id
                    }
                )
                return True
                
            except Exception as exc:  # Changed from 'e'
                self.logger.error(
                    "Database commit failed while processing bet",
                    extra={
                        'error': str(exc),
                        'prediction_id': prediction.id,
                        'user_id': user_id,
                        'amount': amount
                    },
                    exc_info=True
                )
                await session.rollback()
                return False
                
        except Exception as exc:  # Changed from 'e'
            self.logger.error(
                "Error processing bet",
                extra={
                    'error': str(exc),
                    'prediction_id': prediction.id,
                    'user_id': user_id,
                    'amount': amount
                },
                exc_info=True
            )
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

    async def get_current_prices(self, prediction_id: int) -> dict:
        """Get current prices and probabilities for all options in a prediction."""
        async with self.session_factory() as session:
            # Get prediction with options
            prediction = await session.execute(
                select(Prediction)
                .options(selectinload(Prediction.options))
                .where(Prediction.id == prediction_id)
            )
            prediction = prediction.scalar_one_or_none()
            
            if not prediction:
                return {}

            # Calculate total bets across all options
            total_bets = sum(option.total_bet_amount for option in prediction.options)
            
            self.logger.debug(f"Total bets for prediction {prediction_id}: {total_bets}")

            prices = {}
            for option in prediction.options:
                self.logger.debug(
                    f"Option {option.id} total_bet_amount: {option.total_bet_amount}"
                )
                
                if total_bets == 0:
                    probability = 100.0 / len(prediction.options)
                else:
                    probability = (option.total_bet_amount / total_bets) * 100

                prices[option.text] = {
                    'probability': probability,
                    'total_bets': option.total_bet_amount
                }

            return prices

    async def calculate_payout(self, prediction_id: int, option_text: str, bet_amount: int) -> float:
        """Calculate potential payout for a bet amount on a specific option."""
        try:
            prices = await self.get_current_prices(prediction_id)
            if not prices or option_text not in prices:
                return 0.0
            
            probability = prices[option_text]['probability'] / 100
            if probability <= 0:
                return 0.0
                
            expected_payout = (bet_amount / probability) if probability > 0 else 0
            
            self.logger.debug(
                "Calculated potential payout",
                extra={
                    'prediction_id': prediction_id,
                    'option': option_text,
                    'bet_amount': bet_amount,
                    'probability': probability,
                    'expected_payout': expected_payout
                }
            )
            
            return expected_payout

        except Exception as exc:
            self.logger.error(
                "Error calculating payout",
                extra={
                    'error': str(exc),
                    'prediction_id': prediction_id,
                    'option': option_text
                },
                exc_info=True
            )
            return 0.0

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
        """Get all predictions with their relationships loaded."""
        try:
            self.logger.debug("Fetching all predictions")
            async with self.session_factory() as session:
                # Use select() with proper relationship loading
                stmt = select(Prediction).options(
                    selectinload(Prediction.bets),
                    selectinload(Prediction.options)
                ).order_by(Prediction.created_at.desc())
                
                result = await session.execute(stmt)
                predictions = result.scalars().all()
                
                self.logger.debug(f"Found {len(predictions)} predictions with relationships")
                return predictions

        except Exception as e:
            self.logger.error(f"Error fetching predictions: {str(e)}", exc_info=True)
            return []

    async def create_prediction(
        self,
        question: str,
        options: List[str],
        creator_id: int,
        end_time: datetime,
        category: Optional[str] = None
    ) -> Optional[Prediction]:
        """Create a new prediction with options."""
        try:
            async with self.session_factory() as session:
                # Create prediction
                prediction = Prediction(
                    question=question,
                    creator_id=creator_id,
                    end_time=end_time,
                    category=category
                )
                session.add(prediction)
                
                # Create options
                for option_text in options:
                    option = PredictionOption(
                        text=option_text,
                        prediction=prediction
                    )
                    session.add(option)
                
                try:
                    await session.commit()
                    await session.refresh(prediction)
                    self.logger.info(
                        "Created new prediction",
                        extra={
                            'prediction_id': prediction.id,
                            'creator_id': creator_id,
                            'category': category
                        }
                    )
                    return prediction
                    
                except Exception as exc:
                    self.logger.error(
                        "Database commit failed",
                        extra={
                            'error': str(exc),
                            'question': question,
                            'creator_id': creator_id,
                            'category': category
                        },
                        exc_info=True
                    )
                    await session.rollback()
                    return None
                    
        except Exception as exc:
            self.logger.error(
                "Prediction creation failed",
                extra={
                    'error': str(exc),
                    'question': question,
                    'creator_id': creator_id,
                    'category': category
                },
                exc_info=True
            )
            return None

    async def schedule_prediction_resolution(self, prediction: Prediction):
        """Schedule notification for when betting period ends."""
        try:
            # Ensure both datetimes are UTC-aware before subtraction
            end_time = ensure_utc(prediction.end_time)
            current_time = utc_now()
            
            time_until_betting_ends = (end_time - current_time).total_seconds()
            if time_until_betting_ends > 0:
                self.logger.debug(f"Waiting {time_until_betting_ends} seconds for betting to end")
                await asyncio.sleep(time_until_betting_ends)
            
            # Recheck prediction state after waiting
            async with self.session_factory() as session:
                stmt = select(Prediction).where(Prediction.id == prediction.id)
                result = await session.execute(stmt)
                prediction = result.scalar_one_or_none()
                
                if not prediction:
                    self.logger.error("Prediction no longer exists")
                    return
                
                if prediction.resolved:
                    self.logger.debug("Prediction already resolved before betting end")
                    return
                
                self.logger.debug(f"Betting period ended for prediction: {prediction.question}")
                
                # Notify creator that betting period has ended
                try:
                    creator = await self.bot.fetch_user(prediction.creator_id)
                    await creator.send(
                        f"Betting has ended for your prediction: '{prediction.question}'\n"
                        f"Please use /resolve_prediction to resolve the market.\n"
                        f"If not resolved within 48 hours, all bets will be automatically refunded."
                    )
                    self.logger.debug(f"Sent notification to creator {prediction.creator_id}")
                except Exception as e:
                    self.logger.error(f"Error notifying creator: {str(e)}", exc_info=True)

        except Exception as e:
            self.logger.error(f"Error in resolution scheduler: {str(e)}", exc_info=True)

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
        """Schedule a notification for when a prediction ends."""
        self.scheduler.add_job(
            self._send_end_notification,
            'date',
            run_date=prediction.end_time,
            args=[prediction.id],
            id=f"end_notification_{prediction.id}"
        )
        
        self.logger.debug(
            "Scheduled end notification",
            extra={
                'prediction_id': prediction.id,
                'end_time': prediction.end_time.isoformat()
            }
        )

    async def get_unresolved_predictions(self) -> List[Prediction]:
        """Get all unresolved predictions."""
        try:
            async with self.session_factory() as session:
                stmt = select(Prediction).options(
                    selectinload(Prediction.options),
                    selectinload(Prediction.bets)
                ).where(not_(Prediction.resolved))
                
                result = await session.execute(stmt)
                return list(result.scalars().all())
        except Exception as exc:
            self.logger.error(
                "Error fetching unresolved predictions",
                extra={'error': str(exc)},
                exc_info=True
            )
            return []

    async def get_active_predictions(self):
        """Fetch active predictions from the database."""
        current_time = utc_now()
        
        async with self.session_factory() as session:
            # Use selectinload to eagerly load the options relationship
            result = await session.execute(
                select(Prediction)
                .options(selectinload(Prediction.options))
                .where(
                    and_(
                        Prediction.resolved == False,  # Not resolved
                        Prediction.end_time > current_time  # Not ended
                    )
                )
                .order_by(Prediction.end_time)  # Order by end time
            )
            
            predictions = result.scalars().all()
            self.logger.debug(
                f"Found {len(predictions)} active predictions before end time {current_time}"
            )
            return predictions

    async def get_pending_resolution_predictions(self) -> List[Prediction]:
        """Get predictions that have ended but haven't been resolved."""
        try:
            self.logger.debug("Fetching pending resolution predictions")
            current_time = utc_now()

            async with self.session_factory() as session:
                stmt = select(Prediction).options(
                    selectinload(Prediction.options),
                    selectinload(Prediction.bets)
                ).where(
                    and_(
                        Prediction.resolved == False,  # noqa: E712
                        Prediction.end_time <= current_time
                    )
                ).order_by(Prediction.end_time.asc())
                
                result = await session.execute(stmt)
                return list(result.scalars().all())

        except Exception as e:
            self.logger.error(f"Error fetching pending resolution predictions: {str(e)}", exc_info=True)
            return []

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
        """Get a single prediction by ID with relationships loaded."""
        try:
            async with self.session_factory() as session:
                stmt = select(Prediction).options(
                    selectinload(Prediction.options),
                    selectinload(Prediction.bets)
                ).where(Prediction.id == prediction_id)
                
                result = await session.execute(stmt)
                return result.scalar_one_or_none()
                
        except Exception as e:
            self.logger.error(f"Error fetching prediction: {str(e)}", exc_info=True)
            return None

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
                            await self.bot.transfer_service.add_points(
                                bet.user_id,
                                bet.amount,
                                bet.economy,
                                f"Refund: Prediction {prediction_id} cancelled"
                            )
                            
                            self.logger.info(
                                "Refunded bet",
                                extra={
                                    'user_id': bet.user_id,
                                    'amount': bet.amount,
                                    'prediction_id': prediction_id
                                }
                            )
                        except Exception as exc:
                            self.logger.error(
                                "Error processing refund",
                                extra={
                                    'error': str(exc),
                                    'bet_id': bet.id,
                                    'user_id': bet.user_id,
                                    'amount': bet.amount
                                },
                                exc_info=True
                            )
                    
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

    async def refund_prediction(self, prediction_id: int) -> bool:
        """Refund all bets for a prediction."""
        try:
            self.logger.debug(f"Attempting to refund prediction {prediction_id}")
            
            async with self.session_factory() as session:
                # Get prediction with relationships
                stmt = select(Prediction).options(
                    selectinload(Prediction.bets)
                ).where(Prediction.id == prediction_id)
                
                result = await session.execute(stmt)
                prediction = result.scalar_one_or_none()
                
                if not prediction:
                    self.logger.error(f"Prediction {prediction_id} not found")
                    return False

                if prediction.refunded:
                    self.logger.warning("Prediction already refunded")
                    return False

                # Process refunds
                for bet in prediction.bets:
                    # Return points to user's balance
                    success = await self.bot.transfer_service.add_points(
                        bet.user_id,
                        bet.amount,
                        bet.economy,
                        f"Refund: {prediction.question}"
                    )
                    if not success:
                        self.logger.error(f"Failed to refund bet {bet.id}")
                        return False

                # Mark prediction as refunded
                prediction.refunded = True
                prediction.resolved = True
                prediction.resolved_at = utc_now()
                
                await session.commit()
                
                self.logger.info(f"Successfully refunded prediction {prediction_id}")
                return True

        except Exception as e:
            self.logger.error(f"Error refunding prediction: {str(e)}", exc_info=True)
            return False

    async def get_unresolved_predictions_by_creator(self, creator_id: int) -> List[Prediction]:
        """Get all unresolved predictions created by a specific user."""
        try:
            async with self.session_factory() as session:
                stmt = select(Prediction).options(
                    selectinload(Prediction.options),
                    selectinload(Prediction.bets)
                ).where(
                    and_(
                        Prediction.creator_id == creator_id,
                        not_(Prediction.resolved)
                    )
                )
                
                result = await session.execute(stmt)
                return list(result.scalars().all())
        except Exception as exc:
            self.logger.error(
                "Error fetching unresolved predictions by creator",
                extra={
                    'error': str(exc),
                    'creator_id': creator_id
                },
                exc_info=True
            )
            return []

    async def get_prediction_status(self, prediction_id: int) -> Dict[str, Any]:
        """Get the current status of a prediction."""
        try:
            async with self.session_factory() as session:
                prediction = await self._get_prediction_with_relations(session, prediction_id)
                
                if not prediction:
                    self.logger.warning(
                        "Prediction not found",
                        extra={'prediction_id': prediction_id}
                    )
                    return {}

                # Calculate total pool and option pools
                total_pool = sum(bet.amount for bet in prediction.bets)
                option_pools = {}
                for option in prediction.options:
                    option_pool = sum(bet.amount for bet in prediction.bets if bet.option_id == option.id)
                    option_pools[option.text] = {
                        'pool_amount': option_pool,
                        'percentage': (option_pool / total_pool * 100) if total_pool > 0 else 0
                    }

                # Get current prices
                prices = await self.get_current_prices(prediction_id)

                # Build status response
                status = {
                    'id': prediction.id,
                    'question': prediction.question,
                    'creator_id': prediction.creator_id,
                    'created_at': prediction.created_at.isoformat(),
                    'end_time': prediction.end_time.isoformat(),
                    'resolved': prediction.resolved,
                    'resolved_at': prediction.resolved_at.isoformat() if prediction.resolved_at else None,
                    'resolver_id': prediction.resolver_id,
                    'total_pool': total_pool,
                    'options': option_pools,
                    'prices': prices,
                    'total_bets': len(prediction.bets),
                    'unique_bettors': len(set(bet.user_id for bet in prediction.bets))
                }

                if prediction.resolved:
                    winning_option = next(
                        (opt for opt in prediction.options if opt.id == prediction.winning_option_id),
                        None
                    )
                    if winning_option:
                        status['winning_option'] = winning_option.text
                        status['winning_pool'] = option_pools[winning_option.text]['pool_amount']

                return status

        except Exception as exc:
            self.logger.error(
                "Error getting prediction status",
                extra={
                    'error': str(exc),
                    'prediction_id': prediction_id
                },
                exc_info=True
            )
            return {}

    async def get_prediction_by_id(self, prediction_id: int) -> Optional[Prediction]:
        """Get a prediction by its ID."""
        try:
            async with self.session_factory() as session:
                stmt = select(Prediction).options(
                    selectinload(Prediction.options),
                    selectinload(Prediction.bets)
                ).where(Prediction.id == prediction_id)
                
                result = await session.execute(stmt)
                return result.scalar_one_or_none()
                
        except Exception as exc:
            self.logger.error(
                "Error fetching prediction by ID",
                extra={
                    'error': str(exc),
                    'prediction_id': prediction_id
                },
                exc_info=True
            )
            return None

    async def get_user_bets(self, user_id: int) -> List[Bet]:
        """Get all bets placed by a user."""
        try:
            async with self.session_factory() as session:
                stmt = select(Bet).options(
                    selectinload(Bet.option).selectinload(PredictionOption.prediction)
                ).where(Bet.user_id == user_id)
                
                result = await session.execute(stmt)
                return list(result.scalars().all())
                
        except Exception as exc:  # Changed from 'e' to 'exc'
            self.logger.error(
                "Error fetching user bets",
                extra={
                    'error': str(exc),
                    'user_id': user_id
                },
                exc_info=True
            )
            return []

    async def get_prediction_bets(self, prediction_id: int) -> List[Bet]:
        """Get all bets for a specific prediction."""
        try:
            async with self.session_factory() as session:
                stmt = select(Bet).join(PredictionOption).where(
                    PredictionOption.prediction_id == prediction_id
                )
                
                result = await session.execute(stmt)
                return list(result.scalars().all())
                
        except Exception as exc:  # Changed from 'e' to 'exc'
            self.logger.error(
                "Error fetching prediction bets",
                extra={
                    'error': str(exc),
                    'prediction_id': prediction_id
                },
                exc_info=True
            )
            return []

    async def get_option_bets(self, option_id: int) -> List[Bet]:
        """Get all bets for a specific option."""
        try:
            async with self.session_factory() as session:
                stmt = select(Bet).where(Bet.option_id == option_id)
                
                result = await session.execute(stmt)
                return list(result.scalars().all())
                
        except Exception as exc:  # Changed from 'e' to 'exc'
            self.logger.error(
                "Error fetching option bets",
                extra={
                    'error': str(exc),
                    'option_id': option_id
                },
                exc_info=True
            )
            return []

    async def auto_resolve_prediction(self, prediction_id: int) -> None:
        """Auto-resolve a prediction by refunding all bets."""
        try:
            async with self.session_factory() as session:
                prediction = await self._get_prediction_with_relations(session, prediction_id)
                if not prediction:
                    return

                if prediction.resolved:
                    return

                # Process refunds
                for bet in prediction.bets:
                    try:
                        await self.bot.transfer_service.add_points(  # Changed from credit
                            bet.user_id,
                            bet.amount,
                            bet.economy,
                            f"Auto-refund: Prediction {prediction_id} expired"
                        )
                        
                        self.logger.info(
                            "Auto-refunded bet",
                            extra={
                                'user_id': bet.user_id,
                                'amount': bet.amount,
                                'prediction_id': prediction_id
                            }
                        )
                    except Exception as exc:
                        self.logger.error(
                            "Error processing auto-refund",
                            extra={
                                'error': str(exc),
                                'bet_id': bet.id,
                                'user_id': bet.user_id,
                                'amount': bet.amount
                            },
                            exc_info=True
                        )

                # Mark prediction as resolved
                prediction.resolved = True
                prediction.resolved_at = utc_now()
                await session.commit()

        except Exception as exc:
            self.logger.error(
                "Error in auto-resolution",
                extra={
                    'error': str(exc),
                    'prediction_id': prediction_id
                },
                exc_info=True
            )