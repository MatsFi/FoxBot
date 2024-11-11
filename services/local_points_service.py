from typing import Tuple
from database.models import Player, Transaction
from sqlalchemy import select
from datetime import datetime

class LocalPointsService:
    def __init__(self, database):
        self.db = database
        self._session = None

    @classmethod
    def from_bot(cls, bot):
        """Create a LocalPointsService instance from a bot instance."""
        return cls(database=bot.database)

    async def initialize(self):
        # """Initialize HTTP session."""
        # if not self._session:
        #     self._session = aiohttp.ClientSession()
        """Initialize database."""
        # maybe we don't need to do anything here

    async def cleanup(self):
        """Cleanup resources."""
        if self._session:
            await self._session.close()
            self._session = None

    async def get_or_create_player(self, discord_id: str, username: str) -> Tuple[Player, bool]:
        """Get an existing player or create a new one.
        
        Returns:
            Tuple of (Player, bool) where bool indicates if player was created
        """
        async with self.db.session() as session:
            # Try to find existing player
            result = await session.execute(
                select(Player).where(Player.discord_id == discord_id)
            )
            player = result.scalars().first()
            
            created = False
            if not player:
                # Create new player
                player = Player(
                    discord_id=discord_id,
                    username=username,
                    points=0,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                session.add(player)
                await session.commit()
                created = True
            elif player.username != username:
                # Update username if changed
                player.username = username
                player.updated_at = datetime.utcnow()
                await session.commit()
                
            # Refresh the player object to ensure we have current data
            await session.refresh(player)
            return player, created

    async def get_balance(self, discord_id: str, username: str = None) -> int:
        """Get user's point balance."""
        try:
            async with self.db.session() as session:
                result = await session.execute(
                    select(Player).where(Player.discord_id == discord_id)
                )
                player = result.scalars().first()
                
                if not player and username:
                    player, _ = await self.get_or_create_player(discord_id, username)
                
                return player.points if player else 0
        except Exception as e:
            print(f"Error getting balance: {str(e)}")
            return 0

    async def transfer_points(self, from_discord_id: str, to_discord_id: str, amount: int, description: str) -> bool:
        """Transfer local points between users."""
        try:
            async with self.db.session() as session:
                # Get or create sender
                result = await session.execute(
                    select(Player).where(Player.discord_id == from_discord_id)
                )
                sender = result.scalars().first()
                if not sender:
                    return False
                
                # Get or create recipient
                result = await session.execute(
                    select(Player).where(Player.discord_id == to_discord_id)
                )
                recipient = result.scalars().first()
                if not recipient:
                    recipient = Player(
                        discord_id=to_discord_id,
                        username=to_discord_id,
                        points=0,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    session.add(recipient)

                # Ensure sender has enough points
                if sender.points < amount:
                    return False
                
                # Update sender and recipient balances
                sender.points -= amount
                recipient.points += amount
                
                # Record transactions
                sender_transaction = Transaction(
                    player_id=sender.id,
                    amount=-amount,
                    description=description,
                    timestamp=datetime.utcnow()
                )
                recipient_transaction = Transaction(
                    player_id=recipient.id,
                    amount=amount,
                    description=description,
                    timestamp=datetime.utcnow()
                )
                
                session.add(sender_transaction)
                session.add(recipient_transaction)
                
                await session.commit()

                return True
                
        except Exception as e:
            print(f"Error transferring points: {str(e)}")
            return False

    async def add_points(self, discord_id: str, amount: int, description: str, username: str) -> bool:
        """Add points to user's balance."""
        try:
            async with self.db.session() as session:
                # Get or create player
                result = await session.execute(
                    select(Player).where(Player.discord_id == discord_id)
                )
                player = result.scalars().first()
                
                if not player:
                    player = Player(
                        discord_id=discord_id,
                        username=username,
                        points=0,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    session.add(player)
                    # We need to flush here to get the player ID for the transaction
                    await session.flush()
                
                # Update points - THIS WAS THE ISSUE
                player.points += amount
                player.updated_at = datetime.utcnow()
                
                # Record transaction
                transaction = Transaction(
                    player_id=player.id,
                    amount=amount,
                    description=description,
                    timestamp=datetime.utcnow()
                )
                session.add(transaction)
                
                # Explicitly commit the changes
                await session.commit()
                
                # Verify the changes were persisted
                await session.refresh(player)
                if player.points < 0:  # Safety check for negative balance
                    await session.rollback()
                    return False
                
                return True
                
        except Exception as e:
            print(f"Error adding points: {str(e)}")
            return False

    async def get_transactions(self, discord_id: str, limit: int = 10) -> list[Transaction]:
        """Get recent transactions for a user."""
        try:
            async with self.db.session() as session:
                player = await session.execute(
                    select(Player).where(Player.discord_id == discord_id)
                )
                player = player.scalars().first()
                
                if not player:
                    return []
                
                transactions = await session.execute(
                    select(Transaction)
                    .where(Transaction.player_id == player.id)
                    .order_by(Transaction.timestamp.desc())
                    .limit(limit)
                )
                
                return transactions.scalars().all()
        except Exception as e:
            print(f"Error getting transactions: {str(e)}")
            return []