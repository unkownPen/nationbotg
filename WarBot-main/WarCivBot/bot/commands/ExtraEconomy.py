"""
ExtraEconomy cog (gold-in-civ currency, cooldowns, extragamble, .extrawork)

Highlights:
- Replaces per-user "cash" with gold stored on the user's civilization.
  All currency operations (get, add, withdraw, set) update the civ's resources.gold
  via bot.civ_manager (if present) or the Database instance passed to setup(...).
  If neither civ APIs are available this module falls back to a local JSON cache
  (but economy features require a civ in normal operation).
- Adds per-command cooldowns. Most commands use a 1 minute (60s) cooldown.
  extrawork uses 5 minutes (300s) which is the maximum allowed. No command
  uses more than 5 minutes.
- Commands only go on cooldown when they complete successfully. If a user
  calls a command incorrectly (missing required args) or the command raises an
  error, the cooldown is NOT applied.
- Replaces any generic "gamble" with `.extragamble`. Also provides `.extrawork`.
- Commands that require a civilization will check via bot.civ_manager or via
  Database.get_civilization; users without civs are asked to create one.
- Background tasks (miners, product payouts, raids, restock) still run and
  reward/penalize gold through the civ resource.

Usage:
    from bot.commands.ExtraEconomy import setup as setup_extra_economy
    setup_extra_economy(bot, db=self.db, storage_dir="./data")

Drop this file into WarBot-main/WarCivBot/bot/commands/ExtraEconomy.py and restart the bot.
"""
from __future__ import annotations

import os
import json
import random
import time
import asyncio
import logging
from threading import Lock
from typing import Dict, Any, Optional, List

from guilded.ext import commands

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# Optional import for typing / compatibility; if import fails we still proceed.
try:
    from bot.database import Database  # type: ignore
except Exception:
    Database = None  # type: ignore


