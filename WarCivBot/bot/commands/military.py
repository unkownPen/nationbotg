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
    @check_cooldown_decorator(minutes=1)
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
    @check_cooldown_decorator(minutes=1)
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
    @check_cooldown_decorator(minutes=1)
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
            
        # Destruction ideology bonus/penalty
        if civ.get('ideology') == 'destruction':
            attacker_roll *= 1.15  # More aggressive
            defender_roll *= 0.9   # But less defensive
        if target_civ.get('ideology') == 'pacifist':
            defender_roll *= 0.85  # Pacifists are worse at defense
            
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
        
        # Destruction ideology bonus
        if attacker_civ.get('ideology') == 'destruction':
            extra_damage = int(defender_civ['resources']['gold'] * 0.05)
            self.civ_manager.update_resources(defender_id, {"gold": -extra_damage})
            embed.add_field(name="Destruction Bonus", 
                          value=f"Your destructive nature caused additional damage! (-{format_number(extra_damage)} gold)", 
                          inline=False)
        
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
        
        # Pacifist defender bonus
        if defender_civ.get('ideology') == 'pacifist':
            peace_chance = random.random()
            if peace_chance > 0.7:
                embed.add_field(name="Pacifist Appeal", 
                              value="The defenders have offered a chance for peace through diplomacy!", 
                              inline=False)
        
        await ctx.send(embed=embed)
        
        # Log the defeat
        self.db.log_event(attacker_id, "defeat", "Battle Defeat", f"Defeated by {defender_civ['name']} in battle.")
        self.db.log_event(defender_id, "victory", "Battle Victory", f"Successfully defended against {attacker_civ['name']}!")

    @commands.command(name='stealthbattle')
    @check_cooldown_decorator(minutes=5)
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
        elif civ.get('ideology') == 'destruction':
            success_chance *= 1.2  # Destruction bonus to spy success
            if random.random() < 0.1:  # 10% chance for extra destruction
                success_chance += 0.15
                
        if target_civ.get('ideology') == 'fascism':
            success_chance *= 0.9  # Fascist states are harder to infiltrate
        elif target_civ.get('ideology') == 'pacifist':
            success_chance *= 1.1  # Pacifist states are easier to infiltrate
            
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
                
                # Destruction ideology bonus
                if civ.get('ideology') == 'destruction':
                    extra_damage = {
                        "gold": -random.randint(20, 100),
                        "food": -random.randint(30, 120)
                    }
                    self.civ_manager.update_resources(defender_id, extra_damage)
                    result_text += f"\nYour destructive nature caused additional damage!"
                
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
    @check_cooldown_decorator(minutes=1)
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
        
        # Destruction ideology bonus
        if civ.get('ideology') == 'destruction':
            extra_damage = {
                "gold": int(target_civ['resources']['gold'] * 0.05),
                "food": int(target_civ['resources']['food'] * 0.05)
            }
            self.civ_manager.update_resources(target_id, {k: -v for k, v in extra_damage.items()})
            embed.add_field(name="Destruction Bonus", 
                          value=f"Your destructive nature caused extra damage!\n🪙 {format_number(extra_damage['gold'])} Gold\n🌾 {format_number(extra_damage['food'])} Food", 
                          inline=False)
        
        await ctx.send(embed=embed)
        
        # Log the siege
        self.db.log_event(user_id, "siege", "Siege Initiated", f"Laying siege to {target_civ['name']}")
        self.db.log_event(target_id, "besieged", "Under Siege", f"Being sieged by {civ['name']}")

    @commands.command(name='find')
    @check_cooldown_decorator(minutes=2)
    async def find_soldiers(self, ctx):
        """Search for wandering soldiers to recruit"""
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return
            
        # Base chance and amount
        base_chance = 0.5  # 50% chance
        min_soldiers = 5
        max_soldiers = 20
        
        # Apply ideology modifiers
        if civ.get('ideology') == 'pacifist':
            base_chance *= 0.7  # Pacifists are less likely to find soldiers
            max_soldiers = 15  # Smaller groups
        elif civ.get('ideology') == 'destruction':
            base_chance *= 1.3  # More likely to find soldiers
            max_soldiers = 30  # Larger groups
            min_soldiers = 10
            
        # Happiness modifier
        happiness_mod = 1 + (civ['population']['happiness'] / 100)
        final_chance = min(0.9, base_chance * happiness_mod)  # Cap at 90%
        
        if random.random() < final_chance:
            # Success - find soldiers
            soldiers_found = random.randint(min_soldiers, max_soldiers)
            
            # Small chance for bonus based on ideology
            bonus = 0
            if civ.get('ideology') == 'destruction' and random.random() < 0.2:
                bonus = soldiers_found // 2
                soldiers_found += bonus
                
            self.civ_manager.update_military(user_id, {"soldiers": soldiers_found})
            
            embed = create_embed(
                "🔍 Soldiers Found!",
                f"You've discovered {soldiers_found} wandering soldiers who have joined your army!" + 
                (f" (including {bonus} extra from your fearsome reputation!)" if bonus else ""),
                guilded.Color.green()
            )
            
            if civ.get('ideology') == 'pacifist':
                embed.add_field(name="Pacifist Note", value="These soldiers have joined reluctantly, drawn by your peaceful ideals.", inline=False)
        else:
            # Failure
            embed = create_embed(
                "🔍 Search Unsuccessful",
                "You couldn't find any willing soldiers to join your cause.",
                guilded.Color.blue()
            )
            
            if civ.get('ideology') == 'destruction':
                embed.add_field(name="Destruction Backfire", 
                              value="Your reputation may have scared away potential recruits!", 
                              inline=False)
        
        await ctx.send(embed=embed)

    @commands.command(name='peace')
    @check_cooldown_decorator(hours=1)
    async def make_peace(self, ctx, target: str = None):
        """Attempt to make peace with an enemy civilization"""
        if not target:
            await ctx.send("🕊️ **Peace Offering**\nUsage: `.peace @user`\nAttempt to end a war with another civilization.")
            return
            
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return
            
        # Parse target
        if target.startswith('<@') and target.endswith('>'):
            target_id = target[2:-1]
            if target_id.startswith('!'):
                target_id = target_id[1:]
        else:
            await ctx.send("❌ Please mention a valid user to make peace with!")
            return
            
        if target_id == user_id:
            await ctx.send("❌ You're already at peace with yourself!")
            return
            
        target_civ = self.civ_manager.get_civilization(target_id)
        if not target_civ:
            await ctx.send("❌ Target user doesn't have a civilization!")
            return
            
        # Check if at war
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COUNT(*) FROM wars 
            WHERE ((attacker_id = ? AND defender_id = ?) OR (attacker_id = ? AND defender_id = ?))
            AND result = 'ongoing'
        ''', (user_id, target_id, target_id, user_id))
        
        if cursor.fetchone()[0] == 0:
            await ctx.send("❌ You're not at war with this civilization!")
            return
            
        # Calculate peace chance
        base_chance = 0.6  # 60% base chance
        
        # Ideology modifiers
        if civ.get('ideology') == 'pacifist':
            base_chance += 0.3  # +30% for pacifists
        elif civ.get('ideology') == 'destruction':
            base_chance -= 0.4  # -40% for destructive civilizations
            
        if target_civ.get('ideology') == 'pacifist':
            base_chance += 0.2  # +20% if target is pacifist
        elif target_civ.get('ideology') == 'destruction':
            base_chance -= 0.3  # -30% if target is destructive
            
        # Recent battles modifier
        cursor.execute('''
            SELECT COUNT(*) FROM battles 
            WHERE (attacker_id = ? AND defender_id = ?)
            OR (attacker_id = ? AND defender_id = ?)
            AND timestamp > datetime('now', '-1 day')
        ''', (user_id, target_id, target_id, user_id))
        
        recent_battles = cursor.fetchone()[0]
        base_chance -= recent_battles * 0.1  # -10% per recent battle
        
        # Clamp between 10-90%
        final_chance = max(0.1, min(0.9, base_chance))
        
        if random.random() < final_chance:
            # Peace successful
            cursor.execute('''
                UPDATE wars SET result = 'peace' 
                WHERE ((attacker_id = ? AND defender_id = ?) OR (attacker_id = ? AND defender_id = ?))
                AND result = 'ongoing'
            ''', (user_id, target_id, target_id, user_id))
            
            conn.commit()
            
            # Happiness boost
            self.civ_manager.update_population(user_id, {"happiness": 15})
            self.civ_manager.update_population(target_id, {"happiness": 15})
            
            embed = create_embed(
                "🕊️ Peace Achieved!",
                f"**{civ['name']}** and **{target_civ['name']}** have agreed to peace!",
                guilded.Color.green()
            )
            
            if civ.get('ideology') == 'pacifist' or target_civ.get('ideology') == 'pacifist':
                embed.add_field(name="Pacifist Influence", 
                              value="The peace movement was strengthened by pacifist ideals!", 
                              inline=False)
        else:
            # Peace rejected
            embed = create_embed(
                "❌ Peace Rejected",
                f"**{target_civ['name']}** has rejected your peace offer!",
                guilded.Color.red()
            )
            
            if target_civ.get('ideology') == 'destruction':
                embed.add_field(name="Warning", 
                              value="The destructive nature of their civilization makes future peace difficult!", 
                              inline=False)
        
        await ctx.send(embed=embed)
        
        # Try to notify the target
        try:
            target_user = await self.bot.fetch_user(int(target_id))
            await target_user.send(f"🕊️ **PEACE OFFER!** {civ['name']} (led by {ctx.author.name}) has {'accepted' if final_chance else 'rejected'} your peace proposal!")
        except:
            pass  # User might have DMs disabled

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

def setup(bot):
    bot.add_cog(MilitaryCommands(bot))