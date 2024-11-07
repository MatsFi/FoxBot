"""Points system models for managing user points and transactions."""
import aiohttp
import sqlite3
from typing import Optional, Dict, List
import logging

logger = logging.getLogger(__name__)

class PointsManager:
    """Manages point operations and API interactions."""
    
    def __init__(self, base_url: str, api_key: str, realm_id: str, hackathon_api_key: str, hackathon_realm_id: str, db_path: str):
        """Initialize the points manager.
        
        Args:
            base_url: Base URL for the points API
            api_key: API authentication key
            realm_id: Realm identifier
        """
        self.conn = sqlite3.connect(db_path)
        self.create_table()

        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.realm_id = realm_id
        self.hackathon_api_key = hackathon_api_key
        self.hackathon_realm_id = hackathon_realm_id
        self.session: Optional[aiohttp.ClientSession] = None
        self._initialized = False

    def create_table(self):
        """Create the Player table if it doesn't exist."""
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS Player (
                username TEXT PRIMARY KEY,
                stam INTEGER DEFAULT 0
            )
        ''')
        self.conn.commit()

    async def initialize(self) -> None:
        """Initialize the points manager."""
        if not self._initialized:
            self.session = aiohttp.ClientSession()
            self._initialized = True
            logger.info("Points manager initialized")

    async def cleanup(self) -> None:
        """Cleanup resources."""
        if self.session:
            await self.session.close()
            self.session = None
        self._initialized = False
        logger.info("Points manager cleaned up")

    async def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def get_all_balances(self, user_id: int) -> int:
        """Get the point balances for each external point system for this user."""
        if not self.session:
            await self.initialize()

        try:
            async with self.session.get(
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
                    raise print(f"Failed to get balance: {error_data}")
        except Exception as e:
            logger.error(f"Error getting balance for user {user_id}: {str(e)}")
            raise print(f"Failed to get balance: {str(e)}")

    async def add_points(
        self,
        user_id: int,
        amount: int,
        description: str = ""
    ) -> bool:
        """Add points to a user's balance."""
        if not self.session:
            await self.initialize()

        try:
            async with self.session.patch(
                f"{self.base_url}/api/v4/realms/{self.realm_id}/members/{user_id}/tokenBalance",
                headers=await self._get_headers(),
                json={"tokens": amount}
            ) as response:
                if response.status == 200:
                    # Update local account
                    account = self._get_account(user_id)
                    account.add_transaction(amount, description)
                    return True
                else:
                    error_data = await response.json()
                    raise print(f"Failed to add points: {error_data}")
        except Exception as e:
            logger.error(f"Error adding points for user {user_id}: {str(e)}")
            raise print(f"Failed to add points: {str(e)}")

    async def remove_points(
        self,
        user_id: int,
        amount: int,
        description: str = ""
    ) -> bool:
        """Remove points from a user's balance."""
        return await self.add_points(user_id, -amount, description)

    async def transfer_points(
        self,
        from_user_id: int,
        to_user_id: int,
        amount: int,
        description: str = ""
    ) -> bool:
        """Transfer points between users."""
        if not self.session:
            await self.initialize()

        try:
            async with self.session.patch(
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
                    raise print(f"Failed to transfer points: {error_data}")
        except Exception as e:
            logger.error(
                f"Error transferring points from {from_user_id} to {to_user_id}: {str(e)}"
            )
            raise print(f"Failed to transfer points: {str(e)}")

    async def get_top_balances(self, limit: int = 10) -> List[tuple[int, int]]:
        """Get top point balances.
        
        Args:
            limit: Maximum number of results to return
            
        Returns:
            List of (user_id, balance) tuples
        """
        if not self.session:
            await self.initialize()

        try:
            async with self.session.get(
                f"{self.base_url}/api/v4/realms/{self.realm_id}/leaderboard",
                headers=await self._get_headers(),
                params={"limit": limit}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return [(entry['userId'], entry['balance']) for entry in data]
                else:
                    error_data = await response.json()
                    raise print(f"Failed to get leaderboard: {error_data}")
        except Exception as e:
            logger.error(f"Error getting top balances: {str(e)}")
            raise print(f"Failed to get leaderboard: {str(e)}")
