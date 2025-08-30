import random
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from firebase_admin import firestore
from google.cloud.firestore_v1 import FieldFilter, ServerValue

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, client: firestore.Client):
        self.client = client
        self.init_database()  # Optional, Firestore creates collections on write
        # No scheduler here - call cleanup_expired_requests from a scheduled function or bot loop

    def init_database(self):
        """Initialize if needed - Firestore doesn't require table creation, but we can log"""
        logger.info("Firestore database ready - collections will be created on first write")

    def create_civilization(self, user_id: str, name: str, bonus_resources: Dict = None, bonuses: Dict = None, hyper_item: str = None) -> bool:
        """Create a new civilization"""
        try:
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
            
            doc_ref = self.client.collection('civilizations').document(user_id)
            if doc_ref.get().exists:
                logger.warning(f"User {user_id} already has a civilization")
                return False
            
            doc_ref.set({
                'name': name,
                'ideology': None,  # Assuming default
                'resources': default_resources,
                'population': default_population,
                'military': default_military,
                'territory': default_territory,
                'hyper_items': hyper_items,
                'bonuses': bonuses,
                'selected_cards': selected_cards,
                'created_at': firestore.SERVER_TIMESTAMP,
                'last_active': firestore.SERVER_TIMESTAMP
            })
            
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
            doc_ref = self.client.collection('civilizations').document(user_id)
            doc = doc_ref.get()
            if not doc.exists:
                return None
            
            civ = doc.to_dict()
            # No need to json.loads since Firestore stores maps natively
            return civ
            
        except Exception as e:
            logger.error(f"Error getting civilization for user {user_id}: {e}")
            return None

    def update_civilization(self, user_id: str, updates: Dict[str, Any]) -> bool:
        """Update civilization data"""
        try:
            doc_ref = self.client.collection('civilizations').document(user_id)
            updates['last_active'] = firestore.SERVER_TIMESTAMP
            doc_ref.update(updates)
            return True
            
        except Exception as e:
            logger.error(f"Error updating civilization for user {user_id}: {e}")
            return False

    def get_command_cooldown(self, user_id: str, command: str) -> Optional[datetime]:
        """Get the last used time for a command, or None if no cooldown"""
        try:
            doc_id = f"{user_id}_{command}"
            doc_ref = self.client.collection('cooldowns').document(doc_id)
            doc = doc_ref.get()
            if doc.exists:
                return doc.to_dict().get('last_used_at')
            return None
            
        except Exception as e:
            logger.error(f"Error getting command cooldown: {e}")
            return None

    def check_cooldown(self, user_id: str, command: str) -> Optional[datetime]:
        """Check if command is on cooldown - returns expiry time if on cooldown, None if available"""
        try:
            return self.get_command_cooldown(user_id, command)
            
        except Exception as e:
            logger.error(f"Error checking command cooldown: {e}")
            return None

    def set_command_cooldown(self, user_id: str, command: str, timestamp: datetime = None) -> bool:
        """Set the last used time for a command"""
        try:
            if timestamp is None:
                timestamp = datetime.utcnow()
                
            doc_id = f"{user_id}_{command}"
            doc_ref = self.client.collection('cooldowns').document(doc_id)
            doc_ref.set({'last_used_at': timestamp})
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
            
            doc_id = f"{user_id}_{tech_level}"
            doc_ref = self.client.collection('cards').document(doc_id)
            doc_ref.set({
                'user_id': user_id,
                'tech_level': tech_level,
                'available_cards': available_cards,
                'status': 'pending',
                'created_at': firestore.SERVER_TIMESTAMP
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
            doc_ref = self.client.collection('cards').document(doc_id)
            doc = doc_ref.get()
            if doc.exists and doc.to_dict().get('status') == 'pending':
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
            doc_ref = self.client.collection('cards').document(doc_id)
            doc_ref.update({'status': 'selected'})
            
            logger.info(f"User {user_id} selected card '{card_name}' at tech level {tech_level}")
            return selected_card
            
        except Exception as e:
            logger.error(f"Error selecting card for user {user_id}: {e}")
            return None

    def get_all_civilizations(self) -> List[Dict[str, Any]]:
        """Get all civilizations for leaderboards"""
        try:
            docs = self.client.collection('civilizations').order_by('last_active', direction=firestore.Query.DESCENDING).stream()
            return [doc.to_dict() for doc in docs]
            
        except Exception as e:
            logger.error(f"Error getting all civilizations: {e}")
            return []

    def create_alliance(self, name: str, leader_id: str, description: str = "") -> bool:
        """Create a new alliance"""
        try:
            doc_ref = self.client.collection('alliances').document(name)  # Using name as ID for uniqueness
            if doc_ref.get().exists:
                logger.warning(f"Alliance name '{name}' already exists")
                return False
            
            doc_ref.set({
                'name': name,
                'description': description,
                'leader_id': leader_id,
                'members': [leader_id],
                'join_requests': [],
                'created_at': firestore.SERVER_TIMESTAMP
            })
            
            logger.info(f"Created alliance '{name}' led by {leader_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating alliance: {e}")
            return False

    def log_event(self, user_id: str, event_type: str, title: str, description: str, effects: Dict = None):
        """Log an event to the database"""
        try:
            doc_ref = self.client.collection('events').document()
            doc_ref.set({
                'user_id': user_id,
                'event_type': event_type,
                'title': title,
                'description': description,
                'effects': effects or {},
                'timestamp': firestore.SERVER_TIMESTAMP
            })
            
            logger.debug(f"Logged event: {title} for user {user_id}")
            
        except Exception as e:
            logger.error(f"Error logging event: {e}")

    def get_recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent events for dashboard"""
        try:
            # Note: Need index on timestamp descending
            docs = self.client.collection('events').order_by('timestamp', direction=firestore.Query.DESCENDING).limit(limit).stream()
            events = [doc.to_dict() for doc in docs]
            
            # Join civ_name client-side
            for event in events:
                civ = self.get_civilization(event['user_id'])
                event['civ_name'] = civ['name'] if civ else 'Unknown'
            
            return events
            
        except Exception as e:
            logger.error(f"Error getting recent events: {e}")
            return []

    def create_trade_request(self, sender_id: str, recipient_id: str, offer: Dict, request: Dict) -> bool:
        """Create a new trade request"""
        try:
            doc_ref = self.client.collection('trade_requests').document()
            doc_ref.set({
                'sender_id': sender_id,
                'recipient_id': recipient_id,
                'offer': offer,
                'request': request,
                'created_at': firestore.SERVER_TIMESTAMP,
                'expires_at': datetime.utcnow() + timedelta(days=1)  # Client-side calc
            })
            logger.info(f"Trade request created from {sender_id} to {recipient_id}")
            return True
        except Exception as e:
            logger.error(f"Error creating trade request: {e}")
            return False

    def get_trade_requests(self, user_id: str) -> List[Dict]:
        """Get all active trade requests for a user"""
        try:
            now = datetime.utcnow()
            docs = self.client.collection('trade_requests') \
                .where(filter=FieldFilter('recipient_id', '==', user_id)) \
                .where(filter=FieldFilter('expires_at', '>', now)) \
                .stream()
            
            requests = [doc.to_dict() for doc in docs]
            
            # Join sender_name client-side
            for req in requests:
                sender_civ = self.get_civilization(req['sender_id'])
                req['sender_name'] = sender_civ['name'] if sender_civ else 'Unknown'
            
            return requests
        except Exception as e:
            logger.error(f"Error getting trade requests: {e}")
            return []

    def get_trade_request_by_id(self, request_id: int) -> Optional[Dict]:
        """Get a specific trade request by ID"""
        try:
            doc_ref = self.client.collection('trade_requests').document(str(request_id))  # Assuming ID is str
            doc = doc_ref.get()
            if doc.exists and doc.to_dict()['expires_at'] > datetime.utcnow():
                return doc.to_dict()
            return None
        except Exception as e:
            logger.error(f"Error getting trade request by ID: {e}")
            return None

    def delete_trade_request(self, request_id: int) -> bool:
        """Delete a trade request"""
        try:
            doc_ref = self.client.collection('trade_requests').document(str(request_id))
            doc_ref.delete()
            return True
        except Exception as e:
            logger.error(f"Error deleting trade request: {e}")
            return False

    def create_alliance_invite(self, alliance_id: int, sender_id: str, recipient_id: str) -> bool:
        """Invite a user to an alliance"""
        try:
            doc_ref = self.client.collection('alliance_invitations').document()
            doc_ref.set({
                'alliance_id': alliance_id,
                'sender_id': sender_id,
                'recipient_id': recipient_id,
                'created_at': firestore.SERVER_TIMESTAMP,
                'expires_at': datetime.utcnow() + timedelta(days=1)
            })
            logger.info(f"Alliance invite created: alliance={alliance_id} to {recipient_id}")
            return True
        except Exception as e:
            logger.error(f"Error creating alliance invite: {e}")
            return False

    def get_alliance_invites(self, user_id: str) -> List[Dict]:
        """Get active alliance invites for a user"""
        try:
            now = datetime.utcnow()
            docs = self.client.collection('alliance_invitations') \
                .where(filter=FieldFilter('recipient_id', '==', user_id)) \
                .where(filter=FieldFilter('expires_at', '>', now)) \
                .stream()
            
            invites = [doc.to_dict() for doc in docs]
            
            # Join alliance_name client-side
            for invite in invites:
                alliance = self.get_alliance(invite['alliance_id'])
                invite['alliance_name'] = alliance['name'] if alliance else 'Unknown'
            
            return invites
        except Exception as e:
            logger.error(f"Error getting alliance invites: {e}")
            return []

    def get_alliance_invite_by_id(self, invite_id: int) -> Optional[Dict]:
        """Get a specific alliance invite by ID"""
        try:
            doc_ref = self.client.collection('alliance_invitations').document(str(invite_id))
            doc = doc_ref.get()
            if doc.exists and doc.to_dict()['expires_at'] > datetime.utcnow():
                invite = doc.to_dict()
                alliance = self.get_alliance(invite['alliance_id'])
                invite['alliance_name'] = alliance['name'] if alliance else 'Unknown'
                return invite
            return None
        except Exception as e:
            logger.error(f"Error getting alliance invite by ID: {e}")
            return None

    def delete_alliance_invite(self, invite_id: int) -> bool:
        """Delete an alliance invitation"""
        try:
            doc_ref = self.client.collection('alliance_invitations').document(str(invite_id))
            doc_ref.delete()
            return True
        except Exception as e:
            logger.error(f"Error deleting alliance invite: {e}")
            return False

    def send_message(self, sender_id: str, recipient_id: str, message: str) -> bool:
        """Send a message between users"""
        try:
            doc_ref = self.client.collection('messages').document()
            doc_ref.set({
                'sender_id': sender_id,
                'recipient_id': recipient_id,
                'message': message,
                'created_at': firestore.SERVER_TIMESTAMP,
                'expires_at': datetime.utcnow() + timedelta(days=1)
            })
            logger.info(f"Message sent from {sender_id} to {recipient_id}")
            return True
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return False

    def get_messages(self, user_id: str) -> List[Dict]:
        """Get active messages for a user"""
        try:
            now = datetime.utcnow()
            docs = self.client.collection('messages') \
                .where(filter=FieldFilter('recipient_id', '==', user_id)) \
                .where(filter=FieldFilter('expires_at', '>', now)) \
                .stream()
            
            messages = [doc.to_dict() for doc in docs]
            
            # Join sender_name client-side
            for msg in messages:
                sender_civ = self.get_civilization(msg['sender_id'])
                msg['sender_name'] = sender_civ['name'] if sender_civ else 'Unknown'
            
            return messages
        except Exception as e:
            logger.error(f"Error getting messages: {e}")
            return []

    def delete_message(self, message_id: int) -> bool:
        """Delete a message"""
        try:
            doc_ref = self.client.collection('messages').document(str(message_id))
            doc_ref.delete()
            return True
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
            return False

    def get_alliance(self, alliance_id: int) -> Optional[Dict]:
        """Get alliance data by ID"""
        try:
            doc_ref = self.client.collection('alliances').document(str(alliance_id))
            doc = doc_ref.get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Error getting alliance: {e}")
            return None

    def get_alliance_by_name(self, name: str) -> Optional[Dict]:
        """Get alliance data by name"""
        try:
            doc_ref = self.client.collection('alliances').document(name)
            doc = doc_ref.get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Error getting alliance by name: {e}")
            return None

    def add_alliance_member(self, alliance_id: int, user_id: str) -> bool:
        """Add member to alliance"""
        try:
            doc_ref = self.client.collection('alliances').document(str(alliance_id))
            doc = doc_ref.get()
            if not doc.exists:
                return False
            
            alliance = doc.to_dict()
            if user_id in alliance.get('members', []):
                return True
            
            members = alliance.get('members', []) + [user_id]
            join_requests = [uid for uid in alliance.get('join_requests', []) if uid != user_id]
            
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
            collection = self.client.collection('wars')
            if user_id:
                query = collection.where(filter=FieldFilter('result', '==', status)) \
                    .where(filter=FieldFilter('attacker_id', 'in', [user_id]))  # Firestore 'in' limited, so split if needed
                wars_attacker = [doc.to_dict() for doc in query.stream()]
                
                query = collection.where(filter=FieldFilter('result', '==', status)) \
                    .where(filter=FieldFilter('defender_id', '==', user_id))
                wars_defender = [doc.to_dict() for doc in query.stream()]
                
                wars = wars_attacker + wars_defender
            else:
                query = collection.where(filter=FieldFilter('result', '==', status))
                wars = [doc.to_dict() for doc in query.stream()]
            
            # Join names client-side
            for war in wars:
                attacker_civ = self.get_civilization(war['attacker_id'])
                defender_civ = self.get_civilization(war['defender_id'])
                war['attacker_name'] = attacker_civ['name'] if attacker_civ else 'Unknown'
                war['defender_name'] = defender_civ['name'] if defender_civ else 'Unknown'
            
            return wars
        except Exception as e:
            logger.error(f"Error getting wars: {e}")
            return []

    def get_peace_offers(self, user_id: str = None) -> List[Dict]:
        """Get peace offers for a user or all peace offers"""
        try:
            collection = self.client.collection('peace_offers')
            if user_id:
                query = collection.where(filter=FieldFilter('status', '==', 'pending')) \
                    .where(filter=FieldFilter('offerer_id', '==', user_id))
                offers_sent = [doc.to_dict() for doc in query.stream()]
                
                query = collection.where(filter=FieldFilter('status', '==', 'pending')) \
                    .where(filter=FieldFilter('receiver_id', '==', user_id))
                offers_received = [doc.to_dict() for doc in query.stream()]
                
                offers = offers_sent + offers_received
            else:
                query = collection.where(filter=FieldFilter('status', '==', 'pending'))
                offers = [doc.to_dict() for doc in query.stream()]
            
            # Join names client-side
            for offer in offers:
                offerer_civ = self.get_civilization(offer['offerer_id'])
                receiver_civ = self.get_civilization(offer['receiver_id'])
                offer['offerer_name'] = offerer_civ['name'] if offerer_civ else 'Unknown'
                offer['receiver_name'] = receiver_civ['name'] if receiver_civ else 'Unknown'
            
            return offers
        except Exception as e:
            logger.error(f"Error getting peace offers: {e}")
            return []

    def create_peace_offer(self, offerer_id: str, receiver_id: str) -> bool:
        """Create a peace offer"""
        try:
            doc_ref = self.client.collection('peace_offers').document()
            doc_ref.set({
                'offerer_id': offerer_id,
                'receiver_id': receiver_id,
                'status': 'pending',
                'offered_at': firestore.SERVER_TIMESTAMP,
                'responded_at': None
            })
            logger.info(f"Peace offer created from {offerer_id} to {receiver_id}")
            return True
        except Exception as e:
            logger.error(f"Error creating peace offer: {e}")
            return False

    def update_peace_offer(self, offer_id: int, status: str) -> bool:
        """Update peace offer status"""
        try:
            doc_ref = self.client.collection('peace_offers').document(str(offer_id))
            doc_ref.update({
                'status': status,
                'responded_at': firestore.SERVER_TIMESTAMP
            })
            return True
        except Exception as e:
            logger.error(f"Error updating peace offer: {e}")
            return False

    def end_war(self, attacker_id: str, defender_id: str, result: str) -> bool:
        """End a war between two civilizations"""
        try:
            # Find and update - Firestore requires querying first
            query = self.client.collection('wars') \
                .where(filter=FieldFilter('result', '==', 'ongoing')) \
                .where(filter=FieldFilter('attacker_id', '==', attacker_id)) \
                .where(filter=FieldFilter('defender_id', '==', defender_id))
            docs = query.stream()
            
            updated = False
            for doc in docs:
                doc.reference.update({
                    'result': result,
                    'ended_at': firestore.SERVER_TIMESTAMP
                })
                updated = True
            
            # Check reverse
            if not updated:
                query = self.client.collection('wars') \
                    .where(filter=FieldFilter('result', '==', 'ongoing')) \
                    .where(filter=FieldFilter('attacker_id', '==', defender_id)) \
                    .where(filter=FieldFilter('defender_id', '==', attacker_id))
                docs = query.stream()
                for doc in docs:
                    doc.reference.update({
                        'result': result,
                        'ended_at': firestore.SERVER_TIMESTAMP
                    })
                    updated = True
            
            return updated
        except Exception as e:
            logger.error(f"Error ending war: {e}")
            return False

    def get_user_statistics(self, user_id: str) -> Dict[str, Any]:
        """Get comprehensive statistics for a user"""
        try:
            civ = self.get_civilization(user_id)
            if not civ:
                return {}
            
            # War stats - query and count client-side
            wars = self.get_wars(user_id, 'all')  # Assume you add status='all' support or fetch all
            war_stats = {
                'total_wars': len(wars),
                'victories': sum(1 for w in wars if w['result'] == 'victory'),
                'defeats': sum(1 for w in wars if w['result'] == 'defeat'),
                'peace_treaties': sum(1 for w in wars if w['result'] == 'peace')
            }
            
            # Event count
            query = self.client.collection('events').where(filter=FieldFilter('user_id', '==', user_id))
            event_count = len(list(query.stream()))
            
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
                'total_events': event_count,
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
                    military_power = (civ['military']['soldiers'] * 10 + 
                                      civ['military']['spies'] * 5 + 
                                      civ['military']['tech_level'] * 50)
                    economic_power = sum(civ['resources'].values())
                    territorial_power = civ['territory']['land_size']
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
        """Automatically remove expired requests (call this periodically)"""
        try:
            now = datetime.utcnow()
            
            # Batch delete for efficiency
            batch = self.client.batch()
            
            # Trade requests
            query = self.client.collection('trade_requests').where(filter=FieldFilter('expires_at', '<=', now))
            for doc in query.stream():
                batch.delete(doc.reference)
            
            # Alliance invites
            query = self.client.collection('alliance_invitations').where(filter=FieldFilter('expires_at', '<=', now))
            for doc in query.stream():
                batch.delete(doc.reference)
            
            # Messages
            query = self.client.collection('messages').where(filter=FieldFilter('expires_at', '<=', now))
            for doc in query.stream():
                batch.delete(doc.reference)
            
            batch.commit()
            logger.info("Cleaned up expired requests")
            return True
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            return False

    def backup_database(self, backup_path: str = None) -> bool:
        """Create a backup of the database - Firestore backups are via Google Cloud console or export"""
        logger.warning("Firestore backups are handled via Firebase Console or gcloud export - not implementing here")
        return False  # Or implement via admin SDK if needed

    def get_database_info(self) -> Dict[str, Any]:
        """Get database information and statistics"""
        try:
            info = {}
            
            # Count docs in collections (approx, fetch all for small DB)
            collections = [
                'civilizations', 'wars', 'peace_offers', 'alliances', 
                'events', 'trade_requests', 'messages', 'cards', 
                'cooldowns', 'alliance_invitations'
            ]
            
            for coll in collections:
                info[f'{coll}_count'] = len(list(self.client.collection(coll).stream()))
            
            # No file size for Firestore
            info['database_size_bytes'] = 'N/A (Firestore)'
            
            # Active users (last_active > now - 7 days)
            seven_days_ago = datetime.utcnow() - timedelta(days=7)
            query = self.client.collection('civilizations').where(filter=FieldFilter('last_active', '>', seven_days_ago))
            info['active_users_week'] = len(list(query.stream()))
            
            return info
            
        except Exception as e:
            logger.error(f"Error getting database info: {e}")
            return {}

    def close_connections(self):
        """Close all database connections (for shutdown) - not needed for Firestore"""
        pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
