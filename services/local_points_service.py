"""Service for managing Local economy points."""
import logging
from datetime import datetime, timezone
from sqlalchemy import select, func
from typing import List, Optional, Tuple
from database.models import Player, Transaction, utc_now, ensure_utc

logger = logging.getLogger(__name__)

class LocalPointsService:
    """Service for managing Local economy points."""
    
    def __init__(self, database):
        self.db = database
        self.logger = logging.getLogger(__name__)
        
        # Initialize user lists for different economies
        self.ffs_users = set()
        self.hackathon_users = set()
    
    @classmethod
    def from_bot(cls, bot):
        """Create service instance from bot instance."""
        return cls(bot.database)
    
    async def initialize(self) -> None:
        """Initialize the service."""
        try:
            await self._load_economy_users()
            self.logger.info("LocalPointsService initialized successfully")
        except Exception as e:
            self.logger.error(f"Error initializing LocalPointsService: {e}")
            raise
    
    async def _load_economy_users(self):
        """Load users with access to different economies."""
        try:
            # TODO: Load these from config or database
            # For now, using test data
            self.ffs_users = {
                # Add FFS user IDs here
            }
            self.hackathon_users = {
                # Add Hackathon user IDs here
            }
            self.logger.info("Economy users loaded successfully")
        except Exception as e:
            self.logger.error(f"Error loading economy users: {e}")
            raise
    
    def has_ffs_access(self, user_id: int) -> bool:
        """Check if user has access to FFS economy."""
        return True
    
    def has_hackathon_access(self, user_id: int) -> bool:
        """Check if user has access to Hackathon economy."""
        return True
    
    async def cleanup(self):
        """Cleanup any resources."""
        self.logger.info("LocalPointsService cleanup completed")
    
    async def get_transactions(self, user_id: str, limit: int = 10) -> List[Transaction]:
        """Get recent transactions for a user."""
        try:
            async with self.db.session() as session:
                stmt = (
                    select(Transaction)
                    .where(Transaction.player_id == user_id)
                    .order_by(Transaction.timestamp.desc())
                    .limit(limit)
                )
                result = await session.execute(stmt)
                return list(result.scalars().all())
        except Exception as e:
            self.logger.error(f"Error getting transactions: {e}")
            return []
    
    async def add_transaction(
        self,
        user_id: str,
        amount: int,
        from_id: Optional[str] = None,
        to_id: Optional[str] = None
    ) -> bool:
        """Record a new transaction."""
        try:
            async with self.db.session() as session:
                transaction = Transaction(
                    player_id=user_id,
                    amount=amount,
                    from_id=from_id or user_id,
                    to_id=to_id or user_id,
                    timestamp=utc_now()  # Ensure UTC timestamp
                )
                session.add(transaction)
                await session.commit()
                return True
        except Exception as e:
            self.logger.error(f"Error adding transaction: {e}")
            return False