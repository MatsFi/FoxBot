"""Service for handling transfers between External and Local economies."""
import logging
from typing import Dict
from services.transfer_interface import ExternalEconomyInterface, TransferResult

logger = logging.getLogger(__name__)

class CrossEconomyTransferService:
    """Service for handling transfers between External and Local economies."""
    
    def __init__(self, local_service):
        """Initialize with local economy service."""
        self.local_service = local_service
        self._external_services: Dict[str, ExternalEconomyInterface] = {}
        self.logger = logging.getLogger(__name__)

    def register_external_service(self, service: ExternalEconomyInterface) -> None:
        """Register an external economy service.
        
        Args:
            service (ExternalEconomyInterface): The external service to register
        """
        self.logger.info(f"Registering external service: {service.economy_name}")
        self._external_services[service.economy_name] = service

    def get_external_service(self, economy_name: str) -> ExternalEconomyInterface:
        """Get an external service by name.
        
        Args:
            economy_name (str): Name of the economy to retrieve
            
        Returns:
            ExternalEconomyInterface: The requested service
            
        Raises:
            ValueError: If no service is registered for the given economy name
        """
        service = self._external_services.get(economy_name)
        if not service:
            raise ValueError(f"No external service registered for economy: {economy_name}")
        return service

    async def deposit_to_local(
        self,
        economy_name: str,
        discord_id: str,
        amount: int,
        username: str
    ) -> TransferResult:
        """Transfer points from any external economy to local."""
        try:
            external_service = self.get_external_service(economy_name)
            
            # Log the start of transaction
            self.logger.info(
                f"Starting deposit to local from {economy_name}: {discord_id}, amount: {amount}"
            )
            
            # Only check external balance since we're moving FROM external TO local
            initial_external = await external_service.get_balance(int(discord_id))
            
            self.logger.info(
                f"Current external balance in {economy_name}: {initial_external}"
            )
            
            # Verify external balance
            if initial_external < amount:
                return TransferResult(
                    success=False,
                    message=f"Insufficient {economy_name} balance. You have {initial_external:,} points.",
                    initial_external_balance=initial_external
                )

            # Add transaction to Local economy first
            local_success = await self.local_service.add_transaction(
                user_id=username,  # This will be the prediction market account
                amount=amount,
                from_id=f"{economy_name}_{discord_id}",  # Source of funds
                to_id=username  # Destination (prediction market account)
            )
            
            if not local_success:
                return TransferResult(
                    success=False,
                    message="Failed to credit Local economy"
                )

            # Remove from external economy
            external_success = await external_service.remove_points(int(discord_id), amount)
            if not external_success:
                # Rollback Local credit by adding a negative transaction
                await self.local_service.add_transaction(
                    user_id=username,
                    amount=-amount,
                    from_id=username,
                    to_id=f"{economy_name}_{discord_id}"
                )
                return TransferResult(
                    success=False,
                    message=f"Failed to debit {economy_name} economy. Transaction rolled back.",
                    initial_external_balance=initial_external
                )

            # Get final external balance for verification
            final_external = await external_service.get_balance(int(discord_id))
            
            return TransferResult(
                success=True,
                message="Transfer successful",
                initial_external_balance=initial_external,
                final_external_balance=final_external
            )

        except Exception as e:
            self.logger.error(f"Error during deposit: {str(e)}", exc_info=True)
            return TransferResult(
                success=False,
                message=f"Error during transfer to Local from {economy_name}: {str(e)}"
            )

    async def withdraw_to_external(
        self,
        economy_name: str,
        discord_id: str,
        amount: int,
        username: str
    ) -> TransferResult:
        """Transfer points from local to any external economy.
        
        Args:
            economy_name (str): Name of the destination economy
            discord_id (str): User's Discord ID
            amount (int): Amount to transfer
            username (str): User's Discord username
            
        Returns:
            TransferResult: Result of the transfer operation
        """
        try:
            external_service = self.get_external_service(economy_name)
            
            # Get initial balances
            initial_local = await self.local_service.get_balance(discord_id, username)
            initial_external = await external_service.get_balance(int(discord_id))
            
            if initial_local < amount:
                return TransferResult(
                    success=False,
                    message=f"Insufficient Local balance. You have {initial_local:,} points.",
                    initial_external_balance=initial_external,
                    initial_local_balance=initial_local
                )

            # Add to external economy first since it's harder to rollback
            external_success = await external_service.add_points(int(discord_id), amount)
            if not external_success:
                return TransferResult(
                    success=False,
                    message=f"Failed to add points to {economy_name} economy.",
                    initial_external_balance=initial_external,
                    initial_local_balance=initial_local
                )

            # Remove from Local economy
            local_success = await self.local_service.add_points(
                discord_id,
                -amount,
                f"Transfer to {economy_name} economy",
                username
            )
            
            if not local_success:
                # Rollback external addition
                rollback_success = await external_service.remove_points(int(discord_id), amount)
                if not rollback_success:
                    self.logger.critical(
                        f"CRITICAL: Failed to rollback {economy_name} points after Local withdrawal "
                        f"failed. User: {discord_id}, Amount: {amount}. Manual intervention required."
                    )
                    return TransferResult(
                        success=False,
                        message="Critical error during withdrawal. Please contact an administrator.",
                        initial_external_balance=initial_external,
                        initial_local_balance=initial_local
                    )
                return TransferResult(
                    success=False,
                    message="Failed to deduct points from Local economy. Transaction rolled back.",
                    initial_external_balance=initial_external,
                    initial_local_balance=initial_local
                )

            # Final verification
            final_local = await self.local_service.get_balance(discord_id, username)
            final_external = await external_service.get_balance(int(discord_id))

            return TransferResult(
                success=True,
                message="Transfer successful",
                initial_external_balance=initial_external,
                initial_local_balance=initial_local,
                final_external_balance=final_external,
                final_local_balance=final_local
            )

        except Exception as e:
            self.logger.error(f"Error during withdrawal: {str(e)}", exc_info=True)
            return TransferResult(
                success=False,
                message=f"Error during transfer: {str(e)}"
            )