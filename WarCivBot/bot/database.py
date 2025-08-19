"""
Database module for WarBot
Handles SQLite database operations, civilization storage, and save states
"""

import sqlite3
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path: str = "warbot.db"):
        """Initialize database connection"""
        self.db_path = db_path
        self.connection = None
        self.init_database()

    def get_connection(self):
        """Get or create database connection"""
        if not hasattr(self, 'connection') or self.connection is None:
            self.connection = sqlite3.connect(self.db_path)
            self.connection.row_factory = sqlite3.Row
        return self.connection

    def init_database(self):
        """Initialize database tables"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            # Civilizations table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS civilizations (
                    user_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    ideology TEXT,
                    resources TEXT NOT NULL,  -- JSON object
                    population TEXT NOT NULL, -- JSON object 
                    military TEXT NOT NULL,   -- JSON object
                    territory TEXT NOT NULL,  -- JSON object
                    hyper_items TEXT NOT NULL DEFAULT '[]',  -- JSON array
                    bonuses TEXT NOT NULL DEFAULT '{}',      -- JSON object
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Save slots table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS civilization_saves (
                    user_id TEXT,
                    slot INTEGER,
                    save_data TEXT NOT NULL,      -- Full JSON civilization state
                    save_name TEXT,               -- Optional save name
                    saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, slot)
                )
            """)

            # Cooldowns table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cooldowns (
                    user_id TEXT,
                    command TEXT,
                    expires_at TIMESTAMP,
                    PRIMARY KEY (user_id, command)
                )
            """)

            # Alliances table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alliances (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    leader_id TEXT NOT NULL,
                    members TEXT NOT NULL DEFAULT '[]',  -- JSON array
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Wars table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS wars (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    attacker_id TEXT NOT NULL,
                    defender_id TEXT NOT NULL,
                    war_type TEXT NOT NULL,
                    declared_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ended_at TIMESTAMP,
                    result TEXT  -- 'attacker_win', 'defender_win', 'ongoing'
                )
            """)

            # Events table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,       -- NULL for global events
                    event_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    effects TEXT NOT NULL DEFAULT '{}',  -- JSON object
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.commit()
            logger.info("Database initialized successfully")

        except Exception as e:
            logger.error(f"Database initialization error: {e}")
            raise

    def create_civilization(self, user_id: str, name: str, bonus_resources: Dict = None, 
                          bonuses: Dict = None, hyper_item: str = None) -> bool:
        """Create a new civilization"""
        try:
            # Default values
            default_resources = {"gold": 100, "food": 100, "stone": 50, "wood": 50}
            default_population = {"citizens": 50, "happiness": 100, "hunger": 0}
            default_military = {"soldiers": 0, "spies": 0, "tech_level": 1}
            default_territory = {"land_size": 1000}

            # Apply bonus resources
            if bonus_resources:
                for resource, amount in bonus_resources.items():
                    if resource in default_resources:
                        default_resources[resource] += amount

            # Initialize hyper items
            hyper_items = [hyper_item] if hyper_item else []

            # Create civilization
            conn = self.get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO civilizations 
                (user_id, name, resources, population, military, territory, hyper_items, bonuses)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                name,
                json.dumps(default_resources),
                json.dumps(default_population),
                json.dumps(default_military),
                json.dumps(default_territory),
                json.dumps(hyper_items),
                json.dumps(bonuses or {})
            ))

            conn.commit()
            logger.info(f"Created civilization '{name}' for user {user_id}")
            return True

        except Exception as e:
            logger.error(f"Error creating civilization: {e}")
            return False

    def get_civilization(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get civilization data"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM civilizations WHERE user_id = ?", (user_id,))
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
            logger.error(f"Error getting civilization data: {e}")
            return None

    def update_civilization(self, user_id: str, updates: Dict[str, Any]) -> bool:
        """Update civilization data"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            # Build update query
            fields = []
            values = []
            for key, value in updates.items():
                if key in ['resources', 'population', 'military', 'territory', 'hyper_items', 'bonuses']:
                    fields.append(f"{key} = ?")
                    values.append(json.dumps(value))
                elif key in ['ideology', 'name']:
                    fields.append(f"{key} = ?")
                    values.append(value)

            if not fields:
                return False

            # Add timestamp and user_id
            fields.append("last_active = CURRENT_TIMESTAMP")
            values.append(user_id)

            query = f"UPDATE civilizations SET {', '.join(fields)} WHERE user_id = ?"
            cursor.execute(query, values)
            conn.commit()

            return True

        except Exception as e:
            logger.error(f"Error updating civilization: {e}")
            return False

    # Save slot methods
    def save_civilization_state(self, user_id: str, slot: int, save_name: str, data: str) -> bool:
        """Save civilization state to a slot"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT OR REPLACE INTO civilization_saves 
                (user_id, slot, save_name, save_data, saved_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            """, (user_id, slot, save_name, data))

            conn.commit()
            return True

        except Exception as e:
            logger.error(f"Error saving civilization state: {e}")
            return False

    def get_civilization_save(self, user_id: str, slot: int) -> Optional[Dict]:
        """Get civilization save data"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT save_data, save_name, saved_at 
                FROM civilization_saves
                WHERE user_id = ? AND slot = ?
            """, (user_id, slot))

            row = cursor.fetchone()
            if not row:
                return None

            return {
                "data": json.loads(row["save_data"]),
                "name": row["save_name"],
                "saved_at": row["saved_at"]
            }

        except Exception as e:
            logger.error(f"Error getting save data: {e}")
            return None

    def list_civilization_saves(self, user_id: str) -> List[Dict]:
        """List all saves for a user"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT slot, save_name, saved_at 
                FROM civilization_saves
                WHERE user_id = ?
                ORDER BY slot
            """, (user_id,))

            saves = []
            for row in cursor.fetchall():
                saves.append({
                    "slot": row["slot"],
                    "name": row["save_name"],
                    "saved_at": row["saved_at"]
                })

            return saves

        except Exception as e:
            logger.error(f"Error listing saves: {e}")
            return []

    def delete_civilization_save(self, user_id: str, slot: int) -> bool:
        """Delete a save slot"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                DELETE FROM civilization_saves
                WHERE user_id = ? AND slot = ?
            """, (user_id, slot))

            conn.commit()
            return True

        except Exception as e:
            logger.error(f"Error deleting save: {e}")
            return False

    # Cooldown methods
    def set_cooldown(self, user_id: str, command: str, duration_minutes: int) -> bool:
        """Set command cooldown"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT OR REPLACE INTO cooldowns (user_id, command, expires_at)
                VALUES (?, ?, datetime('now', '+' || ? || ' minutes'))
            """, (user_id, command, duration_minutes))

            conn.commit()
            return True

        except Exception as e:
            logger.error(f"Error setting cooldown: {e}")
            return False

    def check_cooldown(self, user_id: str, command: str) -> Optional[datetime]:
        """Check if command is on cooldown"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT expires_at FROM cooldowns 
                WHERE user_id = ? AND command = ? AND expires_at > datetime('now')
            """, (user_id, command))

            row = cursor.fetchone()
            return datetime.fromisoformat(row["expires_at"]) if row else None

        except Exception as e:
            logger.error(f"Error checking cooldown: {e}")
            return None

    def clear_expired_cooldowns(self) -> None:
        """Clear expired cooldowns"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            cursor.execute("DELETE FROM cooldowns WHERE expires_at <= datetime('now')")
            conn.commit()

        except Exception as e:
            logger.error(f"Error clearing cooldowns: {e}")

    def close(self):
        """Close database connection"""
        if self.connection:
            self.connection.close()
            self.connection = None
