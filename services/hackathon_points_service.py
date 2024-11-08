"""Points system models for managing user points and transactions."""
import aiohttp
from typing import Optional, Dict, List
import datetime
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class Transaction:
    """Represents a point transaction."""
    timestamp: datetime.datetime
    user_id: int
    amount: int
    description: str
    balance_after: int
    transaction_id: str

    @property
    def is_debit(self) -> bool:
        """Whether this is a debit transaction."""
        return self.amount < 0

    @property
    def is_credit(self) -> bool:
        """Whether this is a credit transaction."""
        return self.amount > 0

class PointsAccount:
    """Represents a user's point account with transaction history."""
    
    def __init__(self, user_id: int, initial_balance: int = 0):
        self.user_id = user_id
        self.balance = initial_balance
        self.transactions: List[Transaction] = []
        self.last_updated = datetime.datetime.utcnow()

    def add_transaction(
        self,
        amount: int,
        description: str,
        transaction_id: Optional[str] = None
    ) -> Transaction:
        """Record a transaction in the account history."""
        self.balance += amount
        transaction = Transaction(
            timestamp=datetime.datetime.utcnow(),
            user_id=self.user_id,
            amount=amount,
            description=description,
            balance_after=self.balance,
            transaction_id=transaction_id or f"tx_{len(self.transactions)}"
        )
        self.transactions.append(transaction)
        self.last_updated = transaction.timestamp
        return transaction

    def get_transaction_history(
        self,
        limit: Optional[int] = None,
        since: Optional[datetime.datetime] = None
    ) -> List[Transaction]:
        """Get transaction history with optional filtering."""
        transactions = self.transactions
        
        if since:
            transactions = [t for t in transactions if t.timestamp >= since]
            
        if limit:
            transactions = transactions[-limit:]
            
        return transactions

    def get_balance_at(self, timestamp: datetime.datetime) -> int:
        """Get the balance at a specific point in time."""
        relevant_transactions = [
            t for t in self.transactions if t.timestamp <= timestamp
        ]
        if not relevant_transactions:
            return 0
        return relevant_transactions[-1].balance_after

class HackathonPointsManager:
    """Manages point operations and API interactions."""
    
    def __init__(self, database, api_config: dict):
        self.db = database
        self.base_url = api_config['base_url'].rstrip('/')
        self.api_key = api_config['api_key']
        self.realm_id = api_config['realm_id']
        self._session = None
        self._accounts: Dict[str, PointsAccount] = {}

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

    def _get_account(self, user_id: int) -> PointsAccount:
        """Get or create a points account for a user."""
        if user_id not in self._accounts:
            self._accounts[user_id] = PointsAccount(user_id)
        return self._accounts[user_id]

    async def sync_account(self, user_id: int) -> PointsAccount:
        """Sync account with API and return up-to-date account."""
        balance = await self.get_balance(user_id)
        account = self._get_account(user_id)
        
        # Only update if balance differs
        if account.balance != balance:
            account.add_transaction(
                amount=balance - account.balance,
                description="Account sync adjustment",
                transaction_id="sync_adjustment"
            )
            
        return account

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
                    account = self._get_account(user_id)
                    account.add_transaction(amount, description)
                    return True
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