class EconomyManager:
    """
    Manages economy persistence and logic. Currency is stored as 'gold'
    within a user's civilization (civ['resources']['gold']).
    """

    def __init__(self, storage_dir: str = ".", db: Optional[Any] = None, bot: Optional[commands.Bot] = None):
        self.db = db
        self.bot = bot  # reference to bot is useful for civ_manager access
        self.storage_dir = storage_dir
        self.lock = Lock()

        os.makedirs(storage_dir, exist_ok=True)
        # JSON fallback files (only used if civ/db not available)
        self.DATA_FALLBACK = os.path.join(storage_dir, "civ_gold_fallback.json")

        # Ensure fallback file exists
        if not os.path.exists(self.DATA_FALLBACK):
            with open(self.DATA_FALLBACK, "w") as f:
                json.dump({}, f)

        # load fallback cache
        self._load_fallback()

        # If db provided create economy tables if needed (we still store gold in civs)
        if self.db:
            try:
                if hasattr(self.db, "get_connection"):
                    conn = self.db.get_connection()
                    cur = conn.cursor()
                    # No special economy tables required for gold (we store in civilizations.resources),
                    # but keep product/inventory tables if required by background tasks
                    cur.execute('''
                        CREATE TABLE IF NOT EXISTS economy_inventory (
                            user_id TEXT PRIMARY KEY,
                            items TEXT NOT NULL
                        )
                    ''')
                    cur.execute('''
                        CREATE TABLE IF NOT EXISTS economy_products (
                            user_id TEXT PRIMARY KEY,
                            products TEXT NOT NULL
                        )
                    ''')
                    conn.commit()
            except Exception:
                logger.exception("Failed to ensure extra economy tables in DB")

    # ---------------- fallback helpers ----------------
    def _load_fallback(self):
        try:
            with open(self.DATA_FALLBACK, "r") as f:
                self.fallback_gold = json.load(f) or {}
        except Exception:
            logger.exception("Failed to load fallback gold file")
            self.fallback_gold = {}

    def _save_fallback(self):
        try:
            with open(self.DATA_FALLBACK, "w") as f:
                json.dump(self.fallback_gold, f, indent=2)
        except Exception:
            logger.exception("Failed to save fallback gold file")

    # ---------------- civ helpers ----------------
    def _get_civ_via_bot(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Try to get civ using bot.civ_manager if available on the bot."""
        try:
            if self.bot and hasattr(self.bot, "civ_manager") and self.bot.civ_manager:
                # civ_manager should return a dict or None
                civ = self.bot.civ_manager.get_civilization(str(user_id))
                return civ
        except Exception:
            logger.exception("Error calling bot.civ_manager.get_civilization")
        return None

    def _get_civ_via_db(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Try to get civ using the provided Database instance."""
        try:
            if self.db and hasattr(self.db, "get_civilization"):
                civ = self.db.get_civilization(str(user_id))
                return civ
        except Exception:
            logger.exception("Error calling Database.get_civilization")
        return None

    def _update_civ_via_bot(self, user_id: str, civ: Dict[str, Any]) -> bool:
        """Try to update civ via bot.civ_manager if available."""
        try:
            if self.bot and hasattr(self.bot, "civ_manager") and self.bot.civ_manager:
                # prefer civ_manager.update_civilization if present
                if hasattr(self.bot.civ_manager, "update_civilization"):
                    return self.bot.civ_manager.update_civilization(str(user_id), civ)
        except Exception:
            logger.exception("Error calling bot.civ_manager.update_civilization")
        return False

    def _update_civ_via_db(self, user_id: str, civ: Dict[str, Any]) -> bool:
        """Try to update civ using the provided Database instance."""
        try:
            if self.db and hasattr(self.db, "update_civilization"):
                return self.db.update_civilization(str(user_id), civ)
        except Exception:
            logger.exception("Error calling Database.update_civilization")
        return False

    def _get_civ(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get a civilization for the user from bot.civ_manager or db if available."""
        # priority: bot.civ_manager -> db.get_civilization -> None
        civ = self._get_civ_via_bot(user_id)
        if civ:
            return civ
        civ = self._get_civ_via_db(user_id)
        if civ:
            return civ
        return None

    def _persist_civ(self, user_id: str, civ: Dict[str, Any]) -> bool:
        """Persist the updated civ using bot.civ_manager or db; return success."""
        # try bot civ_manager update first
        if self._update_civ_via_bot(user_id, civ):
            return True
        if self._update_civ_via_db(user_id, civ):
            return True
        return False

    # ---------------- gold operations (public) ----------------
    def get_gold(self, user_id: str) -> int:
        """
        Return current gold for the user's civ. If civ exists in DB, read from civ.resources.gold.
        If no civ/db available, fallback to local JSON cache.
        """
        try:
            civ = self._get_civ(user_id)
            if civ:
                resources = civ.get("resources", {})
                return int(resources.get("gold", 0))
        except Exception:
            logger.exception("get_gold via civ failed")
        # fallback
        return int(self.fallback_gold.get(str(user_id), 0))

    def set_gold(self, user_id: str, amount: int) -> bool:
        """
        Set the civ gold to amount. Returns True on success (persisted).
        If civ isn't available, writes to fallback JSON.
        """
        user_id = str(user_id)
        try:
            civ = self._get_civ(user_id)
            if civ is not None:
                resources = civ.get("resources", {})
                resources["gold"] = int(amount)
                civ["resources"] = resources
                if self._persist_civ(user_id, civ):
                    return True
            # fallback write
            self.fallback_gold[user_id] = int(amount)
            self._save_fallback()
            return True
        except Exception:
            logger.exception("set_gold failed")
            return False

    def add_gold(self, user_id: str, amount: int) -> bool:
        """Add amount to civ gold (amount may be negative for subtract)."""
        user_id = str(user_id)
        try:
            civ = self._get_civ(user_id)
            if civ is not None:
                resources = civ.get("resources", {})
                resources["gold"] = int(resources.get("gold", 0)) + int(amount)
                civ["resources"] = resources
                if self._persist_civ(user_id, civ):
                    return True
            # fallback
            curr = int(self.fallback_gold.get(user_id, 0))
            self.fallback_gold[user_id] = curr + int(amount)
            self._save_fallback()
            return True
        except Exception:
            logger.exception("add_gold failed")
            return False

    def try_withdraw_gold(self, user_id: str, amount: int) -> bool:
        """Attempt to withdraw gold. Returns True if enough funds and withdraw succeeded."""
        user_id = str(user_id)
        try:
            civ = self._get_civ(user_id)
            if civ is not None:
                resources = civ.get("resources", {})
                curr = int(resources.get("gold", 0))
                if curr >= int(amount):
                    resources["gold"] = curr - int(amount)
                    civ["resources"] = resources
                    if self._persist_civ(user_id, civ):
                        return True
                    # If persist fails, treat as fail to avoid desync
                    return False
                else:
                    return False
            # fallback
            curr = int(self.fallback_gold.get(user_id, 0))
            if curr >= int(amount):
                self.fallback_gold[user_id] = curr - int(amount)
                self._save_fallback()
                return True
            return False
        except Exception:
            logger.exception("try_withdraw_gold failed")
            return False

    # Inventory / products wrappers (DB-backed or fallback)
    def get_inventory(self, user_id: str) -> List[str]:
        try:
            if self.db and hasattr(self.db, "get_inventory"):
                return list(self.db.get_inventory(str(user_id)) or [])
        except Exception:
            logger.debug("db.get_inventory not used")
        # fallback: no inventory persistence? return empty or fallback store if present
        return []

    def update_inventory(self, user_id: str, items: List[str]) -> None:
        try:
            if self.db and hasattr(self.db, "update_inventory"):
                return self.db.update_inventory(str(user_id), items)
        except Exception:
            logger.debug("db.update_inventory not used")
        # fallback: no-op for now

    def get_products(self, user_id: str) -> Dict[str, Any]:
        try:
            if self.db and hasattr(self.db, "get_products"):
                return dict(self.db.get_products(str(user_id)) or {})
        except Exception:
            logger.debug("db.get_products not used")
        return {}

    def update_products(self, user_id: str, products: Dict[str, Any]) -> None:
        try:
            if self.db and hasattr(self.db, "update_products"):
                return self.db.update_products(str(user_id), products)
        except Exception:
            logger.debug("db.update_products not used")
        # fallback no-op


class EconomyCog(commands.Cog):
    """
    Guilded Cog providing economy commands. Integrates with EconomyManager.

    Cooldown policy:
    - default_cd_seconds = 60 for most commands (1 minute)
    - extrawork_cd_seconds = 300 (5 minutes, max allowed)
    - cooldowns applied only after successful execution
    """

    def __init__(self, bot: commands.Bot, db: Optional[Any] = None, storage_dir: str = "."):
        self.bot = bot
        self.manager = EconomyManager(storage_dir=storage_dir, db=db, bot=bot)
        # per-command, per-user last-used timestamps (command -> {user_id: ts})
        self.cooldowns: Dict[str, Dict[str, float]] = {}
        self.default_cd_seconds = 60  # most commands 1 minute
        self.extrawork_cd_seconds = 300  # 5 minutes max
        # background game state
        self.coding_tasks: Dict[str, tuple] = {}
        self.product_last_pay: Dict[str, Dict[str, float]] = {}
        self._tasks: List[asyncio.Task] = []

    # ---------------- lifecycle ----------------
    async def cog_load(self):
        loop = self.bot.loop
        self._tasks.append(loop.create_task(self._restock_shop_loop()))
        self._tasks.append(loop.create_task(self._crypto_miner_loop()))
        self._tasks.append(loop.create_task(self._swat_raid_loop()))
        self._tasks.append(loop.create_task(self._product_income_loop()))
        self._tasks.append(loop.create_task(self._coding_loop()))
        logger.info("EconomyCog: background tasks started")

    async def cog_unload(self):
        for t in self._tasks:
            try:
                t.cancel()
            except Exception:
                logger.exception("Failed to cancel task")
        self._tasks.clear()
        logger.info("EconomyCog: background tasks cancelled")

    # ---------------- cooldown helpers ----------------
    def _get_last(self, cmd_name: str, user_id: str) -> float:
        return self.cooldowns.get(cmd_name, {}).get(user_id, 0.0)

    def _set_last(self, cmd_name: str, user_id: str, ts: Optional[float] = None):
        ts = ts or time.time()
        self.cooldowns.setdefault(cmd_name, {})[user_id] = ts

    def _is_on_cooldown(self, cmd_name: str, user_id: str, cd_seconds: int) -> Optional[int]:
        """
        Returns None if not on cooldown; otherwise returns remaining seconds (int).
        """
        last = self._get_last(cmd_name, user_id)
        if last == 0.0:
            return None
        elapsed = time.time() - last
        if elapsed >= cd_seconds:
            return None
        return int(cd_seconds - elapsed)

    # ---------------- civ requirement ----------------
    def _user_has_civ_via_bot(self, user_id: str) -> bool:
        try:
            if hasattr(self.bot, "civ_manager") and self.bot.civ_manager:
                civ = self.bot.civ_manager.get_civilization(str(user_id))
                return civ is not None
        except Exception:
            logger.exception("Error checking civ via bot.civ_manager")
        return False

    def _user_has_civ_via_db(self, user_id: str) -> bool:
        try:
            if self.manager.db and hasattr(self.manager.db, "get_civilization"):
                civ = self.manager.db.get_civilization(str(user_id))
                return civ is not None
        except Exception:
            logger.exception("Error checking civ via Database.get_civilization")
        return False

    def user_has_civ(self, user_id: str) -> bool:
        if self._user_has_civ_via_bot(user_id):
            return True
        if self._user_has_civ_via_db(user_id):
            return True
        return False

    async def require_civ(self, ctx) -> bool:
        uid = str(ctx.author.id)
        if not self.user_has_civ(uid):
            await ctx.send("🚫 You need a civilization to use that command. Create one using your civ commands.")
            return False
        return True

    # ---------------- background coroutines ----------------
    async def _restock_shop_loop(self):
        try:
            while True:
                await asyncio.sleep(180)
                # shop stocks are ephemeral in-memory; restock by resetting defaults
                # (this could be moved into manager if persistent shop needed)
                # nothing to persist here
        except asyncio.CancelledError:
            return

    async def _crypto_miner_loop(self):
        try:
            while True:
                await asyncio.sleep(3600)
                # pay miners: iterate users with crypto_miner in their inventory (DB-backed if present)
                inv_map = {}
                try:
                    if self.manager.db and hasattr(self.manager.db, "get_all_inventories"):
                        inv_map = self.manager.db.get_all_inventories()
                    # else no inventories available; skip
                except Exception:
                    logger.debug("crypto miner loop: no DB inventories")
                    inv_map = {}
                try:
                    for suid, items in list(inv_map.items()):
                        if not isinstance(items, list):
                            continue
                        miner_count = sum(1 for i in items if i == "crypto_miner")
                        if miner_count > 0:
                            # pay 200 gold per miner hourly
                            self.manager.add_gold(suid, 200 * miner_count)
                except Exception:
                    logger.exception("crypto miner loop error")
        except asyncio.CancelledError:
            return

    async def _swat_raid_loop(self):
        try:
            while True:
                await asyncio.sleep(18000)
                # raids work against inventories in DB if available
                inv_map = {}
                try:
                    if self.manager.db and hasattr(self.manager.db, "get_all_inventories"):
                        inv_map = self.manager.db.get_all_inventories()
                except Exception:
                    inv_map = {}
                try:
                    for suid, items in list(inv_map.items()):
                        if self.manager.get_faction(suid) == "Criminal" and random.random() < 0.5:
                            loss = min(self.manager.get_gold(suid), random.randint(200, 1000))
                            if loss > 0:
                                self.manager.try_withdraw_gold(suid, loss)
                            inv = items[:] if isinstance(items, list) else []
                            illegal = {"ak", "ammo", "glock17", "explosives", "stolen_data", "forged_documents"}
                            inv = [i for i in inv if i not in illegal]
                            # persist inventory back to DB if possible
                            try:
                                if self.manager.db and hasattr(self.manager.db, "update_inventory"):
                                    self.manager.db.update_inventory(suid, inv)
                            except Exception:
                                logger.debug("Could not update inventory after raid")
                except Exception:
                    logger.exception("swat raid loop error")
        except asyncio.CancelledError:
            return

    async def _product_income_loop(self):
        try:
            while True:
                await asyncio.sleep(3600)
                now = time.time()
                prod_map = {}
                try:
                    if self.manager.db and hasattr(self.manager.db, "get_all_products"):
                        prod_map = self.manager.db.get_all_products()
                except Exception:
                    prod_map = {}
                try:
                    for suid, prods in list(prod_map.items()):
                        if not isinstance(prods, dict):
                            continue
                        if "messenger" in prods:
                            state = prods["messenger"]
                            last = self.product_last_pay.get(suid, {}).get("messenger", 0)
                            if state == "viral":
                                interval = 18000
                                if now - last >= interval:
                                    payout = random.randint(1000, 5000)
                                    self.manager.add_gold(suid, payout)
                                    self.product_last_pay.setdefault(suid, {})["messenger"] = now
                            else:
                                interval = 10800
                                if now - last >= interval:
                                    self.manager.add_gold(suid, 10)
                                    self.product_last_pay.setdefault(suid, {})["messenger"] = now
                except Exception:
                    logger.exception("product income loop error")
        except asyncio.CancelledError:
            return

    async def _coding_loop(self):
        try:
            while True:
                await asyncio.sleep(30)
                now = time.time()
                finished = []
                for suid, task in list(self.coding_tasks.items()):
                    proj, finish_ts = task
                    if now >= finish_ts:
                        finished.append((suid, proj))
                for suid, proj in finished:
                    if proj == "website":
                        self.manager.add_gold(suid, random.randint(50, 150))
                    elif proj == "virus":
                        if random.random() < 0.25:
                            logger.debug(f"Virus coder {suid} got caught.")
                        else:
                            self.manager.add_gold(suid, random.randint(250, 763))
                    elif proj == "messenger":
                        prods = self.manager.get_products(suid)
                        prods["messenger"] = "viral" if random.random() < 0.45 else "flop"
                        self.manager.update_products(suid, prods)
                    self.coding_tasks.pop(suid, None)
        except asyncio.CancelledError:
            return

    # --------------- UI helpers ---------------
    def build_shop_display(self) -> str:
        lines = ["🛒 Current Shop Stock (ephemeral):",
                 "- AK ($500) — 5 in stock",
                 "- AMMO ($100) — 10 in stock",
                 "- GLOCK17 ($800) — 5 in stock",
                 "- CRYPTO_MINER ($4000) — 2 in stock (produces gold hourly)"]
        lines.append("\nBuy with .buy [item] (requires civ).")
        return "\n".join(lines)

    def build_darkweb_display(self) -> str:
        lines = ["🌑 Dark Web Market (50% scam risk):",
                 "- forged_documents ($5000)",
                 "- stolen_data ($3000)",
                 "- silencer ($1500)",
                 "- explosives ($5000)",
                 "- crypto_miner ($3500)"]
        lines.append("\nUse .darkweb [item] to attempt a purchase (requires civ).")
        return "\n".join(lines)

    # ---------------- command implementations ----------------
    @commands.command()
    async def balance(self, ctx):
        """Show your civ gold balance. .balance"""
        try:
            uid = str(ctx.author.id)
            # balance view does not require a civ? we will require civ per earlier policy
            if not await self.require_civ(ctx):
                return
            bal = self.manager.get_gold(uid)
            await ctx.send(f"💰 Your civilization has {bal} gold.")
        except Exception:
            logger.exception("balance command failed")
            await ctx.send("❌ Failed to fetch balance. No cooldown applied.")

    @commands.command()
    async def profile(self, ctx, user: Optional[str] = None):
        """Show profile for yourself or other user (requires civ)."""
        try:
            target_id = str(ctx.author.id) if user is None else str(user)
            if not self.user_has_civ(target_id):
                await ctx.send("User does not have a civilization.")
                return
            civ = self.manager._get_civ(target_id)
            if not civ:
                await ctx.send("Could not load civilization.")
                return
            resources = civ.get("resources", {})
            gold = resources.get("gold", 0)
            name = civ.get("name", "Unknown")
            await ctx.send(f"👤 {name}\n💰 Gold: {gold}\nOther resources: {resources}")
        except Exception:
            logger.exception("profile command failed")
            await ctx.send("❌ Failed to fetch profile. No cooldown applied.")

    @commands.command()
    async def inventory(self, ctx):
        """Show inventory (if DB-backed)."""
        try:
            uid = str(ctx.author.id)
            if not await self.require_civ(ctx):
                return
            inv = self.manager.get_inventory(uid)
            await ctx.send(f"🎒 Inventory: {', '.join(inv) if inv else 'Empty'}")
        except Exception:
            logger.exception("inventory command failed")
            await ctx.send("❌ Failed to fetch inventory. No cooldown applied.")

    @commands.command()
    async def give(self, ctx, user: Optional[str] = None, amount: Optional[int] = None):
        """
        Give gold to another user's civilization. Usage: .give <recipient_user_id> <amount>
        Applies default cooldown (1 minute) only on successful transfer.
        """
        cmd = "give"
        uid = str(ctx.author.id)
        try:
            # argument checks
            if not await self.require_civ(ctx):
                return
            if user is None or amount is None:
                await ctx.send("Usage: .give <recipient_user_id> <amount> — No cooldown applied.")
                return
            recipient = str(user)
            if amount <= 0:
                await ctx.send("Amount must be positive. No cooldown applied.")
                return
            # check cooldown
            rem = self._is_on_cooldown(cmd, uid, self.default_cd_seconds)
            if rem:
                await ctx.send(f"⏳ You are on cooldown for {rem}s.")
                return
            # withdraw and add
            if not self.manager.try_withdraw_gold(uid, amount):
                await ctx.send("You don't have enough gold. No cooldown applied.")
                return
            # add to recipient
            self.manager.add_gold(recipient, amount)
            # success -> set cooldown
            self._set_last(cmd, uid)
            await ctx.send(f"✅ Transferred {amount} gold to {recipient}.")
        except Exception:
            logger.exception("give command error")
            await ctx.send("❌ Transfer failed due to an error. No cooldown applied.")

    @commands.command()
    async def shop(self, ctx):
        """Show shop (ephemeral)."""
        try:
            await ctx.send(self.build_shop_display())
        except Exception:
            logger.exception("shop command failed")
            await ctx.send("❌ Failed to show shop. No cooldown applied.")

    @commands.command(name="buy")
    async def buy_item(self, ctx, item: Optional[str] = None):
        """
        Buy an item from the shop. Usage: .buy <item>
        Default cooldown 1 minute applied only on success.
        """
        cmd = "buy"
        uid = str(ctx.author.id)
        try:
            if not await self.require_civ(ctx):
                return
            if item is None:
                await ctx.send("Usage: .buy <item>. No cooldown applied.")
                return
            # simple in-memory prices
            prices = {"ak": 500, "ammo": 100, "glock17": 800, "crypto_miner": 4000}
            item = item.lower()
            if item not in prices:
                await ctx.send("Item not found. No cooldown applied.")
                return
            rem = self._is_on_cooldown(cmd, uid, self.default_cd_seconds)
            if rem:
                await ctx.send(f"⏳ You are on cooldown for {rem}s.")
                return
            price = prices[item]
            if not self.manager.try_withdraw_gold(uid, price):
                await ctx.send("Not enough gold. No cooldown applied.")
                return
            # add to user's inventory (DB-backed)
            try:
                inv = self.manager.get_inventory(uid) or []
                inv.append(item)
                self.manager.update_inventory(uid, inv)
            except Exception:
                logger.debug("Failed to update inventory; still granting item in memory")
            self._set_last(cmd, uid)
            await ctx.send(f"✅ Purchased {item.upper()} for {price} gold.")
        except Exception:
            logger.exception("buy command failed")
            await ctx.send("❌ Purchase failed. No cooldown applied.")

    @commands.command()
    async def darkweb(self, ctx, item: Optional[str] = None):
        """
        Attempt to buy an item from the dark web. 50% scam chance.
        Usage: .darkweb <item>
        Default cooldown 1 minute applied on success only.
        """
        cmd = "darkweb"
        uid = str(ctx.author.id)
        try:
            if not await self.require_civ(ctx):
                return
            if item is None:
                await ctx.send(self.build_darkweb_display())
                return
            item = item.lower()
            prices = {"forged_documents": 5000, "stolen_data": 3000, "silencer": 1500, "explosives": 5000, "crypto_miner": 3500}
            if item not in prices:
                await ctx.send("Item not available. No cooldown applied.")
                return
            rem = self._is_on_cooldown(cmd, uid, self.default_cd_seconds)
            if rem:
                await ctx.send(f"⏳ You are on cooldown for {rem}s.")
                return
            price = prices[item]
            if not self.manager.try_withdraw_gold(uid, price):
                await ctx.send("You don't have enough gold. No cooldown applied.")
                return
            if random.random() < 0.5:
                inv = self.manager.get_inventory(uid) or []
                inv.append(item)
                self.manager.update_inventory(uid, inv)
                self._set_last(cmd, uid)
                await ctx.send(f"✅ Dark web purchase succeeded: acquired {item.upper()}.")
            else:
                # lost money, no item; still counts as executed -> set cooldown
                self._set_last(cmd, uid)
                await ctx.send(f"💀 Scammed. Lost {price} gold.")
        except Exception:
            logger.exception("darkweb command error")
            await ctx.send("❌ Darkweb purchase failed. No cooldown applied.")

    @commands.command()
    async def slots(self, ctx, amount: Optional[int] = None):
        """Slots gamble - default cooldown 1 minute, applied only on success."""
        cmd = "slots"
        uid = str(ctx.author.id)
        try:
            if not await self.require_civ(ctx):
                return
            if amount is None:
                await ctx.send("Usage: .slots <amount>. No cooldown applied.")
                return
            if amount <= 0:
                await ctx.send("Bet must be positive. No cooldown applied.")
                return
            rem = self._is_on_cooldown(cmd, uid, self.default_cd_seconds)
            if rem:
                await ctx.send(f"⏳ You are on cooldown for {rem}s.")
                return
            if amount > self.manager.get_gold(uid):
                await ctx.send("You don't have enough gold. No cooldown applied.")
                return
            # play
            symbols = ["🍒", "🍋", "🔔", "💎", "7️⃣"]
            result = [random.choice(symbols) for _ in range(3)]
            if result == ["7️⃣", "7️⃣", "7️⃣"]:
                win = amount * 10
                self.manager.add_gold(uid, win)
                self._set_last(cmd, uid)
                await ctx.send(f"{' '.join(result)}\n🎉 JACKPOT! You won {win} gold!")
            elif result.count(result[0]) == 3:
                win = amount * 2
                self.manager.add_gold(uid, win)
                self._set_last(cmd, uid)
                await ctx.send(f"{' '.join(result)}\nNice triple! You won {win} gold!")
            else:
                # lose bet (we do not withdraw here because bet wasn't withdrawn up-front)
                # withdraw now
                self.manager.try_withdraw_gold(uid, amount)
                self._set_last(cmd, uid)
                await ctx.send(f"{' '.join(result)}\nNo win. You lost {amount} gold.")
        except Exception:
            logger.exception("slots command error")
            await ctx.send("❌ Slots failed. No cooldown applied.")

    @commands.command()
    async def blackjack(self, ctx, amount: Optional[int] = None):
        """
        Blackjack simple implementation. Default cooldown 1 minute applied only on success.
        Usage: .blackjack <amount>
        """
        cmd = "blackjack"
        uid = str(ctx.author.id)
        try:
            if not await self.require_civ(ctx):
                return
            if amount is None:
                await ctx.send("Usage: .blackjack <amount>. No cooldown applied.")
                return
            if amount <= 0:
                await ctx.send("Bet must be positive. No cooldown applied.")
                return
            rem = self._is_on_cooldown(cmd, uid, self.default_cd_seconds)
            if rem:
                await ctx.send(f"⏳ You are on cooldown for {rem}s.")
                return
            if amount > self.manager.get_gold(uid):
                await ctx.send("Not enough gold. No cooldown applied.")
                return
            # simple compare sums
            player = [random.randint(2, 11), random.randint(2, 11)]
            dealer = [random.randint(2, 11), random.randint(2, 11)]
            p, d = sum(player), sum(dealer)
            if p > d:
                # pay amount (profit = amount)
                self.manager.add_gold(uid, amount)
                self._set_last(cmd, uid)
                await ctx.send(f"🃏 You win! {player} ({p}) vs {dealer} ({d}) — +{amount} gold.")
            elif p < d:
                # lose bet
                self.manager.try_withdraw_gold(uid, amount)
                self._set_last(cmd, uid)
                await ctx.send(f"🃏 Dealer wins. {player} ({p}) vs {dealer} ({d}) — you lost {amount} gold.")
            else:
                await ctx.send(f"🃏 Tie! {player} ({p}) vs {dealer} ({d}) — no change. No cooldown applied.")
        except Exception:
            logger.exception("blackjack command failed")
            await ctx.send("❌ Blackjack failed. No cooldown applied.")

    @commands.command()
    async def cards(self, ctx, amount: Optional[int] = None):
        """
        Cards mini-game. Default cooldown 1 minute applied only on success.
        Usage: .cards <amount>
        """
        cmd = "cards"
        uid = str(ctx.author.id)
        try:
            if not await self.require_civ(ctx):
                return
            if amount is None:
                await ctx.send("Usage: .cards <amount>. No cooldown applied.")
                return
            if amount <= 0:
                await ctx.send("Bet must be positive. No cooldown applied.")
                return
            rem = self._is_on_cooldown(cmd, uid, self.default_cd_seconds)
            if rem:
                await ctx.send(f"⏳ You are on cooldown for {rem}s.")
                return
            if amount > self.manager.get_gold(uid):
                await ctx.send("Not enough gold. No cooldown applied.")
                return
            you = random.randint(2, 14)
            botc = random.randint(2, 14)
            rank = {11: "J", 12: "Q", 13: "K", 14: "A"}
            y_label = rank.get(you, str(you))
            b_label = rank.get(botc, str(botc))
            if you > botc:
                self.manager.add_gold(uid, amount)
                self._set_last(cmd, uid)
                await ctx.send(f"🂡 You drew {y_label}, bot drew {b_label}. You win +{amount} gold!")
            elif you < botc:
                self.manager.try_withdraw_gold(uid, amount)
                self._set_last(cmd, uid)
                await ctx.send(f"🂱 You drew {y_label}, bot drew {b_label}. You lost {amount} gold.")
            else:
                await ctx.send(f"🂠 Both drew {y_label}. Tie — no change. No cooldown applied.")
        except Exception:
            logger.exception("cards command failed")
            await ctx.send("❌ Cards failed. No cooldown applied.")

    @commands.command()
    async def extragamble(self, ctx, amount: Optional[int] = None):
        """
        General gamble command replacing old `gamble`.
        Usage: .extragamble <amount>
        Mechanics:
          - 45% chance to lose your bet
          - 45% chance to double your bet
          - 10% chance to triple your bet
        Default cooldown 1 minute applied only on successful resolution (win or loss).
        """
        cmd = "extragamble"
        uid = str(ctx.author.id)
        try:
            if not await self.require_civ(ctx):
                return
            if amount is None:
                await ctx.send("Usage: .extragamble <amount>. No cooldown applied.")
                return
            if amount <= 0:
                await ctx.send("Bet must be positive. No cooldown applied.")
                return
            rem = self._is_on_cooldown(cmd, uid, self.default_cd_seconds)
            if rem:
                await ctx.send(f"⏳ You are on cooldown for {rem}s.")
                return
            if amount > self.manager.get_gold(uid):
                await ctx.send("Not enough gold. No cooldown applied.")
                return
            r = random.random()
            if r < 0.45:
                # lose
                self.manager.try_withdraw_gold(uid, amount)
                self._set_last(cmd, uid)
                await ctx.send(f"💸 You lost {amount} gold.")
            elif r < 0.90:
                # double
                self.manager.add_gold(uid, amount)
                self._set_last(cmd, uid)
                await ctx.send(f"🎉 You won {amount} gold (1x profit).")
            else:
                # triple
                self.manager.add_gold(uid, amount * 2)
                self._set_last(cmd, uid)
                await ctx.send(f"🎊 JACKPOT! You won {amount * 2} gold (2x profit).")
        except Exception:
            logger.exception("extragamble failed")
            await ctx.send("❌ Gambling failed. No cooldown applied.")

    @commands.command()
    async def jobs(self, ctx):
        try:
            # show available jobs - does not alter gold
            roles = {
                "bank": ["Teller", "Manager", "Executive"],
                "police": ["Recruit", "Officer", "Captain"],
                "security": ["Guard", "Supervisor", "Chief"],
                "government": ["Clerk", "Minister", "President", "Prime Minister"],
                "military": ["Private", "Sergeant", "Commander"]
            }
            text = ["📋 Available Jobs:"]
            for cat, rs in roles.items():
                text.append(f"- {cat.title()}: {', '.join(rs)}")
            await ctx.send("\n".join(text))
        except Exception:
            logger.exception("jobs failed")
            await ctx.send("❌ Failed to fetch jobs. No cooldown applied.")

    @commands.command()
    async def job(self, ctx, job_type: Optional[str] = None):
        """
        Apply for a job. Usage: .job <job_type>
        Default cooldown 1 minute on success.
        """
        cmd = "job"
        uid = str(ctx.author.id)
        try:
            if not await self.require_civ(ctx):
                return
            if job_type is None:
                await ctx.send("Usage: .job <job_type>. No cooldown applied.")
                return
            rem = self._is_on_cooldown(cmd, uid, self.default_cd_seconds)
            if rem:
                await ctx.send(f"⏳ You are on cooldown for {rem}s.")
                return
            jt = job_type.lower()
            mapping = {
                "bank": ["Rejected", "Teller", "Manager", "Executive"],
                "police": ["Rejected", "Recruit", "Officer", "Captain"],
                "security": ["Rejected", "Guard", "Supervisor", "Chief"],
                "government": ["Rejected", "Clerk", "Minister", "President", "Prime Minister"],
                "military": ["Rejected", "Private", "Sergeant", "Commander"]
            }
            if jt not in mapping:
                await ctx.send("Invalid job type. No cooldown applied.")
                return
            outcome = random.choice(mapping[jt])
            # store job on civ if possible by adding a 'job' field in civ.bonuses metadata
            civ = self.manager._get_civ(uid)
            if civ is not None:
                # Use civ['bonuses']['job'] or civ['job'] depending on structure
                try:
                    # prefer top-level job field if present
                    civ['job'] = outcome
                    self.manager._persist_civ(uid, civ)
                except Exception:
                    logger.debug("Could not persist job on civ")
            # set cooldown and inform user
            self._set_last(cmd, uid)
            if outcome == "Rejected":
                await ctx.send(f"😢 Application for {jt.title()} was rejected.")
            else:
                await ctx.send(f"🎉 You are now a {outcome} in {jt.title()}.")
        except Exception:
            logger.exception("job failed")
            await ctx.send("❌ Job application failed. No cooldown applied.")

    @commands.command()
    async def extrawork(self, ctx):
        """
        Work at your civ job and earn salary. Usage: .extrawork
        This uses a cooldown of 5 minutes (300 seconds).
        """
        cmd = "extrawork"
        uid = str(ctx.author.id)
        try:
            if not await self.require_civ(ctx):
                return
            rem = self._is_on_cooldown(cmd, uid, self.extrawork_cd_seconds)
            if rem:
                await ctx.send(f"⏳ You are on cooldown for {rem}s.")
                return
            # determine job and salary; job may be stored on civ['job'] or manager.get_faction fallback
            civ = self.manager._get_civ(uid)
            job_name = "Unemployed"
            if civ is not None:
                job_name = civ.get("job", job_name)
            if job_name == "Unemployed":
                await ctx.send("You need a job to work. Use .job to get one. No cooldown applied.")
                return
            # salary mapping (keeps within reasonable bounds)
            salary_map = {
                "Teller": 100, "Manager": 200, "Executive": 300,
                "Recruit": 150, "Officer": 250, "Captain": 350,
                "Guard": 120, "Supervisor": 220, "Chief": 320,
                "Clerk": 180, "Minister": 280, "President": 500, "Prime Minister": 600,
                "Private": 130, "Sergeant": 230, "Commander": 330
            }
            salary = salary_map.get(job_name, 50)
            self.manager.add_gold(uid, salary)
            self._set_last(cmd, uid)
            bal = self.manager.get_gold(uid)
            await ctx.send(f"💼 You earned {salary} gold as a {job_name}. Civ gold: {bal}.")
        except Exception:
            logger.exception("extrawork failed")
            await ctx.send("❌ Work failed. No cooldown applied.")

    @commands.command()
    async def arrest(self, ctx, target: Optional[str] = None):
        """
        Arrest another user's civ (police only). Usage: .arrest <target_user_id>
        Default cooldown 1 minute applied only on success.
        """
        cmd = "arrest"
        uid = str(ctx.author.id)
        try:
            if not await self.require_civ(ctx):
                return
            if target is None:
                await ctx.send("Usage: .arrest <target_user_id>. No cooldown applied.")
                return
            # check role: we examine civ.job field
            civ = self.manager._get_civ(uid)
            job = civ.get("job", "") if civ else ""
            if job.lower() not in ["recruit", "officer", "captain", "police"]:
                await ctx.send("🚫 Only police can arrest criminals. No cooldown applied.")
                return
            rem = self._is_on_cooldown(cmd, uid, self.default_cd_seconds)
            if rem:
                await ctx.send(f"⏳ You are on cooldown for {rem}s.")
                return
            # attempt arrest
            if random.random() < 0.6:
                if self.manager.try_withdraw_gold(target, 200):
                    self.manager.add_gold(uid, 200)
                    self._set_last(cmd, uid)
                    await ctx.send(f"🚓 Arrested {target} and seized 200 gold!")
                else:
                    self._set_last(cmd, uid)
                    await ctx.send(f"🚓 Arrested {target} but they had no funds.")
            else:
                await ctx.send("❌ Arrest failed. No cooldown applied.")
        except Exception:
            logger.exception("arrest failed")
            await ctx.send("❌ Arrest failed due to an error. No cooldown applied.")

    @commands.command()
    async def rob(self, ctx, target: Optional[str] = None):
        """
        Rob another user's civ (criminals only). Usage: .rob <target_user_id>
        Default cooldown 1 minute on success.
        """
        cmd = "rob"
        uid = str(ctx.author.id)
        try:
            if not await self.require_civ(ctx):
                return
            if target is None:
                await ctx.send("Usage: .rob <target_user_id>. No cooldown applied.")
                return
            civ = self.manager._get_civ(uid)
            job = civ.get("job", "") if civ else ""
            # criminals are civs without standard jobs (simple heuristic)
            if job.lower() in ["teller", "manager", "executive", "recruit", "officer", "captain",
                               "guard", "supervisor", "chief", "clerk", "minister", "president",
                               "prime minister", "private", "sergeant", "commander"]:
                await ctx.send("🚫 Only criminals can rob others. No cooldown applied.")
                return
            rem = self._is_on_cooldown(cmd, uid, self.default_cd_seconds)
            if rem:
                await ctx.send(f"⏳ You are on cooldown for {rem}s.")
                return
            if random.random() < 0.5:
                stolen = random.randint(100, 300)
                if self.manager.try_withdraw_gold(target, stolen):
                    self.manager.add_gold(uid, stolen)
                    self._set_last(cmd, uid)
                    await ctx.send(f"💸 Robbed {target} for {stolen} gold!")
                else:
                    await ctx.send("Target has insufficient funds. No cooldown applied.")
            else:
                await ctx.send("❌ Robbery failed. No cooldown applied.")
        except Exception:
            logger.exception("rob failed")
            await ctx.send("❌ Rob failed due to an error. No cooldown applied.")

    @commands.command()
    async def code(self, ctx, project: Optional[str] = None):
        """
        Start a coding project. Costs gold up-front; no cooldown enforced here beyond 1 minute if started.
        Projects:
          - virus: cost 250, 25 min (kept as background task timeframe)
          - website: cost 50, 10 min
          - messenger: cost 3500, 5 hours
        """
        cmd = "code"
        uid = str(ctx.author.id)
        try:
            if not await self.require_civ(ctx):
                return
            if project is None:
                await ctx.send(
                    "💻 Coding Projects:\n"
                    ".code virus — 250 gold, finishes in ~25 min\n"
                    ".code website — 50 gold, finishes in ~10 min\n"
                    ".code messenger — 3500 gold, finishes in ~5 hours"
                )
                return
            rem = self._is_on_cooldown(cmd, uid, self.default_cd_seconds)
            if rem:
                await ctx.send(f"⏳ You are on cooldown for {rem}s.")
                return
            p = project.lower()
            if p == "virus":
                cost = 250
                duration = 1500
            elif p == "website":
                cost = 50
                duration = 600
            elif p == "messenger":
                cost = 3500
                duration = 18000
            else:
                await ctx.send("Unknown project. No cooldown applied.")
                return
            if not self.manager.try_withdraw_gold(uid, cost):
                await ctx.send("Not enough gold. No cooldown applied.")
                return
            # schedule task
            self.coding_tasks[self.manager.uid(uid)] = (p, time.time() + duration)
            self._set_last(cmd, uid)
            await ctx.send(f"🛠️ Started coding {p}. It will finish in approx {int(duration/60)} minutes.")
        except Exception:
            logger.exception("code failed")
            await ctx.send("❌ Code command failed. No cooldown applied.")

    @commands.command()
    async def setbalance(self, ctx, amount: Optional[int] = None):
        """
        Admin command to set your civ gold. Usage: .setbalance <amount>
        This modifies the civ's gold (not a separate cash value).
        """
        uid = str(ctx.author.id)
        try:
            allowed_ids = os.getenv("ADMIN_ALLOWED_IDS", "mpGYeq9d,mL2MM1N4").split(",")
            if str(ctx.author.id) not in allowed_ids:
                await ctx.send("❌ You don't have permission to use this command.")
                return
            if amount is None:
                await ctx.send("Usage: .setbalance <amount>. No cooldown applied.")
                return
            if amount < 0:
                await ctx.send("Amount must be non-negative. No cooldown applied.")
                return
            if not await self.require_civ(ctx):
                return
            self.manager.set_gold(uid, int(amount))
            await ctx.send(f"✅ Civ gold set to {amount}.")
        except Exception:
            logger.exception("setbalance failed")
            await ctx.send("❌ Failed to set balance. No cooldown applied.")

    # ---------------- setup helper ----------------
def setup(bot: commands.Bot, db: Optional[Any] = None, storage_dir: str = "."):
    """
    Register the cog.

    Call from your main.py (after creating Database and civ manager):
        from bot.commands.ExtraEconomy import setup as setup_extra_economy
        setup_extra_economy(self, db=self.db, storage_dir="./data")
    """
    cog = EconomyCog(bot, db=db, storage_dir=storage_dir)
    bot.add_cog(cog)
    logger.info("EconomyCog registered (ExtraEconomy).")


__all__ = ["EconomyManager", "EconomyCog", "setup"]