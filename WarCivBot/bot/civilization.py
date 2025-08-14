import random
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from bot.database import Database

logger = logging.getLogger(__name__)

class CivilizationManager:
    def __init__(self, db: Database):
        self.db = db
        
        # Ideology modifiers
        self.ideology_modifiers = {
            "fascism": {
                "soldier_training_speed": 1.25,
                "diplomacy_success": 0.85,
                "luck_modifier": 0.90
            },
            "democracy": {
                "happiness_boost": 1.20,
                "trade_profit": 1.10,
                "soldier_training_speed": 0.85
            },
            "communism": {
                "citizen_productivity": 1.10,
                "tech_speed": 0.90
            },
            "theocracy": {
                "propaganda_success": 1.15,
                "happiness_boost": 1.05,
                "tech_speed": 0.90
            },
            "anarchy": {
                "random_event_frequency": 2.0,
                "soldier_upkeep": 0.0,
                "spy_success": 0.80
            },
            # NEW IDEOLOGY: Destruction
            "destruction": {
                "combat_strength": 1.35,
                "resource_production": 0.75,
                "soldier_training_speed": 1.40,
                "happiness_boost": 0.70,
                "diplomacy_success": 0.50
            },
            # NEW IDEOLOGY: Pacifist
            "pacifist": {
                "happiness_boost": 1.35,
                "population_growth": 1.25,
                "trade_profit": 1.20,
                "soldier_training_speed": 0.40,
                "combat_strength": 0.60,
                "diplomacy_success": 1.25
            }
        }

    def create_civilization(self, user_id: str, name: str, bonus_resources: Dict = None, bonuses: Dict = None, hyper_item: str = None) -> bool:
        """Create a new civilization"""
        return self.db.create_civilization(user_id, name, bonus_resources, bonuses, hyper_item)

    def get_civilization(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get civilization data"""
        return self.db.get_civilization(user_id)

    def set_ideology(self, user_id: str, ideology: str) -> bool:
        """Set civilization ideology"""
        return self.db.update_civilization(user_id, {"ideology": ideology})

    def update_resources(self, user_id: str, resource_changes: Dict[str, int]) -> bool:
        """Update civilization resources"""
        civ = self.get_civilization(user_id)
        if not civ:
            return False
            
        resources = civ['resources']
        
        # Apply changes
        for resource, change in resource_changes.items():
            if resource in resources:
                resources[resource] = max(0, resources[resource] + change)
        
        return self.db.update_civilization(user_id, {"resources": resources})

    def update_population(self, user_id: str, population_changes: Dict[str, int]) -> bool:
        """Update civilization population stats"""
        civ = self.get_civilization(user_id)
        if not civ:
            return False
            
        population = civ['population']
        
        # Apply changes with bounds checking
        for stat, change in population_changes.items():
            if stat in population:
                if stat in ['happiness', 'hunger']:
                    population[stat] = max(0, min(100, population[stat] + change))
                else:
                    population[stat] = max(0, population[stat] + change)
        
        return self.db.update_civilization(user_id, {"population": population})

    def update_military(self, user_id: str, military_changes: Dict[str, int]) -> bool:
        """Update civilization military stats"""
        civ = self.get_civilization(user_id)
        if not civ:
            return False
            
        military = civ['military']
        
        # Apply changes
        for stat, change in military_changes.items():
            if stat in military:
                military[stat] = max(0, military[stat] + change)
        
        return self.db.update_civilization(user_id, {"military": military})

    def add_hyper_item(self, user_id: str, item: str) -> bool:
        """Add a HyperItem to civilization"""
        civ = self.get_civilization(user_id)
        if not civ:
            return False
            
        hyper_items = civ['hyper_items']
        hyper_items.append(item)
        
        return self.db.update_civilization(user_id, {"hyper_items": hyper_items})

    def use_hyper_item(self, user_id: str, item: str) -> bool:
        """Use/consume a HyperItem"""
        civ = self.get_civilization(user_id)
        if not civ:
            return False
            
        hyper_items = civ['hyper_items']
        if item not in hyper_items:
            return False
            
        hyper_items.remove(item)
        return self.db.update_civilization(user_id, {"hyper_items": hyper_items})

    def calculate_resource_income(self, user_id: str) -> Dict[str, int]:
        """Calculate passive resource income"""
        civ = self.get_civilization(user_id)
        if not civ:
            return {}
            
        population = civ['population']
        territory = civ['territory']
        ideology = civ.get('ideology', '')
        
        # Base income calculations
        base_gold = int(population['citizens'] * 0.1 * (territory['land_size'] / 1000))
        base_food = int(population['citizens'] * 0.2)
        
        # Apply ideology modifiers
        if ideology == 'communism':
            base_gold = int(base_gold * self.ideology_modifiers['communism']['citizen_productivity'])
            base_food = int(base_food * self.ideology_modifiers['communism']['citizen_productivity'])
        elif ideology == 'democracy':
            base_gold = int(base_gold * self.ideology_modifiers['democracy']['trade_profit'])
        # NEW: Destruction resource penalty
        elif ideology == 'destruction':
            resource_mod = self.ideology_modifiers['destruction']['resource_production']
            base_gold = int(base_gold * resource_mod)
            base_food = int(base_food * resource_mod)
        # NEW: Pacifist trade bonus
        elif ideology == 'pacifist':
            base_gold = int(base_gold * self.ideology_modifiers['pacifist']['trade_profit'])
            
        return {
            "gold": base_gold,
            "food": base_food,
            "stone": random.randint(0, 5),
            "wood": random.randint(0, 5)
        }

    def calculate_upkeep_costs(self, user_id: str) -> Dict[str, int]:
        """Calculate military and population upkeep costs"""
        civ = self.get_civilization(user_id)
        if not civ:
            return {}
            
        population = civ['population']
        military = civ['military']
        ideology = civ.get('ideology', '')
        
        # Population food consumption
        food_consumption = int(population['citizens'] * 0.3)
        
        # Military upkeep
        soldier_upkeep = military['soldiers'] * 2
        spy_upkeep = military['spies'] * 5
        
        # Apply ideology modifiers
        if ideology == 'anarchy':
            soldier_upkeep = 0  # No soldier upkeep in anarchy
            
        return {
            "food": food_consumption,
            "gold": soldier_upkeep + spy_upkeep
        }

    def apply_happiness_effects(self, user_id: str):
        """Apply effects based on civilization happiness"""
        civ = self.get_civilization(user_id)
        if not civ:
            return
            
        population = civ['population']
        happiness = population['happiness']
        
        # Low happiness effects
        if happiness < 20:
            # Chance of population revolt
            if random.random() < 0.1:
                revolt_loss = int(population['citizens'] * 0.05)
                self.update_population(user_id, {"citizens": -revolt_loss})
                self.db.log_event(user_id, "revolt", "Population Revolt", 
                                f"Low happiness caused {revolt_loss} citizens to leave!")
                                
        # High happiness effects
        elif happiness > 80:
            # Chance of population growth
            if random.random() < 0.15:
                growth = int(population['citizens'] * 0.03)
                self.update_population(user_id, {"citizens": growth})
                self.db.log_event(user_id, "growth", "Population Boom", 
                                f"High happiness attracted {growth} new citizens!")

    def process_hunger(self, user_id: str):
        """Process hunger effects on population"""
        civ = self.get_civilization(user_id)
        if not civ:
            return
            
        population = civ['population']
        resources = civ['resources']
        
        # Calculate food needed
        food_needed = int(population['citizens'] * 0.2)
        
        if resources['food'] < food_needed:
            # Not enough food - increase hunger
            hunger_increase = min(20, food_needed - resources['food'])
            self.update_population(user_id, {"hunger": hunger_increase})
            
            # Severe hunger effects
            if population['hunger'] > 80:
                starvation_loss = int(population['citizens'] * 0.02)
                self.update_population(user_id, {"citizens": -starvation_loss, "happiness": -10})
                self.db.log_event(user_id, "famine", "Famine Strikes", 
                                f"Severe hunger caused {starvation_loss} citizens to perish!")
        else:
            # Enough food - reduce hunger and consume food
            self.update_resources(user_id, {"food": -food_needed})
            if population['hunger'] > 0:
                self.update_population(user_id, {"hunger": -5})

    def get_ideology_modifier(self, user_id: str, modifier_type: str) -> float:
        """Get ideology modifier for specific action"""
        civ = self.get_civilization(user_id)
        if not civ or not civ.get('ideology'):
            return 1.0
            
        ideology = civ['ideology']
        modifiers = self.ideology_modifiers.get(ideology, {})
        return modifiers.get(modifier_type, 1.0)

    def get_name_bonus(self, user_id: str, bonus_type: str) -> float:
        """Get name-based bonus"""
        civ = self.get_civilization(user_id)
        if not civ:
            return 0.0
            
        bonuses = civ.get('bonuses', {})
        return bonuses.get(f"{bonus_type}_bonus", 0.0) / 100.0  # Convert percentage to decimal

    def calculate_total_modifier(self, user_id: str, action_type: str) -> float:
        """Calculate total modifier for an action"""
        base_modifier = 1.0
        
        # Apply ideology modifier
        ideology_modifier = self.get_ideology_modifier(user_id, action_type)
        
        # Apply name bonuses
        name_bonus = 0.0
        if action_type == "luck":
            name_bonus = self.get_name_bonus(user_id, "luck")
        elif action_type == "diplomacy":
            name_bonus = self.get_name_bonus(user_id, "diplomacy")
            
        return base_modifier * ideology_modifier + name_bonus

    def can_afford(self, user_id: str, costs: Dict[str, int]) -> bool:
        """Check if civilization can afford given costs"""
        civ = self.get_civilization(user_id)
        if not civ:
            return False
            
        resources = civ['resources']
        
        for resource, cost in costs.items():
            if resource in resources and resources[resource] < cost:
                return False
                
        return True

    def spend_resources(self, user_id: str, costs: Dict[str, int]) -> bool:
        """Spend resources if affordable"""
        if not self.can_afford(user_id, costs):
            return False
            
        # Convert costs to negative values for update_resources
        negative_costs = {resource: -cost for resource, cost in costs.items()}
        return self.update_resources(user_id, negative_costs)

    def get_civilization_power(self, user_id: str) -> int:
        """Calculate civilization's total power score"""
        civ = self.get_civilization(user_id)
        if not civ:
            return 0
            
        resources = civ['resources']
        population = civ['population']
        military = civ['military']
        territory = civ['territory']
        
        # Calculate power components
        resource_power = sum(resources.values()) // 10
        population_power = population['citizens'] * 2
        military_power = military['soldiers'] * 5 + military['spies'] * 10
        tech_power = military['tech_level'] * 100
        territory_power = territory['land_size'] // 100
        happiness_power = population['happiness']
        
        total_power = (resource_power + population_power + military_power + 
                      tech_power + territory_power + happiness_power)
        
        return total_power