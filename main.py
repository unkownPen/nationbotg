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

# Custom attack messages
UNDERDOG_VICTORY_MESSAGES = [
    "A lone soldier dodged every bullet and soloed the entire enemy army!",
    "Against all odds, your outnumbered forces executed a perfect ambush!",
    "Your commander's brilliant tactics turned certain defeat into victory!",
    "The enemy became overconfident and walked right into your trap!",
    "Divine intervention! A miracle saved your forces at the last moment!"
]

CIVIL_WAR_MESSAGES = [
    "Brother fights brother as your nation tears itself apart!",
    "Political factions clash in the streets!",
    "Regional warlords declare independence!",
    "Mass desertions cripple your military!",
    "Rebel forces seize government buildings!"
]

class Player:
    def __init__(self, id):
        self.id = id
        self.resources = {
            "gold": 1000,
            "food": 500,
            "soldiers": 100,
            "happiness": 50,
            "hunger": 1000
        }
        self.last_attack = 0
        self.last_gather = 0
        self.last_gamble = 0
        self.last_build = 0
        self.civil_war_counter = 0
        self.cheer_cost = 100
        self.feed_cost = 50
        self.happiness_boost = 1.0
        self.buildings = 0
        self.allies = set()
        self.last_passive = time.time()
        self.last_hunger_penalty = time.time()
        self.cheer_count = 0
        self.last_farm = 0
        self.last_backstab = 0
        self.in_civil_war = False

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
        
        for player_id, player in list(players.items()):
            try:
                # Passive gold drain every 10 minutes
                if now - player.last_passive > 600:
                    player.resources["gold"] = max(0, player.resources["gold"] - 50)
                    player.last_passive = now
                
                # Hunger depletion (only during non-night hours)
                if not is_night_in_uae():
                    if now - player.last_passive > 600:
                        player.resources["hunger"] = max(0, player.resources["hunger"] - 1)
                
                # Apply hunger penalties
                hunger = player.resources["hunger"]
                if hunger < 250:
                    if now - player.last_hunger_penalty > 60:
                        player.resources["happiness"] = max(0, player.resources["happiness"] - 15)
                        player.resources["soldiers"] = max(0, player.resources["soldiers"] - 4)
                        player.last_hunger_penalty = now
                elif hunger < 500:
                    if now - player.last_hunger_penalty > 120:
                        player.resources["happiness"] = max(0, player.resources["happiness"] - 10)
                        player.resources["soldiers"] = max(0, player.resources["soldiers"] - 2)
                        player.last_hunger_penalty = now
                
                # Reset cheer cost after 4 days
                if now - player.last_passive > 345600:
                    player.cheer_cost = 100
                    player.cheer_count = 0
                    player.feed_cost = 50
                
                # Check for civil war
                if player.resources["happiness"] < 30 and not player.in_civil_war:
                    player.in_civil_war = True
                    player.civil_war_counter = 0
                
            except Exception as e:
                print(f"Error processing passive effects: {e}")
        
        await asyncio.sleep(10)

# Async setup hook
@bot.event
async def setup_hook():
    bot.loop.create_task(passive_effects())

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    await bot.set_status("Managing civilizations!")
    print("Bot is ready and Flask server is running")

