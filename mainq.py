"""
WarBot - A comprehensive civilization-building game bot for Guilded
Complete multiplayer strategy game with economy, combat, territory, and diplomacy systems
"""

import os
import asyncio
import random
import threading
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

import guilded
from guilded.ext import commands
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, ForeignKey, Float
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session
from flask import Flask, render_template_string, jsonify

# Database setup
Base = declarative_base()
engine = create_engine('sqlite:///warbot.db', echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Database Models
class Player(Base):
    __tablename__ = "players"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, unique=True, index=True)
    username = Column(String)
    civ_name = Column(String)
    
    # Resources
    gold = Column(Integer, default=100)
    wood = Column(Integer, default=50)
    stone = Column(Integer, default=50)
    food = Column(Integer, default=100)
    
    # Population
    citizens = Column(Integer, default=10)
    happiness = Column(Integer, default=50)
    hunger = Column(Integer, default=30)
    
    # Military
    soldiers = Column(Integer, default=5)
    spies = Column(Integer, default=2)
    tech_level = Column(Integer, default=1)
    
    # Territory
    territory = Column(Float, default=10.0)  # square km
    
    # Buildings
    houses = Column(Integer, default=1)
    farms = Column(Integer, default=1)
    barracks = Column(Integer, default=0)
    walls = Column(Integer, default=0)
    markets = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    cooldowns = relationship("Cooldown", back_populates="player")
    items = relationship("PlayerItem", back_populates="player")
    alliances_sent = relationship("Alliance", foreign_keys="Alliance.sender_id", back_populates="sender")
    alliances_received = relationship("Alliance", foreign_keys="Alliance.receiver_id", back_populates="receiver")
    messages_sent = relationship("Message", foreign_keys="Message.sender_id", back_populates="sender")
    messages_received = relationship("Message", foreign_keys="Message.receiver_id", back_populates="receiver")

class Cooldown(Base):
    __tablename__ = "cooldowns"
    
    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("players.id"))
    command = Column(String)
    expires_at = Column(DateTime)
    
    player = relationship("Player", back_populates="cooldowns")

class SpecialItem(Base):
    __tablename__ = "special_items"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True)
    description = Column(Text)
    effect = Column(String)
    rarity = Column(String)  # common, rare, legendary

class PlayerItem(Base):
    __tablename__ = "player_items"
    
    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("players.id"))
    item_id = Column(Integer, ForeignKey("special_items.id"))
    quantity = Column(Integer, default=1)
    
    player = relationship("Player", back_populates="items")
    item = relationship("SpecialItem")

class Alliance(Base):
    __tablename__ = "alliances"
    
    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("players.id"))
    receiver_id = Column(Integer, ForeignKey("players.id"))
    status = Column(String)  # pending, accepted, rejected
    created_at = Column(DateTime, default=datetime.utcnow)
    
    sender = relationship("Player", foreign_keys=[sender_id], back_populates="alliances_sent")
    receiver = relationship("Player", foreign_keys=[receiver_id], back_populates="alliances_received")

class Message(Base):
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("players.id"))
    receiver_id = Column(Integer, ForeignKey("players.id"))
    content = Column(Text)
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    sender = relationship("Player", foreign_keys=[sender_id], back_populates="messages_sent")
    receiver = relationship("Player", foreign_keys=[receiver_id], back_populates="messages_received")

class GameEvent(Base):
    __tablename__ = "game_events"
    
    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String)
    description = Column(Text)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

# Create tables
Base.metadata.create_all(bind=engine)

# Initialize special items
def init_special_items():
    db = SessionLocal()
    try:
        if db.query(SpecialItem).count() == 0:
            items = [
                SpecialItem(name="Nuclear Warhead", description="Unlocks the devastating nuke command", effect="nuke_unlock", rarity="legendary"),
                SpecialItem(name="War Drum", description="Boosts attack power by 50%", effect="attack_boost", rarity="rare"),
                SpecialItem(name="Gold Crown", description="Increases happiness generation by 25%", effect="happiness_boost", rarity="rare"),
                SpecialItem(name="Territory Map", description="Increases land captured in battles by 100%", effect="territory_boost", rarity="rare"),
                SpecialItem(name="Lucky Charm", description="Improves gambling and treasure hunting odds", effect="luck_boost", rarity="common"),
                SpecialItem(name="Ancient Scroll", description="Boosts technology research speed", effect="tech_boost", rarity="rare"),
            ]
            for item in items:
                db.add(item)
            db.commit()
    finally:
        db.close()

init_special_items()

# Bot setup
class WarBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='.')
        
    async def on_ready(self):
        print(f'🏛️ WarBot is online! Logged in as {self.user}')
        print(f'🌍 Ready to manage civilizations!')
    
    async def setup_hook(self):
        """Setup hook called when bot starts"""
        # Start random disaster system
        self.loop.create_task(random_disaster_system())

bot = WarBot()

# Utility functions
def get_db():
    db = SessionLocal()
    try:
        return db
    finally:
        pass

def get_player(db: Session, user_id: str) -> Optional[Player]:
    return db.query(Player).filter(Player.user_id == user_id).first()

def create_player(db: Session, user_id: str, username: str, civ_name: str) -> Player:
    player = Player(user_id=user_id, username=username, civ_name=civ_name)
    db.add(player)
    db.commit()
    db.refresh(player)
    return player

def check_cooldown(db: Session, player_id: int, command: str) -> bool:
    cooldown = db.query(Cooldown).filter(
        Cooldown.player_id == player_id,
        Cooldown.command == command,
        Cooldown.expires_at > datetime.utcnow()
    ).first()
    return cooldown is None

def set_cooldown(db: Session, player_id: int, command: str, minutes: int):
    # Remove existing cooldown
    db.query(Cooldown).filter(
        Cooldown.player_id == player_id,
        Cooldown.command == command
    ).delete()
    
    # Add new cooldown
    cooldown = Cooldown(
        player_id=player_id,
        command=command,
        expires_at=datetime.utcnow() + timedelta(minutes=minutes)
    )
    db.add(cooldown)
    db.commit()

def get_territory_multiplier(territory: float) -> float:
    """Calculate resource production multiplier based on territory size"""
    return 1.0 + (territory / 100.0)

def has_item(db: Session, player_id: int, item_name: str) -> bool:
    return db.query(PlayerItem).join(SpecialItem).filter(
        PlayerItem.player_id == player_id,
        SpecialItem.name == item_name
    ).first() is not None

def add_event(db: Session, event_type: str, description: str, player_id: Optional[int] = None):
    event = GameEvent(event_type=event_type, description=description, player_id=player_id)
    db.add(event)
    db.commit()

# Command decorators
def require_player(func):
    async def wrapper(ctx, *args, **kwargs):
        db = get_db()
        try:
            player = get_player(db, str(ctx.author.id))
            if not player:
                await ctx.send("🏛️ **You haven't started your civilization yet!** Use `.start <civilization_name>` to begin your empire!")
                return
            player.last_active = datetime.utcnow()
            db.commit()
            return await func(ctx, player, db, *args, **kwargs)
        finally:
            db.close()
    return wrapper

def require_cooldown(command_name: str, minutes: int):
    def decorator(func):
        async def wrapper(ctx, player, db, *args, **kwargs):
            if not check_cooldown(db, player.id, command_name):
                cooldown = db.query(Cooldown).filter(
                    Cooldown.player_id == player.id,
                    Cooldown.command == command_name
                ).first()
                remaining = cooldown.expires_at - datetime.utcnow()
                await ctx.send(f"⏰ **Cooldown active!** You can use this command again in {remaining.seconds // 60} minutes and {remaining.seconds % 60} seconds.")
                return
            
            result = await func(ctx, player, db, *args, **kwargs)
            set_cooldown(db, player.id, command_name, minutes)
            return result
        return wrapper
    return decorator

# Bot Commands

@bot.command(name='start')
async def start_civilization(ctx, *, civ_name: str):
    """Start your civilization empire"""
    db = get_db()
    try:
        existing_player = get_player(db, str(ctx.author.id))
        if existing_player:
            await ctx.send(f"🏛️ **You already rule the mighty civilization of {existing_player.civ_name}!** Use `.status` to check your empire.")
            return
        
        if len(civ_name) > 50:
            await ctx.send("🚫 **Civilization name too long!** Keep it under 50 characters.")
            return
        
        player = create_player(db, str(ctx.author.id), str(ctx.author), civ_name)
        add_event(db, "civilization_founded", f"{civ_name} was founded by {ctx.author}", int(player.id))
        
        await ctx.send(f"""🏛️ **Welcome, mighty ruler!** 

🌟 **The civilization of {civ_name} has been founded!** 🌟

📊 **Your starting empire:**
💰 Gold: 100 | 🪵 Wood: 50 | 🪨 Stone: 50 | 🍞 Food: 100
👥 Citizens: 10 | 😊 Happiness: 50 | 🍽️ Hunger: 30
⚔️ Soldiers: 5 | 🕵️ Spies: 2 | 🔬 Tech Level: 1
🗺️ Territory: 10.0 km²

🏠 **Buildings:** 1 House, 1 Farm

📜 **Use `.help` to see all available commands and start building your empire!**
🎮 **Pro tip:** Start with `.gather` to collect resources and `.build` to expand your civilization!

*May your reign be long and prosperous!* 👑""")
    finally:
        db.close()

@bot.command(name='status')
@require_player
async def show_status(ctx, player, db):
    """Display your civilization status"""
    # Calculate territory multiplier
    territory_mult = get_territory_multiplier(player.territory)
    
    # Count items
    items = db.query(PlayerItem).join(SpecialItem).filter(PlayerItem.player_id == player.id).all()
    item_list = [f"{item.item.name} x{item.quantity}" for item in items] if items else ["None"]
    
    status_embed = f"""🏛️ **Civilization of {player.civ_name}** 👑

📊 **Resources** (Territory Bonus: +{(territory_mult-1)*100:.0f}%):
💰 Gold: {player.gold:,} | 🪵 Wood: {player.wood:,} | 🪨 Stone: {player.stone:,} | 🍞 Food: {player.food:,}

👥 **Population:**
👨‍👩‍👧‍👦 Citizens: {player.citizens:,} | 😊 Happiness: {player.happiness}/100 | 🍽️ Hunger: {player.hunger}/100

⚔️ **Military:**
🛡️ Soldiers: {player.soldiers:,} | 🕵️ Spies: {player.spies:,} | 🔬 Tech Level: {player.tech_level}

🗺️ **Territory:** {player.territory:.1f} km² 

🏗️ **Buildings:**
🏠 Houses: {player.houses} | 🌾 Farms: {player.farms} | 🏛️ Barracks: {player.barracks}
🧱 Walls: {player.walls} | 🏪 Markets: {player.markets}

🎒 **Special Items:** {', '.join(item_list[:3])}{'...' if len(item_list) > 3 else ''}

⏰ **Last Active:** {player.last_active.strftime('%Y-%m-%d %H:%M UTC')}"""

    await ctx.send(status_embed)

@bot.command(name='gather')
@require_player
@require_cooldown('gather', 15)
async def gather_resources(ctx, player, db):
    """Gather random resources from your territory"""
    territory_mult = get_territory_multiplier(player.territory)
    
    # Base resource gains
    gold_gain = random.randint(10, 30)
    wood_gain = random.randint(15, 25)
    stone_gain = random.randint(10, 20)
    food_gain = random.randint(5, 15)
    
    # Apply territory multiplier
    gold_gain = int(gold_gain * territory_mult)
    wood_gain = int(wood_gain * territory_mult)
    stone_gain = int(stone_gain * territory_mult)
    food_gain = int(food_gain * territory_mult)
    
    # Lucky charm bonus
    if has_item(db, player.id, "Lucky Charm"):
        if random.random() < 0.3:  # 30% chance for bonus
            gold_gain *= 2
            wood_gain *= 2
            stone_gain *= 2
            food_gain *= 2
            bonus_msg = "\n🍀 **Lucky Charm activated!** Double resources!"
        else:
            bonus_msg = ""
    else:
        bonus_msg = ""
    
    player.gold += gold_gain
    player.wood += wood_gain
    player.stone += stone_gain
    player.food += food_gain
    
    db.commit()
    
    outcomes = [
        "Your citizens work tirelessly in the fields and quarries!",
        "A successful expedition returns with valuable resources!",
        "Your territory's natural wealth provides bountiful materials!",
        "Hardworking villagers bring back a good harvest!",
        "Your scouts discover rich deposits in unexplored areas!"
    ]
    
    await ctx.send(f"""🌾 **{random.choice(outcomes)}**

📈 **Resources Gathered:**
💰 +{gold_gain} Gold | 🪵 +{wood_gain} Wood | 🪨 +{stone_gain} Stone | 🍞 +{food_gain} Food
🗺️ Territory Bonus: +{(territory_mult-1)*100:.0f}%{bonus_msg}

💼 **New Totals:**
💰 {player.gold:,} | 🪵 {player.wood:,} | 🪨 {player.stone:,} | 🍞 {player.food:,}""")

