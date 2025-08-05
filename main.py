#!/usr/bin/env python3
"""
WarBot - Complete Guilded Civilization Management Bot
Enhanced with Espionage, Natural Disasters, Messaging & GIFs
"""

import os
import asyncio
import time
import threading
import random
from datetime import datetime, timedelta
from flask import Flask, render_template_string
import guilded
from guilded.ext import commands

# =============================================================================
# MODELS AND DATA STORAGE
# =============================================================================

class Player:
    """Enhanced player data model with espionage and messaging"""
    def __init__(self, user_id):
        self.user_id = user_id
        self.name = None  # Civilization name
        
        # Resources
        self.resources = {
            "gold": 1000,
            "food": 500,
            "soldiers": 100,
            "happiness": 500,
            "hunger": 1000
        }
        
        # Buildings
        self.buildings = {
            "houses": 0,
            "farms": 0,
            "barracks": 0,
            "walls": 0,
            "warplanes": 0,
            "fighter_jets": 0,
            "tanks": 0
        }
        
        # Military & Espionage
        self.military_units = {
            "mi6_civilians": 0  # Fake operatives
        }
        self.espionage = {
            "spy_level": 1,
            "spy_attempts": 0,
            "max_spies": 3,
            "spy_success_rate": 0.6
        }
        
        # Communications
        self.mailbox = []  # Received messages
        self.sent_mail = []  # Sent messages
        
        # Alliances & Cooldowns
        self.alliances = set()
        self.last_gather = 0
        self.last_build = 0
        self.last_buy = 0
        self.last_farm = 0
        self.last_attack = 0
        self.last_cheer = 0
        self.last_feed = 0
        self.last_gamble = 0
        self.last_civil_war = 0
        self.last_ally = 0
        self.last_break = 0
        self.last_passive = time.time()
        self.last_hunger_penalty = time.time()
        self.last_train = 0
        self.last_spy = 0
        self.last_sabotage = 0
        self.last_hack = 0
        self.cheer_cost = 100
        self.cheer_count = 0
        self.feed_cost = 50

# Global player storage
players = {}

def get_player(user_id):
    """Get or create player"""
    if user_id not in players:
        players[user_id] = Player(user_id)
    return players[user_id]

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def is_night_in_uae():
    """Check if it's night time in UAE (UTC+4)"""
    try:
        uae_time = datetime.utcnow() + timedelta(hours=4)
        hour = uae_time.hour
        return hour >= 22 or hour <= 6  # 10 PM to 6 AM
    except:
        return False

