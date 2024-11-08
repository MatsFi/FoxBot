import discord
from discord.ext import commands
from discord import app_commands
from services.points_service import PointsService
from utils.decorators import is_admin

class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Get the points service from the bot instance
        self.points_service = bot.points_service

    @app_commands.command(name="balance")
    async def check_balance(self, interaction: discord.Interaction):
        """Check your points balance."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            balance = await self.points_service.get_balance(str(interaction.user.id))
            await interaction.followup.send(
                f"Your balance: {balance:,} Points",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                f"Error checking balance: {str(e)}",
                ephemeral=True
            )

    @app_commands.command(name="transfer")
    @app_commands.describe(
        recipient="The user to transfer points to",
        amount="Amount of points to transfer",
        reason="Optional reason for the transfer"
    )
    async def transfer(
        self,
        interaction: discord.Interaction,
        recipient: discord.Member,
        amount: int,
        reason: str = None
    ):
        """Transfer points to another user."""
        await interaction.response.defer(ephemeral=True)

        if amount <= 0:
            await interaction.followup.send("Amount must be positive!", ephemeral=True)
            return

        if recipient.id == interaction.user.id:
            await interaction.followup.send("You cannot transfer points to yourself!", ephemeral=True)
            return

        if recipient.bot:
            await interaction.followup.send("You cannot transfer points to bots!", ephemeral=True)
            return

        try:
            # Get sender's balance
            sender_balance = await self.points_service.get_balance(str(interaction.user.id))
            if sender_balance < amount:
                await interaction.followup.send(
                    f"Insufficient balance! You have {sender_balance:,} points.",
                    ephemeral=True
                )
                return

            # Process transfer
            description = f"Transfer to {recipient.display_name}"
            if reason:
                description += f": {reason}"

            success = await self.points_service.transfer_points(
                from_user_id=str(interaction.user.id),
                to_user_id=str(recipient.id),
                amount=amount,
                description=description
            )

            if success:
                # Get updated balances
                new_sender_balance = await self.points_service.get_balance(str(interaction.user.id))
                new_recipient_balance = await self.points_service.get_balance(str(recipient.id))

                embed = discord.Embed(
                    title="Points Transfer",
                    description=f"✅ Successfully transferred {amount:,} points to {recipient.mention}",
                    color=discord.Color.green()
                )

                if reason:
                    embed.add_field(name="Reason", value=reason, inline=False)

                embed.add_field(
                    name="Your New Balance",
                    value=f"{new_sender_balance:,} points",
                    inline=True
                )
                embed.add_field(
                    name=f"{recipient.display_name}'s New Balance",
                    value=f"{new_recipient_balance:,} points",
                    inline=True
                )

                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send("Transfer failed!", ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"Error during transfer: {str(e)}", ephemeral=True)

    @app_commands.command(name="leaderboard")
    async def leaderboard(self, interaction: discord.Interaction):
        """Show the points leaderboard."""
        await interaction.response.defer()

        try:
            # Get all members with points
            members = []
            for member in interaction.guild.members:
                if not member.bot:  # Skip bots
                    balance = await self.points_service.get_balance(str(member.id))
                    if balance > 0:
                        members.append((member, balance))

            # Sort by balance
            members.sort(key=lambda x: x[1], reverse=True)

            embed = discord.Embed(
                title="🏆 Points Leaderboard",
                color=discord.Color.gold()
            )

            # Medal emojis for top 3
            medals = {0: "🥇", 1: "🥈", 2: "🥉"}

            # Add members to leaderboard
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
            await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.followup.send(
                f"Error fetching leaderboard: {str(e)}",
                ephemeral=True
            )

# This is the setup function that Discord.py looks for
async def setup(bot: commands.Bot):
    """Setup function for the Economy cog."""
    await bot.add_cog(Economy(bot))