"""Service for handling mixer/lottery operations."""
import logging
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, NamedTuple
from sqlalchemy import select, func, desc
from database.mixer_models import MixerDraw, MixerTicket, MixerPotEntry
from services.transfer_interface import ExternalEconomyInterface

logger = logging.getLogger(__name__)

class DrawingSummary(NamedTuple):
    """Summary of a drawing's results."""
    draw_id: int
    draw_time: datetime
    total_players: int
    top_awards: List[Tuple[str, str, str, int]]  # [(username, discord_id, token_type, amount)]
    total_tokens: Dict[str, int]  # {token_type: total_amount}

class MixerService:
    """Service for managing mixer/lottery operations."""
    
    def __init__(self, database, external_services: Dict[str, ExternalEconomyInterface]):
        self.db = database
        self.external_services = external_services
        self.logger = logging.getLogger(__name__)

    async def get_active_draw(self) -> Optional[MixerDraw]:
        """Get the currently active draw if one exists."""
        async with self.db.session() as session:
            query = select(MixerDraw).where(
                MixerDraw.is_completed == False,
                MixerDraw.draw_time > datetime.utcnow()
            )
            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def initialize_draw(self, duration_minutes: int) -> Tuple[bool, str]:
        """Initialize a new draw."""
        if duration_minutes > 5:
            return False, "Maximum duration is 5 minutes"
            
        active_draw = await self.get_active_draw()
        if active_draw:
            return False, "A draw is already active"
            
        draw_time = datetime.utcnow() + timedelta(minutes=duration_minutes)
        
        async with self.db.session() as session:
            new_draw = MixerDraw(draw_time=draw_time)
            session.add(new_draw)
            await session.commit()
            
        return True, f"Draw initialized, ending at {draw_time.strftime('%H:%M:%S')}"

    async def add_to_pot(
            self,
            draw_id: int,
            discord_id: str,
            username: str,
            token_type: str,
            amount: int,
            is_donation: bool
        ) -> Tuple[bool, str]:
            """Add tokens to the pot."""
            if token_type not in self.external_services:
                return False, f"Unknown token type: {token_type}"
                
            service = self.external_services[token_type]
            
            # Verify user has enough balance
            balance = await service.get_balance(int(discord_id))
            if balance < amount:
                return False, f"Insufficient {token_type} balance: {balance}"
                
            # Remove tokens from user's external balance
            success = await service.remove_points(int(discord_id), amount)
            if not success:
                return False, f"Failed to remove tokens from {token_type} balance"
                
            try:
                async with self.db.session() as session:
                    # Add pot entry
                    pot_entry = MixerPotEntry(
                        draw_id=draw_id,
                        discord_id=discord_id,
                        username=username,
                        token_type=token_type,
                        amount=amount,
                        is_donation=is_donation
                    )
                    session.add(pot_entry)
                    
                    # Add tickets (one per token) if not a donation
                    if not is_donation:
                        tickets = []
                        for _ in range(amount):  # Create one ticket per token
                            ticket = MixerTicket(
                                draw_id=draw_id,
                                discord_id=discord_id,
                                username=username
                            )
                            tickets.append(ticket)
                        session.add_all(tickets)
                    
                    await session.commit()
                    
                return True, f"Successfully added {amount} {token_type} tokens to the pot" + \
                    (f" and issued {amount} tickets" if not is_donation else "")
                
            except Exception as e:
                self.logger.error(f"Error adding to pot: {e}")
                # Attempt to return tokens to user
                await service.add_points(int(discord_id), amount)
                return False, f"Error adding to pot: {str(e)}"

    async def get_draw_status(self, draw_id: int, user_discord_id: str) -> Dict:
        """Get the current status of a draw."""
        async with self.db.session() as session:
            draw = await session.get(MixerDraw, draw_id)
            if not draw:
                return {"error": "Draw not found"}
                
            # Get pot totals by token type
            pot_query = select(
                MixerPotEntry.token_type,
                func.sum(MixerPotEntry.amount)
            ).where(
                MixerPotEntry.draw_id == draw_id
            ).group_by(MixerPotEntry.token_type)
            
            pot_result = await session.execute(pot_query)
            pot_totals = {token: amount for token, amount in pot_result}
            
            # Get total tickets
            total_tickets = await session.scalar(
                select(func.count()).select_from(MixerTicket).where(
                    MixerTicket.draw_id == draw_id
                )
            )
            
            # Get user's tickets
            user_tickets = await session.scalar(
                select(func.count()).select_from(MixerTicket).where(
                    MixerTicket.draw_id == draw_id,
                    MixerTicket.discord_id == user_discord_id
                )
            )
            
            return {
                "pot_totals": pot_totals,
                "total_tickets": total_tickets or 0,
                "user_tickets": user_tickets or 0,
                "user_ratio": user_tickets / total_tickets if total_tickets else 0,
                "draw_time": draw.draw_time,
                "time_remaining": (draw.draw_time - datetime.utcnow()).total_seconds()
            }

    async def get_drawing_results(self, draw_id: int) -> Optional[DrawingSummary]:
        """Get detailed results for a specific drawing."""
        async with self.db.session() as session:
            # Get the draw
            draw = await session.get(MixerDraw, draw_id)
            if not draw or not draw.is_completed:
                return None

            # Get all pot entries for this draw
            query = select(MixerPotEntry).where(
                MixerPotEntry.draw_id == draw_id
            )
            result = await session.execute(query)
            entries = result.scalars().all()

            # Calculate unique players
            unique_players = len(set(entry.discord_id for entry in entries))

            # Calculate total tokens by type
            token_totals = {}
            for entry in entries:
                token_totals[entry.token_type] = token_totals.get(entry.token_type, 0) + entry.amount

            # Get top 3 awards
            top_awards = []
            for token_type in token_totals.keys():
                query = select(
                    MixerPotEntry.username,
                    MixerPotEntry.discord_id,
                    MixerPotEntry.token_type,
                    func.sum(MixerPotEntry.amount).label('total_amount')
                ).where(
                    MixerPotEntry.draw_id == draw_id,
                    MixerPotEntry.token_type == token_type
                ).group_by(
                    MixerPotEntry.discord_id,
                    MixerPotEntry.username,
                    MixerPotEntry.token_type
                ).order_by(desc('total_amount'))

                result = await session.execute(query)
                awards = result.fetchall()
                top_awards.extend(awards[:3])

            # Sort overall top awards by amount
            top_awards.sort(key=lambda x: x[3], reverse=True)

            return DrawingSummary(
                draw_id=draw_id,
                draw_time=draw.draw_time,
                total_players=unique_players,
                top_awards=top_awards[:3],
                total_tokens=token_totals
            )

    async def get_recent_drawings(self, limit: int = 5) -> List[Tuple[int, datetime, bool]]:
        """Get recent drawings."""
        async with self.db.session() as session:
            query = select(
                MixerDraw.id,
                MixerDraw.draw_time,
                MixerDraw.is_completed
            ).order_by(
                desc(MixerDraw.draw_time)
            ).limit(limit)
            
            result = await session.execute(query)
            return result.fetchall()

    async def process_draw(self, draw_id: int) -> Tuple[bool, str, Optional[DrawingSummary]]:
        """Process a completed draw and distribute tokens."""
        async with self.db.session() as session:
            # Get draw and verify it's ready
            draw = await session.get(MixerDraw, draw_id)
            if not draw or draw.is_completed:
                return False, "Invalid or already completed draw", None
                
            if draw.draw_time > datetime.utcnow():
                return False, "Draw time has not been reached", None
                
            # Get all tickets in order
            tickets_query = select(MixerTicket).where(
                MixerTicket.draw_id == draw_id
            ).order_by(MixerTicket.created_at)
            
            tickets_result = await session.execute(tickets_query)
            tickets = tickets_result.scalars().all()
            
            if not tickets:
                return False, "No tickets in draw", None
                
            # Get pot totals by token type
            pot_query = select(
                MixerPotEntry.token_type,
                func.sum(MixerPotEntry.amount)
            ).where(
                MixerPotEntry.draw_id == draw_id
            ).group_by(MixerPotEntry.token_type)
            
            pot_result = await session.execute(pot_query)
            pot_totals = {token: int(amount) for token, amount in pot_result}
            
            # Calculate base distribution and remainders
            distribution = {}
            for token_type, total_amount in pot_totals.items():
                base_amount = total_amount // len(tickets)
                remainder = total_amount % len(tickets)
                
                # Randomly assign remainders
                lucky_tickets = random.sample(tickets, remainder)
                
                for ticket in tickets:
                    if ticket.discord_id not in distribution:
                        distribution[ticket.discord_id] = {}
                    
                    amount = base_amount
                    if ticket in lucky_tickets:
                        amount += 1
                        
                    if amount > 0:
                        if token_type not in distribution[ticket.discord_id]:
                            distribution[ticket.discord_id][token_type] = 0
                        distribution[ticket.discord_id][token_type] += amount
            
            # Distribute tokens
            for discord_id, token_amounts in distribution.items():
                for token_type, amount in token_amounts.items():
                    service = self.external_services[token_type]
                    success = await service.add_points(int(discord_id), amount)
                    if not success:
                        self.logger.error(
                            f"Failed to distribute {amount} {token_type} tokens to {discord_id}"
                        )
            
            # Mark draw as completed
            draw.is_completed = True
            await session.commit()
            
            # Get and return results
            results = await self.get_drawing_results(draw_id)
            return True, "Draw completed and tokens distributed", results