def format_cooldown_time(seconds):
    """Format cooldown time as MM:SS"""
    if seconds <= 0:
        return "0:00"
    
    minutes = int(seconds // 60)
    remaining_seconds = int(seconds % 60)
    return f"{minutes}:{remaining_seconds:02d}"

def create_embed(title, description, color=0x00ff00):
    """Create a standardized embed"""
    embed = guilded.Embed(title=title, description=description, color=color)
    return embed

def calculate_battle_power(player):
    """Calculate total battle power"""
    soldiers = player.resources["soldiers"]
    happiness = player.resources["happiness"]
    
    # Base power from soldiers
    base_power = soldiers * 10
    
    # Happiness multiplier (1.0 to 2.5x based on happiness 0-1000)
    happiness_multiplier = 1.0 + (happiness / 1000) * 1.5
    
    # Military unit bonuses
    warplane_bonus = player.buildings["warplanes"] * 500
    jet_bonus = player.buildings["fighter_jets"] * 750
    tank_bonus = player.buildings["tanks"] * 300
    mi6_bonus = player.military_units["mi6_civilians"] * 150
    
    # Espionage bonus
    spy_bonus = player.espionage["spy_level"] * 50
    
    total_power = (base_power * happiness_multiplier) + warplane_bonus + jet_bonus + tank_bonus + mi6_bonus + spy_bonus
    return int(total_power)

def calculate_discount(player):
    """Calculate total discount percentage"""
    happiness_discount = min(player.resources["happiness"] * 0.01, 100)  # 1% per happiness point
    building_discount = sum(player.buildings.values()) * 5  # 5% per building
    total_discount = min(happiness_discount + building_discount, 90)  # Max 90% discount
    return total_discount

def calculate_spy_success(attacker, defender):
    """Calculate spy success based on levels and randomness"""
    base_chance = attacker.espionage["spy_success_rate"]
    level_diff = attacker.espionage["spy_level"] - defender.espionage["spy_level"]
    bonus = min(level_diff * 0.1, 0.3)
    return min(0.9, base_chance + bonus + random.uniform(-0.2, 0.2))

def trigger_natural_disaster():
    """Randomly trigger disasters affecting all players"""
    disasters = [
        {"name": "Earthquake", "gold_loss": 0.15, "food_loss": 0.2, "soldier_loss": 0.05},
        {"name": "Drought", "gold_loss": 0.1, "food_loss": 0.3, "soldier_loss": 0.02},
        {"name": "Plague", "gold_loss": 0.2, "food_loss": 0.1, "soldier_loss": 0.25},
        {"name": "Tornado", "gold_loss": 0.12, "food_loss": 0.15, "soldier_loss": 0.08},
        {"name": "Flood", "gold_loss": 0.18, "food_loss": 0.25, "soldier_loss": 0.03}
    ]
    
    if random.random() < 0.03:  # 3% chance per cycle
        disaster = random.choice(disasters)
        return disaster
    return None

# =============================================================================
# BOT SETUP AND BACKGROUND TASKS
# =============================================================================

# Bot setup
bot = commands.Bot(command_prefix='.', help_command=None)

# Background task for passive effects
async def passive_effects():
    """Background task to handle passive resource changes and disasters"""
    await bot.wait_until_ready()
    while True:
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
                
                # Reset spy attempts daily
                if now - player.last_passive > 86400:  # 24 hours
                    player.espionage["spy_attempts"] = 0
                
                # Reset costs after 4 days (345,600 seconds)
                if now - player.last_passive > 345600:
                    player.cheer_cost = 100
                    player.cheer_count = 0
                    player.feed_cost = 50
                    
            except Exception as e:
                print(f"Error processing passive effects for player {player_id}: {e}")
        
        # Check for natural disasters
        disaster = trigger_natural_disaster()
        if disaster:
            print(f"🌪️ Natural disaster triggered: {disaster['name']}")
            
            for player_id, player in list(players.items()):
                gold_loss = int(player.resources["gold"] * disaster["gold_loss"])
                food_loss = int(player.resources["food"] * disaster["food_loss"])
                soldier_loss = int(player.resources["soldiers"] * disaster["soldier_loss"])
                
                player.resources["gold"] = max(0, player.resources["gold"] - gold_loss)
                player.resources["food"] = max(0, player.resources["food"] - food_loss)
                player.resources["soldiers"] = max(0, player.resources["soldiers"] - soldier_loss)
                
                # Send disaster notification
                try:
                    user = await bot.fetch_user(player_id)
                    await user.send(f"🚨 **{disaster['name']}** struck your nation!\n💰 -{gold_loss} gold\n🌾 -{food_loss} food\n⚔️ -{soldier_loss} soldiers")
                except:
                    pass
        
        await asyncio.sleep(30)  # Check every 30 seconds

# Async setup hook
@bot.event
async def setup_hook():
    """Setup background tasks"""
    bot.loop.create_task(passive_effects())

# Bot events
@bot.event
async def on_ready():
    """Event fired when bot is ready"""
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    print('------')
    print("Bot is ready!")

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors"""
    if isinstance(error, commands.CommandOnCooldown):
        cooldown_time = format_cooldown_time(int(error.retry_after))
        await ctx.send(f"⏱️ Command on cooldown! Try again in {cooldown_time}")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing required argument: {error.param}")
    elif isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Unknown command! Use `.help` for available commands.")
    else:
        print(f"Unhandled error: {error}")
        await ctx.send("❌ An error occurred while processing your command.")

# =============================================================================
# BASIC COMMANDS
# =============================================================================

@bot.command()
async def start(ctx, *, civilization_name=None):
    """Initialize your civilization with a name (one-time command)"""
    player = get_player(str(ctx.author.id))
    
    if player.name is not None:
        embed = create_embed("🏰 Civilization Already Exists", 
                           f"Your civilization '{player.name}' is already established!\nUse `.status` to check your progress.", 
                           0xff9900)
        await ctx.send(embed=embed)
        return
    
    if not civilization_name:
        embed = create_embed("❌ Missing Civilization Name", 
                           "Please provide a name for your civilization!\nExample: `.start Roman Empire`", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    if len(civilization_name) > 50:
        embed = create_embed("❌ Name Too Long", 
                           "Civilization name must be 50 characters or less!", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    # Set civilization name
    player.name = civilization_name
    
    embed = create_embed("🎉 Civilization Founded!", 
                       f"Welcome to **{civilization_name}**!\n\n" +
                       "🏆 **Starting Resources:**\n" +
                       f"💰 Gold: {player.resources['gold']}\n" +
                       f"🌾 Food: {player.resources['food']}\n" +
                       f"⚔️ Soldiers: {player.resources['soldiers']}\n" +
                       f"😊 Happiness: {player.resources['happiness']}\n" +
                       f"🍽️ Hunger: {player.resources['hunger']}\n\n" +
                       "Use `.help` to see available commands!")
    
    await ctx.send(embed=embed)

@bot.command()
async def status(ctx):
    """Check your civilization status"""
    player = get_player(str(ctx.author.id))
    
    if player.name is None:
        embed = create_embed("❌ No Civilization", 
                           "You haven't started your civilization yet!\nUse `.start <name>` to begin.", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    # Calculate battle power and discount
    battle_power = calculate_battle_power(player)
    discount = calculate_discount(player)
    
    embed = create_embed(f"🏰 {player.name} Status", "Your civilization overview")
    
    # Resources
    resources_text = ""
    for resource, amount in player.resources.items():
        emoji = {"gold": "💰", "food": "🌾", "soldiers": "⚔️", "happiness": "😊", "hunger": "🍽️"}
        resources_text += f"{emoji[resource]} {resource.title()}: {amount}\n"
    
    embed.add_field(name="📊 Resources", value=resources_text, inline=True)
    
    # Buildings
    buildings_text = ""
    building_emojis = {
        "houses": "🏠", "farms": "🚜", "barracks": "🏛️", "walls": "🧱",
        "warplanes": "✈️", "fighter_jets": "🛩️", "tanks": "🚗"
    }
    for building, count in player.buildings.items():
        if count > 0:
            emoji = building_emojis.get(building, "🏗️")
            buildings_text += f"{emoji} {building.replace('_', ' ').title()}: {count}\n"
    
    if not buildings_text:
        buildings_text = "No buildings constructed"
    
    embed.add_field(name="🏗️ Buildings", value=buildings_text, inline=True)
    
    # Military Units
    military_text = ""
    if player.military_units["mi6_civilians"] > 0:
        military_text += f"🕵️ MI6 Civilians: {player.military_units['mi6_civilians']}\n"
    
    if not military_text:
        military_text = "No special units"
    
    embed.add_field(name="🎯 Special Units", value=military_text, inline=True)
    
    # Espionage
    embed.add_field(name="🕵️ Espionage", 
                   value=f"Spy Level: {player.espionage['spy_level']}\n"
                         f"Spy Attempts: {player.espionage['spy_attempts']}/{player.espionage['max_spies']}", 
                   inline=True)
    
    # Communications
    embed.add_field(name="📧 Messages", 
                   value=f"Inbox: {len(player.mailbox)} unread\nSent: {len(player.sent_mail)}", 
                   inline=True)
    
    # Combat stats and discounts
    embed.add_field(name="⚔️ Battle Power", value=f"{battle_power:,}", inline=True)
    embed.add_field(name="💸 Shop Discount", value=f"{discount:.1f}%", inline=True)
    
    # Alliances
    if player.alliances:
        alliance_list = [f"<@{ally}>" for ally in list(player.alliances)[:5]]
        embed.add_field(name="🤝 Alliances", value="\n".join(alliance_list), inline=True)
    
    await ctx.send(embed=embed)

@bot.command()
async def help(ctx, command_name=None):
    """Show all commands or detailed help for a specific command"""
    if command_name:
        # Show specific command help
        command = bot.get_command(command_name)
        if command:
            embed = create_embed(f"📋 Command: .{command.name}", command.help or "No description available.")
            if command.aliases:
                embed.add_field(name="Aliases", value=", ".join(command.aliases), inline=False)
        else:
            embed = create_embed("❌ Command Not Found", f"Command '{command_name}' does not exist.")
    else:
        # Show all commands
        embed = create_embed("🏰 WarBot Commands", "Complete civilization management system!")
        
        basic_commands = [
            "`.start <name>` - Initialize your civilization with a name",
            "`.status` - Check your civilization status",
            "`.help [command]` - Show this help or get command details"
        ]
        
        economy_commands = [
            "`.gather` - Collect resources (1 min cooldown)",
            "`.build <item>` - Construct buildings (2 min cooldown)",
            "`.buy <item> [amount]` - Purchase resources/units (1.5 min cooldown)",
            "`.farm` - Farm food with chance for money (2 min cooldown)",
            "`.cheer` - Boost happiness (1.5 min cooldown)",
            "`.feed` - Restore hunger levels (2 min cooldown)",
            "`.gamble <amount>` - Risk gold for rewards (3 min cooldown)"
        ]
        
        combat_commands = [
            "`.attack <@user>` - Attack another player (1.5 min cooldown)",
            "`.civil_war` - Internal conflict for resources (2.5 min cooldown)",
            "`.train` - Train soldiers & improve spies (2.5 min cooldown)"
        ]
        
        espionage_commands = [
            "`.spy @user` - Gather intelligence (3 min cooldown)",
            "`.sabotage @user` - Damage enemy military (5 min cooldown)",
            "`.hack @user` - Steal happiness & gold (4 min cooldown)"
        ]
        
        alliance_commands = [
            "`.ally <@user>` - Form alliance (2 min cooldown)",
            "`.break <@user>` - Break alliance (2 min cooldown)"
        ]
        
        communication_commands = [
            "`.send @user message` - Send diplomatic message",
            "`.mail` - Check your messages"
        ]
        
        embed.add_field(name="🏛️ Basic Commands", value="\n".join(basic_commands), inline=False)
        embed.add_field(name="💰 Economy Commands", value="\n".join(economy_commands), inline=False)
        embed.add_field(name="⚔️ Combat Commands", value="\n".join(combat_commands), inline=False)
        embed.add_field(name="🕵️ Espionage Commands", value="\n".join(espionage_commands), inline=False)
        embed.add_field(name="🤝 Alliance Commands", value="\n".join(alliance_commands), inline=False)
        embed.add_field(name="📧 Communication Commands", value="\n".join(communication_commands), inline=False)
        
    await ctx.send(embed=embed)

# =============================================================================
# ECONOMY COMMANDS
# =============================================================================

@bot.command()
@commands.cooldown(1, 60, commands.BucketType.user)  # 1-minute cooldown
async def gather(ctx):
    """Collect resources (1 min cooldown)"""
    player = get_player(str(ctx.author.id))
    
    if player.name is None:
        embed = create_embed("❌ No Civilization", 
                           "You need to start your civilization first! Use `.start <name>`", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    # Base amounts
    base_gold = random.randint(80, 150)
    base_food = random.randint(60, 120)
    base_soldiers = random.randint(5, 15)
    
    # Night bonus in UAE
    multiplier = 1.5 if is_night_in_uae() else 1.0
    bonus_text = " (🌙 Night bonus!)" if is_night_in_uae() else ""
    
    # Apply multiplier
    gold_gained = int(base_gold * multiplier)
    food_gained = int(base_food * multiplier) 
    soldiers_gained = int(base_soldiers * multiplier)
    
    # Add to resources
    player.resources["gold"] += gold_gained
    player.resources["food"] += food_gained
    player.resources["soldiers"] += soldiers_gained
    
    embed = create_embed("⛏️ Resources Gathered!", f"Your workers have been busy!{bonus_text}")
    embed.add_field(name="💰 Gold", value=f"+{gold_gained}", inline=True)
    embed.add_field(name="🌾 Food", value=f"+{food_gained}", inline=True)
    embed.add_field(name="⚔️ Soldiers", value=f"+{soldiers_gained}", inline=True)
    
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 120, commands.BucketType.user)  # 2-minute cooldown
async def build(ctx, *, item=None):
    """Build structures to improve your civilization (2 min cooldown)"""
    player = get_player(str(ctx.author.id))
    
    if player.name is None:
        embed = create_embed("❌ No Civilization", 
                           "You need to start your civilization first! Use `.start <name>`", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    if not item:
        embed = create_embed("🏗️ Available Buildings", "Choose what to build:")
        
        basic_buildings = [
            "**house** - Cost: 200 gold, 100 food (+50 happiness)",
            "**farm** - Cost: 150 gold (+food production)",
            "**barracks** - Cost: 300 gold, 200 food (+soldier training)",
            "**walls** - Cost: 400 gold, 150 food (+defense)"
        ]
        
        military_buildings = [
            "**warplane** - Cost: 1000 gold, 500 food (massive attack bonus)",
            "**fighter_jet** - Cost: 1500 gold, 750 food (superior air power)",
            "**tank** - Cost: 800 gold, 400 food (ground dominance)"
        ]
        
        embed.add_field(name="🏘️ Basic Buildings", value="\n".join(basic_buildings), inline=False)
        embed.add_field(name="🚁 Military Vehicles", value="\n".join(military_buildings), inline=False)
        embed.add_field(name="Usage", value="Example: `.build house`", inline=False)
        
        await ctx.send(embed=embed)
        return
    
    # Building costs and requirements
    buildings = {
        "house": {"gold": 200, "food": 100, "happiness": 50},
        "farm": {"gold": 150, "food": 0, "effect": "food_production"},
        "barracks": {"gold": 300, "food": 200, "effect": "soldier_training"},
        "walls": {"gold": 400, "food": 150, "effect": "defense"},
        "warplane": {"gold": 1000, "food": 500, "effect": "air_superiority"},
        "fighter_jet": {"gold": 1500, "food": 750, "effect": "elite_air_power"},
        "tank": {"gold": 800, "food": 400, "effect": "ground_control"}
    }
    
    building_name = item.lower().replace(" ", "_")
    if building_name not in buildings:
        embed = create_embed("❌ Unknown Building", 
                           f"'{item}' is not a valid building. Use `.build` to see options.", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    building_data = buildings[building_name]
    gold_cost = building_data["gold"]
    food_cost = building_data.get("food", 0)
    
    # Check if player has enough resources
    if player.resources["gold"] < gold_cost or player.resources["food"] < food_cost:
        embed = create_embed("❌ Insufficient Resources", 
                           f"Need {gold_cost} gold and {food_cost} food to build {building_name.replace('_', ' ')}")
        embed.add_field(name="Your Resources", 
                       value=f"💰 {player.resources['gold']} gold\n🌾 {player.resources['food']} food")
        await ctx.send(embed=embed)
        return
    
    # Deduct costs
    player.resources["gold"] -= gold_cost
    player.resources["food"] -= food_cost
    
    # Add building
    player.buildings[building_name] += 1
    
    # Apply effects
    effect_text = ""
    if "happiness" in building_data:
        player.resources["happiness"] += building_data["happiness"]
        effect_text = f"\n+{building_data['happiness']} happiness!"
    
    building_emojis = {
        "house": "🏠", "farm": "🚜", "barracks": "🏛️", "walls": "🧱",
        "warplane": "✈️", "fighter_jet": "🛩️", "tank": "🚗"
    }
    
    emoji = building_emojis.get(building_name, "🏗️")
    embed = create_embed("🏗️ Construction Complete!", 
                       f"{emoji} {building_name.replace('_', ' ').title()} has been built!{effect_text}")
    embed.add_field(name="Costs", value=f"💰 -{gold_cost} gold\n🌾 -{food_cost} food", inline=True)
    embed.add_field(name="Total Built", value=f"{player.buildings[building_name]}", inline=True)
    
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 90, commands.BucketType.user)  # 1.5-minute cooldown
async def buy(ctx, item=None, amount=1):
    """Purchase resources and military units from the shop (1.5 min cooldown)"""
    player = get_player(str(ctx.author.id))
    
    if player.name is None:
        embed = create_embed("❌ No Civilization", 
                           "You need to start your civilization first! Use `.start <name>`", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    if not item:
        # Show shop with current discount
        discount = calculate_discount(player)
        
        embed = create_embed("🛒 Civilization Shop", f"Your discount: {discount:.1f}%")
        
        # Base prices (before discount)
        base_prices = {
            "soldiers": {"price": 50, "currency": "gold", "description": "Expand your army"},
            "food": {"price": 30, "currency": "gold", "description": "Feed your people"},
            "mi6_civilians": {"price": 200, "currency": "gold", "description": "Fake operatives (combat bonus)"}
        }
        
        shop_items = []
        for item_name, data in base_prices.items():
            discounted_price = int(data["price"] * (1 - discount/100))
            shop_items.append(f"**{item_name}** - {discounted_price} {data['currency']} ({data['description']})")
        
        embed.add_field(name="📦 Available Items", value="\n".join(shop_items), inline=False)
        embed.add_field(name="💡 Discount Info", 
                       value=f"• Happiness: {min(player.resources['happiness'] * 0.01, 100):.1f}%\n" +
                             f"• Buildings: {sum(player.buildings.values()) * 5}%", 
                       inline=False)
        embed.add_field(name="Usage", value="Example: `.buy soldiers 10`", inline=False)
        
        await ctx.send(embed=embed)
        return
    
    # Validate amount
    try:
        amount = max(1, int(amount))
    except (ValueError, TypeError):
        amount = 1
    
    # Shop items with base prices
    shop_items = {
        "soldiers": {"price": 50, "currency": "gold", "resource": "soldiers"},
        "food": {"price": 30, "currency": "gold", "resource": "food"},
        "mi6_civilians": {"price": 200, "currency": "gold", "military_unit": "mi6_civilians"}
    }
    
    item_name = item.lower()
    if item_name not in shop_items:
        embed = create_embed("❌ Item Not Found", 
                           f"'{item}' is not available in the shop. Use `.buy` to see options.", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    item_data = shop_items[item_name]
    
    # Calculate discounted price
    discount = calculate_discount(player)
    base_price = item_data["price"]
    discounted_price = int(base_price * (1 - discount/100))
    total_cost = discounted_price * amount
    
    currency = item_data["currency"]
    
    # Check if player has enough currency
    if player.resources[currency] < total_cost:
        embed = create_embed("❌ Insufficient Funds", 
                           f"Need {total_cost} {currency} to buy {amount} {item_name.replace('_', ' ')}")
        embed.add_field(name="Your Resources", value=f"💰 {player.resources[currency]} {currency}")
        await ctx.send(embed=embed)
        return
    
    # Process purchase
    player.resources[currency] -= total_cost
    
    if "resource" in item_data:
        player.resources[item_data["resource"]] += amount
        target_display = f"{item_data['resource']}"
    elif "military_unit" in item_data:
        player.military_units[item_data["military_unit"]] += amount
        target_display = f"{item_data['military_unit'].replace('_', ' ')}"
    
    embed = create_embed("🛍️ Purchase Complete!", 
                       f"Successfully bought {amount} {item_name.replace('_', ' ')}!")
    embed.add_field(name="Cost", value=f"💰 -{total_cost} {currency}", inline=True)
    embed.add_field(name="Discount Applied", value=f"{discount:.1f}%", inline=True)
    embed.add_field(name="Items Received", value=f"+{amount} {target_display}", inline=True)
    
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 120, commands.BucketType.user)  # 2-minute cooldown
async def farm(ctx):
    """Farm food and sometimes earn money (2 min cooldown)"""
    player = get_player(str(ctx.author.id))
    
    if player.name is None:
        embed = create_embed("❌ No Civilization", 
                           "You need to start your civilization first! Use `.start <name>`", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    # Base farming amounts
    base_food = random.randint(100, 200)
    
    # 25% chance of failure with humorous messages
    if random.random() < 0.25:
        failure_messages = [
            "🐛 Your crops were eaten by locusts!",
            "🌧️ A sudden flood washed away your fields!",
            "🔥 Drought scorched your farmland!",
            "🦅 Birds stole all your seeds!",
            "🧙 A wizard cursed your soil!",
            "💸 You bought fake seeds from a scammer!",
            "🍄 Your crops grew moldy and inedible!"
        ]
        
        failure_msg = random.choice(failure_messages)
        # Small consolation prize
        consolation_gold = random.randint(10, 30)
        player.resources["gold"] += consolation_gold
        
        embed = create_embed("🚜 Farming Failed!", failure_msg, 0xff9900)
        embed.add_field(name="Consolation Prize", value=f"💰 +{consolation_gold} gold (insurance payout)", inline=False)
        await ctx.send(embed=embed)
        return
    
    # Successful farming
    food_gained = base_food
    player.resources["food"] += food_gained
    
    # 30% chance for bonus money from selling extra crops
    bonus_gold = 0
    bonus_text = ""
    if random.random() < 0.3:
        bonus_gold = random.randint(50, 120)
        player.resources["gold"] += bonus_gold
        bonus_text = f"\n💰 Bonus: +{bonus_gold} gold from selling surplus crops!"
    
    embed = create_embed("🚜 Successful Harvest!", 
                       f"Your farming efforts paid off!{bonus_text}")
    embed.add_field(name="🌾 Food Gained", value=f"+{food_gained}", inline=True)
    if bonus_gold > 0:
        embed.add_field(name="💰 Gold Bonus", value=f"+{bonus_gold}", inline=True)
    
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 90, commands.BucketType.user)  # 1.5-minute cooldown  
async def cheer(ctx):
    """Boost your civilization's happiness (1.5 min cooldown)"""
    player = get_player(str(ctx.author.id))
    
    if player.name is None:
        embed = create_embed("❌ No Civilization", 
                           "You need to start your civilization first! Use `.start <name>`", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    # Check if player has enough gold
    if player.resources["gold"] < player.cheer_cost:
        embed = create_embed("❌ Insufficient Gold", 
                           f"Need {player.cheer_cost} gold to organize celebration!")
        embed.add_field(name="Your Gold", value=f"💰 {player.resources['gold']}")
        await ctx.send(embed=embed)
        return
    
    # Deduct cost and increase happiness
    player.resources["gold"] -= player.cheer_cost
    happiness_gain = random.randint(80, 150)
    player.resources["happiness"] += happiness_gain
    
    # Increase cost for next cheer and increment counter
    player.cheer_count += 1
    player.cheer_cost += 50  # Increases by 50 each use
    
    embed = create_embed("🎉 Celebration Organized!", 
                       "Your people are cheering with joy!")
    embed.add_field(name="😊 Happiness Gained", value=f"+{happiness_gain}", inline=True)
    embed.add_field(name="💰 Cost Paid", value=f"-{player.cheer_cost - 50} gold", inline=True)
    embed.add_field(name="Next Cost", value=f"{player.cheer_cost} gold", inline=True)
    
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 120, commands.BucketType.user)  # 2-minute cooldown
async def feed(ctx):
    """Restore your people's hunger levels (2 min cooldown)"""
    player = get_player(str(ctx.author.id))
    
    if player.name is None:
        embed = create_embed("❌ No Civilization", 
                           "You need to start your civilization first! Use `.start <name>`", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    # Check if player has enough food
    if player.resources["food"] < player.feed_cost:
        embed = create_embed("❌ Insufficient Food", 
                           f"Need {player.feed_cost} food to feed your people!")
        embed.add_field(name="Your Food", value=f"🌾 {player.resources['food']}")
        await ctx.send(embed=embed)
        return
    
    # Deduct cost and restore hunger
    player.resources["food"] -= player.feed_cost
    hunger_restored = random.randint(200, 350)
    player.resources["hunger"] = min(1000, player.resources["hunger"] + hunger_restored)
    
    # Increase cost for next feeding
    player.feed_cost += 25  # Increases by 25 each use
    
    embed = create_embed("🍽️ People Fed!", 
                       "Your citizens have been well-fed!")
    embed.add_field(name="🍽️ Hunger Restored", value=f"+{hunger_restored}", inline=True)
    embed.add_field(name="🌾 Food Used", value=f"-{player.feed_cost - 25}", inline=True)
    embed.add_field(name="Next Cost", value=f"{player.feed_cost} food", inline=True)
    
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 180, commands.BucketType.user)  # 3-minute cooldown
async def gamble(ctx, amount=None):
    """Risk gold for potential rewards (3 min cooldown)"""
    player = get_player(str(ctx.author.id))
    
    if player.name is None:
        embed = create_embed("❌ No Civilization", 
                           "You need to start your civilization first! Use `.start <name>`", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    if not amount:
        embed = create_embed("🎰 Gambling Rules", 
                           "Risk your gold for potential rewards!")
        embed.add_field(name="How to Play", value="`.gamble <amount>` - Bet gold for rewards", inline=False)
        embed.add_field(name="Possible Outcomes", 
                       value="🎯 50% chance: Win 1.5x your bet\n💰 25% chance: Win 2x your bet\n💎 15% chance: Win 3x your bet\n👑 10% chance: Win 5x your bet", 
                       inline=False)
        embed.add_field(name="Example", value="`.gamble 100` - Risk 100 gold", inline=False)
        await ctx.send(embed=embed)
        return
    
    try:
        bet_amount = int(amount)
        if bet_amount <= 0:
            raise ValueError("Amount must be positive")
    except ValueError:
        embed = create_embed("❌ Invalid Amount", 
                           "Please enter a valid positive number!", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    if player.resources["gold"] < bet_amount:
        embed = create_embed("❌ Insufficient Gold", 
                           f"You only have {player.resources['gold']} gold!")
        await ctx.send(embed=embed)
        return
    
    # Deduct bet amount
    player.resources["gold"] -= bet_amount
    
    # Determine outcome (60% chance of winning something)
    roll = random.random()
    
    if roll < 0.4:  # 40% chance - lose everything
        embed = create_embed("🎰 Bad Luck!", 
                           f"You lost {bet_amount} gold! Better luck next time.", 
                           0xff0000)
    elif roll < 0.65:  # 25% chance - win 1.5x
        winnings = int(bet_amount * 1.5)
        player.resources["gold"] += winnings
        embed = create_embed("🎰 Small Win!", 
                           f"You won {winnings} gold! (1.5x return)", 
                           0x00ff00)
    elif roll < 0.85:  # 20% chance - win 2x
        winnings = bet_amount * 2
        player.resources["gold"] += winnings
        embed = create_embed("🎰 Good Win!", 
                           f"You won {winnings} gold! (2x return)", 
                           0x00ff00)
    elif roll < 0.95:  # 10% chance - win 3x
        winnings = bet_amount * 3
        player.resources["gold"] += winnings
        embed = create_embed("🎰 Great Win!", 
                           f"You won {winnings} gold! (3x return)", 
                           0x00ff00)
    else:  # 5% chance - win 5x
        winnings = bet_amount * 5
        player.resources["gold"] += winnings
        embed = create_embed("🎰 YOU HIT THE JACKPOT!", 
                           f"You won {winnings} gold! (5x return)", 
                           0xffd700)
    
    embed.add_field(name="Current Gold", value=f"💰 {player.resources['gold']}", inline=True)
    await ctx.send(embed=embed)

# =============================================================================
# COMBAT COMMANDS
# =============================================================================

@bot.command()
@commands.cooldown(1, 90, commands.BucketType.user)  # 1.5-minute cooldown
async def attack(ctx, target: guilded.Member = None):
    """Attack another player's civilization (1.5 min cooldown)"""
    attacker = get_player(str(ctx.author.id))
    
    if attacker.name is None:
        embed = create_embed("❌ No Civilization", 
                           "You need to start your civilization first! Use `.start <name>`", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    if not target:
        embed = create_embed("❌ No Target", 
                           "You must specify a target to attack!\nExample: `.attack @username`", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    if str(target.id) == str(ctx.author.id):
        embed = create_embed("❌ Self Attack", 
                           "You cannot attack yourself! Use `.civil_war` for internal conflict.", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    defender = get_player(str(target.id))
    
    if defender.name is None:
        embed = create_embed("❌ Invalid Target", 
                           "Target player hasn't started their civilization yet!", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    # Check for alliance
    if str(target.id) in attacker.alliances:
        embed = create_embed("❌ Allied Nation", 
                           f"You cannot attack {defender.name} - you are allied!\nUse `.break @{target.name}` to end the alliance first.", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    # Check if attacker has enough soldiers
    if attacker.resources["soldiers"] < 10:
        embed = create_embed("❌ Insufficient Army", 
                           "You need at least 10 soldiers to launch an attack!", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    # Calculate battle powers
    attacker_power = calculate_battle_power(attacker)
    defender_power = calculate_battle_power(defender)
    
    # Add some randomness (±20%)
    attacker_roll = attacker_power * random.uniform(0.8, 1.2)
    defender_roll = defender_power * random.uniform(0.8, 1.2)
    
    # Determine winner
    if attacker_roll > defender_roll:
        # Attacker wins
        victory_margin = (attacker_roll - defender_roll) / defender_roll
        
        # Calculate losses (both sides lose soldiers)
        attacker_losses = max(1, int(attacker.resources["soldiers"] * random.uniform(0.05, 0.15)))
        defender_losses = max(1, int(defender.resources["soldiers"] * random.uniform(0.15, 0.30)))
        
        # Apply losses
        attacker.resources["soldiers"] = max(0, attacker.resources["soldiers"] - attacker_losses)
        defender.resources["soldiers"] = max(0, defender.resources["soldiers"] - defender_losses)
        
        # Calculate spoils based on victory margin
        gold_stolen = int(defender.resources["gold"] * min(0.3, 0.1 + victory_margin * 0.2))
        food_stolen = int(defender.resources["food"] * min(0.2, 0.05 + victory_margin * 0.15))
        
        # Transfer resources
        attacker.resources["gold"] += gold_stolen
        attacker.resources["food"] += food_stolen
        defender.resources["gold"] = max(0, defender.resources["gold"] - gold_stolen)
        defender.resources["food"] = max(0, defender.resources["food"] - food_stolen)
        
        # Happiness effects
        attacker.resources["happiness"] += random.randint(50, 100)
        defender.resources["happiness"] = max(0, defender.resources["happiness"] - random.randint(100, 200))
        
        embed = create_embed("⚔️ Victory!", 
                           f"{attacker.name} has defeated {defender.name}!")
        embed.set_image(url="https://media1.tenor.com/m/6BvNeDJWv4MAAAAd/gou-gougang.gif")
        embed.add_field(name="⚡ Battle Power", 
                       value=f"Attacker: {attacker_power:,}\nDefender: {defender_power:,}", 
                       inline=True)
        embed.add_field(name="💰 Spoils of War", 
                       value=f"💰 {gold_stolen} gold\n🌾 {food_stolen} food", 
                       inline=True)
        embed.add_field(name="💀 Casualties", 
                       value=f"Attacker: -{attacker_losses}\nDefender: -{defender_losses}", 
                       inline=True)
        
    else:
        # Defender wins
        defeat_margin = (defender_roll - attacker_roll) / attacker_roll
        
        # Attacker loses more soldiers in defeat
        attacker_losses = max(5, int(attacker.resources["soldiers"] * random.uniform(0.20, 0.35)))
        defender_losses = max(1, int(defender.resources["soldiers"] * random.uniform(0.05, 0.10)))
        
        # Apply losses
        attacker.resources["soldiers"] = max(0, attacker.resources["soldiers"] - attacker_losses)
        defender.resources["soldiers"] = max(0, defender.resources["soldiers"] - defender_losses)
        
        # Attacker loses some resources in retreat
        gold_lost = int(attacker.resources["gold"] * min(0.15, 0.05 + defeat_margin * 0.1))
        attacker.resources["gold"] = max(0, attacker.resources["gold"] - gold_lost)
        
        # Happiness effects
        attacker.resources["happiness"] = max(0, attacker.resources["happiness"] - random.randint(100, 200))
        defender.resources["happiness"] += random.randint(50, 100)
        
        embed = create_embed("🛡️ Defeat!", 
                           f"{defender.name} has repelled {attacker.name}'s attack!", 
                           0xff9900)
        embed.set_image(url="https://media1.tenor.com/m/6BvNeDJWv4MAAAAd/gou-gougang.gif")
        embed.add_field(name="⚡ Battle Power", 
                       value=f"Attacker: {attacker_power:,}\nDefender: {defender_power:,}", 
                       inline=True)
        embed.add_field(name="💸 Losses", 
                       value=f"💰 -{gold_lost} gold (retreat cost)", 
                       inline=True)
        embed.add_field(name="💀 Casualties", 
                       value=f"Attacker: -{attacker_losses}\nDefender: -{defender_losses}", 
                       inline=True)
    
    # Notify the defender if they're online (optional - basic implementation)
    try:
        await target.send(f"🚨 Your civilization {defender.name} was attacked by {attacker.name}! Check the server for details.")
    except:
        pass  # User might have DMs disabled
    
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 150, commands.BucketType.user)  # 2.5-minute cooldown
async def civil_war(ctx):
    """Trigger internal conflict in your civilization (2.5 min cooldown)"""
    player = get_player(str(ctx.author.id))
    
    if player.name is None:
        embed = create_embed("❌ No Civilization",
                           "You need to start your civilization first! Use `.start <name>`", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    # Check minimum requirements
    if player.resources["soldiers"] < 20:
        embed = create_embed("❌ Army Too Small", 
                           "You need at least 20 soldiers to have a civil war!", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    # Determine outcome (60% chance of positive outcome)
    if random.random() < 0.6:
        # Positive outcome - military coup succeeds, gain resources
        gold_gained = random.randint(200, 500)
        food_gained = random.randint(100, 300)
        soldiers_lost = int(player.resources["soldiers"] * random.uniform(0.1, 0.2))
        happiness_lost = random.randint(50, 150)
        
        player.resources["gold"] += gold_gained
        player.resources["food"] += food_gained
        player.resources["soldiers"] = max(0, player.resources["soldiers"] - soldiers_lost)
        player.resources["happiness"] = max(0, player.resources["happiness"] - happiness_lost)
        
        embed = create_embed("⚔️ Successful Coup!", 
                           "Your military has overthrown corrupt officials!")
        embed.add_field(name="💰 Treasury Seized", value=f"+{gold_gained} gold", inline=True)
        embed.add_field(name="🌾 Supplies Captured", value=f"+{food_gained} food", inline=True)
        embed.add_field(name="💀 Military Losses", value=f"-{soldiers_lost} soldiers", inline=True)
        embed.add_field(name="😔 Civil Unrest", value=f"-{happiness_lost} happiness", inline=True)
        
    else:
        # Negative outcome - civil war causes chaos
        gold_lost = int(player.resources["gold"] * random.uniform(0.15, 0.30))
        food_lost = int(player.resources["food"] * random.uniform(0.10, 0.25))
        soldiers_lost = int(player.resources["soldiers"] * random.uniform(0.25, 0.40))
        happiness_lost = random.randint(150, 300)
        
        player.resources["gold"] = max(0, player.resources["gold"] - gold_lost)
        player.resources["food"] = max(0, player.resources["food"] - food_lost)
        player.resources["soldiers"] = max(0, player.resources["soldiers"] - soldiers_lost)
        player.resources["happiness"] = max(0, player.resources["happiness"] - happiness_lost)
        
        embed = create_embed("💥 Civil War Chaos!", 
                           "Internal conflict has torn your civilization apart!", 
                           0xff0000)
        embed.add_field(name="💸 Treasury Lost", value=f"-{gold_lost} gold", inline=True)
        embed.add_field(name="🌾 Supplies Destroyed", value=f"-{food_lost} food", inline=True)
        embed.add_field(name="💀 Heavy Casualties", value=f"-{soldiers_lost} soldiers", inline=True)
        embed.add_field(name="😭 Mass Exodus", value=f"-{happiness_lost} happiness", inline=True)
    
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 150, commands.BucketType.user)  # 2.5-minute cooldown
async def train(ctx):
    """Train your soldiers to improve combat effectiveness"""
    player = get_player(str(ctx.author.id))
    
    if player.name is None:
        return await ctx.send("❌ Start your civilization first! `.start <name>`")
    
    cost = 200
    if player.resources["gold"] < cost:
        return await ctx.send(f"❌ Need {cost} gold to train soldiers!")
    
    # Training logic
    player.resources["gold"] -= cost
    soldiers_trained = random.randint(15, 30)
    player.resources["soldiers"] += soldiers_trained
    
    # Increase spy level chance
    if random.random() < 0.3:
        player.espionage["spy_level"] += 1
        level_up = f"\n🎓 Spy level increased to {player.espionage['spy_level']}!"
    else:
        level_up = ""
    
    # Training GIF
    gif_url = "https://media2.giphy.com/media/v1.Y2lkPTc5MGI3NjExYTFjbzFqNTh5MWxwZGI3MHViZW5kOTZ2YXFiazlnZTJham0ybTBrZSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/PiznJzzPYacIXxmHeD/giphy.gif"
    
    embed = create_embed("🏋️ Training Complete!", f"Your soldiers are ready for battle!{level_up}")
    embed.set_image(url=gif_url)
    embed.add_field(name="💰 Training Cost", value=f"-{cost} gold", inline=True)
    embed.add_field(name="⚔️ New Soldiers", value=f"+{soldiers_trained}", inline=True)
    
    await ctx.send(embed=embed)

# =============================================================================
# ESPIONAGE COMMANDS
# =============================================================================

@bot.command()
@commands.cooldown(1, 180, commands.BucketType.user)
async def spy(ctx, target: guilded.Member = None):
    """Spy on another nation to gather intelligence (3 min cooldown)"""
    player = get_player(str(ctx.author.id))
    
    if not target or str(target.id) == str(ctx.author.id):
        return await ctx.send("❌ Usage: `.spy @user`")
    
    target_player = get_player(str(target.id))
    if target_player.name is None:
        return await ctx.send("❌ Target hasn't started their civilization!")
    
    if player.espionage["spy_attempts"] >= player.espionage["max_spies"]:
        return await ctx.send("❌ Max spy attempts reached! Wait 24h or upgrade spies.")
    
    success_rate = calculate_spy_success(player, target_player)
    player.espionage["spy_attempts"] += 1
    
    if random.random() < success_rate:
        # Successful spy
        intel = {
            "battle_power": calculate_battle_power(target_player),
            "resources": dict(target_player.resources),
            "buildings": dict(target_player.buildings),
            "alliances": list(target_player.alliances)
        }
        
        embed = create_embed("🕵️ Spy Mission Success!", f"Intel on **{target_player.name}**:")
        embed.add_field(name="⚔️ Battle Power", value=intel["battle_power"], inline=True)
        embed.add_field(name="💰 Gold", value=intel["resources"]["gold"], inline=True)
        embed.add_field(name="🤝 Alliances", value=len(intel["alliances"]), inline=True)
        
        # Small chance to discover mail
        if random.random() < 0.3 and target_player.mailbox:
            mail = random.choice(target_player.mailbox)
            embed.add_field(name="📧 Intercepted Mail", value=f"From: {mail['from']}\nSubject: {mail['subject'][:50]}...", inline=False)
        
    else:
        # Failed spy - lose happiness
        happiness_loss = random.randint(50, 100)
        player.resources["happiness"] = max(0, player.resources["happiness"] - happiness_loss)
        embed = create_embed("🕵️ Spy Mission Failed!", f"Your spy was caught! -{happiness_loss} happiness")
    
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 300, commands.BucketType.user)
async def sabotage(ctx, target: guilded.Member = None):
    """Sabotage enemy military units and buildings (5 min cooldown)"""
    player = get_player(str(ctx.author.id))
    
    if not target or str(target.id) == str(ctx.author.id):
        return await ctx.send("❌ Usage: `.sabotage @user`")
    
    target_player = get_player(str(target.id))
    if target_player.name is None:
        return await ctx.send("❌ Target hasn't started their civilization!")
    
    success_rate = calculate_spy_success(player, target_player) * 0.7
    
    if random.random() < success_rate:
        # Successful sabotage
        soldiers_destroyed = max(1, int(target_player.resources["soldiers"] * 0.1))
        buildings_damaged = 0
        
        for building in target_player.buildings:
            if target_player.buildings[building] > 0:
                target_player.buildings[building] -= 1
                buildings_damaged += 1
        
        target_player.resources["soldiers"] = max(0, target_player.resources["soldiers"] - soldiers_destroyed)
        
        embed = create_embed("💣 Sabotage Success!", f"Damaged **{target_player.name}**!")
        embed.add_field(name="💀 Soldiers Killed", value=soldiers_destroyed, inline=True)
        embed.add_field(name="🏗️ Buildings Damaged", value=buildings_damaged, inline=True)
    else:
        # Failed sabotage
        happiness_loss = random.randint(75, 150)
        player.resources["happiness"] = max(0, player.resources["happiness"] - happiness_loss)
        embed = create_embed("💣 Sabotage Failed!", f"Your saboteurs were discovered! -{happiness_loss} happiness")
    
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 240, commands.BucketType.user)
async def hack(ctx, target: guilded.Member = None):
    """Hack enemy systems to reduce happiness and steal info (4 min cooldown)"""
    player = get_player(str(ctx.author.id))
    
    if not target or str(target.id) == str(ctx.author.id):
        return await ctx.send("❌ Usage: `.hack @user`")
    
    target_player = get_player(str(target.id))
    if target_player.name is None:
        return await ctx.send("❌ Target hasn't started their civilization!")
    
    success_rate = calculate_spy_success(player, target_player) * 0.8
    
    if random.random() < success_rate:
        # Successful hack
        happiness_stolen = random.randint(100, 250)
        gold_stolen = int(target_player.resources["gold"] * 0.05)
        
        target_player.resources["happiness"] = max(0, target_player.resources["happiness"] - happiness_stolen)
        target_player.resources["gold"] = max(0, target_player.resources["gold"] - gold_stolen)
        
        player.resources["happiness"] += int(happiness_stolen * 0.5)
        player.resources["gold"] += gold_stolen
        
        embed = create_embed("💻 Hack Success!", f"Breached **{target_player.name}**!")
        embed.add_field(name="😈 Happiness Stolen", value=f"+{int(happiness_stolen*0.5)} for you, -{happiness_stolen} for them", inline=True)
        embed.add_field(name="💰 Gold Stolen", value=gold_stolen, inline=True)
    else:
        # Failed hack
        happiness_loss = random.randint(100, 200)
        player.resources["happiness"] = max(0, player.resources["happiness"] - happiness_loss)
        embed = create_embed("💻 Hack Failed!", f"Your hackers were traced! -{happiness_loss} happiness")
    
    await ctx.send(embed=embed)

# =============================================================================
# ALLIANCE COMMANDS
# =============================================================================

@bot.command()
@commands.cooldown(1, 120, commands.BucketType.user)  # 2-minute cooldown
async def ally(ctx, target: guilded.Member = None):
    """Form an alliance with another player (2 min cooldown)"""
    player = get_player(str(ctx.author.id))
    
    if player.name is None:
        embed = create_embed("❌ No Civilization", 
                           "You need to start your civilization first! Use `.start <name>`", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    if not target:
        embed = create_embed("❌ No Target", 
                           "You must specify who to ally with!\nExample: `.ally @username`", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    if str(target.id) == str(ctx.author.id):
        embed = create_embed("❌ Self Alliance", 
                           "You cannot ally with yourself!", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    target_player = get_player(str(target.id))
    
    if target_player.name is None:
        embed = create_embed("❌ Invalid Target", 
                           "Target player hasn't started their civilization yet!", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    # Check if already allied
    if str(target.id) in player.alliances:
        embed = create_embed("❌ Already Allied", 
                           f"You are already allied with {target_player.name}!", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    # Check alliance limits (max 5 alliances)
    if len(player.alliances) >= 5:
        embed = create_embed("❌ Alliance Limit", 
                           "You can only have 5 alliances at once!\nUse `.break @user` to end an alliance first.", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    # Cost to form alliance
    alliance_cost = 150
    if player.resources["gold"] < alliance_cost:
        embed = create_embed("❌ Insufficient Gold", 
                           f"You need {alliance_cost} gold to form an alliance!")
        embed.add_field(name="Your Gold", value=f"💰 {player.resources['gold']}")
        await ctx.send(embed=embed)
        return
    
    # Form the alliance (mutual)
    player.resources["gold"] -= alliance_cost
    player.alliances.add(str(target.id))
    target_player.alliances.add(str(ctx.author.id))
    
    # Both sides gain happiness
    happiness_gain = random.randint(75, 125)
    player.resources["happiness"] += happiness_gain
    target_player.resources["happiness"] += happiness_gain
    
    embed = create_embed("🤝 Alliance Formed!", 
                       f"{player.name} and {target_player.name} are now allies!")
    embed.add_field(name="💰 Diplomatic Cost", value=f"-{alliance_cost} gold", inline=True)
    embed.add_field(name="😊 Happiness Boost", value=f"+{happiness_gain} (both sides)", inline=True)
    embed.add_field(name="🛡️ Protection", value="Cannot attack each other", inline=True)
    
    # Notify the target player
    try:
        await target.send(f"🤝 {player.name} has formed an alliance with your civilization {target_player.name}!")
    except:
        pass  # User might have DMs disabled
    
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 120, commands.BucketType.user)  # 2-minute cooldown
async def break_alliance(ctx, target: guilded.Member = None):
    """Break an alliance with another player (2 min cooldown)"""
    player = get_player(str(ctx.author.id))
    
    if player.name is None:
        embed = create_embed("❌ No Civilization", 
                           "You need to start your civilization first! Use `.start <name>`", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    if not target:
        embed = create_embed("❌ No Target", 
                           "You must specify whose alliance to break!\nExample: `.break @username`", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    if str(target.id) == str(ctx.author.id):
        embed = create_embed("❌ Invalid Target", 
                           "You cannot break alliance with yourself!", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    target_player = get_player(str(target.id))
    
    # Check if alliance exists
    if str(target.id) not in player.alliances:
        embed = create_embed("❌ No Alliance", 
                           f"You are not allied with {target.name}!", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    # Break the alliance (mutual)
    player.alliances.discard(str(target.id))
    target_player.alliances.discard(str(ctx.author.id))
    
    # Both sides lose happiness
    happiness_loss = random.randint(100, 200)
    player.resources["happiness"] = max(0, player.resources["happiness"] - happiness_loss)
    target_player.resources["happiness"] = max(0, target_player.resources["happiness"] - happiness_loss)
    
    embed = create_embed("💔 Alliance Broken!", 
                       f"{player.name} has ended their alliance with {target_player.name}!")
    embed.add_field(name="😔 Diplomatic Fallout", value=f"-{happiness_loss} happiness (both sides)", inline=True)
    embed.add_field(name="⚔️ Combat Enabled", value="You can now attack each other", inline=True)
    
    # Notify the target player
    try:
        await target.send(f"💔 {player.name} has broken their alliance with your civilization {target_player.name}!")
    except:
        pass  # User might have DMs disabled
    
    await ctx.send(embed=embed)

# Add alias for break command
@bot.command(name="break")
@commands.cooldown(1, 120, commands.BucketType.user)  # 2-minute cooldown
async def break_command(ctx, target: guilded.Member = None):
    """Alias for break_alliance command"""
    await break_alliance(ctx, target)

# =============================================================================
# COMMUNICATION COMMANDS
# =============================================================================

@bot.command()
async def send(ctx, target: guilded.Member = None, *, message=None):
    """Send a diplomatic message to another nation"""
    player = get_player(str(ctx.author.id))
    
    if player.name is None:
        embed = create_embed("❌ No Civilization", 
                           "You need to start your civilization first! Use `.start <name>`", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    if not target or not message:
        embed = create_embed("📧 Send Message", 
                           "Send diplomatic messages to other nations!\n"
                           "**Usage:** `.send @player Your message here`")
        await ctx.send(embed=embed)
        return
    
    target_player = get_player(str(target.id))
    if target_player.name is None:
        return await ctx.send("❌ Target hasn't started their civilization!")
    
    # Create message
    mail = {
        "from": player.name,
        "from_id": str(ctx.author.id),
        "subject": f"Message from {player.name}",
        "content": message,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    
    target_player.mailbox.append(mail)
    player.sent_mail.append(mail)
    
    embed = create_embed("📧 Message Sent!", f"Sent to **{target_player.name}**: {message[:100]}...")
    await ctx.send(embed=embed)
    
    # Notify target
    try:
        await target.send(f"📧 New message from **{player.name}** in Guilded: {message[:50]}...")
    except:
        pass

@bot.command()
async def mail(ctx):
    """Check your diplomatic messages"""
    player = get_player(str(ctx.author.id))
    
    if player.name is None:
        embed = create_embed("❌ No Civilization", 
                           "You need to start your civilization first! Use `.start <name>`", 
                           0xff0000)
        await ctx.send(embed=embed)
        return
    
    if not player.mailbox:
        return await ctx.send("📭 Your inbox is empty!")
    
    embed = create_embed("📧 Diplomatic Mail", f"You have {len(player.mailbox)} messages:")
    
    for i, mail in enumerate(player.mailbox[-5:], 1):
        embed.add_field(
            name=f"#{i} From: {mail['from']} ({mail['timestamp']})",
            value=mail['content'][:100] + ("..." if len(mail['content']) > 100 else ""),
            inline=False
        )
    
    await ctx.send(embed=embed)

# =============================================================================
# FLASK WEB SERVER
# =============================================================================

# Initialize Flask app for keep-alive
app = Flask(__name__)

# HTML template for the web interface
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>WarBot - Advanced Civilization Management</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <style>
        body {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        .main-container {
            background: rgba(255, 255, 255, 0.95);
            border-radius: 15px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            backdrop-filter: blur(10px);
            margin: 2rem auto;
            max-width: 1200px;
        }
        .header-section {
            background: linear-gradient(135deg, #ff6b6b, #ee5a24);
            color: white;
            border-radius: 15px 15px 0 0;
            padding: 2rem;
            text-align: center;
        }
        .status-badge {
            background: #2ecc71;
            color: white;
            padding: 0.5rem 1rem;
            border-radius: 20px;
            font-weight: bold;
        }
        .command-card {
            background: white;
            border-radius: 10px;
            padding: 1.5rem;
            margin: 1rem 0;
            box-shadow: 0 5px 15px rgba(0,0,0,0.08);
            border-left: 4px solid #3498db;
        }
        .command-title {
            color: #2c3e50;
            font-weight: bold;
            margin-bottom: 0.5rem;
        }
        .command-description {
            color: #7f8c8d;
            margin-bottom: 1rem;
        }
        .command-example {
            background: #f8f9ff;
            padding: 0.5rem 1rem;
            border-radius: 5px;
            font-family: 'Courier New', monospace;
            border-left: 3px solid #3498db;
        }
        .feature-icon {
            font-size: 2rem;
            color: #3498db;
            margin-bottom: 1rem;
        }
        .disaster-alert {
            background: linear-gradient(45deg, #ff6b6b, #ffa500);
            color: white;
            padding: 1rem;
            border-radius: 10px;
            margin: 1rem 0;
            text-align: center;
        }
    </style>
</head>
<body>
    <div class="container-fluid">
        <div class="main-container">
            <div class="header-section">
                <div class="row align-items-center">
                    <div class="col-md-8">
                        <h1><i class="fas fa-crown"></i> WarBot</h1>
                        <p class="lead mb-0">Advanced Civilization Management with Espionage</p>
                    </div>
                    <div class="col-md-4 text-end">
                        <div class="status-badge">
                            <i class="fas fa-circle pulse"></i> Online & Ready
                        </div>
                    </div>
                </div>
            </div>

            <div class="container p-4">
                <div class="disaster-alert">
                    <i class="fas fa-exclamation-triangle"></i> 
                    <strong>NEW FEATURES:</strong> Espionage System, Natural Disasters, Diplomatic Messaging & GIF Animations!
                </div>

                <div class="row">
                    <div class="col-lg-4">
                        <h3><i class="fas fa-rocket feature-icon"></i></h3>
                        <h4>Core Features</h4>
                        <ul class="list-unstyled">
                            <li><i class="fas fa-check text-success"></i> Complete civilization management</li>
                            <li><i class="fas fa-check text-success"></i> Resource gathering & economy</li>
                            <li><i class="fas fa-check text-success"></i> Strategic combat & military units</li>
                            <li><i class="fas fa-check text-success"></i> Alliance system & diplomacy</li>
                        </ul>
                    </div>
                    <div class="col-lg-4">
                        <h3><i class="fas fa-user-secret feature-icon"></i></h3>
                        <h4>Espionage System</h4>
                        <ul class="list-unstyled">
                            <li><i class="fas fa-eye text-info"></i> Spy on enemy nations</li>
                            <li><i class="fas fa-bomb text-danger"></i> Sabotage military units</li>
                            <li><i class="fas fa-laptop-code text-warning"></i> Hack enemy systems</li>
                            <li><i class="fas fa-graduation-cap text-primary"></i> Train elite soldiers</li>
                        </ul>
                    </div>
                    <div class="col-lg-4">
                        <h3><i class="fas fa-cloud-rain feature-icon"></i></h3>
                        <h4>Dynamic Events</h4>
                        <ul class="list-unstyled">
                            <li><i class="fas fa-bolt text-warning"></i> Natural disasters (3% daily)</li>
                            <li><i class="fas fa-envelope text-primary"></i> Diplomatic messaging</li>
                            <li><i class="fas fa-moon text-info"></i> Day/night cycle bonuses</li>
                            <li><i class="fas fa-heart text-danger"></i> Hunger & happiness systems</li>
                        </ul>
                    </div>
                </div>

                <hr class="my-4">

                <h3 class="text-center mb-4"><i class="fas fa-terminal"></i> Complete Command List</h3>
                
                <div class="row">
                    <div class="col-md-6">
                        <div class="command-card">
                            <div class="command-title"><i class="fas fa-flag"></i> Basic & Economy</div>
                            <div class="command-example">
                                .start Roman Empire<br>
                                .gather | .build house<br>
                                .buy soldiers 10 | .farm<br>
                                .cheer | .feed | .gamble 100
                            </div>
                        </div>

                        <div class="command-card">
                            <div class="command-title"><i class="fas fa-sword"></i> Combat & Training</div>
                            <div class="command-example">
                                .attack @enemy<br>
                                .civil_war<br>
                                .train (with GIF)
                            </div>
                        </div>
                    </div>

                    <div class="col-md-6">
                        <div class="command-card">
                            <div class="command-title"><i class="fas fa-user-secret"></i> Espionage</div>
                            <div class="command-example">
                                .spy @enemy<br>
                                .sabotage @enemy<br>
                                .hack @enemy
                            </div>
                        </div>

                        <div class="command-card">
                            <div class="command-title"><i class="fas fa-handshake"></i> Diplomacy</div>
                            <div class="command-example">
                                .ally @friend | .break @friend<br>
                                .send @player Hello!<br>
                                .mail (check inbox)
                            </div>
                        </div>
                    </div>
                </div>

                <hr class="my-4">

                <div class="text-center">
                    <h4><i class="fas fa-info-circle"></i> Getting Started</h4>
                    <p class="lead">Join a Guilded server with WarBot and type <code>.start YourCivilizationName</code> to begin!</p>
                    <p class="text-muted">All cooldowns optimized for balanced gameplay. Natural disasters occur randomly affecting all players!</p>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/health')
def health():
    return {"status": "healthy", "bot_ready": bot.is_ready() if hasattr(bot, 'is_ready') else False}

def run_flask():
    """Run Flask server in a separate thread"""
    app.run(host='0.0.0.0', port=5000, debug=False)

def run_bot():
    """Run the Guilded bot"""
    token = os.getenv('GUILDED_BOT_TOKEN', 'your_bot_token_here')
    if token == 'your_bot_token_here':
        print("WARNING: Using default bot token. Set GUILDED_BOT_TOKEN environment variable.")
    bot.run(token)

# =============================================================================
# MAIN EXECUTION
# =============================================================================

if __name__ == '__main__':
    print("WarBot - Complete Civilization Management System")
    print("=" * 50)
    print("✅ Enhanced Features:")
    print("  • Espionage System (.spy, .sabotage, .hack)")
    print("  • Natural Disasters (3% daily occurrence)")
    print("  • Diplomatic Messaging (.send, .mail)")
    print("  • Soldier Training with GIFs")
    print("  • Attack GIFs")
    print("=" * 50)
    
    # Start Flask server in background thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("Flask server started on port 5000")
    
    # Start the bot (this will block)
    print("Starting Guilded bot...")
    run_bot()
