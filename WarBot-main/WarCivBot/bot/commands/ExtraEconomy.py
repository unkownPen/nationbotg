"""
Economy cog for Guilded bot.

This file provides:
- EconomyManager: pure logic + JSON persistence (balances, jobs, inventory, products).
- EconomyCog: a guilded.ext.commands.Cog exposing economy commands and starting background loops.

Usage:
    from bot.economy import EconomyCog
    bot.add_cog(EconomyCog(bot, db=None))

If you have a Database abstraction you want to use instead of JSON files,
pass it as db=YourDatabaseInstance to EconomyCog; it must implement the methods
used in the manager (optional). By default JSON files are used for persistence.
"""
import os
import json
import random
import time
import logging
from threading import Thread, Lock
from typing import Dict, Any, Optional

from flask import Flask
from guilded.ext import commands

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# -----------------------
# EconomyManager (persistence + logic)
# -----------------------
class EconomyManager:
    def __init__(self, storage_dir: str = ".", db: Optional[Any] = None):
        """
        :param storage_dir: Directory to store JSON files
        :param db: Optional external Database object; if provided, manager will prefer db operations.
        """
        self.db = db
        self.storage_dir = storage_dir
        self.lock = Lock()

        # JSON filenames
        self.DATA_BAL = os.path.join(storage_dir, "user_balances.json")
        self.DATA_JOB = os.path.join(storage_dir, "user_jobs.json")
        self.DATA_INV = os.path.join(storage_dir, "user_inventory.json")
        self.DATA_PROD = os.path.join(storage_dir, "user_products.json")

        # Load state (if not using db)
        if not self.db:
            self.user_balances = self._load_json(self.DATA_BAL)
            self.user_jobs = self._load_json(self.DATA_JOB)
            self.user_inventory = self._load_json(self.DATA_INV)
            self.user_products = self._load_json(self.DATA_PROD)
        else:
            # If using an external db, these caches are not used
            self.user_balances = {}
            self.user_jobs = {}
            self.user_inventory = {}
            self.user_products = {}

        # game state
        self.job_roles = {
            "bank": ["Rejected", "Teller", "Manager", "Executive"],
            "police": ["Rejected", "Recruit", "Officer", "Captain"],
            "security": ["Rejected", "Guard", "Supervisor", "Chief"],
            "government": ["Rejected", "Clerk", "Minister", "President", "Prime Minister"],
            "military": ["Rejected", "Private", "Sergeant", "Commander"]
        }
        self.job_salaries = {
            "Teller": 100, "Manager": 200, "Executive": 300,
            "Recruit": 150, "Officer": 250, "Captain": 350,
            "Guard": 120, "Supervisor": 220, "Chief": 320,
            "Clerk": 180, "Minister": 280, "President": 500, "Prime Minister": 600,
            "Private": 130, "Sergeant": 230, "Commander": 330
        }

        self.shop_items = {
            "ak": {"price": 500, "stock": 5},
            "ammo": {"price": 100, "stock": 10},
            "glock17": {"price": 800, "stock": 5},
            "crypto_miner": {"price": 4000, "stock": 2}
        }

        self.darkweb_items = {
            "forged_documents": {"price": 5000, "desc": "High-quality forgeries"},
            "stolen_data": {"price": 3000, "desc": "Leaked sensitive datasets"},
            "silencer": {"price": 1500, "desc": "Reduces report of firearms"},
            "explosives": {"price": 5000, "desc": "Illicit demolition materials"},
            "crypto_miner": {"price": 3500, "desc": "Cheaper, shady miner hardware"}
        }

    # --- Persistence helpers (JSON) ---
    def _load_json(self, path: str) -> dict:
        try:
            if not os.path.exists(path):
                with open(path, "w") as f:
                    json.dump({}, f)
            with open(path, "r") as f:
                return json.load(f) or {}
        except Exception:
            logger.exception("Failed to load JSON %s", path)
            return {}

    def _save_json(self, path: str, data: dict) -> None:
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            logger.exception("Failed to save JSON %s", path)

    # --- Generic DB wrappers: if self.db provided, prefer that interface (not implemented here) ---
    def _get_state(self, key: str):
        if self.db:
            try:
                return self.db.get_state(key)
            except Exception:
                logger.exception("db.get_state failed")
                return {}
        else:
            return getattr(self, key)

    def _save_state(self, key: str, data: dict):
        if self.db:
            try:
                return self.db.save_state(key, data)
            except Exception:
                logger.exception("db.save_state failed")
                return False
        else:
            setattr(self, key, data)
            # persist corresponding file
            if key == "user_balances":
                self._save_json(self.DATA_BAL, data)
            elif key == "user_jobs":
                self._save_json(self.DATA_JOB, data)
            elif key == "user_inventory":
                self._save_json(self.DATA_INV, data)
            elif key == "user_products":
                self._save_json(self.DATA_PROD, data)
            return True

    # --- Utility functions ---
    def uid(self, user_id) -> str:
        return str(user_id)

    # --- User ensure & simple CRUD ---
    def ensure_user(self, user_id):
        suid = self.uid(user_id)
        with self.lock:
            if not self.db:
                if suid not in self.user_balances:
                    self.user_balances[suid] = 500
                    self._save_state("user_balances", self.user_balances)
                if suid not in self.user_jobs:
                    self.user_jobs[suid] = "Unemployed"
                    self._save_state("user_jobs", self.user_jobs)
                if suid not in self.user_inventory:
                    self.user_inventory[suid] = []
                    self._save_state("user_inventory", self.user_inventory)
                if suid not in self.user_products:
                    self.user_products[suid] = {}
                    self._save_state("user_products", self.user_products)
            else:
                # If using external DB, call db.ensure_user if available
                try:
                    if hasattr(self.db, "ensure_user"):
                        self.db.ensure_user(suid)
                except Exception:
                    logger.exception("db.ensure_user failed")

    def get_balance(self, user_id) -> int:
        self.ensure_user(user_id)
        if self.db:
            try:
                return int(self.db.get_balance(self.uid(user_id)))
            except Exception:
                logger.exception("db.get_balance failed")
                return 0
        return int(self.user_balances.get(self.uid(user_id), 0))

    def update_balance(self, user_id, amount) -> None:
        self.ensure_user(user_id)
        if self.db:
            try:
                return self.db.update_balance(self.uid(user_id), int(amount))
            except Exception:
                logger.exception("db.update_balance failed")
                return
        with self.lock:
            self.user_balances[self.uid(user_id)] = int(amount)
            self._save_state("user_balances", self.user_balances)

    def add_money(self, user_id, amount) -> None:
        self.ensure_user(user_id)
        if self.db:
            try:
                return self.db.add_money(self.uid(user_id), int(amount))
            except Exception:
                logger.exception("db.add_money failed")
                return
        with self.lock:
            curr = int(self.user_balances.get(self.uid(user_id), 0))
            self.user_balances[self.uid(user_id)] = curr + int(amount)
            self._save_state("user_balances", self.user_balances)

    def try_withdraw(self, user_id, amount) -> bool:
        self.ensure_user(user_id)
        if self.db:
            try:
                return self.db.try_withdraw(self.uid(user_id), int(amount))
            except Exception:
                logger.exception("db.try_withdraw failed")
                return False
        with self.lock:
            curr = int(self.user_balances.get(self.uid(user_id), 0))
            if curr >= int(amount):
                self.user_balances[self.uid(user_id)] = curr - int(amount)
                self._save_state("user_balances", self.user_balances)
                return True
            return False

    def update_inventory(self, user_id, items) -> None:
        self.ensure_user(user_id)
        if self.db:
            try:
                return self.db.update_inventory(self.uid(user_id), items)
            except Exception:
                logger.exception("db.update_inventory failed")
                return
        with self.lock:
            self.user_inventory[self.uid(user_id)] = items
            self._save_state("user_inventory", self.user_inventory)

    def get_inventory(self, user_id):
        self.ensure_user(user_id)
        if self.db:
            try:
                return self.db.get_inventory(self.uid(user_id))
            except Exception:
                logger.exception("db.get_inventory failed")
                return []
        return list(self.user_inventory.get(self.uid(user_id), []))

    def update_job(self, user_id, job_name) -> None:
        self.ensure_user(user_id)
        if self.db:
            try:
                return self.db.update_job(self.uid(user_id), job_name)
            except Exception:
                logger.exception("db.update_job failed")
                return
        with self.lock:
            self.user_jobs[self.uid(user_id)] = job_name
            self._save_state("user_jobs", self.user_jobs)

    def get_job(self, user_id):
        self.ensure_user(user_id)
        if self.db:
            try:
                return self.db.get_job(self.uid(user_id))
            except Exception:
                logger.exception("db.get_job failed")
                return "Unemployed"
        return self.user_jobs.get(self.uid(user_id), "Unemployed")

    def get_products(self, user_id):
        self.ensure_user(user_id)
        if self.db:
            try:
                return self.db.get_products(self.uid(user_id))
            except Exception:
                logger.exception("db.get_products failed")
                return {}
        return self.user_products.get(self.uid(user_id), {})

    def update_products(self, user_id, products):
        self.ensure_user(user_id)
        if self.db:
            try:
                return self.db.update_products(self.uid(user_id), products)
            except Exception:
                logger.exception("db.update_products failed")
                return
        with self.lock:
            self.user_products[self.uid(user_id)] = products
            self._save_state("user_products", self.user_products)

    # --- Faction detection similar to original code ---
    def get_faction(self, user_id) -> str:
        job = self.get_job(user_id)
        if job in ["Teller", "Manager", "Executive"]:
            return "Bank"
        if job in ["Recruit", "Officer", "Captain"]:
            return "Police"
        if job in ["Guard", "Supervisor", "Chief"]:
            return "Security"
        if job in ["Clerk", "Minister", "President", "Prime Minister"]:
            return "Government"
        if job in ["Private", "Sergeant", "Commander"]:
            return "Military"
        return "Criminal"

