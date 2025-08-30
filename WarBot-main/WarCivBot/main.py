import os
import asyncio
import logging
from datetime import datetime, timedelta
import guilded
from guilded.ext import commands
import threading
from firebase_functions import https_fn
from firebase_admin import initialize_app, firestore
from web.dashboard import app as flask_app
from bot.database import Database
from bot.civilization import CivilizationManager
from bot.commands.basic import BasicCommands
from bot.commands.economy import EconomyCommands
from bot.commands.military import MilitaryCommands
from bot.commands.diplomacy import DiplomacyCommands
from bot.commands.store import StoreCommands
from bot.commands.hyperitems import HyperItemCommands
from bot.events import EventManager
from bot.utils import format_number, get_ascii_art

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('warbot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize Firebase (default creds in Functions env)
initialize_app()
db_client = firestore.client()  # For your Database class to use

class WarBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='.')
        
        self.db = Database(db_client)  # Pass Firestore client to Database (mod your Database class)
        self.civ_manager = CivilizationManager(self.db)
        self.event_manager = EventManager(self.db)
        
        # Initialize command cogs - will be loaded in on_ready
        pass

    async def on_ready(self):
        logger.info(f'{self.user} has connected to Guilded!')
        print(f'WarBot is online as {self.user}')
        
        # Initialize command cogs after bot is ready
        try:
            self.add_cog(BasicCommands(self))
            self.add_cog(EconomyCommands(self))
            self.add_cog(MilitaryCommands(self))
            self.add_cog(DiplomacyCommands(self))
            self.add_cog(StoreCommands(self))
            self.add_cog(HyperItemCommands(self))
            logger.info("All command cogs loaded successfully")
        except Exception as e:
            logger.error(f"Error loading cogs: {e}")
        
        # Start random events loop
        asyncio.create_task(self.event_manager.start_random_events(self))

    async def on_message(self, event):
        message = event
        if message.author == self.user:
            return
        
        # Process commands
        await self.process_commands(message)

# Global vars for bot state (Functions instances reuse globals while warm)
bot = WarBot()
bot_running = False
loop = asyncio.new_event_loop()  # New loop for async in Functions
asyncio.set_event_loop(loop)

@https_fn.on_request()
def dashboard(req: https_fn.Request) -> https_fn.Response:
    global bot_running
    if not bot_running:
        bot_running = True
        token = os.environ.get('GUILDED_BOT_TOKEN')
        if not token:
            logger.error("No GUILDED_BOT_TOKEN set")
            return https_fn.Response("Bot token missing", status=500)
        # Start bot in async task
        loop.create_task(bot.start(token))
        logger.info("Bot started in background")
    
    # Handle Flask request
    return flask_app(req)
