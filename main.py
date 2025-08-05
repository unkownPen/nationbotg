import os
import threading
import random
import time
import asyncio
from datetime import datetime, timedelta
from flask import Flask
import guilded
from guilded.ext import commands

# Initialize Flask app for keep-alive
app = Flask(__name__)

@app.route('/')
def index():
    return f"⚔️ Warbot is running! Server pinged at: {time.strftime('%Y-%m-%d %H:%M:%S')}"

# Bot setup
bot = commands.Bot(command_prefix='.', help_command=None)

# Simple database simulation
players = {}
RESOURCE_TYPES = ["gold", "food", "soldiers", "happiness", "hunger"]

class Player:
    def __init__(self, id):
        self.id = id
        self.resources = {
            "gold": 1000,
            "food": 500,
            "soldiers": 100,
            "happiness": 50,
            "hunger": 1000  # New hunger system (0-3000)
        }
        self.last_attack = 0
        self.last_gather = 0
        self.last_gamble = 0
        self.civil_war_counter = 0
        self.cheer_cost = 100  # Dynamic cheer pricing
        self.feed_cost = 50    # Dynamic feed pricing
        self.happiness_boost = 1.0  # Building multiplier
        self.buildings = 0      # Number of buildings
        self.allies = set()     # Set of ally IDs
        self.last_passive = time.time()
        self.last_hunger_penalty = time.time()
        self.cheer_count = 0   # Track cheer count for price reset
        self.last_farm = 0     # Farm cooldown tracker

def get_player(user_id):
    if user_id not in players:
        players[user_id] = Player(user_id)
    return players[user_id]

# UAE Timezone (UTC+4)
def is_night_in_uae():
    utc_now = datetime.utcnow()
    uae_time = utc_now + timedelta(hours=4)
    return 22 <= uae_time.hour or uae_time.hour < 6

# Background task for passive effects
async def passive_effects():
    await bot.wait_until_ready()
    while not bot.is_closed():
        now = time.time()
        
        # Process all players
        for player_id, player in list(players.items()):
            try:
                # Passive gold drain every 10 minutes
                if now - player.last_passive > 600:
                    player.resources["gold"] = max(0, player.resources["gold"] - 50)
                    player.last_passive = now
                
                # Hunger depletion (only during non-night hours)
                if not is_night_in_uae():
                    if now - player.last_passive > 600:  # Every 10 minutes
                        player.resources["hunger"] = max(0, player.resources["hunger"] - 1)
                
                # Apply hunger penalties
                hunger = player.resources["hunger"]
                if hunger < 250:  # Under 25%
                    if now - player.last_hunger_penalty > 60:  # Every minute
                        player.resources["happiness"] = max(0, player.resources["happiness"] - 15)
                        player.resources["soldiers"] = max(0, player.resources["soldiers"] - 4)
                        player.last_hunger_penalty = now
                elif hunger < 500:  # Under 50%
                    if now - player.last_hunger_penalty > 120:  # Every 2 minutes
                        player.resources["happiness"] = max(0, player.resources["happiness"] - 10)
                        player.resources["soldiers"] = max(0, player.resources["soldiers"] - 2)
                        player.last_hunger_penalty = now
                
                # Reset cheer cost after 4 days (345,600 seconds)
                if now - player.last_passive > 345600:
                    player.cheer_cost = 100
                    player.cheer_count = 0
                    player.feed_cost = 50
                
            except Exception as e:
                print(f"Error processing passive effects: {e}")
        
        await asyncio.sleep(10)  # Check every 10 seconds

# Async setup hook
@bot.event
async def setup_hook():
    bot.loop.create_task(passive_effects())

# Bot events
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    print('------')
    await bot.set_status("Managing civilizations!")
    print("Bot is ready and Flask server is running")

# Bot commands
@bot.command()
async def start(ctx):
    """Initialize your civilization"""
    player = get_player(ctx.author.id)
    embed = guilded.Embed(
        title="🏰 Civilization Created!",
        description=f"Welcome {ctx.author.mention}, your civilization is ready!",
        color=guilded.Color.green()
    )
    resources_display = "\n".join(
        [f"{r.capitalize()}: {player.resources[r]}" for r in RESOURCE_TYPES]
    )
    resources_display += f"\nHappiness Boost: x{player.happiness_boost}"
    embed.add_field(name="Starting Resources", value=resources_display)
    await ctx.send(embed=embed)