# -----------------------
# EconomyCog - Guilded commands
# -----------------------
class EconomyCog(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Optional[Any] = None, storage_dir: str = "."):
        self.bot = bot
        self.manager = EconomyManager(storage_dir=storage_dir, db=db)

        # background state
        self.last_work_time = {}            # per-user cooldown for /work
        self.coding_tasks = {}              # uid -> (project, finish_ts)
        self.product_last_pay = {}          # uid -> {product_name: ts}

        # start background loops (daemon)
        Thread(target=self._restock_shop_loop, daemon=True).start()
        Thread(target=self._crypto_miner_loop, daemon=True).start()
        Thread(target=self._swat_raid_loop, daemon=True).start()
        Thread(target=self._product_income_loop, daemon=True).start()
        Thread(target=self._coding_loop, daemon=True).start()

        # start webserver for uptime (optional)
        Thread(target=self._run_web, daemon=True).start()

    # ---------------- background loops ----------------
    def _restock_shop_loop(self):
        while True:
            time.sleep(180)  # 3 minutes
            self.manager.shop_items["ak"]["stock"] = 5
            self.manager.shop_items["ammo"]["stock"] = 10
            self.manager.shop_items["glock17"]["stock"] = 5
            self.manager.shop_items["crypto_miner"]["stock"] = 2
            logger.debug("Shop restocked.")

    def _crypto_miner_loop(self):
        while True:
            time.sleep(3600)  # 1 hour
            # give each miner owner payout (simple)
            inv_map = self.manager._get_state("user_inventory") if not self.manager.db else self.manager.db.get_all_inventories()
            try:
                for suid, items in list(inv_map.items()):
                    if not isinstance(items, list):
                        continue
                    miner_count = sum(1 for i in items if i == "crypto_miner")
                    if miner_count > 0:
                        self.manager.add_money(suid, 200 * miner_count)
                        logger.debug(f"Crypto miners paid ${200 * miner_count} to {suid}")
            except Exception:
                logger.exception("crypto miner loop error")

    def _swat_raid_loop(self):
        while True:
            time.sleep(18000)  # 5 hours
            inv_map = self.manager._get_state("user_inventory") if not self.manager.db else self.manager.db.get_all_inventories()
            try:
                for suid, items in list(inv_map.items()):
                    if self.manager.get_faction(suid) == "Criminal" and random.random() < 0.5:
                        loss = min(self.manager.get_balance(suid), random.randint(200, 1000))
                        if loss > 0:
                            self.manager.try_withdraw(suid, loss)
                        inv = items[:] if isinstance(items, list) else []
                        illegal = {"ak", "ammo", "glock17", "explosives", "stolen_data", "forged_documents"}
                        inv = [i for i in inv if i not in illegal]
                        self.manager.update_inventory(suid, inv)
                        logger.debug(f"SWAT raided {suid}, seized ${loss} and contraband.")
            except Exception:
                logger.exception("swat raid loop error")

    def _product_income_loop(self):
        while True:
            time.sleep(3600)  # hourly check (adjust to your needs)
            now = time.time()
            products_map = self.manager._get_state("user_products") if not self.manager.db else self.manager.db.get_all_products()
            try:
                for suid, prods in list(products_map.items()):
                    if not isinstance(prods, dict):
                        continue
                    if "messenger" in prods:
                        state = prods["messenger"]
                        last = self.product_last_pay.get(suid, {}).get("messenger", 0)
                        if state == "viral":
                            interval = 18000  # 5 hours
                            if now - last >= interval:
                                payout = random.randint(1000, 5000)
                                self.manager.add_money(suid, payout)
                                self.product_last_pay.setdefault(suid, {})["messenger"] = now
                                logger.debug(f"Messenger viral payout ${payout} -> {suid}")
                        else:
                            interval = 10800
                            if now - last >= interval:
                                self.manager.add_money(suid, 10)
                                self.product_last_pay.setdefault(suid, {})["messenger"] = now
                                logger.debug(f"Messenger flop payout $10 -> {suid}")
            except Exception:
                logger.exception("product income loop error")

    def _coding_loop(self):
        while True:
            time.sleep(30)
            now = time.time()
            finished = []
            for suid, task in list(self.coding_tasks.items()):
                proj, finish_ts = task
                if now >= finish_ts:
                    finished.append((suid, proj))
            for suid, proj in finished:
                if proj == "website":
                    self.manager.add_money(suid, random.randint(50, 150))
                elif proj == "virus":
                    # 25% chance police catch (simple log)
                    if random.random() < 0.25:
                        logger.debug(f"Virus coder {suid} got caught.")
                    else:
                        self.manager.add_money(suid, random.randint(250, 763))
                elif proj == "messenger":
                    prods = self.manager.get_products(suid)
                    prods["messenger"] = "viral" if random.random() < 0.45 else "flop"
                    self.manager.update_products(suid, prods)
                self.coding_tasks.pop(suid, None)
                logger.debug(f"Coding finished for {suid}: {proj}")

    # ---------------- webserver for uptime ----------------
    def _run_web(self):
        app = Flask("economy_uptime")
        @app.route("/")
        def home():
            return "Economy Cog running."
        try:
            app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
        except Exception:
            logger.exception("Web server failed to start (likely in non-blocking environment).")

    # ---------------- Helpers for UI ----------------
    def build_shop_display(self) -> str:
        lines = ["🛒 Current Shop Stock:"]
        for name, data in self.manager.shop_items.items():
            extra = " ⛏️ $200/hour" if name == "crypto_miner" else ""
            lines.append(f"- {name.upper()} (${data['price']}) — {data['stock']} in stock{extra}")
        return "\n".join(lines)

    def build_darkweb_display(self) -> str:
        lines = ["🌑 Dark Web Market (50% scam risk):"]
        for name, data in self.manager.darkweb_items.items():
            lines.append(f"- {name.upper()} (${data['price']}) — {data['desc']}")
        lines.append("\nUse /darkweb [item] to attempt a purchase.")
        return "\n".join(lines)

    # ---------------- Commands ----------------
    @commands.command()
    async def help(self, ctx):
        await ctx.send(
            "📜 Commands:\n"
            "/balance — Check your money\n"
            "/profile [user] — View profile\n"
            "/inventory — View your items\n"
            "/give [user] [amount] — Send money\n"
            "/shop — View shop items\n"
            "/buy [item] — Buy from shop\n"
            "/darkweb [item]? — View or attempt shady purchase (50% scam)\n"
            "/slots [amount] — Slots with bet (no loss on fail)\n"
            "/blackjack [amount] — Beat dealer to win (no loss on fail)\n"
            "/cards [amount] — High card wins (no loss on fail)\n"
            "/jobs — List job categories\n"
            "/job [type] — Apply for a job\n"
            "/work — Earn salary every 20 min\n"
            "/arrest [user] — Police perk\n"
            "/rob [user] — Criminal perk\n"
            "/code — List coding projects"
        )

    @commands.command()
    async def balance(self, ctx):
        self.manager.ensure_user(ctx.author.id)
        bal = self.manager.get_balance(ctx.author.id)
        if bal < 0:
            await ctx.send(f"💸 You are in debt by ${abs(bal)}.")
        elif bal == 0:
            await ctx.send("💵 You currently have $0.")
        else:
            await ctx.send(f"💵 Your balance is ${bal}.")

    @commands.command()
    async def profile(self, ctx, user: Optional[str] = None):
        target = str(ctx.author.id) if user is None else str(user)
        self.manager.ensure_user(target)
        bal = self.manager.get_balance(target)
        job = self.manager.get_job(target)
        inv = self.manager.get_inventory(target)
        prods = self.manager.get_products(target) or {}
        prod_line = f"Messenger: {prods.get('messenger')}" if "messenger" in prods else "None"
        await ctx.send(
            f"👤 Profile for {user or ctx.author.name}:\n"
            f"💰 Balance: ${bal}\n"
            f"🧑‍💼 Job: {job}\n"
            f"🎒 Inventory: {', '.join(inv) if inv else 'None'}\n"
            f"🏭 Products: {prod_line}"
        )

    @commands.command()
    async def inventory(self, ctx):
        self.manager.ensure_user(ctx.author.id)
        items = self.manager.get_inventory(ctx.author.id)
        await ctx.send(f"🎒 Your inventory: {', '.join(items) if items else 'Empty'}")

    @commands.command()
    async def give(self, ctx, user: str, amount: int):
        self.manager.ensure_user(ctx.author.id)
        self.manager.ensure_user(user)
        if amount <= 0:
            await ctx.send("Amount must be positive.")
            return
        if self.manager.try_withdraw(ctx.author.id, amount):
            self.manager.add_money(user, amount)
            await ctx.send(f"💸 You gave ${amount} to {user}.")
        else:
            await ctx.send("You don't have enough money.")

    @commands.command()
    async def shop(self, ctx):
        await ctx.send(self.build_shop_display())

    @commands.command(name="buy")
    async def buy_item(self, ctx, item: str):
        self.manager.ensure_user(ctx.author.id)
        item = item.lower()
        if item not in self.manager.shop_items:
            await ctx.send("❌ Item not found.")
            return
        if self.manager.shop_items[item]["stock"] <= 0:
            await ctx.send(f"⛔ {item.upper()} is out of stock. Wait for restock.")
            return
        price = self.manager.shop_items[item]["price"]
        if self.manager.try_withdraw(ctx.author.id, price):
            inv = self.manager.get_inventory(ctx.author.id)
            inv.append(item)
            self.manager.update_inventory(ctx.author.id, inv)
            self.manager.shop_items[item]["stock"] -= 1
            await ctx.send(f"✅ Purchased {item.upper()} for ${price}.")
        else:
            await ctx.send("💸 Not enough money.")

    @commands.command()
    async def darkweb(self, ctx, item: Optional[str] = None):
        self.manager.ensure_user(ctx.author.id)
        if item is None:
            await ctx.send(self.build_darkweb_display())
            return
        item = item.lower()
        if item not in self.manager.darkweb_items:
            await ctx.send("❌ Not available on the dark web.")
            return
        price = self.manager.darkweb_items[item]["price"]
        if not self.manager.try_withdraw(ctx.author.id, price):
            await ctx.send("💸 You don't have enough for this shady deal.")
            return
        if random.random() < 0.5:
            inv = self.manager.get_inventory(ctx.author.id)
            inv.append(item)
            self.manager.update_inventory(ctx.author.id, inv)
            await ctx.send(f"✅ Success. Acquired {item.upper()}.")
        else:
            await ctx.send(f"💀 Scammed. Lost ${price} with nothing to show.")

    @commands.command()
    async def slots(self, ctx, amount: int):
        self.manager.ensure_user(ctx.author.id)
        if amount <= 0:
            await ctx.send("Bet must be positive.")
            return
        if amount > self.manager.get_balance(ctx.author.id):
            await ctx.send("You don't have enough money to bet that.")
            return
        symbols = ["🍒", "🍋", "🔔", "💎", "7️⃣"]
        result = [random.choice(symbols) for _ in range(3)]
        if result == ["7️⃣", "7️⃣", "7️⃣"]:
            win = amount * 10
            self.manager.add_money(ctx.author.id, win)
            await ctx.send(f"{' '.join(result)}\n🎉 JACKPOT! You won ${win}!")
        elif result.count(result[0]) == 3:
            win = amount * 2
            self.manager.add_money(ctx.author.id, win)
            await ctx.send(f"{' '.join(result)}\nNice triple! You won ${win}!")
        else:
            await ctx.send(f"{' '.join(result)}\nNo win. You keep your money.")

    @commands.command()
    async def blackjack(self, ctx, amount: int):
        self.manager.ensure_user(ctx.author.id)
        if amount <= 0:
            await ctx.send("Bet must be positive.")
            return
        if amount > self.manager.get_balance(ctx.author.id):
            await ctx.send("Not enough money to bet.")
            return
        player = [random.randint(2, 11), random.randint(2, 11)]
        dealer = [random.randint(2, 11), random.randint(2, 11)]
        p, d = sum(player), sum(dealer)
        if p > d:
            self.manager.add_money(ctx.author.id, amount)
            await ctx.send(f"🃏 You win! {player} ({p}) vs {dealer} ({d}) — +${amount}")
        elif p < d:
            await ctx.send(f"🃏 Dealer wins! {player} ({p}) vs {dealer} ({d}) — no loss")
        else:
            await ctx.send(f"🃏 Tie! {player} ({p}) vs {dealer} ({d}) — no change")

    @commands.command()
    async def cards(self, ctx, amount: int):
        self.manager.ensure_user(ctx.author.id)
        if amount <= 0:
            await ctx.send("Bet must be positive.")
            return
        if amount > self.manager.get_balance(ctx.author.id):
            await ctx.send("Not enough money to bet that.")
            return
        you = random.randint(2, 14)
        botc = random.randint(2, 14)
        rank = {11: "J", 12: "Q", 13: "K", 14: "A"}
        y_label = rank.get(you, str(you))
        b_label = rank.get(botc, str(botc))
        if you > botc:
            self.manager.add_money(ctx.author.id, amount)
            await ctx.send(f"🂡 You drew {y_label}, bot drew {b_label}. You win +${amount}!")
        elif you < botc:
            await ctx.send(f"🂱 You drew {y_label}, bot drew {b_label}. You lose — no money lost.")
        else:
            await ctx.send(f"🂠 Both drew {y_label}. Tie — no change.")

    # Jobs
    @commands.command()
    async def jobs(self, ctx):
        text = ["📋 Available Jobs:"]
        for cat, roles in self.manager.job_roles.items():
            text.append(f"- {cat.title()}: {', '.join(roles[1:])}")
        await ctx.send("\n".join(text))

    @commands.command()
    async def job(self, ctx, job_type: str):
        self.manager.ensure_user(ctx.author.id)
        jt = job_type.lower()
        if jt not in self.manager.job_roles:
            await ctx.send("❌ Invalid job type.")
            return
        outcome = random.choice(self.manager.job_roles[jt])
        self.manager.update_job(ctx.author.id, outcome)
        if outcome == "Rejected":
            await ctx.send(f"😢 Application for {jt.title()} was rejected.")
        else:
            await ctx.send(f"🎉 You are now a {outcome} in {jt.title()}.")

    @commands.command()
    async def work(self, ctx):
        self.manager.ensure_user(ctx.author.id)
        user_id = ctx.author.id
        now = time.time()
        job_name = self.manager.get_job(user_id)
        if job_name == "Unemployed":
            await ctx.send("You need a job to work.")
            return
        if user_id in self.last_work_time and now - self.last_work_time[user_id] < 1200:
            remaining = int(1200 - (now - self.last_work_time[user_id]))
            await ctx.send(f"⏳ Wait {remaining // 60}m {remaining % 60}s before working again.")
            return
        salary = self.manager.job_salaries.get(job_name, 50)
        self.manager.add_money(user_id, salary)
        self.last_work_time[user_id] = now
        await ctx.send(f"💼 You earned ${salary} as a {job_name}. Balance: ${self.manager.get_balance(user_id)}")

    @commands.command()
    async def arrest(self, ctx, target: str):
        self.manager.ensure_user(ctx.author.id)
        if self.manager.get_faction(ctx.author.id) != "Police":
            await ctx.send("🚫 Only police can arrest criminals.")
            return
        if random.random() < 0.6:
            try:
                # attempt to seize $200 from target
                if self.manager.try_withdraw(target, 200):
                    self.manager.add_money(ctx.author.id, 200)
                    await ctx.send(f"🚓 Arrested {target} and seized $200!")
                else:
                    await ctx.send(f"🚓 Arrested {target} but they had no funds.")
            except Exception:
                await ctx.send("❌ Arrest attempt failed due to an error.")
                logger.exception("arrest command error")
        else:
            await ctx.send("❌ Arrest failed.")

    @commands.command()
    async def rob(self, ctx, target: str):
        self.manager.ensure_user(ctx.author.id)
        if self.manager.get_faction(ctx.author.id) != "Criminal":
            await ctx.send("🚫 Only criminals can rob others.")
            return
        if random.random() < 0.5:
            stolen = random.randint(100, 300)
            if self.manager.try_withdraw(target, stolen):
                self.manager.add_money(ctx.author.id, stolen)
                await ctx.send(f"💸 Robbed {target} for ${stolen}!")
            else:
                await ctx.send("Target has insufficient funds.")
        else:
            await ctx.send("❌ Robbery failed.")

    # Coding projects
    @commands.command()
    async def code(self, ctx, project: Optional[str] = None):
        self.manager.ensure_user(ctx.author.id)
        if project is None:
            await ctx.send(
                "💻 Coding Projects:\n"
                "/code virus — $250 – $763 in 25 min, 25% police catch chance\n"
                "/code website — $50 – $150 in 10 min\n"
                "/code messenger — 45% viral (thousands/5h) or 55% flop ($10/3h)"
            )
            return
        uid = self.manager.uid(ctx.author.id)
        if uid in self.coding_tasks:
            await ctx.send("⌛ You're already coding something.")
            return
        p = project.lower()
        if p == "virus":
            cost = 250
            if not self.manager.try_withdraw(ctx.author.id, cost):
                await ctx.send("💸 Not enough money.")
                return
            self.coding_tasks[uid] = ("virus", time.time() + 1500)
            await ctx.send("🦠 Coding a virus... will finish in 25 minutes.")
        elif p == "website":
            cost = 50
            if not self.manager.try_withdraw(ctx.author.id, cost):
                await ctx.send("💸 Not enough money.")
                return
            self.coding_tasks[uid] = ("website", time.time() + 600)
            await ctx.send("🌐 Building a website... will finish in 10 minutes.")
        elif p == "messenger":
            cost = 3500
            if not self.manager.try_withdraw(ctx.author.id, cost):
                await ctx.send("💸 Not enough money.")
                return
            self.coding_tasks[uid] = ("messenger", time.time() + 18000)
            await ctx.send("📱 Developing a messenger app... will finish in 5 hours.")
        else:
            await ctx.send("❌ Unknown project. Use /code to see options.")

    # Admin command: setbalance (guarded by guilded author id strings in ADMIN_ALLOWED_IDS)
    @commands.command()
    async def setbalance(self, ctx, amount: int):
        allowed_ids = os.getenv("ADMIN_ALLOWED_IDS", "mpGYeq9d,mL2MM1N4").split(",")
        if str(ctx.author.id) not in allowed_ids:
            await ctx.send("❌ You don't have permission to use this command.")
            return
        if amount < 0:
            await ctx.send("❌ Amount must be positive.")
            return
        self.manager.update_balance(ctx.author.id, amount)
        await ctx.send(f"✅ Your balance has been set to ${amount}.")


# helper to register cog in main program
def setup(bot: commands.Bot, db: Optional[Any] = None, storage_dir: str = "."):
    bot.add_cog(EconomyCog(bot, db=db, storage_dir=storage_dir))
    logger.info("EconomyCog registered.")


__all__ = ["EconomyManager", "EconomyCog", "setup"]
