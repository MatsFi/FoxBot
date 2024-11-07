import discord
from discord.ext import commands
# Import PointsManager from models
from models.points_manager import PointsManager

class PlayersCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.points_manager = PointsManager(
            base_url=bot.config['API_BASE_URL'],
            api_key=bot.config['API_KEY'],
            realm_id=bot.config['REALM_ID'],
            hackathon_api_key=bot.config['HACKATHON_API_KEY'],
            hackathon_realm_id=bot.config['HACKATHON_REALM_ID'],
            db_path = bot.config["PLAYER_DB_PATH"],
        )

    @commands.hybrid_command(
        name="player_balance",
        description="Check your token balances.",
    )
    async def balance(self, ctx: commands.Context) -> None:
        """Check your current token balances."""
        try:
            balance = await self.points_manager.get_all_balances(str(ctx.author))
            
            embed = discord.Embed(
                title="Token Balances",
                color=discord.Color.blue()
            )
#            for token_type, balance in balances.items():
            embed.add_field(
                name="token_type",
                value=balance
            )
            
            await ctx.reply(embed=embed, ephemeral=True)
            
        except Exception as e:
            await ctx.reply(
                f"❌ Error checking balance: {str(e)}",
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(PlayersCog(bot))