@bot.command()
async def ally(ctx, *, target_name: str = None):
    """Form an alliance with another player"""
    if target_name is None:
        await ctx.send("❌ Please mention a user to ally with! Example: `.ally @Username`")
        return
    
    # Find the mentioned user
    target = None
    if ctx.message.mentions:
        target = ctx.message.mentions[0]
    
    # If no mentions found, search by name
    if not target:
        for member in await ctx.server.fetch_members():
            if target_name.lower() in member.name.lower():
                target = member
                break
    
    # If still not found
    if not target:
        await ctx.send("❌ User not found! Please mention a valid user in this server.")
        return
    
    if target.id == ctx.author.id:
        await ctx.send("❌ You can't ally yourself!")
        return
        
    if target.bot:
        await ctx.send("❌ You can't ally bots!")
        return
        
    player = get_player(ctx.author.id)
    target_player = get_player(target.id)
    
    # Add each other as allies
    player.allies.add(target.id)
    target_player.allies.add(ctx.author.id)
    
    embed = guilded.Embed(
        title="🤝 Alliance Formed!",
        description=f"{ctx.author.mention} and {target.mention} are now allies!",
        color=guilded.Color.green()
    )
    embed.add_field(name="Terms", value="Support each other and don't backstab... or do?")
    await ctx.send(embed=embed)

@bot.command()
async def send(ctx, resource: str, amount: int, *, target_name: str = None):
    """Send resources to another player"""
    if target_name is None:
        await ctx.send("❌ Please mention a user to send to! Example: `.send food 100 @Username`")
        return
    
    if resource not in ["gold", "food", "soldiers"]:
        await ctx.send("❌ Invalid resource! Can only send gold, food, or soldiers.")
        return
    
    if amount <= 0:
        await ctx.send("❌ Amount must be positive!")
        return
    
    # Find the mentioned user
    target = None
    if ctx.message.mentions:
        target = ctx.message.mentions[0]
    
    # If no mentions found, search by name
    if not target:
        for member in await ctx.server.fetch_members():
            if target_name.lower() in member.name.lower():
                target = member
                break
    
    # If still not found
    if not target:
        await ctx.send("❌ User not found! Please mention a valid user in this server.")
        return
    
    if target.id == ctx.author.id:
        await ctx.send("❌ You can't send resources to yourself!")
        return
        
    if target.bot:
        await ctx.send("❌ You can't send resources to bots!")
        return
    
    player = get_player(ctx.author.id)
    target_player = get_player(target.id)
    
    # Check if sender has enough resources
    if player.resources[resource] < amount:
        await ctx.send(f"❌ You don't have enough {resource} to send!")
        return
    
    # Transfer resources
    player.resources[resource] -= amount
    target_player.resources[resource] += amount
    
    embed = guilded.Embed(
        title="📦 Resources Sent!",
        description=f"{ctx.author.mention} sent {amount} {resource} to {target.mention}!",
        color=guilded.Color.blue()
    )
    embed.add_field(name=f"Your remaining {resource}", value=f"{player.resources[resource]}")
    await ctx.send(embed=embed)

