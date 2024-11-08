import aiohttp
from typing import Optional, Tuple
from database.models import Player, Transaction
from sqlalchemy import select
from datetime import datetime

class PointsService:
    def __init__(self, database, api_config: dict):
        self.db = database
        self.base_url = api_config['base_url'].rstrip('/')
        self.api_key = api_config['api_key']
        self.realm_id = api_config['realm_id']
        self._session = None

    @classmethod
    def from_bot(cls, bot):
        """Create a PointsService instance from a bot instance."""
        return cls(
            database=bot.database,
            api_config={
                'base_url': bot.config.api_base_url,
                'api_key': bot.config.api_key,
                'realm_id': bot.config.realm_id
            }
        )

    async def initialize(self):
        """Initialize HTTP session."""
        if not self._session:
            self._session = aiohttp.ClientSession()

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
                
                # Update points
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
                
                await session.commit()
                # Refresh the player object
                await session.refresh(player)
                print(f"Updated balance for {username}: {player.points}")  # Debug print
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