"""Points system models for managing user points and transactions."""
import aiohttp
from typing import Optional, Dict, List, Tuple
from database.models import Player, Transaction
from datetime import datetime
from sqlalchemy import select
import logging

logger = logging.getLogger(__name__)

class HackathonPointsManager:
    """Manages point operations and API interactions."""
    
    def __init__(self, database, api_config: dict):
        self.db = database
        self.base_url = api_config['base_url'].rstrip('/')
        self.api_key = api_config['api_key']
        self.realm_id = api_config['realm_id']
        self._session = None

    @classmethod
    def from_bot(cls, bot):
        """Create a LocalPointsService instance from a bot instance."""
        return cls(
            database=bot.database,
            # game host's API
            api_config={
                'base_url': bot.config.api_base_url,
                'api_key': bot.config.api_key,
                'realm_id': bot.config.realm_id
            }
        )

    async def initialize(self) -> None:
        """Initialize the points manager."""
        self._session = aiohttp.ClientSession()
        logger.info("Points manager initialized")

    async def cleanup(self) -> None:
        """Cleanup resources."""
        if self._session:
            await self._session.close()
            self._session = None
        logger.info("Points manager cleaned up")

    async def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

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
        
    async def get_balance(self, user_id: int) -> int:
        """Get the point balance for a user."""
        if not self._session:
            await self.initialize()

        try:
            async with self._session.get(
                f"{self.base_url}/api/v4/realms/{self.realm_id}/members/{user_id}",
                headers=await self._get_headers()
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    if not data.get('balances'):
                        return 0
                    realm_point_ids = list(data['balances'].keys())
                    return data['balances'].get(realm_point_ids[0], 0)
                else:
                    error_data = await response.json()
                    raise PointsError(f"Failed to get balance: {error_data}")
        except Exception as e:
            logger.error(f"Error getting balance for user {user_id}: {str(e)}")
            raise PointsError(f"Failed to get balance: {str(e)}")

    async def add_points(
        self,
        user_id: int,
        amount: int,
        description: str = ""
    ) -> bool:
        """Add points to a user's balance."""
        if not self._session:
            await self.initialize()
        try:
            async with self._session.patch(
                f"{self.base_url}/api/v4/realms/{self.realm_id}/members/{user_id}/tokenBalance",
                headers=await self._get_headers(),
                json={"tokens": amount}
            ) as response:
                if response.status == 200:
                    # Update local account
                    try:
                        async with self.db.session() as session:
                            result = await session.execute(
                                select(Player).where(Player.discord_id == user_id)
                            )
                            player = result.scalars().first()                           
                            if not player:
                                player = Player(
                                    discord_id=user_id,
                                    username=user_id,
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

                            return True
                        
                    except Exception as e:
                        print(f"Error getting local balance: {str(e)}")
                        return 0
                else:
                    error_data = await response.json()
                    raise PointsError(f"Failed to add points: {error_data}")
        except Exception as e:
            logger.error(f"Error adding points for user {user_id}: {str(e)}")
            raise PointsError(f"Failed to add points: {str(e)}")

    async def remove_points(
        self,
        user_id: int,
        amount: int,
        description: str = "remove points"
    ) -> bool:
        """Remove points from a user's balance."""
        return await self.add_points(user_id, -amount, description)

    async def transfer_points(
        self,
        from_user_id: int,
        to_user_id: int,
        amount: int,
        description: str = "transfer points"
    ) -> bool:
        """Transfer points between users."""
        if not self._session:
            await self.initialize()

        try:
            async with self._session.patch(
                f"{self.base_url}/api/v4/realms/{self.realm_id}/members/{from_user_id}/transfer",
                headers=await self._get_headers(),
                json={
                    "recipientId": to_user_id,
                    "tokens": amount
                }
            ) as response:
                if response.status == 200:
                    # Update local accounts
                    from_account = self._get_account(from_user_id)
                    to_account = self._get_account(to_user_id)
                    
                    # Record transactions
                    from_account.add_transaction(
                        -amount,
                        f"Transfer to {to_user_id}: {description}"
                    )
                    to_account.add_transaction(
                        amount,
                        f"Transfer from {from_user_id}: {description}"
                    )
                    return True
                else:
                    error_data = await response.json()
                    raise PointsError(f"Failed to transfer points: {error_data}")
        except Exception as e:
            logger.error(
                f"Error transferring points from {from_user_id} to {to_user_id}: {str(e)}"
            )
            raise PointsError(f"Failed to transfer points: {str(e)}")

    async def deposit_points(
        self,
        discord_id: str,
        amount: int,
    ) -> bool:
        """Deposit points into Local economy."""
        if not self._session:
            await self.initialize()

        try:
            async with self._session.patch(
                f"{self.base_url}/api/v4/realms/{self.realm_id}/members/{discord_id}/tokenBalance",
                headers=await self._get_headers(),
                json={
                    "recipientId": discord_id,
                    "tokens": -amount
                }
            ) as response:
                if response.status == 200:
                    # Update local account     
                    
                    
                    ############ call to Local economy to do this update.
                    # local_account = self._get_account(discord_id)
                    # local_account.balance += amount
                    
                    # # Record transaction
                    # # add transaction(method) may have a bug with recording new balance as += amount

                    # local_account.add_transaction(
                    #     amount,
                    #     "Deposit from Hackathon points into Local economy"
                    # )
                    return True
                else:
                    error_data = await response.json()
                    raise PointsError(f"Failed to debit Hackathon points: {error_data}")

        except Exception as e:
            logger.error(
                f"Error depositing points from Hackathon economy into your Local account: {str(e)}"
            )
            raise PointsError(f"Failed to deposit Hackathon points: {str(e)}")

    async def get_top_balances(self, limit: int = 10) -> List[tuple[int, int]]:
        """Get top point balances.
        
        Args:
            limit: Maximum number of results to return
            
        Returns:
            List of (user_id, balance) tuples
        """
        if not self._session:
            await self.initialize()

        try:
            async with self._session.get(
                f"{self.base_url}/api/v4/realms/{self.realm_id}/leaderboard",
                headers=await self._get_headers(),
                params={"limit": limit}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return [(entry['userId'], entry['balance']) for entry in data]
                else:
                    error_data = await response.json()
                    raise PointsError(f"Failed to get leaderboard: {error_data}")
        except Exception as e:
            logger.error(f"Error getting top balances: {str(e)}")
            raise PointsError(f"Failed to get leaderboard: {str(e)}")

class PointsError(Exception):
    """Custom exception for points-related errors."""
    pass