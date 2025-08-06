"""
Guilded Civilization Bot - Render-Ready Single File
A complete civilization-building game bot with economy, combat, alliances, espionage, and natural disasters.
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

# --------------------------- LOGGING ---------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("civ-bot")

# --------------------------- WEB SERVER (RENDER) ---------------------------

async def health_check(request: web.Request) -> web.Response:
    """Health-check endpoint for Render."""
    return web.Response(text="Bot is running")

async def start_web_server() -> None:
    """Start a tiny web server so Render keeps the container alive."""
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Health-check server listening on port %s", port)

# --------------------------- GAME CONFIG ---------------------------

class GameConfig:
    COOLDOWNS = {
        "gather": 1,
        "build": 2,
        "train": 1.5,
        "attack": 1.5,
        "ally": 2,
        "break": 2,
        "spy": 2,
        "send": 0.5,
        "mail": 1
    }

    BUILDINGS = {
        "house":    {"name": "House",    "cost": {"materials": 20, "gold": 10}, "effects": {"population": 5}},
        "farm":     {"name": "Farm",     "cost": {"materials": 30, "gold": 15}, "effects": {"food_per_turn": 5}},
        "barracks": {"name": "Barracks", "cost": {"materials": 50, "gold": 25}, "effects": {"soldiers": 3}},
        "wall":     {"name": "Wall",     "cost": {"materials": 40, "gold": 20}, "effects": {"defenses": 2}},
        "market":   {"name": "Market",   "cost": {"materials": 60, "gold": 30}, "effects": {"gold_per_turn": 3}},
        "temple":   {"name": "Temple",   "cost": {"materials": 80, "gold": 40}, "effects": {"happiness": 10}}
    }

    STARTING_STATS = {
        "gold": 50, "food": 100, "materials": 50, "population": 10,
        "happiness": 50, "hunger": 100, "soldiers": 5, "defenses": 1,
        "buildings": {}, "wins": 0, "losses": 0, "level": 1, "experience": 0
    }

    BALANCE = {
        "max_alliances": 3,
        "max_resources": {"gold": 1000, "food": 500, "materials": 300},
        "experience_per_level": 100,
        "level_benefits": {"population_bonus": 2, "resource_bonus": 5}
    }

# --------------------------- DATABASE ---------------------------

class DatabaseManager:
    def __init__(self, db_path: str = "civilizations.db"):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None

    async def initialize(self) -> None:
        self.conn = sqlite3.connect(self.db_path)
        cur = self.conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS civilizations (
                user_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                gold INTEGER DEFAULT 0,
                food INTEGER DEFAULT 100,
                materials INTEGER DEFAULT 50,
                population INTEGER DEFAULT 10,
                happiness INTEGER DEFAULT 50,
                hunger INTEGER DEFAULT 100,
                soldiers INTEGER DEFAULT 5,
                defenses INTEGER DEFAULT 1,
                buildings TEXT DEFAULT '{}',
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                experience INTEGER DEFAULT 0
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS cooldowns (
                user_id TEXT,
                command TEXT,
                expires_at TIMESTAMP,
                PRIMARY KEY (user_id, command)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS alliances (
                user1_id TEXT,
                user2_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user1_id, user2_id)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS alliance_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user_id TEXT,
                to_user_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                UNIQUE(from_user_id, to_user_id)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id TEXT NOT NULL,
                recipient_id TEXT NOT NULL,
                subject TEXT,
                content TEXT NOT NULL,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                read BOOLEAN DEFAULT FALSE
            )
        """)
        self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            self.conn.close()

    # --- helpers (sync wrappers) ---
    async def get_civilization(self, user_id: str) -> Optional[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM civilizations WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if not row:
            return None
        data = dict(zip([c[0] for c in cur.description], row))
        data["buildings"] = json.loads(data["buildings"])
        return data

    async def create_civilization(self, user_id: str, name: str) -> bool:
        try:
            cur = self.conn.cursor()
            cur.execute("""
                INSERT INTO civilizations (user_id, name, gold, food, materials,
                                           population, happiness, hunger,
                                           soldiers, defenses)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, name, *GameConfig.STARTING_STATS[k] for k in
                  ["gold", "food", "materials", "population", "happiness",
                   "hunger", "soldiers", "defenses"]))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    async def update_civilization(self, user_id: str, updates: Dict[str, Any]) -> None:
        if "buildings" in updates:
            updates["buildings"] = json.dumps(updates["buildings"])
        set_clause = ", ".join(f"{k}=?" for k in updates)
        values = list(updates.values()) + [user_id]
        self.conn.execute(f"UPDATE civilizations SET {set_clause} WHERE user_id=?", values)
        self.conn.commit()

    async def check_cooldown(self, user_id: str, command: str) -> Optional[datetime]:
        cur = self.conn.cursor()
        cur.execute("""
            SELECT expires_at FROM cooldowns
            WHERE user_id=? AND command=? AND expires_at>datetime('now')
        """, (user_id, command))
        row = cur.fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    async def set_cooldown(self, user_id: str, command: str, minutes: float) -> None:
        expires = (datetime.utcnow() + timedelta(minutes=minutes)).isoformat()
        self.conn.execute("INSERT OR REPLACE INTO cooldowns VALUES (?,?,?)",
                          (user_id, command, expires))
        self.conn.commit()

    async def get_alliances(self, user_id: str) -> List[str]:
        cur = self.conn.cursor()
        cur.execute("""
            SELECT user2_id FROM alliances WHERE user1_id=?
            UNION
            SELECT user1_id FROM alliances WHERE user2_id=?
        """, (user_id, user_id))
        return [r[0] for r in cur.fetchall()]

    async def create_alliance(self, a: str, b: str) -> bool:
        if a > b:
            a, b = b, a
        try:
            self.conn.execute("INSERT INTO alliances (user1_id, user2_id) VALUES (?,?)", (a, b))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    async def break_alliance(self, a: str, b: str) -> bool:
        cur = self.conn.cursor()
        cur.execute("""
            DELETE FROM alliances
            WHERE (user1_id=? AND user2_id=?) OR (user1_id=? AND user2_id=?)
        """, (a, b, b, a))
        self.conn.commit()
        return cur.rowcount > 0

    async def create_alliance_request(self, frm: str, to: str) -> bool:
        expires = (datetime.utcnow() + timedelta(hours=24)).isoformat()
        try:
            self.conn.execute("""
                INSERT INTO alliance_requests (from_user_id, to_user_id, expires_at)
                VALUES (?,?,?)
            """, (frm, to, expires))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    async def get_alliance_request(self, frm: str, to: str) -> Optional[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("""
            SELECT * FROM alliance_requests
            WHERE from_user_id=? AND to_user_id=? AND expires_at>datetime('now')
        """, (frm, to))
        row = cur.fetchone()
        if not row:
            return None
        return dict(zip([c[0] for c in cur.description], row))

    async def delete_alliance_request(self, frm: str, to: str) -> bool:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM alliance_requests WHERE from_user_id=? AND to_user_id=?", (frm, to))
        self.conn.commit()
        return cur.rowcount > 0

    async def send_message(self, sender: str, recipient: str, subject: str, content: str) -> None:
        self.conn.execute("""
            INSERT INTO messages (sender_id, recipient_id, subject, content)
            VALUES (?,?,?,?)
        """, (sender, recipient, subject, content))
        self.conn.commit()

    async def get_messages(self, user_id: str, unread_only: bool = False) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        sql = "SELECT * FROM messages WHERE recipient_id=?"
        params = [user_id]
        if unread_only:
            sql += " AND read=0"
        sql += " ORDER BY sent_at DESC LIMIT 10"
        cur.execute(sql, params)
        return [dict(zip([c[0] for c in cur.description], row)) for row in cur.fetchall()]

    async def mark_message_read(self, msg_id: int) -> None:
        self.conn.execute("UPDATE messages SET read=1 WHERE id=?", (msg_id,))
        self.conn.commit()

# --------------------------- UTILITIES ---------------------------

def extract_user_id(mention: str) -> Optional[str]:
    m = re.search(r"<@([a-zA-Z0-9]{8})>", mention)
    return m.group(1) if m else None

def fmt_remaining(td: timedelta) -> str:
    secs = int(td.total_seconds())
    if secs <= 0:
        return "0s"
    mins, secs = divmod(secs, 60)
    return f"{mins}m {secs}s" if mins else f"{secs}s"

async def on_cooldown(db: DatabaseManager, uid: str, cmd: str, mins: float) -> Optional[timedelta]:
    exp = await db.check_cooldown(uid, cmd)
    if exp and exp > datetime.utcnow():
        return exp - datetime.utcnow()
    return None

# --------------------------- GAME LOGIC ---------------------------

class GameLogic:
    def __init__(self):
        self.cfg = GameConfig()

    def combat(self, atk: Dict[str, Any], dfn: Dict[str, Any]) -> Dict[str, Any]:
        ap = atk["soldiers"] + (atk["defenses"] * 0.5)
        dp = dfn["soldiers"] + (dfn["defenses"] * 1.5)
        ap *= random.uniform(0.8, 1.2)
        dp *= random.uniform(0.8, 1.2)

        if ap > dp:
            ratio = ap / dp
            al = max(1, int(atk["soldiers"] * 0.1))
            dl = max(1, int(dfn["soldiers"] * min(0.5, ratio * 0.2)))
            gg = min(dfn["gold"], int(dfn["gold"] * 0.3))
            gf = min(dfn["food"], int(dfn["food"] * 0.2))
            return {"winner": "attacker", "al": al, "dl": dl, "gg": gg, "gf": gf}
        else:
            ratio = dp / ap
            al = max(1, int(atk["soldiers"] * min(0.6, ratio * 0.3)))
            dl = max(1, int(dfn["soldiers"] * 0.1))
            return {"winner": "defender", "al": al, "dl": dl, "gg": 0, "gf": 0}

# --------------------------- BOT ---------------------------

class CivilizationBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=".",
            help_command=None,
            case_insensitive=True
        )
        self.db = DatabaseManager()
        self.logic = GameLogic()
        self.disaster = None

    async def on_ready(self):
        logger.info("%s connected to Guilded", self.user)
        await self.db.initialize()
        self.disaster = NaturalDisasterManager(self)
        asyncio.create_task(self.disaster.start())

    # ---------- BASIC ----------
    @commands.command(name="start")
    async def start_cmd(self, ctx: commands.Context, *, name: str = ""):
        if not name or len(name) > 50:
            return await ctx.reply("❌ Provide a name ≤50 chars: `.start My Empire`")
        uid = str(ctx.author.id)
        if await self.db.get_civilization(uid):
            return await ctx.reply("❌ You already have a civilization!")
        if await self.db.create_civilization(uid, name):
            embed = guilded.Embed(title="🏛️ Civilization Founded!",
                                  description=f"Welcome to **{name}**!",
                                  color=0x00ff00)
            embed.add_field(name="Starting Resources",
                            value="\n".join(f"{k.title()}: {v}" for k, v in GameConfig.STARTING_STATS.items()
                                            if k in {"gold", "food", "materials", "population"}))
            await ctx.reply(embed=embed)

    @commands.command(name="status")
    async def status_cmd(self, ctx: commands.Context):
        uid = str(ctx.author.id)
        civ = await self.db.get_civilization(uid)
        if not civ:
            return await ctx.reply("❌ Create a civilization first: `.start <name>`")
        embed = guilded.Embed(title=f"🏛️ {civ['name']}", color=0x0099ff)
        embed.add_field(name="💰 Resources",
                        value=f"Gold: {civ['gold']}\nFood: {civ['food']}\nMaterials: {civ['materials']}")
        embed.add_field(name="👥 Population & Military",
                        value=f"Pop: {civ['population']}\nSoldiers: {civ['soldiers']}\nDefenses: {civ['defenses']}")
        await ctx.reply(embed=embed)

    @commands.command(name="help")
    async def help_cmd(self, ctx: commands.Context):
        embed = guilded.Embed(title="🏛️ Civilization Bot Commands", color=0x0099ff)
        embed.add_field(name="Essential", value="`.start <name>` ‑ create\n`.status` ‑ view\n`.help` ‑ this")
        embed.add_field(name="Economy", value="`.gather` ‑ resources\n`.build <type>` ‑ construct\n`.train` ‑ soldiers")
        embed.add_field(name="Interaction", value="`.attack @p` ‑ assault\n`.ally @p` ‑ alliance\n`.send @p msg` ‑ message\n`.mail` ‑ inbox")
        embed.add_field(name="Buildings", value=", ".join(GameConfig.BUILDINGS.keys()))
        await ctx.reply(embed=embed)

    # ---------- ECONOMY ----------
    @commands.command(name="gather")
    async def gather_cmd(self, ctx: commands.Context):
        uid = str(ctx.author.id)
        civ = await self.db.get_civilization(uid)
        if not civ:
            return await ctx.reply("❌ Create a civilization first.")
        rem = await on_cooldown(self.db, uid, "gather", GameConfig.COOLDOWNS["gather"])
        if rem:
            return await ctx.reply(f"⏰ Wait {fmt_remaining(rem)}")
        g, f, m = random.randint(10, 25), random.randint(15, 30), random.randint(5, 15)
        bonus = civ["level"] * GameConfig.BALANCE["level_benefits"]["resource_bonus"]
        g += bonus; f += bonus; m += bonus
        await self.db.update_civilization(uid, {
            "gold": min(civ["gold"] + g, GameConfig.BALANCE["max_resources"]["gold"]),
            "food": min(civ["food"] + f, GameConfig.BALANCE["max_resources"]["food"]),
            "materials": min(civ["materials"] + m, GameConfig.BALANCE["max_resources"]["materials"]),
            "experience": civ["experience"] + 5
        })
        await self.db.set_cooldown(uid, "gather", GameConfig.COOLDOWNS["gather"])
        await ctx.reply(f"💰 Gathered: +{g}g +{f}f +{m}m")

    @commands.command(name="build")
    async def build_cmd(self, ctx: commands.Context, *, btype: str = ""):
        btype = btype.lower()
        if btype not in GameConfig.BUILDINGS:
            return await ctx.reply("❌ Types: " + ", ".join(GameConfig.BUILDINGS))
        uid = str(ctx.author.id)
        civ = await self.db.get_civilization(uid)
        if not civ:
            return await ctx.reply("❌ Create a civilization first.")
        rem = await on_cooldown(self.db, uid, "build", GameConfig.COOLDOWNS["build"])
        if rem:
            return await ctx.reply(f"⏰ Wait {fmt_remaining(rem)}")
        info = GameConfig.BUILDINGS[btype]
        cost = info["cost"]
        if civ["materials"] < cost["materials"] or civ["gold"] < cost["gold"]:
            return await ctx.reply("❌ Not enough resources.")
        b = civ["buildings"].copy()
        b[btype] = b.get(btype, 0) + 1
        updates = {"materials": civ["materials"] - cost["materials"],
                   "gold": civ["gold"] - cost["gold"],
                   "buildings": b,
                   "experience": civ["experience"] + 10}
        for k, v in info["effects"].items():
            updates[k] = civ.get(k, 0) + v
        await self.db.update_civilization(uid, updates)
        await self.db.set_cooldown(uid, "build", GameConfig.COOLDOWNS["build"])
        await ctx.reply(f"🏗️ Built a {info['name']}!")

    @commands.command(name="train")
    async def train_cmd(self, ctx: commands.Context):
        uid = str(ctx.author.id)
        civ = await self.db.get_civilization(uid)
        if not civ:
            return await ctx.reply("❌ Create a civilization first.")
        rem = await on_cooldown(self.db, uid, "train", GameConfig.COOLDOWNS["train"])
        if rem:
            return await ctx.reply(f"⏰ Wait {fmt_remaining(rem)}")
        barr = civ["buildings"].get("barracks", 0)
        if not barr:
            return await ctx.reply("❌ Need barracks first.")
        cost_g, cost_f = 25, 15
        if civ["gold"] < cost_g or civ["food"] < cost_f:
            return await ctx.reply("❌ Need 25g & 15f to train.")
        trained = barr * 2
        await self.db.update_civilization(uid, {
            "gold": civ["gold"] - cost_g,
            "food": civ["food"] - cost_f,
            "soldiers": civ["soldiers"] + trained
        })
        await self.db.set_cooldown(uid, "train", GameConfig.COOLDOWNS["train"])
        await ctx.reply(f"⚔️ Trained {trained} soldiers!")

    # ---------- COMBAT ----------
    @commands.command(name="attack")
    async def attack_cmd(self, ctx: commands.Context, target: str = ""):
        tid = extract_user_id(target)
        if not tid:
            return await ctx.reply("❌ Mention a user: `.attack @user`")
        uid = str(ctx.author.id)
        if tid == uid:
            return await ctx.reply("❌ Can't attack yourself.")
        atk_civ = await self.db.get_civilization(uid)
        dfn_civ = await self.db.get_civilization(tid)
        if not atk_civ or not dfn_civ:
            return await ctx.reply("❌ Both players need civilizations.")
        rem = await on_cooldown(self.db, uid, "attack", GameConfig.COOLDOWNS["attack"])
        if rem:
            return await ctx.reply(f"⏰ Wait {fmt_remaining(rem)}")
        if tid in await self.db.get_alliances(uid):
            return await ctx.reply("❌ Can't attack allies.")
        if atk_civ["soldiers"] <= 0:
            return await ctx.reply("❌ No soldiers to attack with.")
        res = self.logic.combat(atk_civ, dfn_civ)
        if res["winner"] == "attacker":
            await self.db.update_civilization(uid, {
                "soldiers": max(0, atk_civ["soldiers"] - res["al"]),
                "gold": atk_civ["gold"] + res["gg"],
                "food": atk_civ["food"] + res["gf"],
                "wins": atk_civ["wins"] + 1,
                "experience": atk_civ["experience"] + 20
            })
            await self.db.update_civilization(tid, {
                "soldiers": max(0, dfn_civ["soldiers"] - res["dl"]),
                "gold": max(0, dfn_civ["gold"] - res["gg"]),
                "food": max(0, dfn_civ["food"] - res["gf"]),
                "losses": dfn_civ["losses"] + 1,
                "happiness": max(0, dfn_civ["happiness"] - 10)
            })
            await ctx.reply(f"⚔️ Victory! You looted {res['gg']}g {res['gf']}f.")
        else:
            await self.db.update_civilization(uid, {
                "soldiers": max(0, atk_civ["soldiers"] - res["al"]),
                "losses": atk_civ["losses"] + 1,
                "happiness": max(0, atk_civ["happiness"] - 15)
            })
            await self.db.update_civilization(tid, {
                "soldiers": max(0, dfn_civ["soldiers"] - res["dl"]),
                "wins": dfn_civ["wins"] + 1,
                "experience": dfn_civ["experience"] + 15
            })
            await ctx.reply("⚔️ Defeat! Your forces were repelled.")
        await self.db.set_cooldown(uid, "attack", GameConfig.COOLDOWNS["attack"])

    # ---------- DIPLOMACY ----------
    @commands.command(name="ally")
    async def ally_cmd(self, ctx: commands.Context, target: str = ""):
        tid = extract_user_id(target)
        if not tid:
            return await ctx.reply("❌ Mention a user: `.ally @user`")
        uid = str(ctx.author.id)
        if tid == uid:
            return await ctx.reply("❌ Can't ally yourself.")
        civ1 = await self.db.get_civilization(uid)
        civ2 = await self.db.get_civilization(tid)
        if not civ1 or not civ2:
            return await ctx.reply("❌ Both need civilizations.")
        rem = await on_cooldown(self.db, uid, "ally", GameConfig.COOLDOWNS["ally"])
        if rem:
            return await ctx.reply(f"⏰ Wait {fmt_remaining(rem)}")
        if tid in await self.db.get_alliances(uid):
            return await ctx.reply("❌ Already allied.")
        req = await self.db.get_alliance_request(tid, uid)
        if req:  # accept
            await self.db.create_alliance(uid, tid)
            await self.db.delete_alliance_request(tid, uid)
            await self.db.set_cooldown(uid, "ally", GameConfig.COOLDOWNS["ally"])
            return await ctx.reply("🤝 Alliance formed!")
        if await self.db.get_alliance_request(uid, tid):
            return await ctx.reply("❌ Request already sent.")
        if len(await self.db.get_alliances(uid)) >= GameConfig.BALANCE["max_alliances"]:
            return await ctx.reply("❌ Alliance limit reached.")
        await self.db.create_alliance_request(uid, tid)
        await self.db.set_cooldown(uid, "ally", GameConfig.COOLDOWNS["ally"])
        await ctx.reply("🤝 Alliance request sent!")

    @commands.command(name="break")
    async def break_cmd(self, ctx: commands.Context, target: str = ""):
        tid = extract_user_id(target)
        if not tid:
            return await ctx.reply("❌ Mention a user: `.break @user`")
        uid = str(ctx.author.id)
        rem = await on_cooldown(self.db, uid, "break", GameConfig.COOLDOWNS["break"])
        if rem:
            return await ctx.reply(f"⏰ Wait {fmt_remaining(rem)}")
        if tid not in await self.db.get_alliances(uid):
            return await ctx.reply("❌ Not allied.")
        await self.db.break_alliance(uid, tid)
        await self.db.set_cooldown(uid, "break", GameConfig.COOLDOWNS["break"])
        await ctx.reply("💔 Alliance broken.")

    # ---------- ESPIONAGE / COMMS ----------
    @commands.command(name="spy")
    async def spy_cmd(self, ctx: commands.Context, target: str = ""):
        tid = extract_user_id(target)
        if not tid:
            return await ctx.reply("❌ Mention a user: `.spy @user`")
        uid = str(ctx.author.id)
        rem = await on_cooldown(self.db, uid, "spy", GameConfig.COOLDOWNS["spy"])
        if rem:
            return await ctx.reply(f"⏰ Wait {fmt_remaining(rem)}")
        civ = await self.db.get_civilization(tid)
        if not civ:
            return await ctx.reply("❌ Target has no civilization.")
        await self.db.set_cooldown(uid, "spy", GameConfig.COOLDOWNS["spy"])
        await ctx.reply("🕵️ Spies dispatched (results sent via mail).")
        await self.db.send_message("System", uid, f"Spy Report on {civ['name']}",
                                   f"Gold: {civ['gold']}\nFood: {civ['food']}\nSoldiers: {civ['soldiers']}")

    @commands.command(name="send")
    async def send_cmd(self, ctx: commands.Context, target: str = "", *, text: str = ""):
        tid = extract_user_id(target)
        if not tid or not text:
            return await ctx.reply("❌ `.send @user message`")
        uid = str(ctx.author.id)
        rem = await on_cooldown(self.db, uid, "send", GameConfig.COOLDOWNS["send"])
        if rem:
            return await ctx.reply(f"⏰ Wait {fmt_remaining(rem)}")
        tciv = await self.db.get_civilization(tid)
        if not tciv:
            return await ctx.reply("❌ Target has no civilization.")
        await self.db.send_message(uid, tid, f"From {ctx.author.name}", text)
        await self.db.set_cooldown(uid, "send", GameConfig.COOLDOWNS["send"])
        await ctx.reply("📮 Message sent!")

    @commands.command(name="mail")
    async def mail_cmd(self, ctx: commands.Context):
        uid = str(ctx.author.id)
        rem = await on_cooldown(self.db, uid, "mail", GameConfig.COOLDOWNS["mail"])
        if rem:
            return await ctx.reply(f"⏰ Wait {fmt_remaining(rem)}")
        msgs = await self.db.get_messages(uid, unread_only=True)
        if not msgs:
            return await ctx.reply("📬 No new mail.")
        out = []
        for m in msgs:
            out.append(f"**{m['subject']}** - *{m['sent_at'][:16]}*\n{m['content'][:120]}...")
            await self.db.mark_message_read(m["id"])
        embed = guilded.Embed(title="📬 Inbox", description="\n\n".join(out), color=0x0099ff)
        await self.db.set_cooldown(uid, "mail", GameConfig.COOLDOWNS["mail"])
        await ctx.reply(embed=embed)

# --------------------------- DISASTER BACKGROUND ---------------------------

class NaturalDisasterManager:
    def __init__(self, bot: CivilizationBot):
        self.bot = bot
        self.chance = 0.02
        self.interval = 3600

    async def start(self):
        await self.bot.db.initialize()
        while True:
            await asyncio.sleep(self.interval)
            await self.check()

    async def check(self):
        cur = self.bot.db.conn.cursor()
        cur.execute("SELECT user_id FROM civilizations WHERE last_active>datetime('now','-7 day')")
        for (uid,) in cur.fetchall():
            if random.random() < self.chance:
                await self.trigger(uid)

    async def trigger(self, uid: str):
        civ = await self.bot.db.get_civilization(uid)
        if not civ:
            return
        disaster = random.choice(["earthquake", "flood", "drought"])
        if disaster == "earthquake":
            lost_pop = random.randint(1, max(1, civ["population"] // 10))
            b = civ["buildings"].copy()
            broken = []
            for k in list(b):
                if random.random() < 0.3:
                    b[k] = max(0, b[k] - 1)
                    if b[k] == 0:
                        del b[k]
                    broken.append(k)
            await self.bot.db.update_civilization(uid, {"population": max(1, civ["population"] - lost_pop), "buildings": b})
            await self.bot.db.send_message("System", uid, "🌍 Earthquake", f"Lost {lost_pop} pop and {broken}")
        elif disaster == "flood":
            lost_f = random.randint(civ["food"] // 4, civ["food"] // 2)
            lost_m = random.randint(civ["materials"] // 3, civ["materials"] // 2)
            await self.bot.db.update_civilization(uid, {"food": max(0, civ["food"] - lost_f),
                                                        "materials": max(0, civ["materials"] - lost_m)})
            await self.bot.db.send_message("System", uid, "🌊 Flood", f"Lost {lost_f}f {lost_m}m")
        elif disaster == "drought":
            lost_f = random.randint(civ["food"] // 3, civ["food"] // 2)
            lost_h = random.randint(10, 20)
            await self.bot.db.update_civilization(uid, {"food": max(0, civ["food"] - lost_f),
                                                        "happiness": max(0, civ["happiness"] - lost_h)})
            await self.bot.db.send_message("System", uid, "🌵 Drought", f"Lost {lost_f}f {lost_h} happiness")

# --------------------------- MAIN ---------------------------

async def main():
    token = os.getenv("GUILDED_BOT_TOKEN")
    if not token:
        logger.error("GUILDED_BOT_TOKEN not set")
        return

    asyncio.create_task(start_web_server())
    bot = CivilizationBot()
    try:
        await bot.start(token)
    finally:
        await bot.db.close()

if __name__ == "__main__":
    asyncio.run(main())
