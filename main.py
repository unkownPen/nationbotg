#!/usr/bin/env python3
"""
WarBot - Complete Guilded Civilization Management Bot
A comprehensive bot featuring civilization building, combat, espionage, technology, and political systems.
"""

import os
import json
import random
import asyncio
import threading
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any

# Framework imports
import guilded
from guilded.ext import commands
from flask import Flask, render_template_string
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import and_, or_
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# =============================================================================
# DATABASE CONFIGURATION
# =============================================================================

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)

# =============================================================================
# CONFIGURATION
# =============================================================================

# Game Configuration
COOLDOWNS = {
    'gather': 60,      # 1 minute
    'build': 120,      # 2 minutes
    'buy': 90,         # 1.5 minutes
    'farm': 120,       # 2 minutes
    'cheer': 90,       # 1.5 minutes
    'feed': 120,       # 2 minutes
    'gamble': 180,     # 3 minutes
    'attack': 90,      # 1.5 minutes
    'civil_war': 150,  # 2.5 minutes
    'train': 150,      # 2.5 minutes
    'spy': 180,        # 3 minutes
    'sabotage': 300,   # 5 minutes
    'hack': 240,       # 4 minutes
    'ally': 120,       # 2 minutes
    'break': 120,      # 2 minutes
    'nuke': 600,       # 10 minutes
    'backstab': 300,   # 5 minutes
    'stealthbattle': 180, # 3 minutes
    'invent': 300,     # 5 minutes
    'provide': 60,     # 1 minute
    'puppet': 900,     # 15 minutes
    'revolt': 300      # 5 minutes
}

# Shop Items
SHOP_ITEMS = {
    'nuke': {'price': 10000, 'type': 'weapon'},
    'anti_nuke_shield': {'price': 8000, 'type': 'defense'},
    'knife': {'price': 500, 'type': 'weapon'}
}

# Buildings
BUILDINGS = {
    'house': {'wood': 20, 'stone': 10, 'gold': 100},
    'farm': {'wood': 30, 'stone': 5, 'gold': 150},
    'barracks': {'wood': 50, 'stone': 30, 'gold': 300},
    'wall': {'wood': 10, 'stone': 40, 'gold': 200},
    'market': {'wood': 40, 'stone': 20, 'gold': 400}
}

# GIF URLs for visual responses
GIFS = {
    'success': 'https://media.giphy.com/media/3o7abKhOpu0NwenH3O/giphy.gif',
    'fail': 'https://media.giphy.com/media/d2lcHJTG5Tscg/giphy.gif',
    'attack': 'https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif',
    'gather': 'https://media.giphy.com/media/3o6Zt481isNVuQI1l6/giphy.gif',
    'build': 'https://media.giphy.com/media/3o7abA4a0QCXtSxGN2/giphy.gif',
    'spy': 'https://media.giphy.com/media/l0HlNyrvLKBMxjFzG/giphy.gif',
    'civil_war': 'https://media.giphy.com/media/26BRpLTzQJiPyLnuo/giphy.gif',
    'nuke': 'https://media.giphy.com/media/HhTXt43pk1I1W/giphy.gif',
    'disaster': 'https://media.giphy.com/media/l0MYJnJQ4EiYhOeWs/giphy.gif'
}

# =============================================================================
# DATABASE MODELS
# =============================================================================

class Player(db.Model):
    __tablename__ = 'players'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), unique=True, nullable=False)
    username = db.Column(db.String(100), nullable=False)
    civilization_name = db.Column(db.String(100), nullable=False)
    
    # Resources
    gold = db.Column(db.Integer, default=1000)
    wood = db.Column(db.Integer, default=100)
    stone = db.Column(db.Integer, default=50)
    food = db.Column(db.Integer, default=100)
    
    # Population
    population = db.Column(db.Integer, default=100)
    happiness = db.Column(db.Integer, default=50)
    hunger = db.Column(db.Integer, default=50)
    
    # Military
    soldiers = db.Column(db.Integer, default=10)
    spies = db.Column(db.Integer, default=2)
    
    # Special Items
    nukes = db.Column(db.Integer, default=0)
    anti_nuke_shields = db.Column(db.Integer, default=0)
    knives = db.Column(db.Integer, default=0)
    tech_level = db.Column(db.Integer, default=0)
    
    # Political Status
    is_puppet = db.Column(db.Boolean, default=False)
    puppet_master_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=True)
    civil_war_strikes = db.Column(db.Integer, default=0)
    
    # Building data stored as JSON
    buildings = db.Column(db.Text, default='{}')
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_active = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    alliances = db.relationship('Alliance', 
                               foreign_keys='Alliance.player1_id',
                               back_populates='player1')
    cooldowns = db.relationship('Cooldown', back_populates='player')
    messages = db.relationship('Message', 
                              foreign_keys='Message.recipient_id',
                              back_populates='recipient')
    puppet_master = db.relationship('Player', foreign_keys=[puppet_master_id], remote_side=[id])
    puppet_states = db.relationship('Player', foreign_keys=[puppet_master_id])

    def get_buildings(self):
        try:
            return json.loads(self.buildings) if self.buildings else {}
        except:
            return {}
    
    def set_buildings(self, building_dict):
        self.buildings = json.dumps(building_dict)
    
    def set_cooldown(self, command, seconds):
        existing = Cooldown.query.filter_by(player_id=self.id, command=command).first()
        if existing:
            existing.expires_at = datetime.utcnow() + timedelta(seconds=seconds)
        else:
            cooldown = Cooldown(player_id=self.id, command=command, 
                              expires_at=datetime.utcnow() + timedelta(seconds=seconds))
            db.session.add(cooldown)

class Alliance(db.Model):
    __tablename__ = 'alliances'
    
    id = db.Column(db.Integer, primary_key=True)
    player1_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=False)
    player2_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    player1 = db.relationship('Player', foreign_keys=[player1_id], back_populates='alliances')
    player2 = db.relationship('Player', foreign_keys=[player2_id])

class Cooldown(db.Model):
    __tablename__ = 'cooldowns'
    
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=False)
    command = db.Column(db.String(50), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    
    player = db.relationship('Player', back_populates='cooldowns')

class Message(db.Model):
    __tablename__ = 'messages'
    
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    sender = db.relationship('Player', foreign_keys=[sender_id])
    recipient = db.relationship('Player', foreign_keys=[recipient_id], back_populates='messages')

class Event(db.Model):
    __tablename__ = 'events'
    
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=False)
    target_player_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=True)
    event_type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    player = db.relationship('Player', foreign_keys=[player_id])
    target_player = db.relationship('Player', foreign_keys=[target_player_id])

# =============================================================================
# GAME MECHANICS ENGINE
# =============================================================================

class GameMechanics:
    @staticmethod
    def calculate_attack_damage(attacker, defender, is_stealth=False):
        """Calculate damage dealt in an attack"""
        attacker_power = attacker.soldiers * random.uniform(0.8, 1.2)
        defender_power = defender.soldiers * random.uniform(0.7, 1.0)
        
        # Tech level provides combat bonuses
        tech_bonus = attacker.tech_level * 0.05  # 5% bonus per tech level
        attacker_power *= (1 + tech_bonus)
        
        # Defender tech provides defensive bonus
        defender_tech_bonus = defender.tech_level * 0.03  # 3% defensive bonus per tech level
        defender_power *= (1 + defender_tech_bonus)
        
        # Check for walls (defense buildings)
        defender_buildings = defender.get_buildings()
        defense_bonus = defender_buildings.get('wall', 0) * 0.1
        defender_power *= (1 + defense_bonus)
        
        # Stealth attacks get surprise bonus
        if is_stealth:
            attacker_power *= 1.3  # 30% stealth bonus
            defender_power *= 0.8   # Defender caught off guard
        
        victory = attacker_power > defender_power
        
        if victory:
            # Calculate stolen resources
            gold_stolen = min(int(defender.gold * 0.15), defender.gold)
            food_stolen = min(int(defender.food * 0.1), defender.food)
            
            # Apply damage
            attacker.soldiers = max(0, attacker.soldiers - random.randint(1, 3))
            defender.soldiers = max(0, defender.soldiers - random.randint(3, 8))
            defender.happiness = max(0, defender.happiness - random.randint(10, 20))
            
            # Transfer resources
            attacker.gold += gold_stolen
            attacker.food += food_stolen
            defender.gold -= gold_stolen
            defender.food -= food_stolen
            
            return True, gold_stolen, food_stolen
        else:
            # Attacker loses
            attacker.soldiers = max(0, attacker.soldiers - random.randint(2, 6))
            attacker.happiness = max(0, attacker.happiness - random.randint(5, 15))
            defender.soldiers = max(0, defender.soldiers - random.randint(1, 3))
            
            return False, 0, 0
    
    @staticmethod
    def execute_spy_mission(spy_player, target_player):
        """Execute a spy mission"""
        success_chance = 60 + (spy_player.spies * 5) - (target_player.spies * 3)
        success = random.randint(1, 100) <= success_chance
        
        if success:
            # Successful spying
            intelligence = {
                'gold': target_player.gold,
                'soldiers': target_player.soldiers,
                'happiness': target_player.happiness,
                'buildings': len(target_player.get_buildings())
            }
            return True, intelligence
        else:
            # Caught spying
            spy_player.spies = max(0, spy_player.spies - 1)
            return False, None
    
    @staticmethod
    def execute_civil_war(player):
        """Execute a civil war"""
        soldier_loss = random.randint(2, 5)
        player.soldiers = max(0, player.soldiers - soldier_loss)
        
        # 50% chance of gaining resources during civil war
        victory = random.random() < 0.5
        if victory:
            player.gold += random.randint(100, 300)
            player.food += random.randint(20, 50)
        
        return victory, soldier_loss

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_or_create_player(user_id: str, username: str) -> Optional[Player]:
    """Get existing player or return None"""
    return Player.query.filter_by(user_id=str(user_id)).first()

