import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1 import FieldFilter, ServerTimestamp  # For advanced timestamp if needed
import random
import json
import threading
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
import time

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, cred_path: str = 'serviceAccountKey.json'):
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        self.db = firestore.client()
        self.setup_cleanup_scheduler()
        logger.info("Firebase database initialized successfully")

    def setup_cleanup_scheduler(self):
        """Schedule daily cleanup of expired requests"""
        def cleanup_task():
            logger.info("Running scheduled cleanup of expired requests...")
            self.cleanup_expired_requests()
            threading.Timer(86400, cleanup_task).start()
        
        threading.Timer(60, cleanup_task).start()
        logger.info("Scheduled cleanup task initialized")

    def create_civilization(self, user_id: str, name: str, bonus_resources: Dict = None, bonuses: Dict = None, hyper_item: str = None) -> bool:
        """Create a new civilization"""
        try:
            # Check if exists
            civ_ref = self.db.collection('civilizations').document(user_id)
            if civ_ref.get().exists:
                logger.warning(f"User {user_id} already has a civilization")
                return False

            default_resources = {
                "gold": 500,
                "food": 300,
                "stone": 100,
                "wood": 100
            }
            
            if bonus_resources:
                for resource, amount in bonus_resources.items():
                    if resource in default_resources:
                        default_resources[resource] += amount
            
            default_population = {
                "citizens": 100 + bonus_resources.get('population', 0) if bonus_resources else 100,
                "happiness": 50 + bonus_resources.get('happiness', 0) if bonus_resources else 50,
                "hunger": 0,
                "employed": 50
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
            selected_cards = []
            
            now = datetime.utcnow()
            data = {
                'name': name,
                'ideology': None,  # Assuming from OG, not set here
                'resources': default_resources,
                'population': default_population,
                'military': default_military,
                'territory': default_territory,
                'hyper_items': hyper_items,
                'bonuses': bonuses,
                'selected_cards': selected_cards,
                'created_at': now,
                'last_active': now
            }
            
            civ_ref.set(data)
            
            # Create initial card selection for tech level 1
            self.generate_card_selection(user_id, 1)
            
            logger.info(f"Created civilization '{name}' for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating civilization: {e}")
            return False

    def get_civilization(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get civilization data for a user"""
        try:
            doc_ref = self.db.collection('civilizations').document(user_id)
            doc = doc_ref.get()
            if doc.exists:
                return doc.to_dict()
            return None
            
        except Exception as e:
            logger.error(f"Error getting civilization for user {user_id}: {e}")
            return None

    def update_civilization(self, user_id: str, updates: Dict[str, Any]) -> bool:
        """Update civilization data"""
        try:
            doc_ref = self.db.collection('civilizations').document(user_id)
            updates['last_active'] = datetime.utcnow()
            doc_ref.update(updates)
            return True
            
        except Exception as e:
            logger.error(f"Error updating civilization for user {user_id}: {e}")
            return False

    def get_command_cooldown(self, user_id: str, command: str) -> Optional[datetime]:
        """Get the last used time for a command, or None if no cooldown"""
        try:
            doc_id = f"{user_id}_{command}"
            doc_ref = self.db.collection('cooldowns').document(doc_id)
            doc = doc_ref.get()
            if doc.exists:
                data = doc.to_dict()
                return data.get('last_used_at')
            return None
            
        except Exception as e:
            logger.error(f"Error getting command cooldown: {e}")
            return None

    def check_cooldown(self, user_id: str, command: str) -> Optional[datetime]:
        """Check if command is on cooldown - returns expiry time if on cooldown, None if available"""
        try:
            last_used = self.get_command_cooldown(user_id, command)
            if last_used:
                return last_used
            return None
            
        except Exception as e:
            logger.error(f"Error checking command cooldown: {e}")
            return None

    def set_command_cooldown(self, user_id: str, command: str, timestamp: datetime = None) -> bool:
        """Set the last used time for a command"""
        try:
            if timestamp is None:
                timestamp = datetime.utcnow()
                
            doc_id = f"{user_id}_{command}"
            doc_ref = self.db.collection('cooldowns').document(doc_id)
            doc_ref.set({
                'user_id': user_id,
                'command': command,
                'last_used_at': timestamp
            })
            return True
            
        except Exception as e:
            logger.error(f"Error setting command cooldown: {e}")
            return False

    def update_cooldown(self, user_id: str, command: str, timestamp: datetime = None) -> bool:
        """Update cooldown - alias for set_command_cooldown for compatibility"""
        return self.set_command_cooldown(user_id, command, timestamp)

    def generate_card_selection(self, user_id: str, tech_level: int) -> bool:
        """Generate 5 random cards for a tech level"""
        try:
            doc_id = f"{user_id}_{tech_level}"
            
            # Define card pool (expanded for variety)
            card_pool = [
                {"name": "Resource Boost", "type": "bonus", "effect": {"resource_production": 10}, "description": "+10% resource production"},
                {"name": "Military Training", "type": "bonus", "effect": {"soldier_training_speed": 15}, "description": "+15% soldier training speed"},
                {"name": "Trade Advantage", "type": "bonus", "effect": {"trade_profit": 10}, "description": "+10% trade profit"},
                {"name": "Population Surge", "type": "bonus", "effect": {"population_growth": 10}, "description": "+10% population growth"},
                {"name": "Tech Breakthrough", "type": "one_time", "effect": {"tech_level": 1}, "description": "+1 tech level (max 10)"},
                {"name": "Gold Cache", "type": "one_time", "effect": {"gold": 500}, "description": "Gain 500 gold"},
                {"name": "Food Reserves", "type": "one_time", "effect": {"food": 300}, "description": "Gain 300 food"},
                {"name": "Mercenary Band", "type": "one_time", "effect": {"soldiers": 20}, "description": "Recruit 20 soldiers"},
                {"name": "Spy Network", "type": "one_time", "effect": {"spies": 5}, "description": "Recruit 5 spies"},
                {"name": "Fortification", "type": "bonus", "effect": {"defense_strength": 15}, "description": "+15% defense strength"},
                {"name": "Stone Quarry", "type": "one_time", "effect": {"stone": 200}, "description": "Gain 200 stone"},
                {"name": "Lumber Mill", "type": "one_time", "effect": {"wood": 200}, "description": "Gain 200 wood"},
                {"name": "Intelligence Agency", "type": "bonus", "effect": {"spy_effectiveness": 20}, "description": "+20% spy effectiveness"},
                {"name": "Economic Boom", "type": "one_time", "effect": {"gold": 800, "happiness": 10}, "description": "Gain 800 gold and +10 happiness"},
                {"name": "Military Academy", "type": "bonus", "effect": {"soldier_training_speed": 25}, "description": "+25% soldier training speed"}
            ]
            
            # Select 5 random cards
            available_cards = random.sample(card_pool, min(5, len(card_pool)))
            
            self.db.collection('cards').document(doc_id).set({
                'user_id': user_id,
                'tech_level': tech_level,
                'available_cards': available_cards,
                'status': 'pending',
                'created_at': datetime.utcnow()
            })
            
            logger.info(f"Generated card selection for user {user_id} at tech level {tech_level}")
            return True
            
        except Exception as e:
            logger.error(f"Error generating card selection: {e}")
            return False

    def get_card_selection(self, user_id: str, tech_level: int) -> Optional[Dict]:
        """Get available cards for a tech level"""
        try:
            doc_id = f"{user_id}_{tech_level}"
            doc_ref = self.db.collection('cards').document(doc_id)
            doc = doc_ref.get()
            if doc.exists:
                return doc.to_dict()
            return None
            
        except Exception as e:
            logger.error(f"Error getting card selection for user {user_id}: {e}")
            return None

    def select_card(self, user_id: str, tech_level: int, card_name: str) -> Optional[Dict]:
        """Select a card and mark it as chosen"""
        try:
            card_selection = self.get_card_selection(user_id, tech_level)
            if not card_selection:
                return None
                
            selected_card = next((card for card in card_selection['available_cards'] if card['name'].lower() == card_name.lower()), None)
            if not selected_card:
                return None
                
            doc_id = f"{user_id}_{tech_level}"
            self.db.collection('cards').document(doc_id).update({'status': 'selected'})
            
            logger.info(f"User {user_id} selected card '{card_name}' at tech level {tech_level}")
            return selected_card
            
        except Exception as e:
            logger.error(f"Error selecting card for user {user_id}: {e}")
            return None

    def get_all_civilizations(self) -> List[Dict[str, Any]]:
        """Get all civilizations for leaderboards"""
        try:
            docs = self.db.collection('civilizations').order_by('last_active', direction=firestore.Query.DESCENDING).stream()
            civilizations = [doc.to_dict() for doc in docs]
            return civilizations
            
        except Exception as e:
            logger.error(f"Error getting all civilizations: {e}")
            return []

    def create_alliance(self, name: str, leader_id: str, description: str = "") -> bool:
        """Create a new alliance"""
        try:
            # Check unique name
            query = self.db.collection('alliances').where(filter=FieldFilter('name', '==', name)).limit(1).stream()
            if next(query, None):
                logger.warning(f"Alliance name '{name}' already exists")
                return False
            
            data = {
                'name': name,
                'description': description,
                'leader_id': leader_id,
                'members': [leader_id],
                'join_requests': [],
                'created_at': datetime.utcnow()
            }
            _, doc_ref = self.db.collection('alliances').add(data)
            logger.info(f"Created alliance '{name}' led by {leader_id} with ID {doc_ref.id}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating alliance: {e}")
            return False

    def log_event(self, user_id: str, event_type: str, title: str, description: str, effects: Dict = None):
        """Log an event to the database"""
        try:
            data = {
                'user_id': user_id,
                'event_type': event_type,
                'title': title,
                'description': description,
                'effects': effects or {},
                'timestamp': datetime.utcnow()
            }
            self.db.collection('events').add(data)
            logger.debug(f"Logged event: {title} for user {user_id}")
            
        except Exception as e:
            logger.error(f"Error logging event: {e}")

    def get_recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent events for dashboard"""
        try:
            docs = self.db.collection('events').order_by('timestamp', direction=firestore.Query.DESCENDING).limit(limit).stream()
            events = []
            for doc in docs:
                event = doc.to_dict()
                civ = self.get_civilization(event['user_id'])
                event['civ_name'] = civ['name'] if civ else 'Unknown'
                events.append(event)
            return events
            
        except Exception as e:
            logger.error(f"Error getting recent events: {e}")
            return []

    def create_trade_request(self, sender_id: str, recipient_id: str, offer: Dict, request: Dict) -> bool:
        """Create a new trade request"""
        try:
            now = datetime.utcnow()
            data = {
                'sender_id': sender_id,
                'recipient_id': recipient_id,
                'offer': offer,
                'request': request,
                'created_at': now,
                'expires_at': now + timedelta(days=1)
            }
            self.db.collection('trade_requests').add(data)
            logger.info(f"Trade request created from {sender_id} to {recipient_id}")
            return True
        except Exception as e:
            logger.error(f"Error creating trade request: {e}")
            return False

    def get_trade_requests(self, user_id: str) -> List[Dict]:
        """Get all active trade requests for a user"""
        try:
            now = datetime.utcnow()
            query = self.db.collection('trade_requests').where(filter=FieldFilter('recipient_id', '==', user_id)).where(filter=FieldFilter('expires_at', '>', now)).stream()
            requests = []
            for doc in query:
                req = doc.to_dict()
                req['id'] = doc.id
                sender_civ = self.get_civilization(req['sender_id'])
                req['sender_name'] = sender_civ['name'] if sender_civ else 'Unknown'
                requests.append(req)
            return requests
        except Exception as e:
            logger.error(f"Error getting trade requests: {e}")
            return []

    def get_trade_request_by_id(self, request_id: str) -> Optional[Dict]:
        """Get a specific trade request by ID"""
        try:
            now = datetime.utcnow()
            doc_ref = self.db.collection('trade_requests').document(request_id)
            doc = doc_ref.get()
            if doc.exists:
                req = doc.to_dict()
                if req['expires_at'] > now:
                    return req
            return None
        except Exception as e:
            logger.error(f"Error getting trade request by ID: {e}")
            return None

    def delete_trade_request(self, request_id: str) -> bool:
        """Delete a trade request"""
        try:
            doc_ref = self.db.collection('trade_requests').document(request_id)
            doc_ref.delete()
            return True
        except Exception as e:
            logger.error(f"Error deleting trade request: {e}")
            return False

    def create_alliance_invite(self, alliance_id: str, sender_id: str, recipient_id: str) -> bool:
        """Invite a user to an alliance"""
        try:
            now = datetime.utcnow()
            data = {
                'alliance_id': alliance_id,
                'sender_id': sender_id,
                'recipient_id': recipient_id,
                'created_at': now,
                'expires_at': now + timedelta(days=1)
            }
            self.db.collection('alliance_invitations').add(data)
            logger.info(f"Alliance invite created: alliance={alliance_id} to {recipient_id}")
            return True
        except Exception as e:
            logger.error(f"Error creating alliance invite: {e}")
            return False

    def get_alliance_invites(self, user_id: str) -> List[Dict]:
        """Get active alliance invites for a user"""
        try:
            now = datetime.utcnow()
            query = self.db.collection('alliance_invitations').where(filter=FieldFilter('recipient_id', '==', user_id)).where(filter=FieldFilter('expires_at', '>', now)).stream()
            invites = []
            for doc in query:
                invite = doc.to_dict()
                invite['id'] = doc.id
                alliance = self.get_alliance(invite['alliance_id'])
                invite['alliance_name'] = alliance['name'] if alliance else 'Unknown'
                invites.append(invite)
            return invites
        except Exception as e:
            logger.error(f"Error getting alliance invites: {e}")
            return []

    def get_alliance_invite_by_id(self, invite_id: str) -> Optional[Dict]:
        """Get a specific alliance invite by ID"""
        try:
            now = datetime.utcnow()
            doc_ref = self.db.collection('alliance_invitations').document(invite_id)
            doc = doc_ref.get()
            if doc.exists:
                invite = doc.to_dict()
                if invite['expires_at'] > now:
                    alliance = self.get_alliance(invite['alliance_id'])
                    invite['alliance_name'] = alliance['name'] if alliance else 'Unknown'
                    return invite
            return None
        except Exception as e:
            logger.error(f"Error getting alliance invite by ID: {e}")
            return None

    def delete_alliance_invite(self, invite_id: str) -> bool:
        """Delete an alliance invitation"""
        try:
            doc_ref = self.db.collection('alliance_invitations').document(invite_id)
            doc_ref.delete()
            return True
        except Exception as e:
            logger.error(f"Error deleting alliance invite: {e}")
            return False

    def send_message(self, sender_id: str, recipient_id: str, message: str) -> bool:
        """Send a message between users"""
        try:
            now = datetime.utcnow()
            data = {
                'sender_id': sender_id,
                'recipient_id': recipient_id,
                'message': message,
                'created_at': now,
                'expires_at': now + timedelta(days=1)
            }
            self.db.collection('messages').add(data)
            logger.info(f"Message sent from {sender_id} to {recipient_id}")
            return True
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return False

    def get_messages(self, user_id: str) -> List[Dict]:
        """Get active messages for a user"""
        try:
            now = datetime.utcnow()
            query = self.db.collection('messages').where(filter=FieldFilter('recipient_id', '==', user_id)).where(filter=FieldFilter('expires_at', '>', now)).stream()
            messages = []
            for doc in query:
                msg = doc.to_dict()
                msg['id'] = doc.id
                sender_civ = self.get_civilization(msg['sender_id'])
                msg['sender_name'] = sender_civ['name'] if sender_civ else 'Unknown'
                messages.append(msg)
            return messages
        except Exception as e:
            logger.error(f"Error getting messages: {e}")
            return []

    def delete_message(self, message_id: str) -> bool:
        """Delete a message"""
        try:
            doc_ref = self.db.collection('messages').document(message_id)
            doc_ref.delete()
            return True
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
            return False

    def get_alliance(self, alliance_id: str) -> Optional[Dict]:
        """Get alliance data by ID"""
        try:
            doc_ref = self.db.collection('alliances').document(alliance_id)
            doc = doc_ref.get()
            if doc.exists:
                return doc.to_dict()
            return None
        except Exception as e:
            logger.error(f"Error getting alliance: {e}")
            return None

    def get_alliance_by_name(self, name: str) -> Optional[Dict]:
        """Get alliance data by name"""
        try:
            query = self.db.collection('alliances').where(filter=FieldFilter('name', '==', name)).limit(1).stream()
            doc = next(query, None)
            if doc:
                return doc.to_dict()
            return None
        except Exception as e:
            logger.error(f"Error getting alliance by name: {e}")
            return None

    def add_alliance_member(self, alliance_id: str, user_id: str) -> bool:
        """Add member to alliance"""
        try:
            alliance = self.get_alliance(alliance_id)
            if not alliance:
                return False
            
            if user_id in alliance['members']:
                return True
            
            members = alliance['members'] + [user_id]
            join_requests = [uid for uid in alliance.get('join_requests', []) if uid != user_id]
            
            doc_ref = self.db.collection('alliances').document(alliance_id)
            doc_ref.update({
                'members': members,
                'join_requests': join_requests
            })
            return True
        except Exception as e:
            logger.error(f"Error adding alliance member: {e}")
            return False

    def get_wars(self, user_id: str = None, status: str = 'ongoing') -> List[Dict]:
        """Get wars involving a user or all wars"""
        try:
            collection = self.db.collection('wars')
            if user_id:
                # Need two queries and union since OR not on different fields easily
                query1 = collection.where(filter=FieldFilter('attacker_id', '==', user_id)).where(filter=FieldFilter('result', '==', status)).stream()
                query2 = collection.where(filter=FieldFilter('defender_id', '==', user_id)).where(filter=FieldFilter('result', '==', status)).stream()
                docs = list(query1) + list(query2)
            else:
                docs = collection.where(filter=FieldFilter('result', '==', status)).stream()
            
            wars = []
            for doc in set(docs):  # Dedup if any
                war = doc.to_dict()
                war['id'] = doc.id
                attacker_civ = self.get_civilization(war['attacker_id'])
                defender_civ = self.get_civilization(war['defender_id'])
                war['attacker_name'] = attacker_civ['name'] if attacker_civ else 'Unknown'
                war['defender_name'] = defender_civ['name'] if defender_civ else 'Unknown'
                wars.append(war)
            return wars
        except Exception as e:
            logger.error(f"Error getting wars: {e}")
            return []

    def get_peace_offers(self, user_id: str = None) -> List[Dict]:
        """Get peace offers for a user or all peace offers"""
        try:
            collection = self.db.collection('peace_offers')
            if user_id:
                query1 = collection.where(filter=FieldFilter('offerer_id', '==', user_id)).where(filter=FieldFilter('status', '==', 'pending')).stream()
                query2 = collection.where(filter=FieldFilter('receiver_id', '==', user_id)).where(filter=FieldFilter('status', '==', 'pending')).stream()
                docs = list(query1) + list(query2)
            else:
                docs = collection.where(filter=FieldFilter('status', '==', 'pending')).stream()
            
            offers = []
            for doc in set(docs):
                offer = doc.to_dict()
                offer['id'] = doc.id
                offerer_civ = self.get_civilization(offer['offerer_id'])
                receiver_civ = self.get_civilization(offer['receiver_id'])
                offer['offerer_name'] = offerer_civ['name'] if offerer_civ else 'Unknown'
                offer['receiver_name'] = receiver_civ['name'] if receiver_civ else 'Unknown'
                offers.append(offer)
            return offers
        except Exception as e:
            logger.error(f"Error getting peace offers: {e}")
            return []

    def create_peace_offer(self, offerer_id: str, receiver_id: str) -> bool:
        """Create a peace offer"""
        try:
            data = {
                'offerer_id': offerer_id,
                'receiver_id': receiver_id,
                'status': 'pending',
                'offered_at': datetime.utcnow(),
                'responded_at': None
            }
            self.db.collection('peace_offers').add(data)
            logger.info(f"Peace offer created from {offerer_id} to {receiver_id}")
            return True
        except Exception as e:
            logger.error(f"Error creating peace offer: {e}")
            return False

    def update_peace_offer(self, offer_id: str, status: str) -> bool:
        """Update peace offer status"""
        try:
            doc_ref = self.db.collection('peace_offers').document(offer_id)
            doc_ref.update({
                'status': status,
                'responded_at': datetime.utcnow()
            })
            return True
        except Exception as e:
            logger.error(f"Error updating peace offer: {e}")
            return False

    def end_war(self, attacker_id: str, defender_id: str, result: str) -> bool:
        """End a war between two civilizations"""
        try:
            # Find matching wars
            query1 = self.db.collection('wars').where(filter=FieldFilter('attacker_id', '==', attacker_id)).where(filter=FieldFilter('defender_id', '==', defender_id)).where(filter=FieldFilter('result', '==', 'ongoing'))
            query2 = self.db.collection('wars').where(filter=FieldFilter('attacker_id', '==', defender_id)).where(filter=FieldFilter('defender_id', '==', attacker_id)).where(filter=FieldFilter('result', '==', 'ongoing'))
            docs = list(query1.stream()) + list(query2.stream())
            
            if not docs:
                return False
            
            for doc in docs:
                doc.reference.update({
                    'result': result,
                    'ended_at': datetime.utcnow()
                })
            return True
        except Exception as e:
            logger.error(f"Error ending war: {e}")
            return False

    def get_user_statistics(self, user_id: str) -> Dict[str, Any]:
        """Get comprehensive statistics for a user"""
        try:
            civ = self.get_civilization(user_id)
            if not civ:
                return {}
            
            # War stats
            wars = self.get_wars(user_id, 'ongoing') + self.get_wars(user_id, 'victory') + self.get_wars(user_id, 'defeat') + self.get_wars(user_id, 'peace')
            total_wars = len(wars)
            victories = sum(1 for w in wars if w['result'] == 'victory')
            defeats = sum(1 for w in wars if w['result'] == 'defeat')
            peace_treaties = sum(1 for w in wars if w['result'] == 'peace')
            war_stats = {
                'total_wars': total_wars,
                'victories': victories,
                'defeats': defeats,
                'peace_treaties': peace_treaties
            }
            
            # Event count
            query = self.db.collection('events').where(filter=FieldFilter('user_id', '==', user_id)).stream()
            total_events = len(list(query))
            
            # Power scores
            military_power = (civ['military']['soldiers'] * 10 + 
                              civ['military']['spies'] * 5 + 
                              civ['military']['tech_level'] * 50)
            economic_power = sum(civ['resources'].values())
            territorial_power = civ['territory']['land_size']
            total_power = military_power + economic_power + territorial_power
            
            return {
                'civilization': civ,
                'war_statistics': war_stats,
                'total_events': total_events,
                'power_scores': {
                    'military': military_power,
                    'economic': economic_power,
                    'territorial': territorial_power,
                    'total': total_power
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting user statistics: {e}")
            return {}

    def get_leaderboard(self, category: str = 'power', limit: int = 10) -> List[Dict]:
        """Get leaderboard for different categories"""
        try:
            civs = self.get_all_civilizations()
            
            if category == 'power':
                scored_civs = []
                for civ in civs:
                    military = civ['military']
                    resources = civ['resources']
                    territory = civ['territory']
                    military_power = (military['soldiers'] * 10 + military['spies'] * 5 + military['tech_level'] * 50)
                    economic_power = sum(resources.values())
                    territorial_power = territory['land_size']
                    total_power = military_power + economic_power + territorial_power
                    scored_civs.append({
                        'user_id': civ['user_id'],
                        'name': civ['name'],
                        'score': total_power,
                        'military_power': military_power,
                        'economic_power': economic_power,
                        'territorial_power': territorial_power
                    })
                return sorted(scored_civs, key=lambda x: x['score'], reverse=True)[:limit]
                
            elif category == 'gold':
                scored_civs = [{
                    'user_id': civ['user_id'],
                    'name': civ['name'],
                    'score': civ['resources']['gold']
                } for civ in civs]
                return sorted(scored_civs, key=lambda x: x['score'], reverse=True)[:limit]
                
            elif category == 'military':
                scored_civs = [{
                    'user_id': civ['user_id'],
                    'name': civ['name'],
                    'score': civ['military']['soldiers'] + civ['military']['spies'],
                    'soldiers': civ['military']['soldiers'],
                    'spies': civ['military']['spies']
                } for civ in civs]
                return sorted(scored_civs, key=lambda x: x['score'], reverse=True)[:limit]
                
            elif category == 'territory':
                scored_civs = [{
                    'user_id': civ['user_id'],
                    'name': civ['name'],
                    'score': civ['territory']['land_size']
                } for civ in civs]
                return sorted(scored_civs, key=lambda x: x['score'], reverse=True)[:limit]
                
            return []
            
        except Exception as e:
            logger.error(f"Error getting leaderboard: {e}")
            return []

    def cleanup_expired_requests(self):
        """Automatically remove expired requests (runs daily)"""
        try:
            now = datetime.utcnow()
            
            # Trade requests
            trade_query = self.db.collection('trade_requests').where(filter=FieldFilter('expires_at', '<=', now)).stream()
            trade_docs = list(trade_query)
            for doc in trade_docs:
                doc.reference.delete()
            trade_count = len(trade_docs)
            
            # Alliance invitations
            invite_query = self.db.collection('alliance_invitations').where(filter=FieldFilter('expires_at', '<=', now)).stream()
            invite_docs = list(invite_query)
            for doc in invite_docs:
                doc.reference.delete()
            invite_count = len(invite_docs)
            
            # Messages
            msg_query = self.db.collection('messages').where(filter=FieldFilter('expires_at', '<=', now)).stream()
            msg_docs = list(msg_query)
            for doc in msg_docs:
                doc.reference.delete()
            message_count = len(msg_docs)
            
            logger.info(f"Cleaned up expired requests: "
                        f"{trade_count} trades, {invite_count} invites, "
                        f"{message_count} messages removed")
            return True
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            return False

    def backup_database(self, backup_path: str = None) -> bool:
        """Create a backup of the database - stubbed for Firebase (use console export)"""
        logger.warning("Backup not implemented for Firebase; use Firebase console or export API")
        return False

    def get_database_info(self) -> Dict[str, Any]:
        """Get database information and statistics"""
        try:
            info = {}
            
            # Count records in each table (collection)
            collections = [
                'civilizations', 'wars', 'peace_offers', 'alliances', 
                'events', 'trade_requests', 'messages', 'cards', 
                'cooldowns', 'alliance_invitations'
            ]
            
            for coll in collections:
                docs = self.db.collection(coll).stream()
                info[f'{coll}_count'] = len(list(docs))
            
            # Database size not directly available in client SDK
            
            # Active users (last_active > now - 7 days)
            seven_days_ago = datetime.utcnow() - timedelta(days=7)
            active_query = self.db.collection('civilizations').where(filter=FieldFilter('last_active', '>', seven_days_ago)).stream()
            info['active_users_week'] = len(list(active_query))
            
            return info
            
        except Exception as e:
            logger.error(f"Error getting database info: {e}")
            return {}

    def close_connections(self):
        """Close all database connections (for shutdown) - not needed for Firebase"""
        pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
