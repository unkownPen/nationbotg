import random
import guilded
from guilded.ext import commands
from datetime import datetime
import logging
from bot.utils import format_number, get_ascii_art, create_embed

logger = logging.getLogger(__name__)

class BasicCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.civ_manager = bot.civ_manager

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
            value="Choose your government ideology with `.ideology <type>`\nOptions: fascism, democracy, communism, theocracy, anarchy",
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
                # ADDED DESTRUCTION IDEOLOGY
                "destruction": "+75% soldier training, +50% attack power, +40% pillage rewards\n-40% productivity, -50% diplomacy, +20% upkeep"
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
        # ADDED DESTRUCTION TO VALID IDEOLOGIES
        valid_ideologies = ["fascism", "democracy", "communism", "theocracy", "anarchy", "destruction"]
        
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
            # ADDED DESTRUCTION DESCRIPTION
            "destruction": "🔥 **Destruction**: Burn everything. Leave only ashes. Glory comes through ruin."
        }
        
        embed = guilded.Embed(
            title=f"🏛️ Ideology Chosen: {ideology_type.capitalize()}",
            description=ideology_descriptions[ideology_type],
            color=0x00ff00
        )
        
        # SPECIAL WARNING FOR DESTRUCTION
        if ideology_type == "destruction":
            embed.add_field(
                name="☠️ WARNING",
                value="Destruction is a path of no return. Your people will either conquer through fire... or perish in it.",
                inline=False
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
        if not category:
            embed = guilded.Embed(
                title="🤖 WarBot Command Guide",
                description="Master your civilization and dominate the world through strategy and cunning!",
                color=0x1e90ff
            )
            
            help_text = """
**🏛️ CIVILIZATION BASICS**
• `.start <name>` - Found your civilization
• `.status` - View your empire's current state
• `.ideology <type>` - Choose government (fascism, democracy, communism, theocracy, anarchy)

**💰 ECONOMIC EMPIRE**
• `.gather` - Collect basic resources from your lands
• `.farm` - Cultivate food to feed your population
• `.mine` - Extract stone from quarries
• `.harvest` - Gather wood from forests
• `.trade <user> <resource> <amount>` - Trade with other civilizations
• `.tax` - Collect taxes from your citizens
• `.lottery` - Try your luck for bonus resources

**⚔️ MILITARY CONQUEST**
• `.attack <user>` - Launch military assault
• `.train <type> <amount>` - Train soldiers or spies
• `.declare <user>` - Declare war formally
• `.siege <user>` - Lay siege to enemy territory
• `.stealthbattle <user>` - Covert military operation

**🕵️ SHADOW OPERATIONS**
• `.spy <user>` - Gather intelligence on enemies
• `.sabotage <user>` - Disrupt enemy operations
• `.hack <user>` - Cyber warfare attacks
• `.steal <user> <resource>` - Steal resources covertly
• `.superspy <user>` - Elite espionage mission

**🤝 DIPLOMATIC RELATIONS**
• `.ally <user>` - Form strategic alliance
• `.break <user>` - End alliance or peace
• `.coalition <name>` - Create multi-nation alliance
• `.mail <user> <message>` - Send diplomatic message
• `.send <user> <resource> <amount>` - Gift resources

**🏪 MARKETPLACE**
• `.store` - Browse items for purchase
• `.blackmarket` - Access rare and forbidden items

**🎁 HYPERITEMS & ULTIMATE POWER**
• `.nuke <user>` - Nuclear devastation (requires Nuclear Warhead)
• `.shield` - Activate defensive systems
• `.propaganda <message>` - Influence other civilizations
• `.obliterate <user>` - Complete annihilation (requires Planet Killer)

**📊 INFORMATION**
• `.warhelp` - Display this help menu
• Web Dashboard available at your server's port 5000
"""
            
            embed.description += help_text
            
            embed.add_field(
                name="🌟 Pro Tips",
                value="• Choose your ideology wisely - each has unique bonuses\n• HyperItems are rare but extremely powerful\n• Maintain happiness to keep your civilization stable\n• Form alliances for mutual protection and growth",
                inline=False
            )
            
            await ctx.send(embed=embed)
        else:
            # Category-specific help would be implemented here
            await ctx.send(f"Detailed help for category '{category}' coming soon!")

async def setup(bot):
    await bot.add_cog(BasicCommands(bot))