@bot.command()
async def start(ctx):
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
async def resources(ctx, *, target_name: str = None):
    """View your or another player's resources"""
    target = ctx.author
    if target_name:
        if ctx.message.mentions:
            target = ctx.message.mentions[0]
        else:
            for member in await ctx.server.fetch_members():
                if target_name.lower() in member.name.lower():
                    target = member
                    break
    
    player = get_player(target.id)
    embed = guilded.Embed(
        title=f"📊 {target.name}'s Resources",
        color=guilded.Color.blue()
    )
    for resource, value in player.resources.items():
        embed.add_field(name=resource.capitalize(), value=str(value), inline=True)
    embed.add_field(name="Buildings", value=str(player.buildings), inline=True)
    embed.add_field(name="Happiness Boost", value=f"x{player.happiness_boost}", inline=True)
    if player.in_civil_war:
        embed.add_field(name="⚠️ CIVIL WAR", value=f"{3 - player.civil_war_counter}/3 battles needed to end the war!", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def allies(ctx):
    """List your current allies"""
    player = get_player(ctx.author.id)
    
    if not player.allies:
        await ctx.send("❌ You don't have any allies yet! Use `.ally @player` to form alliances.")
        return
    
    ally_list = []
    for ally_id in player.allies:
        try:
            user = await bot.fetch_user(ally_id)
            ally_list.append(user.name)
        except:
            ally_list.append(f"Unknown Player ({ally_id})")
    
    embed = guilded.Embed(
        title="🤝 Your Alliances",
        description="\n".join(ally_list) or "No allies found",
        color=guilded.Color.gold()
    )
    embed.set_footer(text=f"Total Allies: {len(player.allies)}")
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 300, commands.BucketType.user)
async def gather(ctx):
    """Collect resources with 50% risk (5 min cooldown)"""
    player = get_player(ctx.author.id)
    
    if player.in_civil_war:
        await ctx.send("❌ You can't gather resources during a civil war! Resolve your internal conflicts first.")
        return
    
    if random.random() < 0.5:  # 50% success chance
        gold_gain = random.randint(100, 300)
        food_gain = random.randint(50, 100)
        soldiers_gain = random.randint(5, 10)
        player.resources["gold"] += gold_gain
        player.resources["food"] += food_gain
        player.resources["soldiers"] += soldiers_gain
        player.resources["happiness"] = min(100, player.resources["happiness"] + random.randint(1, 5))
        
        embed = guilded.Embed(
            title="⛏️ Gathering Success!",
            description="You found valuable resources!",
            color=guilded.Color.green()
        )
        embed.add_field(name="Gold", value=f"+{gold_gain}", inline=True)
        embed.add_field(name="Food", value=f"+{food_gain}", inline=True)
        embed.add_field(name="Soldiers", value=f"+{soldiers_gain}", inline=True)
    else:
        gold_loss = random.randint(50, 100)
        food_loss = random.randint(10, 30)
        soldiers_loss = random.randint(5, 10)
        player.resources["gold"] = max(0, player.resources["gold"] - gold_loss)
        player.resources["food"] = max(0, player.resources["food"] - food_loss)
        player.resources["soldiers"] = max(0, player.resources["soldiers"] - soldiers_loss)
        player.resources["happiness"] = max(0, player.resources["happiness"] - random.randint(5, 10))
        
        embed = guilded.Embed(
            title="💀 Gathering Disaster!",
            description="You were ambushed by bandits!",
            color=guilded.Color.red()
        )
        embed.add_field(name="Gold", value=f"-{gold_loss}", inline=True)
        embed.add_field(name="Food", value=f"-{food_loss}", inline=True)
        embed.add_field(name="Soldiers", value=f"-{soldiers_loss}", inline=True)
    
    await ctx.send(embed=embed)

@bot.command()
async def cheer(ctx):
    """Boost happiness (increasing cost)"""
    player = get_player(ctx.author.id)
    
    if player.in_civil_war:
        await ctx.send("❌ Your people are too angry to cheer! Resolve the civil war first.")
        return
    
    if player.resources["gold"] < player.cheer_cost:
        await ctx.send(f"❌ You need {player.cheer_cost} gold to cheer!")
        return
    
    player.resources["gold"] -= player.cheer_cost
    player.resources["happiness"] = min(100, player.resources["happiness"] + 10)
    player.cheer_cost += 50
    player.cheer_count += 1
    
    embed = guilded.Embed(
        title="🎉 Cheer Successful!",
        description=f"Your people are happier! (-{player.cheer_cost - 50} gold)",
        color=guilded.Color.gold()
    )
    embed.add_field(name="New Happiness", value=str(player.resources["happiness"]))
    embed.add_field(name="Next Cheer Cost", value=f"{player.cheer_cost} gold")
    await ctx.send(embed=embed)

