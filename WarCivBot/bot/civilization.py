# Civilization.py
import random
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from bot.database import Database

logger = logging.getLogger(__name__)

class CivilizationManager:
    def __init__(self, db: Database):
        self.db = db
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
            "destruction": {
                "combat_strength": 1.35,
                "resource_production": 0.75,
                "soldier_training_speed": 1.40,
                "happiness_boost": 0.70,
                "diplomacy_success": 0.50
            },
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
        civ = self.db.get_civilization(user_id)
        if civ and 'employed' not in civ['population']:
            civ['population']['employed'] = civ['population']['citizens'] // 2
            self.db.update_civilization(user_id, {"population": civ['population']})
        return civ

    def set_ideology(self, user_id: str, ideology: str) -> bool:
        """Set civilization ideology"""
        return self.db.update_civilization(user_id, {"ideology": ideology})

    def update_resources(self, user_id: str, resource_changes: Dict[str, int]) -> bool:
        """Update civilization resources"""
        civ = self.get_civilization(user_id)
        if not civ:
            return False
            
        resources = civ['resources']
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
        for stat, change in population_changes.items():
            if stat in population:
                if stat in ['happiness', 'hunger']:
                    population[stat] = max(0, min(100, population[stat] + change))
                elif stat == 'citizens':
                    population['citizens'] = max(0, population['citizens'] + change)
                    population['employed'] = min(population.get('employed', 0), population['citizens'])
                else:
                    population[stat] = max(0, population[stat] + change)
        
        return self.db.update_civilization(user_id, {"population": population})

    def update_military(self, user_id: str, military_changes: Dict[str, int]) -> bool:
        """Update civilization military stats, checking for tech level increase"""
        civ = self.get_civilization(user_id)
        if not civ:
            return False
            
        military = civ['military']
        old_tech_level = military['tech_level']
        
        for stat, change in military_changes.items():
            if stat in military:
                if stat == 'tech_level':
                    military[stat] = min(10, max(1, military[stat] + change))  # Cap at 10
                else:
                    military[stat] = max(0, military[stat] + change)
        
        new_tech_level = military['tech_level']
        result = self.db.update_civilization(user_id, {"military": military})
        
        if result and new_tech_level > old_tech_level and new_tech_level <= 10:
            self.db.generate_card_selection(user_id, new_tech_level)
            self.db.log_event(user_id, "tech_advance", "Tech Level Increased",
                            f"Reached tech level {new_tech_level}. New card selection available!")
        
        return result

    def update_employment(self, user_id: str, change: int) -> bool:
        """Update employed citizens"""
        civ = self.get_civilization(user_id)
        if not civ:
            return False
        
        population = civ['population']
        employed = population.get('employed', 0) + change
        employed = max(0, min(population['citizens'], employed))
        population['employed'] = employed
        
        return self.db.update_civilization(user_id, {"population": population})

    def update_territory(self, user_id: str, territory_changes: Dict[str, int]) -> bool:
        """Update civilization territory stats"""
        civ = self.get_civilization(user_id)
        if not civ:
            return False
            
        territory = civ['territory']
        for stat, change in territory_changes.items():
            if stat in territory:
                territory[stat] = max(0, territory[stat] + change)
        
        return self.db.update_civilization(user_id, {"territory": territory})

    def get_employment_rate(self, user_id: str) -> float:
        """Get employment rate percentage"""
        civ = self.get_civilization(user_id)
        if not civ:
            return 0.0
        
        population = civ['population']
        citizens = population['citizens']
        employed = population.get('employed', 0)
        return (employed / citizens * 100) if citizens > 0 else 0.0

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

    def apply_card_effect(self, user_id: str, card: Dict) -> bool:
        """Apply the effect of a selected card"""
        civ = self.get_civilization(user_id)
        if not civ:
            return False
            
        effect = card['effect']
        card_type = card['type']
        
        if card_type == "bonus":
            bonuses = civ['bonuses']
            for key, value in effect.items():
                bonuses[key] = bonuses.get(key, 0) + value
            self.db.update_civilization(user_id, {"bonuses": bonuses})
        
        elif card_type == "one_time":
            if "gold" in effect or "food" in effect or "stone" in effect or "wood" in effect:
                self.update_resources(user_id, effect)
            elif "soldiers" in effect or "spies" in effect or "tech_level" in effect:
                self.update_military(user_id, effect)
            elif "citizens" in effect or "happiness" in effect or "hunger" in effect:
                self.update_population(user_id, effect)
        
        selected_cards = civ['selected_cards']
        selected_cards.append(card['name'])
        self.db.update_civilization(user_id, {"selected_cards": selected_cards})
        
        self.db.log_event(user_id, "card_selected", f"Card Selected: {card['name']}",
                         card['description'], effect)
        return True

    def calculate_resource_income(self, user_id: str) -> Dict[str, int]:
        """Calculate passive resource income"""
        civ = self.get_civilization(user_id)
        if not civ:
            return {}
            
        population = civ['population']
        territory = civ['territory']
        ideology = civ.get('ideology', '')
        bonuses = civ['bonuses']
        employment_rate = self.get_employment_rate(user_id)
        employment_modifier = employment_rate / 100
        
        base_gold = int(population['citizens'] * 0.1 * (territory['land_size'] / 1000) * employment_modifier)
        base_food = int(population['citizens'] * 0.2 * employment_modifier)
        
        resource_modifier = 1.0
        if ideology == 'communism':
            resource_modifier *= self.ideology_modifiers['communism']['citizen_productivity']
        elif ideology == 'democracy':
            resource_modifier *= self.ideology_modifiers['democracy']['trade_profit']
        elif ideology == 'destruction':
            resource_modifier *= self.ideology_modifiers['destruction']['resource_production']
        elif ideology == 'pacifist':
            resource_modifier *= self.ideology_modifiers['pacifist']['trade_profit']
        
        resource_modifier *= (1 + bonuses.get('resource_production', 0) / 100)
        
        return {
            "gold": int(base_gold * resource_modifier),
            "food": int(base_food * resource_modifier),
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
        
        food_consumption = int(population['citizens'] * 0.3)
        soldier_upkeep = military['soldiers'] * 2
        spy_upkeep = military['spies'] * 5
        
        if ideology == 'anarchy':
            soldier_upkeep = 0
            
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
        bonuses = civ['bonuses']
        
        happiness_modifier = 1 + bonuses.get('happiness_boost', 0) / 100
        happiness = int(happiness * happiness_modifier)
        
        if happiness < 20:
            if random.random() < 0.1:
                revolt_loss = int(population['citizens'] * 0.05)
                self.update_population(user_id, {"citizens": -revolt_loss})
                self.db.log_event(user_id, "revolt", "Population Revolt",
                                f"Low happiness caused {revolt_loss} citizens to leave!")
        
        elif happiness > 80:
            growth_rate = bonuses.get('population_growth', 0) / 100
            if ideology == 'pacifist':
                growth_rate += self.ideology_modifiers['pacifist']['population_growth'] - 1
            if random.random() < (0.15 + growth_rate):
                growth = int(population['citizens'] * (0.03 + growth_rate))
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
        
        food_needed = int(population['citizens'] * 0.2)
        
        if resources['food'] < food_needed:
            hunger_increase = min(20, food_needed - resources['food'])
            self.update_population(user_id, {"hunger": hunger_increase})
            
            if population['hunger'] > 80:
                starvation_loss = int(population['citizens'] * 0.02)
                self.update_population(user_id, {"citizens": -starvation_loss, "happiness": -10})
                self.db.log_event(user_id, "famine", "Famine Strikes",
                                f"Severe hunger caused {starvation_loss} citizens to perish!")
        else:
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
        base_modifier = modifiers.get(modifier_type, 1.0)
        
        if modifier_type in ['soldier_training_speed', 'combat_strength', 'trade_profit', 'population_growth']:
            return base_modifier + (civ['bonuses'].get(modifier_type, 0) / 100)
        return base_modifier

    def get_name_bonus(self, user_id: str, bonus_type: str) -> float:
        """Get name-based bonus"""
        civ = self.get_civilization(user_id)
        if not civ:
            return 0.0
            
        bonuses = civ.get('bonuses', {})
        return bonuses.get(f"{bonus_type}_bonus", 0.0) / 100.0

    def calculate_total_modifier(self, user_id: str, action_type: str) -> float:
        """Calculate total modifier for an action"""
        base_modifier = 1.0
        ideology_modifier = self.get_ideology_modifier(user_id, action_type)
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
        bonuses = civ['bonuses']
        
        resource_power = sum(resources.values()) // 10
        population_power = population['citizens'] * 2
        military_power = military['soldiers'] * 5 + military['spies'] * 10
        tech_power = military['tech_level'] * 100
        territory_power = territory['land_size'] // 100
        happiness_power = population['happiness']
        
        defense_bonus = bonuses.get('defense_strength', 0)
        total_power = (resource_power + population_power + military_power +
                      tech_power + territory_power + happiness_power)
        
        total_power = int(total_power * (1 + defense_bonus / 100))
        return total_power
