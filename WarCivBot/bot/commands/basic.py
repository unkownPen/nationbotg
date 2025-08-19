"""
BasicCommands Cog for WarBot

Provides core civilization commands:
- .start - Found a new civilization
- .ideology - Choose government type
- .status - View civilization status
- .warhelp - Display command manual
"""

import os
import random
import logging
from datetime import datetime, timedelta
from collections import defaultdict, deque

import guilded
from guilded.ext import commands

from bot.utils import format_number, get_ascii_art, create_embed

logger = logging.getLogger(__name__)

# Constants
MAX_CONVERSATION_HISTORY = 5
CONVERSATION_TIMEOUT = 1800  # 30 minutes
DEFAULT_AI_MODEL = "deepseek/deepseek-chat"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

DEFAULT_IDEOLOGIES = [
    "fascism", "democracy", "communism", "socialism", 
    "theocracy", "anarchy", "monarchy", "terrorism", "pacifist"
]

class BasicCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = getattr(bot, "db", None)
        self.civ_manager = getattr(bot, "civ_manager", None)
        
        # AI chat settings
        self.openrouter_key = os.getenv("OPENROUTER")
        self.current_model = os.getenv("AI_MODEL", DEFAULT_AI_MODEL)
        self.rate_limited = False
        self.model_switch_time = None
        
        # Conversation tracking
        self.conversations = defaultdict(deque)
        self.last_interaction = {}

    def _get_utc_time(self) -> str:
        """Get current UTC time in standard format"""
        return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    def _format_embed(self, title: str, desc: str, color=0x00FF00) -> guilded.Embed:
        """Create a standard embed with footer"""
        embed = guilded.Embed(
            title=title,
            description=desc,
            color=color
        )
        embed.set_footer(text=f"UTC: {self._get_utc_time()}")
        return embed

    @commands.command(name="start")
    async def start_civilization(self, ctx, *, name: str = None):
        """Found a new civilization"""
        try:
            # Validate input
            if not name:
                await ctx.send(
                    embed=self._format_embed(
                        "❌ Missing Name",
                        "ATTENTION PRESIDENT! You must provide a name: `.start <name>`",
                        color=0xFF0000
                    )
                )
                return

            user_id = str(ctx.author.id)
            
            # Check for existing civilization
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
                special_message = "🖋️ The pen will never forget your work. (+5% luck)"
            elif "pen" in name_lower:
                name_bonuses["diplomacy_bonus"] = 5
                special_message = "🖋️ The pen is mightier than the sword. (+5% diplomacy)"

            # Random HyperItem (5% chance)
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
                    "ATTENTION PRESIDENT! Failed to create civilization. Please try again.",
                    color=0xFF0000
                )
            )

    @commands.command(name="ideology")
    async def choose_ideology(self, ctx, ideology_type: str = None):
        """Choose civilization ideology"""
        try:
            if ideology_type is None:
                # Show ideology list
                descriptions = {
                    "fascism": "+25% soldier training, -15% diplomacy, -10% luck",
                    "democracy": "+20% happiness, +10% trade, -15% training",
                    "communism": "+10% productivity, -10% tech speed",
                    "socialism": "+15% happiness, +20% productivity, -10% military",
                    "theocracy": "+15% propaganda, +5% happiness, -10% tech",
                    "anarchy": "2x random events, 0 upkeep, -20% spy success",
                    "monarchy": "+20% diplomacy, +25% tax, -10% productivity",
                    "terrorism": "+40% sabotage, +30% spy, -40% happiness",
                    "pacifist": "+35% happiness, +25% growth, -60% combat"
                }

                embed = self._format_embed(
                    "🏛️ Choose Your Ideology",
                    "Select your government type:"
                )

                for name, desc in descriptions.items():
                    embed.add_field(
                        name=name.capitalize(),
                        value=desc,
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
            desc_map = {
                "fascism": "⚔️ Strong military, poor diplomacy",
                "democracy": "🗳️ Happy population and trade",
                "communism": "🏭 Increased productivity",
                "socialism": "✊ Balanced growth and welfare",
                "theocracy": "⛪ Divine authority and propaganda",
                "anarchy": "💥 Chaotic but efficient",
                "monarchy": "👑 Diplomatic prestige and taxes",
                "terrorism": "💣 Sabotage-focused",
                "pacifist": "🕊️ Peace and prosperity"
            }

            embed = self._format_embed(
                f"🏛️ Ideology Set: {choice.capitalize()}",
                desc_map.get(choice, "")
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

    @commands.command(name="warhelp")
    async def warbot_help(self, ctx, category: str = None):
        """Display help manual"""
        try:
            embed = self._format_embed(
                "🤖 WARBOT MANUAL",
                "Use `.warhelp <category>` for details. Example: `.warhelp Military`"
            )

            embed.add_field(
                name="🏛️ Basic Commands",
                value=(
                    "`.start <name>` - Found civilization\n"
                    "`.status` - View status\n"
                    "`.ideology <type>` - Set government\n"
                    "`@WarBot <question>` - Ask NationGPT"
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
                    "Powerful special items:\n"
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

            embed.set_footer(text="DROP AND GIVE ME 50 WHILE READING, PRESIDENT!")
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
    await bot.add_cog(BasicCommands(bot))
