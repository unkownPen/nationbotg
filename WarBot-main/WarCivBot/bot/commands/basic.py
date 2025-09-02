import random
import guilded
import os
import aiohttp
import asyncio
import logging
from datetime import datetime, timedelta
from collections import defaultdict, deque
from guilded.ext import commands
from bot.utils import format_number, get_ascii_art, create_embed

logger = logging.getLogger(__name__)

# Constants
MAX_CONVERSATION_HISTORY = 5  # Keep last 5 exchanges per user
CONVERSATION_TIMEOUT = 1800  # 30 minutes in seconds

class BasicCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.civ_manager = bot.civ_manager
        self.openrouter_key = os.getenv('OPENROUTER')
        self.openai_key = os.getenv('OPENAI_API_KEY')  # fallback option
        self.current_model = "deepseek/deepseek-chat"
        self.model_switch_time = None
        self.rate_limited = False
        
        # Conversation tracking
        self.conversations = defaultdict(deque)  # user_id: deque of messages
        self.last_interaction = {}  # user_id: timestamp

    def _get_conversation_history(self, user_id):
        """Get formatted conversation history for a user"""
        history = []
        for msg in self.conversations[user_id]:
            history.append({
                "role": "user" if msg['is_user'] else "assistant",
                "content": msg['content']
            })
        return history

    def _update_conversation(self, user_id, is_user, content):
        """Update conversation history for a user"""
        now = datetime.now()
        self.last_interaction[user_id] = now
        
        # Add new message to history
        self.conversations[user_id].append({
            "is_user": is_user,
            "content": content,
            "timestamp": now
        })
        
        # Trim old messages if needed
        while len(self.conversations[user_id]) > MAX_CONVERSATION_HISTORY * 2:
            self.conversations[user_id].popleft()
            
        # Clean up expired conversations
        expired_users = []
        for uid, last_time in list(self.last_interaction.items()):
            if (now - last_time).total_seconds() > CONVERSATION_TIMEOUT:
                expired_users.append(uid)
                
        for uid in expired_users:
            try:
                del self.conversations[uid]
                del self.last_interaction[uid]
            except KeyError:
                pass

    @commands.Cog.listener()
    async def on_message(self, message):
        """Respond to mentions with AI assistance"""
        # Skip if message is from bot
        try:
            if message.author.bot:
                return
        except Exception:
            # If message object doesn't have .author or .bot attribute as expected, bail
            return
            
        user_id = str(message.author.id)
        content = (message.content or "").strip()
        
        # Check if this is a reply to the bot
        is_reply = False
        if getattr(message, "replied_to", None):
            try:
                # guilded's fetch may differ; attempt to get the replied_to author id safely
                replied = message.replied_to
                if getattr(replied, "author", None) and getattr(replied.author, "id", None) == self.bot.user.id:
                    is_reply = True
                else:
                    # Best-effort fetch if possible
                    try:
                        replied_msg = await message.channel.fetch_message(message.replied_to.id)
                        if replied_msg and getattr(replied_msg.author, "id", None) == self.bot.user.id:
                            is_reply = True
                    except Exception:
                        pass
            except Exception:
                pass
        
        # Check if our bot is mentioned
        bot_mentioned = False
        try:
            mentions = getattr(message, "mentions", []) or []
            bot_mentioned = any((getattr(u, "id", None) == self.bot.user.id) for u in mentions)
        except Exception:
            bot_mentioned = False
        
        # Only respond to direct mentions or replies to our messages
        if not (bot_mentioned or is_reply):
            return
            
        # Handle mentions
        if bot_mentioned:
            # Remove mention text if present
            try:
                content = content.replace(f'<@{self.bot.user.id}>', '').strip()
            except Exception:
                pass
            
        # Reset conversation if it's a new mention (not a reply)
        if bot_mentioned and not is_reply:
            self.conversations[user_id] = deque()
            self.last_interaction[user_id] = datetime.now()
            
        # Handle empty content
        if not content:
            if bot_mentioned:
                # Default response for just a mention
                try:
                    await message.reply(embed=create_embed(
                        "🤖 NationBot Assistant",
                        "Hello! I'm here to help you with NationBot. Ask me about:\n"
                        "- Starting your civilization (`.start`)\n"
                        "- Managing resources (`.status`)\n"
                        "- Military commands (`.warhelp`)\n"
                        "- Ideologies and strategies\n\n"
                        "Try asking: 'How do I declare war?' or 'What does fascism do?'",
                        guilded.Color.blue()
                    ))
                    self._update_conversation(user_id, False, "Hello! How can I assist with NationBot today?")
                except Exception:
                    logger.exception("Failed to send default mention reply")
            return
            
        # Get user's civilization status for context
        civ = None
        try:
            civ = self.civ_manager.get_civilization(user_id)
        except Exception:
            logger.exception("Failed to fetch civ for context")
            civ = None

        civ_status = ""
        if civ:
            try:
                civ_status = (
                    f"Player's Civilization: {civ['name']} (Ideology: {civ.get('ideology', 'none')})\n"
                    f"Resources: 🪙{format_number(civ['resources'].get('gold',0))} "
                    f"🌾{format_number(civ['resources'].get('food',0))} "
                    f"🪨{format_number(civ['resources'].get('stone',0))} "
                    f"🪵{format_number(civ['resources'].get('wood',0))}\n"
                    f"Military: ⚔️{format_number(civ['military'].get('soldiers',0))} "
                    f"🕵️{format_number(civ['military'].get('spies',0))}\n"
                )
            except Exception:
                civ_status = ""
        
        # Prepare system prompt
        system_prompt = f"""You are NationBot, an AI assistant for a nation simulation game. 
Players build civilizations, manage resources, wage wars, and form alliances. 
Your role is to help players understand game mechanics and strategies.

{civ_status}
Key Game Concepts:
- Resources: gold, food, stone, wood
- Military: soldiers, spies, tech_level
- Population: citizens, happiness, hunger
- Territory: land_size
- Ideologies: fascism, democracy, communism, theocracy, anarchy, destruction, pacifist

BasicCommands:
  ideology      Choose your civilization's government ideology
  start         Start a new civilization with a cinematic intro
  status        View your civilization status
  warhelp       Display help information

EconomyCommands: (short)
  extrawork, extrastore, extrainventory, extragamble, extracards, slots, blackjack, give, setbalance

MilitaryCommands & Diplomacy:
  Use `.warhelp Military` or `.warhelp Diplomacy` to see full lists.

You are helpful, encouraging, and strategic. Keep responses concise and focused on gameplay.
If asked about non-game topics, politely decline. Use brief Discord-style formatting.
Address the player as 'President' and keep a confident, commanding tone.
When appropriate, include tactical suggestions and short examples.
"""
        
        # Generate AI response with conversation history
        try:
            # Build messages with conversation history
            messages = [{"role": "system", "content": system_prompt}]
            
            # Add conversation history if available
            if user_id in self.conversations and self.conversations[user_id]:
                history = self._get_conversation_history(user_id)
                messages.extend(history)
            
            # Add current user message
            messages.append({"role": "user", "content": content})
            
            # Generate response
            response = await self.generate_ai_response(messages)
            
            # Send response and update conversation
            try:
                await message.reply(response)
            except Exception:
                # fallback to sending as plain text if reply fails
                try:
                    await message.channel.send(response)
                except Exception:
                    logger.exception("Failed to send AI response to channel")
            self._update_conversation(user_id, True, content)
            self._update_conversation(user_id, False, response)
        except Exception as e:
            logger.error(f"AI response error: {e}", exc_info=True)
            try:
                await message.reply("I'm having trouble thinking right now. Please try again later!")
            except Exception:
                pass

    async def generate_ai_response(self, messages):
        """Generate response using OpenRouter API or fallback to OpenAI (if configured)"""
        # PRIORITY: OpenRouter (OPENROUTER) -> OpenAI (OPENAI_API_KEY) -> local fallback message
        # messages should be a list of dicts with 'role' and 'content'
        headers = {}
        # Try OpenRouter first
        if self.openrouter_key:
            headers = {
                "Authorization": f"Bearer {self.openrouter_key}",
                "Content-Type": "application/json"
            }
            # Check model switch due to rate limiting
            if self.rate_limited and self.model_switch_time and datetime.now() < self.model_switch_time:
                model = "moonshotai/kimi-k2:free"
            else:
                model = self.current_model
                self.rate_limited = False

            payload = {
                "model": model,
                "messages": messages,
                "max_tokens": 500
            }

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post("https://openrouter.ai/api/v1/chat/completions",
                                            headers=headers, json=payload, timeout=60) as response:
                        text = await response.text()
                        if response.status == 200:
                            data = await response.json()
                            # OpenRouter follows a similar structure
                            return data['choices'][0]['message']['content']
                        elif response.status == 429:
                            # Rate limited: switch to fallback model for 24 hours
                            self.rate_limited = True
                            self.model_switch_time = datetime.now() + timedelta(hours=24)
                            logger.warning("OpenRouter rate limited; switching to fallback model for 24 hours")
                            # Retry with fallback model once
                            payload["model"] = "moonshotai/kimi-k2:free"
                            async with session.post("https://openrouter.ai/api/v1/chat/completions",
                                                    headers=headers, json=payload, timeout=60) as fallback_response:
                                if fallback_response.status == 200:
                                    data = await fallback_response.json()
                                    return data['choices'][0]['message']['content']
                                else:
                                    errtxt = await fallback_response.text()
                                    raise Exception(f"Fallback model failed: {fallback_response.status} - {errtxt}")
                        else:
                            raise Exception(f"OpenRouter API error {response.status}: {text}")
            except Exception as e:
                logger.exception("OpenRouter failed, will try OpenAI if available")
                # Fall through to OpenAI fallback
        # Try OpenAI if available
        if self.openai_key:
            headers = {
                "Authorization": f"Bearer {self.openai_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "gpt-3.5-turbo",
                "messages": messages,
                "max_tokens": 500,
                "temperature": 0.7
            }
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post("https://api.openai.com/v1/chat/completions",
                                            headers=headers, json=payload, timeout=60) as response:
                        text = await response.text()
                        if response.status == 200:
                            data = await response.json()
                            return data['choices'][0]['message']['content']
                        else:
                            raise Exception(f"OpenAI API error {response.status}: {text}")
            except Exception:
                logger.exception("OpenAI request failed")
        # No API keys configured or all attempts failed
        logger.error("No configured AI provider available or all providers failed")
        return ("⚠️ AI is unavailable right now. Please make sure the bot has an API key set "
                "via the OPENROUTER or OPENAI_API_KEY environment variable, and try again later.")

    @commands.command(name='start')
    async def start_civilization(self, ctx, civ_name: str = None):
        """Start a new civilization with a cinematic intro"""
        if not civ_name:
            await ctx.send("❌ Please provide a civilization name: `.start <civilization_name>`")
            return
            
        user_id = str(ctx.author.id)
        
        # Check if user already has a civilization
        if self.civ_manager.get_civilization(user_id):
            await ctx.send("❌ You already have a civilization! Use `.status` to view it.")
            return
            
        # Show cinematic intro
        intro_art = get_ascii_art("civilization_start")
        
        # Random founding event
        founding_events = [
            ("🏛️ **Golden Dawn**: Your people discovered ancient gold deposits!", {"gold": 200}),
            ("🌾 **Fertile Lands**: Blessed with rich soil for farming!", {"food": 300}),
            ("🏗️ **Master Builders**: Your citizens are natural architects!", {"stone": 150, "wood": 150}),
            ("👥 **Population Boom**: Word of your great leadership spreads!", {"population": 50}),
            ("⚡ **Lightning Strike**: A divine sign brings good fortune!", {"gold": 100, "happiness": 20})
        ]
        
        event_text, bonus_resources = random.choice(founding_events)
        
        # Special name bonuses
        name_bonuses = {}
        special_message = ""
        if "ink" in civ_name.lower():
            name_bonuses["luck_bonus"] = 5
            special_message = "🖋️ *The pen will never forget your work.* (+5% luck)"
        elif "pen" in civ_name.lower():
            name_bonuses["diplomacy_bonus"] = 5
            special_message = "🖋️ *The pen is mightier than the sword.* (+5% diplomacy success)"
            
        # 5% chance for random HyperItem
        hyper_item = None
        if random.random() < 0.05:
            common_items = ["Lucky Charm", "Propaganda Kit", "Mercenary Contract"]
            hyper_item = random.choice(common_items)
            
        # Create civilization
        self.civ_manager.create_civilization(user_id, civ_name, bonus_resources, name_bonuses, hyper_item)
        
        # Send intro message
        embed = guilded.Embed(
            title=f"🏛️ The Founding of {civ_name}",
            description=f"{intro_art}\n\n{event_text}\n{special_message}",
            color=0x00ff00
        )
        
        if hyper_item:
            embed.add_field(
                name="🎁 Rare Discovery!",
                value=f"Your scouts found a **{hyper_item}**! This powerful item unlocks special abilities.",
                inline=False
            )
            
        embed.add_field(
            name="📋 Next Step",
            value="Choose your government ideology with `.ideology <type>`\nOptions: fascism, democracy, communism, theocracy, anarchy, destruction, pacifist",
            inline=False
        )
        
        await ctx.send(embed=embed)

    @commands.command(name='ideology')
    async def choose_ideology(self, ctx, ideology_type: str = None):
        """Choose your civilization's government ideology"""
        if not ideology_type:
            ideologies = {
                "fascism": "+25% soldier training speed, -15% diplomacy success, -10% luck",
                "democracy": "+20% happiness, +10% trade profit, slower soldier training (-15%)",
                "communism": "Equal resource distribution (+10% citizen productivity), -10% tech speed",
                "theocracy": "+15% propaganda success, +5% happiness, -10% tech speed",
                "anarchy": "Random events happen twice as often, 0 soldier upkeep, -20% spy success",
                # NEW IDEOLOGIES
                "destruction": "+35% combat strength, +40% soldier training, -25% resources, -30% happiness, -50% diplomacy",
                "pacifist": "+35% happiness, +25% population growth, +20% trade profit, -60% soldier training, -40% combat, +25% diplomacy"
            }
            
            embed = guilded.Embed(title="🏛️ Government Ideologies", color=0x0099ff)
            for name, description in ideologies.items():
                embed.add_field(name=name.capitalize(), value=description, inline=False)
            embed.add_field(name="Usage", value="`.ideology <type>`", inline=False)
            
            await ctx.send(embed=embed)
            return
            
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return
            
        if civ.get('ideology'):
            await ctx.send("❌ You have already chosen an ideology! It cannot be changed.")
            return
            
        ideology_type = ideology_type.lower()
        # UPDATED valid ideologies list
        valid_ideologies = ["fascism", "democracy", "communism", "theocracy", "anarchy", "destruction", "pacifist"]
        
        if ideology_type not in valid_ideologies:
            await ctx.send(f"❌ Invalid ideology! Choose from: {', '.join(valid_ideologies)}")
            return
            
        # Apply ideology
        self.civ_manager.set_ideology(user_id, ideology_type)
        
        ideology_descriptions = {
            "fascism": "⚔️ **Fascism**: Your military grows strong, but diplomacy suffers.",
            "democracy": "🗳️ **Democracy**: Your people are happy and trade flourishes.",
            "communism": "🏭 **Communism**: Workers unite for the collective good.",
            "theocracy": "⛪ **Theocracy**: Divine blessing guides your civilization.",
            "anarchy": "💥 **Anarchy**: Chaos reigns, but freedom has no limits.",
            # NEW IDEOLOGY DESCRIPTIONS
            "destruction": "💥 **Destruction**: Y o u. m o n s t e r.",
            "pacifist": "🕊️ **Pacifist**: Your civilization thrives in peace and harmony."
        }
        
        embed = guilded.Embed(
            title=f"🏛️ Ideology Chosen: {ideology_type.capitalize()}",
            description=ideology_descriptions[ideology_type],
            color=0x00ff00
        )
        embed.add_field(
            name="✅ Civilization Complete!",
            value="Your civilization is now ready. Use `.status` to view your progress and `.warhelp` for available commands.",
            inline=False
        )
        
        await ctx.send(embed=embed)

    @commands.command(name='status')
    async def civilization_status(self, ctx):
        """View your civilization status"""
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        
        if not civ:
            await ctx.send("❌ You don't have a civilization yet! Use `.start <name>` to begin.")
            return
            
        # Create status embed
        embed = guilded.Embed(
            title=f"🏛️ {civ['name']}",
            description=f"**Leader**: {ctx.author.name}\n**Ideology**: {civ['ideology'].capitalize() if civ.get('ideology') else 'None'}",
            color=0x0099ff
        )
        
        # Resources
        resources = civ['resources']
        embed.add_field(
            name="💰 Resources",
            value=f"🪙 Gold: {format_number(resources['gold'])}\n🌾 Food: {format_number(resources['food'])}\n🪨 Stone: {format_number(resources['stone'])}\n🪵 Wood: {format_number(resources['wood'])}",
            inline=True
        )
        
        # Population & Military
        population = civ['population']
        military = civ['military']
        embed.add_field(
            name="👥 Population & Military",
            value=f"👤 Citizens: {format_number(population['citizens'])}\n😊 Happiness: {population['happiness']}%\n🍽️ Hunger: {population['hunger']}%\n⚔️ Soldiers: {format_number(military['soldiers'])}\n🕵️ Spies: {format_number(military['spies'])}\n🔬 Tech Level: {military['tech_level']}",
            inline=True
        )
        
        # Territory & Items
        territory = civ['territory']
        hyper_items = civ.get('hyper_items', [])
        embed.add_field(
            name="🗺️ Territory & Items",
            value=f"🏞️ Land Size: {format_number(territory['land_size'])} km²\n🎁 HyperItems: {len(hyper_items)}\n{chr(10).join(f'• {item}' for item in hyper_items[:5])}" + ("..." if len(hyper_items) > 5 else ""),
            inline=True
        )
        
        await ctx.send(embed=embed)

   @commands.command(name='warhelp')
