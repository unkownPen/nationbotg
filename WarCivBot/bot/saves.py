import json
import logging
from datetime import datetime
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)

class SaveManager:
    def __init__(self, db):
        self.db = db
        self.MAX_SLOTS = 5
        
    async def save_civilization(self, user_id: str, slot: int, name: str = None) -> bool:
        """Save civilization to a numbered slot"""
        try:
            if not 1 <= slot <= self.MAX_SLOTS:
                return False
                
            # Get current civilization data
            civ = await self.db.get_civilization(user_id)
            if not civ:
                return False
                
            # Add metadata
            save_data = {
                "civilization": civ,
                "metadata": {
                    "saved_at": datetime.utcnow().isoformat(),
                    "name": name or f"Save {slot}",
                    "slot": slot
                }
            }
            
            # Save to database
            return await self.db.save_civilization_state(
                user_id=user_id,
                slot=slot,
                data=json.dumps(save_data)
            )
            
        except Exception as e:
            logger.error(f"Error saving civilization to slot {slot}: {e}")
            return False
            
    async def load_civilization(self, user_id: str, slot: int) -> bool:
        """Load civilization from a numbered slot"""
        try:
            if not 1 <= slot <= self.MAX_SLOTS:
                return False
                
            # Get save data
            save_data = await self.db.get_civilization_save(user_id, slot)
            if not save_data:
                return False
                
            # Parse save data
            data = json.loads(save_data)
            civ_data = data["civilization"]
            
            # Restore civilization state
            return await self.db.restore_civilization(user_id, civ_data)
            
        except Exception as e:
            logger.error(f"Error loading civilization from slot {slot}: {e}")
            return False
            
    async def list_saves(self, user_id: str) -> List[Dict]:
        """Get list of available save slots"""
        try:
            saves = await self.db.get_civilization_saves(user_id)
            
            # Format save info
            save_list = []
            for slot in range(1, self.MAX_SLOTS + 1):
                save_data = saves.get(str(slot))
                if save_data:
                    data = json.loads(save_data)
                    meta = data["metadata"]
                    civ = data["civilization"]
                    save_list.append({
                        "slot": slot,
                        "name": meta["name"],
                        "saved_at": meta["saved_at"],
                        "civilization_name": civ["name"],
                        "ideology": civ.get("ideology", "None")
                    })
                else:
                    save_list.append({
                        "slot": slot,
                        "name": f"Empty Slot {slot}",
                        "saved_at": None,
                        "civilization_name": None,
                        "ideology": None
                    })
                    
            return save_list
            
        except Exception as e:
            logger.error(f"Error listing saves: {e}")
            return []

    async def delete_save(self, user_id: str, slot: int) -> bool:
        """Delete a save slot"""
        try:
            if not 1 <= slot <= self.MAX_SLOTS:
                return False
            return await self.db.delete_civilization_save(user_id, slot)
        except Exception as e:
            logger.error(f"Error deleting save in slot {slot}: {e}")
            return False
