"""Transfer service interface definitions."""
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class TransferResult:
    """Result of a transfer operation."""
    success: bool
    message: str
    initial_external_balance: int = 0
    initial_local_balance: int = 0
    final_external_balance: int = 0
    final_local_balance: int = 0

class ExternalEconomyInterface(ABC):
    """Abstract interface for external economies."""
    
    @abstractmethod
    async def get_balance(self, user_id: int) -> int:
        """Get balance for a user."""
        pass
        
    @abstractmethod
    async def add_points(self, user_id: int, amount: int) -> bool:
        """Add points to a user's balance."""
        pass
        
    @abstractmethod
    async def remove_points(self, user_id: int, amount: int) -> bool:
        """Remove points from a user's balance."""
        pass

    @property
    @abstractmethod
    def economy_name(self) -> str:
        """Get the name of this economy."""
        pass