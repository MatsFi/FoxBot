from discord import app_commands
import discord

def is_admin():
    """Check if user has administrator permissions."""
    def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.guild_permissions.administrator
    return app_commands.check(predicate)