@bot.command()
async def buy(ctx, item: str):
    """Buy resources or resets"""
    player = get_player(ctx.author.id)
    discount = 1.0 - (player.buildings * 0.05)  # 5% discount per building
    
    prices = {
        "hunger_reset": max(50, int(200 * discount)),
        "happiness_reset": max(100, int(300 * discount)),
        "food": max(10, int(20 * discount)),
        "soldiers": max(50, int(100 * discount))
    }
    
    if item not in prices:
        await ctx.send("❌ Invalid item! Available items: hunger_reset, happiness_reset, food, soldiers")
        return
    
    cost = prices[item]
    
    if player.resources["gold"] < cost:
        await ctx.send(f"❌ You need {cost} gold to buy {item}!")
        return
    
    # Process purchase
    player.resources["gold"] -= cost
    if item == "hunger_reset":
        player.resources["hunger"] = 100
        result = "Reset hunger to 100!"
    elif item == "happiness_reset":
        player.resources["happiness"] = 50
        result = "Reset happiness to 50!"
    elif item == "food":
        amount = 1000
        player.resources["food"] += amount
        result = f"Bought {amount} food!"
    elif item == "soldiers":
        amount = 50
        player.resources["soldiers"] += amount
        result = f"Bought {amount} soldiers!"
    
    embed = guilded.Embed(
        title="🛒 Purchase Complete!",
        description=f"{ctx.author.mention} bought {item} for {cost} gold!",
        color=guilded.Color.gold()
    )
    embed.add_field(name="Result", value=result)
    embed.add_field(name="Discount Applied", value=f"{int((1-discount)*100)}% (from buildings)")
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 300, commands.BucketType.user)  # 5-minute cooldown
async def farm(ctx):
    """Grow food with a chance of poisonous mushrooms (5 min cooldown)"""
    player = get_player(ctx.author.id)
    
    # 10% chance of poisonous mushroom
    if random.random() < 0.1:
        # Bad outcome
        hunger_loss = random.randint(50, 100)
        happiness_loss = random.randint(5, 15)
        player.resources["hunger"] = max(0, player.resources["hunger"] - hunger_loss)
        player.resources["happiness"] = max(0, player.resources["happiness"] - happiness_loss)
        
        embed = guilded.Embed(
            title="🍄 Farming Disaster!",
            description=f"{ctx.author.mention} found poisonous mushrooms while farming!",
            color=guilded.Color.red()
        )
        embed.add_field(name="Hunger Lost", value=f"-{hunger_loss}")
        embed.add_field(name="Happiness Lost", value=f"-{happiness_loss}")
    else:
        # Good outcome
        food_gain = random.randint(100, 300)
        happiness_gain = random.randint(5, 10)
        player.resources["food"] += food_gain
        player.resources["happiness"] = min(100, player.resources["happiness"] + happiness_gain)
        
        embed = guilded.Embed(
            title="🌱 Farming Success!",
            description=f"{ctx.author.mention} harvested a bountiful crop!",
            color=guilded.Color.green()
        )
        embed.add_field(name="Food Gained", value=f"+{food_gain}")
        embed.add_field(name="Happiness Gained", value=f"+{happiness_gain}")
    
    await ctx.send(embed=embed)

# ... (keep all other existing commands unchanged) ...

@bot.command()
async def help(ctx):
    """Show available commands"""
    embed = guilded.Embed(
        title="🛠️ Warbot Commands",
        description="Manage your civilization and wage wars!",
        color=guilded.Color.dark_gold()
    )
    
    commands = {
        ".start": "Create your civilization",
        ".attack @user": "Declare war (1 min cooldown)",
        ".resources [name]": "View resources",
        ".gather": "Collect resources (5 min cooldown, 50% risk)",
        ".cheer": "Boost happiness (increasing cost)",
        ".feed": "Feed your people (increasing cost)",
        ".build": "Build skyscrapers (500 gold, 1 hr cooldown)",
        ".ally @user": "Form an alliance",
        ".unally @user": "Dissolve an alliance",
        ".backstab @user": "Betray an ally (30% fail risk, 1-day cooldown)",
        ".send <resource> <amount> @user": "Send resources to another player",
        ".buy <item>": "Purchase items (hunger_reset, happiness_reset, food, soldiers)",
        ".farm": "Grow food with 10% risk (5 min cooldown)",
        ".gamble": "50/50 gold gamble (loses 15 happiness, 1 min cooldown)",
        ".help": "Show this help menu"
    }
    
    for cmd, desc in commands.items():
        embed.add_field(name=cmd, value=desc, inline=False)
    
    embed.set_footer(text="Warbot v5.0 | Trading & Farming added!")
    await ctx.send(embed=embed)

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# Start Flask in a separate thread
flask_thread = threading.Thread(target=run_flask)
flask_thread.daemon = True
flask_thread.start()

# Get bot token from environment variable and run
TOKEN = os.environ.get('GUILDED_TOKEN')
if TOKEN:
    print("Starting bot...")
    bot.run(TOKEN)
else:
    print("ERROR: GUILDED_TOKEN environment variable not set!")
    print("Please set your bot token in Replit secrets (Environment Variables)")
