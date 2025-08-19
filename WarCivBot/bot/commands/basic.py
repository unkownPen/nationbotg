"""
BasicCommands Cog for WarBot
Handles core civilization commands, save system, and command cooldowns
"""

import os
import random
import logging
from datetime import datetime, timedelta
from typing import Optional

import guilded
from guilded.ext import commands

from bot.utils import format_number, get_ascii_art, create_embed
from bot.saves import SaveManager

logger = logging.getLogger(__name__)

# Constants
DEFAULT_IDEOLOGIES = [
    "fascism", "democracy", "communism", "theocracy", "anarchy", 
    "capitalism", "monarchy", "pacifist"
]

IDEOLOGY_DESCRIPTIONS = {
    "fascism": "⚔️ +25% soldier training, -15% diplomacy, -10% luck",
    "democracy": "🗳️ +20% happiness, +10% trade, -15% training",
    "communism": "🏭 +10% productivity, -10% tech speed",
    "theocracy": "⛪ +15% propaganda, +5% happiness, -10% tech",
    "anarchy": "💥 2x events, 0 upkeep, -20% spy success",
    "capitalism": "💰 +35% trade, +25% tax, +20% production, -15% military costs",
    "monarchy": "👑 +20% diplomacy, +25% tax, -10% productivity",
    "pacifist": "🕊️ +35% happiness, +25% growth, -60% combat"
}

class BasicCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = getattr(bot, "db", None)
        self.civ_manager = getattr(bot, "civ_manager", None)
        self.save_manager = SaveManager(self.db)

    def _get_utc_timestamp(self) -> str:
        """Get current UTC time in standard format"""
        return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    def _format_embed(self, title: str, description: str, color=0x00FF00) -> guilded.Embed:
        """Create a standard embed with UTC timestamp"""
        embed = guilded.Embed(
            title=title,
            description=description,
            color=color
        )
        embed.set_footer(text=f"UTC: {self._get_utc_timestamp()}")
        return embed

    @commands.command(name="start")
    async def start_civilization(self, ctx, *, name: str = None):
        """Found a new civilization"""
        try:
            if not name:
                await ctx.send(
                    embed=self._format_embed(
                        "❌ Missing Name",
                        "PRESIDENT! You must provide a name: `.start <name>`",
                        color=0xFF0000
                    )
                )
                return

            user_id = str(ctx.author.id)

            # Check existing civilization
            if existing := await self.civ_manager.get_civilization(user_id):
                await ctx.send(
                    embed=self._format_embed(
                        "❌ Civilization Exists",
                        f"PRESIDENT! You already command {existing['name']}! Use `.status` to view it.",
                        color=0xFF0000
                    )
                )
                return

            # Get cinematic intro
            intro = get_ascii_art("civilization_start")

            # Random founding event
            founding_events = [
                ("🏛️ **Golden Dawn**: Ancient gold deposits discovered!", {"gold": 200}),
                ("🌾 **Fertile Lands**: Rich farming soil blessed!", {"food": 300}),
                ("🏗️ **Master Builders**: Natural architects emerge!", {"stone": 150, "wood": 150}),
                ("👥 **Population Boom**: Your fame spreads!", {"citizens": 50}),
                ("⚡ **Lightning Strike**: Divine fortune!", {"gold": 100, "happiness": 20})
            ]
            event_text, bonus_resources = random.choice(founding_events)

            # Name-based bonuses
            name_bonuses = {}
            special_message = ""
            name_lower = name.lower()

            if "ink" in name_lower:
                name_bonuses["luck_bonus"] = 5
                special_message = "🖋️ *The pen will never forget your work.* (+5% luck)"
            elif "pen" in name_lower:
                name_bonuses["diplomacy_bonus"] = 5
                special_message = "🖋️ *The pen is mightier than the sword.* (+5% diplomacy)"

            # HyperItem chance (5%)
            hyper_item = None
            if random.random() < 0.05:
                hyper_item = random.choice([
                    "Lucky Charm", "Propaganda Kit", "Mercenary Contract"
                ])

            # Create civilization
            if not await self.civ_manager.create_civilization(
                user_id=user_id,
                name=name,
                bonus_resources=bonus_resources,
                bonuses=name_bonuses,
                hyper_item=hyper_item
            ):
                raise Exception("Failed to create civilization")

            # Success embed
            embed = self._format_embed(
                f"🏛️ The Birth of {name}",
                f"{intro}\n\n{event_text}\n{special_message}"
            )

            if hyper_item:
                embed.add_field(
                    name="🎁 Strategic Asset Found!",
                    value=f"Your scouts discovered a **{hyper_item}**!",
                    inline=False
                )

            embed.add_field(
                name="📋 Next Orders",
                value=(
                    "ATTENTION PRESIDENT! Choose your ideology with `.ideology <type>`\n"
                    f"Options: {', '.join(DEFAULT_IDEOLOGIES)}"
                ),
                inline=False
            )

            await ctx.send(embed=embed)

        except Exception as e:
            logger.exception("Error in start command")
            await ctx.send(
                embed=self._format_embed(
                    "❌ Command Error",
                    "ATTENTION PRESIDENT! Failed to create civilization. Try again.",
                    color=0xFF0000
                )
            )

    @commands.command(name="ideology")
    async def choose_ideology(self, ctx, ideology_type: str = None):
        """Choose civilization ideology"""
        try:
            if ideology_type is None:
                embed = self._format_embed(
                    "🏛️ Choose Your Ideology",
                    "Select your government type:"
                )

                for ideology in DEFAULT_IDEOLOGIES:
                    embed.add_field(
                        name=ideology.capitalize(),
                        value=IDEOLOGY_DESCRIPTIONS[ideology],
                        inline=False
                    )

                embed.add_field(
                    name="Usage",
                    value="`.ideology <type>`",
                    inline=False
                )

                await ctx.send(embed=embed)
                return

            # Get civilization
            user_id = str(ctx.author.id)
            if not (civ := await self.civ_manager.get_civilization(user_id)):
                await ctx.send(
                    embed=self._format_embed(
                        "❌ No Civilization",
                        "PRESIDENT! Found a civilization first with `.start <name>`",
                        color=0xFF0000
                    )
                )
                return

            # Check existing ideology
            if civ.get("ideology"):
                await ctx.send(
                    embed=self._format_embed(
                        "❌ Ideology Set",
                        "PRESIDENT! You've already chosen an ideology!",
                        color=0xFF0000
                    )
                )
                return

            # Validate choice
            choice = ideology_type.lower()
            if choice not in DEFAULT_IDEOLOGIES:
                await ctx.send(
                    embed=self._format_embed(
                        "❌ Invalid Choice",
                        f"PRESIDENT! Choose from: {', '.join(DEFAULT_IDEOLOGIES)}",
                        color=0xFF0000
                    )
                )
                return

            # Set ideology
            if not await self.civ_manager.set_ideology(user_id, choice):
                raise Exception("Failed to set ideology")

            # Success message
            embed = self._format_embed(
                f"🏛️ Ideology Set: {choice.capitalize()}",
                IDEOLOGY_DESCRIPTIONS[choice]
            )
            
            embed.add_field(
                name="Orders",
                value="DROP AND GIVE ME 50, PRESIDENT! Check `.status` for updates.",
                inline=False
            )

            await ctx.send(embed=embed)

        except Exception as e:
            logger.exception("Error in ideology command")
            await ctx.send(
                embed=self._format_embed(
                    "❌ Command Error",
                    "PRESIDENT! Failed to set ideology. Try again.",
                    color=0xFF0000
                )
            )

    @commands.command(name="status")
    async def civilization_status(self, ctx):
        """Show civilization status"""
        try:
            user_id = str(ctx.author.id)
            if not (civ := await self.civ_manager.get_civilization(user_id)):
                await ctx.send(
                    embed=self._format_embed(
                        "❌ No Civilization",
                        "PRESIDENT! Found your empire with `.start <name>`",
                        color=0xFF0000
                    )
                )
                return

            ide = civ.get("ideology", "None").capitalize()
            embed = self._format_embed(
                f"🏛️ Status: {civ.get('name')}",
                f"**Commander:** {ctx.author.display_name}\n**Ideology:** {ide}"
            )

            # Resources
            res = civ.get("resources", {})
            embed.add_field(
                name="💰 Resources",
                value=(
                    f"🪙 Gold: {format_number(res.get('gold',0))}\n"
                    f"🌾 Food: {format_number(res.get('food',0))}\n"
                    f"🪨 Stone: {format_number(res.get('stone',0))}\n"
                    f"🪵 Wood: {format_number(res.get('wood',0))}"
                ),
                inline=True
            )

            # Population & Military
            pop = civ.get("population", {})
            mil = civ.get("military", {})
            embed.add_field(
                name="👥 Population & Military",
                value=(
                    f"👤 Citizens: {format_number(pop.get('citizens',0))}\n"
                    f"😊 Happiness: {pop.get('happiness',0)}%\n"
                    f"🍽️ Hunger: {pop.get('hunger',0)}%\n"
                    f"⚔️ Soldiers: {format_number(mil.get('soldiers',0))}\n"
                    f"🕵️ Spies: {format_number(mil.get('spies',0))}\n"
                    f"🔬 Tech: {mil.get('tech_level',0)}"
                ),
                inline=True
            )

            # Territory & Items
            ter = civ.get("territory", {})
            items = civ.get("hyper_items", [])
            embed.add_field(
                name="🗺️ Territory & Items",
                value=(
                    f"🏞️ Land: {format_number(ter.get('land_size',0))} km²\n"
                    f"🎁 HyperItems: {len(items)}\n" +
                    ("\n".join(f"• {item}" for item in items[:5]) + 
                     ("..." if len(items) > 5 else ""))
                ),
                inline=True
            )

            await ctx.send(embed=embed)

        except Exception as e:
            logger.exception("Error in status command")
            await ctx.send(
                embed=self._format_embed(
                    "❌ Command Error",
                    "PRESIDENT! Failed to retrieve status. Try again.",
                    color=0xFF0000
                )
            )

    @commands.command(name="save")
    async def save_civilization_state(self, ctx, slot: int = None, *, name: str = None):
        """Save civilization to slot (1-5)"""
        try:
            if slot is None:
                # Show available slots
                saves = await self.save_manager.list_saves(str(ctx.author.id))
                
                embed = self._format_embed(
                    "💾 Save Slots",
                    "Use `.save <1-5> [name]` to save your civilization."
                )
                
                for save in saves:
                    if save["saved_at"]:
                        embed.add_field(
                            name=f"Slot {save['slot']}: {save['name']}",
                            value=(
                                f"Civilization: {save['civilization_name']}\n"
                                f"Ideology: {save['ideology']}\n"
                                f"Saved: {save['saved_at']}"
                            ),
                            inline=False
                        )
                    else:
                        embed.add_field(
                            name=f"Slot {save['slot']}: Empty",
                            value="Available",
                            inline=False
                        )
                        
                await ctx.send(embed=embed)
                return
                
            # Validate slot
            if not 1 <= slot <= 5:
                await ctx.send(
                    embed=self._format_embed(
                        "❌ Invalid Slot",
                        "PRESIDENT! Choose a slot between 1 and 5.",
                        color=0xFF0000
                    )
                )
                return
                
            # Save civilization
            if await self.save_manager.save_civilization(str(ctx.author.id), slot, name):
                await ctx.send(
                    embed=self._format_embed(
                        "💾 Civilization Saved",
                        f"Your civilization has been saved to slot {slot}!"
                    )
                )
            else:
                await ctx.send(
                    embed=self._format_embed(
                        "❌ Save Failed",
                        "PRESIDENT! Failed to save civilization.",
                        color=0xFF0000
                    )
                )
                
        except Exception as e:
            logger.exception("Error in save command")
            await ctx.send(
                embed=self._format_embed(
                    "❌ Command Error",
                    "PRESIDENT! An error occurred while saving.",
                    color=0xFF0000
                )
            )

    @commands.command(name="load")
    async def load_civilization_state(self, ctx, slot: int):
        """Load civilization from save slot"""
        try:
            if not 1 <= slot <= 5:
                await ctx.send(
                    embed=self._format_embed(
                        "❌ Invalid Slot",
                        "PRESIDENT! Choose a slot between 1 and 5.",
                        color=0xFF0000
                    )
                )
                return
                
            # Load civilization
            if await self.save_manager.load_civilization(str(ctx.author.id), slot):
                await ctx.send(
                    embed=self._format_embed(
                        "📥 Civilization Loaded",
                        f"Your civilization has been restored from slot {slot}!"
                    )
                )
            else:
                await ctx.send(
                    embed=self._format_embed(
                        "❌ Load Failed",
                        "PRESIDENT! Failed to load from that slot.",
                        color=0xFF0000
                    )
                )
                
        except Exception as e:
            logger.exception("Error in load command")
            await ctx.send(
                embed=self._format_embed(
                    "❌ Command Error",
                    "PRESIDENT! An error occurred while loading.",
                    color=0xFF0000
                )
            )

    @commands.command(name="warhelp")
    async def warbot_help(self, ctx, category: str = None):
        """Display help manual"""
        try:
            embed = self._format_embed(
                "🤖 WARBOT MANUAL",
                "Use `.warhelp <category>` for details."
            )

            embed.add_field(
                name="🏛️ Basic Commands",
                value=(
                    "`.start <name>` - Found civilization\n"
                    "`.status` - View status\n"
                    "`.ideology <type>` - Set government\n"
                    "`.save [1-5]` - Save civilization\n"
                    "`.load <1-5>` - Load save\n"
                    "`@WarBot` - Ask NationGPT"
                ),
                inline=False
            )

            embed.add_field(
                name="💰 Economy",
                value=(
                    "`.gather` - Collect resources\n"
                    "`.farm` - Produce food\n"
                    "`.mine` - Extract stone\n"
                    "`.harvest` - Get wood\n"
                    "`.trade` - Trade resources\n"
                    "`.tax` - Collect taxes"
                ),
                inline=False
            )

            embed.add_field(
                name="⚔️ Military",
                value=(
                    "`.train` - Train units\n"
                    "`.attack` - Attack enemy\n"
                    "`.siege` - Siege city\n"
                    "`.spy` - Espionage"
                ),
                inline=False
            )

            embed.add_field(
                name="🎁 HyperItems",
                value=(
                    "Special items from black market:\n"
                    "• Lucky Charm - Critical hits\n"
                    "• Nuclear Warhead - Mass damage\n"
                    "• Propaganda Kit - Convert troops"
                ),
                inline=False
            )

            embed.add_field(
                name="🤝 Diplomacy",
                value=(
                    "`.ally` - Form alliance\n"
                    "`.break` - End alliance\n"
                    "`.mail` - Send message\n"
                    "`.coalition` - Create faction"
                ),
                inline=False
            )

            await ctx.send(embed=embed)

        except Exception as e:
            logger.exception("Error in help command")
            await ctx.send(
                embed=self._format_embed(
                    "❌ Command Error",
                    "PRESIDENT! Failed to show help. Try again.",
                    color=0xFF0000
                )
            )

async def setup(bot):
    """Add cog to bot"""
    await bot.add_cog(BasicCommands(bot))
