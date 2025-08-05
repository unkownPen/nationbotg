"""
Guilded Civilization Bot - Complete Single File Implementation
A comprehensive civilization-building game bot with economy, combat, alliances, espionage, and natural disasters.
"""

import os
import asyncio
import guilded
from guilded.ext import commands
import logging
import sqlite3
import json
import random
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from aiohttp import web

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# WEB SERVER FOR RENDER COMPATIBILITY
# ============================================================================

async def health_check(request):
    """Simple health check endpoint for Render"""
    return web.Response(text="Bot is running")

async def start_web_server():
    """Start a simple web server for health checks"""
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Health check server running on port {port}")

# ============================================================================
# CONFIGURATION
# ============================================================================

class GameConfig:
    """Configuration class for game balance and settings"""
    
    # Cooldowns (in minutes)
    COOLDOWNS = {
        'gather': 1,
        'build': 2,
        'buy': 1.5,
        'farm': 2,
        'cheer': 1.5,
        'feed': 2,
        'gamble': 3,
        'attack': 1.5,
        'civil_war': 2.5,
        'ally': 2,
        'break': 2,
        'train': 1.5,
        'spy': 2,
        'sabotage': 3,
        'propaganda': 2.5,
        'send': 0.5,
        'mail': 1
    }
    
    # Building types and their properties
    BUILDINGS = {
        'house': {
            'name': 'House',
            'description': 'Increases population capacity',
            'cost': {'materials': 20, 'gold': 10},
            'effects': {'population': 5}
        },
        'farm': {
            'name': 'Farm',
            'description': 'Produces food over time',
            'cost': {'materials': 30, 'gold': 15},
            'effects': {'food_per_turn': 5}
        },
        'barracks': {
            'name': 'Barracks',
            'description': 'Trains soldiers for your army',
            'cost': {'materials': 50, 'gold': 25},
            'effects': {'soldiers': 3}
        },
        'wall': {
            'name': 'Wall',
            'description': 'Defensive structure',
            'cost': {'materials': 40, 'gold': 20},
            'effects': {'defenses': 2}
        },
        'market': {
            'name': 'Market',
            'description': 'Generates gold over time',
            'cost': {'materials': 60, 'gold': 30},
            'effects': {'gold_per_turn': 3}
        },
        'temple': {
            'name': 'Temple',
            'description': 'Increases happiness',
            'cost': {'materials': 80, 'gold': 40},
            'effects': {'happiness': 10}
        }
    }
    
    # Purchasable items
    SHOP_ITEMS = {
        'food': {
            'name': 'Food',
            'cost': 2,  # gold per unit
            'max_purchase': 50
        },
        'materials': {
            'name': 'Materials', 
            'cost': 3,  # gold per unit
            'max_purchase': 30
        },
        'soldier': {
            'name': 'Soldier',
            'cost': 15,  # gold per unit
            'max_purchase': 10
        }
    }
    
    # Starting civilization stats
    STARTING_STATS = {
        'gold': 50,
        'food': 100,
        'materials': 50,
        'population': 10,
        'happiness': 50,
        'hunger': 100,
        'soldiers': 5,
        'defenses': 1,
        'buildings': {},
        'wins': 0,
        'losses': 0,
        'level': 1,
        'experience': 0
    }
    
    # Game balance settings
    BALANCE = {
        'max_alliances': 3,
        'hunger_decay_rate': 2,  # per hour
        'happiness_decay_rate': 1,  # per hour
        'max_resources': {
            'gold': 1000,
            'food': 500,
            'materials': 300
        },
        'experience_per_level': 100,
        'level_benefits': {
            'population_bonus': 2,
            'resource_bonus': 5
        }
    }

# ============================================================================
# DATABASE MANAGER
# ============================================================================

