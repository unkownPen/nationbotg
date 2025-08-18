# database.py  (COMPLETE – 100 % compatible with the cog you posted)
import sqlite3
import random
import json
import threading
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class Database:
    """Thread-safe SQLite wrapper for NationBot."""

    def __init__(self, db_path: str = "nationbot.db"):
        self.db_path = db_path
        self.local = threading.local()
        self.init_database()
        self.setup_cleanup_scheduler()

    # ------------------------------------------------------------------ #
    # Connection helpers
    # ------------------------------------------------------------------ #
    def get_connection(self) -> sqlite3.Connection:
        if not hasattr(self.local, "connection"):
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self.local.connection = conn
        return self.local.connection

    # ------------------------------------------------------------------ #
    # Database bootstrap
    # ------------------------------------------------------------------ #
    def init_database(self) -> None:
        conn = self.get_connection()
        cur = conn.cursor()

        cur.executescript(
            """
            -- Core
            CREATE TABLE IF NOT EXISTS civilizations (
                user_id       TEXT PRIMARY KEY,
                name          TEXT NOT NULL,
                ideology      TEXT,
                resources     TEXT NOT NULL,
                population    TEXT NOT NULL,
                military      TEXT NOT NULL,
                territory     TEXT NOT NULL,
                hyper_items   TEXT NOT NULL DEFAULT '[]',
                bonuses       TEXT NOT NULL DEFAULT '{}',
                selected_cards TEXT NOT NULL DEFAULT '[]',
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS cooldowns (
                user_id      TEXT,
                command      TEXT,
                last_used_at TIMESTAMP,
                PRIMARY KEY (user_id, command)
            );

            CREATE TABLE IF NOT EXISTS cards (
                user_id         TEXT,
                tech_level      INTEGER,
                available_cards TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'pending',
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, tech_level)
            );

            CREATE TABLE IF NOT EXISTS alliances (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT NOT NULL UNIQUE,
                description   TEXT,
                leader_id     TEXT NOT NULL,
                members       TEXT NOT NULL DEFAULT '[]',
                join_requests TEXT NOT NULL DEFAULT '[]',
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS alliance_invitations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                alliance_id INTEGER NOT NULL,
                sender_id   TEXT NOT NULL,
                recipient_id TEXT NOT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at  TIMESTAMP DEFAULT (datetime('now', '+1 day'))
            );

            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id   TEXT NOT NULL,
                recipient_id TEXT NOT NULL,
                message     TEXT NOT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at  TIMESTAMP DEFAULT (datetime('now', '+1 day'))
            );

            CREATE TABLE IF NOT EXISTS trade_requests (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id    TEXT NOT NULL,
                recipient_id TEXT NOT NULL,
                offer        TEXT NOT NULL,
                request      TEXT NOT NULL,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at   TIMESTAMP DEFAULT (datetime('now', '+1 day'))
            );

            CREATE TABLE IF NOT EXISTS events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT,
                event_type  TEXT NOT NULL,
                title       TEXT NOT NULL,
                description TEXT NOT NULL,
                effects     TEXT NOT NULL DEFAULT '{}',
                timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS global_settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            -- Military tables
            CREATE TABLE IF NOT EXISTS wars (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                attacker_id TEXT NOT NULL,
                defender_id TEXT NOT NULL,
                war_type    TEXT NOT NULL,
                result      TEXT NOT NULL DEFAULT 'ongoing',
                declared_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ended_at    TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS peace_offers (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                offerer_id   TEXT NOT NULL,
                receiver_id  TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'pending',
                offered_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                responded_at TIMESTAMP
            );

            -- Indexes
            CREATE INDEX IF NOT EXISTS idx_messages_expires  ON messages(expires_at);
            CREATE INDEX IF NOT EXISTS idx_trade_expires     ON trade_requests(expires_at);
            CREATE INDEX IF NOT EXISTS idx_invites_expires   ON alliance_invitations(expires_at);
            CREATE INDEX IF NOT EXISTS idx_wars_ongoing      ON wars(result) WHERE result = 'ongoing';
            CREATE INDEX IF NOT EXISTS idx_peace_pending     ON peace_offers(status) WHERE status = 'pending';
            """
        )
        conn.commit()
        logger.info("Database initialized.")

    # ------------------------------------------------------------------ #
    # Cleanup
    # ------------------------------------------------------------------ #
    def setup_cleanup_scheduler(self) -> None:
        def task() -> None:
            self.cleanup_expired_requests()
            threading.Timer(86400, task).start()

        threading.Timer(60, task).start()

    def cleanup_expired_requests(self) -> None:
        conn = self.get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM trade_requests     WHERE expires_at <= CURRENT_TIMESTAMP")
        tr = cur.rowcount
        cur.execute("DELETE FROM alliance_invitations WHERE expires_at <= CURRENT_TIMESTAMP")
        ai = cur.rowcount
        cur.execute("DELETE FROM messages            WHERE expires_at <= CURRENT_TIMESTAMP")
        msg = cur.rowcount
        conn.commit()
        logger.info(f"Cleanup: {tr} trades, {ai} invites, {msg} messages removed")

    # ------------------------------------------------------------------ #
    # Civilization CRUD
    # ------------------------------------------------------------------ #
    def create_civilization(
        self,
        user_id: str,
        name: str,
        bonus_resources: Dict[str, int] = None,
        bonuses: Dict[str, Any] = None,
        hyper_item: str = None,
    ) -> bool:
        bonus_resources = bonus_resources or {}
        bonuses = bonuses or {}

        resources = {"gold": 500, "food": 300, "stone": 100, "wood": 100}
        for k, v in bonus_resources.items():
            if k in resources:
                resources[k] += v

        population = {
            "citizens": 100 + bonus_resources.get("population", 0),
            "happiness": 50 + bonus_resources.get("happiness", 0),
            "hunger": 0,
            "employed": 50,
        }
        military = {"soldiers": 10, "spies": 2, "tech_level": 1}
        territory = {"land_size": 1000}

        conn = self.get_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO civilizations
                (user_id, name, resources, population, military, territory, hyper_items, bonuses, selected_cards)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    name,
                    json.dumps(resources),
                    json.dumps(population),
                    json.dumps(military),
                    json.dumps(territory),
                    json.dumps([hyper_item] if hyper_item else []),
                    json.dumps(bonuses),
                    json.dumps([]),
                ),
            )
            self.generate_card_selection(user_id, 1)
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_civilization(self, user_id: str) -> Optional[Dict[str, Any]]:
        cur = self.get_connection().cursor()
        row = cur.execute("SELECT * FROM civilizations WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            return None
        civ = dict(row)
        for key in ("resources", "population", "military", "territory", "hyper_items", "bonuses", "selected_cards"):
            civ[key] = json.loads(civ[key])
        return civ

    def update_civilization(self, user_id: str, updates: Dict[str, Any]) -> bool:
        conn = self.get_connection()
        cur = conn.cursor()
        set_clauses, values = [], []
        for key, value in updates.items():
            if key in {"resources", "population", "military", "territory", "hyper_items", "bonuses", "selected_cards"}:
                set_clauses.append(f"{key} = ?")
                values.append(json.dumps(value))
            else:
                set_clauses.append(f"{key} = ?")
                values.append(value)
        set_clauses.append("last_active = CURRENT_TIMESTAMP")
        values.append(user_id)
        query = f"UPDATE civilizations SET {', '.join(set_clauses)} WHERE user_id = ?"
        cur.execute(query, values)
        conn.commit()
        return cur.rowcount > 0

    def get_all_civilizations(self) -> List[Dict[str, Any]]:
        cur = self.get_connection().cursor()
        rows = cur.execute("SELECT * FROM civilizations ORDER BY last_active DESC").fetchall()
        civs = []
        for row in rows:
            civ = dict(row)
            for key in ("resources", "population", "military", "territory", "hyper_items", "bonuses", "selected_cards"):
                civ[key] = json.loads(civ[key])
            civs.append(civ)
        return civs

    # ------------------------------------------------------------------ #
    # Resource helpers used by MilitaryCommands and elsewhere
    # ------------------------------------------------------------------ #
    def can_afford(self, user_id: str, costs: Dict[str, int]) -> bool:
        civ = self.get_civilization(user_id)
        if not civ:
            return False
        for res, amt in costs.items():
            if civ["resources"].get(res, 0) < amt:
                return False
        return True

    def spend_resources(self, user_id: str, costs: Dict[str, int]) -> None:
        civ = self.get_civilization(user_id)
        if not civ:
            return
        for res, amt in costs.items():
            civ["resources"][res] = max(0, civ["resources"].get(res, 0) - amt)
        self.update_civilization(user_id, {"resources": civ["resources"]})

    def update_resources(self, user_id: str, delta: Dict[str, int]) -> None:
        civ = self.get_civilization(user_id)
        if not civ:
            return
        for res, amt in delta.items():
            civ["resources"][res] = civ["resources"].get(res, 0) + amt
        self.update_civilization(user_id, {"resources": civ["resources"]})

    def update_military(self, user_id: str, delta: Dict[str, int]) -> None:
        civ = self.get_civilization(user_id)
        if not civ:
            return
        for k, v in delta.items():
            civ["military"][k] = max(0, civ["military"].get(k, 0) + v)
        self.update_civilization(user_id, {"military": civ["military"]})

    def update_territory(self, user_id: str, delta: Dict[str, int]) -> None:
        civ = self.get_civilization(user_id)
        if not civ:
            return
        for k, v in delta.items():
            civ["territory"][k] = max(0, civ["territory"].get(k, 0) + v)
        self.update_civilization(user_id, {"territory": civ["territory"]})

    def update_population(self, user_id: str, delta: Dict[str, int]) -> None:
        civ = self.get_civilization(user_id)
        if not civ:
            return
        for k, v in delta.items():
            civ["population"][k] = max(0, civ["population"].get(k, 0) + v)
        self.update_civilization(user_id, {"population": civ["population"]})

    def get_ideology_modifier(self, user_id: str, key: str) -> float:
        """
        Placeholder for ideology-based multipliers.
        Returns a float that the cog multiplies into outcomes.
        """
        civ = self.get_civilization(user_id)
        if not civ or not civ.get("ideology"):
            return 1.0
        ideology = civ["ideology"]
        # Example mapping; extend as you wish
        modifiers = {
            "fascism": {"soldier_training_speed": 1.1},
            "pacifist": {"soldier_training_speed": 0.9},
            "destruction": {"soldier_training_speed": 1.2},
            "anarchy": {"soldier_training_speed": 0.85},
        }
        return modifiers.get(ideology, {}).get(key, 1.0)

    # ------------------------------------------------------------------ #
    # Cards
    # ------------------------------------------------------------------ #
    def generate_card_selection(self, user_id: str, tech_level: int) -> bool:
        pool = [
            {"name": "Resource Boost", "type": "bonus", "effect": {"resource_production": 10}, "description": "+10% resource production"},
            {"name": "Military Training", "type": "bonus", "effect": {"soldier_training_speed": 15}, "description": "+15% training speed"},
            {"name": "Trade Advantage", "type": "bonus", "effect": {"trade_profit": 10}, "description": "+10% trade profit"},
            {"name": "Population Surge", "type": "bonus", "effect": {"population_growth": 10}, "description": "+10% population growth"},
            {"name": "Tech Breakthrough", "type": "one_time", "effect": {"tech_level": 1}, "description": "+1 tech level"},
            {"name": "Gold Cache", "type": "one_time", "effect": {"gold": 500}, "description": "Gain 500 gold"},
            {"name": "Food Reserves", "type": "one_time", "effect": {"food": 300}, "description": "Gain 300 food"},
            {"name": "Mercenary Band", "type": "one_time", "effect": {"soldiers": 20}, "description": "Recruit 20 soldiers"},
            {"name": "Spy Network", "type": "one_time", "effect": {"spies": 5}, "description": "Recruit 5 spies"},
            {"name": "Fortification", "type": "bonus", "effect": {"defense_strength": 15}, "description": "+15% defense"},
        ]
        cards = random.sample(pool, 5)
        conn = self.get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO cards (user_id, tech_level, available_cards, status) VALUES (?, ?, ?, ?)",
            (user_id, tech_level, json.dumps(cards), "pending"),
        )
        conn.commit()
        return True

    def get_card_selection(self, user_id: str, tech_level: int) -> Optional[Dict[str, Any]]:
        cur = self.get_connection().cursor()
        row = cur.execute(
            "SELECT * FROM cards WHERE user_id = ? AND tech_level = ? AND status = 'pending'", (user_id, tech_level)
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["available_cards"] = json.loads(data["available_cards"])
        return data

    def select_card(self, user_id: str, tech_level: int, card_name: str) -> Optional[Dict[str, Any]]:
        sel = self.get_card_selection(user_id, tech_level)
        if not sel:
            return None
        card = next((c for c in sel["available_cards"] if c["name"].lower() == card_name.lower()), None)
        if not card:
            return None
        conn = self.get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE cards SET status = 'selected' WHERE user_id = ? AND tech_level = ?", (user_id, tech_level))
        conn.commit()
        return card

    def apply_card_effect(self, user_id: str, card: Dict[str, Any]) -> None:
        """
        Apply the effect dict from a selected card.
        This is intentionally generic; extend as you add more card effects.
        """
        effect = card.get("effect", {})
        if not effect:
            return
        civ = self.get_civilization(user_id)
        if not civ:
            return

        # Tech level (one-time)
        if "tech_level" in effect:
            civ["military"]["tech_level"] = min(10, civ["military"]["tech_level"] + effect["tech_level"])
            self.update_civilization(user_id, {"military": civ["military"]})

        # One-time resources
        for res in ("gold", "food", "stone", "wood"):
            if res in effect:
                self.update_resources(user_id, {res: effect[res]})

        # One-time military
        if "soldiers" in effect:
            self.update_military(user_id, {"soldiers": effect["soldiers"]})
        if "spies" in effect:
            self.update_military(user_id, {"spies": effect["spies"]})

        # Permanent bonuses (stored in bonuses dict)
        bonuses = civ["bonuses"]
        for k, v in effect.items():
            bonuses[k] = bonuses.get(k, 0) + v
        self.update_civilization(user_id, {"bonuses": bonuses})

    # ------------------------------------------------------------------ #
    # Cooldown helpers
    # ------------------------------------------------------------------ #
    def get_command_cooldown(self, user_id: str, command: str) -> Optional[datetime]:
        cur = self.get_connection().cursor()
        row = cur.execute(
            "SELECT last_used_at FROM cooldowns WHERE user_id = ? AND command = ?", (user_id, command)
        ).fetchone()
        return datetime.fromisoformat(row["last_used_at"]) if row else None

    def set_command_cooldown(self, user_id: str, command: str, ts: datetime) -> bool:
        conn = self.get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO cooldowns (user_id, command, last_used_at) VALUES (?, ?, ?)",
            (user_id, command, ts.isoformat()),
        )
        conn.commit()
        return True

    # ------------------------------------------------------------------ #
    # Alliance helpers
    # ------------------------------------------------------------------ #
    def create_alliance(self, name: str, leader_id: str, description: str = "") -> bool:
        conn = self.get_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO alliances (name, leader_id, members, description) VALUES (?, ?, ?, ?)",
                (name, leader_id, json.dumps([leader_id]), description),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_alliance(self, alliance_id: int) -> Optional[Dict[str, Any]]:
        cur = self.get_connection().cursor()
        row = cur.execute("SELECT * FROM alliances WHERE id = ?", (alliance_id,)).fetchone()
        if not row:
            return None
        al = dict(row)
        al["members"] = json.loads(al["members"])
        al["join_requests"] = json.loads(al["join_requests"])
        return al

    def add_alliance_member(self, alliance_id: int, user_id: str) -> bool:
        al = self.get_alliance(alliance_id)
        if not al:
            return False
        members = al["members"]
        if user_id in members:
            return True
        members.append(user_id)
        join_requests = [u for u in al["join_requests"] if u != user_id]
        conn = self.get_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE alliances SET members = ?, join_requests = ? WHERE id = ?",
            (json.dumps(members), json.dumps(join_requests), alliance_id),
        )
        conn.commit()
        return True

    def create_alliance_invite(self, alliance_id: int, sender_id: str, recipient_id: str) -> bool:
        conn = self.get_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO alliance_invitations (alliance_id, sender_id, recipient_id) VALUES (?, ?, ?)",
                (alliance_id, sender_id, recipient_id),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_alliance_invites(self, user_id: str) -> List[Dict[str, Any]]:
        cur = self.get_connection().cursor()
        rows = cur.execute(
            """
            SELECT ai.*, a.name as alliance_name
            FROM alliance_invitations ai
            JOIN alliances a ON ai.alliance_id = a.id
            WHERE ai.recipient_id = ? AND ai.expires_at > CURRENT_TIMESTAMP
            """,
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_alliance_invite_by_id(self, invite_id: int) -> Optional[Dict[str, Any]]:
        cur = self.get_connection().cursor()
        row = cur.execute(
            """
            SELECT ai.*, a.name as alliance_name
            FROM alliance_invitations ai
            JOIN alliances a ON ai.alliance_id = a.id
            WHERE ai.id = ? AND ai.expires_at > CURRENT_TIMESTAMP
            """,
            (invite_id,),
        ).fetchone()
        return dict(row) if row else None

    def delete_alliance_invite(self, invite_id: int) -> bool:
        conn = self.get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM alliance_invitations WHERE id = ?", (invite_id,))
        conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------ #
    # Trade helpers
    # ------------------------------------------------------------------ #
    def create_trade_request(self, sender_id: str, recipient_id: str, offer: Dict, request: Dict) -> bool:
        conn = self.get_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO trade_requests (sender_id, recipient_id, offer, request) VALUES (?, ?, ?, ?)",
                (sender_id, recipient_id, json.dumps(offer), json.dumps(request)),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_trade_requests(self, user_id: str) -> List[Dict[str, Any]]:
        cur = self.get_connection().cursor()
        rows = cur.execute(
            """
            SELECT t.*, c.name as sender_name
            FROM trade_requests t
            JOIN civilizations c ON t.sender_id = c.user_id
            WHERE t.recipient_id = ? AND t.expires_at > CURRENT_TIMESTAMP
            """,
            (user_id,),
        ).fetchall()
        trades = []
        for r in rows:
            t = dict(r)
            t["offer"] = json.loads(t["offer"])
            t["request"] = json.loads(t["request"])
            trades.append(t)
        return trades

    def get_trade_request_by_id(self, request_id: int) -> Optional[Dict[str, Any]]:
        cur = self.get_connection().cursor()
        row = cur.execute(
            "SELECT * FROM trade_requests WHERE id = ? AND expires_at > CURRENT_TIMESTAMP", (request_id,)
        ).fetchone()
        if not row:
            return None
        t = dict(row)
        t["offer"] = json.loads(t["offer"])
        t["request"] = json.loads(t["request"])
        return t

    def delete_trade_request(self, request_id: int) -> bool:
        conn = self.get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM trade_requests WHERE id = ?", (request_id,))
        conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------ #
    # Messaging
    # ------------------------------------------------------------------ #
    def send_message(self, sender_id: str, recipient_id: str, message: str) -> bool:
        conn = self.get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO messages (sender_id, recipient_id, message) VALUES (?, ?, ?)",
            (sender_id, recipient_id, message),
        )
        conn.commit()
        return True

    def get_messages(self, user_id: str) -> List[Dict[str, Any]]:
        cur = self.get_connection().cursor()
        rows = cur.execute(
            """
            SELECT m.*, c.name as sender_name
            FROM messages m
            JOIN civilizations c ON m.sender_id = c.user_id
            WHERE m.recipient_id = ? AND m.expires_at > CURRENT_TIMESTAMP
            """,
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_message(self, message_id: int) -> bool:
        conn = self.get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------ #
    # Events / logging
    # ------------------------------------------------------------------ #
    def log_event(
        self,
        user_id: str,
        event_type: str,
        title: str,
        description: str,
        effects: Dict[str, Any] = None,
    ) -> None:
        conn = self.get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO events (user_id, event_type, title, description, effects) VALUES (?, ?, ?, ?, ?)",
            (user_id, event_type, title, description, json.dumps(effects or {})),
        )
        conn.commit()

    def get_recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        cur = self.get_connection().cursor()
        rows = cur.execute(
            """
            SELECT e.*, c.name as civ_name
            FROM events e
            LEFT JOIN civilizations c ON e.user_id = c.user_id
            ORDER BY e.timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        events = []
        for r in rows:
            e = dict(r)
            e["effects"] = json.loads(e["effects"])
            events.append(e)
        return events

    # ------------------------------------------------------------------ #
    # Shutdown
    # ------------------------------------------------------------------ #
    def close_connections(self) -> None:
        if hasattr(self.local, "connection"):
            self.local.connection.close()
            del self.local.connection
