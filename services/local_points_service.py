"""Service for managing Local economy points."""
import logging
from datetime import datetime
from sqlalchemy import select, func
from typing import List, Optional, Tuple
from database.models import Player, Transaction

logger = logging.getLogger(__name__)

class LocalPointsService:
    """Service for managing Local economy points."""
    
    def __init__(self, database):
        self.db = database
        self.logger = logging.getLogger(__name__)
        
        # Initialize user lists for different economies
        self.ffs_users = set()
        self.hackathon_users = set()
    
    @classmethod
    def from_bot(cls, bot):
        """Create service instance from bot instance."""
        return cls(bot.database)
    
    async def initialize(self) -> None:
        """Initialize the service."""
        try:
            await self._load_economy_users()
            self.logger.info("LocalPointsService initialized successfully")
        except Exception as e:
            self.logger.error(f"Error initializing LocalPointsService: {e}")
            raise
    
    async def _load_economy_users(self):
        """Load users with access to different economies."""
        try:
            # TODO: Load these from config or database
            # For now, using test data
            self.ffs_users = {
                # Add FFS user IDs here
            }
            self.hackathon_users = {
                # Add Hackathon user IDs here
            }
            self.logger.info("Economy users loaded successfully")
        except Exception as e:
            self.logger.error(f"Error loading economy users: {e}")
            raise
    
    def has_ffs_access(self, user_id: int) -> bool:
        """Check if user has access to FFS economy."""
        return True
    
    def has_hackathon_access(self, user_id: int) -> bool:
        """Check if user has access to Hackathon economy."""
        return True
    
    async def cleanup(self):
        """Cleanup any resources."""
        self.logger.info("LocalPointsService cleanup completed")