class DatabaseManager:
    def __init__(self, db_path: str = 'civilizations.db'):
        self.db_path = db_path
        self.conn = None
        
    async def initialize(self):
        """Initialize database with required tables"""
        self.conn = sqlite3.connect(self.db_path)
        cursor = self.conn.cursor()
        
        # Civilizations table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS civilizations (
                user_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                
                -- Resources
                gold INTEGER DEFAULT 0,
                food INTEGER DEFAULT 100,
                materials INTEGER DEFAULT 50,
                population INTEGER DEFAULT 10,
                happiness INTEGER DEFAULT 50,
                hunger INTEGER DEFAULT 100,
                
                -- Military
                soldiers INTEGER DEFAULT 5,
                defenses INTEGER DEFAULT 1,
                
                -- Buildings
                buildings TEXT DEFAULT '{}',
                
                -- Stats
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                experience INTEGER DEFAULT 0
            )
        ''')
        
        # Cooldowns table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cooldowns (
                user_id TEXT,
                command TEXT,
                expires_at TIMESTAMP,
                PRIMARY KEY (user_id, command)
            )
        ''')
        
        # Alliances table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS alliances (
                user1_id TEXT,
                user2_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user1_id, user2_id)
            )
        ''')
        
        # Alliance requests table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS alliance_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user_id TEXT,
                to_user_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                UNIQUE(from_user_id, to_user_id)
            )
        ''')
        
        # Messages table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id TEXT NOT NULL,
                recipient_id TEXT NOT NULL,
                subject TEXT,
                content TEXT NOT NULL,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                read BOOLEAN DEFAULT FALSE
            )
        ''')
        
        self.conn.commit()
        
    async def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
        
    async def get_civilization(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get civilization data for a user"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM civilizations WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        
        if result:
            data = dict(zip([col[0] for col in cursor.description], result))
            data['buildings'] = json.loads(data['buildings'])
            return data
        return None
        
    async def create_civilization(self, user_id: str, name: str) -> bool:
        """Create a new civilization"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO civilizations (user_id, name, gold, food, materials, population, happiness, hunger, soldiers, defenses)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id, 
                name,
                GameConfig.STARTING_STATS['gold'],
                GameConfig.STARTING_STATS['food'],
                GameConfig.STARTING_STATS['materials'],
                GameConfig.STARTING_STATS['population'],
                GameConfig.STARTING_STATS['happiness'],
                GameConfig.STARTING_STATS['hunger'],
                GameConfig.STARTING_STATS['soldiers'],
                GameConfig.STARTING_STATS['defenses']
            ))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
            
    async def update_civilization(self, user_id: str, updates: Dict[str, Any]):
        """Update civilization data"""
        cursor = self.conn.cursor()
        
        # Convert buildings dict to JSON if present
        if 'buildings' in updates:
            updates['buildings'] = json.dumps(updates['buildings'])
            
        # Build update query
        set_clause = ', '.join([f'{key} = ?' for key in updates.keys()])
        values = list(updates.values()) + [user_id]
        
        cursor.execute(f'UPDATE civilizations SET {set_clause} WHERE user_id = ?', values)
        self.conn.commit()
        
    async def check_cooldown(self, user_id: str, command: str) -> Optional[datetime]:
        """Check if user is on cooldown for a command"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT expires_at FROM cooldowns 
            WHERE user_id = ? AND command = ? AND expires_at > CURRENT_TIMESTAMP
        ''', (user_id, command))
        
        result = cursor.fetchone()
        if result:
            return datetime.fromisoformat(result[0])
        return None
        
    async def set_cooldown(self, user_id: str, command: str, minutes: float):
        """Set cooldown for a command"""
        cursor = self.conn.cursor()
        expires_at = datetime.utcnow() + timedelta(minutes=minutes)
        
        cursor.execute('''
            INSERT OR REPLACE INTO cooldowns (user_id, command, expires_at)
            VALUES (?, ?, ?)
        ''', (user_id, command, expires_at.isoformat()))
        self.conn.commit()
        
    async def get_alliances(self, user_id: str) -> List[str]:
        """Get list of user's allies"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT user2_id FROM alliances WHERE user1_id = ?
            UNION
            SELECT user1_id FROM alliances WHERE user2_id = ?
        ''', (user_id, user_id))
        
        results = cursor.fetchall()
        return [row[0] for row in results]
        
    async def create_alliance(self, user1_id: str, user2_id: str) -> bool:
        """Create alliance between two users"""
        try:
            # Ensure consistent ordering
            if user1_id > user2_id:
                user1_id, user2_id = user2_id, user1_id
                
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO alliances (user1_id, user2_id)
                VALUES (?, ?)
            ''', (user1_id, user2_id))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
            
    async def break_alliance(self, user1_id: str, user2_id: str) -> bool:
        """Break alliance between two users"""
        cursor = self.conn.cursor()
        cursor.execute('''
            DELETE FROM alliances 
            WHERE (user1_id = ? AND user2_id = ?) OR (user1_id = ? AND user2_id = ?)
        ''', (user1_id, user2_id, user2_id, user1_id))
        
        affected = cursor.rowcount > 0
        self.conn.commit()
        return affected
        
    async def create_alliance_request(self, from_user_id: str, to_user_id: str) -> bool:
        """Create an alliance request"""
        try:
            # Set expiration to 24 hours from now
            expires_at = datetime.utcnow() + timedelta(hours=24)
            
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO alliance_requests (from_user_id, to_user_id, expires_at)
                VALUES (?, ?, ?)
            ''', (from_user_id, to_user_id, expires_at.isoformat()))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
            
    async def get_alliance_request(self, from_user_id: str, to_user_id: str) -> Optional[Dict[str, Any]]:
        """Get an active alliance request"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM alliance_requests 
            WHERE from_user_id = ? AND to_user_id = ? AND expires_at > CURRENT_TIMESTAMP
        ''', (from_user_id, to_user_id))
        
        result = cursor.fetchone()
        if result:
            columns = [col[0] for col in cursor.description]
            return dict(zip(columns, result))
        return None
        
    async def delete_alliance_request(self, from_user_id: str, to_user_id: str) -> bool:
        """Delete an alliance request"""
        cursor = self.conn.cursor()
        cursor.execute('''
            DELETE FROM alliance_requests 
            WHERE from_user_id = ? AND to_user_id = ?
        ''', (from_user_id, to_user_id))
        
        affected = cursor.rowcount > 0
        self.conn.commit()
        return affected
        
    async def send_message(self, sender_id: str, recipient_id: str, subject: str, content: str):
        """Send a message between players"""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO messages (sender_id, recipient_id, subject, content)
            VALUES (?, ?, ?, ?)
        ''', (sender_id, recipient_id, subject, content))
        self.conn.commit()
        
    async def get_messages(self, user_id: str, unread_only: bool = False) -> List[Dict[str, Any]]:
        """Get messages for a user"""
        cursor = self.conn.cursor()
        query = 'SELECT * FROM messages WHERE recipient_id = ?'
        params = [user_id]
        
        if unread_only:
            query += ' AND read = FALSE'
            
        query += ' ORDER BY sent_at DESC LIMIT 10'
        
        cursor.execute(query, params)
        results = cursor.fetchall()
        
        if not results:
            return []
        
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in results]
        
    async def mark_message_read(self, message_id: int):
        """Mark a message as read"""
        cursor = self.conn.cursor()
        cursor.execute('UPDATE messages SET read = TRUE WHERE id = ?', (message_id,))
        self.conn.commit()

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_user_from_mention(mention: str) -> Optional[str]:
    """Extract user ID from mention format"""
    # Guilded mentions are in format: <@userId>
    match = re.search(r'<@([a-zA-Z0-9]{8})>', mention)
    if match:
        return match.group(1)
    return None

def format_time_remaining(remaining_time: timedelta) -> str:
    """Format remaining time in a human-readable way"""
    total_seconds = int(remaining_time.total_seconds())
    
    if total_seconds <= 0:
        return "0 seconds"
    
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    else:
        return f"{seconds}s"

async def check_cooldown(db: DatabaseManager, user_id: str, command: str, cooldown_minutes: float) -> Optional[timedelta]:
    """Check if user is on cooldown for a command"""
    cooldown_end = await db.check_cooldown(user_id, command)
    if cooldown_end:
        remaining = cooldown_end - datetime.utcnow()
        if remaining.total_seconds() > 0:
            return remaining
    return None

# ============================================================================
# GAME LOGIC
# ============================================================================

