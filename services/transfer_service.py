from typing import Optional, Tuple
from database.models import Player, Transaction
from datetime import datetime
from services.local_points_service import LocalPointsService
from services.hackathon_points_service import HackathonPointsManager
import logging

logger = logging.getLogger(__name__)

class CrossEconomyTransferService:
    """Service for handling transfers between Hackathon and Local economies."""
    
    def __init__(self, local_service: LocalPointsService, hackathon_service: HackathonPointsManager):
        self.local_service = local_service
        self.hackathon_service = hackathon_service
        self.logger = logging.getLogger(__name__)

    @classmethod
    def from_bot(cls, bot):
        """Create service instance from bot instance."""
        local_service = LocalPointsService.from_bot(bot)
        hackathon_service = HackathonPointsManager.from_bot(bot)
        return cls(local_service, hackathon_service)

    async def deposit_to_local(self, discord_id: str, amount: int, username: str) -> Tuple[bool, str]:
        """Transfer points from Hackathon to Local economy."""
        try:
            # Log the start of transaction
            print(f"Starting deposit to local: {discord_id}, amount: {amount}")
            self.logger.info(f"Starting deposit to local: {discord_id}, amount: {amount}")
            
            # Verify Hackathon balance
            hackathon_balance = await self.hackathon_service.get_balance(discord_id)
            self.logger.info(f"Current hackathon balance: {hackathon_balance}")
            
            if hackathon_balance < amount:
                return False, f"Insufficient Hackathon balance. You have {hackathon_balance:,} points."

            # Start with Local economy credit first
            # Get current local balance for logging
            current_local = await self.local_service.get_balance(discord_id, username)
            self.logger.info(f"Current local balance before deposit: {current_local}")

            # Add to Local economy
            local_success = await self.local_service.add_points(
                discord_id,
                amount,
                f"Deposit from Hackathon economy (ID: {discord_id})",
                username
            )
            
            if not local_success:
                print("Failed to credit Local economy")
                self.logger.error("Failed to credit Local economy")
                return False, "Failed to credit Local economy"

            # Verify Local credit worked
            new_local = await self.local_service.get_balance(discord_id, username)
            print(f"New local balance after deposit: {new_local}")
            self.logger.info(f"New local balance after deposit: {new_local}")
            print(f"Current local balance: {current_local}")
            print(f"Amount: {amount}")
            
            if new_local != current_local + amount:
                self.logger.error(f"Local balance mismatch: {new_local} != {current_local + amount}")
                print("Local balance mismatch {new_local} != {current_local} + {amount}")
                # Attempt to rollback local change
                await self.local_service.add_points(
                    discord_id,
                    -amount,
                    "Rollback failed deposit",
                    username
                )
                return False, "Local economy credit verification failed"

            test_local = await self.local_service.get_balance(discord_id, username)
            print(f"Test local balance after rollback: {test_local}")

            # Now deduct from Hackathon economy
            hackathon_success = await self.hackathon_service.remove_points(
                discord_id,
                amount,
            )
            remove_local = await self.local_service.get_balance(discord_id, username)
            print(f"Test local balance after remove_points: {remove_local}")
            
            if not hackathon_success:
                print("Failed to debit Hackathon economy")
                self.logger.error("Failed to debit Hackathon economy")
                # Rollback Local credit
                await self.local_service.add_points(
                    discord_id,
                    -amount,
                    "Rollback due to Hackathon debit failure",
                    username
                )
                return False, "Failed to debit Hackathon economy. Transaction rolled back."

            # Final verification
            final_hackathon = await self.hackathon_service.get_balance(discord_id)
            final_local = await self.local_service.get_balance(discord_id, username)
            print(f"Final Hackathon balance: {final_hackathon}")
            print(f"Final Local balance: {final_local}")
            
            self.logger.info(
                f"Transfer complete - Hackathon: {final_hackathon}, Local: {final_local}"
            )
            
            return True, "Transfer successful"

        except Exception as e:
            self.logger.error(f"Error during deposit: {str(e)}", exc_info=True)
            return False, f"Error during transfer to Local from Hackathon: {str(e)}"


    async def withdraw_to_hackathon(self, discord_id: str, amount: int, username: str) -> tuple[bool, str]:
        """
        Transfer points from Local to Hackathon economy.
        
        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            # First check Local balance
            local_balance = await self.local_service.get_balance(discord_id, username)
            if local_balance < amount:
                return False, f"Insufficient Local balance. You have {local_balance:,} points."

            # First add to Hackathon economy using the tokenBalance API
            # We do this first because it's harder to rollback the external API
            success = await self.hackathon_service.add_points(
                discord_id,
                amount,
                "Transfer from Local economy"
            )
            
            if not success:
                return False, "Failed to add points to Hackathon economy."

            # Then remove points from Local economy
            local_success = await self.local_service.add_points(
                discord_id,
                -amount,  # Negative amount for removal
                "Transfer to Hackathon economy",
                username
            )
            
            if not local_success:
                # Rollback Hackathon addition
                rollback_success = await self.hackathon_service.remove_points(
                    discord_id,
                    amount,
                )
                if not rollback_success:
                    # This is a critical error - points were added to Hackathon but not removed from Local
                    # Log this for manual intervention
                    self.logger.critical(
                        f"CRITICAL: Failed to rollback Hackathon points after Local withdrawal "
                        f"failed. User: {discord_id}, Amount: {amount}. Manual intervention required."
                    )
                    return False, "Critical error during withdrawal. Please contact an administrator."
                return False, "Failed to deduct points from Local economy. Transaction rolled back."

            # Verify final balances
            final_local = await self.local_service.get_balance(discord_id, username)
            final_hackathon = await self.hackathon_service.get_balance(discord_id)
            
            if final_local != local_balance - amount:
                self.logger.error(
                    f"Local balance verification failed. Expected: {local_balance - amount}, "
                    f"Got: {final_local}"
                )
                return False, "Balance verification failed. Please check your balances."

            return True, "Transfer successful"

        except Exception as e:
            self.logger.error(f"Error during withdrawal: {str(e)}", exc_info=True)
            return False, f"Error during transfer: {str(e)}"
