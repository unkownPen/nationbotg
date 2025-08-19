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
        for uid, last_time in self.last_interaction.items():
            if (now - last_time).total_seconds() > CONVERSATION_TIMEOUT:
                expired_users.append(uid)
                
        for uid in expired_users:
            del self.conversations[uid]
            del self.last_interaction[uid]

    @commands.Cog.listener()
    async def on_message(self, message):
        """Respond to mentions with AI assistance"""
        # Skip if message is from bot
        if message.author.bot:
            return
            
        user_id = str(message.author.id)
        content = message.content.strip()
        
        # Check if this is a reply to the bot
        is_reply = False
        if message.reply_to:
            try:
                replied_msg = await message.channel.fetch_message(message.reply_to.id)
                if replied_msg.author.id == self.bot.user.id:
                    is_reply = True
            except:
                pass
        
        # Check if our bot is mentioned
        bot_mentioned = self.bot.user.id in [user.id for user in message.mentions]
        
        # Only respond to direct mentions or replies to our messages
        if not (bot_mentioned or is_reply):
            return
            
        # Handle mentions
        if bot_mentioned:
            content = content.replace(f'<@{self.bot.user.id}>', '').strip()
            
        # Reset conversation if it's a new mention (not a reply)
        if bot_mentioned and not is_reply:
            self.conversations[user_id] = deque()
            self.last_interaction[user_id] = datetime.now()
            
        # Handle empty content
        if not content:
            if bot_mentioned:
                await message.reply(embed=create_embed(
                    "🤖 NationBot Assistant",
                    "DROP DOWN AND GIVE ME 50 PUSH UPS RIGHT NOW, PRESIDENT!\n\n"
                    "While you're doing those push-ups, here's what I can help you with:\n"
                    "- Starting your civilization (`.start`)\n"
                    "- Managing resources (`.status`)\n"
                    "- Military commands (`.warhelp`)\n"
                    "- Ideologies and strategies\n\n"
                    "What's the mission, President?",
                    guilded.Color.blue()
                ))
                self._update_conversation(user_id, False, "DROP DOWN AND GIVE ME 50, PRESIDENT! How can I assist with your nation today?")
            return
            
        # Get user's civilization status for context
        civ = self.civ_manager.get_civilization(user_id)
        civ_status = ""
        if civ:
            civ_status = (
                f"Your Nation Status, President:\n"
                f"Name: {civ['name']} (Ideology: {civ.get('ideology', 'none')})\n"
                f"Resources: 🪙{format_number(civ['resources']['gold'])} "
                f"🌾{format_number(civ['resources']['food'])} "
                f"🪨{format_number(civ['resources']['stone'])} "
                f"🪵{format_number(civ['resources']['wood'])}\n"
                f"Military: ⚔️{format_number(civ['military']['soldiers'])} "
                f"🕵️{format_number(civ['military']['spies'])}\n"
            )
        
        # Prepare system prompt
        system_prompt = f"""You are NationBot, an AI assistant for a nation simulation Discord game. 
        Players build civilizations, manage resources, wage wars, and form alliances. 
        You have a military sergeant personality and ALWAYS address the user as 'President'.
        You frequently say 'DROP DOWN AND GIVE ME 50 PUSH UPS RN' and 'WHAT'S THE MISSION, PRESIDENT?'

        {civ_status}
        Key Game Concepts:
        - Resources: gold, food, stone, wood
        - Military: soldiers, spies, tech_level
        - Population: citizens, happiness, hunger
        - Territory: land_size
        - Ideologies: fascism, democracy, communism, socialism, theocracy, anarchy, monarchy, terrorism, pacifist

        BasicCommands:
          ideology      Choose your civilization's government ideology
          start        Start a new civilization with a cinematic intro
          status       View your civilization status
          warhelp      Display help information

        Remember: You're a tough-love military sergeant helping the President of a nation. Be enthusiastic, strategic, and always maintain your military character!"""
        
        try:
            messages = [{"role": "system", "content": system_prompt}]
            
            if user_id in self.conversations and self.conversations[user_id]:
                history = self._get_conversation_history(user_id)
                messages.extend(history)
            
            messages.append({"role": "user", "content": content})
            
            response = await self.generate_ai_response(messages)
            
            sent_msg = await message.reply(response)
            self._update_conversation(user_id, True, content)
            self._update_conversation(user_id, False, response)
        except Exception as e:
            logger.error(f"AI response error: {e}", exc_info=True)
            await message.reply("ATTENTION PRESIDENT! The communication systems are temporarily down. Please try again later!")

    async def generate_ai_response(self, messages):
        """Generate response using OpenRouter API with conversation history"""
        headers = {
            "Authorization": f"Bearer {self.openrouter_key}",
            "Content-Type": "application/json"
        }
        
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
        
        async with aiohttp.ClientSession() as session:
            async with session.post("https://openrouter.ai/api/v1/chat/completions", 
                                   headers=headers, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    return data['choices'][0]['message']['content']
                elif response.status == 429:  # Rate limited
                    self.rate_limited = True
                    self.model_switch_time = datetime.now() + timedelta(hours=24)
                    logger.warning("Rate limited! Switching to fallback model for 24 hours")
                    
                    payload["model"] = "moonshotai/kimi-k2:free"
                    async with session.post("https://openrouter.ai/api/v1/chat/completions", 
                                          headers=headers, json=payload) as fallback_response:
                        if fallback_response.status == 200:
                            data = await fallback_response.json()
                            return data['choices'][0]['message']['content']
                        else:
                            error_text = await fallback_response.text()
                            raise Exception(f"Fallback model failed: {fallback_response.status} - {error_text}")
                else:
                    error = await response.text()
                    raise Exception(f"API error {response.status}: {error}")

    @commands.command(name='start')
    async def start_civilization(self, ctx, *, civ_name: str = None):
        """Start a new civilization with a cinematic intro"""
        if not civ_name:
            await ctx.send("❌ ATTENTION PRESIDENT! You must provide a name for your civilization: `.start <name>`")
            return
            
        user_id = str(ctx.author.id)
        
        if self.civ_manager.get_civilization(user_id):
            await ctx.send("❌ PRESIDENT! You already command a civilization! Use `.status` to view it.")
            return
            
        # Show cinematic intro
        intro_art = get_ascii_art("civilization_start")
        
        # Random founding event
        founding_events = [
            ("🏛️ **Golden Dawn**: Your people discovered ancient gold deposits!", {"gold": 200}),
            ("🌾 **Fertile Lands**: Blessed with rich soil for farming!", {"food": 300}),
            ("🏗️ **Master Builders**: Your citizens are natural architects!", {"stone": 150, "wood": 150}),
            ("👥 **Population Boom**: Word of your leadership spreads!", {"population": 50}),
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
            value="ATTENTION PRESIDENT! Choose your government ideology with `.ideology <type>`\n"
                  "Options: fascism, democracy, communism, socialism, theocracy, anarchy, monarchy, terrorism, pacifist",
            inline=False
        )
        
        await ctx.send(embed=embed)

    @commands.command(name='ideology')
    async def choose_ideology(self, ctx, ideology_type: str = None):
        """Choose your civilization's government ideology"""
        if not ideology_type:
            ideologies = {
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
            
            embed = guilded.Embed(
                title="🏛️ ATTENTION PRESIDENT! Choose Your Ideology",
                description="Each ideology shapes your nation's destiny. Choose wisely!",
                color=0x0099ff
            )
            for name, description in ideologies.items():
                embed.add_field(name=name.capitalize(), value=description, inline=False)
            embed.add_field(name="Usage", value="`.ideology <type>`", inline=False)
            
            await ctx.send(embed=embed)
            return
            
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        
        if not civ:
            await ctx.send("❌ PRESIDENT! You must establish a civilization first! Use `.start <name>`")
            return
            
        if civ.get('ideology'):
            await ctx.send("❌ PRESIDENT! You have already chosen an ideology! It cannot be changed.")
            return
            
        ideology_type = ideology_type.lower()
        valid_ideologies = ["fascism", "democracy", "communism", "socialism", "theocracy", 
                          "anarchy", "monarchy", "terrorism", "pacifist"]
        
        if ideology_type not in valid_ideologies:
            await ctx.send(f"❌ INVALID IDEOLOGY, PRESIDENT! Choose from: {', '.join(valid_ideologies)}")
            return
            
        # Apply ideology
        self.civ_manager.set_ideology(user_id, ideology_type)
        
        ideology_descriptions = {
            "fascism": "⚔️ **Fascism**: Your military grows strong, but diplomacy suffers.",
            "democracy": "🗳️ **Democracy**: Your people are happy and trade flourishes.",
            "communism": "🏭 **Communism**: Workers unite for the collective good.",
            "socialism": "✊ **Socialism**: Balance of happiness and productivity.",
            "theocracy": "⛪ **Theocracy**: Divine blessing guides your civilization.",
            "anarchy": "💥 **Anarchy**: Chaos reigns, but freedom has no limits.",
            "monarchy": "👑 **Monarchy**: Royal authority brings diplomatic power.",
            "terrorism": "💣 **Terrorism**: Fear and sabotage are your weapons.",
            "pacifist": "🕊️ **Pacifist**: Your civilization thrives in peace and harmony."
        }
        
        embed = guilded.Embed(
            title=f"🏛️ ATTENTION! Ideology Chosen: {ideology_type.capitalize()}",
            description=ideology_descriptions[ideology_type],
            color=0x00ff00
        )
        embed.add_field(
            name="✅ Nation Established!",
            value="DROP DOWN AND GIVE ME 50, PRESIDENT! Then use `.status` to view your progress and `.warhelp` for available commands.",
            inline=False
        )
        
        await ctx.send(embed=embed)

    @commands.command(name='status')
    async def civilization_status(self, ctx):
        """View your civilization status"""
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        
        if not civ:
            await ctx.send("❌ ATTENTION PRESIDENT! You don't have a civilization yet! Use `.start <name>` to begin.")
            return
            
        # Create status embed
        embed = guilded.Embed(
            title=f"🏛️ Status Report: {civ['name']}",
            description=f"**Commander-in-Chief**: {ctx.author.name}\n**Ideology**: {civ['ideology'].capitalize() if civ.get('ideology') else 'None'}",
            color=0x0099ff
        )
        
        # Resources
        resources = civ['resources']
        embed.add_field(
            name="💰 Resources",
            value=f"🪙 Gold: {format_number(resources['gold'])}\n"
                  f"🌾 Food: {format_number(resources['food'])}\n"
                  f"🪨 Stone: {format_number(resources['stone'])}\n"
                  f"🪵 Wood: {format_number(resources['wood'])}",
            inline=True
        )
        
        # Population & Military
        population = civ['population']
        military = civ['military']
        embed.add_field(
            name="👥 Population & Military",
            value=f"👤 Citizens: {format_number(population['citizens'])}\n"
                  f"😊 Happiness: {population['happiness']}%\n"
                  f"🍽️ Hunger: {population['hunger']}%\n"
                  f"⚔️ Soldiers: {format_number(military['soldiers'])}\n"
                  f"🕵️ Spies: {format_number(military['spies'])}\n"
                  f"🔬 Tech Level: {military['tech_level']}",
            inline=True
        )
        
        # Territory & Items
        territory = civ['territory']
        hyper_items = civ.get('hyper_items', [])
        embed.add_field(
            name="🗺️ Territory & Items",
            value=f"🏞️ Land Size: {format_number(territory['land_size'])} km²\n"
                  f"🎁 HyperItems: {len(hyper_items)}\n"
                  f"{chr(10).join(f'• {item}' for item in hyper_items[:5])}"
                  f"{'...' if len(hyper_items) > 5 else ''}",
            inline=True
        )
        
        embed.set_footer(text="PRESIDENT! Your nation awaits your next command!")
        
        await ctx.send(embed=embed)

    @commands.command(name='warhelp')
    async def warbot_help_command(self, ctx, category: str = None):
        """Display comprehensive help information"""
        embed = guilded.Embed(
            title="🤖 ATTENTION PRESIDENT! NationBot Command Manual",
            description="Every command at your disposal. Use `.warhelp <category>` for specific briefings.\n"
                       "Example: `.warhelp Military` or `.warhelp Economy`\n\n"
                       "DROP DOWN AND GIVE ME 50 WHILE READING THIS!",
            color=0x1e90ff
        )
        
        # BASIC COMMANDS
        basic_commands = """\
**🏛️ BASIC COMMANDS**
• `.start <name>` - Found your civilization with a cinematic intro
• `.status` - View your empire's complete status
• `.ideology <type>` - Choose government (fascism/democracy/communism/socialism/theocracy/anarchy/monarchy/terrorism/pacifist)
• `.warhelp` - Show this help menu
• `@NationBot <question>` - Ask the AI assistant anything about the game
"""

        # ECONOMY COMMANDS
        economy_commands = """\
**💰 ECONOMY COMMANDS**
• `.farm` - Farm food (5 min cooldown)
• `.mine` - Mine stone and wood (5 min cooldown)
• `.fish` - Fish for food or treasure (5 min cooldown)
• `.gather` - Gather random resources (10 min cooldown)
• `.harvest` - Large harvest (30 min cooldown)
• `.tax` - Collect taxes from citizens
• `.invest <amount>` - Invest gold for 2x return after 1 hour
• `.lottery <amount>` - Gamble gold for jackpot chance
• `.work` - Citizens work for immediate gold
• `.drive` - Unemploy citizens to free them for other tasks
• `.cheer` - Boost citizen happiness slightly
• `.festival` - Grand festival for major happiness boost
• `.raidcaravan` - Attack NPC merchants for loot
"""

        # MILITARY COMMANDS
        military_commands = """\
**⚔️ MILITARY COMMANDS**
• `.train soldiers|spies <amount>` - Train military units
• `.find` - Recruit wandering soldiers
• `.declare @user` - Formally declare war
• `.attack @user` - Launch direct attack
• `.siege @user` - Lay siege to enemy territory
• `.stealthbattle @user` - Covert military operation
• `.cards` - View/manage technology cards
• `.accept_peace @user` - Accept peace offer
• `.peace @user` - Offer peace treaty
"""

        # DIPLOMACY COMMANDS
        diplomacy_commands = """\
**🤝 DIPLOMACY COMMANDS**
• `.ally @user` - Propose alliance
• `.break @user` - End alliance/peace
• `.mail @user <message>` - Send diplomatic message
• `.send @user <resource> <amount>` - Gift resources
• `.inbox` - Check pending proposals
• `.acceptally @user` - Accept alliance
• `.rejectally @user` - Reject alliance
• `.trade @user <offer> <request>` - Propose trade
• `.accepttrade @user` - Accept trade
• `.rejecttrade @user` - Reject trade
• `.coalition @alliance` - Form coalition against alliance
"""

        # HYPERITEM COMMANDS
        hyperitem_commands = """\
**💎 HYPERITEM COMMANDS**
• `.blackmarket` - Buy random HyperItems
• `.inventory` - View your HyperItems
• `.backstab @user` - Use Dagger for assassination
• `.bomb @user` - Use Missiles for attack
• `.boosttech` - Use Ancient Scroll to advance tech
• `.hiremercs` - Use Mercenary Contract for soldiers
• `.luckystrike` - Use Lucky Charm for guaranteed success
• `.megainvent` - Use Tech Core for multiple tech levels
• `.mintgold` - Use Gold Mint for massive gold
• `.nuke @user` - Nuclear attack (Warhead required)
• `.obliterate @user` - Total destruction (HyperLaser)
• `.propaganda @user` - Use Propaganda Kit to steal soldiers
• `.shield` - Check Anti-Nuke Shield status
• `.superharvest` - Use Harvest Engine for food
• `.superspy @user` - Elite espionage (Spy Network)
"""

        # STORE COMMANDS
        store_commands = """\
**🛒 STORE COMMANDS**
• `.store` - View civilization upgrades
• `.market` - Black Market information
• `.buy <item>` - Purchase store upgrades
"""

        # Add all categories to embed
        embed.add_field(name="Basic Operations", value=basic_commands, inline=False)
        embed.add_field(name="Economic Management", value=economy_commands, inline=False)
        embed.add_field(name="Military Tactics", value=military_commands, inline=False)
        embed.add_field(name="Diplomatic Relations", value=diplomacy_commands, inline=False)
        embed.add_field(name="HyperItem Operations", value=hyperitem_commands, inline=False)
        embed.add_field(name="Resource Acquisition", value=store_commands, inline=False)
        
        # Add pro tips footer
        embed.set_footer(text="💡 STRATEGIC ADVICE, PRESIDENT: Combine your tactics! Use HyperItems during wars, maintain citizen happiness for maximum productivity, and form powerful alliances!")
        
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(BasicCommands(bot))