class GameLogic:
    def __init__(self):
        self.config = GameConfig()
    
    def calculate_combat_result(self, attacker: dict, defender: dict) -> dict:
        """Calculate the result of combat between two civilizations"""
        attacker_power = attacker['soldiers'] + (attacker['defenses'] * 0.5)
        defender_power = defender['soldiers'] + (defender['defenses'] * 1.5)  # Defensive bonus
        
        # Add some randomness
        attacker_roll = random.uniform(0.8, 1.2)
        defender_roll = random.uniform(0.8, 1.2)
        
        final_attacker_power = attacker_power * attacker_roll
        final_defender_power = defender_power * defender_roll
        
        if final_attacker_power > final_defender_power:
            # Attacker wins
            power_ratio = final_attacker_power / final_defender_power
            
            # Calculate losses
            attacker_losses = max(1, int(attacker['soldiers'] * 0.1))
            defender_losses = max(1, int(defender['soldiers'] * min(0.5, power_ratio * 0.2)))
            
            # Calculate rewards
            gold_stolen = min(defender['gold'], int(defender['gold'] * 0.3))
            food_stolen = min(defender['food'], int(defender['food'] * 0.2))
            
            return {
                'winner': 'attacker',
                'attacker_losses': attacker_losses,
                'defender_losses': defender_losses,
                'gold_stolen': gold_stolen,
                'food_stolen': food_stolen,
                'power_ratio': power_ratio
            }
        else:
            # Defender wins
            power_ratio = final_defender_power / final_attacker_power
            
            # Calculate losses (attacker loses more when losing)
            attacker_losses = max(1, int(attacker['soldiers'] * min(0.6, power_ratio * 0.3)))
            defender_losses = max(1, int(defender['soldiers'] * 0.1))
            
            return {
                'winner': 'defender',
                'attacker_losses': attacker_losses,
                'defender_losses': defender_losses,
                'gold_stolen': 0,
                'food_stolen': 0,
                'power_ratio': power_ratio
            }
    
    def calculate_spy_result(self, target_civ: dict) -> dict:
        """Calculate espionage results"""
        # Base success chance
        success_chance = 0.7
        
        # Reduce chance based on target's defenses
        defense_penalty = min(0.3, target_civ['defenses'] * 0.05)
        success_chance -= defense_penalty
        
        success = random.random() < success_chance
        discovered = random.random() < 0.3  # 30% chance of being discovered
        
        return {
            'success': success,
            'discovered': discovered,
            'defense_penalty': defense_penalty
        }
    
    def calculate_sabotage_result(self, target_civ: dict) -> dict:
        """Calculate sabotage mission results"""
        # Base success chance
        success_chance = 0.6
        
        # Reduce chance based on target's defenses
        defense_penalty = min(0.4, target_civ['defenses'] * 0.08)
        success_chance -= defense_penalty
        
        success = random.random() < success_chance
        discovered = random.random() < 0.4  # 40% chance of being discovered
        
        result = {
            'success': success,
            'discovered': discovered
        }
        
        if success:
            # Determine damage type
            damage_types = ['building', 'resources', 'military']
            damage_type = random.choice(damage_types)
            result['damage_type'] = damage_type
            
            if damage_type == 'building' and target_civ['buildings']:
                # Destroy a random building
                building_types = list(target_civ['buildings'].keys())
                destroyed_building = random.choice(building_types)
                result['destroyed_building'] = destroyed_building
                
            elif damage_type == 'resources':
                # Steal/destroy resources
                result['gold_loss'] = random.randint(10, min(50, target_civ['gold']))
                result['food_loss'] = random.randint(5, min(30, target_civ['food']))
                
            elif damage_type == 'military':
                # Eliminate soldiers
                result['soldier_loss'] = random.randint(1, max(1, target_civ['soldiers'] // 4))
        
        return result
    
    def calculate_propaganda_result(self, target_civ: dict) -> dict:
        """Calculate propaganda campaign results"""
        # Base success chance
        success_chance = 0.5
        
        # Reduce chance based on target's happiness and defenses
        happiness_penalty = max(0, (target_civ['happiness'] - 50) * 0.01)
        defense_penalty = min(0.2, target_civ['defenses'] * 0.03)
        success_chance -= (happiness_penalty + defense_penalty)
        
        success = random.random() < success_chance
        discovered = random.random() < 0.35  # 35% chance of being discovered
        
        result = {
            'success': success,
            'discovered': discovered
        }
        
        if success:
            # Calculate soldiers recruited
            max_recruitable = min(target_civ['soldiers'] // 3, 5)
            soldiers_recruited = random.randint(1, max(1, max_recruitable))
            result['soldiers_recruited'] = soldiers_recruited
        
        return result

# ============================================================================
# NATURAL DISASTERS
# ============================================================================

class NaturalDisasterManager:
    def __init__(self, bot):
        self.bot = bot
        self.db = DatabaseManager()
        self.config = GameConfig()
        self.disaster_chance = 0.02  # 2% chance every check
        self.check_interval = 3600   # Check every hour (in seconds)
        
    async def start_disaster_system(self):
        """Start the natural disaster background task"""
        await self.db.initialize()
        while True:
            await asyncio.sleep(self.check_interval)
            await self.check_for_disasters()
            
    async def check_for_disasters(self):
        """Check if any disasters should occur"""
        # Get all active civilizations
        cursor = self.db.conn.cursor()
        cursor.execute('''
            SELECT user_id FROM civilizations 
            WHERE last_active > datetime('now', '-7 days')
        ''')
        
        active_civs = [row[0] for row in cursor.fetchall()]
        
        for user_id in active_civs:
            if random.random() < self.disaster_chance:
                await self.trigger_disaster(user_id)
                
    async def trigger_disaster(self, user_id: str):
        """Trigger a random disaster for a civilization"""
        civ = await self.db.get_civilization(user_id)
        if not civ:
            return
            
        disaster_type = random.choice([
            'earthquake', 'flood', 'drought', 'plague', 
            'wildfire', 'storm', 'locust_swarm'
        ])
        
        disaster_effects = await self.apply_disaster_effects(civ, disaster_type)
        
        if disaster_effects:
            await self.db.update_civilization(user_id, disaster_effects['updates'])
            await self.send_disaster_notification(user_id, disaster_type, disaster_effects)
            
    async def apply_disaster_effects(self, civ: dict, disaster_type: str) -> dict:
        """Apply effects of a specific disaster"""
        updates = {}
        message_data = {}
        
        if disaster_type == 'earthquake':
            # Destroy buildings and kill population
            buildings = civ['buildings'].copy()
            destroyed_buildings = []
            
            for building_type in list(buildings.keys()):
                if random.random() < 0.3:  # 30% chance per building type
                    destroyed = min(buildings[building_type], random.randint(1, 2))
                    buildings[building_type] = max(0, buildings[building_type] - destroyed)
                    if buildings[building_type] == 0:
                        del buildings[building_type]
                    destroyed_buildings.append(f"{destroyed} {building_type}")
                    
            population_loss = random.randint(1, max(1, civ['population'] // 10))
            
            updates.update({
                'buildings': buildings,
                'population': max(1, civ['population'] - population_loss)
            })
            
            message_data = {
                'emoji': '🌍',
                'title': 'Earthquake Devastation',
                'description': f"A massive earthquake has struck **{civ['name']}**!",
                'effects': [
                    f"Population lost: {population_loss}",
                    f"Buildings destroyed: {', '.join(destroyed_buildings) if destroyed_buildings else 'None'}"
                ]
            }
            
        elif disaster_type == 'flood':
            # Destroy food and materials
            food_loss = random.randint(civ['food'] // 4, civ['food'] // 2)
            materials_loss = random.randint(civ['materials'] // 3, civ['materials'] // 2)
            
            updates.update({
                'food': max(0, civ['food'] - food_loss),
                'materials': max(0, civ['materials'] - materials_loss)
            })
            
            message_data = {
                'emoji': '🌊',
                'title': 'Devastating Flood',
                'description': f"Torrential rains have flooded **{civ['name']}**!",
                'effects': [
                    f"Food lost: {food_loss}",
                    f"Materials lost: {materials_loss}"
                ]
            }
            
        elif disaster_type == 'drought':
            # Reduce food and happiness
            food_loss = random.randint(civ['food'] // 3, civ['food'] // 2)
            happiness_loss = random.randint(10, 20)
            
            updates.update({
                'food': max(0, civ['food'] - food_loss),
                'happiness': max(0, civ['happiness'] - happiness_loss)
            })
            
            message_data = {
                'emoji': '🌵',
                'title': 'Severe Drought',
                'description': f"A prolonged drought has withered **{civ['name']}**!",
                'effects': [
                    f"Food lost: {food_loss}",
                    f"Happiness decreased: {happiness_loss}"
                ]
            }
            
        return {
            'updates': updates,
            'message': message_data
        }
        
    async def send_disaster_notification(self, user_id: str, disaster_type: str, disaster_data: dict):
        """Send disaster notification to affected player"""
        message_info = disaster_data['message']
        
        # Send system message
        message_content = f"{message_info['description']}\n\n"
        message_content += "**Effects:**\n"
        for effect in message_info['effects']:
            message_content += f"• {effect}\n"
        message_content += "\nRebuild and recover to restore your civilization's strength!"
        
        await self.db.send_message(
            "System", 
            user_id, 
            f"{message_info['emoji']} {message_info['title']}", 
            message_content
        )

# ============================================================================
# MAIN BOT CLASS
# ============================================================================

class CivilizationBot(commands.Bot):
    def __init__(self):
        # PROPERLY CONFIGURE COMMAND HANDLING
        super().__init__(
            command_prefix='.', 
            help_command=None,
            case_insensitive=True
        )
        self.db = DatabaseManager()
        self.config = GameConfig()
        self.game_logic = GameLogic()
        self.disaster_manager = None
        
        # MANUALLY REGISTER COMMANDS TO ENSURE THEY'RE PROPERLY LOADED
        self.add_command(commands.Command(
            name='start',
            callback=self.start_civilization,
            help='Create a new civilization'
        ))
        self.add_command(commands.Command(
            name='status',
            callback=self.civilization_status,
            help='Display civilization status'
        ))
        self.add_command(commands.Command(
            name='help',
            callback=self.help_command,
            help='Display help information'
        ))
        self.add_command(commands.Command(
            name='gather',
            callback=self.gather_resources,
            help='Gather resources for your civilization'
        ))
        self.add_command(commands.Command(
            name='build',
            callback=self.build_structure,
            help='Construct buildings'
        ))
        self.add_command(commands.Command(
            name='train',
            callback=self.train_soldiers,
            help='Train soldiers for your army'
        ))
        self.add_command(commands.Command(
            name='attack',
            callback=self.attack_player,
            help='Attack another player\'s civilization'
        ))
        self.add_command(commands.Command(
            name='ally',
            callback=self.form_alliance,
            help='Form an alliance with another player'
        ))
        self.add_command(commands.Command(
            name='break',
            callback=self.break_alliance,
            help='Break an alliance with another player'
        ))
        self.add_command(commands.Command(
            name='spy',
            callback=self.spy_on_player,
            help='Gather intelligence on another civilization'
        ))
        self.add_command(commands.Command(
            name='send',
            callback=self.send_message,
            help='Send a message to another player'
        ))
        self.add_command(commands.Command(
            name='mail',
            callback=self.check_mail,
            help='Check inbox and read messages'
        ))
        
    async def on_ready(self):
        logger.info(f'{self.user} has connected to Guilded!')
        await self.db.initialize()
        
        # Log registered commands for debugging
        logger.info(f"Registered commands: {', '.join([cmd.name for cmd in self.commands])}")
        
        # Start natural disaster system
        self.disaster_manager = NaturalDisasterManager(self)
        asyncio.create_task(self.disaster_manager.start_disaster_system())
        
    async def on_message(self, message):
        # Ignore bot messages
        if message.author == self.user:
            return
            
        # Process commands
        await self.process_commands(message)

    # ========================================================================
    # BASIC COMMANDS
    # ========================================================================
    
    async def start_civilization(self, ctx: commands.Context, *, name: str = ""):
        """Create a new civilization"""
        if not name.strip():
            await ctx.reply("❌ Please provide a name for your civilization!\nExample: `.start Roman Empire`")
            return
            
        if len(name) > 50:
            await ctx.reply("❌ Civilization name must be 50 characters or less!")
            return
            
        user_id = str(ctx.author.id)
        
        # Check if user already has a civilization
        existing_civ = await self.db.get_civilization(user_id)
        if existing_civ:
            await ctx.reply(f"❌ You already have a civilization called **{existing_civ['name']}**!\nUse `.status` to view it.")
            return
            
        # Create civilization
        success = await self.db.create_civilization(user_id, name)
        if success:
            embed = guilded.Embed(
                title="🏛️ Civilization Founded!",
                description=f"Welcome to **{name}**!",
                color=0x00ff00
            )
            
            embed.add_field(
                name="Starting Resources",
                value=f"Gold: {self.config.STARTING_STATS['gold']}\n"
                      f"Food: {self.config.STARTING_STATS['food']}\n"
                      f"Materials: {self.config.STARTING_STATS['materials']}\n"
                      f"Population: {self.config.STARTING_STATS['population']}",
                inline=True
            )
            
            embed.add_field(
                name="Military",
                value=f"Soldiers: {self.config.STARTING_STATS['soldiers']}\n"
                      f"Defenses: {self.config.STARTING_STATS['defenses']}",
                inline=True
            )
            
            embed.add_field(
                name="Next Steps",
                value="Use `.gather` to collect resources\nUse `.build` to construct buildings\nUse `.help` for all commands",
                inline=False
            )
            
            await ctx.reply(embed=embed)
        else:
            await ctx.reply("❌ Failed to create civilization. Please try again.")

    async def civilization_status(self, ctx: commands.Context):
        """Display civilization status"""
        user_id = str(ctx.author.id)
        
        civ = await self.db.get_civilization(user_id)
        if not civ:
            await ctx.reply("❌ You don't have a civilization yet! Use `.start <name>` to create one.")
            return
            
        embed = guilded.Embed(
            title=f"🏛️ {civ['name']}",
            description=f"Level {civ['level']} Civilization",
            color=0x0099ff
        )
        
        # Resources
        embed.add_field(
            name="💰 Resources",
            value=f"Gold: {civ['gold']}\n"
                  f"Food: {civ['food']}\n"
                  f"Materials: {civ['materials']}",
            inline=True
        )
        
        # Population & Military
        embed.add_field(
            name="👥 Population & Military",
            value=f"Population: {civ['population']}\n"
                  f"Soldiers: {civ['soldiers']}\n"
                  f"Defenses: {civ['defenses']}",
            inline=True
        )
        
        # Status
        embed.add_field(
            name="📊 Status",
            value=f"Happiness: {civ['happiness']}/100\n"
                  f"Hunger: {civ['hunger']}/100\n"
                  f"Experience: {civ['experience']}/{self.config.BALANCE['experience_per_level']}",
            inline=True
        )
        
        # Buildings
        if civ['buildings']:
            building_list = []
            for building_type, count in civ['buildings'].items():
                building_name = self.config.BUILDINGS.get(building_type, {}).get('name', building_type)
                building_list.append(f"{building_name}: {count}")
            
            embed.add_field(
                name="🏗️ Buildings",
                value="\n".join(building_list),
                inline=False
            )
        else:
            embed.add_field(
                name="🏗️ Buildings",
                value="No buildings constructed yet",
                inline=False
            )
            
        # Combat Record
        embed.add_field(
            name="⚔️ Combat Record",
            value=f"Victories: {civ['wins']}\nDefeats: {civ['losses']}",
            inline=True
        )
        
        await ctx.reply(embed=embed)

    async def help_command(self, ctx: commands.Context):
        """Display help information"""
        embed = guilded.Embed(
            title="🏛️ Civilization Bot Commands",
            description="Build and manage your virtual civilization!",
            color=0x0099ff
        )
        
        embed.add_field(
            name="🏗️ Basic Commands",
            value="`.start <name>` - Create civilization\n"
                  "`.status` - View your civilization\n"
                  "`.help` - Show this help",
            inline=False
        )
        
        embed.add_field(
            name="💰 Economy",
            value="`.gather` - Collect resources\n"
                  "`.build <building>` - Construct buildings\n"
                  "`.buy <item> <amount>` - Purchase items\n"
                  "`.train` - Train soldiers",
            inline=True
        )
        
        embed.add_field(
            name="⚔️ Combat",
            value="`.attack @player` - Attack player\n"
                  "`.civil_war` - Internal conflict",
            inline=True
        )
        
        embed.add_field(
            name="🤝 Diplomacy",
            value="`.ally @player` - Request/accept alliance\n"
                  "`.break @player` - Break alliance",
            inline=True
        )
        
        embed.add_field(
            name="🕵️ Espionage",
            value="`.spy @player` - Gather intelligence\n"
                  "`.sabotage @player` - Damage infrastructure\n"
                  "`.propaganda @player` - Recruit soldiers",
            inline=True
        )
        
        embed.add_field(
            name="📮 Communication",
            value="`.send @player <message>` - Send message\n"
                  "`.mail` - Check inbox",
            inline=True
        )
        
        embed.add_field(
            name="🏗️ Buildings",
            value="house, farm, barracks, wall, market, temple",
            inline=False
        )
        
        await ctx.reply(embed=embed)

    # ========================================================================
    # ECONOMY COMMANDS
    # ========================================================================
    
    async def gather_resources(self, ctx: commands.Context):
        """Gather resources for your civilization"""
        user_id = str(ctx.author.id)
        
        # Check if user has civilization
        user_civ = await self.db.get_civilization(user_id)
        if not user_civ:
            await ctx.reply("❌ You need to create a civilization first! Use `.start <name>`")
            return
            
        # Check cooldown
        cooldown_remaining = await check_cooldown(self.db, user_id, 'gather', self.config.COOLDOWNS['gather'])
        if cooldown_remaining:
            await ctx.reply(f"⏰ You must wait {format_time_remaining(cooldown_remaining)} before gathering again!")
            return
            
        # Generate random resources
        gold_gain = random.randint(10, 25)
        food_gain = random.randint(15, 30)
        materials_gain = random.randint(5, 15)
        
        # Apply level bonuses
        level_bonus = user_civ['level'] * self.config.BALANCE['level_benefits']['resource_bonus']
        gold_gain += level_bonus
        food_gain += level_bonus
        materials_gain += level_bonus
        
        # Update civilization
        new_gold = min(user_civ['gold'] + gold_gain, self.config.BALANCE['max_resources']['gold'])
        new_food = min(user_civ['food'] + food_gain, self.config.BALANCE['max_resources']['food'])
        new_materials = min(user_civ['materials'] + materials_gain, self.config.BALANCE['max_resources']['materials'])
        
        updates = {
            'gold': new_gold,
            'food': new_food,
            'materials': new_materials,
            'experience': user_civ['experience'] + 5
        }
        
        await self.db.update_civilization(user_id, updates)
        await self.db.set_cooldown(user_id, 'gather', self.config.COOLDOWNS['gather'])
        
        embed = guilded.Embed(
            title="💰 Resources Gathered!",
            description=f"**{user_civ['name']}** has collected resources!",
            color=0x00ff00
        )
        
        embed.add_field(
            name="Resources Gained",
            value=f"Gold: +{gold_gain} ({new_gold})\n"
                  f"Food: +{food_gain} ({new_food})\n"
                  f"Materials: +{materials_gain} ({new_materials})",
            inline=False
        )
        
        await ctx.reply(embed=embed)

    async def build_structure(self, ctx: commands.Context, building_type: str = ""):
        """Construct buildings"""
        if not building_type:
            await ctx.reply("❌ Please specify a building type!\nAvailable: house, farm, barracks, wall, market, temple")
            return
            
        building_type = building_type.lower()
        if building_type not in self.config.BUILDINGS:
            await ctx.reply("❌ Invalid building type!\nAvailable: house, farm, barracks, wall, market, temple")
            return
            
        user_id = str(ctx.author.id)
        
        # Check if user has civilization
        user_civ = await self.db.get_civilization(user_id)
        if not user_civ:
            await ctx.reply("❌ You need to create a civilization first! Use `.start <name>`")
            return
            
        # Check cooldown
        cooldown_remaining = await check_cooldown(self.db, user_id, 'build', self.config.COOLDOWNS['build'])
        if cooldown_remaining:
            await ctx.reply(f"⏰ You must wait {format_time_remaining(cooldown_remaining)} before building again!")
            return
            
        building_info = self.config.BUILDINGS[building_type]
        
        # Check if user has enough resources
        materials_needed = building_info['cost']['materials']
        gold_needed = building_info['cost']['gold']
        
        if user_civ['materials'] < materials_needed:
            await ctx.reply(f"❌ You need {materials_needed} materials to build {building_info['name']}! (You have {user_civ['materials']})")
            return
            
        if user_civ['gold'] < gold_needed:
            await ctx.reply(f"❌ You need {gold_needed} gold to build {building_info['name']}! (You have {user_civ['gold']})")
            return
            
        # Build the structure
        buildings = user_civ['buildings'].copy()
        buildings[building_type] = buildings.get(building_type, 0) + 1
        
        updates = {
            'materials': user_civ['materials'] - materials_needed,
            'gold': user_civ['gold'] - gold_needed,
            'buildings': buildings,
            'experience': user_civ['experience'] + 10
        }
        
        # Apply building effects
        if 'population' in building_info['effects']:
            updates['population'] = user_civ['population'] + building_info['effects']['population']
            
        if 'soldiers' in building_info['effects']:
            updates['soldiers'] = user_civ['soldiers'] + building_info['effects']['soldiers']
            
        if 'defenses' in building_info['effects']:
            updates['defenses'] = user_civ['defenses'] + building_info['effects']['defenses']
            
        if 'happiness' in building_info['effects']:
            updates['happiness'] = min(100, user_civ['happiness'] + building_info['effects']['happiness'])
        
        await self.db.update_civilization(user_id, updates)
        await self.db.set_cooldown(user_id, 'build', self.config.COOLDOWNS['build'])
        
        embed = guilded.Embed(
            title="🏗️ Construction Complete!",
            description=f"**{user_civ['name']}** has built a {building_info['name']}!",
            color=0x0099ff
        )
        
        embed.add_field(
            name="Building Effects",
            value=building_info['description'],
            inline=False
        )
        
        embed.add_field(
            name="Resources Spent",
            value=f"Materials: -{materials_needed}\nGold: -{gold_needed}",
            inline=True
        )
        
        embed.add_field(
            name="Total Buildings",
            value=f"{building_info['name']}: {buildings[building_type]}",
            inline=True
        )
        
        await ctx.reply(embed=embed)

    async def train_soldiers(self, ctx: commands.Context):
        """Train soldiers for your army"""
        user_id = str(ctx.author.id)
        
        # Check if user has civilization
        user_civ = await self.db.get_civilization(user_id)
        if not user_civ:
            await ctx.reply("❌ You need to create a civilization first! Use `.start <name>`")
            return
            
        # Check cooldown
        cooldown_remaining = await check_cooldown(self.db, user_id, 'train', self.config.COOLDOWNS['train'])
        if cooldown_remaining:
            await ctx.reply(f"⏰ You must wait {format_time_remaining(cooldown_remaining)} before training more soldiers!")
            return
            
        # Check if they have enough resources and barracks
        barracks_count = user_civ['buildings'].get('barracks', 0)
        if barracks_count == 0:
            await ctx.reply("❌ You need at least one barracks to train soldiers! Use `.build barracks`")
            return
            
        # Training costs
        gold_cost = 25
        food_cost = 15
        
        if user_civ['gold'] < gold_cost:
            await ctx.reply(f"❌ You need {gold_cost} gold to train soldiers! (You have {user_civ['gold']})")
            return
            
        if user_civ['food'] < food_cost:
            await ctx.reply(f"❌ You need {food_cost} food to train soldiers! (You have {user_civ['food']})")
            return
            
        # Calculate soldiers trained (based on barracks)
        soldiers_trained = barracks_count * 2  # 2 soldiers per barracks
        
        # Update civilization
        updates = {
            'gold': user_civ['gold'] - gold_cost,
            'food': user_civ['food'] - food_cost,
            'soldiers': user_civ['soldiers'] + soldiers_trained
        }
        
        await self.db.update_civilization(user_id, updates)
        await self.db.set_cooldown(user_id, 'train', self.config.COOLDOWNS['train'])
        
        embed = guilded.Embed(
            title="⚔️ Military Training Complete!",
            description=f"**{user_civ['name']}** has successfully trained new soldiers!",
            color=0x8b0000
        )
        
        embed.add_field(
            name="Training Results",
            value=f"Soldiers trained: +{soldiers_trained}\n"
                  f"Total army: {user_civ['soldiers'] + soldiers_trained} soldiers\n"
                  f"Training facilities: {barracks_count} barracks",
            inline=False
        )
        
        embed.add_field(
            name="Resources Spent",
            value=f"Gold: -{gold_cost} ({updates['gold']} remaining)\n"
                  f"Food: -{food_cost} ({updates['food']} remaining)",
            inline=False
        )
        
        await ctx.reply(embed=embed)

    # ========================================================================
    # COMBAT COMMANDS
    # ========================================================================
    
    async def attack_player(self, ctx: commands.Context, target_mention: str = ""):
        """Attack another player's civilization"""
        if not target_mention.strip():
            await ctx.reply("❌ Please mention a player to attack!\nExample: `.attack @player`")
            return
            
        user_id = str(ctx.author.id)
        target_id = get_user_from_mention(target_mention)
        
        if not target_id:
            await ctx.reply("❌ Invalid user mention! Please use @username format.")
            return
            
        if target_id == user_id:
            await ctx.reply("❌ You cannot attack yourself!")
            return
            
        # Check if user has civilization
        user_civ = await self.db.get_civilization(user_id)
        if not user_civ:
            await ctx.reply("❌ You need to create a civilization first! Use `.start <name>`")
            return
            
        # Check if target has civilization
        target_civ = await self.db.get_civilization(target_id)
        if not target_civ:
            await ctx.reply("❌ Target player doesn't have a civilization!")
            return
            
        # Check cooldown
        cooldown_remaining = await check_cooldown(self.db, user_id, 'attack', self.config.COOLDOWNS['attack'])
        if cooldown_remaining:
            await ctx.reply(f"⏰ You must wait {format_time_remaining(cooldown_remaining)} before attacking again!")
            return
            
        # Check if they are allies
        allies = await self.db.get_alliances(user_id)
        if target_id in allies:
            await ctx.reply("❌ You cannot attack your ally! That would betray your alliance.")
            return
            
        # Check if attacker has soldiers
        if user_civ['soldiers'] <= 0:
            await ctx.reply("❌ You need soldiers to attack! Train some first with `.train`")
            return
            
        # Calculate combat result
        combat_result = self.game_logic.calculate_combat_result(user_civ, target_civ)
        
        await self.db.set_cooldown(user_id, 'attack', self.config.COOLDOWNS['attack'])
        
        if combat_result['winner'] == 'attacker':
            # Attacker wins
            attacker_updates = {
                'soldiers': max(0, user_civ['soldiers'] - combat_result['attacker_losses']),
                'gold': user_civ['gold'] + combat_result['gold_stolen'],
                'food': user_civ['food'] + combat_result['food_stolen'],
                'wins': user_civ['wins'] + 1,
                'experience': user_civ['experience'] + 20
            }
            
            defender_updates = {
                'soldiers': max(0, target_civ['soldiers'] - combat_result['defender_losses']),
                'gold': max(0, target_civ['gold'] - combat_result['gold_stolen']),
                'food': max(0, target_civ['food'] - combat_result['food_stolen']),
                'losses': target_civ['losses'] + 1,
                'happiness': max(0, target_civ['happiness'] - 10)
            }
            
            await self.db.update_civilization(user_id, attacker_updates)
            await self.db.update_civilization(target_id, defender_updates)
            
            embed = guilded.Embed(
                title="⚔️ Victory!",
                description=f"**{user_civ['name']}** has conquered **{target_civ['name']}**!",
                color=0x00ff00
            )
            
            embed.add_field(
                name="Battle Results",
                value=f"Your losses: {combat_result['attacker_losses']} soldiers\n"
                      f"Enemy losses: {combat_result['defender_losses']} soldiers",
                inline=False
            )
            
            embed.add_field(
                name="Spoils of War",
                value=f"Gold plundered: {combat_result['gold_stolen']}\n"
                      f"Food seized: {combat_result['food_stolen']}",
                inline=False
            )
            
        else:
            # Defender wins
            attacker_updates = {
                'soldiers': max(0, user_civ['soldiers'] - combat_result['attacker_losses']),
                'losses': user_civ['losses'] + 1,
                'happiness': max(0, user_civ['happiness'] - 15)
            }
            
            defender_updates = {
                'soldiers': max(0, target_civ['soldiers'] - combat_result['defender_losses']),
                'wins': target_civ['wins'] + 1,
                'experience': target_civ['experience'] + 15,
                'happiness': min(100, target_civ['happiness'] + 5)
            }
            
            await self.db.update_civilization(user_id, attacker_updates)
            await self.db.update_civilization(target_id, defender_updates)
            
            embed = guilded.Embed(
                title="⚔️ Defeat!",
                description=f"**{target_civ['name']}** has repelled the attack from **{user_civ['name']}**!",
                color=0xff0000
            )
            
            embed.add_field(
                name="Battle Results",
                value=f"Your losses: {combat_result['attacker_losses']} soldiers\n"
                      f"Enemy losses: {combat_result['defender_losses']} soldiers",
                inline=False
            )
            
            embed.add_field(
                name="Consequence",
                value="Your failed attack has demoralized your people!\nHappiness decreased by 15 points.",
                inline=False
            )
        
        # Send notification to target
        try:
            battle_msg = f"⚔️ **{user_civ['name']}** attacked your civilization!\n"
            if combat_result['winner'] == 'attacker':
                battle_msg += f"Result: Defeat - Lost {combat_result['defender_losses']} soldiers and resources"
            else:
                battle_msg += f"Result: Victory - Lost {combat_result['defender_losses']} soldiers but repelled the attack"
            
            await self.db.send_message("System", target_id, "Battle Report", battle_msg)
        except:
            pass
            
        await ctx.reply(embed=embed)

    # ========================================================================
    # ALLIANCE COMMANDS
    # ========================================================================
    
    async def form_alliance(self, ctx: commands.Context, target_mention: str = ""):
        """Form an alliance with another player"""
        if not target_mention.strip():
            await ctx.reply("❌ Please mention a player to ally with!\nExample: `.ally @player`")
            return
            
        user_id = str(ctx.author.id)
        target_id = get_user_from_mention(target_mention)
        
        if not target_id:
            await ctx.reply("❌ Invalid user mention! Please use @username format.")
            return
            
        if target_id == user_id:
            await ctx.reply("❌ You cannot ally with yourself!")
            return
            
        # Check if user has civilization
        user_civ = await self.db.get_civilization(user_id)
        if not user_civ:
            await ctx.reply("❌ You need to create a civilization first! Use `.start <name>`")
            return
            
        # Check if target has civilization
        target_civ = await self.db.get_civilization(target_id)
        if not target_civ:
            await ctx.reply("❌ Target player doesn't have a civilization!")
            return
            
        # Check cooldown
        cooldown_remaining = await check_cooldown(self.db, user_id, 'ally', self.config.COOLDOWNS['ally'])
        if cooldown_remaining:
            await ctx.reply(f"⏰ You must wait {format_time_remaining(cooldown_remaining)} before forming another alliance!")
            return
            
        # Check if already allies
        user_allies = await self.db.get_alliances(user_id)
        if target_id in user_allies:
            await ctx.reply(f"❌ You are already allied with **{target_civ['name']}**!")
            return
            
        # Check if there's a pending request FROM the target TO the user (for accepting)
        existing_request = await self.db.get_alliance_request(target_id, user_id)
        if existing_request:
            # Accept the alliance request
            success = await self.db.create_alliance(user_id, target_id)
            if success:
                await self.db.delete_alliance_request(target_id, user_id)
                await self.db.set_cooldown(user_id, 'ally', self.config.COOLDOWNS['ally'])
                
                embed = guilded.Embed(
                    title="🤝 Alliance Formed!",
                    description=f"**{user_civ['name']}** and **{target_civ['name']}** are now allies!",
                    color=0x00ff00
                )
                
                embed.add_field(
                    name="Alliance Benefits",
                    value="🛡️ Cannot attack each other\n🤝 Shared diplomatic status\n📢 Alliance chat access",
                    inline=False
                )
                
                # Notify both players
                try:
                    await self.db.send_message("System", target_id, "Alliance Accepted", 
                                             f"🤝 **{user_civ['name']}** has accepted your alliance request!")
                except:
                    pass
                    
                await ctx.reply(embed=embed)
                return
            else:
                await ctx.reply("❌ Failed to create alliance. Please try again.")
                return
        
        # Check if user already sent a request to target
        existing_outbound = await self.db.get_alliance_request(user_id, target_id)
        if existing_outbound:
            await ctx.reply(f"❌ You already sent an alliance request to **{target_civ['name']}**! Wait for their response.")
            return
            
        # Check alliance limits
        if len(user_allies) >= self.config.BALANCE['max_alliances']:
            await ctx.reply(f"❌ You can only have {self.config.BALANCE['max_alliances']} alliances at once!")
            return
            
        target_allies = await self.db.get_alliances(target_id)
        if len(target_allies) >= self.config.BALANCE['max_alliances']:
            await ctx.reply(f"❌ **{target_civ['name']}** already has the maximum number of alliances!")
            return
            
        # Send alliance request
        success = await self.db.create_alliance_request(user_id, target_id)
        if success:
            await self.db.set_cooldown(user_id, 'ally', self.config.COOLDOWNS['ally'])
            
            embed = guilded.Embed(
                title="🤝 Alliance Request Sent!",
                description=f"You sent an alliance request to **{target_civ['name']}**!",
                color=0x0099ff
            )
            
            embed.add_field(
                name="Next Steps",
                value=f"**{target_civ['name']}** must type `.ally @{ctx.author.name}` to accept your request.\nRequest expires in 24 hours.",
                inline=False
            )
            
            # Send notification to target
            try:
                await self.db.send_message("System", target_id, "Alliance Request", 
                                         f"🤝 **{user_civ['name']}** wants to form an alliance with you!\nType `.ally @{ctx.author.name}` to accept.")
            except:
                pass
                
            await ctx.reply(embed=embed)
        else:
            await ctx.reply("❌ Failed to send alliance request. You may have already sent one.")

    async def break_alliance(self, ctx: commands.Context, target_mention: str = ""):
        """Break an alliance with another player"""
        if not target_mention.strip():
            await ctx.reply("❌ Please mention a player to break alliance with!\nExample: `.break @player`")
            return
            
        user_id = str(ctx.author.id)
        target_id = get_user_from_mention(target_mention)
        
        if not target_id:
            await ctx.reply("❌ Invalid user mention! Please use @username format.")
            return
            
        if target_id == user_id:
            await ctx.reply("❌ You cannot break alliance with yourself!")
            return
            
        # Check if user has civilization
        user_civ = await self.db.get_civilization(user_id)
        if not user_civ:
            await ctx.reply("❌ You need to create a civilization first! Use `.start <name>`")
            return
            
        # Check if target has civilization
        target_civ = await self.db.get_civilization(target_id)
        if not target_civ:
            await ctx.reply("❌ Target player doesn't have a civilization!")
            return
            
        # Check cooldown
        cooldown_remaining = await check_cooldown(self.db, user_id, 'break', self.config.COOLDOWNS['break'])
        if cooldown_remaining:
            await ctx.reply(f"⏰ You must wait {format_time_remaining(cooldown_remaining)} before breaking another alliance!")
            return
            
        # Check if they are actually allies
        allies = await self.db.get_alliances(user_id)
        if target_id not in allies:
            await ctx.reply(f"❌ You are not allied with **{target_civ['name']}**!")
            return
            
        # Break the alliance
        success = await self.db.break_alliance(user_id, target_id)
        if success:
            await self.db.set_cooldown(user_id, 'break', self.config.COOLDOWNS['break'])
            
            embed = guilded.Embed(
                title="💔 Alliance Broken!",
                description=f"**{user_civ['name']}** has ended their alliance with **{target_civ['name']}**!",
                color=0xff0000
            )
            
            embed.add_field(
                name="Diplomatic Status",
                value="You are no longer allies and can attack each other again.",
                inline=False
            )
            
            # Notify the other player
            try:
                await self.db.send_message("System", target_id, "Alliance Broken", 
                                         f"💔 **{user_civ['name']}** has broken their alliance with you!")
            except:
                pass
                
            await ctx.reply(embed=embed)
        else:
            await ctx.reply("❌ Failed to break alliance. Please try again.")

    # ========================================================================
    # ESPIONAGE COMMANDS
    # ========================================================================
    
    async def spy_on_player(self, ctx: commands.Context, target_mention: str = ""):
        """Gather intelligence on another civilization"""
        if not target_mention.strip():
            await ctx.reply("❌ Please mention a player to spy on!\nExample: `.spy @player`")
            return
            
        user_id = str(ctx.author.id)
        target_id = get_user_from_mention(target_mention)
        
        if not target_id:
            await ctx.reply("❌ Invalid user mention! Please use @username format.")
            return
            
        if target_id == user_id:
            await ctx.reply("❌ You cannot spy on yourself!")
            return
            
        # Check if user has civilization
        user_civ = await self.db.get_civilization(user_id)
        if not user_civ:
            await ctx.reply("❌ You need to create a civilization first! Use `.start <name>`")
            return
            
        # Check if target has civilization
        target_civ = await self.db.get_civilization(target_id)
        if not target_civ:
            await ctx.reply("❌ Target player doesn't have a civilization!")
            return
            
        # Check cooldown
        cooldown_remaining = await check_cooldown(self.db, user_id, 'spy', self.config.COOLDOWNS['spy'])
        if cooldown_remaining:
            await ctx.reply(f"⏰ You must wait {format_time_remaining(cooldown_remaining)} before spying again!")
            return
            
        # Calculate spy result
        spy_result = self.game_logic.calculate_spy_result(target_civ)
        
        await self.db.set_cooldown(user_id, 'spy', self.config.COOLDOWNS['spy'])
        
        if spy_result['success']:
            embed = guilded.Embed(
                title="🕵️ Intelligence Gathered!",
                description=f"Your spies have successfully infiltrated **{target_civ['name']}**!",
                color=0x0099ff
            )
            
            embed.add_field(
                name="💰 Resources",
                value=f"Gold: {target_civ['gold']}\n"
                      f"Food: {target_civ['food']}\n"
                      f"Materials: {target_civ['materials']}",
                inline=True
            )
            
            embed.add_field(
                name="⚔️ Military",
                value=f"Soldiers: {target_civ['soldiers']}\n"
                      f"Defenses: {target_civ['defenses']}",
                inline=True
            )
            
            embed.add_field(
                name="📊 Status",
                value=f"Population: {target_civ['population']}\n"
                      f"Happiness: {target_civ['happiness']}\n"
                      f"Level: {target_civ['level']}",
                inline=True
            )
            
            # Show buildings if any
            if target_civ['buildings']:
                building_list = []
                for building_type, count in target_civ['buildings'].items():
                    building_name = self.config.BUILDINGS.get(building_type, {}).get('name', building_type)
                    building_list.append(f"{building_name}: {count}")
                
                embed.add_field(
                    name="🏗️ Buildings",
                    value="\n".join(building_list),
                    inline=False
                )
        else:
            embed = guilded.Embed(
                title="🕵️ Espionage Failed!",
                description="Your spies were unable to gather useful intelligence.",
                color=0xff0000
            )
            embed.add_field(
                name="Mission Status",
                value="❌ No intelligence gathered\n🛡️ Target security too strong",
                inline=False
            )
        
        # Check if discovered
        if spy_result['discovered']:
            embed.add_field(
                name="⚠️ Mission Compromised",
                value="Your spies were detected! The target has been alerted.",
                inline=False
            )
            
            # Notify the target
            try:
                if spy_result['success']:
                    notification = f"🕵️ **{user_civ['name']}** successfully spied on your civilization!"
                else:
                    notification = f"🚨 **{user_civ['name']}** attempted to spy on your civilization but failed!"
                await self.db.send_message("System", target_id, "Espionage Detected", notification)
            except:
                pass
        else:
            embed.add_field(
                name="🤫 Covert Success",
                value="Your spies completed the mission without detection.",
                inline=False
            )
        
        await ctx.reply(embed=embed)

    # ========================================================================
    # COMMUNICATION COMMANDS
    # ========================================================================
    
    async def send_message(self, ctx: commands.Context, target_mention: str = "", *, message: str = ""):
        """Send a message to another player"""
        if not target_mention.strip() or not message.strip():
            await ctx.reply("❌ Please specify a recipient and message!\nExample: `.send @player Hello there!`")
            return
            
        user_id = str(ctx.author.id)
        target_id = get_user_from_mention(target_mention)
        
        if not target_id:
            await ctx.reply("❌ Invalid user mention! Please use @username format.")
            return
            
        if target_id == user_id:
            await ctx.reply("❌ You cannot send a message to yourself!")
            return
            
        # Check if user has civilization
        user_civ = await self.db.get_civilization(user_id)
        if not user_civ:
            await ctx.reply("❌ You need to create a civilization first! Use `.start <name>`")
            return
            
        # Check if target has civilization
        target_civ = await self.db.get_civilization(target_id)
        if not target_civ:
            await ctx.reply("❌ Target player doesn't have a civilization!")
            return
            
        # Check cooldown
        cooldown_remaining = await check_cooldown(self.db, user_id, 'send', self.config.COOLDOWNS['send'])
        if cooldown_remaining:
            await ctx.reply(f"⏰ You must wait {format_time_remaining(cooldown_remaining)} before sending another message!")
            return
            
        # Send the message
        await self.db.send_message(user_id, target_id, f"Message from {user_civ['name']}", message)
        await self.db.set_cooldown(user_id, 'send', self.config.COOLDOWNS['send'])
        
        embed = guilded.Embed(
            title="📮 Message Sent!",
            description=f"Your message has been delivered to **{target_civ['name']}**!",
            color=0x00ff00
        )
        
        embed.add_field(name="Recipient", value=target_civ['name'], inline=True)
        embed.add_field(name="Message", value=message[:100] + "..." if len(message) > 100 else message, inline=False)
        
        await ctx.reply(embed=embed)

    async def check_mail(self, ctx: commands.Context, action: str = ""):
        """Check inbox and read messages"""
        user_id = str(ctx.author.id)
        
        # Check if user has civilization
        user_civ = await self.db.get_civilization(user_id)
        if not user_civ:
            await ctx.reply("❌ You need to create a civilization first! Use `.start <name>`")
            return
            
        # Check cooldown
        cooldown_remaining = await check_cooldown(self.db, user_id, 'mail', self.config.COOLDOWNS['mail'])
        if cooldown_remaining:
            await ctx.reply(f"⏰ You must wait {format_time_remaining(cooldown_remaining)} before checking mail again!")
            return
            
        await self.db.set_cooldown(user_id, 'mail', self.config.COOLDOWNS['mail'])
        
        if action.strip() and action.lower() == 'read':
            # Show all messages (read and unread)
            messages = await self.db.get_messages(user_id, unread_only=False)
        else:
            # Show only unread messages
            messages = await self.db.get_messages(user_id, unread_only=True)
        
        embed = guilded.Embed(
            title="📬 Mailbox",
            description=f"Mail for **{user_civ['name']}**",
            color=0x0099ff
        )
        
        if messages:
            message_list = []
            for msg in messages:
                status = "📩" if not msg['read'] else "📧"
                sender = "System" if msg['sender_id'] == "System" else f"Player {msg['sender_id']}"
                message_list.append(f"{status} **{msg['subject']}**\nFrom: {sender}\n{msg['content'][:80]}{'...' if len(msg['content']) > 80 else ''}\n")
            
            embed.add_field(
                name="Messages",
                value="\n\n".join(message_list),
                inline=False
            )
            
            # Mark messages as read if they were viewing unread messages
            if not action.strip() or action.lower() != 'read':
                for msg in messages:
                    if not msg['read']:
                        await self.db.mark_message_read(msg['id'])
                        
        else:
            if action.strip() and action.lower() == 'read':
                embed.add_field(
                    name="All Messages", 
                    value="No messages in your mailbox.",
                    inline=False
                )
            else:
                embed.add_field(
                    name="New Messages", 
                    value="No new messages.\nUse `.mail read` to see all messages.",
                    inline=False
                )
        
        embed.set_footer(text="Use .mail to read messages")
        
        await ctx.reply(embed=embed)

# ============================================================================
# BOT INITIALIZATION
# ============================================================================

# Initialize bot
bot = CivilizationBot()

async def main():
    # Get bot token from environment
    token = os.getenv('GUILDED_BOT_TOKEN')
    
    if not token:
        logger.error('Please set GUILDED_BOT_TOKEN environment variable')
        return
        
    # Start the web server for Render compatibility
    asyncio.create_task(start_web_server())
        
    try:
        await bot.start(token)
    except Exception as e:
        logger.error(f'Failed to start bot: {e}')
    finally:
        await bot.db.close()

if __name__ == '__main__':
    asyncio.run(main())
