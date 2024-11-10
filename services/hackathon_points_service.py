"""Points system for managing Hackathon economy points via API."""
import aiohttp
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)

class HackathonPointsManager:
    """Manages point operations and API interactions for Hackathon economy."""
    
    def __init__(self, api_config: dict):
        self.base_url = api_config['base_url'].rstrip('/')
        self.api_key = api_config['api_key']
        self.realm_id = api_config['realm_id']
        self._session = None
        self.logger = logging.getLogger(__name__)

    @classmethod
    def from_bot(cls, bot):
        """Create a HackathonPointsManager instance from a bot instance."""
        return cls(
            # game host's API config
            api_config={
                'base_url': bot.config.api_base_url,
                'api_key': bot.config.hackathon_api_key,
                'realm_id': bot.config.hackathon_realm_id
            }
        )

    async def initialize(self) -> None:
        """Initialize the points manager."""
        self._session = aiohttp.ClientSession()
        self.logger.info("Hackathon points manager initialized")

    async def cleanup(self) -> None:
        """Cleanup resources."""
        if self._session:
            await self._session.close()
            self._session = None
        self.logger.info("Hackathon points manager cleaned up")

    async def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def get_balance(self, user_id: int) -> int:
        """Get the point balance for a user from the Hackathon API."""
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
            self.logger.error(f"Error getting balance for user {user_id}: {str(e)}")
            raise PointsError(f"Failed to get balance: {str(e)}")

    async def add_points(self, user_id: int, amount: int) -> bool:
        """Add points to user's balance using the Hackathon API."""
        if not self._session:
            await self.initialize()

        try:
            async with self._session.patch(
                f"{self.base_url}/api/v4/realms/{self.realm_id}/members/{user_id}/tokenBalance",
                headers=await self._get_headers(),
                json={"tokens": amount}
            ) as response:
                if response.status == 200:
                    self.logger.info(f"Successfully added {amount} points to user {user_id}")
                    return True
                else:
                    error_data = await response.json()
                    self.logger.error(f"Failed to add points: {error_data}")
                    return False
        except Exception as e:
            self.logger.error(f"Error adding points for user {user_id}: {str(e)}")
            return False

    async def remove_points(self, user_id: int, amount: int) -> bool:
        """Remove points from user's balance using the Hackathon API."""
        return await self.add_points(user_id, -amount)

    async def transfer_points(self, from_user_id: int, to_user_id: int, amount: int) -> bool:
        """Transfer points between users using the Hackathon API."""
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
                    self.logger.info(
                        f"Successfully transferred {amount} points from {from_user_id} to {to_user_id}"
                    )
                    return True
                else:
                    error_data = await response.json()
                    self.logger.error(f"Failed to transfer points: {error_data}")
                    return False
        except Exception as e:
            self.logger.error(
                f"Error transferring points from {from_user_id} to {to_user_id}: {str(e)}"
            )
            return False

    async def get_top_balances(self, limit: int = 10) -> list[tuple[int, int]]:
        """Get top point balances from the Hackathon API."""
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
            self.logger.error(f"Error getting top balances: {str(e)}")
            raise PointsError(f"Failed to get leaderboard: {str(e)}")

class PointsError(Exception):
    """Custom exception for points-related errors."""
    pass