@bot.command()
async def feed(ctx):
    """Feed your people (increasing cost)"""
    player = get_player(ctx.author.id)
    
    if player.in_civil_war:
        await ctx.send("❌ Food distribution is impossible during civil war!")
        return
    
    if player.resources["gold"] < player.feed_cost:
        await ctx.send(f"❌ You need {player.feed_cost} gold to feed your people!")
        return
    
    player.resources["gold"] -= player.feed_cost
    player.resources["hunger"] = min(3000, player.resources["hunger"] + 100)
    player.feed_cost += 20
    
    embed = guilded.Embed(
        title="🍗 Feeding Successful!",
        description=f"Your people are well fed! (-{player.feed_cost - 20} gold)",
        color=guilded.Color.green()
    )
    embed.add_field(name="New Hunger", value=str(player.resources["hunger"]))
    embed.add_field(name="Next Feed Cost", value=f"{player.feed_cost} gold")
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 3600, commands.BucketType.user)
async def build(ctx):
    """Build skyscrapers (500 gold, 1 hr cooldown)"""
    player = get_player(ctx.author.id)
    
    if player.in_civil_war:
        await ctx.send("❌ Construction halted due to civil unrest!")
        return
    
    if player.resources["gold"] < 500:
        await ctx.send("❌ You need 500 gold to build a skyscraper!")
        return
    
    player.resources["gold"] -= 500
    player.buildings += 1
    player.happiness_boost += 0.05
    player.resources["happiness"] = min(100, player.resources["happiness"] + 5)
    
    embed = guilded.Embed(
        title="🏗️ Building Constructed!",
        description="You built a magnificent skyscraper! (-500 gold)",
        color=guilded.Color.blue()
    )
    embed.add_field(name="Total Buildings", value=str(player.buildings))
    embed.add_field(name="Happiness Boost", value=f"x{player.happiness_boost:.2f}")
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
    
    if target.id in player.allies:
        await ctx.send("❌ You're already allied with this player!")
        return
    
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
async def unally(ctx, *, target_name: str = None):
    """Dissolve an alliance"""
    if target_name is None:
        await ctx.send("❌ Please mention a user to unally! Example: `.unally @Username`")
        return
    
    target = None
    if ctx.message.mentions:
        target = ctx.message.mentions[0]
    else:
        for member in await ctx.server.fetch_members():
            if target_name.lower() in member.name.lower():
                target = member
                break
    
    if not target:
        await ctx.send("❌ User not found!")
        return
    
    player = get_player(ctx.author.id)
    target_player = get_player(target.id)
    
    if target.id not in player.allies:
        await ctx.send("❌ You are not allies with this player!")
        return
    
    player.allies.remove(target.id)
    target_player.allies.remove(ctx.author.id)
    
    embed = guilded.Embed(
        title="🚫 Alliance Dissolved!",
        description=f"{ctx.author.mention} and {target.mention} are no longer allies.",
        color=guilded.Color.red()
    )
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 86400, commands.BucketType.user)
async def backstab(ctx, *, target_name: str = None):
    """Betray an ally (30% fail risk, 1-day cooldown)"""
    if target_name is None:
        await ctx.send("❌ Please mention an ally to backstab! Example: `.backstab @Username`")
        return
    
    target = None
    if ctx.message.mentions:
        target = ctx.message.mentions[0]
    else:
        for member in await ctx.server.fetch_members():
            if target_name.lower() in member.name.lower():
                target = member
                break
    
    if not target:
        await ctx.send("❌ User not found!")
        return
    
    player = get_player(ctx.author.id)
    target_player = get_player(target.id)
    
    if target.id not in player.allies:
        await ctx.send("❌ You can only backstab allies!")
        return
    
    # 30% chance of failure
    if random.random() < 0.3:
        player.resources["happiness"] = max(0, player.resources["happiness"] - 50)
        player.resources["soldiers"] = max(0, player.resources["soldiers"] - 20)
        
        embed = guilded.Embed(
            title="🔪 Backstab Failed!",
            description=f"Your betrayal of {target.mention} was discovered!",
            color=guilded.Color.red()
        )
        embed.add_field(name="Happiness Lost", value="-50")
        embed.add_field(name="Soldiers Lost", value="-20")
    else:
        # Successful backstab
        gold_stolen = int(target_player.resources["gold"] * 0.2)
        food_stolen = int(target_player.resources["food"] * 0.2)
        soldiers_stolen = int(target_player.resources["soldiers"] * 0.2)
        
        player.resources["gold"] += gold_stolen
        player.resources["food"] += food_stolen
        player.resources["soldiers"] += soldiers_stolen
        
        target_player.resources["gold"] = max(0, target_player.resources["gold"] - gold_stolen)
        target_player.resources["food"] = max(0, target_player.resources["food"] - food_stolen)
        target_player.resources["soldiers"] = max(0, target_player.resources["soldiers"] - soldiers_stolen)
        
        # Remove alliance
        player.allies.remove(target.id)
        target_player.allies.remove(ctx.author.id)
        
        embed = guilded.Embed(
            title="🗡️ Backstab Successful!",
            description=f"You betrayed {target.mention} and stole resources!",
            color=guilded.Color.dark_red()
        )
        embed.add_field(name="Gold Stolen", value=str(gold_stolen))
        embed.add_field(name="Food Stolen", value=str(food_stolen))
        embed.add_field(name="Soldiers Stolen", value=str(soldiers_stolen))
    
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 60, commands.BucketType.user)
async def gamble(ctx, amount: int):
    """50/50 gold gamble (loses 15 happiness, 1 min cooldown)"""
    player = get_player(ctx.author.id)
    
    if player.in_civil_war:
        await ctx.send("❌ Gambling is impossible during civil unrest!")
        return
    
    if amount <= 0:
        await ctx.send("❌ Amount must be positive!")
        return
    
    if player.resources["gold"] < amount:
        await ctx.send("❌ You don't have enough gold!")
        return
    
    if player.resources["happiness"] < 15:
        await ctx.send("❌ You need at least 15 happiness to gamble!")
        return
    
    player.resources["happiness"] -= 15
    player.resources["gold"] -= amount
    
    # 50% chance to win
    if random.random() < 0.5:
        winnings = amount * 2
        player.resources["gold"] += winnings
        embed = guilded.Embed(
            title="🎲 You Won!",
            description=f"Congratulations! You won {winnings} gold!",
            color=guilded.Color.green()
        )
    else:
        embed = guilded.Embed(
            title="🎲 You Lost!",
            description=f"Better luck next time! You lost {amount} gold.",
            color=guilded.Color.red()
        )
    
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 300, commands.BucketType.user)  # 5-minute cooldown
async def farm(ctx):
    """Grow food with a chance of poisonous mushrooms (5 min cooldown)"""
    player = get_player(ctx.author.id)
    
    if player.in_civil_war:
        await ctx.send("❌ Farming impossible during civil war!")
        return
    
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
@commands.cooldown(1, 60, commands.BucketType.user)
async def attack(ctx, *, target_name: str = None):
    """Declare war on another player (1 min cooldown)"""
    player = get_player(ctx.author.id)
    
    # Civil war self-attack
    if target_name and target_name.lower() == "yourself":
        if player.in_civil_war:
            player.civil_war_counter += 1
            casualties = random.randint(10, 30)
            player.resources["soldiers"] = max(0, player.resources["soldiers"] - casualties)
            
            embed = guilded.Embed(
                title="⚔️ CIVIL WAR BATTLE",
                description=random.choice(CIVIL_WAR_MESSAGES),
                color=guilded.Color.dark_red()
            )
            embed.add_field(name="Soldiers Lost", value=f"-{casualties}")
            
            if player.civil_war_counter >= 3:
                player.in_civil_war = False
                player.civil_war_counter = 0
                player.resources["happiness"] = 40  # Reset to neutral state
                embed.add_field(name="⚖️ WAR ENDED", value="You've restored order to your nation!", inline=False)
            
            await ctx.send(embed=embed)
            return
        else:
            await ctx.send("❌ You're not in a civil war! Attack other players instead.")
            return
    
    # Normal attack
    if target_name is None:
        await ctx.send("❌ Please mention a user to attack! Example: `.attack @Username`")
        return
    
    target = None
    if ctx.message.mentions:
        target = ctx.message.mentions[0]
    else:
        for member in await ctx.server.fetch_members():
            if target_name.lower() in member.name.lower():
                target = member
                break
    
    if not target:
        await ctx.send("❌ User not found!")
        return
    
    if target.id == ctx.author.id:
        await ctx.send("❌ Attack yourself with `.attack yourself` during civil wars!")
        return
        
    if target.bot:
        await ctx.send("❌ You can't attack bots!")
        return
    
    attacker = get_player(ctx.author.id)
    defender = get_player(target.id)
    
    if target.id in attacker.allies:
        await ctx.send("❌ You can't attack allies! Use `.backstab` instead")
        return
    
    if attacker.resources["soldiers"] < 10:
        await ctx.send("❌ You need at least 10 soldiers to attack!")
        return
    
    # Calculate battle scores
    attacker_score = attacker.resources["soldiers"] + random.randint(0, 50)
    defender_score = defender.resources["soldiers"] + random.randint(0, 50) + (defender.buildings * 10)
    
    # Underdog chance (25% for smaller army to win)
    underdog_win = False
    if (attacker.resources["soldiers"] < defender.resources["soldiers"] and random.random() < 0.25):
        underdog_win = True
        attacker_score = defender_score + 1000  # Force attacker win
    elif (defender.resources["soldiers"] < attacker.resources["soldiers"] and random.random() < 0.25):
        underdog_win = True
        defender_score = attacker_score + 1000  # Force defender win
    
    if attacker_score > defender_score:
        # Attacker wins
        gold_stolen = int(defender.resources["gold"] * 0.1)
        food_stolen = int(defender.resources["food"] * 0.1)
        
        attacker.resources["gold"] += gold_stolen
        attacker.resources["food"] += food_stolen
        attacker.resources["soldiers"] = int(attacker.resources["soldiers"] * 0.9)
        defender.resources["soldiers"] = int(defender.resources["soldiers"] * 0.8)
        
        embed = guilded.Embed(
            title="⚔️ Attack Successful!",
            description=f"{ctx.author.mention} defeated {target.mention} in battle!",
            color=guilded.Color.green()
        )
        if underdog_win:
            embed.description = f"{ctx.author.mention} {random.choice(UNDERDOG_VICTORY_MESSAGES)}"
        embed.add_field(name="Gold Stolen", value=str(gold_stolen))
        embed.add_field(name="Food Stolen", value=str(food_stolen))
        embed.add_field(name="Your Soldiers Lost", value="10%")
        embed.add_field(name="Enemy Soldiers Lost", value="20%")
    else:
        # Defender wins
        attacker.resources["gold"] = max(0, attacker.resources["gold"] - 50)
        attacker.resources["soldiers"] = int(attacker.resources["soldiers"] * 0.8)
        defender.resources["soldiers"] = int(defender.resources["soldiers"] * 0.9)
        
        embed = guilded.Embed(
            title="🛡️ Defense Successful!",
            description=f"{target.mention} repelled {ctx.author.mention}'s attack!",
            color=guilded.Color.red()
        )
        if underdog_win:
            embed.description = f"{target.mention} {random.choice(UNDERDOG_VICTORY_MESSAGES)}"
        embed.add_field(name="Your Gold Lost", value="50")
        embed.add_field(name="Your Soldiers Lost", value="20%")
        embed.add_field(name="Enemy Soldiers Lost", value="10%")
    
    await ctx.send(embed=embed)

