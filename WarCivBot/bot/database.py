import sqlite3
import json
import threading
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
import time

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path: str = 'nationbot.db'):
        self.db_path = db_path
        self.local = threading.local()
        self.init_database()
        self.setup_cleanup_scheduler()

    def setup_cleanup_scheduler(self):
        """Schedule daily cleanup of expired requests"""
        def cleanup_task():
            logger.info("Running scheduled cleanup of expired requests...")
            self.cleanup_expired_requests()
            # Reschedule after 24 hours
            threading.Timer(86400, cleanup_task).start()
        
        # First run in 1 minute then every 24 hours
        threading.Timer(60, cleanup_task).start()
        logger.info("Scheduled cleanup task initialized")

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
                resources TEXT NOT NULL,
                population TEXT NOT NULL,
                military TEXT NOT NULL,
                territory TEXT NOT NULL,
                hyper_items TEXT NOT NULL DEFAULT '[]',
                bonuses TEXT NOT NULL DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Cooldowns table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cooldowns (
                user_id TEXT,
                command TEXT,
                last_used_at TIMESTAMP,
                PRIMARY KEY (user_id, command)
            )
        ''')
        
        # Alliances table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS alliances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                leader_id TEXT NOT NULL,
                members TEXT NOT NULL DEFAULT '[]',
                join_requests TEXT NOT NULL DEFAULT '[]',
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
                result TEXT
            )
        ''')
        
        # Messages table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id TEXT NOT NULL,
                recipient_id TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP DEFAULT (datetime('now', '+1 day'))
            )
        ''')
        
        # Trade requests table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trade_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id TEXT NOT NULL,
                recipient_id TEXT NOT NULL,
                offer TEXT NOT NULL,
                request TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP DEFAULT (datetime('now', '+1 day'))
            )
        ''')
        
        # Events table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                effects TEXT NOT NULL DEFAULT '{}',
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
        
        # Alliance invitation table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS alliance_invitations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alliance_id INTEGER NOT NULL,
                sender_id TEXT NOT NULL,
                recipient_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP DEFAULT (datetime('now', '+1 day'))
            )
        ''')
        
        # Create indexes for faster lookups
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_expires ON messages(expires_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_trade_expires ON trade_requests(expires_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_invites_expires ON alliance_invitations(expires_at)')
        
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
            
        except sqlite3.IntegrityError:
            logger.warning(f"User {user_id} already has a civilization")
            return False
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

    def get_command_cooldown(self, user_id: str, command: str) -> Optional[datetime]:
        """Get the last used time for a command, or None if no cooldown"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT last_used_at FROM cooldowns 
                WHERE user_id = ? AND command = ?
            ''', (user_id, command))
            
            row = cursor.fetchone()
            if row:
                return datetime.fromisoformat(row['last_used_at'])
            return None
            
        except Exception as e:
            logger.error(f"Error getting command cooldown: {e}")
            return None

    def set_command_cooldown(self, user_id: str, command: str, timestamp: datetime) -> bool:
        """Set the last used time for a command"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO cooldowns (user_id, command, last_used_at)
                VALUES (?, ?, ?)
            ''', (user_id, command, timestamp.isoformat()))
            
            conn.commit()
            return True
            
        except Exception as e:
            logger.error(f"Error setting command cooldown: {e}")
            return False

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

    def create_alliance(self, name: str, leader_id: str, description: str = "") -> bool:
        """Create a new alliance"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO alliances (name, leader_id, members, description)
                VALUES (?, ?, ?, ?)
            ''', (name, leader_id, json.dumps([leader_id]), description))
            
            conn.commit()
            logger.info(f"Created alliance '{name}' led by {leader_id}")
            return True
            
        except sqlite3.IntegrityError:
            logger.warning(f"Alliance name '{name}' already exists")
            return False
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
            logger.debug(f"Logged event: {title} for user {user_id}")
            
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

    # NEW METHODS FOR REQUESTS AND MESSAGES =====================================
    def create_trade_request(self, sender_id: str, recipient_id: str, offer: Dict, request: Dict) -> bool:
        """Create a new trade request"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO trade_requests (sender_id, recipient_id, offer, request)
                VALUES (?, ?, ?, ?)
            ''', (sender_id, recipient_id, json.dumps(offer), json.dumps(request)))
            conn.commit()
            logger.info(f"Trade request created from {sender_id} to {recipient_id}")
            return True
        except Exception as e:
            logger.error(f"Error creating trade request: {e}")
            return False

    def get_trade_requests(self, user_id: str) -> List[Dict]:
        """Get all active trade requests for a user"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT t.*, c.name as sender_name 
                FROM trade_requests t
                JOIN civilizations c ON t.sender_id = c.user_id
                WHERE recipient_id = ? AND expires_at > CURRENT_TIMESTAMP
            ''', (user_id,))
            rows = cursor.fetchall()
            requests = []
            for row in rows:
                req = dict(row)
                req['offer'] = json.loads(req['offer'])
                req['request'] = json.loads(req['request'])
                requests.append(req)
            return requests
        except Exception as e:
            logger.error(f"Error getting trade requests: {e}")
            return []

    def get_trade_request_by_id(self, request_id: int) -> Optional[Dict]:
        """Get a specific trade request by ID"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM trade_requests 
                WHERE id = ? AND expires_at > CURRENT_TIMESTAMP
            ''', (request_id,))
            row = cursor.fetchone()
            if row:
                req = dict(row)
                req['offer'] = json.loads(req['offer'])
                req['request'] = json.loads(req['request'])
                return req
            return None
        except Exception as e:
            logger.error(f"Error getting trade request by ID: {e}")
            return None

    def delete_trade_request(self, request_id: int) -> bool:
        """Delete a trade request"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM trade_requests WHERE id = ?', (request_id,))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting trade request: {e}")
            return False

    def create_alliance_invite(self, alliance_id: int, sender_id: str, recipient_id: str) -> bool:
        """Invite a user to an alliance"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO alliance_invitations (alliance_id, sender_id, recipient_id)
                VALUES (?, ?, ?)
            ''', (alliance_id, sender_id, recipient_id))
            conn.commit()
            logger.info(f"Alliance invite created: alliance={alliance_id} to {recipient_id}")
            return True
        except Exception as e:
            logger.error(f"Error creating alliance invite: {e}")
            return False

    def get_alliance_invites(self, user_id: str) -> List[Dict]:
        """Get active alliance invites for a user"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT ai.*, a.name as alliance_name 
                FROM alliance_invitations ai
                JOIN alliances a ON ai.alliance_id = a.id
                WHERE recipient_id = ? AND expires_at > CURRENT_TIMESTAMP
            ''', (user_id,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting alliance invites: {e}")
            return []

    def get_alliance_invite_by_id(self, invite_id: int) -> Optional[Dict]:
        """Get a specific alliance invite by ID"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT ai.*, a.name as alliance_name 
                FROM alliance_invitations ai
                JOIN alliances a ON ai.alliance_id = a.id
                WHERE ai.id = ? AND expires_at > CURRENT_TIMESTAMP
            ''', (invite_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting alliance invite by ID: {e}")
            return None

    def delete_alliance_invite(self, invite_id: int) -> bool:
        """Delete an alliance invitation"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM alliance_invitations WHERE id = ?', (invite_id,))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting alliance invite: {e}")
            return False

    def send_message(self, sender_id: str, recipient_id: str, message: str) -> bool:
        """Send a message between users"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO messages (sender_id, recipient_id, message)
                VALUES (?, ?, ?)
            ''', (sender_id, recipient_id, message))
            conn.commit()
            logger.info(f"Message sent from {sender_id} to {recipient_id}")
            return True
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return False

    def get_messages(self, user_id: str) -> List[Dict]:
        """Get active messages for a user"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT m.*, c.name as sender_name 
                FROM messages m
                JOIN civilizations c ON m.sender_id = c.user_id
                WHERE recipient_id = ? AND expires_at > CURRENT_TIMESTAMP
            ''', (user_id,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting messages: {e}")
            return []

    def delete_message(self, message_id: int) -> bool:
        """Delete a message"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM messages WHERE id = ?', (message_id,))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
            return False

    # ALLIANCE MANAGEMENT ======================================================
    def get_alliance(self, alliance_id: int) -> Optional[Dict]:
        """Get alliance data by ID"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM alliances WHERE id = ?', (alliance_id,))
            row = cursor.fetchone()
            if row:
                alliance = dict(row)
                alliance['members'] = json.loads(alliance['members'])
                alliance['join_requests'] = json.loads(alliance['join_requests'])
                return alliance
            return None
        except Exception as e:
            logger.error(f"Error getting alliance: {e}")
            return None

    def add_alliance_member(self, alliance_id: int, user_id: str) -> bool:
        """Add member to alliance"""
        try:
            alliance = self.get_alliance(alliance_id)
            if not alliance:
                return False
            
            if user_id in alliance['members']:
                return True  # Already a member
            
            members = alliance['members'] + [user_id]
            join_requests = [uid for uid in alliance['join_requests'] if uid != user_id]
            
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE alliances 
                SET members = ?, join_requests = ?
                WHERE id = ?
            ''', (json.dumps(members), json.dumps(join_requests), alliance_id))
            
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding alliance member: {e}")
            return False

    # CLEANUP METHOD ============================================================
    def cleanup_expired_requests(self):
        """Automatically remove expired requests (runs daily)"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Delete expired trade requests
            cursor.execute('DELETE FROM trade_requests WHERE expires_at <= CURRENT_TIMESTAMP')
            trade_count = cursor.rowcount
            
            # Delete expired alliance invites
            cursor.execute('DELETE FROM alliance_invitations WHERE expires_at <= CURRENT_TIMESTAMP')
            invite_count = cursor.rowcount
            
            # Delete expired messages
            cursor.execute('DELETE FROM messages WHERE expires_at <= CURRENT_TIMESTAMP')
            message_count = cursor.rowcount
            
            conn.commit()
            logger.info(f"Cleaned up expired requests: "
                       f"{trade_count} trades, {invite_count} invites, "
                       f"{message_count} messages removed")
            return True
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            return False

    # UTILITY METHODS ==========================================================
    def close_connections(self):
        """Close all database connections (for shutdown)"""
        if hasattr(self.local, 'connection'):
            self.local.connection.close()
            del self.local.connection

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Example usage
if __name__ == "__main__":
    db = Database()
    
    # Create test civilization
    db.create_civilization("user123", "Athena Republic", 
                          bonus_resources={"gold": 100, "population": 50})
    
    # Create trade request
    db.create_trade_request(
        sender_id="user123",
        recipient_id="user456",
        offer={"gold": 100, "wood": 200},
        request={"stone": 150}
    )
    
    # Create alliance invite
    db.create_alliance_invite(
        alliance_id=1,
        sender_id="user789",
        recipient_id="user123"
    )
    
    # Send message
    db.send_message(
        sender_id="user456",
        recipient_id="user123",
        message="Let's form an alliance against Sparta!"
    )
    
    # Retrieve data
    print("Trade requests for user123:", db.get_trade_requests("user123"))
    print("Alliance invites for user123:", db.get_alliance_invites("user123"))
    print("Messages for user123:", db.get_messages("user123"))
    
    # Simulate cleanup after expiration
    time.sleep(2)  # Allow time for initial inserts
    print("Running cleanup...")
    db.cleanup_expired_requests()
    
    # Close connections
    db.close_connections()