@bot.command(name='build')
@require_player
@require_cooldown('build', 10)
async def build_structure(ctx, player, db, building_type: str):
    """Build structures to improve your civilization"""
    building_type = building_type.lower()
    
    # Building costs and effects
    buildings = {
        'house': {'gold': 50, 'wood': 30, 'stone': 20, 'effect': 'citizens', 'amount': 5, 'desc': 'Increases population capacity'},
        'farm': {'gold': 40, 'wood': 25, 'stone': 15, 'effect': 'food_production', 'amount': 10, 'desc': 'Improves food production'},
        'barracks': {'gold': 100, 'wood': 50, 'stone': 80, 'effect': 'soldiers', 'amount': 3, 'desc': 'Trains military units'},
        'wall': {'gold': 80, 'wood': 60, 'stone': 100, 'effect': 'defense', 'amount': 20, 'desc': 'Improves defensive capabilities'},
        'market': {'gold': 120, 'wood': 40, 'stone': 60, 'effect': 'gold_production', 'amount': 15, 'desc': 'Increases trade income'}
    }
    
    if building_type not in buildings:
        await ctx.send(f"🏗️ **Invalid building type!** Available: {', '.join(buildings.keys())}")
        return
    
    building = buildings[building_type]
    
    # Check territory limits
    total_buildings = player.houses + player.farms + player.barracks + player.walls + player.markets
    max_buildings = int(player.territory / 2)  # 1 building per 2 km²
    
    if total_buildings >= max_buildings:
        await ctx.send(f"🚫 **Not enough territory!** You can only have {max_buildings} buildings with {player.territory:.1f} km² of land. Expand your territory through conquest!")
        return
    
    # Check resources
    if (player.gold < building['gold'] or 
        player.wood < building['wood'] or 
        player.stone < building['stone']):
        await ctx.send(f"""💸 **Insufficient resources to build {building_type}!**

💰 Required: {building['gold']} gold (you have {player.gold})
🪵 Required: {building['wood']} wood (you have {player.wood})  
🪨 Required: {building['stone']} stone (you have {player.stone})

💡 Use `.gather` to collect more resources!""")
        return
    
    # Deduct resources
    player.gold -= building['gold']
    player.wood -= building['wood']
    player.stone -= building['stone']
    
    # Add building and effects
    if building_type == 'house':
        player.houses += 1
        player.citizens += building['amount']
    elif building_type == 'farm':
        player.farms += 1
        player.food += building['amount']
    elif building_type == 'barracks':
        player.barracks += 1
        player.soldiers += building['amount']
    elif building_type == 'wall':
        player.walls += 1
        # Walls improve defense (used in combat calculations)
    elif building_type == 'market':
        player.markets += 1
        player.gold += building['amount']
    
    db.commit()
    add_event(db, "building_constructed", f"{player.civ_name} built a {building_type}", player.id)
    
    await ctx.send(f"""🏗️ **Construction Complete!** 

🏛️ **A magnificent {building_type} has been built in {player.civ_name}!**
✨ {building['desc']}

📊 **Construction Costs:**
💰 -{building['gold']} Gold | 🪵 -{building['wood']} Wood | 🪨 -{building['stone']} Stone

📈 **Benefits Gained:**
{f"👥 +{building['amount']} Citizens" if building_type == 'house' else ""}
{f"🍞 +{building['amount']} Food" if building_type == 'farm' else ""}
{f"⚔️ +{building['amount']} Soldiers" if building_type == 'barracks' else ""}
{f"🛡️ +{building['amount']} Defense" if building_type == 'wall' else ""}
{f"💰 +{building['amount']} Gold Bonus" if building_type == 'market' else ""}

🏗️ **Total Buildings:** {total_buildings + 1}/{max_buildings} (Territory: {player.territory:.1f} km²)""")

@bot.command(name='farm')
@require_player
@require_cooldown('farm', 20)
async def farm_food(ctx, player, db):
    """Produce extra food from your farms"""
    base_food = 20 + (player.farms * 10)
    territory_mult = get_territory_multiplier(player.territory)
    food_gain = int(base_food * territory_mult)
    
    player.food += food_gain
    player.hunger = max(0, player.hunger - 5)  # Farming reduces hunger
    
    db.commit()
    
    await ctx.send(f"""🌾 **Bountiful Harvest!**

🚜 Your {player.farms} farms work overtime, producing abundant crops!
🍞 **+{food_gain} Food** (Base: {base_food}, Territory Bonus: +{(territory_mult-1)*100:.0f}%)
🍽️ **Hunger reduced by 5** (now {player.hunger}/100)

📦 **Total Food:** {player.food:,}""")

@bot.command(name='cheer')
@require_player
@require_cooldown('cheer', 30)
async def boost_happiness(ctx, player, db):
    """Boost your civilization's happiness"""
    happiness_gain = random.randint(10, 20)
    
    # Gold Crown bonus
    if has_item(db, player.id, "Gold Crown"):
        happiness_gain = int(happiness_gain * 1.25)
        crown_msg = "\n👑 **Gold Crown Effect:** +25% happiness boost!"
    else:
        crown_msg = ""
    
    player.happiness = min(100, player.happiness + happiness_gain)
    
    db.commit()
    
    celebrations = [
        "🎉 A grand festival fills the streets with joy!",
        "🎭 Royal entertainers perform for delighted crowds!",
        "🎪 A magnificent carnival brings smiles to all!",
        "🎵 Musicians play uplifting melodies throughout the land!",
        "🌸 Beautiful gardens bloom, inspiring hope and wonder!"
    ]
    
    await ctx.send(f"""{random.choice(celebrations)}

😊 **+{happiness_gain} Happiness** (now {player.happiness}/100){crown_msg}
✨ Your citizens feel more content and motivated!""")

@bot.command(name='feed')
@require_player  
@require_cooldown('feed', 25)
async def feed_population(ctx, player, db):
    """Feed your population to reduce hunger"""
    if player.food < 30:
        await ctx.send("🍞 **Not enough food!** You need at least 30 food to feed your population.")
        return
    
    food_cost = 30
    hunger_reduction = random.randint(15, 25)
    
    player.food -= food_cost
    player.hunger = max(0, player.hunger - hunger_reduction)
    player.happiness = min(100, player.happiness + 5)  # Well-fed citizens are happier
    
    db.commit()
    
    await ctx.send(f"""🍽️ **Community Feast!**

🍞 Your wise leadership ensures everyone is well-fed!
📉 **-{hunger_reduction} Hunger** (now {player.hunger}/100)
😊 **+5 Happiness** (now {player.happiness}/100)
💰 **Food consumed:** {food_cost} (remaining: {player.food:,})

🎉 Your citizens are grateful for your generous care!""")

@bot.command(name='gamble')
@require_player
@require_cooldown('gamble', 60)
async def gamble_gold(ctx, player, db, amount: int):
    """Risk gold for potentially huge gains"""
    if amount < 10:
        await ctx.send("🎰 **Minimum bet is 10 gold!**")
        return
    
    if player.gold < amount:
        await ctx.send(f"💸 **You only have {player.gold} gold!** Can't bet {amount}.")
        return
    
    # Lucky charm improves odds
    base_win_chance = 0.4
    if has_item(db, player.id, "Lucky Charm"):
        win_chance = 0.55
        luck_msg = "\n🍀 **Lucky Charm:** Improved odds!"
    else:
        win_chance = base_win_chance
        luck_msg = ""
    
    player.gold -= amount
    
    if random.random() < win_chance:
        # Win! 1.5x to 3x multiplier
        multiplier = random.uniform(1.5, 3.0)
        winnings = int(amount * multiplier)
        player.gold += winnings
        
        db.commit()
        
        await ctx.send(f"""🎰 **JACKPOT!** 🎉

💰 **You win {winnings} gold!** (Multiplier: {multiplier:.1f}x)
🎯 Bet: {amount} → Won: {winnings} (Profit: +{winnings-amount})
💼 **New Balance:** {player.gold:,} gold{luck_msg}

🍀 Fortune favors the bold!""")
    else:
        db.commit()
        
        await ctx.send(f"""🎰 **Bad Luck!** 💸

💸 **You lost {amount} gold!**
💼 **Remaining Gold:** {player.gold:,}{luck_msg}

🎲 Better luck next time! The house always has an edge...""")

