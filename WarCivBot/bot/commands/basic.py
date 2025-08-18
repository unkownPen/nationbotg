import random
import guilded
import os
import aiohttp
import asyncio
import logging
from datetime import datetime, timedelta
from guilded.ext import commands
from bot.utils import format_number, get_ascii_art, create_embed

logger = logging.getLogger(__name__)

class BasicCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.civ_manager = bot.civ_manager
        self.openrouter_key = os.getenv('OPENROUTER')
        self.current_model = "deepseek/deepseek-chat"
        self.model_switch_time = None
        self.rate_limited = False

    @commands.Cog.listener()
    async def on_message(self, message):
        """Respond to mentions with AI assistance"""
        if message.author.bot or not self.bot.user.mentioned_in(message):
            return
            
        user_id = str(message.author.id)
        content = message.content.replace(f'<@{self.bot.user.id}>', '').strip()
        
        if not content:
            # Default response for just a mention
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
            return
            
        # Get user's civilization status for context
        civ = self.civ_manager.get_civilization(user_id)
        civ_status = ""
        if civ:
            civ_status = (
                f"Player's Civilization: {civ['name']} (Ideology: {civ.get('ideology', 'none')})\n"
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
        Your role is to help players understand game mechanics and strategies.

        {civ_status}
        Key Game Concepts:
        - Resources: gold, food, stone, wood
        - Military: soldiers, spies, tech_level
        - Population: citizens, happiness, hunger
        - Territory: land_size
        - Ideologies: fascism, democracy, communism, theocracy, anarchy, destruction, pacifist

        Common Commands:
        - .start <name>: Begin your civilization
        - .status: View your civilization
        - .ideology <type>: Choose government type
        - .train <soldiers|spies> <amount>: Train military
        - .attack @user: Attack another player
        - .declare @user: Declare war
        - .peace @user: Offer peace
        - .find: Search for soldiers
        - .cards: Manage tech cards

        You are helpful, encouraging, and strategic. Keep responses concise and focused on gameplay. 
        If asked about non-game topics, politely decline. Use Discord markdown for formatting.
        """
        
        # Generate AI response
        try:
            response = await self.generate_ai_response(system_prompt, content)
            await message.reply(response)
        except Exception as e:
            logger.error(f"AI response error: {e}")
            await message.reply("I'm having trouble thinking right now. Please try again later!")

    async def generate_ai_response(self, system_prompt, user_query):
        """Generate response using OpenRouter API"""
        headers = {
            "Authorization": f"Bearer {self.openrouter_key}",
            "Content-Type": "application/json"
        }
        
        # Check if we need to switch models due to rate limiting
        if self.rate_limited and self.model_switch_time and datetime.now() < self.model_switch_time:
            model = "moonshotai/kimi-k2:free"
        else:
            model = self.current_model
            self.rate_limited = False
            
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query}
            ],
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
                    
                    # Retry with fallback model
                    payload["model"] = "moonshotai/kimi-k2:free"
                    async with session.post("https://openrouter.ai/api/v1/chat/completions", 
                                          headers=headers, json=payload) as fallback_response:
                        if fallback_response.status == 200:
                            data = await fallback_response.json()
                            return data['choices'][0]['message']['content']
                        else:
                            raise Exception(f"Fallback model failed: {fallback_response.status}")
                else:
                    error = await response.text()
                    raise Exception(f"API error {response.status}: {error}")

    @commands.command(name='start')
    async def start_civilization(self, ctx, *, civ_name: str = None):
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
        """Display help information"""
        embed = guilded.Embed(
            title="🤖 NationBot Command Guide",
            description="Master your civilization and dominate the world through strategy and cunning!",
            color=0x1e90ff
        )
        
        help_text = """
**🏛️ CIVILIZATION BASICS**
• `.start <name>` - Found your civilization
• `.status` - View your empire's current state
• `.ideology <type>` - Choose government (fascism, democracy, communism, theocracy, anarchy, destruction, pacifist)

**💰 ECONOMIC COMMANDS**
• `.farm` - Farm food for your civilization
• `.mine` - Mine stone and wood from your territory
• `.fish` - Fish for food or occasionally find treasure
• `.gather` - Gather random resources from your territory
• `.tax` - Collect taxes from your citizens
• `.invest` - Invest gold for delayed profit
• `.lottery` - Gamble gold for a chance at the jackpot

**⚔️ MILITARY COMMANDS**
• `.train <soldiers|spies> <amount>` - Train military units
• `.declare @user` - Declare war formally
• `.attack @user` - Launch military assault
• `.siege @user` - Lay siege to enemy territory
• `.stealthbattle @user` - Covert military operation
• `.find` - Search for wandering soldiers to recruit
• `.cards` - Manage technology cards

**🕵️ ESPIONAGE COMMANDS**
• `.spy @user` - Gather intelligence on enemies
• `.sabotage @user` - Disrupt enemy operations
• `.steal @user <resource>` - Steal resources covertly

**🤝 DIPLOMATIC COMMANDS**
• `.ally @user` - Form strategic alliance
• `.break @user` - End alliance or peace
• `.mail @user <message>` - Send diplomatic message
• `.send @user <resource> <amount>` - Gift resources
• `.peace @user` - Offer peace treaty
• `.accept_peace @user` - Accept peace offer

**💎 HYPERITEMS & SPECIALS**
• `.blackmarket` - Purchase random HyperItems
• `.inventory` - View your HyperItems
• `.propaganda @user` - Use Propaganda Kit to convert soldiers
• `.nuke @user` - Launch nuclear attack (requires Warhead)
• `.boosttech` - Instantly advance technology (requires Ancient Scroll)

**ℹ️ INFORMATION**
• `.warhelp` - Display this help menu
• Ping me (@NationBot) for AI assistance with any game questions!
"""
        
        embed.description = help_text
        
        embed.add_field(
            name="🌟 Pro Tips",
            value="• Maintain happiness to keep your civilization stable\n"
                  "• Different ideologies provide unique bonuses/penalties\n"
                  "• Form alliances for mutual protection and growth\n"
                  "• Use HyperItems strategically for maximum impact\n"
                  "• Balance resource production with military expansion",
            inline=False
        )
        
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(BasicCommands(bot))
