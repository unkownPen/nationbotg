import os
import asyncio
import logging
from datetime import datetime, timedelta
import guilded
from guilded.ext import commands
import threading
from web.dashboard import app as flask_app
from bot.database import Database
from bot.civilization import CivilizationManager
from bot.commands.basic import BasicCommands
# Bring back the original EconomyCommands (legacy/old economy bot code)
from bot.commands.economy import EconomyCommands
# Also load the ExtraEconomy cog you added (ExtraEconomy.py should expose setup)
from ExtraEconomy import setup as setup_extra_economy
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

class WarBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='.')
        
        self.db = Database()
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

            # Register legacy/old economy cog (kept as EconomyCommands)
            try:
                self.add_cog(EconomyCommands(self))
                logger.info("Legacy EconomyCommands cog loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load legacy EconomyCommands cog: {e}")

            # Register the ExtraEconomy cog using the setup helper from ExtraEconomy.py.
            # This is the new/extra economy implementation you've pasted into ExtraEconomy.py.
            try:
                setup_extra_economy(self, db=self.db, storage_dir="./data")
                logger.info("ExtraEconomy cog (extra/modern economy) loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load ExtraEconomy cog: {e}")

            self.add_cog(MilitaryCommands(self))
            self.add_cog(DiplomacyCommands(self))
            self.add_cog(StoreCommands(self))
            self.add_cog(HyperItemCommands(self))
            logger.info("All other command cogs loaded successfully")
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



def start_flask_server():
    """Start the Flask web dashboard in a separate thread"""
    try:
        flask_app.run(host='0.0.0.0', port=5000, debug=False)
    except Exception as e:
        logger.error(f"Failed to start Flask server: {e}")

async def main():
    """Main function to start the bot"""
    # Start Flask server in background thread
    flask_thread = threading.Thread(target=start_flask_server, daemon=True)
    flask_thread.start()
    logger.info("Flask dashboard started on port 5000")
    
    # Get bot token from environment
    token = os.getenv('GUILDED_BOT_TOKEN', 'your_bot_token_here')
    
    if token == 'your_bot_token_here':
        logger.error("Please set GUILDED_BOT_TOKEN environment variable")
        return
    
    # Start the bot
    bot = WarBot()
    try:
        await bot.start(token)
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot shutdown requested")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
