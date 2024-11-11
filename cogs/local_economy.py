"""Local economy cog implementation."""
import discord
from discord.ext import commands
from discord import app_commands
from services import LocalPointsService, CrossEconomyTransferService
from utils.decorators import is_admin

class LocalEconomy(commands.Cog):
    """Economy management commands."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.points_service = LocalPointsService.from_bot(bot)
        
        # Initialize transfer service and attach to bot for other cogs to access
        self.bot.transfer_service = CrossEconomyTransferService(self.points_service)
        
    async def cog_load(self):
        """Called when the cog is loaded."""
        await self.points_service.initialize()
        
    async def cog_unload(self):
        """Called when the cog is unloaded."""
        if self.points_service:
            await self.points_service.cleanup()

    @app_commands.command(name="local_token_mint", description="[Admin] Mint new tokens for yourself")
    @app_commands.describe(amount="Amount of tokens to mint")
    @is_admin()
    async def token_mint(self, interaction: discord.Interaction, amount: int):
        await interaction.response.defer(ephemeral=True)
        
        try:
            if amount <= 0:
                await interaction.followup.send("❌ Amount must be positive!", ephemeral=True)
                return
                
            current_balance = await self.points_service.get_balance(
                str(interaction.user.id),
                username=interaction.user.name
            )
            
            success = await self.points_service.add_points(
                str(interaction.user.id),
                amount,
                f"Minted {amount} tokens",
                username=interaction.user.name
            )
            
            if success:
                new_balance = await self.points_service.get_balance(
                    str(interaction.user.id),
                    username=interaction.user.name
                )
                
                embed = discord.Embed(
                    title="🌟 Token Minting Success",
                    description=f"Successfully minted {amount:,} tokens!",
                    color=discord.Color.green()
                )
                
                embed.add_field(
                    name="Previous Balance",
                    value=f"{current_balance:,} tokens",
                    inline=True
                )
                
                embed.add_field(
                    name="New Balance",
                    value=f"{new_balance:,} tokens",
                    inline=True
                )
                
                embed.timestamp = discord.utils.utcnow()
                embed.set_footer(
                    text=f"Minted by {interaction.user.display_name}",
                    icon_url=interaction.user.display_avatar.url
                )
                
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send(
                    "❌ Failed to mint tokens. Please try again later.",
                    ephemeral=True
                )
                
        except Exception as e:
            await interaction.followup.send(
                f"❌ Error minting tokens: {str(e)}",
                ephemeral=True
            )
                        
    @app_commands.command(name="local_balance")
    async def check_balance(self, interaction: discord.Interaction):
        """Check your points balance."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            balance = await self.points_service.get_balance(
                str(interaction.user.id),
                username=interaction.user.name
            )
            await interaction.followup.send(
                f"Your balance: {balance:,} Points",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                f"Error checking balance: {str(e)}",
                ephemeral=True
            )

    @app_commands.command(name="local_transfer")
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
            sender_balance = await self.points_service.get_balance(
                str(interaction.user.id),
                username=interaction.user.name
            )
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
                from_discord_id=str(interaction.user.id),
                to_discord_id=str(recipient.id),
                amount=amount,
                description=description,
                from_username=interaction.user.name,
                to_username=recipient.name
            )

            if success:
                # Get updated balances
                new_sender_balance = await self.points_service.get_balance(
                    str(interaction.user.id),
                    username=interaction.user.name
                )
                new_recipient_balance = await self.points_service.get_balance(
                    str(recipient.id),
                    username=recipient.name
                )

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

    @app_commands.command(name="local_leaderboard")
    async def leaderboard(self, interaction: discord.Interaction):
        """Show the points leaderboard."""
        await interaction.response.defer()

        try:
            # Get all members with points
            members = []
            for member in interaction.guild.members:
                if not member.bot:  # Skip bots
                    balance = await self.points_service.get_balance(
                        str(member.id),
                        username=member.name
                    )
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

    @app_commands.command(name="local_debug_balance", description="[Admin] Debug balance information")
    @is_admin()
    async def debug_balance(self, interaction: discord.Interaction):
        """Debug command to show detailed balance information."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Get balance
            balance = await self.points_service.get_balance(
                str(interaction.user.id),
                username=interaction.user.name
            )
            
            # Get recent transactions
            transactions = await self.points_service.get_transactions(
                str(interaction.user.id)
            )
            
            embed = discord.Embed(
                title="🔍 Balance Debug Information",
                color=discord.Color.blue()
            )
            
            embed.add_field(
                name="Current Balance",
                value=f"{balance:,} tokens",
                inline=False
            )
            
            if transactions:
                trans_text = "\n".join(
                    f"• {t.timestamp.strftime('%Y-%m-%d %H:%M:%S')}: {t.amount:+d} ({t.description})"
                    for t in transactions[-10:]  # Show last 10 transactions
                )
                embed.add_field(
                    name="Recent Transactions",
                    value=trans_text or "No transactions",
                    inline=False
                )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(
                f"❌ Error getting debug info: {str(e)}",
                ephemeral=True
            )

    @token_mint.error
    @debug_balance.error
    async def admin_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            await interaction.response.send_message(
                "You don't have permission to use this command!",
                ephemeral=True
            )

async def setup(bot):
    """Setup function for the Economy cog."""
    await bot.add_cog(LocalEconomy(bot))