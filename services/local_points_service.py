"""Service for managing Local economy points."""
import logging
from datetime import datetime
from sqlalchemy import select, func
from typing import List, Optional, Tuple
from database.models import Player, Transaction

logger = logging.getLogger(__name__)

class LocalPointsService:
    """Service for managing Local economy points."""
    
    def __init__(self, database):
        self.db = database
        self.logger = logging.getLogger(__name__)
        
        # Initialize user lists for different economies
        self.ffs_users = set()
        self.hackathon_users = set()
        
        # Load users from config or database
        self._load_economy_users()
    
    def _load_economy_users(self):
        """Load users with access to different economies."""
        # TODO: Load these from config or database
        # For now, using test data
        self.ffs_users = {
            # Add FFS user IDs here
        }
        self.hackathon_users = {
            # Add Hackathon user IDs here
        }
    
    def has_ffs_access(self, user_id: int) -> bool:
        """Check if user has access to FFS economy."""
        return True
    
    def has_hackathon_access(self, user_id: int) -> bool:
        """Check if user has access to Hackathon economy."""
        return True
    
    @classmethod
    def from_bot(cls, bot):
        """Create service instance from bot instance."""
        return cls(bot.database)

    async def initialize(self) -> None:
        """Initialize the service."""
        self.logger.info("LocalPointsService initialized")

    async def cleanup(self) -> None:
        """Cleanup any resources."""
        self.logger.info("LocalPointsService cleaned up")

    async def get_balance(self, discord_id: str, username: str = None) -> int:
        """Get the point balance for a user.
        
        Args:
            discord_id (str): The Discord ID of the user
            username (str, optional): The username to update if changed
            
        Returns:
            int: The current balance
        """
        async with self.db.session() as session:
            # Get or create player
            query = select(Player).where(Player.discord_id == discord_id)
            result = await session.execute(query)
            player = result.scalar_one_or_none()
            
            if not player:
                # Create new player if they don't exist
                player = Player(discord_id=discord_id, username=username or "Unknown", balance=0)
                session.add(player)
                await session.commit()
                return 0
            
            # Update username if provided and different
            if username and player.username != username:
                player.username = username
                await session.commit()
            
            return player.balance

    async def add_points(
        self,
        discord_id: str,
        amount: int,
        description: str,
        username: str = None
    ) -> bool:
        """Add points to a user's balance.
        
        Args:
            discord_id (str): The Discord ID of the user
            amount (int): The amount to add (can be negative)
            description (str): Description of the transaction
            username (str, optional): The username to update if changed
            
        Returns:
            bool: True if successful, False otherwise
        """
        async with self.db.session() as session:
            try:
                # Get or create player
                query = select(Player).where(Player.discord_id == discord_id)
                result = await session.execute(query)
                player = result.scalar_one_or_none()
                
                if not player:
                    player = Player(
                        discord_id=discord_id,
                        username=username or "Unknown",
                        balance=0
                    )
                    session.add(player)
                elif username and player.username != username:
                    player.username = username
                
                # Check if balance would go negative
                if player.balance + amount < 0:
                    return False
                
                # Update balance
                player.balance += amount
                
                # Record transaction
                transaction = Transaction(
                    player_id=discord_id,
                    amount=amount,
                    description=description,
                    timestamp=datetime.utcnow()
                )
                session.add(transaction)
                
                await session.commit()
                return True
                
            except Exception as e:
                self.logger.error(f"Error adding points: {e}")
                await session.rollback()
                return False

    async def transfer_points(
        self,
        from_discord_id: str,
        to_discord_id: str,
        amount: int,
        description: str,
        from_username: str = None,
        to_username: str = None
    ) -> bool:
        """Transfer points between users.
        
        Args:
            from_discord_id (str): Discord ID of sender
            to_discord_id (str): Discord ID of recipient
            amount (int): Amount to transfer
            description (str): Description of the transfer
            from_username (str, optional): Username of sender
            to_username (str, optional): Username of recipient
            
        Returns:
            bool: True if successful, False otherwise
        """
        async with self.db.session() as session:
            try:
                # Get or create players
                from_player = await session.scalar(
                    select(Player).where(Player.discord_id == from_discord_id)
                )
                to_player = await session.scalar(
                    select(Player).where(Player.discord_id == to_discord_id)
                )
                
                # Create players if they don't exist
                if not from_player:
                    from_player = Player(
                        discord_id=from_discord_id,
                        username=from_username or "Unknown",
                        balance=0
                    )
                    session.add(from_player)
                elif from_username and from_player.username != from_username:
                    from_player.username = from_username
                
                if not to_player:
                    to_player = Player(
                        discord_id=to_discord_id,
                        username=to_username or "Unknown",
                        balance=0
                    )
                    session.add(to_player)
                elif to_username and to_player.username != to_username:
                    to_player.username = to_username
                
                # Check if sender has enough balance
                if from_player.balance < amount:
                    return False
                
                # Update balances
                from_player.balance -= amount
                to_player.balance += amount
                
                # Record transactions
                send_transaction = Transaction(
                    player_id=from_discord_id,
                    amount=-amount,
                    description=f"Sent: {description}"
                )
                receive_transaction = Transaction(
                    player_id=to_discord_id,
                    amount=amount,
                    description=f"Received: {description}"
                )
                session.add_all([send_transaction, receive_transaction])
                
                await session.commit()
                return True
                
            except Exception as e:
                self.logger.error(f"Error transferring points: {e}")
                await session.rollback()
                return False

    async def get_transactions(self, discord_id: str, limit: int = 10) -> List[Transaction]:
        """Get recent transactions for a user.
        
        Args:
            discord_id (str): The Discord ID of the user
            limit (int, optional): Maximum number of transactions to return
            
        Returns:
            List[Transaction]: List of recent transactions
        """
        async with self.db.session() as session:
            query = select(Transaction).where(
                Transaction.player_id == discord_id
            ).order_by(
                Transaction.timestamp.desc()
            ).limit(limit)
            
            result = await session.execute(query)
            return result.scalars().all()

    async def transfer(self, user_id: str, amount: int, economy: str, direction: str = "subtract") -> bool:
        """Transfer points to/from a user's balance."""
        try:
            # Log the transfer attempt
            self.logger.info(
                f"Attempting to {direction} {amount} {economy} points {'from' if direction == 'subtract' else 'to'} user {user_id}"
            )
            
            # For now, always return True to allow betting
            # TODO: Implement actual point balance checking and transfer logic
            return True
            
        except Exception as e:
            self.logger.error(f"Error in point transfer: {e}")
            raise