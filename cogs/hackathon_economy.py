"""Hackathon economy cog implementation."""
import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone
from services import HackathonPointsManager, HackathonServiceAdapter
from utils.decorators import is_admin
from .economy_cog_template import ExternalEconomyCog
from database.models import utc_now, ensure_utc

class HackathonEconomy(ExternalEconomyCog):
    """Handles Hackathon economy operations."""
    
    def __init__(self, bot):
        super().__init__(
            bot,
            HackathonPointsManager,
            HackathonServiceAdapter,
            "Hackathon"
        )

    @commands.hybrid_command(
        name="hackathon_deposit",
        description="Deposit Hackathon points into your Local account"
    )
    @app_commands.describe(
        amount="Amount of points to transfer"
    )
    async def deposit(self, ctx: commands.Context, amount: int) -> None:
        """Deposit Hackathon points into your Local account."""
        await self.process_deposit(ctx, amount)

    @commands.hybrid_command(
        name="hackathon_withdraw",
        description="Withdraw points from your Local account to Hackathon"
    )
    @app_commands.describe(
        amount="Amount of points to withdraw"
    )
    async def withdraw(self, ctx: commands.Context, amount: int) -> None:
        """Withdraw points from Local account to Hackathon economy."""
        await self.process_withdraw(ctx, amount)

    @app_commands.guild_only()
    @app_commands.command(name="hackathon_balance", description="Check your Points balance")
    async def check_balance(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        try:
            balance = await self.points_service.get_balance(interaction.user.id)
            embed = discord.Embed(
                title="Hackathon Points Balance",
                color=discord.Color.blue(),
                timestamp=utc_now()  # Use UTC for embed timestamp
            )
            embed.add_field(name="Balance", value=f"{balance:,} Points")
            embed.set_footer(text=f"Requested by {interaction.user.display_name}")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error checking balance: {str(e)}", ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="hackathon_add_points", description="[Admin] Add Points to a user")
    @app_commands.describe(
        user="The user to receive Points",
        amount="Amount of Points to add"
    )
    @is_admin()
    async def add_points(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        await interaction.response.defer(ephemeral=True)
        
        if amount <= 0:
            await interaction.followup.send("Amount must be positive!", ephemeral=True)
            return

        if user.bot:
            await interaction.followup.send("Can't add Points to bots!", ephemeral=True)
            return
        
        try:
            success = await self.points_service.add_points(user.id, amount)
            
            if success:
                new_balance = await self.points_service.get_balance(user.id)
                await interaction.followup.send(
                    f"Successfully added {amount:,} Points to {user.mention}!\n"
                    f"Their new balance: {new_balance:,} Points",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Failed to add Points. Please try again later.",
                    ephemeral=True
                )
        except Exception as e:
            await interaction.followup.send(f"Error adding Points: {str(e)}", ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="hackathon_remove_points", description="[Admin] Remove Points from a user")
    @app_commands.describe(
        user="The user to remove Points from",
        amount="Amount of Points to remove"
    )
    @is_admin()
    async def remove_points(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        await interaction.response.defer(ephemeral=True)
        
        if amount <= 0:
            await interaction.followup.send("Amount must be positive!", ephemeral=True)
            return

        if user.bot:
            await interaction.followup.send("Can't remove Points from bots!", ephemeral=True)
            return
        
        try:
            current_balance = await self.points_service.get_balance(user.id)
            if current_balance < amount:
                await interaction.followup.send(
                    f"User only has {current_balance:,} Points! Cannot remove {amount:,} Points.",
                    ephemeral=True
                )
                return

            success = await self.points_service.remove_points(user.id, amount)
            
            if success:
                new_balance = await self.points_service.get_balance(user.id)
                await interaction.followup.send(
                    f"Successfully removed {amount:,} Points from {user.mention}!\n"
                    f"Their new balance: {new_balance:,} Points",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Failed to remove Points. Please try again later.",
                    ephemeral=True
                )
        except Exception as e:
            await interaction.followup.send(f"Error removing Points: {str(e)}", ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="hackathon_check", description="Check another user's Points balance")
    @app_commands.describe(user="The user to check")
    async def check_other(self, interaction: discord.Interaction, user: discord.Member):
        await interaction.response.defer(ephemeral=True)
        
        if user.bot:
            await interaction.followup.send("Bots don't have Points!", ephemeral=True)
            return
        
        try:
            balance = await self.points_service.get_balance(user.id)
            await interaction.followup.send(
                f"{user.mention}'s balance: {balance:,} Points",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"Error checking balance: {str(e)}", ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="hackathon_leaderboard", description="Show the points leaderboard")
    async def leaderboard(self, interaction: discord.Interaction):
        try:
            members = []
            for member in interaction.guild.members:
                if not member.bot:
                    balance = await self.points_service.get_balance(member.id)
                    if balance > 0:
                        members.append((member, balance))

            members.sort(key=lambda x: x[1], reverse=True)

            embed = discord.Embed(
                title="🏆 Hackathon Points Leaderboard",
                color=discord.Color.gold(),
                timestamp=utc_now()  # Use UTC for embed timestamp
            )

            medals = {0: "🥇", 1: "🥈", 2: "🥉"}
            leaderboard_text = []
            for idx, (member, balance) in enumerate(members[:10]):
                prefix = medals.get(idx, f"`#{idx+1}`")
                leaderboard_text.append(
                    f"{prefix} {member.mention}: **{balance:,}** points"
                )

            if leaderboard_text:
                embed.description = "\n".join(leaderboard_text)
            else:
                embed.description = "No points recorded yet!"

            embed.set_footer(text=f"Total Participants: {len(members)}")
            await interaction.response.send_message(embed=embed)

        except Exception as e:
            await interaction.response.send_message(
                f"Error fetching leaderboard: {str(e)}",
                ephemeral=True
            )

    @add_points.error
    @remove_points.error
    async def admin_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            await interaction.response.send_message(
                "You don't have permission to use this command!", 
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(HackathonEconomy(bot))