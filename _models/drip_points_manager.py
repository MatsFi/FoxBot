"""Points system models for managing user points and transactions."""
import aiohttp
import sqlite3
from typing import Optional, Dict, List
import datetime
from dataclasses import dataclass

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
    
class PointsManagerSingleton:
    _instance = None
    _initialized = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, base_url: str, api_key: str, realm_id: str, hackathon_api_key: str, hackathon_realm_id: str, db_path: str):
#    def __init__(self, base_url: str = None, api_key: str = None, realm_id: str = None):
        self.conn = sqlite3.connect(db_path)
        self.create_table()
        self._accounts: Dict[str, PointsAccount] = {}

        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.realm_id = realm_id
        self.hackathon_api_key = hackathon_api_key
        self.hackathon_realm_id = hackathon_realm_id
        self.session: Optional[aiohttp.ClientSession] = None
        self._accounts: Dict[int, PointsAccount] = {}
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

    async def initialize(self):
        """Initialize the aiohttp session if it doesn't exist."""
        if not self.session:
            self.session = aiohttp.ClientSession()

    async def cleanup(self):
        """Cleanup the aiohttp session."""
        if self.session:
            await self.session.close()
            self.session = None

    async def _get_headers(self) -> dict:
        """Get headers with API key authentication."""
        return {"Authorization": f"Bearer {self.api_key}"}

    async def get_balance(self, user_id: int) -> int:
        """Get the point balance for a user."""
        if not self.session:
            await self.initialize()
            
        headers = await self._get_headers()
        
        async with self.session.get(
            f"{self.base_url}/api/v4/realms/{self.realm_id}/members/{user_id}",
            headers=headers
        ) as response:
            if response.status == 200:
                data = await response.json()
                if not data.get('balances'):
                    return 0
                realm_point_ids = list(data['balances'].keys())
                return data['balances'].get(realm_point_ids[0], 0)
            else:
                error_data = await response.json()
                raise Exception(f"Failed to get balance: {error_data}")

    async def add_points(self, user_id: int, amount: int) -> bool:
        """Add points to a user's balance."""
        if not self.session:
            await self.initialize()
            
        headers = await self._get_headers()
        
        async with self.session.patch(
            f"{self.base_url}/api/v4/realms/{self.realm_id}/members/{user_id}/tokenBalance",
            headers=headers,
            json={"tokens": amount}
        ) as response:
            return response.status == 200

    async def remove_points(self, user_id: int, amount: int) -> bool:
        """Remove points from a user's balance."""
        return await self.add_points(user_id, -amount)

    async def transfer_points(self, from_user_id: int, to_user_id: int, amount: int) -> bool:
        """Transfer points from one user to another."""
        if not self.session:
            await self.initialize()
            
        headers = await self._get_headers()
        
        async with self.session.patch(
            f"{self.base_url}/api/v4/realms/{self.realm_id}/members/{from_user_id}/transfer",
            headers=headers,
            json={
                "recipientId": to_user_id,
                "tokens": amount
            }
        ) as response:
            return response.status == 200