def check_cooldown(player: Player, command: str) -> Tuple[bool, int]:
    """Check if player can use a command"""
    cooldown = Cooldown.query.filter_by(player_id=player.id, command=command).first()
    if not cooldown:
        return True, 0
    
    now = datetime.utcnow()
    if now >= cooldown.expires_at:
        db.session.delete(cooldown)
        db.session.commit()
        return True, 0
    
    time_left = int((cooldown.expires_at - now).total_seconds())
    return False, time_left

# =============================================================================
# FLASK WEB SERVER
# =============================================================================

def create_flask_app():
    """Create Flask web server for status monitoring"""
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///warbot.db")
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_recycle": 300,
        "pool_pre_ping": True,
    }
    
    db.init_app(app)
    
    @app.route('/')
    def status():
        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>WarBot Status</title>
            <meta http-equiv="refresh" content="30">
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; background: #f0f0f0; }
                .container { background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
                .status { color: #28a745; font-weight: bold; }
                .info { margin: 10px 0; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🏰 WarBot Civilization System</h1>
                <div class="info">Status: <span class="status">ONLINE</span></div>
                <div class="info">Last Updated: {{ timestamp }}</div>
                <div class="info">Total Players: {{ player_count }}</div>
                <div class="info">Active Alliances: {{ alliance_count }}</div>
                <h3>🎮 Features</h3>
                <ul>
                    <li>Civilization Management (resources, population, military)</li>
                    <li>Combat System with technology bonuses</li>
                    <li>Stealth warfare and nuclear capabilities</li>
                    <li>Espionage and intelligence operations</li>
                    <li>Alliance and diplomatic systems</li>
                    <li>Technology research and advancement</li>
                    <li>Puppet states and political control</li>
                    <li>Civil war resolution mechanics</li>
                    <li>Resource sharing and trade</li>
                    <li>Complete historical event logging</li>
                </ul>
            </div>
        </body>
        </html>
        """
        
        with app.app_context():
            player_count = Player.query.count()
            alliance_count = Alliance.query.count()
            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
            
            return render_template_string(html_template, 
                                        player_count=player_count,
                                        alliance_count=alliance_count,
                                        timestamp=timestamp)
    
    return app

# =============================================================================
# GUILDED BOT
# =============================================================================

    """Create and configure the Guilded bot"""
    bot = commands.Bot()
    
    def create_embed(title: str, description: str, color: int = 0x00ff00, gif_url: str = None):
        """Create a formatted embed message"""
        embed = guilded.Embed(title=title, description=description, color=color)
        if gif_url:
            embed.set_image(url=gif_url)
        return embed
    
    bot.create_embed = create_embed
    
    # =============================================================================
    # BOT EVENTS
    # =============================================================================
    
    @bot.event
    async def on_ready():
        print(f"NationBot has connected to Guilded!")
    
    # =============================================================================
    # CORE COMMANDS
    # =============================================================================
    
    @bot.command(name='start')
    async def start_civilization(ctx, *, civilization_name: str):
        """Start a new civilization"""
        existing = get_or_create_player(ctx.author.id, ctx.author.name)
        if existing:
            await ctx.send("❌ You already have a civilization! Use `.status` to check it.")
            return
        
        if len(civilization_name) > 50:
            await ctx.send("❌ Civilization name must be 50 characters or less.")
            return
        
        user_id = str(ctx.author.id)
        username = ctx.author.name
        
        player = Player(
            user_id=user_id,
            username=username,
            civilization_name=civilization_name
        )
        db.session.add(player)
        db.session.commit()
        
        embed = bot.create_embed(
            "🏰 Civilization Founded!",
            f"Welcome, {username}!\n"
            f"Your civilization '{civilization_name}' has been established!\n\n"
            f"**Starting Resources:**\n"
            f"💰 Gold: 1,000\n"
            f"🪵 Wood: 100\n"
            f"🪨 Stone: 50\n"
            f"🍖 Food: 100\n"
            f"👥 Population: 100\n"
            f"⚔️ Soldiers: 10\n"
            f"🕵️ Spies: 2\n\n"
            f"Use `.status` to check your civilization and `.help` for commands!",
            gif_url=GIFS['success']
        )
        await ctx.send(embed=embed)
    
    @bot.command(name='status')
    async def check_status(ctx):
        """Check civilization status"""
        player = get_or_create_player(ctx.author.id, ctx.author.name)
        if not player:
            await ctx.send("❌ You haven't started a civilization yet! Use `.start <name>` to begin.")
            return
        
        buildings = player.get_buildings()
        building_list = "\n".join([f"🏢 {name.title()}: {count}" for name, count in buildings.items()]) or "None"
        
        # Political status information
        political_status = ""
        if player.is_puppet:
            puppet_master = Player.query.get(player.puppet_master_id)
            master_name = puppet_master.civilization_name if puppet_master else "Unknown"
            political_status = f"**👑 Political Status:** Puppet State of {master_name}\n"
        
        # Civil war status
        civil_war_status = ""
        if player.civil_war_strikes > 0:
            remaining = 3 - player.civil_war_strikes
            civil_war_status = f"**🏴‍☠️ Civil War:** Battle {player.civil_war_strikes}/3 ({remaining} more needed)\n"
        
        embed = bot.create_embed(
            f"🏰 {player.civilization_name}",
            f"**👑 Ruler:** {player.username}\n"
            f"{political_status}"
            f"{civil_war_status}\n"
            f"**💰 Resources:**\n"
            f"Gold: {player.gold:,}\n"
            f"Wood: {player.wood:,}\n"
            f"Stone: {player.stone:,}\n"
            f"Food: {player.food:,}\n\n"
            f"**👥 Population:**\n"
            f"Citizens: {player.population:,}\n"
            f"Happiness: {player.happiness}/100\n"
            f"Hunger: {player.hunger}/100\n\n"
            f"**⚔️ Military:**\n"
            f"Soldiers: {player.soldiers:,}\n"
            f"Spies: {player.spies:,}\n"
            f"🧪 Tech Level: {player.tech_level}\n\n"
            f"**🏢 Buildings:**\n{building_list}\n\n"
            f"**🎯 Special Items:**\n"
            f"☢️ Nukes: {player.nukes}\n"
            f"🛡️ Anti-Nuke Shields: {player.anti_nuke_shields}\n"
            f"🔪 Knives: {player.knives}",
            color=0x00ff00
        )
        await ctx.send(embed=embed)
    
    # =============================================================================
    # ECONOMY COMMANDS
    # =============================================================================
    
    @bot.command(name='gather')
    async def gather_resources(ctx):
        """Gather resources"""
        player = get_or_create_player(ctx.author.id, ctx.author.name)
        if not player:
            await ctx.send("❌ Start a civilization first with `.start <name>`")
            return
        
        can_use, time_left = check_cooldown(player, 'gather')
        if not can_use:
            await ctx.send(f"⏰ You must wait {time_left} seconds before gathering again.")
            return
        
        # Random resource gathering
        wood_gain = random.randint(20, 50)
        stone_gain = random.randint(10, 30)
        food_gain = random.randint(15, 35)
        
        player.wood += wood_gain
        player.stone += stone_gain
        player.food += food_gain
        
        player.set_cooldown('gather', COOLDOWNS['gather'])
        db.session.commit()
        
        embed = bot.create_embed(
            "🌲 Resources Gathered!",
            f"Your workers collected:\n"
            f"🪵 Wood: +{wood_gain}\n"
            f"🪨 Stone: +{stone_gain}\n"
            f"🍖 Food: +{food_gain}",
            gif_url=GIFS['gather']
        )
        await ctx.send(embed=embed)
    
    @bot.command(name='build')
    async def build_structure(ctx, building_type: str, quantity: int = 1):
        """Build structures"""
        player = get_or_create_player(ctx.author.id, ctx.author.name)
        if not player:
            await ctx.send("❌ Start a civilization first with `.start <name>`")
            return
        
        can_use, time_left = check_cooldown(player, 'build')
        if not can_use:
            await ctx.send(f"⏰ You must wait {time_left} seconds before building again.")
            return
        
        building_type = building_type.lower()
        if building_type not in BUILDINGS:
            available = ", ".join(BUILDINGS.keys())
            await ctx.send(f"❌ Invalid building type. Available: {available}")
            return
        
        if quantity <= 0:
            await ctx.send("❌ Quantity must be positive!")
            return
        
        # Calculate costs
        costs = BUILDINGS[building_type]
        total_wood = costs['wood'] * quantity
        total_stone = costs['stone'] * quantity
        total_gold = costs['gold'] * quantity
        
        # Check resources
        if (player.wood < total_wood or player.stone < total_stone or player.gold < total_gold):
            await ctx.send(f"❌ Insufficient resources! Need: {total_wood} wood, {total_stone} stone, {total_gold} gold")
            return
        
        # Deduct resources
        player.wood -= total_wood
        player.stone -= total_stone
        player.gold -= total_gold
        
        # Add buildings
        buildings = player.get_buildings()
        buildings[building_type] = buildings.get(building_type, 0) + quantity
        player.set_buildings(buildings)
        
        player.set_cooldown('build', COOLDOWNS['build'])
        db.session.commit()
        
        embed = bot.create_embed(
            "🏗️ Construction Complete!",
            f"Built {quantity} {building_type}(s)!\n\n"
            f"**Costs:**\n"
            f"🪵 Wood: -{total_wood}\n"
            f"🪨 Stone: -{total_stone}\n"
            f"💰 Gold: -{total_gold}",
            gif_url=GIFS['build']
        )
        await ctx.send(embed=embed)
    
    @bot.command(name='buy')
    async def buy_item(ctx, item: str, quantity: int = 1):
        """Buy items from the shop"""
        player = get_or_create_player(ctx.author.id, ctx.author.name)
        if not player:
            await ctx.send("❌ Start a civilization first with `.start <name>`")
            return
        
        can_use, time_left = check_cooldown(player, 'buy')
        if not can_use:
            await ctx.send(f"⏰ You must wait {time_left} seconds before buying again.")
            return
        
        item = item.lower()
        if item not in SHOP_ITEMS:
            available = ", ".join(SHOP_ITEMS.keys())
            await ctx.send(f"❌ Invalid item. Available: {available}")
            return
        
        if quantity <= 0:
            await ctx.send("❌ Quantity must be positive!")
            return
        
        total_cost = SHOP_ITEMS[item]['price'] * quantity
        
        if player.gold < total_cost:
            await ctx.send(f"❌ You need {total_cost:,} gold. You have {player.gold:,}")
            return
        
        player.gold -= total_cost
        
        # Add items to inventory
        if item == 'nuke':
            player.nukes += quantity
        elif item == 'anti_nuke_shield':
            player.anti_nuke_shields += quantity
        elif item == 'knife':
            player.knives += quantity
        
        player.set_cooldown('buy', COOLDOWNS['buy'])
        db.session.commit()
        
        item_name = item.replace('_', ' ').title()
        embed = bot.create_embed(
            "🛒 Purchase Complete!",
            f"Bought {quantity} {item_name}(s) for {total_cost:,} gold!\n\n"
            f"💰 Remaining gold: {player.gold:,}",
            gif_url=GIFS['success']
        )
        await ctx.send(embed=embed)
    
    @bot.command(name='farm')
    async def farm_food(ctx):
        """Farm food for your population"""
        player = get_or_create_player(ctx.author.id, ctx.author.name)
        if not player:
            await ctx.send("❌ Start a civilization first with `.start <name>`")
            return
        
        can_use, time_left = check_cooldown(player, 'farm')
        if not can_use:
            await ctx.send(f"⏰ You must wait {time_left} seconds before farming again.")
            return
        
        # Check for farms
        buildings = player.get_buildings()
        farm_count = buildings.get('farm', 0)
        base_food = random.randint(30, 60)
        farm_bonus = farm_count * random.randint(5, 15)
        total_food = base_food + farm_bonus
        
        player.food += total_food
        player.set_cooldown('farm', COOLDOWNS['farm'])
        db.session.commit()
        
        embed = bot.create_embed(
            "🌾 Harvest Complete!",
            f"Your farmers harvested:\n"
            f"🍖 Food: +{total_food}\n"
            f"🏢 Farm bonus: +{farm_bonus}\n\n"
            f"Total food: {player.food:,}",
            gif_url=GIFS['gather']
        )
        await ctx.send(embed=embed)
    
    @bot.command(name='cheer')
    async def boost_morale(ctx):
        """Boost citizen happiness"""
        player = get_or_create_player(ctx.author.id, ctx.author.name)
        if not player:
            await ctx.send("❌ Start a civilization first with `.start <name>`")
            return
        
        can_use, time_left = check_cooldown(player, 'cheer')
        if not can_use:
            await ctx.send(f"⏰ You must wait {time_left} seconds before cheering again.")
            return
        
        cost = 200
        if player.gold < cost:
            await ctx.send(f"❌ Celebrations cost {cost:,} gold. You have {player.gold:,}")
            return
        
        player.gold -= cost
        happiness_gain = random.randint(15, 30)
        player.happiness = min(100, player.happiness + happiness_gain)
        
        player.set_cooldown('cheer', COOLDOWNS['cheer'])
        db.session.commit()
        
        embed = bot.create_embed(
            "🎉 Celebration!",
            f"Your people celebrate with festivals and parades!\n\n"
            f"😊 Happiness: +{happiness_gain}\n"
            f"💰 Cost: {cost:,} gold",
            gif_url=GIFS['success']
        )
        await ctx.send(embed=embed)
    
    @bot.command(name='feed')
    async def feed_population(ctx):
        """Feed your population to reduce hunger"""
        player = get_or_create_player(ctx.author.id, ctx.author.name)
        if not player:
            await ctx.send("❌ Start a civilization first with `.start <name>`")
            return
        
        can_use, time_left = check_cooldown(player, 'feed')
        if not can_use:
            await ctx.send(f"⏰ You must wait {time_left} seconds before feeding again.")
            return
        
        food_needed = int(player.population * 0.5)
        if player.food < food_needed:
            await ctx.send(f"❌ You need {food_needed:,} food to feed your population. You have {player.food:,}")
            return
        
        player.food -= food_needed
        hunger_reduction = random.randint(20, 40)
        player.hunger = max(0, player.hunger - hunger_reduction)
        
        # Well-fed population is happier
        if player.hunger < 30:
            player.happiness = min(100, player.happiness + 5)
        
        player.set_cooldown('feed', COOLDOWNS['feed'])
        db.session.commit()
        
        embed = bot.create_embed(
            "🍽️ Population Fed!",
            f"Your people have been well fed!\n\n"
            f"🍖 Food consumed: {food_needed:,}\n"
            f"😋 Hunger reduced: -{hunger_reduction}\n"
            f"😊 Happiness bonus applied!",
            gif_url=GIFS['success']
        )
        await ctx.send(embed=embed)
    
    @bot.command(name='gamble')
    async def gamble_resources(ctx):
        """Gamble resources for potential gains"""
        player = get_or_create_player(ctx.author.id, ctx.author.name)
        if not player:
            await ctx.send("❌ Start a civilization first with `.start <name>`")
            return
        
        can_use, time_left = check_cooldown(player, 'gamble')
        if not can_use:
            await ctx.send(f"⏰ You must wait {time_left} seconds before gambling again.")
            return
        
        bet = 500
        if player.gold < bet:
            await ctx.send(f"❌ You need {bet:,} gold to gamble. You have {player.gold:,}")
            return
        
        player.gold -= bet
        
        # 40% chance to win
        if random.random() < 0.4:
            winnings = random.randint(800, 1500)
            player.gold += winnings
            net_gain = winnings - bet
            
            embed = bot.create_embed(
                "🎰 Gambling Win!",
                f"Lady Luck smiles upon you!\n\n"
                f"💰 Winnings: {winnings:,} gold\n"
                f"📈 Net gain: {net_gain:,} gold\n"
                f"💎 Total gold: {player.gold:,}",
                gif_url=GIFS['success']
            )
        else:
            embed = bot.create_embed(
                "🎰 Gambling Loss!",
                f"The house always wins...\n\n"
                f"💸 Lost: {bet:,} gold\n"
                f"💰 Remaining gold: {player.gold:,}",
                color=0xff0000,
                gif_url=GIFS['fail']
            )
        
        player.set_cooldown('gamble', COOLDOWNS['gamble'])
        db.session.commit()
        
        await ctx.send(embed=embed)
    
    # =============================================================================
    # COMBAT COMMANDS
    # =============================================================================
    
    @bot.command(name='attack')
    async def attack_player(ctx, target: guilded.Member):
        """Attack another player"""
        if target.id == ctx.author.id:
            await ctx.send("❌ You cannot attack yourself!")
            return
        
        attacker = get_or_create_player(ctx.author.id, ctx.author.name)
        defender = Player.query.filter_by(user_id=str(target.id)).first()
        
        if not attacker:
            await ctx.send("❌ Start a civilization first with `.start <name>`")
            return
        
        if not defender:
            await ctx.send("❌ Target player hasn't started a civilization yet.")
            return
        
        can_use, time_left = check_cooldown(attacker, 'attack')
        if not can_use:
            await ctx.send(f"⏰ You must wait {time_left} seconds before attacking again.")
            return
        
        # Check for alliance
        alliance = Alliance.query.filter(
            ((Alliance.player1_id == attacker.id) & (Alliance.player2_id == defender.id)) |
            ((Alliance.player1_id == defender.id) & (Alliance.player2_id == attacker.id))
        ).first()
        
        if alliance:
            await ctx.send("❌ You cannot attack an ally! Break the alliance first.")
            return
        
        if attacker.soldiers < 5:
            await ctx.send("❌ You need at least 5 soldiers to attack!")
            return
        
        victory, stolen_gold, stolen_food = GameMechanics.calculate_attack_damage(attacker, defender)
        
        attacker.set_cooldown('attack', COOLDOWNS['attack'])
        
        # Log the attack event
        if victory:
            event_desc = f"{attacker.civilization_name} attacked {defender.civilization_name} and stole {stolen_gold} gold, {stolen_food} food"
            embed = bot.create_embed(
                "⚔️ Victory!",
                f"**{attacker.civilization_name}** conquered **{defender.civilization_name}**!\n\n"
                f"**Spoils of War:**\n"
                f"💰 Gold stolen: {stolen_gold:,}\n"
                f"🍖 Food stolen: {stolen_food:,}",
                gif_url=GIFS['attack']
            )
        else:
            event_desc = f"{defender.civilization_name} repelled {attacker.civilization_name}'s attack"
            embed = bot.create_embed(
                "⚔️ Defeat!",
                f"**{defender.civilization_name}** repelled **{attacker.civilization_name}**'s attack!\n\n"
                f"Your forces suffered heavy casualties.",
                color=0xff0000,
                gif_url=GIFS['fail']
            )
        
        # Create event records
        attack_event = Event(
            player_id=attacker.id,
            target_player_id=defender.id,
            event_type='attack',
            description=event_desc
        )
        db.session.add(attack_event)
        
        db.session.commit()
        
        await ctx.send(embed=embed)
    
    @bot.command(name='stealthbattle')
    async def stealth_attack_player(ctx, target: guilded.Member):
        """Launch a stealth attack on another player"""
        if target.id == ctx.author.id:
            await ctx.send("❌ You cannot attack yourself!")
            return
        
        attacker = get_or_create_player(ctx.author.id, ctx.author.name)
        defender = Player.query.filter_by(user_id=str(target.id)).first()
        
        if not attacker:
            await ctx.send("❌ Start a civilization first with `.start <name>`")
            return
        
        if not defender:
            await ctx.send("❌ Target player hasn't started a civilization yet.")
            return
        
        can_use, time_left = check_cooldown(attacker, 'stealthbattle')
        if not can_use:
            await ctx.send(f"⏰ You must wait {time_left} seconds before launching another stealth attack.")
            return
        
        # Check for alliance
        alliance = Alliance.query.filter(
            ((Alliance.player1_id == attacker.id) & (Alliance.player2_id == defender.id)) |
            ((Alliance.player1_id == defender.id) & (Alliance.player2_id == attacker.id))
        ).first()
        
        if alliance:
            await ctx.send("❌ You cannot stealth attack an ally! Break the alliance first.")
            return
        
        if attacker.soldiers < 8:
            await ctx.send("❌ You need at least 8 soldiers for a stealth operation!")
            return
        
        # Stealth attacks have higher success rate due to surprise
        victory, stolen_gold, stolen_food = GameMechanics.calculate_attack_damage(attacker, defender, is_stealth=True)
        
        attacker.set_cooldown('stealthbattle', COOLDOWNS['stealthbattle'])
        
        # Log the stealth attack event
        if victory:
            event_desc = f"{attacker.civilization_name} launched a stealth attack on {defender.civilization_name} and stole {stolen_gold} gold, {stolen_food} food"
            embed = bot.create_embed(
                "🥷 Stealth Victory!",
                f"**{attacker.civilization_name}** struck **{defender.civilization_name}** under cover of darkness!\n\n"
                f"**Spoils of War:**\n"
                f"💰 Gold stolen: {stolen_gold:,}\n"
                f"🍖 Food stolen: {stolen_food:,}\n\n"
                f"The surprise attack caught them completely off guard!",
                gif_url=GIFS['attack']
            )
        else:
            event_desc = f"{defender.civilization_name} detected and repelled {attacker.civilization_name}'s stealth attack"
            embed = bot.create_embed(
                "🥷 Stealth Failed!",
                f"**{defender.civilization_name}** detected **{attacker.civilization_name}**'s stealth approach!\n\n"
                f"The stealth attack was discovered and repelled with heavy losses!",
                color=0xff0000,
                gif_url=GIFS['fail']
            )
        
        # Create event records
        stealth_event = Event(
            player_id=attacker.id,
            target_player_id=defender.id,
            event_type='stealthbattle',
            description=event_desc
        )
        db.session.add(stealth_event)
        
        db.session.commit()
        
        await ctx.send(embed=embed)
    
    @bot.command(name='civil_war')
    async def civil_war(ctx):
        """Start a civil war to restore order (requires 3 attempts when happiness is low)"""
        player = get_or_create_player(ctx.author.id, ctx.author.name)
        if not player:
            await ctx.send("❌ Start a civilization first with `.start <name>`")
            return
        
        can_use, time_left = check_cooldown(player, 'civil_war')
        if not can_use:
            await ctx.send(f"⏰ You must wait {time_left} seconds before starting another civil war.")
            return
        
        # Check if civil war is needed (low happiness triggers automatic civil war state)
        if player.happiness <= 20 and player.civil_war_strikes == 0:
            player.civil_war_strikes = 1  # Automatically enter civil war state
        
        if player.civil_war_strikes == 0 and player.happiness > 20:
            await ctx.send("❌ Your civilization is stable. Civil wars only occur when happiness is very low (≤20).")
            return
        
        if player.soldiers < 5:
            await ctx.send("❌ You need at least 5 soldiers to fight a civil war!")
            return
        
        # Civil war battle
        soldier_loss = random.randint(2, 5)
        player.soldiers = max(0, player.soldiers - soldier_loss)
        player.civil_war_strikes += 1
        player.set_cooldown('civil_war', COOLDOWNS['civil_war'])
        
        # Log the civil war event
        if player.civil_war_strikes >= 3:
            # Civil war resolved after 3 attempts
            player.civil_war_strikes = 0
            player.happiness = 50  # Restore to moderate level
            event_desc = f"{player.civilization_name} ended their civil war after 3 battles and restored order"
            embed = bot.create_embed(
                "🏛️ Order Restored!",
                f"**{player.civilization_name}** has ended the civil war after 3 brutal conflicts!\n\n"
                f"💀 Final battle casualties: {soldier_loss:,} soldiers\n"
                f"😊 Happiness restored to 50\n"
                f"🏛️ Order and stability have returned to your people!",
                gif_url=GIFS['success']
            )
            civil_event = Event(
                player_id=player.id,
                event_type='civil_war',
                description=event_desc
            )
        else:
            remaining = 3 - player.civil_war_strikes
            event_desc = f"{player.civilization_name} fought civil war battle #{player.civil_war_strikes}"
            embed = bot.create_embed(
                f"⚔️ Civil War Battle #{player.civil_war_strikes}/3",
                f"The civil war in **{player.civilization_name}** continues!\n\n"
                f"💀 Casualties: {soldier_loss:,} soldiers lost\n"
                f"🏴‍☠️ **{remaining} more civil war battles needed** to restore order\n\n"
                f"Your civilization remains divided and unstable.",
                color=0xff0000,
                gif_url=GIFS['civil_war']
            )
            civil_event = Event(
                player_id=player.id,
                event_type='civil_war',
                description=event_desc
            )
        
        db.session.add(civil_event)
        db.session.commit()
        
        await ctx.send(embed=embed)
    
    @bot.command(name='train')
    async def train_military(ctx):
        """Train soldiers and improve spies"""
        player = get_or_create_player(ctx.author.id, ctx.author.name)
        if not player:
            await ctx.send("❌ Start a civilization first with `.start <name>`")
            return
        
        can_use, time_left = check_cooldown(player, 'train')
        if not can_use:
            await ctx.send(f"⏰ You must wait {time_left} seconds before training again.")
            return
        
        cost = 200
        if player.gold < cost:
            await ctx.send(f"❌ Training costs {cost:,} gold. You have {player.gold:,}")
            return
        
        player.gold -= cost
        
        soldiers_trained = random.randint(3, 8)
        spies_trained = random.randint(1, 3)
        
        player.soldiers += soldiers_trained
        player.spies += spies_trained
        
        player.set_cooldown('train', COOLDOWNS['train'])
        db.session.commit()
        
        embed = bot.create_embed(
            "🎖️ Training Complete!",
            f"Military training successful!\n\n"
            f"**New Recruits:**\n"
            f"⚔️ Soldiers: +{soldiers_trained}\n"
            f"🕵️ Spies: +{spies_trained}\n\n"
            f"Cost: {cost:,} gold",
            gif_url=GIFS['success']
        )
        await ctx.send(embed=embed)
    
    @bot.command(name='nuke')
    async def nuke_attack(ctx, target: guilded.Member):
        """Launch a nuclear attack on another civilization"""
        if target.id == ctx.author.id:
            await ctx.send("❌ You cannot nuke yourself!")
            return
        
        attacker = get_or_create_player(ctx.author.id, ctx.author.name)
        defender = Player.query.filter_by(user_id=str(target.id)).first()
        
        if not attacker:
            await ctx.send("❌ Start a civilization first with `.start <name>`")
            return
        
        if not defender:
            await ctx.send("❌ Target player hasn't started a civilization yet.")
            return
        
        can_use, time_left = check_cooldown(attacker, 'nuke')
        if not can_use:
            await ctx.send(f"⏰ You must wait {time_left} seconds before launching another nuke.")
            return
        
        if attacker.nukes < 1:
            await ctx.send("❌ You need at least 1 nuke to launch a nuclear attack! Buy one from the shop first.")
            return
        
        # Check for alliance
        alliance = Alliance.query.filter(
            ((Alliance.player1_id == attacker.id) & (Alliance.player2_id == defender.id)) |
            ((Alliance.player1_id == defender.id) & (Alliance.player2_id == attacker.id))
        ).first()
        
        if alliance:
            await ctx.send("❌ You cannot nuke an ally! Break the alliance first.")
            return
        
        # Check if defender has anti-nuke shields
        if defender.anti_nuke_shields > 0:
            defender.anti_nuke_shields -= 1
            attacker.nukes -= 1
            attacker.set_cooldown('nuke', COOLDOWNS['nuke'])
            
            # Log the intercepted nuke event
            nuke_event = Event(
                player_id=attacker.id,
                target_player_id=defender.id,
                event_type='nuke',
                description=f"{attacker.civilization_name}'s nuclear attack on {defender.civilization_name} was intercepted by anti-nuke shields"
            )
            db.session.add(nuke_event)
            db.session.commit()
            
            embed = bot.create_embed(
                "🛡️ Nuclear Attack Intercepted!",
                f"**{defender.civilization_name}**'s anti-nuke shield intercepted the nuclear missile!\n\n"
                f"The devastating attack was completely neutralized.\n"
                f"Both the nuke and shield were destroyed in the process.",
                color=0x00ff00,
                gif_url=GIFS['success']
            )
            await ctx.send(embed=embed)
            return
        
        # Nuclear attack devastates the target
        attacker.nukes -= 1
        attacker.set_cooldown('nuke', COOLDOWNS['nuke'])
        
        # Nuclear devastation
        soldiers_lost = int(defender.soldiers * 0.7)  # 70% of soldiers die
        gold_lost = int(defender.gold * 0.5)          # 50% of gold destroyed
        food_lost = int(defender.food * 0.6)          # 60% of food destroyed
        buildings_destroyed = int(len(defender.get_buildings()) * 0.4)  # 40% of buildings
        
        defender.soldiers = max(0, defender.soldiers - soldiers_lost)
        defender.gold = max(0, defender.gold - gold_lost)
        defender.food = max(0, defender.food - food_lost)
        defender.happiness = max(0, defender.happiness - 40)  # Massive morale loss
        
        # Destroy some buildings
        buildings = defender.get_buildings()
        if buildings:
            building_types = list(buildings.keys())
            for _ in range(min(buildings_destroyed, len(building_types))):
                if building_types:
                    building_to_destroy = random.choice(building_types)
                    if buildings[building_to_destroy] > 0:
                        buildings[building_to_destroy] -= 1
                        if buildings[building_to_destroy] == 0:
                            building_types.remove(building_to_destroy)
            defender.set_buildings(buildings)
        
        # Log the nuclear attack event
        nuke_event = Event(
            player_id=attacker.id,
            target_player_id=defender.id,
            event_type='nuke',
            description=f"{attacker.civilization_name} launched a nuclear attack on {defender.civilization_name}, causing massive devastation"
        )
        db.session.add(nuke_event)
        
        db.session.commit()
        
        embed = bot.create_embed(
            "☢️ NUCLEAR DEVASTATION!",
            f"**{attacker.civilization_name}** has launched a nuclear strike against **{defender.civilization_name}**!\n\n"
            f"**Catastrophic Damage:**\n"
            f"💀 Soldiers killed: {soldiers_lost:,}\n"
            f"💰 Gold destroyed: {gold_lost:,}\n"
            f"🍖 Food destroyed: {food_lost:,}\n"
            f"🏢 Buildings destroyed: {buildings_destroyed}\n"
            f"😢 Massive morale collapse (-40 happiness)\n\n"
            f"The nuclear fallout will affect the region for generations...",
            color=0xff0000,
            gif_url=GIFS['nuke']
        )
        await ctx.send(embed=embed)
    
    # =============================================================================
    # ESPIONAGE COMMANDS
    # =============================================================================
    
    @bot.command(name='spy')
    async def spy_on_player(ctx, target: guilded.Member):
        """Spy on another player to gather intelligence"""
        if target.id == ctx.author.id:
            await ctx.send("❌ You cannot spy on yourself!")
            return
        
        spy_player = get_or_create_player(ctx.author.id, ctx.author.name)
        target_player = Player.query.filter_by(user_id=str(target.id)).first()
        
        if not spy_player:
            await ctx.send("❌ Start a civilization first with `.start <name>`")
            return
        
        if not target_player:
            await ctx.send("❌ Target player hasn't started a civilization yet.")
            return
        
        can_use, time_left = check_cooldown(spy_player, 'spy')
        if not can_use:
            await ctx.send(f"⏰ You must wait {time_left} seconds before spying again.")
            return
        
        if spy_player.spies < 1:
            await ctx.send("❌ You need at least 1 spy for this mission!")
            return
        
        success, intel = GameMechanics.execute_spy_mission(spy_player, target_player)
        
        spy_player.set_cooldown('spy', COOLDOWNS['spy'])
        
        # Log spy mission event
        if success:
            spy_event = Event(
                player_id=spy_player.id,
                target_player_id=target_player.id,
                event_type='spy_mission',
                description=f"{spy_player.civilization_name} successfully spied on {target_player.civilization_name} and gathered intelligence"
            )
            embed = bot.create_embed(
                "🕵️ Intelligence Report",
                f"Spy mission successful on **{target_player.civilization_name}**!\n\n"
                f"**Gathered Intelligence:**\n"
                f"💰 Gold: {intel['gold']:,}\n"
                f"⚔️ Soldiers: {intel['soldiers']:,}\n"
                f"😊 Happiness: {intel['happiness']}/100\n"
                f"🏢 Buildings: {intel['buildings']}",
                gif_url=GIFS['spy']
            )
        else:
            spy_event = Event(
                player_id=spy_player.id,
                target_player_id=target_player.id,
                event_type='spy_mission',
                description=f"{spy_player.civilization_name}'s spy was caught infiltrating {target_player.civilization_name}"
            )
            embed = bot.create_embed(
                "🕵️ Mission Failed!",
                f"Your spy was caught infiltrating **{target_player.civilization_name}**!\n"
                f"Lost 1 spy in the process.",
                color=0xff0000,
                gif_url=GIFS['fail']
            )
        
        db.session.add(spy_event)
        db.session.commit()
        
        await ctx.send(embed=embed)
    
    @bot.command(name='sabotage')
    async def sabotage_player(ctx, target: guilded.Member):
        """Sabotage another player's infrastructure"""
        if target.id == ctx.author.id:
            await ctx.send("❌ You cannot sabotage yourself!")
            return
        
        saboteur = get_or_create_player(ctx.author.id, ctx.author.name)
        target_player = Player.query.filter_by(user_id=str(target.id)).first()
        
        if not saboteur:
            await ctx.send("❌ Start a civilization first with `.start <name>`")
            return
        
        if not target_player:
            await ctx.send("❌ Target player hasn't started a civilization yet.")
            return
        
        can_use, time_left = check_cooldown(saboteur, 'sabotage')
        if not can_use:
            await ctx.send(f"⏰ You must wait {time_left} seconds before sabotaging again.")
            return
        
        if saboteur.spies < 2:
            await ctx.send("❌ You need at least 2 spies for sabotage missions!")
            return
        
        # 50% base success chance
        success_chance = 50 + (saboteur.spies * 3) - (target_player.spies * 2)
        success = random.randint(1, 100) <= success_chance
        
        saboteur.set_cooldown('sabotage', COOLDOWNS['sabotage'])
        
        if success:
            # Successful sabotage
            gold_destroyed = random.randint(100, 300)
            food_destroyed = random.randint(50, 150)
            
            target_player.gold = max(0, target_player.gold - gold_destroyed)
            target_player.food = max(0, target_player.food - food_destroyed)
            target_player.happiness = max(0, target_player.happiness - 10)
            
            # Log successful sabotage
            sabotage_event = Event(
                player_id=saboteur.id,
                target_player_id=target_player.id,
                event_type='sabotage',
                description=f"{saboteur.civilization_name} sabotaged {target_player.civilization_name}, destroying {gold_destroyed} gold and {food_destroyed} food"
            )
            
            embed = bot.create_embed(
                "💥 Sabotage Successful!",
                f"Your spies sabotaged **{target_player.civilization_name}**!\n\n"
                f"**Damage Caused:**\n"
                f"💰 Gold destroyed: {gold_destroyed:,}\n"
                f"🍖 Food destroyed: {food_destroyed:,}\n"
                f"😢 Morale damage: -10 happiness",
                gif_url=GIFS['spy']
            )
        else:
            # Failed sabotage
            spies_lost = 1
            saboteur.spies = max(0, saboteur.spies - spies_lost)
            
            # Log failed sabotage
            sabotage_event = Event(
                player_id=saboteur.id,
                target_player_id=target_player.id,
                event_type='sabotage',
                description=f"{saboteur.civilization_name}'s sabotage mission against {target_player.civilization_name} was thwarted"
            )
            
            embed = bot.create_embed(
                "💥 Sabotage Failed!",
                f"Your sabotage mission against **{target_player.civilization_name}** was discovered!\n\n"
                f"🕵️ Lost 1 spy",
                color=0xff0000,
                gif_url=GIFS['fail']
            )
        
        db.session.add(sabotage_event)
        db.session.commit()
        
        await ctx.send(embed=embed)
    
    @bot.command(name='hack')
    async def hack_player(ctx, target: guilded.Member):
        """Hack another player's systems to steal resources"""
        if target.id == ctx.author.id:
            await ctx.send("❌ You cannot hack yourself!")
            return
        
        hacker = get_or_create_player(ctx.author.id, ctx.author.name)
        target_player = Player.query.filter_by(user_id=str(target.id)).first()
        
        if not hacker:
            await ctx.send("❌ Start a civilization first with `.start <name>`")
            return
        
        if not target_player:
            await ctx.send("❌ Target player hasn't started a civilization yet.")
            return
        
        can_use, time_left = check_cooldown(hacker, 'hack')
        if not can_use:
            await ctx.send(f"⏰ You must wait {time_left} seconds before hacking again.")
            return
        
        if hacker.spies < 3:
            await ctx.send("❌ You need at least 3 spies for hacking operations!")
            return
        
        # 45% base success chance
        success_chance = 45 + (hacker.spies * 2) + (hacker.tech_level * 5) - (target_player.tech_level * 3)
        success = random.randint(1, 100) <= success_chance
        
        hacker.set_cooldown('hack', COOLDOWNS['hack'])
        
        if success:
            # Successful hack - steal resources
            gold_stolen = random.randint(200, 500)
            gold_stolen = min(gold_stolen, target_player.gold)
            
            target_player.gold -= gold_stolen
            hacker.gold += gold_stolen
            
            # Log successful hack
            hack_event = Event(
                player_id=hacker.id,
                target_player_id=target_player.id,
                event_type='hack',
                description=f"{hacker.civilization_name} hacked {target_player.civilization_name} and stole {gold_stolen} gold"
            )
            
            embed = bot.create_embed(
                "💻 Hack Successful!",
                f"Your cyber specialists infiltrated **{target_player.civilization_name}**'s systems!\n\n"
                f"**Digital Theft:**\n"
                f"💰 Gold stolen: {gold_stolen:,}\n"
                f"🔒 Security bypassed using advanced technology",
                gif_url=GIFS['spy']
            )
        else:
            # Failed hack
            spies_lost = 1
            hacker.spies = max(0, hacker.spies - spies_lost)
            
            # Log failed hack
            hack_event = Event(
                player_id=hacker.id,
                target_player_id=target_player.id,
                event_type='hack',
                description=f"{hacker.civilization_name}'s hacking attempt against {target_player.civilization_name} was detected and blocked"
            )
            
            embed = bot.create_embed(
                "💻 Hack Failed!",
                f"Your hacking attempt against **{target_player.civilization_name}** was detected!\n\n"
                f"🕵️ Lost 1 spy to counter-intelligence\n"
                f"🛡️ Their security systems proved too strong",
                color=0xff0000,
                gif_url=GIFS['fail']
            )
        
        db.session.add(hack_event)
        db.session.commit()
        
        await ctx.send(embed=embed)
    
    # =============================================================================
    # ALLIANCE COMMANDS
    # =============================================================================
    
    @bot.command(name='ally')
    async def form_alliance(ctx, target: guilded.Member):
        """Form an alliance with another player"""
        if target.id == ctx.author.id:
            await ctx.send("❌ You cannot form an alliance with yourself!")
            return
        
        player1 = get_or_create_player(ctx.author.id, ctx.author.name)
        player2 = Player.query.filter_by(user_id=str(target.id)).first()
        
        if not player1:
            await ctx.send("❌ Start a civilization first with `.start <name>`")
            return
        
        if not player2:
            await ctx.send("❌ Target player hasn't started a civilization yet.")
            return
        
        can_use, time_left = check_cooldown(player1, 'ally')
        if not can_use:
            await ctx.send(f"⏰ You must wait {time_left} seconds before forming another alliance.")
            return
        
        # Check if alliance already exists
        existing = Alliance.query.filter(
            ((Alliance.player1_id == player1.id) & (Alliance.player2_id == player2.id)) |
            ((Alliance.player1_id == player2.id) & (Alliance.player2_id == player1.id))
        ).first()
        
        if existing:
            await ctx.send(f"❌ You already have an alliance with **{player2.civilization_name}**!")
            return
        
        # Create alliance
        alliance = Alliance(player1_id=player1.id, player2_id=player2.id)
        db.session.add(alliance)
        
        # Both players gain happiness from alliance
        player1.happiness = min(100, player1.happiness + 10)
        player2.happiness = min(100, player2.happiness + 10)
        
        player1.set_cooldown('ally', COOLDOWNS['ally'])
        
        # Log alliance formation event
        ally_event = Event(
            player_id=player1.id,
            target_player_id=player2.id,
            event_type='ally_formed',
            description=f"{player1.civilization_name} formed an alliance with {player2.civilization_name}"
        )
        db.session.add(ally_event)
        
        db.session.commit()
        
        embed = bot.create_embed(
            "🤝 Alliance Formed!",
            f"**{player1.civilization_name}** and **{player2.civilization_name}** have formed an alliance!\n\n"
            f"Both civilizations cannot attack each other and gain +10 happiness.\n"
            f"Use `.break {target.mention}` to dissolve the alliance.",
            gif_url=GIFS['success']
        )
        await ctx.send(embed=embed)
    
    @bot.command(name='break')
    async def break_alliance(ctx, target: guilded.Member):
        """Break an alliance with another player"""
        player1 = get_or_create_player(ctx.author.id, ctx.author.name)
        player2 = Player.query.filter_by(user_id=str(target.id)).first()
        
        if not player1:
            await ctx.send("❌ Start a civilization first with `.start <name>`")
            return
        
        if not player2:
            await ctx.send("❌ Target player hasn't started a civilization yet.")
            return
        
        can_use, time_left = check_cooldown(player1, 'break')
        if not can_use:
            await ctx.send(f"⏰ You must wait {time_left} seconds before breaking another alliance.")
            return
        
        # Find alliance
        alliance = Alliance.query.filter(
            ((Alliance.player1_id == player1.id) & (Alliance.player2_id == player2.id)) |
            ((Alliance.player1_id == player2.id) & (Alliance.player2_id == player1.id))
        ).first()
        
        if not alliance:
            await ctx.send(f"❌ You don't have an alliance with **{player2.civilization_name}**!")
            return
        
        # Remove alliance
        db.session.delete(alliance)
        
        # Happiness penalties for betrayal
        player1.happiness = max(0, player1.happiness - 15)
        player2.happiness = max(0, player2.happiness - 20)  # Betrayed player loses more
        
        player1.set_cooldown('break', COOLDOWNS['break'])
        
        # Log alliance breaking event
        break_event = Event(
            player_id=player1.id,
            target_player_id=player2.id,
            event_type='ally_broken',
            description=f"{player1.civilization_name} betrayed and broke alliance with {player2.civilization_name}"
        )
        db.session.add(break_event)
        
        db.session.commit()
        
        embed = bot.create_embed(
            "💔 Alliance Broken!",
            f"**{player1.civilization_name}** has betrayed **{player2.civilization_name}**!\n\n"
            f"The alliance has been dissolved.\n"
            f"Both civilizations suffer happiness penalties from this betrayal.\n"
            f"You can now attack each other again.",
            color=0xff0000,
            gif_url=GIFS['fail']
        )
        await ctx.send(embed=embed)
    
    # =============================================================================
    # TECHNOLOGY COMMANDS
    # =============================================================================
    
    @bot.command(name='invent')
    async def research_technology(ctx):
        """Research new technology to improve your civilization"""
        player = get_or_create_player(ctx.author.id, ctx.author.name)
        if not player:
            await ctx.send("❌ Start a civilization first with `.start <name>`")
            return
        
        can_use, time_left = check_cooldown(player, 'invent')
        if not can_use:
            await ctx.send(f"⏰ You must wait {time_left} seconds before researching again.")
            return
        
        # Technology research costs scale with current tech level
        base_cost = 2000
        cost = base_cost + (player.tech_level * 500)
        
        if player.gold < cost:
            await ctx.send(f"❌ You need {cost:,} gold to research new technology!")
            return
        
        player.gold -= cost
        player.tech_level += 1
        player.set_cooldown('invent', COOLDOWNS['invent'])
        
        # Random technology discoveries
        tech_names = [
            "Advanced Metallurgy", "Siege Engineering", "Military Tactics", "Fortification",
            "Logistics", "Communication Networks", "Naval Technology", "Cryptography",
            "Engineering", "Architecture", "Medicine", "Agriculture", "Mathematics"
        ]
        
        discovered_tech = random.choice(tech_names)
        
        # Log the invention event
        invent_event = Event(
            player_id=player.id,
            event_type='invention',
            description=f"{player.civilization_name} discovered {discovered_tech} (Tech Level {player.tech_level})"
        )
        db.session.add(invent_event)
        
        db.session.commit()
        
        embed = bot.create_embed(
            "🔬 Scientific Breakthrough!",
            f"**{player.civilization_name}** has made a technological advancement!\n\n"
            f"**Discovery:** {discovered_tech}\n"
            f"🧪 Tech Level: {player.tech_level}\n"
            f"💰 Research Cost: {cost:,} gold\n\n"
            f"⚔️ Combat Bonus: +{player.tech_level * 5}%\n"
            f"🛡️ Defense Bonus: +{player.tech_level * 3}%",
            gif_url=GIFS['success']
        )
        await ctx.send(embed=embed)
    
    @bot.command(name='tech')
    async def show_technology(ctx):
        """Show your current technology level and research progress"""
        player = get_or_create_player(ctx.author.id, ctx.author.name)
        if not player:
            await ctx.send("❌ Start a civilization first with `.start <name>`")
            return
        
        next_cost = 2000 + (player.tech_level * 500)
        combat_bonus = player.tech_level * 5
        defense_bonus = player.tech_level * 3
        
        embed = bot.create_embed(
            "🔬 Technology Status",
            f"**{player.civilization_name}** Science Department\n\n"
            f"🧪 **Current Tech Level:** {player.tech_level}\n"
            f"⚔️ **Combat Bonus:** +{combat_bonus}%\n"
            f"🛡️ **Defense Bonus:** +{defense_bonus}%\n\n"
            f"**Next Research:**\n"
            f"💰 Cost: {next_cost:,} gold\n"
            f"📈 Will increase combat bonus to +{(player.tech_level + 1) * 5}%",
            color=0x0066cc
        )
        await ctx.send(embed=embed)
    
    # =============================================================================
    # COMMUNICATION COMMANDS
    # =============================================================================
    
    @bot.command(name='send')
    async def send_message(ctx, target: guilded.Member, *, message_content: str):
        """Send a diplomatic message"""
        sender = get_or_create_player(ctx.author.id, ctx.author.name)
        recipient = Player.query.filter_by(user_id=str(target.id)).first()
        
        if not sender:
            await ctx.send("❌ Start a civilization first with `.start <name>`")
            return
        
        if not recipient:
            await ctx.send("❌ Target player hasn't started a civilization yet.")
            return
        
        if target.id == ctx.author.id:
            await ctx.send("❌ You cannot send a message to yourself!")
            return
        
        # Create message
        message = Message(
            sender_id=sender.id,
            recipient_id=recipient.id,
            content=message_content[:500]  # Limit message length
        )
        db.session.add(message)
        
        # Log message event
        message_event = Event(
            player_id=sender.id,
            target_player_id=recipient.id,
            event_type='message',
            description=f"{sender.civilization_name} sent a diplomatic message to {recipient.civilization_name}"
        )
        db.session.add(message_event)
        
        db.session.commit()
        
        embed = bot.create_embed(
            "📧 Message Sent!",
            f"Your diplomatic message has been delivered to **{recipient.civilization_name}**!\n\n"
            f"**Message Preview:**\n{message_content[:100]}{'...' if len(message_content) > 100 else ''}",
            gif_url=GIFS['success']
        )
        await ctx.send(embed=embed)
    
    @bot.command(name='mail')
    async def check_mail(ctx):
        """Check your diplomatic messages"""
        player = get_or_create_player(ctx.author.id, ctx.author.name)
        if not player:
            await ctx.send("❌ Start a civilization first with `.start <name>`")
            return
        
        messages = Message.query.filter_by(recipient_id=player.id).order_by(Message.created_at.desc()).limit(5).all()
        
        if not messages:
            embed = bot.create_embed(
                "📧 No Messages",
                "Your diplomatic mailbox is empty.",
                color=0x666666
            )
            await ctx.send(embed=embed)
            return
        
        message_list = []
        for msg in messages:
            status = "📩" if not msg.read else "📧"
            sender_name = msg.sender.civilization_name
            preview = msg.content[:50] + "..." if len(msg.content) > 50 else msg.content
            time_ago = (datetime.utcnow() - msg.created_at).total_seconds() / 3600
            
            if time_ago < 1:
                time_str = f"{int(time_ago * 60)}m ago"
            elif time_ago < 24:
                time_str = f"{int(time_ago)}h ago"
            else:
                time_str = f"{int(time_ago / 24)}d ago"
            
            message_list.append(f"{status} **{sender_name}** ({time_str})\n{preview}")
            
            # Mark as read
            msg.read = True
        
        db.session.commit()
        
        embed = bot.create_embed(
            "📧 Diplomatic Messages",
            "\n\n".join(message_list),
            color=0x0066cc
        )
        await ctx.send(embed=embed)
    
    # =============================================================================
    # RESOURCE SHARING COMMANDS
    # =============================================================================
    
    @bot.command(name='provide')
    async def provide_resources(ctx, target: guilded.Member, resource_type: str, amount: int):
        """Provide resources to another player"""
        if target.id == ctx.author.id:
            await ctx.send("❌ You cannot provide resources to yourself!")
            return
        
        provider = get_or_create_player(ctx.author.id, ctx.author.name)
        recipient = Player.query.filter_by(user_id=str(target.id)).first()
        
        if not provider:
            await ctx.send("❌ Start a civilization first with `.start <name>`")
            return
        
        if not recipient:
            await ctx.send("❌ Target player hasn't started a civilization yet.")
            return
        
        can_use, time_left = check_cooldown(provider, 'provide')
        if not can_use:
            await ctx.send(f"⏰ You must wait {time_left} seconds before providing resources again.")
            return
        
        if amount <= 0:
            await ctx.send("❌ Amount must be positive!")
            return
        
        resource_type = resource_type.lower()
        valid_resources = ['gold', 'wood', 'stone', 'food']
        
        if resource_type not in valid_resources:
            await ctx.send(f"❌ Invalid resource type! Valid resources: {', '.join(valid_resources)}")
            return
        
        # Check if provider has enough resources
        provider_amount = getattr(provider, resource_type)
        if provider_amount < amount:
            await ctx.send(f"❌ You don't have enough {resource_type}! You have {provider_amount:,}, need {amount:,}")
            return
        
        # Transfer resources
        setattr(provider, resource_type, provider_amount - amount)
        recipient_amount = getattr(recipient, resource_type)
        setattr(recipient, resource_type, recipient_amount + amount)
        
        provider.set_cooldown('provide', COOLDOWNS['provide'])
        
        # Log the resource sharing event
        provide_event = Event(
            player_id=provider.id,
            target_player_id=recipient.id,
            event_type='resource_sharing',
            description=f"{provider.civilization_name} provided {amount:,} {resource_type} to {recipient.civilization_name}"
        )
        db.session.add(provide_event)
        
        db.session.commit()
        
        resource_emojis = {'gold': '💰', 'wood': '🪵', 'stone': '🪨', 'food': '🍖'}
        
        embed = bot.create_embed(
            "🤝 Resources Provided!",
            f"**{provider.civilization_name}** has generously provided resources to **{recipient.civilization_name}**!\n\n"
            f"**Transfer:**\n"
            f"{resource_emojis[resource_type]} {amount:,} {resource_type.title()}\n\n"
            f"This act of diplomacy strengthens ties between civilizations!",
            gif_url=GIFS['success']
        )
        await ctx.send(embed=embed)
    
    # =============================================================================
    # PUPPET STATE COMMANDS
    # =============================================================================
    
    @bot.command(name='puppet')
    async def create_puppet_state(ctx, target: guilded.Member):
        """Turn a defeated civilization into your puppet state"""
        conqueror = get_or_create_player(ctx.author.id, ctx.author.name)
        target_player = Player.query.filter_by(user_id=str(target.id)).first()
        
        if not conqueror:
            await ctx.send("❌ Start a civilization first with `.start <name>`")
            return
        
        if not target_player:
            await ctx.send("❌ Target player hasn't started a civilization yet.")
            return
        
        if target.id == ctx.author.id:
            await ctx.send("❌ You cannot make yourself a puppet state!")
            return
        
        can_use, time_left = check_cooldown(conqueror, 'puppet')
        if not can_use:
            await ctx.send(f"⏰ You must wait {time_left} seconds before creating another puppet state.")
            return
        
        # Check if target is weak enough to puppet (less than 20% of conqueror's soldiers)
        min_required_soldiers = int(target_player.soldiers * 5)  # Need 5x their army
        if conqueror.soldiers < min_required_soldiers:
            await ctx.send(f"❌ You need at least {min_required_soldiers:,} soldiers to puppet **{target_player.civilization_name}** (they have {target_player.soldiers:,} soldiers)")
            return
        
        # Check if target has low happiness (easier to puppet demoralized civilizations)
        if target_player.happiness > 30:
            await ctx.send(f"❌ **{target_player.civilization_name}** has too high morale ({target_player.happiness}/100) to puppet! Attack them first to lower their morale.")
            return
        
        # Check for alliance
        alliance = Alliance.query.filter(
            ((Alliance.player1_id == conqueror.id) & (Alliance.player2_id == target_player.id)) |
            ((Alliance.player1_id == target_player.id) & (Alliance.player2_id == conqueror.id))
        ).first()
        
        if alliance:
            await ctx.send("❌ You cannot puppet an ally! Break the alliance first.")
            return
        
        # Create puppet state
        target_player.is_puppet = True
        target_player.puppet_master_id = conqueror.id
        target_player.happiness = max(0, target_player.happiness - 20)  # Further demoralization
        
        conqueror.set_cooldown('puppet', COOLDOWNS['puppet'])
        
        # Log the puppet creation event
        puppet_event = Event(
            player_id=conqueror.id,
            target_player_id=target_player.id,
            event_type='puppet_creation',
            description=f"{conqueror.civilization_name} established {target_player.civilization_name} as a puppet state"
        )
        db.session.add(puppet_event)
        
        db.session.commit()
        
        embed = bot.create_embed(
            "👑 Puppet State Established!",
            f"**{conqueror.civilization_name}** has established **{target_player.civilization_name}** as a puppet state!\n\n"
            f"**{target_player.civilization_name}** is now under the political control of **{conqueror.civilization_name}**.\n\n"
            f"The puppet state can only regain independence through a successful revolt.",
            color=0x800080,
            gif_url=GIFS['success']
        )
        await ctx.send(embed=embed)
    
    @bot.command(name='revolt')
    async def revolt_against_master(ctx):
        """Revolt against your puppet master to regain independence"""
        player = get_or_create_player(ctx.author.id, ctx.author.name)
        if not player:
            await ctx.send("❌ Start a civilization first with `.start <name>`")
            return
        
        if not player.is_puppet:
            await ctx.send("❌ You are not a puppet state! This command is only for puppet states.")
            return
        
        can_use, time_left = check_cooldown(player, 'revolt')
        if not can_use:
            await ctx.send(f"⏰ You must wait {time_left} seconds before attempting another revolt.")
            return
        
        puppet_master = Player.query.get(player.puppet_master_id)
        if not puppet_master:
            # Master no longer exists, automatically free
            player.is_puppet = False
            player.puppet_master_id = None
            db.session.commit()
            await ctx.send("🎉 Your puppet master no longer exists! You are now free!")
            return
        
        # Revolt success chance based on relative strength and happiness
        base_chance = 30  # 30% base chance
        happiness_bonus = player.happiness * 0.5  # Higher happiness helps
        strength_ratio = (player.soldiers / max(puppet_master.soldiers, 1)) * 100
        strength_bonus = min(strength_ratio * 0.3, 30)  # Max 30% bonus from strength
        
        success_chance = base_chance + happiness_bonus + strength_bonus
        success = random.randint(1, 100) <= success_chance
        
        player.set_cooldown('revolt', COOLDOWNS['revolt'])
        
        if success:
            # Successful revolt
            player.is_puppet = False
            player.puppet_master_id = None
            player.happiness = min(100, player.happiness + 30)  # Liberation boost
            
            # Master loses some soldiers (revolt suppression costs)
            soldiers_lost = int(puppet_master.soldiers * 0.1)
            puppet_master.soldiers = max(0, puppet_master.soldiers - soldiers_lost)
            
            # Log the successful revolt
            revolt_event = Event(
                player_id=player.id,
                target_player_id=puppet_master.id,
                event_type='revolt',
                description=f"{player.civilization_name} successfully revolted against {puppet_master.civilization_name} and regained independence"
            )
            db.session.add(revolt_event)
            
            embed = bot.create_embed(
                "🗽 INDEPENDENCE ACHIEVED!",
                f"**{player.civilization_name}** has successfully revolted against **{puppet_master.civilization_name}**!\n\n"
                f"🎉 Your civilization is now free and independent!\n"
                f"😊 Morale boost: +30 happiness\n"
                f"⚔️ **{puppet_master.civilization_name}** lost {soldiers_lost:,} soldiers suppressing the revolt\n\n"
                f"Freedom has been restored to your people!",
                color=0x00ff00,
                gif_url=GIFS['success']
            )
        else:
            # Failed revolt
            soldiers_lost = int(player.soldiers * 0.2)  # 20% casualties
            player.soldiers = max(0, player.soldiers - soldiers_lost)
            player.happiness = max(0, player.happiness - 15)  # Crushing defeat
            
            # Log the failed revolt
            revolt_event = Event(
                player_id=player.id,
                target_player_id=puppet_master.id,
                event_type='revolt',
                description=f"{player.civilization_name}'s revolt against {puppet_master.civilization_name} was crushed"
            )
            db.session.add(revolt_event)
            
            embed = bot.create_embed(
                "💔 Revolt Crushed!",
                f"**{player.civilization_name}**'s revolt against **{puppet_master.civilization_name}** has been brutally suppressed!\n\n"
                f"💀 Casualties: {soldiers_lost:,} soldiers lost\n"
                f"😢 Morale penalty: -15 happiness\n\n"
                f"The dream of independence will have to wait...",
                color=0xff0000,
                gif_url=GIFS['fail']
            )
        
        db.session.commit()
        await ctx.send(embed=embed)
    
    # =============================================================================
    # UTILITY COMMANDS
    # =============================================================================
    
    @bot.command(name='shop')
    async def show_shop(ctx):
        """Display the shop"""
        shop_items = []
        for item, details in SHOP_ITEMS.items():
            item_name = item.replace('_', ' ').title()
            price = details['price']
            item_type = details['type'].title()
            shop_items.append(f"**{item_name}** - {price:,} gold ({item_type})")
        
        embed = bot.create_embed(
            "🏪 War Shop",
            "Use `.buy <item> [amount]` to purchase items:\n\n" + "\n".join(shop_items),
            color=0xffd700
        )
        await ctx.send(embed=embed)
    
    @bot.command(name='lore')
    async def show_lore(ctx, event_type: str = None, limit: int = 10):
        """Show civilization history and lore"""
        player = get_or_create_player(ctx.author.id, ctx.author.name)
        if not player:
            await ctx.send("❌ Start a civilization first with `.start <name>`")
            return
        
        # Build query for events
        query = Event.query
        
        if event_type:
            event_type = event_type.lower()
            valid_types = ['battle', 'alliance', 'message', 'disaster', 'spy', 'nuke', 'all']
            if event_type not in valid_types:
                await ctx.send(f"❌ Invalid event type. Valid types: {', '.join(valid_types)}")
                return
            
            if event_type != 'all':
                if event_type == 'battle':
                    query = query.filter(Event.event_type.in_(['attack', 'civil_war', 'backstab', 'stealthbattle']))
                elif event_type == 'alliance':
                    query = query.filter(Event.event_type.in_(['ally_formed', 'ally_broken']))
                elif event_type == 'spy':
                    query = query.filter(Event.event_type.in_(['spy_mission', 'sabotage', 'hack']))
                else:
                    query = query.filter(Event.event_type == event_type)
        
        # Filter to events involving this player
        query = query.filter(
            (Event.player_id == player.id) | 
            (Event.target_player_id == player.id)
        )
        
        # Get recent events
        events = query.order_by(Event.created_at.desc()).limit(min(limit, 20)).all()
        
        if not events:
            embed = bot.create_embed(
                "📜 Civilization Lore",
                f"No historical events found for **{player.civilization_name}**.\n"
                f"Start your legend by interacting with other civilizations!",
                color=0x8b4513
            )
            await ctx.send(embed=embed)
            return
        
        # Format events for display
        lore_entries = []
        for event in events:
            timestamp = event.created_at.strftime("%m/%d %H:%M")
            
            # Get emoji for event type
            emoji_map = {
                'attack': '⚔️',
                'civil_war': '🏴‍☠️',
                'backstab': '🗡️',
                'nuke': '☢️',
                'stealthbattle': '🥷',
                'spy_mission': '🕵️',
                'sabotage': '💥',
                'hack': '💻',
                'ally_formed': '🤝',
                'ally_broken': '💔',
                'disaster': '🌪️',
                'message': '📧',
                'invention': '🔬',
                'resource_sharing': '🤝',
                'puppet_creation': '👑',
                'revolt': '🗽'
            }
            
            emoji = emoji_map.get(event.event_type, '📅')
            entry = f"{emoji} `{timestamp}` {event.description}"
            lore_entries.append(entry)
        
        # Create embed with lore
        title = f"📜 {player.civilization_name} - Historical Chronicles"
        if event_type and event_type != 'all':
            title += f" ({event_type.title()} Events)"
        
        description = f"**Recent events in the life of {player.civilization_name}:**\n\n"
        description += "\n".join(lore_entries)
        
        if len(events) == limit and limit < 20:
            description += f"\n\n*Use `.lore {event_type or 'all'} {limit + 10}` to see more events*"
        
        embed = bot.create_embed(
            title,
            description,
            color=0x8b4513
        )
        
        await ctx.send(embed=embed)
    
    return bot

# =============================================================================
# DISASTER SYSTEM
# =============================================================================

async def disaster_system(bot):
    """Background task for random disasters"""
    while True:
        try:
            await asyncio.sleep(1800)  # Check every 30 minutes
            
            players = Player.query.filter(Player.last_active > datetime.utcnow() - timedelta(hours=2)).all()
            
            if players and random.random() < 0.3:  # 30% chance
                victim = random.choice(players)
                
                disasters = [
                    {
                        'name': 'Earthquake',
                        'emoji': '🌍',
                        'damage': lambda p: {
                            'soldiers': random.randint(5, 15),
                            'buildings': 1,
                            'happiness': random.randint(10, 20)
                        }
                    },
                    {
                        'name': 'Plague',
                        'emoji': '🦠',
                        'damage': lambda p: {
                            'population': int(p.population * 0.1),
                            'happiness': random.randint(15, 25)
                        }
                    },
                    {
                        'name': 'Famine',
                        'emoji': '🌾',
                        'damage': lambda p: {
                            'food': int(p.food * 0.3),
                            'happiness': random.randint(10, 20)
                        }
                    },
                    {
                        'name': 'Economic Crisis',
                        'emoji': '💸',
                        'damage': lambda p: {
                            'gold': int(p.gold * 0.2),
                            'happiness': random.randint(5, 15)
                        }
                    }
                ]
                
                disaster = random.choice(disasters)
                damage = disaster['damage'](victim)
                
                # Apply damage
                for attr, amount in damage.items():
                    if hasattr(victim, attr):
                        current = getattr(victim, attr)
                        setattr(victim, attr, max(0, current - amount))
                
                # Log disaster event
                disaster_event = Event(
                    player_id=victim.id,
                    event_type='disaster',
                    description=f"{victim.civilization_name} was struck by a {disaster['name']}"
                )
                db.session.add(disaster_event)
                db.session.commit()
                
        except Exception as e:
            print(f"Disaster system error: {e}")

# =============================================================================
# MAIN APPLICATION
# =============================================================================

def main():
    """Main application entry point"""
    print("🏰 Starting WarBot Civilization Management System...")
    print("=" * 50)
    
    # Create Flask app
    flask_app = create_flask_app()
    
    # Create database tables
    with flask_app.app_context():
        db.create_all()
        print("Database tables created successfully!")
    
    # Create Guilded bot
    
    def run_flask():
        """Run Flask server in a separate thread"""
        print("Starting Flask web server on port 5000...")
        flask_app.run(host='0.0.0.0', port=5000, debug=False)
    
    def run_guilded():
        """Run Guilded bot"""
        print("Starting Guilded bot...")
        token = os.environ.get('GUILDED_BOT_TOKEN')
        if not token:
            print("❌ GUILDED_BOT_TOKEN environment variable not set!")
            return
        
        print("Bot token configured: Yes")
        
        # Start disaster system
        async def start_with_disasters():
            async with guilded_bot:
                # Start disaster system in background
                disaster_task = asyncio.create_task(disaster_system(guilded_bot))
                
                # Start bot
                await guilded_bot.start(token)
        
        asyncio.run(start_with_disasters())
    
    # Start Flask server in background thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Start Guilded bot (main thread)
    run_guilded()

if __name__ == "__main__":
    main()
