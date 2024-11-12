"""Service for managing Staminah game operations."""
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional
from sqlalchemy import select, desc
from database.models import GameState, Player, Miner
from services.staminah_types import MinerState
from services.staminah_constants import (
    INITIAL_BLOCK_REWARD,
    DECAY_RATE,
    MAX_CORN_SUPPLY,
    MINER_TYPES,
    DECAY_INTERVAL
)

logger = logging.getLogger(__name__)

class StaminahService:
    """Service for managing Staminah game operations."""
    
    def __init__(self, database):
        self.db = database
        self.miners: Dict[str, MinerState] = {}
        self.current_block = 1
        self.current_reward = INITIAL_BLOCK_REWARD
        self.total_corn_mined = 0
        self.total_work = 0
        self.last_blocks_work = []
        self.accumulated_reward = 0
        self.next_decay = datetime.now(timezone.utc) + DECAY_INTERVAL
        self.logger = logging.getLogger(__name__)

    @classmethod
    def from_bot(cls, bot):
        """Create a StaminahService instance from a bot instance."""
        return cls(bot.database)

    async def initialize(self) -> None:
        """Initialize game state from database."""
        async with self.db.session() as session:
            # Load game state
            state = await session.execute(
                select(GameState).order_by(desc(GameState.block_number)).limit(1)
            )
            state = state.scalar_one_or_none()
            
            if state:
                self.current_block = state.block_number
                self.current_reward = state.current_reward
                self.total_corn_mined = state.total_corn_mined
                self.total_work = state.total_work
                self.next_decay = state.next_decay
                self.accumulated_reward = state.accumulated_reward
            else:
                # Initialize new game state
                new_state = GameState(
                    block_number=1,
                    current_reward=INITIAL_BLOCK_REWARD,
                    total_corn_mined=0,
                    total_work=0,
                    next_decay=datetime.now(timezone.utc) + DECAY_INTERVAL,
                    accumulated_reward=0
                )
                session.add(new_state)
                await session.commit()

            # Load miners
            miners = await session.execute(select(Miner))
            for miner in miners.scalars():
                self.miners[miner.owner_id] = MinerState(
                    owner_id=miner.owner_id,
                    miner_type=miner.miner_type,
                    is_on=miner.is_on,
                    stam_balance=miner.stam_balance,
                    work=miner.work,
                    total_work=miner.total_work,
                    consumption_rate=miner.consumption_rate,
                    last_update=miner.last_update
                )

    async def update_miner_work(self) -> None:
        """Update work for all active miners."""
        now = datetime.now(timezone.utc)
        async with self.db.session() as session:
            for miner in self.miners.values():
                if miner.is_on and miner.stam_balance > 0:
                    time_diff = (now - miner.last_update).total_seconds() / 60  # minutes
                    stam_consumed = int(miner.consumption_rate * time_diff)
                    
                    if stam_consumed > miner.stam_balance:
                        stam_consumed = miner.stam_balance
                        miner.is_on = False
                    
                    efficiency = MINER_TYPES[miner.miner_type]["efficiency"]
                    work_produced = stam_consumed * efficiency
                    
                    miner.work += work_produced
                    miner.stam_balance -= stam_consumed
                    miner.last_update = now
                    
                    # Update database
                    db_miner = await session.get(Miner, miner.owner_id)
                    if db_miner:
                        db_miner.work = miner.work
                        db_miner.stam_balance = miner.stam_balance
                        db_miner.is_on = miner.is_on
                        db_miner.last_update = miner.last_update
            
            await session.commit()

    async def process_block(self) -> Optional[MinerState]:
        """Process the next block and distribute rewards."""
        if self.total_corn_mined >= MAX_CORN_SUPPLY:
            return None
            
        # Find miner with most work
        winner = None
        max_work = 0
        
        for miner in self.miners.values():
            if miner.work > max_work:
                max_work = miner.work
                winner = miner
                
        async with self.db.session() as session:
            now = datetime.now(timezone.utc)
            
            if winner and max_work > 0:
                total_reward = self.current_reward + self.accumulated_reward
                self.accumulated_reward = 0
                
                winner.total_work += winner.work
                winner.work = 0
                
                db_miner = await session.get(Miner, winner.owner_id)
                if db_miner:
                    db_miner.total_work = winner.total_work
                    db_miner.work = 0
                    
                db_player = await session.get(Player, winner.owner_id)
                if db_player:
                    db_player.corn_balance += total_reward
                    
                self.total_work += max_work
                self.total_corn_mined += total_reward
                self.last_blocks_work.append(max_work)
                if len(self.last_blocks_work) > 10:
                    self.last_blocks_work.pop(0)
            else:
                self.accumulated_reward += self.current_reward
                
            if now >= self.next_decay:
                self.current_reward *= DECAY_RATE
                self.next_decay = now + DECAY_INTERVAL
                
            new_state = GameState(
                block_number=self.current_block + 1,
                current_reward=self.current_reward,
                total_corn_mined=self.total_corn_mined,
                total_work=self.total_work,
                next_decay=self.next_decay,
                accumulated_reward=self.accumulated_reward,
                timestamp=now
            )
            session.add(new_state)
            await session.commit()
            
            self.current_block += 1
            return winner

    async def cleanup(self) -> None:
        """Cleanup resources."""
        self.logger.info("Staminah service cleaned up")