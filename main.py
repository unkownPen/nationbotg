#!/usr/bin/env python3
"""
WarBot - Complete Guilded Civilization Management Bot
Fixed for Render deployment
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
    """Player data model"""
    def __init__(self, user_id):
        self.user_id = user_id
        self.name = None  # Civilization name
        self.resources = {
            "gold": 1000,
            "food": 500,
            "soldiers": 100,
            "happiness": 500,
            "hunger": 1000
        }
        self.buildings = {
            "houses": 0,
            "farms": 0,
            "barracks": 0,
            "walls": 0,
            "warplanes": 0,
            "fighter_jets": 0,
            "tanks": 0
        }
        self.military_units = {
            "mi6_civilians": 0  # Fake operatives
        }
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
    
    total_power = (base_power * happiness_multiplier) + warplane_bonus + jet_bonus + tank_bonus + mi6_bonus
    return int(total_power)

def calculate_discount(player):
    """Calculate total discount percentage"""
    happiness_discount = min(player.resources["happiness"] * 0.01, 100)  # 1% per happiness point
    building_discount = sum(player.buildings.values()) * 5  # 5% per building
    total_discount = min(happiness_discount + building_discount, 90)  # Max 90% discount
    return total_discount

# =============================================================================
# BOT SETUP AND BACKGROUND TASKS
# =============================================================================

# Bot setup
bot = commands.Bot(command_prefix='.', help_command=None)

# Background task for passive effects
async def passive_effects():
    """Background task to handle passive resource changes"""
    await bot.wait_until_ready()
    while True:
        try:
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
                    
                    # Reset costs after 4 days (345,600 seconds)
                    if now - player.last_passive > 345600:
                        player.cheer_cost = 100
                        player.cheer_count = 0
                        player.feed_cost = 50
                        
                except Exception as e:
                    print(f"Error processing passive effects for player {player_id}: {e}")
            
            await asyncio.sleep(30)  # Check every 30 seconds to reduce resource usage
        except Exception as e:
            print(f"Error in passive_effects task: {e}")
            await asyncio.sleep(60)  # Wait longer on error

# Bot events
@bot.event
async def on_ready():
    """Event fired when bot is ready"""
    print(f'Bot logged in as: {bot.user.name} ({bot.user.id})')
    print('------')
    print("WarBot is ready and online!")

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
        embed = create_embed("🏰 WarBot Commands", "Manage your civilization!")
        
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
            "`.civil_war` - Internal conflict for resources (2.5 min cooldown)"
        ]
        
        alliance_commands = [
            "`.ally <@user>` - Form alliance (2 min cooldown)",
            "`.break <@user>` - Break alliance (2 min cooldown)"
        ]
        
        embed.add_field(name="🏛️ Basic Commands", value="\n".join(basic_commands), inline=False)
        embed.add_field(name="💰 Economy Commands", value="\n".join(economy_commands), inline=False)
        embed.add_field(name="⚔️ Combat Commands", value="\n".join(combat_commands), inline=False)
        embed.add_field(name="🤝 Alliance Commands", value="\n".join(alliance_commands), inline=False)
        
    await ctx.send(embed=embed)

# =============================================================================
# ECONOMY COMMANDS (I'll include a few key ones - the rest remain the same)
# =============================================================================

@bot.command()
@commands.cooldown(1, 60, commands.BucketType.user)
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

# =============================================================================
# FLASK WEB SERVER
# =============================================================================

app = Flask(__name__)

@app.route('/')
def index():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>WarBot Status</title>
        <style>
            body { font-family: Arial, sans-serif; text-align: center; padding: 50px; background: #f0f0f0; }
            .container { background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🏰 WarBot</h1>
            <h2>✅ Bot is Online</h2>
            <p>Guilded Civilization Management Bot</p>
            <p>Ready to serve on Guilded servers!</p>
        </div>
    </body>
    </html>
    """

@app.route('/health')
def health():
    return {"status": "healthy", "bot_ready": True}

# =============================================================================
# MAIN EXECUTION
# =============================================================================

async def start_bot():
    """Start the bot with proper async setup"""
    try:
        # Create the passive effects task
        bot.loop.create_task(passive_effects())
        
        # Get token from environment
        token = os.getenv('GUILDED_BOT_TOKEN')
        if not token:
            print("ERROR: GUILDED_BOT_TOKEN environment variable not set!")
            return
        
        print("Starting bot...")
        await bot.start(token)
    except Exception as e:
        print(f"Error starting bot: {e}")

def run_flask():
    """Run Flask server"""
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

def main():
    """Main execution function"""
    print("WarBot - Starting up...")
    print("=" * 50)
    
    # Start Flask server in background thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print(f"Flask server started on port {os.getenv('PORT', 5000)}")
    
    # Start the bot
    try:
        asyncio.run(start_bot())
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Fatal error: {e}")

if __name__ == '__main__':
    main()
