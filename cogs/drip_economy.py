from discord.ext import commands
import discord
from discord import app_commands

from models.drip_points_manager import PointsManagerSingleton

def is_admin():
    def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.guild_permissions.administrator
    return app_commands.check(predicate)

class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.points_manager = PointsManagerSingleton(
            base_url=bot.config['API_BASE_URL'],
            api_key=bot.config['API_KEY'],
            realm_id=bot.config['REALM_ID'],
#            hackathon_api_key=bot.config['HACKATHON_API_KEY'],
#            hackathon_realm_id=bot.config['HACKATHON_REALM_ID'],
#            db_path = bot.config["PLAYER_DB_PATH"],
        )

    @app_commands.guild_only()
    @app_commands.command(name="balance", description="Check your Points balance")
    async def check_balance(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        try:
            balance = await self.points_manager.get_balance(interaction.user.id)
            await interaction.followup.send(f"Your balance: {balance:,} Points", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error checking balance: {str(e)}", ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="tip", description="Tip Points to another user")
    @app_commands.describe(
        user="The user to tip",
        amount="Amount of Points to tip"
    )
    async def tip(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        await interaction.response.defer(ephemeral=True)
        
        if amount <= 0:
            await interaction.followup.send("Amount must be positive!", ephemeral=True)
            return
            
        if user.id == interaction.user.id:
            await interaction.followup.send("You can't tip yourself!", ephemeral=True)
            return

        if user.bot:
            await interaction.followup.send("You can't tip bots!", ephemeral=True)
            return
        
        try:
            # Check if sender has enough balance
            sender_balance = await self.points_manager.get_balance(interaction.user.id)
            if sender_balance < amount:
                await interaction.followup.send(
                    f"You don't have enough Points! Your balance: {sender_balance:,} Points", 
                    ephemeral=True
                )
                return

            success = await self.points_manager.transfer_points(
                interaction.user.id,
                user.id,
                amount
            )
            
            if success:
                await interaction.followup.send(
                    f"Successfully tipped {amount:,} Points to {user.mention}!",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Failed to transfer Points. Please try again later.",
                    ephemeral=True
                )
        except Exception as e:
            await interaction.followup.send(f"Error processing tip: {str(e)}", ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="add_points", description="[Admin] Add Points to a user")
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
            success = await self.points_manager.add_points(user.id, amount)
            
            if success:
                new_balance = await self.points_manager.get_balance(user.id)
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
    @app_commands.command(name="remove_points", description="[Admin] Remove Points from a user")
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
            # Check if user has enough balance
            current_balance = await self.points_manager.get_balance(user.id)
            if current_balance < amount:
                await interaction.followup.send(
                    f"User only has {current_balance:,} Points! Cannot remove {amount:,} Points.",
                    ephemeral=True
                )
                return

            success = await self.points_manager.remove_points(user.id, amount)
            
            if success:
                new_balance = await self.points_manager.get_balance(user.id)
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
    @app_commands.command(name="check", description="Check another user's Points balance")
    @app_commands.describe(user="The user to check")
    async def check_other(self, interaction: discord.Interaction, user: discord.Member):
        await interaction.response.defer(ephemeral=True)
        
        if user.bot:
            await interaction.followup.send("Bots don't have Points!", ephemeral=True)
            return
        
        try:
            balance = await self.points_manager.get_balance(user.id)
            await interaction.followup.send(
                f"{user.mention}'s balance: {balance:,} Points",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"Error checking balance: {str(e)}", ephemeral=True)

    @commands.hybrid_command(
        name="leaderboard",
        description="Show the points leaderboard"
    )
    async def leaderboard(self, ctx: commands.Context) -> None:
        """Show the server's points leaderboard."""
        try:
            # Get all members with points
            members = []
            for member in ctx.guild.members:
                if not member.bot:  # Skip bots
                    balance = await self.points_manager.get_balance(member.id)
                    if balance > 0:
                        members.append((member, balance))

            # Sort by balance
            members.sort(key=lambda x: x[1], reverse=True)

            embed = discord.Embed(
                title="🏆 Points Leaderboard",
                color=discord.Color.gold()
            )

            # Medal emojis for top 3
            medals = {
                0: "🥇",
                1: "🥈",
                2: "🥉"
            }

            # Add members to leaderboard
            leaderboard_text = []
            for idx, (member, balance) in enumerate(members[:10], 1):
                if idx <= 3:
                    # Top 3 get medals
                    prefix = medals[idx-1]
                else:
                    # Others get numbers
                    prefix = f"`#{idx}`"
                
                leaderboard_text.append(
                    f"{prefix} {member.mention}: **{balance:,}** points"
                )

            if leaderboard_text:
                embed.description = "\n".join(leaderboard_text)
            else:
                embed.description = "No points recorded yet!"

            # Add total participants
            embed.set_footer(text=f"Total Participants: {len(members)}")

            await ctx.reply(embed=embed)

        except Exception as e:
            await ctx.reply(
                f"❌ Error fetching leaderboard: {str(e)}",
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

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Economy(bot))