async def warbot_help_command(self, ctx, category: str = None):
    """Display comprehensive, emoji-rich help for every command group."""
    embed = guilded.Embed(
        title="🤖 NationBot — Complete Command Encyclopedia",
        description="Use `.warhelp <category>` to jump to a section (e.g. `.warhelp Military`). Every command below is shown with a short, playful note. 🇺🇳",
        color=0x1e90ff
    )

    basic = (
        "🏛️ BasicCommands:\n"
        "• `.start <name>` — Start a new civilization with a cinematic intro 🎬\n"
        "• `.ideology <type>` — Choose your government (fascism, democracy, communism, theocracy, anarchy, destruction, pacifist) 🏷️\n"
        "• `.status` — View your civ's full status: resources, military, items 📊\n"
        "• `.warhelp` — Display this comprehensive help menu 📚"
    )

    diplomacy = (
        "🤝 DiplomacyCommands:\n"
        "• `.ally @user` — Propose an alliance 🤝\n"
        "• `.acceptally @user` — Accept a pending alliance ✅\n"
        "• `.rejectally @user` — Reject a pending alliance ❌\n"
        "• `.accepttrade @user` — Accept a pending trade ✅\n"
        "• `.rejecttrade @user` — Reject a pending trade ❌\n"
        "• `.trade @user <offer> <request>` — Propose a resource trade 📦↔️📦\n"
        "• `.send @user <resource> <amount>` — Send resources to an ally 🚚\n"
        "• `.mail @user <message>` — Send a diplomatic message ✉️\n"
        "• `.inbox` — Check pending alliances, trades & messages 📥\n"
        "• `.break @user` — Break your current alliance or peace 🪓\n"
        "• `.coalition <target>` — Form a coalition against another alliance ⚔️"
    )

    economy_cog = (
        "💰 EconomyCog (ExtraEconomy & related):\n"
        "• `.arrest <id>` — Police-only seizure attempt 🚓\n"
        "• `.balance` — (legacy) Show civ gold 💳\n"
        "• `.blackjack <amt>` — Quick blackjack vs dealer 🃏\n"
        "• `.code` — Start coding projects (website/virus/messenger) 💻\n"
        "• `.darkweb [item]` — Risky dark web buy (50% scam) 🌑\n"
        "• `.extracards <amt>` — Cards mini-game (renamed from cards) 🂡\n"
        "• `.extragamble <amt>` — Gamble (lose/win/jackpot) 🎲\n"
        "• `.extrainventory` — Show your civ inventory 🎒\n"
        "• `.extrastore` — View extrastore 🛒\n"
        "• `.extrastore buy <item>` — Buy from extrastore (1m cd on success) 🛍️\n"
        "• `.extrawork` — Work your job and earn civ gold (5m cd on success) 💼\n"
        "• `.job <category>` — Apply for a job (bank/police/etc.) 📝\n"
        "• `.jobs` — List job categories and roles 📋\n"
        "• `.profile` — (legacy) Show civ profile 🪪\n"
        "• `.rob <id>` — Criminal-only robbery attempt 🏴‍☠️\n"
        "• `.setbalance <amt>` — Admin-only set civ gold 🔧\n"
        "• `.slots <amt>` — Slot machine mini-game 🎰"
    )

    economy = (
        "🌾 EconomyCommands (core economy):\n"
        "• `.farm` — Farm food (cooldowns apply) 🌽\n"
        "• `.fish` — Fish for food or treasure 🎣\n"
        "• `.mine` — Mine stone & wood ⛏️\n"
        "• `.gather` — Gather random resources 🌿\n"
        "• `.harvest` — Large harvest (longer cooldown) 🌾\n"
        "• `.drill` — Extract rare minerals with drilling 🛠️\n"
        "• `.raidcaravan` — Raid NPC merchant caravans for loot 🛍️⚔️\n"
        "• `.tax` — Collect taxes from citizens 🧾\n"
        "• `.invest <amt>` — Invest gold for delayed profit 📈\n"
        "• `.lottery <amt>` — Lottery gamble for jackpot 🎟️\n"
        "• `.work` — Employ citizens for immediate gold 👷\n"
        "• `.drive` — Unemploy citizens to free them up 🔄\n"
        "• `.cheer` — Spread cheer to boost happiness 😊\n"
        "• `.festival` — Grand festival for major happiness boost 🎉"
    )

    hyperitems = (
        "💎 HyperItemCommands (powerful items):\n"
        "• `.blackmarket` — Enter Black Market for random HyperItems 🕶️\n"
        "• `.inventory` — View your HyperItems & store upgrades 📦\n"
        "• `.backstab @user` — Use Dagger for assassination attempt 🗡️\n"
        "• `.bomb @user` — Use Missiles for mid-tier strike 💣\n"
        "• `.boosttech` — Ancient Scroll to instantly advance tech 📜\n"
        "• `.hiremercs` — Mercenary Contract to hire soldiers 🪖\n"
        "• `.luckystrike` — Lucky Charm for guaranteed critical success 🍀\n"
        "• `.megainvent` — Tech Core to advance multiple tech levels ⚙️\n"
        "• `.mintgold` — Gold Mint to generate large amounts of gold 🏦\n"
        "• `.nuke @user` — Launch nuclear attack (Warhead required) ☢️\n"
        "• `.obliterate @user` — Complete obliteration (HyperLaser) 🔥\n"
        "• `.propaganda @user` — Use Propaganda Kit to steal soldiers 📣\n"
        "• `.shield` — Display Anti-Nuke Shield status 🛡️\n"
        "• `.superharvest` — Harvest Engine for massive food 🌾🚜\n"
        "• `.superspy @user` — Spy Network for elite espionage 🕵️‍♀️"
    )

    military = (
        "⚔️ MilitaryCommands:\n"
        "• `.train soldiers|spies <amt>` — Train units (soldiers or spies) 🏋️‍♂️\n"
        "• `.find` — Search for wandering soldiers to recruit 🔎\n"
        "• `.declare @user` — Declare war on another civ 🪖\n"
        "• `.attack @user` — Launch a direct attack ⚔️\n"
        "• `.siege @user` — Lay siege to enemy territory 🏰\n"
        "• `.stealthbattle @user` — Spy-based stealth attack 🕶️\n"
        "• `.cards` — View/select tech/military cards 🃏\n"
        "• `.accept_peace @user` — Accept a peace offer ✌️\n"
        "• `.peace @user` — Offer peace 🤝\n"
        "• `.debug_military` — Debug military & user data (admin/dev) 🛠️"
    )

    store = (
        "🏬 StoreCommands:\n"
        "• `.store` — View civilization upgrades & store 🏪\n"
        "• `.market` — Black Market information 🧾\n"
        "• `.buy <item>` — Purchase store upgrades 🛒\n"
        "• `.blackmarket` / `.extrastore` — Alternative markets for HyperItems & gear 🕳️"
    )

    misc = (
        "ℹ️ No Category:\n"
        "• `.help` — Show a short help message (this is the full `.warhelp`)\n\n"
        "🔔 Notes:\n"
        "• All commands use '.' prefix. Most economy/military commands require an existing civilization (use `.start`).\n"
        "• Gold is stored on the civ record: civ['resources']['gold'] — persistence: bot.civ_manager -> Database -> JSON fallback.\n"
        "• Cooldowns are applied ONLY after successful execution. If a command errors or you mistype, you will NOT be charged or placed on cooldown.\n"
        "• Default economy/interact cooldown: ~60s on success; `.extrawork` uses 300s (5m). Some heavy actions have longer cooldowns.\n"
        "• AI mentions: the assistant addresses you as 'President' and gives concise tactical guidance when mentioned.\n"
        "• ExtraEconomy credit: (Huge Thanks To @pen)\n"
    )

    # Add fields to the embed
    embed.add_field(name="Basic", value=basic, inline=False)
    embed.add_field(name="Diplomacy", value=diplomacy, inline=False)
    embed.add_field(name="EconomyCog", value=economy_cog, inline=False)
    embed.add_field(name="Economy (Core)", value=economy, inline=False)
    embed.add_field(name="HyperItems", value=hyperitems, inline=False)
    embed.add_field(name="Military", value=military, inline=False)
    embed.add_field(name="Store", value=store, inline=False)
    embed.add_field(name="Misc & Notes", value=misc, inline=False)

    embed.set_footer(text="🎯 Tip: Use `.warhelp <category>` to show just one section if this is too big for chat.")

    await ctx.send(embed=embed)
