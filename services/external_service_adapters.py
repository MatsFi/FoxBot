"""Adapters for external economy services to implement the ExternalEconomyInterface."""
from services.transfer_interface import ExternalEconomyInterface

class ExternalServiceAdapter(ExternalEconomyInterface):
    """Base adapter class for external economy services."""
    
    def __init__(self, service, economy_name: str):
        self._service = service
        self._economy_name = economy_name

    @property
    def economy_name(self) -> str:
        return self._economy_name

    async def get_balance(self, user_id: int) -> int:
        return await self._service.get_balance(user_id)

    async def add_points(self, user_id: int, amount: int) -> bool:
        return await self._service.add_points(user_id, amount)

    async def remove_points(self, user_id: int, amount: int) -> bool:
        return await self._service.remove_points(user_id, amount)

class HackathonServiceAdapter(ExternalServiceAdapter):
    """Adapter for Hackathon economy service."""
    
    def __init__(self, hackathon_service):
        super().__init__(hackathon_service, "Hackathon")

class FFSServiceAdapter(ExternalServiceAdapter):
    """Adapter for FFS economy service."""
    
    def __init__(self, ffs_service):
        super().__init__(ffs_service, "FFS")