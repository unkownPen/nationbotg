import random
import guilded
from guilded.ext import commands
import logging
from bot.utils import format_number, check_cooldown_decorator, create_embed

logger = logging.getLogger(__name__)

class MilitaryCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.civ_manager = bot.civ_manager

    @commands.command(name='train')
    @check_cooldown_decorator(minutes=10)
    async def train_soldiers(self, ctx, unit_type: str = None, amount: int = None):
        """Train military units"""
        if not unit_type:
            embed = create_embed(
                "⚔️ Military Training",
                "Train units to strengthen your army!",
                guilded.Color.blue()
            )
            embed.add_field(name="Available Units", value="`soldiers` - Basic infantry (50 gold, 10 food each)\n`spies` - Intelligence operatives (100 gold, 5 food each)", inline=False)
            embed.add_field(name="Usage", value="`.train <unit_type> <amount>`", inline=False)
            await ctx.send(embed=embed)
            return
            
        if unit_type not in ['soldiers', 'spies']:
            await ctx.send("❌ Invalid unit type! Choose 'soldiers' or 'spies'.")
            return
            
        if amount is None or amount < 1:
            await ctx.send("❌ Please specify a valid amount to train!")
            return
            
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return
            
        # Calculate costs
        if unit_type == 'soldiers':
            gold_cost = amount * 50
            food_cost = amount * 10
        else:  # spies
            gold_cost = amount * 100
            food_cost = amount * 5
            
        costs = {"gold": gold_cost, "food": food_cost}
        
        # Check if affordable
        if not self.civ_manager.can_afford(user_id, costs):
            await ctx.send(f"❌ Not enough resources! Need {format_number(gold_cost)} gold and {format_number(food_cost)} food.")
            return
            
        # Apply ideology modifier to training speed
        training_modifier = self.civ_manager.get_ideology_modifier(user_id, "soldier_training_speed")
        
        if training_modifier > 1.0:
            # Faster training - chance for bonus units
            bonus_chance = (training_modifier - 1.0) * 2  # Convert to bonus chance
            if random.random() < bonus_chance:
                bonus_units = max(1, amount // 10)
                amount += bonus_units
                
        elif training_modifier < 1.0:
            # Slower training - chance to lose some units
            penalty_chance = (1.0 - training_modifier) * 2
            if random.random() < penalty_chance:
                lost_units = max(1, amount // 10)
                amount = max(1, amount - lost_units)
        
        # Spend resources
        self.civ_manager.spend_resources(user_id, costs)
        
        # Add units
        military_update = {unit_type: amount}
        self.civ_manager.update_military(user_id, military_update)
        
        embed = create_embed(
            f"⚔️ Training Complete",
            f"Successfully trained {format_number(amount)} {unit_type}!",
            guilded.Color.green()
        )
        
        embed.add_field(name="Cost", value=f"🪙 {format_number(gold_cost)} Gold\n🌾 {format_number(food_cost)} Food", inline=True)
        
        # Add ideology-specific flavor text
        ideology = civ.get('ideology', '')
        if ideology == 'fascism' and training_modifier > 1.0:
            embed.add_field(name="Regime Bonus", value="Fascist efficiency boosted training!", inline=True)
        elif ideology == 'democracy' and training_modifier < 1.0:
            embed.add_field(name="Democratic Process", value="Democratic oversight slowed training.", inline=True)
            
        await ctx.send(embed=embed)

    @commands.command(name='declare')
    @check_cooldown_decorator(minutes=60)
    async def declare_war(self, ctx, target: str = None):
        """Declare war on another civilization"""
        if not target:
            await ctx.send("⚔️ **Declaration of War**\nUsage: `.declare @user`\nNote: War must be declared before attacking!")
            return
            
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return
            
        # Parse target (simple implementation)
        if target.startswith('<@') and target.endswith('>'):
            target_id = target[2:-1]
            if target_id.startswith('!'):
                target_id = target_id[1:]
        else:
            await ctx.send("❌ Please mention a valid user to declare war on!")
            return
            
        if target_id == user_id:
            await ctx.send("❌ You cannot declare war on yourself!")
            return
            
        target_civ = self.civ_manager.get_civilization(target_id)
        if not target_civ:
            await ctx.send("❌ Target user doesn't have a civilization!")
            return
            
        # Store war declaration in database
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO wars (attacker_id, defender_id, war_type, result)
                VALUES (?, ?, ?, ?)
            ''', (user_id, target_id, 'declared', 'ongoing'))
            
            conn.commit()
            
            # Log the declaration
            self.db.log_event(user_id, "war_declaration", "War Declared", 
                            f"{civ['name']} has declared war on {target_civ['name']}!")
            
            embed = create_embed(
                "⚔️ War Declared!",
                f"**{civ['name']}** has officially declared war on **{target_civ['name']}**!",
                guilded.Color.red()
            )
            embed.add_field(name="Next Steps", value="You can now use `.attack`, `.siege`, or `.stealthbattle` against this civilization.", inline=False)
            
            await ctx.send(embed=embed)
            
            # Try to notify the target
            try:
                target_user = await self.bot.fetch_user(int(target_id))
                await target_user.send(f"⚔️ **WAR DECLARED!** {civ['name']} (led by {ctx.author.name}) has declared war on your civilization!")
            except:
                pass  # User might have DMs disabled
                
        except Exception as e:
            logger.error(f"Error declaring war: {e}")
            await ctx.send("❌ Failed to declare war. Please try again.")

    @commands.command(name='attack')
    @check_cooldown_decorator(minutes=30)
    async def attack_civilization(self, ctx, target: str = None):
        """Launch a direct attack on another civilization"""
        if not target:
            await ctx.send("⚔️ **Direct Attack**\nUsage: `.attack @user`\nNote: War must be declared first!")
            return
            
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return
            
        if civ['military']['soldiers'] < 10:
            await ctx.send("❌ You need at least 10 soldiers to launch an attack!")
            return
            
        # Parse target
        if target.startswith('<@') and target.endswith('>'):
            target_id = target[2:-1]
            if target_id.startswith('!'):
                target_id = target_id[1:]
        else:
            await ctx.send("❌ Please mention a valid user to attack!")
            return
            
        if target_id == user_id:
            await ctx.send("❌ You cannot attack yourself!")
            return
            
        target_civ = self.civ_manager.get_civilization(target_id)
        if not target_civ:
            await ctx.send("❌ Target user doesn't have a civilization!")
            return
            
        # Check if war is declared
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COUNT(*) FROM wars 
            WHERE attacker_id = ? AND defender_id = ? AND result = 'ongoing'
        ''', (user_id, target_id))
        
        if cursor.fetchone()[0] == 0:
            await ctx.send("❌ You must declare war first! Use `.declare @user`")
            return
            
        # Calculate battle strength
        attacker_strength = self._calculate_military_strength(civ)
        defender_strength = self._calculate_military_strength(target_civ)
        
        # Apply random factors and modifiers
        attacker_roll = random.uniform(0.8, 1.2)
        defender_roll = random.uniform(0.8, 1.2)
        
        # Apply ideology modifiers
        if civ.get('ideology') == 'fascism':
            attacker_roll *= 1.1  # Military bonus
        if target_civ.get('ideology') == 'fascism':
            defender_roll *= 1.1
            
        final_attacker_strength = attacker_strength * attacker_roll
        final_defender_strength = defender_strength * defender_roll
        
        # Determine outcome
        if final_attacker_strength > final_defender_strength:
            # Attacker wins
            victory_margin = final_attacker_strength / final_defender_strength
            await self._process_attack_victory(ctx, user_id, target_id, civ, target_civ, victory_margin)
        else:
            # Defender wins
            defeat_margin = final_defender_strength / final_attacker_strength
            await self._process_attack_defeat(ctx, user_id, target_id, civ, target_civ, defeat_margin)

    async def _process_attack_victory(self, ctx, attacker_id, defender_id, attacker_civ, defender_civ, margin):
        """Process successful attack"""
        # Calculate losses and gains
        attacker_losses = random.randint(2, 8)
        defender_losses = int(attacker_losses * margin)
        
        # Resource spoils
        spoils = {
            "gold": int(defender_civ['resources']['gold'] * 0.15),
            "food": int(defender_civ['resources']['food'] * 0.10),
            "stone": int(defender_civ['resources']['stone'] * 0.10),
            "wood": int(defender_civ['resources']['wood'] * 0.10)
        }
        
        # Territory gain
        territory_gained = int(defender_civ['territory']['land_size'] * 0.05)
        
        # Apply changes
        self.civ_manager.update_military(attacker_id, {"soldiers": -attacker_losses})
        self.civ_manager.update_military(defender_id, {"soldiers": -defender_losses})
        
        self.civ_manager.update_resources(attacker_id, spoils)
        negative_spoils = {res: -amt for res, amt in spoils.items()}
        self.civ_manager.update_resources(defender_id, negative_spoils)
        
        self.civ_manager.update_resources(attacker_id, {"territory": {"land_size": territory_gained}})
        self.civ_manager.update_resources(defender_id, {"territory": {"land_size": -territory_gained}})
        
        # Create victory embed
        embed = create_embed(
            "⚔️ Victory!",
            f"**{attacker_civ['name']}** has defeated **{defender_civ['name']}** in battle!",
            guilded.Color.green()
        )
        
        embed.add_field(name="Battle Results", 
                       value=f"Your Losses: {attacker_losses} soldiers\nEnemy Losses: {defender_losses} soldiers", 
                       inline=True)
        
        spoils_text = "\n".join([f"{'🪙' if res == 'gold' else '🌾' if res == 'food' else '🪨' if res == 'stone' else '🪵'} {format_number(amt)} {res.capitalize()}" 
                               for res, amt in spoils.items() if amt > 0])
        embed.add_field(name="Spoils of War", value=spoils_text, inline=True)
        embed.add_field(name="Territory Gained", value=f"🏞️ {format_number(territory_gained)} km²", inline=True)
        
        await ctx.send(embed=embed)
        
        # Log the victory
        self.db.log_event(attacker_id, "victory", "Battle Victory", f"Defeated {defender_civ['name']} in battle!")
        self.db.log_event(defender_id, "defeat", "Battle Defeat", f"Defeated by {attacker_civ['name']} in battle.")

    async def _process_attack_defeat(self, ctx, attacker_id, defender_id, attacker_civ, defender_civ, margin):
        """Process failed attack"""
        # Calculate losses
        attacker_losses = int(random.randint(5, 15) * margin)
        defender_losses = random.randint(2, 5)
        
        # Apply losses
        self.civ_manager.update_military(attacker_id, {"soldiers": -attacker_losses})
        self.civ_manager.update_military(defender_id, {"soldiers": -defender_losses})
        
        # Happiness penalty for failed attack
        self.civ_manager.update_population(attacker_id, {"happiness": -10})
        
        embed = create_embed(
            "⚔️ Defeat!",
            f"**{attacker_civ['name']}** was defeated by **{defender_civ['name']}**!",
            guilded.Color.red()
        )
        
        embed.add_field(name="Battle Results", 
                       value=f"Your Losses: {attacker_losses} soldiers\nEnemy Losses: {defender_losses} soldiers", 
                       inline=True)
        embed.add_field(name="Consequences", value="Your people are demoralized! (-10 happiness)", inline=False)
        
        await ctx.send(embed=embed)
        
        # Log the defeat
        self.db.log_event(attacker_id, "defeat", "Battle Defeat", f"Defeated by {defender_civ['name']} in battle.")
        self.db.log_event(defender_id, "victory", "Battle Victory", f"Successfully defended against {attacker_civ['name']}!")

    @commands.command(name='stealthbattle')
    @check_cooldown_decorator(minutes=45)
    async def stealth_battle(self, ctx, target: str = None):
        """Conduct a spy-based stealth attack"""
        if not target:
            await ctx.send("🕵️ **Stealth Battle**\nUsage: `.stealthbattle @user`\nUses spies instead of soldiers for covert operations.")
            return
            
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return
            
        if civ['military']['spies'] < 3:
            await ctx.send("❌ You need at least 3 spies to conduct stealth operations!")
            return
            
        # Parse target (same as attack command)
        if target.startswith('<@') and target.endswith('>'):
            target_id = target[2:-1]
            if target_id.startswith('!'):
                target_id = target_id[1:]
        else:
            await ctx.send("❌ Please mention a valid user to attack!")
            return
            
        target_civ = self.civ_manager.get_civilization(target_id)
        if not target_civ:
            await ctx.send("❌ Target user doesn't have a civilization!")
            return
            
        # Calculate spy operation success
        attacker_spy_power = civ['military']['spies'] * civ['military']['tech_level']
        defender_spy_power = target_civ['military']['spies'] * target_civ['military']['tech_level']
        
        # Base success chance
        success_chance = 0.6 + (attacker_spy_power - defender_spy_power) / 100
        success_chance = max(0.2, min(0.9, success_chance))  # Clamp between 20-90%
        
        # Apply ideology modifiers
        if civ.get('ideology') == 'anarchy':
            success_chance *= 0.8  # Anarchy penalty to spy success
        if target_civ.get('ideology') == 'fascism':
            success_chance *= 0.9  # Fascist states are harder to infiltrate
            
        if random.random() < success_chance:
            # Stealth mission succeeds
            spy_losses = random.randint(0, 2)
            
            # Stealth operations cause different effects
            operation_type = random.choice(['sabotage', 'theft', 'intel'])
            
            if operation_type == 'sabotage':
                # Damage infrastructure
                damage = {
                    "stone": -random.randint(50, 200),
                    "wood": -random.randint(30, 150)
                }
                self.civ_manager.update_resources(defender_id, damage)
                result_text = "Your spies sabotaged enemy infrastructure!"
                
            elif operation_type == 'theft':
                # Steal resources
                stolen = {
                    "gold": int(target_civ['resources']['gold'] * random.uniform(0.05, 0.15))
                }
                self.civ_manager.update_resources(attacker_id, stolen)
                self.civ_manager.update_resources(defender_id, {"gold": -stolen["gold"]})
                result_text = f"Your spies stole {format_number(stolen['gold'])} gold!"
                
            else:  # intel
                # Gain tech advantage
                tech_gain = 1 if random.random() < 0.3 else 0
                if tech_gain:
                    self.civ_manager.update_military(attacker_id, {"tech_level": tech_gain})
                result_text = "Your spies gathered valuable intelligence!" + (f" (+{tech_gain} tech level)" if tech_gain else "")
            
            if spy_losses > 0:
                self.civ_manager.update_military(attacker_id, {"spies": -spy_losses})
                
            embed = create_embed(
                "🕵️ Stealth Operation Success!",
                result_text,
                guilded.Color.purple()
            )
            
            if spy_losses > 0:
                embed.add_field(name="Casualties", value=f"Lost {spy_losses} spies during the operation", inline=False)
                
        else:
            # Stealth mission fails
            spy_losses = random.randint(1, 4)
            self.civ_manager.update_military(attacker_id, {"spies": -spy_losses})
            
            embed = create_embed(
                "🕵️ Stealth Operation Failed!",
                f"Your stealth mission was detected! Lost {spy_losses} spies.",
                guilded.Color.red()
            )
            
            # Notify defender of the attempt
            try:
                target_user = await self.bot.fetch_user(int(target_id))
                await target_user.send(f"🔍 **Security Alert!** Your intelligence network detected and thwarted a stealth attack from {civ['name']}!")
            except:
                pass
                
        await ctx.send(embed=embed)

    @commands.command(name='siege')
    @check_cooldown_decorator(minutes=60)
    async def siege_city(self, ctx, target: str = None):
        """Lay siege to an enemy civilization"""
        if not target:
            await ctx.send("🏰 **Siege Warfare**\nUsage: `.siege @user`\nDrains enemy resources over time but requires large army.")
            return
            
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return
            
        if civ['military']['soldiers'] < 50:
            await ctx.send("❌ You need at least 50 soldiers to lay siege!")
            return
            
        # Parse target (same logic as before)
        if target.startswith('<@') and target.endswith('>'):
            target_id = target[2:-1]
            if target_id.startswith('!'):
                target_id = target_id[1:]
        else:
            await ctx.send("❌ Please mention a valid user to siege!")
            return
            
        target_civ = self.civ_manager.get_civilization(target_id)
        if not target_civ:
            await ctx.send("❌ Target user doesn't have a civilization!")
            return
            
        # Check war declaration
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COUNT(*) FROM wars 
            WHERE attacker_id = ? AND defender_id = ? AND result = 'ongoing'
        ''', (user_id, target_id))
        
        if cursor.fetchone()[0] == 0:
            await ctx.send("❌ You must declare war first! Use `.declare @user`")
            return
            
        # Calculate siege effectiveness
        siege_power = civ['military']['soldiers'] + civ['military']['tech_level'] * 10
        defender_resistance = target_civ['military']['soldiers'] + target_civ['territory']['land_size'] / 100
        
        siege_effectiveness = siege_power / (siege_power + defender_resistance)
        
        # Resource drain on defender
        resource_drain = {
            "gold": int(target_civ['resources']['gold'] * siege_effectiveness * 0.1),
            "food": int(target_civ['resources']['food'] * siege_effectiveness * 0.2),
            "wood": int(target_civ['resources']['wood'] * siege_effectiveness * 0.15),
            "stone": int(target_civ['resources']['stone'] * siege_effectiveness * 0.15)
        }
        
        # Attacker maintenance costs
        maintenance_cost = {
            "gold": civ['military']['soldiers'] * 2,
            "food": civ['military']['soldiers'] * 3
        }
        
        if not self.civ_manager.can_afford(user_id, maintenance_cost):
            await ctx.send("❌ You cannot afford to maintain the siege! Need more gold and food.")
            return
            
        # Apply siege effects
        self.civ_manager.spend_resources(user_id, maintenance_cost)
        negative_drain = {res: -amt for res, amt in resource_drain.items()}
        self.civ_manager.update_resources(target_id, negative_drain)
        
        # Happiness effects
        self.civ_manager.update_population(target_id, {"happiness": -15})  # Being sieged is demoralizing
        self.civ_manager.update_population(user_id, {"happiness": -5})  # Sieging is expensive
        
        embed = create_embed(
            "🏰 Siege in Progress",
            f"**{civ['name']}** has laid siege to **{target_civ['name']}**!",
            guilded.Color.orange()
        )
        
        drain_text = "\n".join([f"{'🪙' if res == 'gold' else '🌾' if res == 'food' else '🪨' if res == 'stone' else '🪵'} {format_number(amt)} {res.capitalize()}" 
                               for res, amt in resource_drain.items() if amt > 0])
        embed.add_field(name="Enemy Resources Drained", value=drain_text, inline=True)
        
        cost_text = f"🪙 {format_number(maintenance_cost['gold'])} Gold\n🌾 {format_number(maintenance_cost['food'])} Food"
        embed.add_field(name="Siege Maintenance Cost", value=cost_text, inline=True)
        
        await ctx.send(embed=embed)
        
        # Log the siege
        self.db.log_event(user_id, "siege", "Siege Initiated", f"Laying siege to {target_civ['name']}")
        self.db.log_event(target_id, "besieged", "Under Siege", f"Being sieged by {civ['name']}")

    def _calculate_military_strength(self, civ):
        """Calculate total military strength of a civilization"""
        soldiers = civ['military']['soldiers']
        spies = civ['military']['spies']
        tech_level = civ['military']['tech_level']
        
        base_strength = soldiers * 10 + spies * 5
        tech_bonus = tech_level * 50
        
        # Territory defensive bonus
        territory_bonus = civ['territory']['land_size'] / 100
        
        return base_strength + tech_bonus + territory_bonus
