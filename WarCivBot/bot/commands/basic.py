"""
BasicCommands Cog for WarBot

Provides:
- NationGPT mention responder (on_message)
- .start to found a civilization
- .ideology to choose ideology
- .status to display civ status
- .warhelp to display help

Dependencies:
- bot.db (Database instance)
- bot.civ_manager (CivilizationManager instance)
- bot.utils: format_number, get_ascii_art, create_embed
"""
import os
import random
import logging
from collections import defaultdict, deque
from datetime import datetime, timedelta

import aiohttp
import guilded
from guilded.ext import commands

from bot.utils import format_number, get_ascii_art, create_embed

logger = logging.getLogger(__name__)

# Conversation / AI constants
MAX_CONVERSATION_HISTORY = 5         # keep last N exchanges (user+assistant counts as 2 entries)
CONVERSATION_TIMEOUT = 1800          # seconds (30 minutes)
DEFAULT_AI_MODEL = "deepseek/deepseek-chat"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
AI_REQUEST_TIMEOUT = 30              # seconds

# Helper constants (used in messages)
DEFAULT_IDEOLOGIES = [
    "fascism", "democracy", "communism", "socialism", "theocracy",
    "anarchy", "monarchy", "terrorism", "pacifist"
]


class BasicCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = getattr(bot, "db", None)
        self.civ_manager = getattr(bot, "civ_manager", None)

        # AI / NationGPT setup
        self.openrouter_key = os.getenv("OPENROUTER")
        if not self.openrouter_key:
            logger.warning("OPENROUTER environment variable not set. NationGPT will be disabled until configured.")
        self.current_model = os.getenv("AI_MODEL", DEFAULT_AI_MODEL)
        self.rate_limited = False
        self.model_switch_time = None

        # Conversation tracking: user_id -> deque of messages
        # Each entry is dict { "is_user": bool, "content": str, "timestamp": datetime }
        self.conversations = defaultdict(deque)
        self.last_interaction = {}  # user_id -> datetime

    # ------------------------
    # Conversation utilities
    # ------------------------
    def _get_conversation_history(self, user_id: str):
        """Return list of messages formatted for the AI API from stored history."""
        history = []
        for msg in self.conversations.get(user_id, []):
            history.append({
                "role": "user" if msg["is_user"] else "assistant",
                "content": msg["content"]
            })
        return history

    def _update_conversation(self, user_id: str, is_user: bool, content: str):
        """Append a message to the conversation history and perform cleanup."""
        now = datetime.utcnow()
        self.last_interaction[user_id] = now
        self.conversations[user_id].append({
            "is_user": is_user,
            "content": content,
            "timestamp": now
        })

        # Trim to keep roughly MAX_CONVERSATION_HISTORY exchanges (user+assistant = 2)
        while len(self.conversations[user_id]) > MAX_CONVERSATION_HISTORY * 2:
            self.conversations[user_id].popleft()

        # Expire stale conversations
        expired = []
        for uid, last_time in list(self.last_interaction.items()):
            if (now - last_time).total_seconds() > CONVERSATION_TIMEOUT:
                expired.append(uid)
        for uid in expired:
            self.conversations.pop(uid, None)
            self.last_interaction.pop(uid, None)

    def _now_utc_str(self):
        """Return current UTC timestamp string formatted for prompts/footers."""
        return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    # ------------------------
    # NationGPT: mention handler
    # ------------------------
    @commands.Cog.listener()
    async def on_message(self, message):
        """
        Respond to direct mentions or replies to the bot using the AI assistant.
        Only handles plain text mentions; command-prefixed interactions remain handled by commands.
        """
        try:
            # Ignore bot messages
            if getattr(message.author, "bot", False):
                return

            # Identify user and raw content
            user_id = str(message.author.id)
            content = (message.content or "").strip()

            # Determine if message is a reply to a bot message
            is_reply = False
            try:
                if getattr(message, "reply_to", None):
                    replied_msg = await message.channel.fetch_message(message.reply_to.id)
                    if replied_msg and getattr(replied_msg.author, "id", None) == getattr(self.bot.user, "id", None):
                        is_reply = True
            except Exception:
                # fetching message could fail (permissions, platform differences); ignore
                pass

            # Check whether the bot was mentioned
            mentions = getattr(message, "mentions", []) or []
            bot_mentioned = any(getattr(m, "id", None) == getattr(self.bot.user, "id", None) for m in mentions)

            # Only respond when directly mentioned or when user replies to bot
            if not (bot_mentioned or is_reply):
                return

            # Remove mention text if present (keep only user message content)
            if bot_mentioned:
                bot_mention_text = f"<@{getattr(self.bot.user, 'id', '')}>"
                content = content.replace(bot_mention_text, "").strip()

            # If new standalone mention (not a reply) reset conversation
            if bot_mentioned and not is_reply:
                self.conversations[user_id] = deque()
                self.last_interaction[user_id] = datetime.utcnow()

            # If there's no content after removing mention, send a helpful embed
            if not content:
                if bot_mentioned:
                    await message.reply(embed=create_embed(
                        "🤖 ATTENTION PRESIDENT!",
                        "DROP DOWN AND GIVE ME 50 PUSH UPS RIGHT NOW!\n\n"
                        "While you're doing those push-ups, here's what I can help you with:\n"
                        "- Founding your civilization (`.start <name>`)\n"
                        "- Viewing status (`.status`)\n"
                        "- Military commands and strategy (`.warhelp`)\n"
                        "- Ideology selection (`.ideology <type>`)\n\n"
                        "What's the mission, President?",
                        guilded.Color.blue()
                    ))
                    # store a small assistant prompt in conversation
                    self._update_conversation(user_id, False, "DROP DOWN AND GIVE ME 50, PRESIDENT! How can I assist with your nation today?")
                return

            # Build civ context if available
            civ = None
            try:
                civ = self.civ_manager.get_civilization(user_id) if self.civ_manager else None
            except Exception:
                civ = None

            civ_status = ""
            if civ:
                try:
                    civ_status = (
                        f"YOUR NATION STATUS, PRESIDENT:\n"
                        f"Nation: {civ.get('name','Unknown')} (Ideology: {civ.get('ideology','none')})\n"
                        f"Resources: 🪙{format_number(civ['resources'].get('gold',0))} "
                        f"🌾{format_number(civ['resources'].get('food',0))} "
                        f"🪨{format_number(civ['resources'].get('stone',0))} "
                        f"🪵{format_number(civ['resources'].get('wood',0))}\n"
                        f"Military: ⚔️{format_number(civ['military'].get('soldiers',0))} "
                        f"🕵️{format_number(civ['military'].get('spies',0))}\n"
                    )
                except Exception:
                    civ_status = ""

            # Compose system prompt for AI
            system_prompt = (
                "You are NationGPT, a military sergeant AI assistant for the WarBot civilization game.\n"
                "Always address the user as 'PRESIDENT' and adopt a tough military sergeant persona.\n"
                "Include motivational short orders such as 'DROP DOWN AND GIVE ME 50 PUSH UPS RN!' and 'WHAT'S THE MISSION, PRESIDENT?'\n"
                f"Current Date and Time (UTC): {self._now_utc_str()}\n\n"
            )
            if civ_status:
                system_prompt += civ_status + "\n"

            system_prompt += (
                "Game features summary: resources (gold, food, stone, wood), military (soldiers, spies, tech_level), "
                "population (citizens, happiness, hunger), territory (land_size), ideologies: "
                + ", ".join(DEFAULT_IDEOLOGIES)
                + "\n\n"
                "Tone & behavior requirements:\n"
                "- Be strategic and concise.\n"
                "- Answer questions about game mechanics, strategy, and specific commands.\n"
                "- Give clear step-by-step recommendations when asked.\n"
                "- Keep the 'sergeant' personality but avoid insulting the user.\n"
                "- If the AI can't access real-time game state, say so and suggest `.status` or `.warhelp`.\n"
            )

            # Build messages payload for AI (system + history + user)
            messages = [{"role": "system", "content": system_prompt}]
            history = self._get_conversation_history(user_id)
            if history:
                messages.extend(history)
            messages.append({"role": "user", "content": content})

            # Request AI response
            try:
                response_text = await self.generate_ai_response(messages)
                # Ensure response is a non-empty string
                if not response_text:
                    response_text = ("ATTENTION PRESIDENT! NationGPT could not produce a response right now. "
                                     "Try again in a moment or use `.warhelp`.")
                # Send reply and store conversation
                await message.reply(response_text)
                self._update_conversation(user_id, True, content)
                self._update_conversation(user_id, False, response_text)
            except Exception as e:
                logger.exception("Error while generating/sending AI response")
                await message.reply(
                    "ATTENTION PRESIDENT! Communication systems are temporarily down.\n"
                    "DROP DOWN AND GIVE ME 20 WHILE WE FIX IT!\n\n"
                    "In the meantime, you can use:\n"
                    "• `.status` - view your nation\n"
                    "• `.warhelp` - view command list"
                )

        except Exception as e:
            logger.exception("Unexpected error in on_message listener")

    # ------------------------
    # AI / OpenRouter interaction
    # ------------------------
    async def generate_ai_response(self, messages):
        """
        Call OpenRouter to get a chat completion.
        Returns response content string on success or a friendly fallback message on failure.
        """
        # Basic check
        if not self.openrouter_key:
            return (
                "ATTENTION PRESIDENT! NationGPT is not configured. The administrator must set the OPENROUTER API key."
            )

        # If rate-limited and within cooldown, short-circuit
        if self.rate_limited and self.model_switch_time:
            if datetime.utcnow() < self.model_switch_time:
                logger.debug("AI rate limited and still cooling down.")
                # fallback text while cooling down
                return ("ATTENTION PRESIDENT! NationGPT is temporarily unavailable due to rate limits. "
                        "Try again in a bit or use `.warhelp` for command help.")
            else:
                # reset
                self.rate_limited = False
                self.model_switch_time = None

        headers = {
            "Authorization": f"Bearer {self.openrouter_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/unkownPen/WarBot",
            "X-Title": "WarBot"
        }

        payload = {
            "model": self.current_model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 500,
            "top_p": 0.9,
            "frequency_penalty": 0.2,
            "presence_penalty": 0.2
        }

        try:
            timeout = aiohttp.ClientTimeout(total=AI_REQUEST_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(OPENROUTER_API_URL, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        # robust extraction
                        try:
                            return data["choices"][0]["message"]["content"]
                        except Exception:
                            # fallback to some possible alternative keys
                            return data.get("choices", [{}])[0].get("text", "") or data.get("result", "")
                    elif resp.status == 429:
                        # rate limited: set flag and try fallback model once
                        self.rate_limited = True
                        self.model_switch_time = datetime.utcnow() + timedelta(hours=1)
                        logger.warning("OpenRouter rate limit encountered. Attempting fallback model.")
                        # switch to fallback model short-term
                        payload["model"] = "moonshotai/kimi-k2:free"
                        async with session.post(OPENROUTER_API_URL, headers=headers, json=payload) as fallback_resp:
                            if fallback_resp.status == 200:
                                fallback_data = await fallback_resp.json()
                                try:
                                    return fallback_data["choices"][0]["message"]["content"]
                                except Exception:
                                    return fallback_data.get("choices", [{}])[0].get("text", "")
                            else:
                                raise RuntimeError(f"Fallback model failed with status {fallback_resp.status}")
                    else:
                        text = await resp.text()
                        raise RuntimeError(f"OpenRouter API error {resp.status}: {text}")
        except Exception as e:
            logger.exception("Error calling OpenRouter API")
            return (
                "ATTENTION PRESIDENT! My communication systems are temporarily down.\n"
                "DROP DOWN AND GIVE ME 20 WHILE WE FIX IT!\n\n"
                "You can still use `.status` and `.warhelp` while we resolve this."
            )

    # ------------------------
    # Commands: start, ideology, status, warhelp
    # ------------------------
    @commands.command(name="start")
    async def start_civilization(self, ctx, *, name: str = None):
        """Start a new civilization with cinematic intro and possible bonuses"""
        try:
            if not name:
                await ctx.send("❌ ATTENTION PRESIDENT! You must provide a name for your civilization: `.start <name>`")
                return

            user_id = str(ctx.author.id)

            # Check existing civ
            existing = None
            try:
                existing = self.civ_manager.get_civilization(user_id) if self.civ_manager else None
            except Exception:
                existing = None

            if existing:
                await ctx.send("❌ PRESIDENT! You already command a civilization! Use `.status` to view it.")
                return

            # Cinematic ASCII
            intro = get_ascii_art("civilization_start") or "🏛️ Your civilization rises..."

            # Random founding event selection
            founding_events = [
                ("🏛️ **Golden Dawn**: Your people discovered ancient gold deposits!", {"gold": 200}),
                ("🌾 **Fertile Lands**: Blessed with rich soil for farming!", {"food": 300}),
                ("🏗️ **Master Builders**: Your citizens are natural architects!", {"stone": 150, "wood": 150}),
                ("👥 **Population Boom**: Word of your leadership spreads!", {"citizens": 50}),
                ("⚡ **Lightning Strike**: A divine sign brings good fortune!", {"gold": 100, "happiness": 20})
            ]
            event_text, bonus_resources = random.choice(founding_events)

            # Name-based bonuses
            name_bonuses = {}
            special_message = ""
            if "ink" in name.lower():
                name_bonuses["luck_bonus"] = 5
                special_message = "🖋️ The pen will never forget your work. (+5% luck)"
            elif "pen" in name.lower():
                name_bonuses["diplomacy_bonus"] = 5
                special_message = "🖋️ The pen is mightier than the sword. (+5% diplomacy success)"

            # 5% chance for hyper item
            hyper_item = None
            if random.random() < 0.05:
                hyper_item = random.choice(["Lucky Charm", "Propaganda Kit", "Mercenary Contract"])

            # Create civ via manager
            created = False
            try:
                created = self.civ_manager.create_civilization(user_id, name, bonus_resources, name_bonuses, hyper_item)
            except Exception:
                created = False

            if not created:
                await ctx.send("❌ ATTENTION PRESIDENT! There was an error creating your civilization. Please try again later.")
                return

            # Assemble embed
            embed = guilded.Embed(
                title=f"🏛️ The Birth of {name}",
                description=f"{intro}\n\n{event_text}\n{special_message}",
                color=0x00FF00
            )
            if hyper_item:
                embed.add_field(name="🎁 Strategic Asset Discovered!", value=f"Your scouts found a **{hyper_item}**!", inline=False)

            embed.add_field(
                name="📋 Next Orders",
                value="ATTENTION PRESIDENT! Choose your government ideology with `.ideology <type>`\n"
                      f"Options: {', '.join(DEFAULT_IDEOLOGIES)}",
                inline=False
            )
            await ctx.send(embed=embed)

        except Exception as e:
            logger.exception("Error in start command")
            await ctx.send("❌ ATTENTION PRESIDENT! An error occurred while founding your civilization.")

    @commands.command(name="ideology")
    async def choose_ideology(self, ctx, ideology_type: str = None):
        """Show ideology choices or set the player's ideology."""
        try:
            if ideology_type is None:
                # Show available ideologies and short descriptions
                descriptions = {
                    "fascism": "+25% soldier training speed, -15% diplomacy success, -10% luck",
                    "democracy": "+20% happiness, +10% trade profit, -15% soldier training",
                    "communism": "+10% citizen productivity, -10% tech speed",
                    "socialism": "+15% happiness, +20% citizen productivity, -10% military efficiency",
                    "theocracy": "+15% propaganda success, +5% happiness, -10% tech speed",
                    "anarchy": "2x random events, 0 soldier upkeep, -20% spy success",
                    "monarchy": "+20% diplomacy success, +25% tax efficiency, -10% citizen productivity",
                    "terrorism": "+40% sabotage success, +30% spy success, -40% happiness",
                    "pacifist": "+35% happiness, +25% population growth, +20% trade profit, -60% combat strength"
                }
                embed = guilded.Embed(title="🏛️ Choose Your Ideology", description="Select one for your civilization:", color=0x0099FF)
                for k, v in descriptions.items():
                    embed.add_field(name=k.capitalize(), value=v, inline=False)
                embed.add_field(name="Usage", value="`.ideology <type>`", inline=False)
                await ctx.send(embed=embed)
                return

            user_id = str(ctx.author.id)
            civ = self.civ_manager.get_civilization(user_id) if self.civ_manager else None
            if not civ:
                await ctx.send("❌ PRESIDENT! You must found a civilization first. Use `.start <name>`.")
                return

            if civ.get("ideology"):
                await ctx.send("❌ PRESIDENT! You have already chosen an ideology and cannot change it.")
                return

            choice = ideology_type.lower()
            if choice not in DEFAULT_IDEOLOGIES:
                await ctx.send(f"❌ INVALID IDEOLOGY. Choose from: {', '.join(DEFAULT_IDEOLOGIES)}")
                return

            ok = self.civ_manager.set_ideology(user_id, choice)
            if not ok:
                await ctx.send("❌ ATTENTION PRESIDENT! Failed to set ideology. Try again.")
                return

            desc_map = {
                "fascism": "⚔️ Fascism — Strong military focus, poor diplomacy.",
                "democracy": "🗳️ Democracy — Happy population and better trade.",
                "communism": "🏭 Communism — Increased productivity for citizens.",
                "socialism": "✊ Socialism — Balanced growth and welfare.",
                "theocracy": "⛪ Theocracy — Divine authority and propaganda.",
                "anarchy": "💥 Anarchy — Chaotic but low upkeep.",
                "monarchy": "👑 Monarchy — Diplomatic prestige and taxes.",
                "terrorism": "💣 Terrorism — Sabotage-focused (dangerous).",
                "pacifist": "🕊️ Pacifist — Prosperous peace-oriented civ."
            }

            embed = guilded.Embed(
                title=f"🏛️ Ideology Chosen: {choice.capitalize()}",
                description=desc_map.get(choice, ""),
                color=0x00FF00
            )
            embed.add_field(name="Orders", value="DROP DOWN AND GIVE ME 50, PRESIDENT! Use `.status` to view your nation.", inline=False)
            await ctx.send(embed=embed)

        except Exception as e:
            logger.exception("Error in ideology command")
            await ctx.send("❌ ATTENTION PRESIDENT! An error occurred while setting your ideology.")

    @commands.command(name="status")
    async def civilization_status(self, ctx):
        """Show a detailed status report for the caller's civilization."""
        try:
            user_id = str(ctx.author.id)
            civ = self.civ_manager.get_civilization(user_id) if self.civ_manager else None
            if not civ:
                await ctx.send("❌ ATTENTION PRESIDENT! You don't have a civilization yet. Use `.start <name>` to found one.")
                return

            # Build embed
            ide = civ.get("ideology") or "None"
            embed = guilded.Embed(
                title=f"🏛️ Status Report: {civ.get('name','Unknown')}",
                description=f"**Commander-in-Chief:** {ctx.author.display_name}\n**Ideology:** {ide.capitalize()}",
                color=0x0099FF
            )

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
                    f"🔬 Tech Level: {mil.get('tech_level',0)}"
                ),
                inline=True
            )

            terr = civ.get("territory", {})
            hyper_items = civ.get("hyper_items", [])
            embed.add_field(
                name="🗺️ Territory & Items",
                value=(
                    f"🏞️ Land Size: {format_number(terr.get('land_size',0))} km²\n"
                    f"🎁 HyperItems: {len(hyper_items)}\n"
                    + ("\n".join(f"• {h}" for h in hyper_items[:5]) + ("..." if len(hyper_items) > 5 else ""))
                ),
                inline=True
            )

            embed.set_footer(text="PRESIDENT! Your nation awaits your next command!")
            await ctx.send(embed=embed)

        except Exception as e:
            logger.exception("Error in status command")
            await ctx.send("❌ ATTENTION PRESIDENT! An error occurred while retrieving your status.")

    @commands.command(name="warhelp")
    async def warbot_help_command(self, ctx, category: str = None):
        """Display a comprehensive help/manual embed for WarBot commands."""
        try:
            embed = guilded.Embed(
                title="🤖 WARBOT COMMAND MANUAL",
                description="Use `.warhelp <category>` for category details. Example: `.warhelp Military`",
                color=0x1E90FF
            )
            # Compose fields (concise)
            embed.add_field(
                name="🏛️ Basic",
                value="`.start <name>` — found a nation\n`.status` — view your nation\n`.ideology <type>` — choose government\n`@WarBot <question>` — ask NationGPT",
                inline=False
            )
            embed.add_field(
                name="💰 Economy",
                value="`.gather`, `.farm`, `.mine`, `.harvest`, `.trade`, `.tax`, `.lottery`",
                inline=False
            )
            embed.add_field(
                name="⚔️ Military",
                value="`.train`, `.declare`, `.attack`, `.siege`, `.stealthbattle`",
                inline=False
            )
            embed.add_field(
                name="🎁 HyperItems",
                value="Powerful one-time or passive items such as Lucky Charm, Nuclear Warhead, Propaganda Kit",
                inline=False
            )
            embed.add_field(
                name="🤝 Diplomacy",
                value="`.ally`, `.break`, `.coalition`, `.mail`, `.send`",
                inline=False
            )
            embed.add_field(
                name="📜 Tips",
                value="Maintain happiness, diversify resources, and use HyperItems strategically.",
                inline=False
            )
            embed.set_footer(text="DROP DOWN AND GIVE ME 50 WHILE YOU READ THIS, PRESIDENT!")
            await ctx.send(embed=embed)
        except Exception as e:
            logger.exception("Error in warhelp command")
            await ctx.send("❌ ATTENTION PRESIDENT! An error occurred while showing help.")

    # ------------------------
    # Cog setup hook
    # ------------------------
async def setup(bot):
    await bot.add_cog(BasicCommands(bot))
