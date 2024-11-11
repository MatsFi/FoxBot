"""Template for economy cogs showing deposit/withdraw implementations."""
import discord
from discord.ext import commands
from discord import app_commands
from typing import Dict, List, Tuple
from utils.decorators import is_admin

def is_admin():
    def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.guild_permissions.administrator
    return app_commands.check(predicate)

class ExternalEconomyCog(commands.Cog):
    """Base class for external economy cogs."""
    
    def __init__(self, bot: commands.Bot, service_class, adapter_class, economy_name: str):
        self.bot = bot
        self.points_service = service_class.from_bot(bot)
        self.adapter = adapter_class(self.points_service)
        
        # Register with transfer service that was initialized by LocalEconomy
        if not hasattr(bot, 'transfer_service'):
            raise RuntimeError("Transfer service not initialized. Ensure LocalEconomy cog is loaded first")
        bot.transfer_service.register_external_service(self.adapter)
        self.economy_name = economy_name

    async def cog_load(self):
        """Called when the cog is loaded."""
        await self.points_service.initialize()
        
    async def cog_unload(self):
        """Called when the cog is unloaded."""
        if self.points_service:
            await self.points_service.cleanup()

    async def process_deposit(self, ctx: commands.Context, amount: int) -> None:
        """Process a deposit from external to local economy."""
        await ctx.defer(ephemeral=True)
        
        if amount <= 0:
            await ctx.reply("❌ Amount must be positive!", ephemeral=True)
            return

        try:
            result = await self.bot.transfer_service.deposit_to_local(
                self.adapter.economy_name,
                str(ctx.author.id),
                amount,
                ctx.author.name
            )
            
            if result.success:
                embed = discord.Embed(
                    title="Cross-Economy Transfer",
                    description=f"✅ Successfully deposited {amount:,} points into Local economy!",
                    color=discord.Color.green()
                )
                
                embed.add_field(
                    name="Previous Balances",
                    value=f"{self.economy_name}: {result.initial_external_balance:,}\n"
                          f"Local: {result.initial_local_balance:,}",
                    inline=False
                )
                
                embed.add_field(
                    name="New Balances",
                    value=f"{self.economy_name}: {result.final_external_balance:,}\n"
                          f"Local: {result.final_local_balance:,}",
                    inline=False
                )
                
                await ctx.reply(embed=embed, ephemeral=True)
            else:
                await ctx.reply(f"❌ {result.message}", ephemeral=True)
                
        except Exception as e:
            await ctx.reply(f"❌ Error during deposit: {str(e)}", ephemeral=True)

    async def process_withdraw(self, ctx: commands.Context, amount: int) -> None:
        """Process a withdrawal from local to external economy."""
        await ctx.defer(ephemeral=True)
        
        if amount <= 0:
            await ctx.reply("❌ Amount must be positive!", ephemeral=True)
            return

        try:
            result = await self.bot.transfer_service.withdraw_to_external(
                self.adapter.economy_name,
                str(ctx.author.id),
                amount,
                ctx.author.name
            )
            
            if result.success:
                embed = discord.Embed(
                    title="Cross-Economy Transfer",
                    description=f"✅ Successfully withdrew {amount:,} points to {self.economy_name} economy!",
                    color=discord.Color.green()
                )
                
                embed.add_field(
                    name="Previous Balances",
                    value=f"Local: {result.initial_local_balance:,}\n"
                          f"{self.economy_name}: {result.initial_external_balance:,}",
                    inline=False
                )
                
                embed.add_field(
                    name="New Balances",
                    value=f"Local: {result.final_local_balance:,}\n"
                          f"{self.economy_name}: {result.final_external_balance:,}",
                    inline=False
                )
                
                await ctx.reply(embed=embed, ephemeral=True)
            else:
                await ctx.reply(f"❌ {result.message}", ephemeral=True)
                
        except Exception as e:
            await ctx.reply(f"❌ Error during withdrawal: {str(e)}", ephemeral=True)