@bot.command(name='attack')
@require_player
@require_cooldown('attack', 45)
async def attack_civilization(ctx, player, db, target_user: str):
    """Attack another civilization to steal resources and capture territory"""
    # Find target player
    target_user = target_user.replace('<@', '').replace('>', '').replace('!', '')
    target = db.query(Player).filter(Player.user_id == target_user).first()
    
    if not target:
        await ctx.send("🚫 **Target civilization not found!** They must start their empire first.")
        return
    
    if target.id == player.id:
        await ctx.send("🤔 **You cannot attack yourself!** Focus your aggression elsewhere.")
        return
    
    if player.soldiers < 1:
        await ctx.send("⚔️ **No soldiers available!** Build barracks to train an army.")
        return
    
    # Check alliance
    alliance = db.query(Alliance).filter(
        ((Alliance.sender_id == player.id) & (Alliance.receiver_id == target.id)) |
        ((Alliance.sender_id == target.id) & (Alliance.receiver_id == player.id)),
        Alliance.status == 'accepted'
    ).first()
    
    if alliance:
        await ctx.send("🤝 **Cannot attack an ally!** Break the alliance first.")
        return
    
    # Calculate combat power
    attacker_power = player.soldiers * player.tech_level
    defender_power = target.soldiers * target.tech_level + (target.walls * 10)
    
    # War Drum bonus
    if has_item(db, player.id, "War Drum"):
        attacker_power = int(attacker_power * 1.5)
        war_drum_msg = "\n🥁 **War Drum Effect:** +50% attack power!"
    else:
        war_drum_msg = ""
    
    # Add randomness
    attacker_roll = random.randint(80, 120) / 100
    defender_roll = random.randint(80, 120) / 100
    
    final_attacker = attacker_power * attacker_roll
    final_defender = defender_power * defender_roll
    
    # Determine outcome
    if final_attacker > final_defender:
        # Victory!
        victory_margin = final_attacker / final_defender
        
        # Resource stealing (10-30% of target's resources)
        steal_percentage = min(0.3, 0.1 + (victory_margin - 1) * 0.1)
        
        gold_stolen = int(target.gold * steal_percentage)
        wood_stolen = int(target.wood * steal_percentage)
        stone_stolen = int(target.stone * steal_percentage)
        food_stolen = int(target.food * steal_percentage)
        
        # Territory capture
        territory_captured = min(target.territory * 0.2, 5.0)  # Max 20% or 5 km²
        if has_item(db, player.id, "Territory Map"):
            territory_captured *= 2
            territory_msg = "\n🗺️ **Territory Map:** Double land captured!"
        else:
            territory_msg = ""
        
        # Casualties
        attacker_losses = random.randint(1, max(2, player.soldiers // 10))
        defender_losses = random.randint(2, max(3, target.soldiers // 5))
        
        # Apply changes
        player.gold += gold_stolen
        player.wood += wood_stolen
        player.stone += stone_stolen
        player.food += food_stolen
        player.territory += territory_captured
        player.soldiers = max(0, player.soldiers - attacker_losses)
        
        target.gold = max(0, target.gold - gold_stolen)
        target.wood = max(0, target.wood - wood_stolen)
        target.stone = max(0, target.stone - stone_stolen)
        target.food = max(0, target.food - food_stolen)
        target.territory = max(1.0, target.territory - territory_captured)
        target.soldiers = max(0, target.soldiers - defender_losses)
        target.happiness = max(0, target.happiness - 20)
        
        db.commit()
        add_event(db, "battle_victory", f"{player.civ_name} conquered territory from {target.civ_name}", player.id)
        
        await ctx.send(f"""⚔️ **GLORIOUS VICTORY!** 🏆

🎯 **{player.civ_name} crushes {target.civ_name}!**
💪 Attack Power: {final_attacker:.1f} vs Defense: {final_defender:.1f}{war_drum_msg}

💰 **Spoils of War:**
💰 +{gold_stolen:,} Gold | 🪵 +{wood_stolen:,} Wood | 🪨 +{stone_stolen:,} Stone | 🍞 +{food_stolen:,} Food
🗺️ **Territory Captured:** +{territory_captured:.1f} km² (now {player.territory:.1f} km²){territory_msg}

⚰️ **Casualties:**
💀 Your losses: {attacker_losses} soldiers (remaining: {player.soldiers})
💀 Enemy losses: {defender_losses} soldiers

👑 **Your empire grows stronger through conquest!**""")
        
    else:
        # Defeat!
        defeat_margin = final_defender / final_attacker
        
        # Losses for failed attack
        attacker_losses = random.randint(2, max(3, player.soldiers // 5))
        gold_lost = min(player.gold, random.randint(20, 100))
        
        player.soldiers = max(0, player.soldiers - attacker_losses)
        player.gold = max(0, player.gold - gold_lost)
        player.happiness = max(0, player.happiness - 15)
        
        db.commit()
        add_event(db, "battle_defeat", f"{player.civ_name} was repelled by {target.civ_name}", player.id)
        
        await ctx.send(f"""⚔️ **CRUSHING DEFEAT!** 💥

😤 **{target.civ_name} successfully defends against {player.civ_name}!**
💪 Attack Power: {final_attacker:.1f} vs Defense: {final_defender:.1f}{war_drum_msg}

💸 **Losses:**
💀 Soldiers lost: {attacker_losses} (remaining: {player.soldiers})
💰 Gold lost in retreat: {gold_lost} (remaining: {player.gold:,})
😞 Happiness decreased by 15 (now {player.happiness}/100)

🛡️ **Your forces retreat in shame. Plan better next time!**""")

@bot.command(name='stealthbattle')
@require_player
@require_cooldown('stealthbattle', 90)
async def stealth_attack(ctx, player, db, target_user: str):
    """Launch a surprise attack with higher risk and reward"""
    # Find target player
    target_user = target_user.replace('<@', '').replace('>', '').replace('!', '')
    target = db.query(Player).filter(Player.user_id == target_user).first()
    
    if not target:
        await ctx.send("🚫 **Target civilization not found!** They must start their empire first.")
        return
    
    if target.id == player.id:
        await ctx.send("🤔 **You cannot attack yourself!**")
        return
    
    if player.spies < 2:
        await ctx.send("🕵️ **Insufficient spies!** You need at least 2 spies for a stealth operation.")
        return
    
    # Check alliance
    alliance = db.query(Alliance).filter(
        ((Alliance.sender_id == player.id) & (Alliance.receiver_id == target.id)) |
        ((Alliance.sender_id == target.id) & (Alliance.receiver_id == player.id)),
        Alliance.status == 'accepted'
    ).first()
    
    if alliance:
        await ctx.send("🤝 **Cannot attack an ally!** Break the alliance first.")
        return
    
    # Stealth has higher risk but higher reward
    success_chance = 0.6 + (player.spies * 0.05) - (target.spies * 0.03)
    success_chance = max(0.2, min(0.8, success_chance))
    
    if random.random() < success_chance:
        # Successful stealth attack - much higher rewards
        gold_stolen = int(target.gold * random.uniform(0.3, 0.5))
        wood_stolen = int(target.wood * random.uniform(0.2, 0.4))
        stone_stolen = int(target.stone * random.uniform(0.2, 0.4))
        food_stolen = int(target.food * random.uniform(0.2, 0.4))
        territory_captured = min(target.territory * 0.3, 8.0)
        
        # Minimal losses due to surprise
        spy_losses = random.randint(0, 1)
        soldier_losses = random.randint(0, 2)
        
        # Apply changes
        player.gold += gold_stolen
        player.wood += wood_stolen
        player.stone += stone_stolen
        player.food += food_stolen
        player.territory += territory_captured
        player.spies = max(0, player.spies - spy_losses)
        player.soldiers = max(0, player.soldiers - soldier_losses)
        
        target.gold = max(0, target.gold - gold_stolen)
        target.wood = max(0, target.wood - wood_stolen)
        target.stone = max(0, target.stone - stone_stolen)
        target.food = max(0, target.food - food_stolen)
        target.territory = max(1.0, target.territory - territory_captured)
        target.happiness = max(0, target.happiness - 30)
        
        db.commit()
        add_event(db, "stealth_victory", f"{player.civ_name} successfully executed a stealth attack on {target.civ_name}", player.id)
        
        await ctx.send(f"""🌙 **PERFECT STEALTH STRIKE!** 🗡️

🥷 **{player.civ_name} strikes {target.civ_name} in the dead of night!**
✨ **Success Rate:** {success_chance*100:.1f}%

💰 **Massive Spoils:**
💰 +{gold_stolen:,} Gold | 🪵 +{wood_stolen:,} Wood | 🪨 +{stone_stolen:,} Stone | 🍞 +{food_stolen:,} Food
🗺️ **Territory Captured:** +{territory_captured:.1f} km² (now {player.territory:.1f} km²)

⚰️ **Minimal Losses:**
🕵️ Spies lost: {spy_losses} | ⚔️ Soldiers lost: {soldier_losses}

🌟 **Your stealth mastery brings great rewards!**""")
        
    else:
        # Failed stealth attack - severe penalties
        spy_losses = random.randint(1, max(2, player.spies // 2))
        soldier_losses = random.randint(2, max(3, player.soldiers // 3))
        gold_lost = min(player.gold, random.randint(50, 200))
        
        player.spies = max(0, player.spies - spy_losses)
        player.soldiers = max(0, player.soldiers - soldier_losses)
        player.gold = max(0, player.gold - gold_lost)
        player.happiness = max(0, player.happiness - 25)
        
        db.commit()
        add_event(db, "stealth_failure", f"{player.civ_name}'s stealth attack on {target.civ_name} was discovered", player.id)
        
        await ctx.send(f"""🌙 **STEALTH OPERATION EXPOSED!** 🚨

😱 **{target.civ_name} detects {player.civ_name}'s infiltration!**
💥 **Detection Rate:** {(1-success_chance)*100:.1f}%

💸 **Severe Losses:**
🕵️ Spies captured: {spy_losses} (remaining: {player.spies})
⚔️ Soldiers lost: {soldier_losses} (remaining: {player.soldiers})
💰 Gold lost: {gold_lost} (remaining: {player.gold:,})
😞 Happiness decreased by 25 (now {player.happiness}/100)

💀 **Your stealth forces are decimated! Plan more carefully next time!**""")

@bot.command(name='nuke')
@require_player
@require_cooldown('nuke', 1440)  # 24 hour cooldown
async def nuclear_strike(ctx, player, db, target_user: str):
    """Launch a devastating nuclear attack (requires Nuclear Warhead)"""
    if not has_item(db, player.id, "Nuclear Warhead"):
        await ctx.send("☢️ **Nuclear Warhead Required!** You need the legendary Nuclear Warhead item to use this command.")
        return
    
    # Find target player
    target_user = target_user.replace('<@', '').replace('>', '').replace('!', '')
    target = db.query(Player).filter(Player.user_id == target_user).first()
    
    if not target:
        await ctx.send("🚫 **Target civilization not found!**")
        return
    
    if target.id == player.id:
        await ctx.send("☢️ **You cannot nuke yourself!** That would be civilization suicide!")
        return
    
    # Check alliance
    alliance = db.query(Alliance).filter(
        ((Alliance.sender_id == player.id) & (Alliance.receiver_id == target.id)) |
        ((Alliance.sender_id == target.id) & (Alliance.receiver_id == player.id)),
        Alliance.status == 'accepted'
    ).first()
    
    if alliance:
        await ctx.send("🤝 **Cannot nuke an ally!** Break the alliance first, you monster!")
        return
    
    # Devastating effects
    gold_destroyed = int(target.gold * 0.7)
    wood_destroyed = int(target.wood * 0.6)
    stone_destroyed = int(target.stone * 0.5)
    food_destroyed = int(target.food * 0.8)
    territory_destroyed = target.territory * 0.4
    citizens_lost = int(target.citizens * 0.6)
    soldiers_lost = int(target.soldiers * 0.8)
    buildings_destroyed = random.randint(1, 3)
    
    # Apply destruction
    target.gold = max(0, target.gold - gold_destroyed)
    target.wood = max(0, target.wood - wood_destroyed)
    target.stone = max(0, target.stone - stone_destroyed)
    target.food = max(0, target.food - food_destroyed)
    target.territory = max(1.0, target.territory - territory_destroyed)
    target.citizens = max(1, target.citizens - citizens_lost)
    target.soldiers = max(0, target.soldiers - soldiers_lost)
    target.happiness = 0  # Complete devastation
    target.hunger = min(100, target.hunger + 50)
    
    # Destroy random buildings
    buildings = ['houses', 'farms', 'barracks', 'walls', 'markets']
    for _ in range(buildings_destroyed):
        building = random.choice(buildings)
        current = getattr(target, building)
        if current > 0:
            setattr(target, building, max(0, current - 1))
    
    # Consume the nuclear warhead
    warhead = db.query(PlayerItem).join(SpecialItem).filter(
        PlayerItem.player_id == player.id,
        SpecialItem.name == "Nuclear Warhead"
    ).first()
    if warhead.quantity > 1:
        warhead.quantity -= 1
    else:
        db.delete(warhead)
    
    db.commit()
    add_event(db, "nuclear_strike", f"{player.civ_name} launched a nuclear strike against {target.civ_name}", player.id)
    
    await ctx.send(f"""☢️ **NUCLEAR APOCALYPSE!** ☢️

🚀 **{player.civ_name} launches a nuclear warhead at {target.civ_name}!**
💥 **MUSHROOM CLOUD RISES AS CIVILIZATION BURNS!**

🔥 **CATASTROPHIC DESTRUCTION:**
💰 Gold destroyed: {gold_destroyed:,} | 🪵 Wood destroyed: {wood_destroyed:,}
🪨 Stone destroyed: {stone_destroyed:,} | 🍞 Food destroyed: {food_destroyed:,}
🗺️ Territory irradiated: {territory_destroyed:.1f} km²
👥 Citizens vaporized: {citizens_lost:,} | ⚔️ Soldiers killed: {soldiers_lost:,}
🏗️ Buildings destroyed: {buildings_destroyed}

💀 **{target.civ_name} is left in radioactive ruins!**
☢️ Happiness obliterated, hunger ravages survivors
⚡ **Nuclear Warhead consumed**

🌍 **The world trembles at this display of ultimate power...**""")

@bot.command(name='siege')
@require_player
@require_cooldown('siege', 120)
async def siege_attack(ctx, player, db, target_user: str):
    """Launch a prolonged siege to gradually capture territory"""
    # Find target player
    target_user = target_user.replace('<@', '').replace('>', '').replace('!', '')
    target = db.query(Player).filter(Player.user_id == target_user).first()
    
    if not target:
        await ctx.send("🚫 **Target civilization not found!**")
        return
    
    if target.id == player.id:
        await ctx.send("🤔 **You cannot siege yourself!**")
        return
    
    if player.soldiers < 5:
        await ctx.send("⚔️ **Need at least 5 soldiers for a siege!**")
        return
    
    # Check alliance
    alliance = db.query(Alliance).filter(
        ((Alliance.sender_id == player.id) & (Alliance.receiver_id == target.id)) |
        ((Alliance.sender_id == target.id) & (Alliance.receiver_id == player.id)),
        Alliance.status == 'accepted'
    ).first()
    
    if alliance:
        await ctx.send("🤝 **Cannot siege an ally!**")
        return
    
    # Siege effectiveness based on soldiers and walls
    siege_power = player.soldiers - (target.walls * 2)
    siege_power = max(1, siege_power)
    
    # Determine siege outcome
    if random.randint(1, 100) <= min(80, siege_power * 5):
        # Successful siege
        territory_captured = min(target.territory * 0.15, 3.0)
        resources_captured = random.randint(10, 30)
        
        # Siege costs
        soldier_losses = random.randint(1, 3)
        food_cost = 20
        
        # Apply changes
        player.territory += territory_captured
        player.gold += resources_captured
        player.wood += resources_captured
        player.soldiers = max(0, player.soldiers - soldier_losses)
        player.food = max(0, player.food - food_cost)
        
        target.territory = max(1.0, target.territory - territory_captured)
        target.happiness = max(0, target.happiness - 15)
        target.food = max(0, target.food - 10)
        
        db.commit()
        add_event(db, "siege_success", f"{player.civ_name} successfully besieged {target.civ_name}", player.id)
        
        await ctx.send(f"""🏰 **SIEGE SUCCESSFUL!** ⚔️

🛡️ **{player.civ_name} breaks through {target.civ_name}'s defenses!**
💪 Siege Power: {siege_power}

🎯 **Siege Results:**
🗺️ Territory captured: {territory_captured:.1f} km² (now {player.territory:.1f} km²)
💰 Resources plundered: +{resources_captured} gold and wood
⚰️ Soldiers lost in siege: {soldier_losses} (remaining: {player.soldiers})
🍞 Food consumed: {food_cost} (remaining: {player.food:,})

🏰 **The enemy walls crumble before your persistent assault!**""")
        
    else:
        # Failed siege
        soldier_losses = random.randint(2, 4)
        food_cost = 25
        gold_lost = random.randint(10, 50)
        
        player.soldiers = max(0, player.soldiers - soldier_losses)
        player.food = max(0, player.food - food_cost)
        player.gold = max(0, player.gold - gold_lost)
        
        db.commit()
        add_event(db, "siege_failure", f"{player.civ_name}'s siege of {target.civ_name} was repelled", player.id)
        
        await ctx.send(f"""🏰 **SIEGE REPELLED!** 💥

🛡️ **{target.civ_name} successfully defends against the siege!**
💪 Siege Power: {siege_power}

💸 **Siege Losses:**
⚰️ Soldiers lost: {soldier_losses} (remaining: {player.soldiers})
🍞 Food consumed: {food_cost} (remaining: {player.food:,})
💰 Gold lost in retreat: {gold_lost} (remaining: {player.gold:,})

🏰 **The enemy defenses hold strong! Regroup and try again!**""")

@bot.command(name='spy')
@require_player
@require_cooldown('spy', 30)
async def spy_mission(ctx, player, db, target_user: str):
    """Gather intelligence on another civilization"""
    # Find target player
    target_user = target_user.replace('<@', '').replace('>', '').replace('!', '')
    target = db.query(Player).filter(Player.user_id == target_user).first()
    
    if not target:
        await ctx.send("🚫 **Target civilization not found!**")
        return
    
    if target.id == player.id:
        await ctx.send("🤔 **You cannot spy on yourself!**")
        return
    
    if player.spies < 1:
        await ctx.send("🕵️ **No spies available!** Train some spies first.")
        return
    
    # Spy success chance
    success_chance = 0.7 + (player.spies * 0.05) - (target.spies * 0.03)
    success_chance = max(0.3, min(0.9, success_chance))
    
    if random.random() < success_chance:
        # Successful espionage
        # Count target's items
        items = db.query(PlayerItem).join(SpecialItem).filter(PlayerItem.player_id == target.id).all()
        item_list = [f"{item.item.name} x{item.quantity}" for item in items] if items else ["None"]
        
        # Get alliances
        alliances = db.query(Alliance).filter(
            ((Alliance.sender_id == target.id) | (Alliance.receiver_id == target.id)),
            Alliance.status == 'accepted'
        ).all()
        ally_count = len(alliances)
        
        intel_report = f"""🕵️ **INTELLIGENCE REPORT** 📋

🎯 **Target:** {target.civ_name}
✅ **Mission Success Rate:** {success_chance*100:.1f}%

💰 **Resources:**
Gold: {target.gold:,} | Wood: {target.wood:,} | Stone: {target.stone:,} | Food: {target.food:,}

👥 **Population:**
Citizens: {target.citizens:,} | Happiness: {target.happiness}/100 | Hunger: {target.hunger}/100

⚔️ **Military:**
Soldiers: {target.soldiers:,} | Spies: {target.spies:,} | Tech Level: {target.tech_level}

🗺️ **Territory:** {target.territory:.1f} km²

🏗️ **Buildings:**
Houses: {target.houses} | Farms: {target.farms} | Barracks: {target.barracks}
Walls: {target.walls} | Markets: {target.markets}

🎒 **Special Items:** {', '.join(item_list[:3])}{'...' if len(item_list) > 3 else ''}
🤝 **Active Alliances:** {ally_count}

📊 **Threat Assessment:** {"HIGH" if target.soldiers > player.soldiers else "MEDIUM" if target.soldiers > player.soldiers // 2 else "LOW"}"""
        
        await ctx.send(intel_report)
        
    else:
        # Failed espionage
        spy_losses = 1 if random.random() < 0.5 else 0
        
        if spy_losses:
            player.spies = max(0, player.spies - spy_losses)
            loss_msg = f"\n🕵️ **1 spy was captured and eliminated!** (Remaining: {player.spies})"
        else:
            loss_msg = "\n🏃 **Your spy escaped undetected!**"
        
        db.commit()
        
        await ctx.send(f"""🕵️ **ESPIONAGE FAILED!** 🚨

🎯 **Target:** {target.civ_name}
❌ **Mission Success Rate:** {success_chance*100:.1f}%

🚫 **Your spy was detected by enemy counterintelligence!**{loss_msg}

🔍 **No intelligence gathered. Try again later!**""")

@bot.command(name='sabotage')
@require_player
@require_cooldown('sabotage', 60)
async def sabotage_mission(ctx, player, db, target_user: str):
    """Sabotage enemy resources and infrastructure"""
    # Find target player
    target_user = target_user.replace('<@', '').replace('>', '').replace('!', '')
    target = db.query(Player).filter(Player.user_id == target_user).first()
    
    if not target:
        await ctx.send("🚫 **Target civilization not found!**")
        return
    
    if target.id == player.id:
        await ctx.send("🤔 **You cannot sabotage yourself!**")
        return
    
    if player.spies < 2:
        await ctx.send("🕵️ **Need at least 2 spies for sabotage missions!**")
        return
    
    # Sabotage success chance
    success_chance = 0.6 + (player.spies * 0.04) - (target.spies * 0.05)
    success_chance = max(0.2, min(0.8, success_chance))
    
    if random.random() < success_chance:
        # Successful sabotage
        gold_damage = int(target.gold * random.uniform(0.1, 0.2))
        wood_damage = int(target.wood * random.uniform(0.15, 0.25))
        stone_damage = int(target.stone * random.uniform(0.1, 0.2))
        food_damage = int(target.food * random.uniform(0.2, 0.3))
        
        # Building damage
        building_damaged = None
        if target.markets > 0 and random.random() < 0.3:
            target.markets -= 1
            building_damaged = "Market"
        elif target.farms > 1 and random.random() < 0.4:  # Keep at least 1 farm
            target.farms -= 1
            building_damaged = "Farm"
        
        # Apply damage
        target.gold = max(0, target.gold - gold_damage)
        target.wood = max(0, target.wood - wood_damage)
        target.stone = max(0, target.stone - stone_damage)
        target.food = max(0, target.food - food_damage)
        target.happiness = max(0, target.happiness - 10)
        
        spy_losses = 1 if random.random() < 0.2 else 0
        player.spies = max(0, player.spies - spy_losses)
        
        db.commit()
        add_event(db, "sabotage_success", f"{player.civ_name} sabotaged {target.civ_name}", player.id)
        
        building_msg = f"\n🏗️ **Building Destroyed:** {building_damaged}" if building_damaged else ""
        spy_msg = f"\n🕵️ **Spy lost during escape:** 1 (remaining: {player.spies})" if spy_losses else ""
        
        await ctx.send(f"""💣 **SABOTAGE SUCCESSFUL!** 🔥

🎯 **Target:** {target.civ_name}
✅ **Mission Success Rate:** {success_chance*100:.1f}%

💥 **Damage Inflicted:**
💰 Gold destroyed: {gold_damage:,} | 🪵 Wood destroyed: {wood_damage:,}
🪨 Stone destroyed: {stone_damage:,} | 🍞 Food spoiled: {food_damage:,}
😞 Happiness reduced by 10{building_msg}{spy_msg}

🌟 **Your saboteurs strike a devastating blow to the enemy!**""")
        
    else:
        # Failed sabotage
        spy_losses = random.randint(1, 2)
        player.spies = max(0, player.spies - spy_losses)
        
        db.commit()
        add_event(db, "sabotage_failure", f"{player.civ_name}'s sabotage attempt on {target.civ_name} failed", player.id)
        
        await ctx.send(f"""💣 **SABOTAGE FAILED!** 🚨

🎯 **Target:** {target.civ_name}
❌ **Mission Success Rate:** {success_chance*100:.1f}%

🚫 **Your saboteurs were caught in the act!**
🕵️ **Spies captured:** {spy_losses} (remaining: {player.spies})

💀 **Mission compromised! Your agents paid the ultimate price!**""")

@bot.command(name='hack')
@require_player
@require_cooldown('hack', 90)
async def cyber_attack(ctx, player, db, target_user: str):
    """Use technology to steal gold from another civilization"""
    # Find target player
    target_user = target_user.replace('<@', '').replace('>', '').replace('!', '')
    target = db.query(Player).filter(Player.user_id == target_user).first()
    
    if not target:
        await ctx.send("🚫 **Target civilization not found!**")
        return
    
    if target.id == player.id:
        await ctx.send("🤔 **You cannot hack yourself!**")
        return
    
    if player.tech_level < 3:
        await ctx.send("💻 **Tech level too low!** You need at least tech level 3 for cyber warfare.")
        return
    
    # Hack success based on tech difference
    tech_advantage = player.tech_level - target.tech_level
    base_success = 0.4 + (tech_advantage * 0.1)
    success_chance = max(0.1, min(0.8, base_success))
    
    if random.random() < success_chance:
        # Successful hack
        gold_stolen = int(target.gold * random.uniform(0.15, 0.3))
        gold_stolen = min(gold_stolen, target.gold)
        
        player.gold += gold_stolen
        target.gold = max(0, target.gold - gold_stolen)
        
        db.commit()
        add_event(db, "cyber_attack", f"{player.civ_name} hacked {target.civ_name}", player.id)
        
        await ctx.send(f"""💻 **CYBER ATTACK SUCCESSFUL!** ⚡

🎯 **Target:** {target.civ_name}
🔬 **Tech Advantage:** {tech_advantage} levels
✅ **Hack Success Rate:** {success_chance*100:.1f}%

💰 **Digital Heist:**
Gold stolen: {gold_stolen:,} (Your balance: {player.gold:,})

🌐 **Your superior technology infiltrates their financial networks!**
⚡ **Credits transferred via encrypted channels!**""")
        
    else:
        # Failed hack - potential backlash
        if random.random() < 0.3:  # 30% chance of backlash
            gold_lost = min(player.gold, random.randint(50, 150))
            player.gold = max(0, player.gold - gold_lost)
            backlash_msg = f"\n💥 **Backlash:** Your systems were compromised! Lost {gold_lost} gold!"
        else:
            backlash_msg = "\n🛡️ **No backlash detected.** Your systems remain secure."
        
        db.commit()
        
        await ctx.send(f"""💻 **CYBER ATTACK FAILED!** 🚨

🎯 **Target:** {target.civ_name}
🔬 **Tech Advantage:** {tech_advantage} levels
❌ **Hack Success Rate:** {success_chance*100:.1f}%

🛡️ **Enemy firewalls repelled your intrusion!**{backlash_msg}

💀 **Their cyber defenses were stronger than anticipated!**""")

@bot.command(name='ally')
@require_player
async def form_alliance(ctx, player, db, target_user: str):
    """Form an alliance with another civilization"""
    # Find target player
    target_user = target_user.replace('<@', '').replace('>', '').replace('!', '')
    target = db.query(Player).filter(Player.user_id == target_user).first()
    
    if not target:
        await ctx.send("🚫 **Target civilization not found!**")
        return
    
    if target.id == player.id:
        await ctx.send("🤔 **You cannot ally with yourself!**")
        return
    
    # Check existing alliance
    existing = db.query(Alliance).filter(
        ((Alliance.sender_id == player.id) & (Alliance.receiver_id == target.id)) |
        ((Alliance.sender_id == target.id) & (Alliance.receiver_id == player.id))
    ).first()
    
    if existing:
        if existing.status == 'accepted':
            await ctx.send("🤝 **Already allied!** You are already allies with this civilization.")
            return
        elif existing.status == 'pending':
            if existing.sender_id == player.id:
                await ctx.send("⏰ **Alliance request pending!** Wait for their response.")
                return
            else:
                # Accept the pending alliance
                existing.status = 'accepted'
                db.commit()
                add_event(db, "alliance_formed", f"{player.civ_name} and {target.civ_name} formed an alliance", player.id)
                
                await ctx.send(f"""🤝 **ALLIANCE FORMED!** 🌟

✅ **{player.civ_name} accepts the alliance proposal from {target.civ_name}!**

🛡️ **Alliance Benefits:**
• Cannot attack each other
• Can share resources
• Mutual protection pacts
• Strategic coordination

🌍 **Two great civilizations unite for mutual prosperity!**""")
                return
    
    # Create new alliance request
    alliance = Alliance(sender_id=player.id, receiver_id=target.id, status='pending')
    db.add(alliance)
    db.commit()
    
    await ctx.send(f"""🤝 **ALLIANCE PROPOSAL SENT!** 📜

📩 **{player.civ_name} proposes an alliance to {target.civ_name}!**

⏰ **Waiting for response...**
💡 **They can accept with:** `.ally <@{ctx.author.id}>`

🌟 **Alliances provide mutual protection and resource sharing opportunities!**""")

@bot.command(name='break')
@require_player
async def break_alliance(ctx, player, db, target_user: str):
    """Break an existing alliance"""
    # Find target player
    target_user = target_user.replace('<@', '').replace('>', '').replace('!', '')
    target = db.query(Player).filter(Player.user_id == target_user).first()
    
    if not target:
        await ctx.send("🚫 **Target civilization not found!**")
        return
    
    # Find alliance
    alliance = db.query(Alliance).filter(
        ((Alliance.sender_id == player.id) & (Alliance.receiver_id == target.id)) |
        ((Alliance.sender_id == target.id) & (Alliance.receiver_id == player.id)),
        Alliance.status == 'accepted'
    ).first()
    
    if not alliance:
        await ctx.send("🚫 **No alliance exists!** You are not allied with this civilization.")
        return
    
    # Break alliance
    db.delete(alliance)
    db.commit()
    add_event(db, "alliance_broken", f"{player.civ_name} broke their alliance with {target.civ_name}", player.id)
    
    await ctx.send(f"""💔 **ALLIANCE BROKEN!** ⚔️

🚫 **{player.civ_name} dissolves their alliance with {target.civ_name}!**

⚠️ **Consequences:**
• Can now attack each other
• Resource sharing disabled
• Mutual protection ended
• Diplomatic relations severed

🌩️ **The bonds of friendship have been shattered by ambition!**""")

@bot.command(name='invent')
@require_player
@require_cooldown('invent', 180)
async def research_technology(ctx, player, db):
    """Research new technology to advance your civilization"""
    research_cost = player.tech_level * 100
    
    if player.gold < research_cost:
        await ctx.send(f"💻 **Insufficient funds for research!** Need {research_cost} gold (you have {player.gold}).")
        return
    
    # Ancient Scroll bonus
    success_bonus = 0.2 if has_item(db, player.id, "Ancient Scroll") else 0
    success_chance = 0.6 + success_bonus
    
    player.gold -= research_cost
    
    if random.random() < success_chance:
        # Successful research
        old_level = player.tech_level
        player.tech_level += 1
        
        # Tech level benefits
        tech_benefits = {
            2: "Improved resource gathering efficiency",
            3: "Unlocks cyber warfare capabilities", 
            4: "Enhanced military training programs",
            5: "Advanced agricultural techniques",
            6: "Sophisticated spy networks",
            7: "Industrial manufacturing processes",
            8: "Renewable energy systems",
            9: "Quantum computing networks",
            10: "Fusion power technology"
        }
        
        benefit = tech_benefits.get(player.tech_level, "Unknown technological advancement")
        
        db.commit()
        add_event(db, "tech_advancement", f"{player.civ_name} advanced to tech level {player.tech_level}", player.id)
        
        scroll_msg = "\n📜 **Ancient Scroll:** Research success guaranteed!" if success_bonus > 0 else ""
        
        await ctx.send(f"""🔬 **BREAKTHROUGH ACHIEVED!** ⚡

🧪 **{player.civ_name} advances to Tech Level {player.tech_level}!**
💰 **Research Cost:** {research_cost} gold{scroll_msg}

🌟 **New Capability Unlocked:**
{benefit}

📊 **Tech Level Benefits:**
• Combat effectiveness: +{player.tech_level * 10}%
• Hacking capabilities: {"Enabled" if player.tech_level >= 3 else "Disabled"}
• Resource efficiency: +{player.tech_level * 5}%

🚀 **Your civilization leaps forward into the future!**""")
        
    else:
        # Failed research
        db.commit()
        
        await ctx.send(f"""🔬 **RESEARCH FAILED!** 💥

🧪 **{player.civ_name}'s research project encounters setbacks!**
💰 **Gold Spent:** {research_cost} (wasted on failed experiments)
🔬 **Tech Level:** Remains at {player.tech_level}

💡 **Research Notes:**
"The path to discovery is paved with failed experiments..."
"Our scientists will learn from these mistakes..."

🎯 **Try again later! Scientific progress requires persistence!**""")

@bot.command(name='tech')
@require_player
async def show_technology(ctx, player, db):
    """Display your current technology level and bonuses"""
    tech_bonuses = {
        1: ["Basic tools and farming", "10% combat effectiveness"],
        2: ["Improved resource gathering", "20% combat effectiveness", "Enhanced efficiency"],
        3: ["Cyber warfare unlocked", "30% combat effectiveness", "Hacking capabilities"],
        4: ["Advanced military training", "40% combat effectiveness", "Better soldier recruitment"],
        5: ["Modern agriculture", "50% combat effectiveness", "Improved food production"],
        6: ["Sophisticated espionage", "60% combat effectiveness", "Enhanced spy networks"],
        7: ["Industrial manufacturing", "70% combat effectiveness", "Mass production capabilities"],
        8: ["Information technology", "80% combat effectiveness", "Digital infrastructure"],
        9: ["Quantum computing", "90% combat effectiveness", "Advanced AI systems"],
        10: ["Fusion technology", "100% combat effectiveness", "Unlimited clean energy"]
    }
    
    current_bonuses = tech_bonuses.get(player.tech_level, ["Unknown technology level"])
    next_cost = player.tech_level * 100
    
    tech_display = f"""🔬 **TECHNOLOGY STATUS** ⚡

🧪 **Current Tech Level:** {player.tech_level}/10

📊 **Active Bonuses:**"""
    
    for bonus in current_bonuses:
        tech_display += f"\n• {bonus}"
    
    tech_display += f"""

💰 **Next Research Cost:** {next_cost} gold
🎯 **Research Success Rate:** {"Varies based on investment and items"}

🔍 **Special Capabilities:**
• Hacking: {"✅ Enabled" if player.tech_level >= 3 else "❌ Requires Tech Level 3"}
• Advanced Combat: {"✅ Enabled" if player.tech_level >= 4 else "❌ Requires Tech Level 4"}
• Quantum Systems: {"✅ Enabled" if player.tech_level >= 9 else "❌ Requires Tech Level 9"}

🚀 **Use `.invent` to advance your technology!**"""
    
    await ctx.send(tech_display)

@bot.command(name='send')
@require_player
async def send_message(ctx, player, db, target_user: str, *, message: str):
    """Send a diplomatic message to another civilization"""
    if len(message) > 500:
        await ctx.send("📜 **Message too long!** Keep it under 500 characters.")
        return
    
    # Find target player
    target_user = target_user.replace('<@', '').replace('>', '').replace('!', '')
    target = db.query(Player).filter(Player.user_id == target_user).first()
    
    if not target:
        await ctx.send("🚫 **Target civilization not found!**")
        return
    
    if target.id == player.id:
        await ctx.send("🤔 **You cannot message yourself!**")
        return
    
    # Create message
    msg = Message(sender_id=player.id, receiver_id=target.id, content=message)
    db.add(msg)
    db.commit()
    
    await ctx.send(f"""📜 **DIPLOMATIC MESSAGE SENT!** 🕊️

📩 **To:** {target.civ_name}
📝 **Message:** "{message}"

✅ **Your diplomatic correspondence has been delivered to their court!**
💡 **They can read their messages with:** `.mail`""")

@bot.command(name='mail')
@require_player
async def check_messages(ctx, player, db):
    """Check your diplomatic mailbox"""
    messages = db.query(Message).filter(Message.receiver_id == player.id).order_by(Message.created_at.desc()).limit(10).all()
    
    if not messages:
        await ctx.send("📮 **No messages!** Your diplomatic mailbox is empty.")
        return
    
    mailbox = "📮 **DIPLOMATIC MAILBOX** 📜\n\n"
    
    for i, msg in enumerate(messages, 1):
        status = "📖" if msg.read else "📩"
        sender = db.query(Player).filter(Player.id == msg.sender_id).first()
        sender_name = sender.civ_name if sender else "Unknown"
        
        mailbox += f"{status} **#{i}** From: {sender_name}\n"
        mailbox += f"📅 {msg.created_at.strftime('%Y-%m-%d %H:%M')}\n"
        mailbox += f"💬 \"{msg.content[:100]}{'...' if len(msg.content) > 100 else ''}\"\n\n"
        
        # Mark as read
        if not msg.read:
            msg.read = True
    
    db.commit()
    
    mailbox += "📖 **All messages marked as read**"
    await ctx.send(mailbox)

@bot.command(name='provide')
@require_player
@require_cooldown('provide', 30)
async def share_resources(ctx, player, db, target_user: str, resource_type: str, amount: int):
    """Share resources with another civilization"""
    if amount <= 0:
        await ctx.send("🚫 **Invalid amount!** Must be positive.")
        return
    
    # Find target player
    target_user = target_user.replace('<@', '').replace('>', '').replace('!', '')
    target = db.query(Player).filter(Player.user_id == target_user).first()
    
    if not target:
        await ctx.send("🚫 **Target civilization not found!**")
        return
    
    if target.id == player.id:
        await ctx.send("🤔 **You cannot share with yourself!**")
        return
    
    resource_type = resource_type.lower()
    valid_resources = ['gold', 'wood', 'stone', 'food']
    
    if resource_type not in valid_resources:
        await ctx.send(f"🚫 **Invalid resource!** Choose from: {', '.join(valid_resources)}")
        return
    
    # Check if player has enough resources
    current_amount = getattr(player, resource_type)
    if current_amount < amount:
        await ctx.send(f"💸 **Insufficient {resource_type}!** You have {current_amount}, need {amount}.")
        return
    
    # Transfer resources
    setattr(player, resource_type, current_amount - amount)
    target_amount = getattr(target, resource_type)
    setattr(target, resource_type, target_amount + amount)
    
    # Small happiness boost for both
    player.happiness = min(100, player.happiness + 2)
    target.happiness = min(100, target.happiness + 5)
    
    db.commit()
    add_event(db, "resource_sharing", f"{player.civ_name} shared {amount} {resource_type} with {target.civ_name}", player.id)
    
    resource_emojis = {'gold': '💰', 'wood': '🪵', 'stone': '🪨', 'food': '🍞'}
    emoji = resource_emojis[resource_type]
    
    await ctx.send(f"""🤝 **RESOURCES SHARED!** 🎁

{emoji} **{player.civ_name} sends {amount} {resource_type} to {target.civ_name}!**

📊 **Transfer Details:**
• Your {resource_type}: {current_amount} → {current_amount - amount}
• Their {resource_type}: {target_amount} → {target_amount + amount}

😊 **Happiness Bonus:**
• Your happiness: +2 (generosity)
• Their happiness: +5 (gratitude)

🌟 **Acts of generosity strengthen diplomatic ties!**""")

@bot.command(name='puppet')
@require_player
@require_cooldown('puppet', 1440)  # 24 hour cooldown
async def create_puppet(ctx, player, db, target_user: str):
    """Attempt to make another civilization your puppet state"""
    # Find target player
    target_user = target_user.replace('<@', '').replace('>', '').replace('!', '')
    target = db.query(Player).filter(Player.user_id == target_user).first()
    
    if not target:
        await ctx.send("🚫 **Target civilization not found!**")
        return
    
    if target.id == player.id:
        await ctx.send("🤔 **You cannot puppet yourself!**")
        return
    
    # Calculate puppeting success based on relative power
    player_power = (player.soldiers * player.tech_level) + (player.territory * 10) + (player.gold // 100)
    target_power = (target.soldiers * target.tech_level) + (target.territory * 10) + (target.gold // 100)
    
    power_ratio = player_power / max(target_power, 1)
    success_chance = min(0.8, max(0.1, (power_ratio - 1) * 0.3 + 0.2))
    
    if random.random() < success_chance:
        # Successful puppeting
        # Target loses independence but gains protection
        tribute_gold = int(target.gold * 0.3)
        tribute_resources = int(target.wood * 0.2)
        
        player.gold += tribute_gold
        player.wood += tribute_resources
        
        target.gold = max(0, target.gold - tribute_gold)
        target.wood = max(0, target.wood - tribute_resources)
        target.happiness = max(0, target.happiness - 30)
        
        # Mark puppeting in database (using alliance table with special status)
        puppet_relation = Alliance(sender_id=player.id, receiver_id=target.id, status='puppet')
        db.add(puppet_relation)
        
        db.commit()
        add_event(db, "puppet_created", f"{target.civ_name} became a puppet state of {player.civ_name}", player.id)
        
        await ctx.send(f"""🎭 **PUPPET STATE ESTABLISHED!** 👑

🏛️ **{target.civ_name} submits to {player.civ_name}'s dominance!**
💪 **Power Ratio:** {power_ratio:.2f} (Success: {success_chance*100:.1f}%)

💰 **Tribute Collected:**
• Gold: +{tribute_gold} (from their treasury)
• Wood: +{tribute_resources} (from their stockpiles)

📊 **Puppet State Effects:**
• Target cannot attack you
• Reduced happiness for puppet (-30)
• Regular tribute payments
• Your protection from other attacks

👑 **Another civilization bows before your supreme power!**""")
        
    else:
        # Failed puppeting attempt
        soldier_losses = random.randint(1, max(2, player.soldiers // 8))
        gold_cost = random.randint(50, 200)
        
        player.soldiers = max(0, player.soldiers - soldier_losses)
        player.gold = max(0, player.gold - gold_cost)
        player.happiness = max(0, player.happiness - 15)
        
        db.commit()
        
        await ctx.send(f"""🎭 **PUPPETING FAILED!** 💥

🏛️ **{target.civ_name} successfully resists {player.civ_name}'s dominance!**
💪 **Power Ratio:** {power_ratio:.2f} (Success: {success_chance*100:.1f}%)

💸 **Failed Attempt Costs:**
• Soldiers lost: {soldier_losses} (remaining: {player.soldiers})
• Gold lost: {gold_cost} (remaining: {player.gold:,})
• Happiness lost: 15 (now {player.happiness}/100)

🛡️ **Their independence remains intact! You need more power to dominate them!**""")

@bot.command(name='revolt')
@require_player
@require_cooldown('revolt', 720)  # 12 hour cooldown
async def puppet_revolt(ctx, player, db):
    """Attempt to overthrow your puppet master and regain independence"""
    # Check if player is a puppet
    puppet_relation = db.query(Alliance).filter(
        Alliance.receiver_id == player.id,
        Alliance.status == 'puppet'
    ).first()
    
    if not puppet_relation:
        await ctx.send("🚫 **You are not a puppet state!** This command is only for oppressed civilizations.")
        return
    
    master = db.query(Player).filter(Player.id == puppet_relation.sender_id).first()
    if not master:
        # Cleanup orphaned relation
        db.delete(puppet_relation)
        db.commit()
        await ctx.send("🎭 **No puppet master found!** You are already free.")
        return
    
    # Calculate revolt success based on relative power growth
    player_power = (player.soldiers * player.tech_level) + player.happiness
    master_power = (master.soldiers * master.tech_level) + (master.territory * 5)
    
    power_ratio = player_power / max(master_power, 1)
    success_chance = min(0.7, max(0.2, power_ratio * 0.4 + 0.1))
    
    if random.random() < success_chance:
        # Successful revolt
        db.delete(puppet_relation)
        
        # Revolt bonuses
        freedom_bonus = random.randint(20, 50)
        player.happiness = min(100, player.happiness + freedom_bonus)
        player.soldiers += random.randint(2, 5)  # Rebels join the cause
        
        # Master losses from losing puppet
        master.happiness = max(0, master.happiness - 10)
        
        db.commit()
        add_event(db, "revolt_success", f"{player.civ_name} successfully revolted against {master.civ_name}", player.id)
        
        await ctx.send(f"""🗽 **REVOLUTION SUCCESSFUL!** ⚡

🔥 **{player.civ_name} breaks free from {master.civ_name}'s oppression!**
💪 **Revolution Power:** {power_ratio:.2f} (Success: {success_chance*100:.1f}%)

🎉 **Freedom Achieved:**
• Independence restored!
• Happiness surges: +{freedom_bonus} (now {player.happiness}/100)
• Rebels join your army: +2-5 soldiers
• No more tribute payments

🗽 **LIBERTY OR DEATH! Your people celebrate their hard-won freedom!**""")
        
    else:
        # Failed revolt - harsh punishment
        soldier_losses = random.randint(2, max(3, player.soldiers // 3))
        happiness_loss = random.randint(20, 40)
        gold_seized = min(player.gold, random.randint(100, 300))
        
        player.soldiers = max(0, player.soldiers - soldier_losses)
        player.happiness = max(0, player.happiness - happiness_loss)
        player.gold = max(0, player.gold - gold_seized)
        
        # Master gets tribute from crushing revolt
        master.gold += gold_seized
        master.happiness = min(100, master.happiness + 5)
        
        db.commit()
        
        await ctx.send(f"""🗽 **REVOLUTION CRUSHED!** 💥

🔥 **{master.civ_name} brutally suppresses {player.civ_name}'s uprising!**
💪 **Revolution Power:** {power_ratio:.2f} (Success: {success_chance*100:.1f}%)

💸 **Harsh Punishment:**
• Soldiers executed: {soldier_losses} (remaining: {player.soldiers})
• Happiness crushed: -{happiness_loss} (now {player.happiness}/100)
• Gold seized: {gold_seized} (remaining: {player.gold:,})

⛓️ **Your chains grow heavier! The puppet master tightens their grip!**""")

@bot.command(name='disaster')
@require_player
@require_cooldown('disaster', 360)  # 6 hour cooldown
async def trigger_disaster(ctx, player, db):
    """Trigger a random natural disaster (for testing or roleplay)"""
    disasters = [
        {
            'name': 'Earthquake',
            'emoji': '🌍',
            'effects': {'stone': -0.2, 'buildings': 1, 'happiness': -15},
            'description': 'A massive earthquake shakes your civilization!'
        },
        {
            'name': 'Famine', 
            'emoji': '🌾',
            'effects': {'food': -0.4, 'hunger': 25, 'citizens': -0.1},
            'description': 'Crops fail and famine grips the land!'
        },
        {
            'name': 'Flood',
            'emoji': '🌊', 
            'effects': {'wood': -0.3, 'food': -0.2, 'happiness': -10},
            'description': 'Raging floods devastate your territories!'
        },
        {
            'name': 'Plague',
            'emoji': '🦠',
            'effects': {'citizens': -0.2, 'soldiers': -0.15, 'happiness': -25},
            'description': 'A deadly plague spreads through your population!'
        },
        {
            'name': 'Wildfire',
            'emoji': '🔥',
            'effects': {'wood': -0.5, 'food': -0.3, 'buildings': 2},
            'description': 'Uncontrolled wildfires burn across your lands!'
        },
        {
            'name': 'Meteor Strike',
            'emoji': '☄️',
            'effects': {'territory': -0.15, 'buildings': 3, 'citizens': -0.3, 'gold': -0.1},
            'description': 'A meteor crashes into your civilization!'
        }
    ]
    
    disaster = random.choice(disasters)
    effects_list = []
    
    # Apply disaster effects
    for effect, value in disaster['effects'].items():
        if effect == 'buildings':
            # Destroy random buildings
            buildings = ['houses', 'farms', 'barracks', 'walls', 'markets']
            for _ in range(value):
                building = random.choice(buildings)
                current = getattr(player, building)
                if current > 0:
                    setattr(player, building, max(0, current - 1))
                    effects_list.append(f"🏗️ 1 {building[:-1]} destroyed")
        else:
            # Percentage-based effects
            if hasattr(player, effect):
                current = getattr(player, effect)
                if value < 0:  # Reduction
                    loss = int(abs(current * value))
                    new_value = max(1 if effect in ['citizens', 'territory'] else 0, current - loss)
                    setattr(player, effect, new_value)
                    effects_list.append(f"📉 -{loss} {effect}")
                else:  # Increase (like hunger)
                    increase = value
                    new_value = min(100 if effect == 'happiness' or effect == 'hunger' else current + increase, current + increase)
                    setattr(player, effect, new_value)
                    effects_list.append(f"📈 +{increase} {effect}")
    
    db.commit()
    add_event(db, "natural_disaster", f"{disaster['name']} struck {player.civ_name}", player.id)
    
    await ctx.send(f"""{disaster['emoji']} **NATURAL DISASTER!** {disaster['emoji']}

💥 **{disaster['description']}**

📊 **Disaster Effects:**
{chr(10).join(effects_list) if effects_list else "• Minimal damage"}

🛡️ **Your civilization endures but is weakened by nature's wrath!**
💪 **Rebuild and recover stronger than before!**""")

@bot.command(name='propaganda')
@require_player
@require_cooldown('propaganda', 180)
async def spread_propaganda(ctx, player, db, target_user: str):
    """Spread propaganda to steal soldiers and lower enemy morale"""
    # Find target player
    target_user = target_user.replace('<@', '').replace('>', '').replace('!', '')
    target = db.query(Player).filter(Player.user_id == target_user).first()
    
    if not target:
        await ctx.send("🚫 **Target civilization not found!**")
        return
    
    if target.id == player.id:
        await ctx.send("🤔 **You cannot spread propaganda against yourself!**")
        return
    
    # Propaganda effectiveness based on happiness difference and tech
    happiness_advantage = player.happiness - target.happiness
    tech_bonus = player.tech_level * 5
    base_effectiveness = happiness_advantage + tech_bonus
    
    success_chance = max(0.2, min(0.8, (base_effectiveness + 50) / 100))
    
    propaganda_cost = 50  # Gold cost for propaganda campaign
    if player.gold < propaganda_cost:
        await ctx.send(f"💸 **Need {propaganda_cost} gold for propaganda campaign!**")
        return
    
    player.gold -= propaganda_cost
    
    if random.random() < success_chance:
        # Successful propaganda
        soldiers_converted = random.randint(1, max(2, target.soldiers // 10))
        territory_influenced = min(target.territory * 0.1, 2.0)
        
        # Transfer soldiers and territory
        player.soldiers += soldiers_converted
        player.territory += territory_influenced
        
        target.soldiers = max(0, target.soldiers - soldiers_converted)
        target.territory = max(1.0, target.territory - territory_influenced)
        target.happiness = max(0, target.happiness - 15)
        
        db.commit()
        add_event(db, "propaganda_success", f"{player.civ_name} successfully influenced {target.civ_name}", player.id)
        
        await ctx.send(f"""📢 **PROPAGANDA CAMPAIGN SUCCESSFUL!** 🎭

🗣️ **{player.civ_name} sways the hearts and minds of {target.civ_name}!**
💰 **Campaign Cost:** {propaganda_cost} gold
📊 **Effectiveness:** {success_chance*100:.1f}%

🎯 **Results:**
⚔️ **Soldiers defected:** {soldiers_converted} (now yours: {player.soldiers})
🗺️ **Territory influenced:** {territory_influenced:.1f} km² (now yours: {player.territory:.1f} km²)
😞 **Enemy morale decreased:** -15 happiness

📺 **Your superior propaganda machine turns their people against them!**""")
        
    else:
        # Failed propaganda - potential backlash
        if random.random() < 0.3:
            happiness_loss = random.randint(5, 15)
            player.happiness = max(0, player.happiness - happiness_loss)
            backlash_msg = f"\n💥 **Backlash:** Your failed propaganda hurts your reputation! -{happiness_loss} happiness"
        else:
            backlash_msg = ""
        
        db.commit()
        
        await ctx.send(f"""📢 **PROPAGANDA CAMPAIGN FAILED!** 📺

🗣️ **{target.civ_name} sees through {player.civ_name}'s manipulation!**
💰 **Campaign Cost:** {propaganda_cost} gold (wasted)
📊 **Effectiveness:** {success_chance*100:.1f}%

🛡️ **Their citizens remain loyal to their civilization!**{backlash_msg}

💭 **Counter-propaganda neutralizes your efforts!**""")

@bot.command(name='trade')
@require_player
@require_cooldown('trade', 45)
async def trade_resources(ctx, player, db, target_user: str, give_resource: str, give_amount: int, want_resource: str, want_amount: int):
    """Trade resources with another civilization"""
    if give_amount <= 0 or want_amount <= 0:
        await ctx.send("🚫 **Invalid amounts!** Must be positive numbers.")
        return
    
    # Find target player
    target_user = target_user.replace('<@', '').replace('>', '').replace('!', '')
    target = db.query(Player).filter(Player.user_id == target_user).first()
    
    if not target:
        await ctx.send("🚫 **Target civilization not found!**")
        return
    
    if target.id == player.id:
        await ctx.send("🤔 **You cannot trade with yourself!**")
        return
    
    give_resource = give_resource.lower()
    want_resource = want_resource.lower()
    valid_resources = ['gold', 'wood', 'stone', 'food']
    
    if give_resource not in valid_resources or want_resource not in valid_resources:
        await ctx.send(f"🚫 **Invalid resources!** Choose from: {', '.join(valid_resources)}")
        return
    
    # Check if both players have enough resources
    player_amount = getattr(player, give_resource)
    target_amount = getattr(target, want_resource)
    
    if player_amount < give_amount:
        await ctx.send(f"💸 **You don't have enough {give_resource}!** Need {give_amount}, have {player_amount}.")
        return
    
    if target_amount < want_amount:
        await ctx.send(f"💸 **{target.civ_name} doesn't have enough {want_resource}!** They need {want_amount}, have {target_amount}.")
        return
    
    # Calculate trade fairness (rough market values)
    resource_values = {'gold': 1.0, 'wood': 0.8, 'stone': 0.9, 'food': 0.6}
    give_value = give_amount * resource_values[give_resource]
    want_value = want_amount * resource_values[want_resource]
    fairness_ratio = give_value / want_value
    
    # Auto-accept fair trades (0.8 to 1.2 ratio), otherwise require manual acceptance
    if 0.8 <= fairness_ratio <= 1.2:
        # Execute trade immediately
        setattr(player, give_resource, player_amount - give_amount)
        setattr(player, want_resource, getattr(player, want_resource) + want_amount)
        
        setattr(target, want_resource, target_amount - want_amount)
        setattr(target, give_resource, getattr(target, give_resource) + give_amount)
        
        # Small happiness boost for fair trade
        player.happiness = min(100, player.happiness + 3)
        target.happiness = min(100, target.happiness + 3)
        
        db.commit()
        add_event(db, "trade_completed", f"{player.civ_name} traded with {target.civ_name}", player.id)
        
        resource_emojis = {'gold': '💰', 'wood': '🪵', 'stone': '🪨', 'food': '🍞'}
        
        await ctx.send(f"""🤝 **TRADE COMPLETED!** 📈

💼 **{player.civ_name} ↔️ {target.civ_name}**
⚖️ **Fair Trade Ratio:** {fairness_ratio:.2f} (Auto-accepted)

📊 **Trade Details:**
{resource_emojis[give_resource]} You gave: {give_amount} {give_resource}
{resource_emojis[want_resource]} You received: {want_amount} {want_resource}

😊 **Both civilizations benefit from this exchange!**
📈 **+3 Happiness for mutual prosperity**""")
        
    else:
        # Unfair trade - would need manual acceptance (simplified for this implementation)
        await ctx.send(f"""🤝 **TRADE PROPOSAL** 📋

💼 **{player.civ_name} → {target.civ_name}**
⚖️ **Trade Ratio:** {fairness_ratio:.2f} {"(Fair)" if 0.8 <= fairness_ratio <= 1.2 else "(Unfair)"}

📊 **Proposed Trade:**
{resource_emojis.get(give_resource, '📦')} You offer: {give_amount} {give_resource}
{resource_emojis.get(want_resource, '📦')} You want: {want_amount} {want_resource}

❌ **Trade rejected!** The proposed exchange is too unfavorable.
💡 **Try offering a more balanced trade ratio (0.8-1.2)**""")

@bot.command(name='blackmarket')
@require_player
@require_cooldown('blackmarket', 240)
async def black_market(ctx, player, db):
    """Buy rare items with risk of being caught"""
    if player.gold < 200:
        await ctx.send("💸 **Need at least 200 gold for black market dealings!**")
        return
    
    # Available black market items with risks
    market_items = [
        {'name': 'Lucky Charm', 'cost': 200, 'risk': 0.1},
        {'name': 'War Drum', 'cost': 500, 'risk': 0.2},
        {'name': 'Gold Crown', 'cost': 400, 'risk': 0.15},
        {'name': 'Territory Map', 'cost': 600, 'risk': 0.25},
        {'name': 'Ancient Scroll', 'cost': 350, 'risk': 0.15},
        {'name': 'Nuclear Warhead', 'cost': 2000, 'risk': 0.4}
    ]
    
    # Filter items player can afford
    affordable_items = [item for item in market_items if item['cost'] <= player.gold]
    
    if not affordable_items:
        await ctx.send("💸 **Cannot afford any black market items!** Save up more gold.")
        return
    
    item = random.choice(affordable_items)
    
    # Check if caught
    caught = random.random() < item['risk']
    
    if caught:
        # Caught by authorities
        fine = item['cost']
        player.gold = max(0, player.gold - fine)
        player.happiness = max(0, player.happiness - 20)
        
        db.commit()
        
        await ctx.send(f"""🚨 **BUSTED BY AUTHORITIES!** 👮

🕵️ **Your black market deal for {item['name']} was discovered!**
💸 **Consequences:**
• Fine paid: {fine} gold (remaining: {player.gold:,})
• Reputation damaged: -20 happiness (now {player.happiness}/100)
• No item acquired

⚖️ **Crime doesn't pay! Your illegal activities have been exposed!**""")
        
    else:
        # Successful black market purchase
        player.gold -= item['cost']
        
        # Add item to inventory
        special_item = db.query(SpecialItem).filter(SpecialItem.name == item['name']).first()
        existing_item = db.query(PlayerItem).filter(
            PlayerItem.player_id == player.id,
            PlayerItem.item_id == special_item.id
        ).first()
        
        if existing_item:
            existing_item.quantity += 1
        else:
            player_item = PlayerItem(player_id=player.id, item_id=special_item.id, quantity=1)
            db.add(player_item)
        
        db.commit()
        add_event(db, "black_market_purchase", f"{player.civ_name} acquired {item['name']} from black market", player.id)
        
        await ctx.send(f"""🖤 **BLACK MARKET SUCCESS!** 💰

🕴️ **You successfully acquire {item['name']} through underground channels!**
💸 **Cost:** {item['cost']} gold (remaining: {player.gold:,})
🎯 **Risk:** {item['risk']*100:.0f}% (avoided detection)

🎒 **New Item Added to Inventory:**
✨ {special_item.description}

🤫 **Keep this transaction secret... for your own safety.**""")

@bot.command(name='festival')
@require_player
@require_cooldown('festival', 120)
async def hold_festival(ctx, player, db):
    """Hold a grand festival to boost happiness and reduce hunger"""
    festival_cost = 150  # Gold cost
    food_cost = 50      # Food cost
    
    if player.gold < festival_cost:
        await ctx.send(f"💸 **Need {festival_cost} gold to organize a festival!**")
        return
    
    if player.food < food_cost:
        await ctx.send(f"🍞 **Need {food_cost} food to feed festival guests!**")
        return
    
    player.gold -= festival_cost
    player.food -= food_cost
    
    # Festival benefits
    happiness_gain = random.randint(25, 40)
    hunger_reduction = random.randint(15, 25)
    
    # Gold Crown bonus
    if has_item(db, player.id, "Gold Crown"):
        happiness_gain = int(happiness_gain * 1.3)
        crown_msg = "\n👑 **Gold Crown Effect:** +30% happiness bonus!"
    else:
        crown_msg = ""
    
    player.happiness = min(100, player.happiness + happiness_gain)
    player.hunger = max(0, player.hunger - hunger_reduction)
    
    db.commit()
    add_event(db, "festival_held", f"{player.civ_name} held a grand festival", player.id)
    
    festival_types = [
        "🎪 Grand Carnival",
        "🎭 Theater Festival", 
        "🎵 Music Festival",
        "🍇 Harvest Festival",
        "🎨 Arts Festival",
        "🏆 Victory Celebration"
    ]
    
    festival_name = random.choice(festival_types)
    
    await ctx.send(f"""🎉 **{festival_name}** 🎉

🎪 **{player.civ_name} hosts a magnificent celebration!**

💰 **Festival Costs:**
• Gold spent: {festival_cost} (remaining: {player.gold:,})
• Food consumed: {food_cost} (remaining: {player.food:,})

🎊 **Festival Benefits:**
😊 **+{happiness_gain} Happiness** (now {player.happiness}/100)
🍽️ **-{hunger_reduction} Hunger** (now {player.hunger}/100){crown_msg}

🌟 **Your citizens dance in the streets with joy!**
🎆 **The celebration brings unity and prosperity to your realm!**""")

@bot.command(name='mercenaries')
@require_player
@require_cooldown('mercenaries', 180)
async def hire_mercenaries(ctx, player, db, amount: int):
    """Hire temporary soldiers for gold"""
    if amount <= 0 or amount > 20:
        await ctx.send("🚫 **Invalid amount!** Hire 1-20 mercenaries at a time.")
        return
    
    cost_per_mercenary = 75
    total_cost = amount * cost_per_mercenary
    
    if player.gold < total_cost:
        await ctx.send(f"💸 **Need {total_cost} gold to hire {amount} mercenaries!** (Cost: {cost_per_mercenary} each)")
        return
    
    player.gold -= total_cost
    player.soldiers += amount
    
    # Mercenaries are temporary and might leave (tracked via events)
    db.commit()
    add_event(db, "mercenaries_hired", f"{player.civ_name} hired {amount} mercenaries", player.id)
    
    mercenary_types = [
        "⚔️ Battle-hardened Veterans",
        "🏹 Elite Archers",
        "🛡️ Heavy Infantry",
        "🐎 Mounted Warriors", 
        "🗡️ Sword Masters",
        "⚡ Lightning Raiders"
    ]
    
    mercenary_type = random.choice(mercenary_types)
    
    await ctx.send(f"""⚔️ **MERCENARIES HIRED!** 💰

🎯 **{mercenary_type} join your army!**

📊 **Contract Details:**
• Mercenaries hired: {amount}
• Cost per soldier: {cost_per_mercenary} gold
• Total cost: {total_cost} gold
• Remaining gold: {player.gold:,}

⚔️ **New Army Size:** {player.soldiers} soldiers

⚠️ **Warning:** Mercenaries fight for gold, not loyalty!
💡 **They're effective but may desert if not paid well!**""")

@bot.command(name='treasure')
@require_player
@require_cooldown('treasure', 300)
async def treasure_hunt(ctx, player, db):
    """Search for hidden treasure and rare items"""
    search_cost = 100  # Gold cost for expedition
    
    if player.gold < search_cost:
        await ctx.send(f"💸 **Need {search_cost} gold to fund a treasure expedition!**")
        return
    
    player.gold -= search_cost
    
    # Lucky charm improves treasure hunting odds
    base_success = 0.4
    if has_item(db, player.id, "Lucky Charm"):
        success_chance = 0.6
        luck_msg = "\n🍀 **Lucky Charm:** Improved treasure hunting!"
    else:
        success_chance = base_success
        luck_msg = ""
    
    if random.random() < success_chance:
        # Successful treasure hunt
        treasure_type = random.choice([
            'gold_large', 'gold_medium', 'resources', 'item_common', 'item_rare'
        ])
        
        if treasure_type == 'gold_large':
            gold_found = random.randint(500, 1000)
            player.gold += gold_found
            treasure_msg = f"💰 **Massive gold cache discovered:** +{gold_found} gold!"
            
        elif treasure_type == 'gold_medium':
            gold_found = random.randint(200, 500)
            player.gold += gold_found
            treasure_msg = f"💰 **Gold stash found:** +{gold_found} gold!"
            
        elif treasure_type == 'resources':
            wood_found = random.randint(100, 200)
            stone_found = random.randint(80, 150)
            food_found = random.randint(50, 100)
            player.wood += wood_found
            player.stone += stone_found
            player.food += food_found
            treasure_msg = f"📦 **Resource cache:** +{wood_found} wood, +{stone_found} stone, +{food_found} food!"
            
        elif treasure_type == 'item_common':
            # Award a common item
            common_items = ['Lucky Charm']
            item_name = random.choice(common_items)
            special_item = db.query(SpecialItem).filter(SpecialItem.name == item_name).first()
            
            existing_item = db.query(PlayerItem).filter(
                PlayerItem.player_id == player.id,
                PlayerItem.item_id == special_item.id
            ).first()
            
            if existing_item:
                existing_item.quantity += 1
            else:
                player_item = PlayerItem(player_id=player.id, item_id=special_item.id, quantity=1)
                db.add(player_item)
            
            treasure_msg = f"✨ **Rare artifact discovered:** {item_name}!"
            
        elif treasure_type == 'item_rare':
            # Small chance for rare item
            rare_items = ['War Drum', 'Gold Crown', 'Territory Map', 'Ancient Scroll']
            item_name = random.choice(rare_items)
            special_item = db.query(SpecialItem).filter(SpecialItem.name == item_name).first()
            
            existing_item = db.query(PlayerItem).filter(
                PlayerItem.player_id == player.id,
                PlayerItem.item_id == special_item.id
            ).first()
            
            if existing_item:
                existing_item.quantity += 1
            else:
                player_item = PlayerItem(player_id=player.id, item_id=special_item.id, quantity=1)
                db.add(player_item)
            
            treasure_msg = f"🌟 **LEGENDARY ARTIFACT FOUND:** {item_name}!"
        
        db.commit()
        add_event(db, "treasure_found", f"{player.civ_name} discovered treasure", player.id)
        
        await ctx.send(f"""🗺️ **TREASURE DISCOVERED!** ✨

🏴‍☠️ **Your expedition strikes gold in the ancient ruins!**
💰 **Expedition Cost:** {search_cost} gold{luck_msg}

🎯 **Treasure Found:**
{treasure_msg}

💼 **Updated Balance:** {player.gold:,} gold
🌟 **Fortune favors the bold explorer!**""")
        
    else:
        # Failed treasure hunt
        db.commit()
        
        failure_outcomes = [
            "🗺️ **No treasure found!** The map was a fake.",
            "🕳️ **Empty ruins!** Previous explorers got here first.",
            "🐍 **Dangerous wildlife!** Your team retreats safely but empty-handed.",
            "🌧️ **Bad weather!** Storms force an early return.",
            "🗿 **Ancient traps!** The ruins are too dangerous to explore."
        ]
        
        await ctx.send(f"""🗺️ **TREASURE HUNT FAILED!** 💸

{random.choice(failure_outcomes)}

💰 **Expedition Cost:** {search_cost} gold (remaining: {player.gold:,}){luck_msg}

🎯 **Sometimes fortune eludes even the most determined explorers!**
💡 **Try again later - persistence often pays off!**""")

# Flask Web Dashboard
app = Flask(__name__)

@app.route('/')
def dashboard():
    db = SessionLocal()
    try:
        # Get statistics
        total_players = db.query(Player).count()
        total_alliances = db.query(Alliance).filter(Alliance.status == 'accepted').count()
        
        # Get top territories
        top_territories = db.query(Player).order_by(Player.territory.desc()).limit(10).all()
        
        # Get recent events
        recent_events = db.query(GameEvent).order_by(GameEvent.created_at.desc()).limit(20).all()
        
        # Calculate total resources
        total_gold = db.query(Player).with_entities(Player.gold).all()
        total_gold_sum = sum([p.gold for p in total_gold])
        
        dashboard_html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>WarBot Dashboard</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #1a1a1a; color: #fff; }}
        .header {{ text-align: center; background: #2d2d2d; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
        .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin-bottom: 20px; }}
        .stat-card {{ background: #2d2d2d; padding: 20px; border-radius: 10px; text-align: center; }}
        .stat-number {{ font-size: 2em; font-weight: bold; color: #4CAF50; }}
        .territories {{ background: #2d2d2d; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
        .events {{ background: #2d2d2d; padding: 20px; border-radius: 10px; }}
        .territory-item {{ padding: 5px 0; border-bottom: 1px solid #444; }}
        .event-item {{ padding: 5px 0; border-bottom: 1px solid #444; font-size: 0.9em; }}
        .last-update {{ text-align: center; margin-top: 20px; color: #888; }}
        h1 {{ color: #4CAF50; }}
        h2 {{ color: #FFA500; }}
    </style>
    <script>
        setTimeout(function(){{ window.location.reload(); }}, 30000); // Auto-refresh every 30 seconds
    </script>
</head>
<body>
    <div class="header">
        <h1>🏛️ WarBot Civilization Dashboard 👑</h1>
        <p>Real-time statistics and empire management</p>
    </div>
    
    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-number">{total_players}</div>
            <div>Total Civilizations</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{total_alliances}</div>
            <div>Active Alliances</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{total_gold_sum:,}</div>
            <div>Total Gold in Economy</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{len(recent_events)}</div>
            <div>Recent Events</div>
        </div>
    </div>
    
    <div class="territories">
        <h2>🗺️ Territory Rankings</h2>
        {"".join([f'<div class="territory-item">#{i+1}. {civ.civ_name} - {civ.territory:.1f} km² ({civ.username})</div>' for i, civ in enumerate(top_territories)])}
    </div>
    
    <div class="events">
        <h2>📰 Recent Events</h2>
        {"".join([f'<div class="event-item">{event.created_at.strftime("%H:%M")} - {event.description}</div>' for event in recent_events])}
    </div>
    
    <div class="last-update">
        Last updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')} | Auto-refresh: 30s
    </div>
</body>
</html>
        """
        
        return dashboard_html
        
    finally:
        db.close()

@app.route('/api/stats')
def api_stats():
    db = SessionLocal()
    try:
        stats = {
            'total_players': db.query(Player).count(),
            'total_alliances': db.query(Alliance).filter(Alliance.status == 'accepted').count(),
            'total_events': db.query(GameEvent).count(),
            'last_update': datetime.utcnow().isoformat()
        }
        return jsonify(stats)
    finally:
        db.close()

# Custom help command with different name to avoid conflict
@bot.command(name='commands')
async def show_commands(ctx, command_name: str = None):
    """Show help for all commands or a specific command"""
    if command_name:
        # Show help for specific command (simplified)
        await ctx.send(f"ℹ️ **Help for specific commands not implemented yet.** Use `.commands` for full command list.")
        return
    
    help_text = """🏛️ **WarBot Command Guide** 👑

**🏗️ CIVILIZATION MANAGEMENT:**
`.start <name>` - Found your civilization
`.status` - View your empire stats
`.build <type>` - Construct buildings (house/farm/barracks/wall/market)

**💰 ECONOMY & RESOURCES:**
`.gather` - Collect resources from territory
`.farm` - Produce extra food
`.cheer` - Boost happiness
`.feed` - Reduce hunger
`.gamble <amount>` - Risk gold for big gains

**⚔️ WARFARE & COMBAT:**
`.attack @user` - Attack another civilization
`.stealthbattle @user` - Surprise attack with higher risk/reward
`.nuke @user` - Nuclear strike (requires Nuclear Warhead)
`.siege @user` - Prolonged attack to capture territory

**🕵️ ESPIONAGE:**
`.spy @user` - Gather intelligence
`.sabotage @user` - Destroy enemy resources
`.hack @user` - Steal gold using technology

**🤝 DIPLOMACY & ALLIANCES:**
`.ally @user` - Form alliance
`.break @user` - Break alliance
`.send @user <message>` - Send diplomatic message
`.mail` - Check your messages

**🔬 TECHNOLOGY:**
`.invent` - Research new technology
`.tech` - View current tech bonuses

**🎯 SPECIAL FEATURES:**
`.provide @user <resource> <amount>` - Share resources
`.puppet @user` - Create puppet state
`.revolt` - Overthrow puppet master
`.disaster` - Trigger random disaster
`.propaganda @user` - Influence enemy population

**🛒 MARKETPLACE & ITEMS:**
`.trade @user <give> <amount> <want> <amount>` - Trade resources
`.blackmarket` - Buy rare items (risky)
`.mercenaries <amount>` - Hire temporary soldiers
`.treasure` - Hunt for hidden treasure

**🎉 EVENTS & FESTIVALS:**
`.festival` - Hold celebration to boost morale

⏰ **Note:** Most commands have cooldowns to prevent spam.
🎒 **Special Items:** Collect rare items with unique effects!
🌍 **Territory:** Larger territory = better resource production!

💡 **Pro Tips:**
• Build houses to increase population
• Use farms to manage hunger
• Form alliances for protection
• Research technology for advantages
• Collect special items for unique abilities

🎮 **Have fun building your empire!** 👑"""
    
    await ctx.send(help_text)

# Random disaster system (automatic)
async def random_disaster_system():
    """Automatically trigger random disasters"""
    while True:
        try:
            await asyncio.sleep(3600)  # Check every hour
            
            if random.random() < 0.1:  # 10% chance per hour
                db = SessionLocal()
                try:
                    players = db.query(Player).all()
                    if players:
                        target_player = random.choice(players)
                        
                        # Use the same disaster system as the command
                        disasters = [
                            {
                                'name': 'Earthquake',
                                'emoji': '🌍',
                                'effects': {'stone': -0.15, 'happiness': -10},
                                'description': 'A sudden earthquake shakes the land!'
                            },
                            {
                                'name': 'Drought', 
                                'emoji': '☀️',
                                'effects': {'food': -0.3, 'hunger': 15},
                                'description': 'A severe drought withers the crops!'
                            },
                            {
                                'name': 'Storm',
                                'emoji': '⛈️', 
                                'effects': {'wood': -0.2, 'happiness': -8},
                                'description': 'Fierce storms damage infrastructure!'
                            }
                        ]
                        
                        disaster = random.choice(disasters)
                        
                        # Apply random disaster effects
                        for effect, value in disaster['effects'].items():
                            if hasattr(target_player, effect):
                                current = getattr(target_player, effect)
                                if value < 0:  # Reduction
                                    loss = int(abs(current * value))
                                    new_value = max(1 if effect in ['citizens', 'territory'] else 0, current - loss)
                                    setattr(target_player, effect, new_value)
                                else:  # Increase
                                    new_value = min(100 if effect in ['happiness', 'hunger'] else current + value, current + value)
                                    setattr(target_player, effect, new_value)
                        
                        db.commit()
                        add_event(db, "random_disaster", f"Random {disaster['name']} struck {target_player.civ_name}", int(target_player.id))
                        
                finally:
                    db.close()
        except Exception as e:
            print(f"Error in random disaster system: {e}")

# Start Flask server in a separate thread
def start_flask():
    app.run(host='0.0.0.0', port=5000, debug=False)

# Main execution
if __name__ == "__main__":
    # Start Flask dashboard in background
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    
    # Get bot token from environment
    token = os.getenv('GUILDED_TOKEN')
    if not token:
        print("❌ Error: GUILDED_TOKEN environment variable not set!")
        print("📝 Please set your Guilded bot token in the environment variables.")
        print("🔗 You can create a bot at: https://www.guilded.gg/")
        exit(1)
    
    print("🚀 Starting WarBot...")
    print("🌐 Web dashboard will be available at http://localhost:5000")
    print("🎮 Bot commands ready!")
    
    # Run the bot
    bot.run(token)
