from typing import Optional
from discord import Interaction, Member, Role
from discord.ext import commands

class PredictionMarketPermissions:
    """Permission checks for prediction market commands."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config = bot.config.prediction_market

    async def can_create_prediction(self, interaction: Interaction) -> bool:
        """Check if user can create predictions."""
        if not interaction.guild:
            return False
            
        member = interaction.user
        if not isinstance(member, Member):
            return False

        # Admin override
        if member.guild_permissions.administrator:
            return True

        # Check creator role if configured
        if self.config.creator_role_id:
            role = interaction.guild.get_role(int(self.config.creator_role_id))
            return bool(role and role in member.roles)
            
        return True  # Anyone can create if no role configured

    async def can_resolve_prediction(
        self,
        interaction: Interaction,
        prediction_creator_id: str
    ) -> bool:
        """Check if user can resolve a specific prediction."""
        if not interaction.guild:
            return False
            
        member = interaction.user
        if not isinstance(member, Member):
            return False

        # Admin override
        if member.guild_permissions.administrator:
            return True

        # Creator can always resolve their own predictions
        return str(member.id) == prediction_creator_id

    async def can_bet(self, interaction: Interaction) -> bool:
        """Check if user can place bets."""
        if not interaction.guild:
            return False
            
        member = interaction.user
        if not isinstance(member, Member):
            return False

        # Add any specific betting restrictions here
        # For now, any guild member can bet
        return True

    async def can_view_predictions(self, interaction: Interaction) -> bool:
        """Check if user can view predictions."""
        if not interaction.guild:
            return False
            
        member = interaction.user
        if not isinstance(member, Member):
            return False

        # Add any specific viewing restrictions here
        # For now, any guild member can view
        return True 