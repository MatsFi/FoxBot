from typing import Optional
import aiohttp
from database.database import Database
from database.models import Player, Transaction

class PointsService:
    def __init__(self, database: Database, api_config: dict):
        self.db = database
        self.base_url = api_config['base_url']
        self.api_key = api_config['api_key']
        self.realm_id = api_config['realm_id']
        self._session: Optional[aiohttp.ClientSession] = None

    async def initialize(self):
        """Initialize HTTP session and database."""
        if not self._session:
            self._session = aiohttp.ClientSession()
        await self.db.create_all()

    async def cleanup(self):
        """Cleanup resources."""
        if self._session:
            await self._session.close()
            self._session = None

    async def get_balance(self, discord_id: str) -> int:
        """Get user's point balance."""
        async with self.db.session() as session:
            player = await session.get(Player, discord_id)
            if not player:
                return 0
            return player.points

    async def add_points(self, discord_id: str, amount: int, description: str) -> bool:
        """Add points to user's balance."""
        async with self.db.session() as session:
            player = await session.get(Player, discord_id)
            if not player:
                player = Player(discord_id=discord_id, points=0)
                session.add(player)
            
            player.points += amount
            transaction = Transaction(
                player_id=player.id,
                amount=amount,
                description=description
            )
            session.add(transaction)
            return True