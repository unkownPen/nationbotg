import sqlite3
import json
import threading
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path: str = 'warbot.db'):
        self.db_path = db_path
        self.local = threading.local()
        self.init_database()

    def get_connection(self):
        """Get thread-local database connection"""
        if not hasattr(self.local, 'connection'):
            self.local.connection = sqlite3.connect(self.db_path)
            self.local.connection.row_factory = sqlite3.Row
        return self.local.connection

    def init_database(self):
        """Initialize database tables"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Civilizations table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS civilizations (
                user_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                ideology TEXT,
                resources TEXT NOT NULL,  -- JSON
                population TEXT NOT NULL,  -- JSON
                military TEXT NOT NULL,  -- JSON
                territory TEXT NOT NULL,  -- JSON
                hyper_items TEXT NOT NULL DEFAULT '[]',  -- JSON array
                bonuses TEXT NOT NULL DEFAULT '{}',  -- JSON
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                leader_id TEXT NOT NULL,
                members TEXT NOT NULL DEFAULT '[]',  -- JSON array
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Wars table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS wars (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attacker_id TEXT NOT NULL,
                defender_id TEXT NOT NULL,
                war_type TEXT NOT NULL,
                declared_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ended_at TIMESTAMP,
                result TEXT  -- 'attacker_win', 'defender_win', 'ongoing'
            )
        ''')
        
        # Messages table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id TEXT NOT NULL,
                recipient_id TEXT NOT NULL,
                message TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Events table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,  -- NULL for global events
                event_type TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                effects TEXT NOT NULL DEFAULT '{}',  -- JSON
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Global settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS global_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')
        
        conn.commit()
        logger.info("Database initialized successfully")

    def create_civilization(self, user_id: str, name: str, bonus_resources: Dict = None, bonuses: Dict = None, hyper_item: str = None) -> bool:
        """Create a new civilization"""
        try:
            # Default starting values
            default_resources = {
                "gold": 500,
                "food": 300,
                "stone": 100,
                "wood": 100
            }
            
            # Apply bonus resources
            if bonus_resources:
                for resource, amount in bonus_resources.items():
                    if resource in default_resources:
                        default_resources[resource] += amount
                    elif resource == 'population':
                        # Will be handled in population section
                        pass
            
            default_population = {
                "citizens": 100 + bonus_resources.get('population', 0),
                "happiness": 50 + bonus_resources.get('happiness', 0),
                "hunger": 0
            }
            
            default_military = {
                "soldiers": 10,
                "spies": 2,
                "tech_level": 1
            }
            
            default_territory = {
                "land_size": 1000
            }
            
            hyper_items = [hyper_item] if hyper_item else []
            bonuses = bonuses or {}
            
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO civilizations 
                (user_id, name, resources, population, military, territory, hyper_items, bonuses)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id, name,
                json.dumps(default_resources),
                json.dumps(default_population),
                json.dumps(default_military),
                json.dumps(default_territory),
                json.dumps(hyper_items),
                json.dumps(bonuses)
            ))
            
            conn.commit()
            logger.info(f"Created civilization '{name}' for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating civilization: {e}")
            return False

    def get_civilization(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get civilization data for a user"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM civilizations WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            # Convert row to dict and parse JSON fields
            civ = dict(row)
            civ['resources'] = json.loads(civ['resources'])
            civ['population'] = json.loads(civ['population'])
            civ['military'] = json.loads(civ['military'])
            civ['territory'] = json.loads(civ['territory'])
            civ['hyper_items'] = json.loads(civ['hyper_items'])
            civ['bonuses'] = json.loads(civ['bonuses'])
            
            return civ
            
        except Exception as e:
            logger.error(f"Error getting civilization for user {user_id}: {e}")
            return None

    def update_civilization(self, user_id: str, updates: Dict[str, Any]) -> bool:
        """Update civilization data"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Build update query dynamically
            set_clauses = []
            values = []
            
            for field, value in updates.items():
                if field in ['resources', 'population', 'military', 'territory', 'hyper_items', 'bonuses']:
                    set_clauses.append(f"{field} = ?")
                    values.append(json.dumps(value))
                else:
                    set_clauses.append(f"{field} = ?")
                    values.append(value)
            
            # Add last_active update
            set_clauses.append("last_active = CURRENT_TIMESTAMP")
            values.append(user_id)
            
            query = f"UPDATE civilizations SET {', '.join(set_clauses)} WHERE user_id = ?"
            cursor.execute(query, values)
            
            conn.commit()
            return True
            
        except Exception as e:
            logger.error(f"Error updating civilization for user {user_id}: {e}")
            return False

    def set_cooldown(self, user_id: str, command: str, duration_minutes: int) -> bool:
        """Set a cooldown for a user command"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            expires_at = datetime.now() + timedelta(minutes=duration_minutes)
            
            cursor.execute('''
                INSERT OR REPLACE INTO cooldowns (user_id, command, expires_at)
                VALUES (?, ?, ?)
            ''', (user_id, command, expires_at))
            
            conn.commit()
            return True
            
        except Exception as e:
            logger.error(f"Error setting cooldown: {e}")
            return False

    def check_cooldown(self, user_id: str, command: str) -> Optional[datetime]:
        """Check if user has cooldown for command. Returns expiry time if on cooldown, None otherwise"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT expires_at FROM cooldowns 
                WHERE user_id = ? AND command = ? AND expires_at > CURRENT_TIMESTAMP
            ''', (user_id, command))
            
            row = cursor.fetchone()
            if row:
                return datetime.fromisoformat(row['expires_at'])
            return None
            
        except Exception as e:
            logger.error(f"Error checking cooldown: {e}")
            return None

    def clear_expired_cooldowns(self):
        """Clear expired cooldowns from database"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM cooldowns WHERE expires_at <= CURRENT_TIMESTAMP')
            conn.commit()
            
        except Exception as e:
            logger.error(f"Error clearing expired cooldowns: {e}")

    def get_all_civilizations(self) -> List[Dict[str, Any]]:
        """Get all civilizations for leaderboards"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM civilizations ORDER BY last_active DESC')
            rows = cursor.fetchall()
            
            civilizations = []
            for row in rows:
                civ = dict(row)
                civ['resources'] = json.loads(civ['resources'])
                civ['population'] = json.loads(civ['population'])
                civ['military'] = json.loads(civ['military'])
                civ['territory'] = json.loads(civ['territory'])
                civ['hyper_items'] = json.loads(civ['hyper_items'])
                civ['bonuses'] = json.loads(civ['bonuses'])
                civilizations.append(civ)
            
            return civilizations
            
        except Exception as e:
            logger.error(f"Error getting all civilizations: {e}")
            return []

    def create_alliance(self, name: str, leader_id: str) -> bool:
        """Create a new alliance"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO alliances (name, leader_id, members)
                VALUES (?, ?, ?)
            ''', (name, leader_id, json.dumps([leader_id])))
            
            conn.commit()
            return True
            
        except Exception as e:
            logger.error(f"Error creating alliance: {e}")
            return False

    def log_event(self, user_id: str, event_type: str, title: str, description: str, effects: Dict = None):
        """Log an event to the database"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO events (user_id, event_type, title, description, effects)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, event_type, title, description, json.dumps(effects or {})))
            
            conn.commit()
            
        except Exception as e:
            logger.error(f"Error logging event: {e}")

    def get_recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent events for dashboard"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT e.*, c.name as civ_name 
                FROM events e 
                LEFT JOIN civilizations c ON e.user_id = c.user_id 
                ORDER BY e.timestamp DESC 
                LIMIT ?
            ''', (limit,))
            
            rows = cursor.fetchall()
            events = []
            for row in rows:
                event = dict(row)
                event['effects'] = json.loads(event['effects'])
                events.append(event)
            
            return events
            
        except Exception as e:
            logger.error(f"Error getting recent events: {e}")
            return []
        except Exception as e:
            logger.error(f"Error getting recent events: {e}")
            return []
