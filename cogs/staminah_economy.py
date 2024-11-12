"""Staminah game cog implementation."""
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict
from dataclasses import dataclass
from database.models import GameState, Player, Miner
from services.staminah_types import MinerState
from services.staminah_service import StaminahService
from services.staminah_constants import (
    STAM_CONVERSION_RATE,
    BLOCK_TIME,
    MINER_TYPES,
    MAX_CONSUMPTION_RATE
)

class StaminahEconomy(commands.Cog):
    """Handles Staminah game operations."""
    
    def __init__(self, bot):
        self.bot = bot
        self.staminah_service = StaminahService.from_bot(bot)
        self.block_task = self.process_blocks.start()
        self.update_task = self.update_miners.start()

    async def cog_load(self):
        """Initialize the game when the cog loads."""
        await self.staminah_service.initialize()

    async def cog_unload(self):
        """Cleanup when the cog unloads."""
        self.block_task.cancel()
        self.update_task.cancel()
        await self.staminah_service.cleanup()

    @tasks.loop(seconds=BLOCK_TIME)
    async def process_blocks(self):
        """Process blocks at regular intervals."""
        try:
            winner = await self.staminah_service.process_block()
            if winner:
                channel = self.bot.get_channel(self.bot.config.staminah_channel_id)
                if channel:
                    now = datetime.now(timezone.utc)
                    embed = discord.Embed(
                        title="🌽 Block Mined!",
                        description=f"Block #{self.staminah_service.current_block-1}",
                        color=discord.Color.gold(),
                        timestamp=now  # Discord will handle timezone conversion
                    )
                    embed.add_field(
                        name="Winner",
                        value=f"<@{winner.owner_id}>",
                        inline=True
                    )
                    embed.add_field(
                        name="Reward",
                        value=f"{self.staminah_service.current_reward:.2f} CORN",
                        inline=True
                    )
                    embed.add_field(
                        name="Work Produced",
                        value=f"{winner.total_work:,.2f}",
                        inline=True
                    )
                    await channel.send(embed=embed)
        except Exception as e:
            self.bot.logger.error(f"Error processing block: {e}")

    @tasks.loop(seconds=15)
    async def update_miners(self):
        """Update miner work periodically."""
        try:
            await self.staminah_service.update_miner_work()
        except Exception as e:
            self.bot.logger.error(f"Error updating miners: {e}")

    @commands.hybrid_command(
        name="staminah_deposit",
        description="Convert external tokens to STAM"
    )
    @app_commands.describe(
        token_type="Type of token to convert",
        amount="Amount of tokens to convert"
    )
    async def deposit(
        self,
        ctx: commands.Context,
        token_type: str,
        amount: int
    ) -> None:
        """Convert external tokens to STAM."""
        await ctx.defer(ephemeral=True)
        
        try:
            result = await self.bot.transfer_service.deposit_to_local(
                token_type,
                str(ctx.author.id),
                amount,
                ctx.author.name
            )
            
            if result.success:
                stam_amount = amount * STAM_CONVERSION_RATE
                async with self.bot.database.session() as session:
                    player = await session.get(Player, str(ctx.author.id))
                    if not player:
                        player = Player(
                            discord_id=str(ctx.author.id),
                            username=ctx.author.name,
                            stam_balance=stam_amount,
                            created_at=datetime.now(timezone.utc)
                        )
                        session.add(player)
                    else:
                        player.stam_balance += stam_amount
                    await session.commit()
                
                embed = discord.Embed(
                    title="💱 Token Conversion",
                    description=f"Successfully converted {amount} {token_type} to {stam_amount:,} STAM!",
                    color=discord.Color.green(),
                    timestamp=datetime.now(timezone.utc)
                )
                await ctx.reply(embed=embed, ephemeral=True)
            else:
                await ctx.reply(f"❌ {result.message}", ephemeral=True)
                
        except Exception as e:
            await ctx.reply(f"Error during deposit: {str(e)}", ephemeral=True)

    @commands.hybrid_command(
        name="staminah_withdraw",
        description="Convert STAM to external tokens"
    )
    @app_commands.describe(
        token_type="Type of token to receive",
        stam_amount="Amount of STAM to convert"
    )
    async def withdraw(
        self,
        ctx: commands.Context,
        token_type: str,
        stam_amount: int
    ) -> None:
        """Convert STAM back to external tokens."""
        await ctx.defer(ephemeral=True)
        
        try:
            async with self.bot.database.session() as session:
                player = await session.get(Player, str(ctx.author.id))
                if not player or player.stam_balance < stam_amount:
                    await ctx.reply("❌ Insufficient STAM balance!", ephemeral=True)
                    return
                
                external_amount = stam_amount // STAM_CONVERSION_RATE
                if external_amount < 1:
                    await ctx.reply(
                        f"❌ Minimum withdrawal is {STAM_CONVERSION_RATE:,} STAM",
                        ephemeral=True
                    )
                    return
                
                result = await self.bot.transfer_service.withdraw_to_external(
                    token_type,
                    str(ctx.author.id),
                    external_amount,
                    ctx.author.name
                )
                
                if result.success:
                    player.stam_balance -= stam_amount
                    await session.commit()
                    
                    embed = discord.Embed(
                        title="💱 Token Conversion",
                        description=f"Successfully converted {stam_amount:,} STAM to {external_amount} {token_type}!",
                        color=discord.Color.green(),
                        timestamp=datetime.now(timezone.utc)
                    )
                    await ctx.reply(embed=embed, ephemeral=True)
                else:
                    await ctx.reply(f"❌ {result.message}", ephemeral=True)
                    
        except Exception as e:
            await ctx.reply(f"Error during withdrawal: {str(e)}", ephemeral=True)

    @app_commands.command(
        name="buy_miner",
        description="Purchase a miner"
    )
    @app_commands.describe(
        miner_type="Type of miner to purchase"
    )
    @app_commands.choices(miner_type=[
        app_commands.Choice(name=info["name"], value=name)
        for name, info in MINER_TYPES.items()
    ])
    async def buy_miner(
        self,
        interaction: discord.Interaction,
        miner_type: str
    ) -> None:
        """Purchase a miner."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            if miner_type not in MINER_TYPES:
                await interaction.followup.send("Invalid miner type!", ephemeral=True)
                return
                
            async with self.bot.database.session() as session:
                # Check if player already has a miner
                existing_miner = await session.get(Miner, str(interaction.user.id))
                if existing_miner:
                    await interaction.followup.send(
                        "You already own a miner! Sell your current one first.",
                        ephemeral=True
                    )
                    return
                
                # Check if player can afford it
                player = await session.get(Player, str(interaction.user.id))
                cost = MINER_TYPES[miner_type]["cost"]
                
                if not player or player.stam_balance < cost:
                    await interaction.followup.send(
                        f"Insufficient STAM! Cost: {cost:,} STAM",
                        ephemeral=True
                    )
                    return
                
                # Purchase the miner
                player.stam_balance -= cost
                now = datetime.now(timezone.utc)
                new_miner = Miner(
                    owner_id=str(interaction.user.id),
                    miner_type=miner_type,
                    is_on=False,
                    stam_balance=0,
                    work=0,
                    total_work=0,
                    consumption_rate=0,
                    last_update=now
                )
                session.add(new_miner)
                
                # Add to game state
                self.staminah_service.miners[str(interaction.user.id)] = MinerState(
                    owner_id=str(interaction.user.id),
                    miner_type=miner_type,
                    is_on=False,
                    stam_balance=0,
                    work=0,
                    total_work=0,
                    consumption_rate=0,
                    last_update=now
                )
                
                await session.commit()
                
                embed = discord.Embed(
                    title="🛒 Miner Purchased!",
                    description=f"Successfully purchased a {MINER_TYPES[miner_type]['name']}!",
                    color=discord.Color.green(),
                    timestamp=now
                )
                embed.add_field(
                    name="Cost",
                    value=f"{cost:,} STAM",
                    inline=True
                )
                embed.add_field(
                    name="Efficiency",
                    value=f"{MINER_TYPES[miner_type]['efficiency']}x",
                    inline=True
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                
        except Exception as e:
            await interaction.followup.send(f"Error purchasing miner: {str(e)}", ephemeral=True)

    @app_commands.command(
        name="sell_miner",
        description="Sell your current miner for 50% of its value"
    )
    async def sell_miner(self, interaction: discord.Interaction) -> None:
        """Sell your current miner."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            async with self.bot.database.session() as session:
                miner = await session.get(Miner, str(interaction.user.id))
                if not miner:
                    await interaction.followup.send("You don't own a miner!", ephemeral=True)
                    return
                
                # Calculate refund (50% of original cost)
                refund = MINER_TYPES[miner.miner_type]["cost"] // 2
                
                # Return STAM balance if any
                refund += miner.stam_balance
                
                # Update player balance
                player = await session.get(Player, str(interaction.user.id))
                if player:
                    player.stam_balance += refund
                
                # Remove miner
                await session.delete(miner)
                self.staminah_service.miners.pop(str(interaction.user.id), None)
                
                await session.commit()
                
                embed = discord.Embed(
                    title="💰 Miner Sold",
                    description="Successfully sold your miner!",
                    color=discord.Color.green(),
                    timestamp=datetime.now(timezone.utc)
                )
                embed.add_field(
                    name="Refund",
                    value=f"{refund:,} STAM",
                    inline=True
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                
        except Exception as e:
            await interaction.followup.send(f"Error selling miner: {str(e)}", ephemeral=True)

    @app_commands.command(
        name="configure_miner",
        description="Configure your miner's STAM consumption rate"
    )
    @app_commands.describe(
        rate="STAM consumption rate (0-200 STAM per minute)"
    )
    async def configure_miner(self, interaction: discord.Interaction, rate: int) -> None:
        """Configure miner's STAM consumption rate."""
        await interaction.response.defer(ephemeral=True)
        
        if not (0 <= rate <= MAX_CONSUMPTION_RATE):
            await interaction.followup.send(
                f"❌ Rate must be between 0 and {MAX_CONSUMPTION_RATE} STAM per minute",
                ephemeral=True
            )
            return
            
        try:
            async with self.bot.database.session() as session:
                miner = await session.get(Miner, str(interaction.user.id))
                if not miner:
                    await interaction.followup.send("You don't own a miner!", ephemeral=True)
                    return
                
                # Update consumption rate
                now = datetime.now(timezone.utc)
                miner.consumption_rate = rate
                miner.last_update = now  # Update timestamp when configuration changes
                
                if str(interaction.user.id) in self.staminah_service.miners:
                    self.staminah_service.miners[str(interaction.user.id)].consumption_rate = rate
                    self.staminah_service.miners[str(interaction.user.id)].last_update = now
                    
                await session.commit()
                
                embed = discord.Embed(
                    title="⚙️ Miner Configured",
                    description=f"Set STAM consumption rate to {rate} STAM/minute",
                    color=discord.Color.blue(),
                    timestamp=now
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                
        except Exception as e:
            await interaction.followup.send(
                f"Error configuring miner: {str(e)}",
                ephemeral=True
            )

    @app_commands.command(
        name="add_stam",
        description="Add STAM to your miner"
    )
    @app_commands.describe(
        amount="Amount of STAM to add"
    )
    async def add_stam(self, interaction: discord.Interaction, amount: int) -> None:
        """Add STAM to your miner."""
        await interaction.response.defer(ephemeral=True)
        
        if amount <= 0:
            await interaction.followup.send("Amount must be positive!", ephemeral=True)
            return
            
        try:
            async with self.bot.database.session() as session:
                player = await session.get(Player, str(interaction.user.id))
                miner = await session.get(Miner, str(interaction.user.id))
                
                if not miner:
                    await interaction.followup.send("You don't own a miner!", ephemeral=True)
                    return
                    
                if not player or player.stam_balance < amount:
                    await interaction.followup.send("Insufficient STAM balance!", ephemeral=True)
                    return
                
                # Transfer STAM
                now = datetime.now(timezone.utc)
                player.stam_balance -= amount
                miner.stam_balance += amount
                miner.last_update = now  # Update timestamp when STAM is added
                
                if str(interaction.user.id) in self.staminah_service.miners:
                    self.staminah_service.miners[str(interaction.user.id)].stam_balance += amount
                    self.staminah_service.miners[str(interaction.user.id)].last_update = now
                    
                await session.commit()
                
                embed = discord.Embed(
                    title="💨 STAM Added",
                    description=f"Added {amount:,} STAM to your miner",
                    color=discord.Color.blue(),
                    timestamp=now
                )
                embed.add_field(
                    name="Miner STAM Balance",
                    value=f"{miner.stam_balance:,} STAM",
                    inline=True
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                
        except Exception as e:
            await interaction.followup.send(f"Error adding STAM: {str(e)}", ephemeral=True)

    @app_commands.command(
        name="recover_stam",
        description="Recover unused STAM from your miner"
    )
    async def recover_stam(self, interaction: discord.Interaction) -> None:
        """Recover unused STAM from your miner."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            async with self.bot.database.session() as session:
                player = await session.get(Player, str(interaction.user.id))
                miner = await session.get(Miner, str(interaction.user.id))
                
                if not miner:
                    await interaction.followup.send("You don't own a miner!", ephemeral=True)
                    return
                    
                if miner.is_on:
                    await interaction.followup.send(
                        "Turn off your miner first!",
                        ephemeral=True
                    )
                    return
                
                if miner.stam_balance <= 0:
                    await interaction.followup.send(
                        "No STAM to recover!",
                        ephemeral=True
                    )
                    return
                
                # Recover STAM
                now = datetime.now(timezone.utc)
                recovered = miner.stam_balance
                player.stam_balance += recovered
                miner.stam_balance = 0
                miner.last_update = now  # Update timestamp when STAM is recovered
                
                if str(interaction.user.id) in self.staminah_service.miners:
                    self.staminah_service.miners[str(interaction.user.id)].stam_balance = 0
                    self.staminah_service.miners[str(interaction.user.id)].last_update = now
                    
                await session.commit()
                
                embed = discord.Embed(
                    title="💨 STAM Recovered",
                    description=f"Recovered {recovered:,} STAM from your miner",
                    color=discord.Color.blue(),
                    timestamp=now
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                
        except Exception as e:
            await interaction.followup.send(
                f"Error recovering STAM: {str(e)}",
                ephemeral=True
            )

    @app_commands.command(
        name="toggle_miner",
        description="Turn your miner on or off"
    )
    async def toggle_miner(self, interaction: discord.Interaction) -> None:
        """Toggle miner on/off."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            async with self.bot.database.session() as session:
                miner = await session.get(Miner, str(interaction.user.id))
                
                if not miner:
                    await interaction.followup.send("You don't own a miner!", ephemeral=True)
                    return
                
                if miner.consumption_rate == 0:
                    await interaction.followup.send(
                        "Configure consumption rate first!",
                        ephemeral=True
                    )
                    return
                
                # Toggle state
                now = datetime.now(timezone.utc)
                miner.is_on = not miner.is_on
                miner.last_update = now  # Update timestamp when toggling state
                
                if str(interaction.user.id) in self.staminah_service.miners:
                    self.staminah_service.miners[str(interaction.user.id)].is_on = miner.is_on
                    self.staminah_service.miners[str(interaction.user.id)].last_update = now
                    
                await session.commit()
                
                status = "ON" if miner.is_on else "OFF"
                embed = discord.Embed(
                    title="🔄 Miner Toggled",
                    description=f"Miner is now {status}",
                    color=discord.Color.green() if miner.is_on else discord.Color.red(),
                    timestamp=now
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                
        except Exception as e:
            await interaction.followup.send(
                f"Error toggling miner: {str(e)}",
                ephemeral=True
            )

    @app_commands.command(
        name="miner_status",
        description="Check your miner's status"
    )
    async def miner_status(self, interaction: discord.Interaction) -> None:
        """Check miner status."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            async with self.bot.database.session() as session:
                miner = await session.get(Miner, str(interaction.user.id))
                
                if not miner:
                    await interaction.followup.send("You don't own a miner!", ephemeral=True)
                    return
                
                now = datetime.now(timezone.utc)
                uptime = now - miner.last_update if miner.is_on else timedelta()
                
                embed = discord.Embed(
                    title="📊 Miner Status",
                    color=discord.Color.blue(),
                    timestamp=now
                )
                
                embed.add_field(
                    name="Type",
                    value=MINER_TYPES[miner.miner_type]["name"],
                    inline=True
                )
                
                embed.add_field(
                    name="Status",
                    value="🟢 ON" if miner.is_on else "🔴 OFF",
                    inline=True
                )
                
                embed.add_field(
                    name="STAM Balance",
                    value=f"{miner.stam_balance:,} STAM",
                    inline=True
                )
                
                embed.add_field(
                    name="Consumption Rate",
                    value=f"{miner.consumption_rate} STAM/min",
                    inline=True
                )
                
                embed.add_field(
                    name="Current Work",
                    value=f"{miner.work:,.2f}",
                    inline=True
                )
                
                embed.add_field(
                    name="Total Work",
                    value=f"{miner.total_work:,.2f}",
                    inline=True
                )
                
                if miner.is_on:
                    hours, remainder = divmod(uptime.seconds, 3600)
                    minutes, seconds = divmod(remainder, 60)
                    embed.add_field(
                        name="Current Session",
                        value=f"{hours}h {minutes}m {seconds}s",
                        inline=True
                    )
                
                embed.add_field(
                    name="Last Updated",
                    value=miner.last_update.strftime("%Y-%m-%d %H:%M:%S %Z"),
                    inline=True
                )
                
                await interaction.followup.send(embed=embed, ephemeral=True)
                
        except Exception as e:
            await interaction.followup.send(
                f"Error checking status: {str(e)}",
                ephemeral=True
            )

    @app_commands.command(
        name="game_stats",
        description="View current game statistics"
    )
    async def game_stats(self, interaction: discord.Interaction) -> None:
        """View game statistics."""
        await interaction.response.defer()
        
        try:
            now = datetime.now(timezone.utc)
            embed = discord.Embed(
                title="🎮 Staminah Game Stats",
                color=discord.Color.blue(),
                timestamp=now
            )
            
            embed.add_field(
                name="Current Block",
                value=str(self.staminah_service.current_block),
                inline=True
            )
            
            embed.add_field(
                name="Block Reward",
                value=f"{self.staminah_service.current_reward:.2f} CORN",
                inline=True
            )
            
            if self.staminah_service.accumulated_reward > 0:
                embed.add_field(
                    name="Accumulated Reward",
                    value=f"{self.staminah_service.accumulated_reward:.2f} CORN",
                    inline=True
                )
            
            corn_remaining = MAX_CORN_SUPPLY - self.staminah_service.total_corn_mined
            embed.add_field(
                name="CORN Remaining",
                value=f"{corn_remaining:,.2f}",
                inline=True
            )
            
            embed.add_field(
                name="Total Work Produced",
                value=f"{self.staminah_service.total_work:,.2f}",
                inline=True
            )
            
            if self.staminah_service.last_blocks_work:
                avg_work = sum(self.staminah_service.last_blocks_work) / len(self.staminah_service.last_blocks_work)
                embed.add_field(
                    name="Average Work (Last 10)",
                    value=f"{avg_work:,.2f}",
                    inline=True
                )
            
            time_to_decay = self.staminah_service.next_decay - now
            days = time_to_decay.days
            hours = time_to_decay.seconds // 3600
            minutes = (time_to_decay.seconds % 3600) // 60
            seconds = time_to_decay.seconds % 60
            
            embed.add_field(
                name="Next Reward Decay",
                value=f"{days}d {hours:02d}h {minutes:02d}m {seconds:02d}s",
                inline=True
            )
            
            active_miners = sum(1 for m in self.staminah_service.miners.values() if m.is_on)
            total_miners = len(self.staminah_service.miners)
            
            embed.add_field(
                name="Active Miners",
                value=f"{active_miners}/{total_miners}",
                inline=True
            )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            await interaction.followup.send(
                f"Error fetching game stats: {str(e)}",
                ephemeral=True
            )

    @app_commands.command(
        name="leaderboard",
        description="View the mining leaderboard"
    )
    @app_commands.describe(
        sort_by="Sort by total work or CORN balance"
    )
    @app_commands.choices(sort_by=[
        app_commands.Choice(name="Total Work", value="work"),
        app_commands.Choice(name="CORN Balance", value="corn")
    ])
    async def leaderboard(
        self,
        interaction: discord.Interaction,
        sort_by: str = "work"
    ) -> None:
        """View the mining leaderboard."""
        await interaction.response.defer()
        
        try:
            now = datetime.now(timezone.utc)
            async with self.bot.database.session() as session:
                if sort_by == "work":
                    query = select(Miner).order_by(desc(Miner.total_work)).limit(10)
                    results = await session.execute(query)
                    miners = results.scalars().all()
                    
                    embed = discord.Embed(
                        title="🏆 Top Miners by Total Work",
                        color=discord.Color.gold(),
                        timestamp=now
                    )
                    
                    for i, miner in enumerate(miners, 1):
                        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
                        embed.add_field(
                            name=f"{medal} <@{miner.owner_id}>",
                            value=f"Work: {miner.total_work:,.2f}\n"
                                  f"Type: {MINER_TYPES[miner.miner_type]['name']}",
                            inline=False
                        )
                else:  # sort by CORN balance
                    query = select(Player).order_by(desc(Player.corn_balance)).limit(10)
                    results = await session.execute(query)
                    players = results.scalars().all()
                    
                    embed = discord.Embed(
                        title="🌽 Top CORN Holders",
                        color=discord.Color.gold(),
                        timestamp=now
                    )
                    
                    for i, player in enumerate(players, 1):
                        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
                        embed.add_field(
                            name=f"{medal} <@{player.discord_id}>",
                            value=f"Balance: {player.corn_balance:,.2f} CORN",
                            inline=False
                        )
                
                await interaction.followup.send(embed=embed)
                
        except Exception as e:
            await interaction.followup.send(
                f"Error fetching leaderboard: {str(e)}",
                ephemeral=True
            )

async def setup(bot):
    """Set up the Staminah cog."""
    await bot.add_cog(StaminahEconomy(bot))