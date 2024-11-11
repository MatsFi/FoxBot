"""Mixer/Lottery cog for managing token mixing operations."""
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from datetime import datetime
from typing import List, Optional
from services import MixerService, DrawingSummary

class MixerEconomy(commands.Cog):
    """Handles mixer/lottery operations."""
    
    def __init__(self, bot):
        self.bot = bot
        # Get external services from transfer service
        external_services = self.bot.transfer_service._external_services
        self.mixer_service = MixerService(self.bot.database, external_services)
        self.active_tasks = {}

    async def token_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> List[app_commands.Choice[str]]:
        """Autocomplete for token choices."""
        choices = [
            app_commands.Choice(name=name, value=name)
            for name in self.bot.transfer_service._external_services.keys()
        ]
        return choices

    async def schedule_draw(self, draw_id: int, delay_seconds: float, channel: discord.TextChannel):
        """Schedule a draw to be processed."""
        try:
            await asyncio.sleep(delay_seconds)
            success, message, results = await self.mixer_service.process_draw(draw_id)
            
            if not success:
                self.bot.logger.error(f"Failed to process draw {draw_id}: {message}")
                await channel.send(f"❌ Failed to process drawing #{draw_id}: {message}")
                return
                
            if results:
                embed = await self.format_drawing_results(results)
                await channel.send(embed=embed)
            else:
                await channel.send(f"⚠️ Drawing #{draw_id} completed but no results available")
            
        except Exception as e:
            self.bot.logger.error(f"Error in scheduled draw {draw_id}: {e}")
            await channel.send(f"❌ Error processing drawing #{draw_id}: {str(e)}")
        finally:
            self.active_tasks.pop(draw_id, None)

    @commands.hybrid_command(
        name="mixer_init",
        description="Initialize a new token mixer draw"
    )
    @app_commands.describe(
        duration="Duration in minutes (max 5)"
    )
    async def init_draw(self, ctx: commands.Context, duration: int) -> None:
        """Initialize a new mixer draw."""
        await ctx.defer()
        
        try:
            success, message = await self.mixer_service.initialize_draw(duration)
            
            if success:
                draw = await self.mixer_service.get_active_draw()
                delay = (draw.draw_time - datetime.utcnow()).total_seconds()
                
                # Schedule the draw with the channel
                task = asyncio.create_task(
                    self.schedule_draw(
                        draw_id=draw.id,
                        delay_seconds=delay,
                        channel=ctx.channel  # Pass the channel here
                    )
                )
                self.active_tasks[draw.id] = task
                
                embed = discord.Embed(
                    title="🎲 Mixer Draw Initialized",
                    description=message,
                    color=discord.Color.green()
                )
                
                # Add available token types to embed
                token_types = ", ".join(self.bot.transfer_service._external_services.keys())
                embed.add_field(
                    name="Available Token Types",
                    value=token_types,
                    inline=False
                )
                
                embed.add_field(
                    name="Duration",
                    value=f"{duration} minutes",
                    inline=True
                )
                
                embed.add_field(
                    name="Draw Time",
                    value=draw.draw_time.strftime("%H:%M:%S"),
                    inline=True
                )

                embed.add_field(
                    name="Drawing ID",
                    value=f"#{draw.id}",
                    inline=True
                )
            else:
                embed = discord.Embed(
                    title="❌ Failed to Initialize Draw",
                    description=message,
                    color=discord.Color.red()
                )
            
            await ctx.reply(embed=embed)
            
        except Exception as e:
            await ctx.reply(f"Error initializing draw: {str(e)}", ephemeral=True)

    @app_commands.command(
        name="mixer_add",
        description="Add tokens to the active mixer draw"
    )
    @app_commands.describe(
        amount="Amount of tokens to add",
        token="Token type to add",
        is_donation="Whether this is a donation (no tickets)"
    )
    @app_commands.autocomplete(token=token_autocomplete)
    async def add_to_mixer(
        self,
        interaction: discord.Interaction,
        amount: int,
        token: str,
        is_donation: bool = False
    ) -> None:
        """Add tokens to the active mixer."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            if amount <= 0:
                await interaction.followup.send("Amount must be positive!")
                return
                
            active_draw = await self.mixer_service.get_active_draw()
            if not active_draw:
                await interaction.followup.send("No active draw found!")
                return
                
            success, message = await self.mixer_service.add_to_pot(
                active_draw.id,
                str(interaction.user.id),
                interaction.user.name,
                token,
                amount,
                is_donation
            )
            
            if success:
                status = await self.mixer_service.get_draw_status(
                    active_draw.id,
                    str(interaction.user.id)
                )
                
                embed = discord.Embed(
                    title="🎲 Added to Mixer",
                    description=message,
                    color=discord.Color.green()
                )
                
                embed.add_field(
                    name="Amount Added",
                    value=f"{amount} {token}",
                    inline=True
                )
                
                embed.add_field(
                    name="Type",
                    value="Donation" if is_donation else "Regular Entry",
                    inline=True
                )
                
                if not is_donation:
                    embed.add_field(
                        name="Your Tickets",
                        value=f"{status['user_tickets']} ({status['user_ratio']:.2%} chance)",
                        inline=False
                    )
                
                await interaction.followup.send(embed=embed)
            else:
                await interaction.followup.send(f"Failed to add to mixer: {message}")
                
        except Exception as e:
            await interaction.followup.send(f"Error adding to mixer: {str(e)}")

    @app_commands.command(
        name="mixer_status",
        description="Check the status of the active mixer draw"
    )
    async def check_status(self, interaction: discord.Interaction) -> None:
        """Check the status of the active mixer."""
        await interaction.response.defer()
        
        try:
            active_draw = await self.mixer_service.get_active_draw()
            if not active_draw:
                await interaction.followup.send("No active draw found!")
                return
                
            status = await self.mixer_service.get_draw_status(
                active_draw.id,
                str(interaction.user.id)
            )
            
            embed = discord.Embed(
                title="🎲 Mixer Status",
                color=discord.Color.blue()
            )
            
            # Add pot totals
            pot_text = "\n".join(
                f"{token}: {amount:,}" for token, amount in status['pot_totals'].items()
            ) or "Empty"
            embed.add_field(
                name="Current Pot",
                value=pot_text,
                inline=False
            )
            
            # Add ticket information
            embed.add_field(
                name="Total Tickets",
                value=str(status['total_tickets']),
                inline=True
            )
            
            embed.add_field(
                name="Your Tickets",
                value=f"{status['user_tickets']} ({status['user_ratio']:.2%} chance)",
                inline=True
            )
            
            # Add time remaining
            minutes = int(status['time_remaining'] // 60)
            seconds = int(status['time_remaining'] % 60)
            embed.add_field(
                name="Time Remaining",
                value=f"{minutes}m {seconds}s",
                inline=False
            )
            
            # Add draw time
            embed.add_field(
                name="Draw Time",
                value=status['draw_time'].strftime("%H:%M:%S"),
                inline=False
            )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            await interaction.followup.send(f"Error checking status: {str(e)}")

    @app_commands.command(
        name="mixer_results",
        description="View results of past drawings"
    )
    @app_commands.describe(
        drawing_id="Optional: Specific drawing ID to view"
    )
    async def view_results(
        self,
        interaction: discord.Interaction,
        drawing_id: Optional[int] = None
    ) -> None:
        """View results of past drawings."""
        await interaction.response.defer()
        
        try:
            if drawing_id:
                # Get specific drawing results
                results = await self.mixer_service.get_drawing_results(drawing_id)
                if results:
                    embed = await self.format_drawing_results(results)
                    await interaction.followup.send(embed=embed)
                else:
                    await interaction.followup.send(
                        f"❌ No results found for drawing #{drawing_id}. "
                        "The drawing might not exist or hasn't completed yet."
                    )
            else:
                # Get recent drawings list
                drawings = await self.mixer_service.get_recent_drawings(5)
                
                if not drawings:
                    await interaction.followup.send("No drawings found in the database.")
                    return
                
                embed = discord.Embed(
                    title="🎲 Recent Drawings",
                    description="Use `/mixer_results <drawing_id>` to view detailed results for a specific drawing.",
                    color=discord.Color.blue()
                )
                
                for draw_id, draw_time, is_completed in drawings:
                    status = "✅ Completed" if is_completed else "⏳ In Progress"
                    embed.add_field(
                        name=f"Drawing #{draw_id}",
                        value=f"Time: {draw_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                              f"Status: {status}",
                        inline=False
                    )
                
                await interaction.followup.send(embed=embed)
                
        except Exception as e:
            await interaction.followup.send(
                f"Error retrieving results: {str(e)}",
                ephemeral=True
            )

    async def format_drawing_results(self, results: 'DrawingSummary') -> discord.Embed:
        """Format drawing results into an embed.
        
        Args:
            results (DrawingSummary): The drawing results to format
            
        Returns:
            discord.Embed: Formatted embed with drawing results
        """
        embed = discord.Embed(
            title=f"🎲 Drawing #{results.draw_id} Results",
            description=f"Drawing held at {results.draw_time.strftime('%Y-%m-%d %H:%M:%S')}",
            color=discord.Color.gold()
        )
        
        embed.add_field(
            name="Total Participants",
            value=str(results.total_players),
            inline=False
        )
        
        # Add pot totals
        pot_text = "\n".join(
            f"{token}: {amount:,}" for token, amount in results.total_tokens.items()
        )
        embed.add_field(
            name="Total Tokens Distributed",
            value=pot_text,
            inline=False
        )
        
        # Add top winners
        if results.top_awards:
            winners_text = ""
            for i, (username, _, token_type, amount) in enumerate(results.top_awards, 1):
                medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, "")
                winners_text += f"{medal} {username}: {amount:,} {token_type}\n"
            
            embed.add_field(
                name="Top Awards",
                value=winners_text,
                inline=False
            )
        else:
            embed.add_field(
                name="Top Awards",
                value="No winners in this drawing",
                inline=False
            )

        embed.set_footer(text=f"Use /mixer_results {results.draw_id} to view these results again")
        
        return embed
        

async def setup(bot):
    """Set up the Mixer cog."""
    await bot.add_cog(MixerEconomy(bot))