@bot.command()
async def help(ctx):
    """Show organized command help"""
    embed = guilded.Embed(
        title="🛠️ Warbot Command Center",
        description="Manage your civilization and wage wars!",
        color=guilded.Color.dark_gold()
    )
    
    # Civilization Management
    embed.add_field(
        name="🏰 CIVILIZATION MANAGEMENT",
        value=(
            "`.start` - Create your civilization\n"
            "`.resources [user]` - View resources\n"
            "`.build` - Construct buildings (1hr cooldown)\n"
            "`.cheer` - Boost happiness (increasing cost)\n"
            "`.feed` - Reduce hunger (increasing cost)\n"
            "`.buy <item>` - Purchase resources/resets"
        ),
        inline=False
    )
    
    # Military Commands
    embed.add_field(
        name="⚔️ MILITARY COMMANDS",
        value=(
            "`.attack @user` - Declare war (1 min cooldown)\n"
            "`.attack yourself` - Fight civil war battles\n"
            "`.gamble <amount>` - Risk gold (1 min cooldown)\n"
            "`.backstab @ally` - Betray an ally (1 day cooldown)"
        ),
        inline=False
    )
    
    # Economy & Resources
    embed.add_field(
        name="💰 ECONOMY & RESOURCES",
        value=(
            "`.gather` - Collect resources (5 min cooldown)\n"
            "`.farm` - Grow food with risk (5 min cooldown)\n"
            "`.send <resource> <amount> @user` - Send resources\n"
            "`.buy <item>` - Purchase resources/resets"
        ),
        inline=False
    )
    
    # Diplomacy
    embed.add_field(
        name="🤝 DIPLOMACY",
        value=(
            "`.ally @user` - Form an alliance\n"
            "`.unally @user` - Dissolve alliance\n"
            "`.allies` - List your current allies\n"
            "`.send <resource> <amount> @user` - Aid allies"
        ),
        inline=False
    )
    
    # Civil War Info
    embed.add_field(
        name="⚠️ CIVIL WAR MECHANIC",
        value=(
            "When happiness drops below 30:\n"
            "- All commands except attack are blocked\n"
            "- Use `.attack yourself` 3 times to end war\n"
            "- Each battle causes soldier casualties"
        ),
        inline=False
    )
    
    embed.set_footer(text="Warbot v6.0 | Civil Wars & Underdog Battles")
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
