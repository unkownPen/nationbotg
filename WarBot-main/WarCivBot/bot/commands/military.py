import random
import re
import logging
from datetime import datetime

import guilded
from guilded.ext import commands

from bot.utils import format_number, create_embed, check_cooldown_decorator

logger = logging.getLogger(__name__)


class MilitaryCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.civ_manager = bot.civ_manager
        self.create_tables()

    def create_tables(self):
        """Create necessary database tables"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS wars (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        attacker_id TEXT NOT NULL,
                        defender_id TEXT NOT NULL,
                        war_type TEXT NOT NULL,
                        result TEXT NOT NULL DEFAULT 'ongoing',
                        declared_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        ended_at TIMESTAMP
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS peace_offers (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        offerer_id TEXT NOT NULL,
                        receiver_id TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        offered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        responded_at TIMESTAMP
                    )
                ''')
                conn.commit()
        except Exception as e:
            logger.error(f"Error creating tables: {e}", exc_info=True)

    def _extract_user_id(self, input_str: str) -> str:
        """
        Extract user ID from a mention string like <@id> (or <@!id>) or return
        the input if it looks like an ID (alphanumeric, length >= 6).
        Returns None if extraction fails.
        """
        if not input_str:
            return None

        # If it's a mention like <@ac5egiu8e> or <@!ac5egiu8e>
        if input_str.startswith('<@') and input_str.endswith('>'):
            inner = input_str[2:-1]
            inner = inner.lstrip('!')  # handle possible ! form
            inner = inner.strip()
            if inner:
                return inner

        # If it's a raw ID (alphanumeric)
        if input_str.isalnum() and len(input_str) >= 6:
            return input_str

        # Try to find an alphanumeric token inside the string (fallback)
        m = re.search(r'[A-Za-z0-9]{6,}', input_str)
        if m:
            return m.group(0)

        return None

    async def _get_member_from_mention(self, ctx, mention: str):
        """
        Robustly resolve a mention string (or usage where user typed/displayed name)
        to a Member object.

        Priorities:
        1. If ctx.mentions exists and contains members, try to match by extracted ID.
           If not able to match, return the first mention from ctx.mentions.
        2. Use MemberConverter (guilded) to attempt to convert the provided string.
        3. Extract user id and fetch member via guild.fetch_member(user_id).
        4. Fallback: attempt to find member by name or display_name in ctx.guild.members.
        Returns None if not found.
        """
        if mention is None:
            return None

        # If the caller already passed a Member object by accident
        if hasattr(mention, "id") and hasattr(mention, "display_name"):
            return mention

        # 1) Use ctx.mentions if present (this is the most reliable)
        try:
            mentions = getattr(ctx, "mentions", None)
            if mentions:
                # If mention string contains an ID, try to match that exact mention in ctx.mentions
                user_id = self._extract_user_id(mention)
                if user_id:
                    for m in mentions:
                        if str(getattr(m, "id", "")).lower() == user_id.lower():
                            return m
                # Otherwise return the first mentioned member
                return mentions[0]
        except Exception:
            # Don't fail hard — continue fallback resolution
            logger.debug("ctx.mentions handling failed in _get_member_from_mention", exc_info=True)

        # 2) Try Guilded's MemberConverter (handles many common formats)
        try:
            converter = commands.MemberConverter()
            member = await converter.convert(ctx, mention)
            if member:
                return member
        except Exception:
            # conversion failed; continue
            pass

        # 3) Try extracting an ID and fetching by it
        user_id = self._extract_user_id(mention)
        if user_id:
            try:
                member = await ctx.guild.fetch_member(user_id)
                if member:
                    return member
            except Exception:
                # Couldn't fetch by id
                pass

        # 4) Fallback: search guild members by name/display_name (case-insensitive)
        try:
            guild_members = getattr(ctx.guild, "members", None)
            if guild_members:
                lowered = mention.lower()
                for m in guild_members:
                    try:
                        if getattr(m, "name", "").lower() == lowered or getattr(m, "display_name", "").lower() == lowered:
                            return m
                    except Exception:
                        continue
        except Exception:
            pass

        return None

    @commands.command(name='train')
    @check_cooldown_decorator(minutes=5)
    async def train_soldiers(self, ctx, unit_type: str = None, amount: int = None):
        """Train military units"""
        try:
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

            unit_type = unit_type.lower()
            if unit_type not in ['soldiers', 'spies']:
                await ctx.send("❌ Invalid unit type! Choose 'soldiers' or 'spies'.")
                return

            if amount is None or amount < 1:
                await ctx.send("❌ Please specify a valid amount to train!")
                return

            user_id = str(ctx.author.id)
            civ = self.civ_manager.get_civilization(user_id)

            if not civ:
                await ctx.send("❌ You need to start a civilization first! Use `.start`")
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

            # Apply ideology and card modifiers to training speed
            training_modifier = self.civ_manager.get_ideology_modifier(user_id, "soldier_training_speed")
            bonus_units = 0
            penalty_units = 0

            if training_modifier > 1.0:
                # Faster training - chance for bonus units
                bonus_chance = (training_modifier - 1.0) * 0.5
                if random.random() < bonus_chance:
                    bonus_units = max(1, amount // 10)
                    amount += bonus_units

            elif training_modifier < 1.0:
                # Slower training - chance to lose some units
                penalty_chance = (1.0 - training_modifier) * 0.5
                if random.random() < penalty_chance:
                    penalty_units = max(1, amount // 10)
                    amount = max(1, amount - penalty_units)

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

            # Add bonus/penalty messages
            if bonus_units > 0:
                embed.add_field(name="Bonus Units", value=f"🎉 Ideology bonus added {bonus_units} extra units!", inline=True)
            if penalty_units > 0:
                embed.add_field(name="Training Issues", value=f"⚠️ Ideology penalty lost {penalty_units} units during training", inline=True)

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in train command: {e}", exc_info=True)
            await ctx.send("❌ An error occurred while training units. Please try again.")

    @commands.command(name='declare')
    async def declare_war(self, ctx, target_mention: str = None):
        """Declare war on another civilization"""
        try:
            if not target_mention:
                await ctx.send("⚔️ **Declaration of War**\nUsage: `.declare @user`\nNote: War must be declared before attacking!")
                return

            user_id = str(ctx.author.id)
            civ = self.civ_manager.get_civilization(user_id)

            if not civ:
                await ctx.send("❌ You need to start a civilization first! Use `.start`")
                return

            # Try to resolve the member from the argument / message mentions
            target = await self._get_member_from_mention(ctx, target_mention)
            if not target:
                await ctx.send("❌ Could not find that user. Make sure you're mentioning a valid user in this server.")
                return

            target_id = str(target.id)

            if target_id == user_id:
                await ctx.send("❌ You cannot declare war on yourself!")
                return

            target_civ = self.civ_manager.get_civilization(target_id)
            if not target_civ:
                await ctx.send("❌ Target user doesn't have a civilization!")
                return

            # Check if war is already ongoing
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id FROM wars 
                    WHERE ((attacker_id = ? AND defender_id = ?) OR (attacker_id = ? AND defender_id = ?))
                    AND result = 'ongoing'
                ''', (user_id, target_id, target_id, user_id))

                if cursor.fetchone():
                    await ctx.send("❌ You're already at war with this civilization!")
                    return

                # Store war declaration in database
                cursor.execute('''
                    INSERT INTO wars (attacker_id, defender_id, war_type, declared_at)
                    VALUES (?, ?, ?, ?)
                ''', (user_id, target_id, 'declared', datetime.utcnow()))

                conn.commit()

            # Log the declaration
            self.db.log_event(user_id, "war_declaration", "War Declared",
                              f"{civ['name']} has declared war on {target_civ['name']}!")

            embed = create_embed(
                "⚔️ War Declared!",
                f"**{civ['name']}** has officially declared war on **{target_civ['name']}**!",
                guilded.Color.red()
            )
            embed.add_field(name="Next Steps", value="You can now use `.attack`, `.siege`, `.stealthbattle`, or `.cards` to gain advantages.", inline=False)

            await ctx.send(embed=embed)
            # safe mention
            try:
                await ctx.send(f"{target.mention} ⚔️ **WAR DECLARED!** {civ['name']} (led by {ctx.author.display_name}) has declared war on your civilization!")
            except Exception:
                await ctx.send(f"⚔️ **WAR DECLARED!** {civ['name']} (led by {ctx.author.display_name}) has declared war on **{target_civ['name']}**!")

        except Exception as e:
            logger.error(f"Error declaring war: {e}", exc_info=True)
            await ctx.send("❌ Failed to declare war. Please try again.")

    @commands.command(name='attack')
    @check_cooldown_decorator(minutes=15)
    async def attack_civilization(self, ctx, target_mention: str = None):
        """Launch a direct attack on another civilization"""
        try:
            if not target_mention:
                await ctx.send("⚔️ **Direct Attack**\nUsage: `.attack @user`\nNote: War must be declared first!")
                return

            user_id = str(ctx.author.id)
            civ = self.civ_manager.get_civilization(user_id)

            if not civ:
                await ctx.send("❌ You need to start a civilization first! Use `.start`")
                return

            if civ['military']['soldiers'] < 10:
                await ctx.send("❌ You need at least 10 soldiers to launch an attack!")
                return

            # Resolve target
            target = await self._get_member_from_mention(ctx, target_mention)
            if not target:
                await ctx.send("❌ Could not find that user. Make sure you're mentioning a valid user in this server.")
                return

            target_id = str(target.id)

            if target_id == user_id:
                await ctx.send("❌ You cannot attack yourself!")
                return

            target_civ = self.civ_manager.get_civilization(target_id)
            if not target_civ:
                await ctx.send("❌ Target user doesn't have a civilization!")
                return

            # Check if war declared
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id FROM wars 
                    WHERE ((attacker_id = ? AND defender_id = ?) OR (attacker_id = ? AND defender_id = ?))
                    AND result = 'ongoing'
                ''', (user_id, target_id, target_id, user_id))

                war = cursor.fetchone()
                if not war:
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

            # Destruction and pacifist ideology effects
            if civ.get('ideology') == 'destruction':
                attacker_roll *= 1.15  # More aggressive
                defender_roll *= 0.9   # Less defensive
            if target_civ.get('ideology') == 'pacifist':
                defender_roll *= 0.85  # Pacifists are worse at defense

            final_attacker_strength = attacker_strength * attacker_roll
            final_defender_strength = defender_strength * defender_roll

            # Determine outcome
            if final_attacker_strength > final_defender_strength:
                victory_margin = final_attacker_strength / max(1, final_defender_strength)
                await self._process_attack_victory(ctx, user_id, target_id, civ, target_civ, victory_margin)
            else:
                defeat_margin = final_defender_strength / max(1, final_attacker_strength)
                await self._process_attack_defeat(ctx, user_id, target_id, civ, target_civ, defeat_margin)

        except Exception as e:
            logger.error(f"Error in attack command: {e}", exc_info=True)
            await ctx.send("❌ An error occurred during the attack. Please try again later.")

    async def _process_attack_victory(self, ctx, attacker_id, defender_id, attacker_civ, defender_civ, margin):
        """Process successful attack"""
        try:
            attacker_losses = min(random.randint(2, 8), attacker_civ['military']['soldiers'])
            defender_losses = min(int(attacker_losses * margin), defender_civ['military']['soldiers'])

            # Resource spoils
            spoils = {
                "gold": min(int(defender_civ['resources']['gold'] * 0.15), defender_civ['resources']['gold']),
                "food": min(int(defender_civ['resources']['food'] * 0.10), defender_civ['resources']['food']),
                "stone": min(int(defender_civ['resources']['stone'] * 0.10), defender_civ['resources']['stone']),
                "wood": min(int(defender_civ['resources']['wood'] * 0.10), defender_civ['resources']['wood'])
            }

            # Territory gain
            territory_gained = min(int(defender_civ['territory']['land_size'] * 0.05), defender_civ['territory']['land_size'])

            # Apply changes
            self.civ_manager.update_military(attacker_id, {"soldiers": -attacker_losses})
            self.civ_manager.update_military(defender_id, {"soldiers": -defender_losses})

            self.civ_manager.update_resources(attacker_id, spoils)
            negative_spoils = {res: -amt for res, amt in spoils.items()}
            self.civ_manager.update_resources(defender_id, negative_spoils)

            self.civ_manager.update_territory(attacker_id, {"land_size": territory_gained})
            self.civ_manager.update_territory(defender_id, {"land_size": -territory_gained})

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
            embed.add_field(name="Spoils of War", value=spoils_text or "None", inline=True)
            embed.add_field(name="Territory Gained", value=f"🏞️ {format_number(territory_gained)} km²", inline=True)

            # Destruction ideology bonus
            if attacker_civ.get('ideology') == 'destruction':
                extra_damage = min(int(defender_civ['resources']['gold'] * 0.05), defender_civ['resources']['gold'])
                self.civ_manager.update_resources(defender_id, {"gold": -extra_damage})
                embed.add_field(name="Destruction Bonus",
                                value=f"Your destructive forces caused extra damage! (-{format_number(extra_damage)} enemy gold)",
                                inline=False)

            await ctx.send(embed=embed)

            # Log the victory
            self.db.log_event(attacker_id, "victory", "Battle Victory", f"Defeated {defender_civ['name']} in battle!")
            self.db.log_event(defender_id, "defeat", "Battle Defeat", f"Defeated by {attacker_civ['name']} in battle.")

            # Try to mention the defender
            try:
                # guilded mention should work via member mention; try to fetch member first
                member = None
                try:
                    member = await ctx.guild.fetch_member(defender_id)
                except Exception:
                    # ignore
                    pass
                if member:
                    await ctx.send(f"{member.mention} ⚔️ Your civilization **{defender_civ['name']}** was defeated by **{attacker_civ['name']}** in battle!")
                else:
                    await ctx.send(f"⚔️ The civilization **{defender_civ['name']}** was defeated by **{attacker_civ['name']}** in battle!")
            except Exception:
                await ctx.send(f"⚔️ The civilization **{defender_civ['name']}** was defeated by **{attacker_civ['name']}** in battle!")

        except Exception as e:
            logger.error(f"Error processing attack victory: {e}", exc_info=True)
            await ctx.send("❌ An error occurred processing the battle results.")

    async def _process_attack_defeat(self, ctx, attacker_id, defender_id, attacker_civ, defender_civ, margin):
        """Process failed attack"""
        try:
            attacker_losses = min(int(random.randint(5, 15) * margin), attacker_civ['military']['soldiers'])
            defender_losses = min(random.randint(2, 5), defender_civ['military']['soldiers'])

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
                                    value="The defenders have offered a chance for peace through diplomacy! Use `.peace @user` to propose peace.",
                                    inline=False)

            await ctx.send(embed=embed)

            # Log the defeat
            self.db.log_event(attacker_id, "defeat", "Battle Defeat", f"Defeated by {defender_civ['name']} in battle.")
            self.db.log_event(defender_id, "victory", "Battle Victory", f"Successfully defended against {attacker_civ['name']}!")

            # Try to mention the defender
            try:
                member = None
                try:
                    member = await ctx.guild.fetch_member(defender_id)
                except Exception:
                    pass
                if member:
                    await ctx.send(f"{member.mention} ⚔️ Your civilization **{defender_civ['name']}** successfully defended against **{attacker_civ['name']}**!")
                else:
                    await ctx.send(f"⚔️ The civilization **{defender_civ['name']}** successfully defended against **{attacker_civ['name']}**!")
            except Exception:
                await ctx.send(f"⚔️ The civilization **{defender_civ['name']}** successfully defended against **{attacker_civ['name']}**!")

        except Exception as e:
            logger.error(f"Error processing attack defeat: {e}", exc_info=True)
            await ctx.send("❌ An error occurred processing the battle results.")

    @commands.command(name='stealthbattle')
    @check_cooldown_decorator(minutes=20)
    async def stealth_battle(self, ctx, target_mention: str = None):
        """Conduct a spy-based stealth attack"""
        try:
            if not target_mention:
                await ctx.send("🕵️ **Stealth Battle**\nUsage: `.stealthbattle @user`\nUses spies instead of soldiers for covert operations.")
                return

            user_id = str(ctx.author.id)
            civ = self.civ_manager.get_civilization(user_id)

            if not civ:
                await ctx.send("❌ You need to start a civilization first! Use `.start`")
                return

            if civ['military']['spies'] < 3:
                await ctx.send("❌ You need at least 3 spies to conduct stealth operations!")
                return

            # Resolve target
            target = await self._get_member_from_mention(ctx, target_mention)
            if not target:
                await ctx.send("❌ Could not find that user. Make sure you're mentioning a valid user in this server.")
                return

            target_id = str(target.id)
            target_civ = self.civ_manager.get_civilization(target_id)
            if not target_civ:
                await ctx.send("❌ Target user doesn't have a civilization!")
                return

            # Calculate spy operation success
            attacker_spy_power = civ['military']['spies'] * civ['military']['tech_level']
            defender_spy_power = target_civ['military']['spies'] * target_civ['military']['tech_level']

            # Base success chance
            success_chance = 0.6 + (attacker_spy_power - defender_spy_power) / 100
            success_chance = max(0.2, min(0.9, success_chance))

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
                result_text = ""

                if operation_type == 'sabotage':
                    # Damage infrastructure
                    damage = {
                        "stone": -random.randint(50, 200),
                        "wood": -random.randint(30, 150)
                    }
                    self.civ_manager.update_resources(target_id, damage)
                    result_text = "Your spies sabotaged enemy infrastructure!"

                    # Destruction ideology bonus
                    if civ.get('ideology') == 'destruction':
                        extra_damage = {
                            "gold": -random.randint(20, 100),
                            "food": -random.randint(30, 120)
                        }
                        self.civ_manager.update_resources(target_id, extra_damage)
                        result_text += f" Your destructive spies caused extra chaos!"

                elif operation_type == 'theft':
                    # Steal resources
                    stolen = min(int(target_civ['resources']['gold'] * random.uniform(0.05, 0.15)), target_civ['resources']['gold'])
                    self.civ_manager.update_resources(target_id, {"gold": -stolen})
                    self.civ_manager.update_resources(user_id, {"gold": stolen})
                    result_text = f"Your spies stole {format_number(stolen)} gold!"

                else:  # intel
                    # Gain tech advantage
                    tech_gain = 1 if random.random() < 0.3 else 0
                    if tech_gain:
                        self.civ_manager.update_military(user_id, {"tech_level": tech_gain})
                    result_text = "Your spies gathered valuable intelligence!" + (f" (+{tech_gain} tech level)" if tech_gain else "")

                if spy_losses > 0:
                    self.civ_manager.update_military(user_id, {"spies": -spy_losses})

                embed = create_embed(
                    "🕵️ Stealth Operation Success!",
                    result_text,
                    guilded.Color.purple()
                )

                if spy_losses > 0:
                    embed.add_field(name="Casualties", value=f"Lost {spy_losses} spies during the operation", inline=False)

                await ctx.send(embed=embed)

                # Try to mention the target
                try:
                    await ctx.send(f"{target.mention} 🕵️ Your civilization **{target_civ['name']}** was hit by a successful stealth operation from **{civ['name']}**!")
                except Exception:
                    await ctx.send(f"🕵️ The civilization **{target_civ['name']}** was hit by a successful stealth operation from **{civ['name']}**!")

            else:
                # Stealth mission fails
                spy_losses = random.randint(1, 4)
                self.civ_manager.update_military(user_id, {"spies": -spy_losses})

                embed = create_embed(
                    "🕵️ Stealth Operation Failed!",
                    f"Your stealth mission was detected! Lost {spy_losses} spies.",
                    guilded.Color.red()
                )

                await ctx.send(embed=embed)

                # Try to mention the target
                try:
                    await ctx.send(f"{target.mention} 🔍 Your intelligence network detected and thwarted a stealth attack from **{civ['name']}**!")
                except Exception:
                    await ctx.send(f"🔍 The intelligence network of **{target_civ['name']}** detected and thwarted a stealth attack from **{civ['name']}**!")

        except Exception as e:
            logger.error(f"Error in stealthbattle command: {e}", exc_info=True)
            await ctx.send("❌ An error occurred during the stealth operation. Please try again later.")

    @commands.command(name='siege')
    @check_cooldown_decorator(minutes=30)
    async def siege_city(self, ctx, target_mention: str = None):
        """Lay siege to an enemy civilization"""
        try:
            if not target_mention:
                await ctx.send("🏰 **Siege Warfare**\nUsage: `.siege @user`\nDrains enemy resources over time but requires large army.")
                return

            user_id = str(ctx.author.id)
            civ = self.civ_manager.get_civilization(user_id)

            if not civ:
                await ctx.send("❌ You need to start a civilization first! Use `.start`")
                return

            if civ['military']['soldiers'] < 50:
                await ctx.send("❌ You need at least 50 soldiers to lay siege!")
                return

            # Resolve target
            target = await self._get_member_from_mention(ctx, target_mention)
            if not target:
                await ctx.send("❌ Could not find that user. Make sure you're mentioning a valid user in this server.")
                return

            target_id = str(target.id)
            target_civ = self.civ_manager.get_civilization(target_id)
            if not target_civ:
                await ctx.send("❌ Target user doesn't have a civilization!")
                return

            # Check war declaration
            with self.db.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    SELECT id FROM wars 
                    WHERE ((attacker_id = ? AND defender_id = ?) OR (attacker_id = ? AND defender_id = ?))
                    AND result = 'ongoing'
                ''', (user_id, target_id, target_id, user_id))

                war = cursor.fetchone()
                if not war:
                    await ctx.send("❌ You must declare war first! Use `.declare @user`")
                    return

            # Calculate siege effectiveness
            siege_power = civ['military']['soldiers'] + civ['military']['tech_level'] * 10
            defender_resistance = target_civ['military']['soldiers'] + target_civ['territory']['land_size'] / 100

            siege_effectiveness = siege_power / (siege_power + defender_resistance)

            # Resource drain on defender
            resource_drain = {
                "gold": min(int(target_civ['resources']['gold'] * siege_effectiveness * 0.1), target_civ['resources']['gold']),
                "food": min(int(target_civ['resources']['food'] * siege_effectiveness * 0.2), target_civ['resources']['food']),
                "wood": min(int(target_civ['resources']['wood'] * siege_effectiveness * 0.15), target_civ['resources']['wood']),
                "stone": min(int(target_civ['resources']['stone'] * siege_effectiveness * 0.15), target_civ['resources']['stone'])
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
            self.civ_manager.update_population(target_id, {"happiness": -15})
            self.civ_manager.update_population(user_id, {"happiness": -5})

            embed = create_embed(
                "🏰 Siege in Progress",
                f"**{civ['name']}** has laid siege to **{target_civ['name']}**!",
                guilded.Color.orange()
            )

            drain_text = "\n".join([f"{'🪙' if res == 'gold' else '🌾' if res == 'food' else '🪨' if res == 'stone' else '🪵'} {format_number(amt)} {res.capitalize()}"
                                   for res, amt in resource_drain.items() if amt > 0])
            embed.add_field(name="Enemy Resources Drained", value=drain_text or "None", inline=True)

            cost_text = f"🪙 {format_number(maintenance_cost['gold'])} Gold\n🌾 {format_number(maintenance_cost['food'])} Food"
            embed.add_field(name="Siege Maintenance Cost", value=cost_text, inline=True)

            # Destruction ideology bonus
            if civ.get('ideology') == 'destruction':
                extra_damage = {
                    "gold": min(int(target_civ['resources']['gold'] * 0.05), target_civ['resources']['gold']),
                    "food": min(int(target_civ['resources']['food'] * 0.05), target_civ['resources']['food'])
                }
                self.civ_manager.update_resources(target_id, {k: -v for k, v in extra_damage.items()})
                embed.add_field(name="Destruction Bonus",
                                value=f"Your destructive siege caused extra damage!\n🪙 {format_number(extra_damage['gold'])} Gold\n🌾 {format_number(extra_damage['food'])} Food",
                                inline=False)

            await ctx.send(embed=embed)

            # Log the siege
            self.db.log_event(user_id, "siege", "Siege Initiated", f"Laying siege to {target_civ['name']}")
            self.db.log_event(target_id, "besieged", "Under Siege", f"Being sieged by {civ['name']}")

            # Try to mention the target
            try:
                await ctx.send(f"{target.mention} 🏰 Your civilization **{target_civ['name']}** is under siege by **{civ['name']}**!")
            except Exception:
                await ctx.send(f"🏰 The civilization **{target_civ['name']}** is under siege by **{civ['name']}**!")

        except Exception as e:
            logger.error(f"Error in siege command: {e}", exc_info=True)
            await ctx.send("❌ An error occurred during the siege. Please try again later.")

    @commands.command(name='find')
    @check_cooldown_decorator(minutes=10)
    async def find_soldiers(self, ctx):
        """Search for wandering soldiers to recruit"""
        try:
            user_id = str(ctx.author.id)
            civ = self.civ_manager.get_civilization(user_id)

            if not civ:
                await ctx.send("❌ You need to start a civilization first! Use `.start`")
                return

            # Base chance and amount
            base_chance = 0.5
            min_soldiers = 5
            max_soldiers = 20

            # Apply ideology modifiers
            if civ.get('ideology') == 'pacifist':
                base_chance *= 1.9  # Pacifists are more likely
                max_soldiers = 15  # Smaller groups
            elif civ.get('ideology') == 'destruction':
                base_chance *= 0.75  # Less likely but larger groups
                max_soldiers = 30
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
                    (f" (including {bonus} coerced by your destructive reputation)" if bonus else ""),
                    guilded.Color.green()
                )

                if civ.get('ideology') == 'pacifist':
                    embed.add_field(name="Pacifist Note", value="These soldiers joined reluctantly, drawn by your peaceful ideals.", inline=False)
            else:
                # Failure
                embed = create_embed(
                    "🔍 Search Unsuccessful",
                    "You couldn't find any willing soldiers to join your cause.",
                    guilded.Color.blue()
                )

                if civ.get('ideology') == 'destruction':
                    embed.add_field(name="Destruction Backfire",
                                  value="Your reputation scared away potential recruits.",
                                  inline=False)

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in find command: {e}", exc_info=True)
            await ctx.send("❌ An error occurred while searching for soldiers. Please try again later.")

    @commands.command(name='peace')
    async def make_peace(self, ctx, target_mention: str = None):
        """Offer peace to an enemy civilization"""
        try:
            if not target_mention:
                await ctx.send("🕊️ **Peace Offering**\nUsage: `.peace @user`\nSend a peace offer to end a war. They can accept with `.accept_peace @you`.")
                return

            user_id = str(ctx.author.id)
            civ = self.civ_manager.get_civilization(user_id)

            if not civ:
                await ctx.send("❌ You need to start a civilization first! Use `.start`")
                return

            # Resolve target
            target = await self._get_member_from_mention(ctx, target_mention)
            if not target:
                await ctx.send("❌ Could not find that user. Make sure you're mentioning a valid user in this server.")
                return

            target_id = str(target.id)

            if target_id == user_id:
                await ctx.send("❌ You're already at peace with yourself!")
                return

            target_civ = self.civ_manager.get_civilization(target_id)
            if not target_civ:
                await ctx.send("❌ Target user doesn't have a civilization!")
                return

            # Check if at war
            with self.db.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    SELECT id FROM wars 
                    WHERE ((attacker_id = ? AND defender_id = ?) OR (attacker_id = ? AND defender_id = ?))
                    AND result = 'ongoing'
                ''', (user_id, target_id, target_id, user_id))

                war = cursor.fetchone()
                if not war:
                    await ctx.send("❌ You're not at war with this civilization!")
                    return

            # Check if there's already a pending offer
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT COUNT(*) FROM peace_offers 
                    WHERE offerer_id = ? AND receiver_id = ? AND status = 'pending'
                ''', (user_id, target_id))

                if cursor.fetchone()[0] > 0:
                    await ctx.send("❌ You already have a pending peace offer to this civilization!")
                    return

                # Store the peace offer
                cursor.execute('''
                    INSERT INTO peace_offers (offerer_id, receiver_id)
                    VALUES (?, ?)
                ''', (user_id, target_id))

                conn.commit()

            embed = create_embed(
                "🕊️ Peace Offer Sent!",
                f"**{civ['name']}** has offered peace to **{target_civ['name']}**! They can accept with `.accept_peace @{ctx.author.display_name}`.",
                guilded.Color.green()
            )

            await ctx.send(embed=embed)

            # Try to mention the target
            try:
                await ctx.send(f"{target.mention} 🕊️ **Peace Offer Received!** {civ['name']} (led by {ctx.author.display_name}) has offered peace to end the war. Use `.accept_peace @{ctx.author.display_name}` to accept!")
            except Exception:
                await ctx.send(f"🕊️ **Peace Offer Received!** {civ['name']} (led by {ctx.author.display_name}) has offered peace to end the war. Use `.accept_peace @{ctx.author.display_name}` to accept!")

        except Exception as e:
            logger.error(f"Error in peace command: {e}", exc_info=True)
            await ctx.send("❌ Failed to send peace offer. Try again later.")

    @commands.command(name='accept_peace')
    @check_cooldown_decorator(minutes=5)
    async def accept_peace(self, ctx, target_mention: str = None):
        """Accept a peace offer from another civilization"""
        try:
            if not target_mention:
                await ctx.send("🕊️ **Accept Peace**\nUsage: `.accept_peace @user`\nAccept a pending peace offer to end the war.")
                return

            user_id = str(ctx.author.id)
            civ = self.civ_manager.get_civilization(user_id)

            if not civ:
                await ctx.send("❌ You need to start a civilization first! Use `.start`")
                return

            # Resolve target
            target = await self._get_member_from_mention(ctx, target_mention)
            if not target:
                await ctx.send("❌ Could not find that user. Make sure you're mentioning a valid user in this server.")
                return

            offerer_id = str(target.id)

            if offerer_id == user_id:
                await ctx.send("❌ You can't accept your own peace offer!")
                return

            offerer_civ = self.civ_manager.get_civilization(offerer_id)
            if not offerer_civ:
                await ctx.send("❌ That user doesn't have a civilization!")
                return

            # Check if at war
            with self.db.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    SELECT id FROM wars 
                    WHERE ((attacker_id = ? AND defender_id = ?) OR (attacker_id = ? AND defender_id = ?))
                    AND result = 'ongoing'
                ''', (user_id, offerer_id, offerer_id, user_id))

                war = cursor.fetchone()
                if not war:
                    await ctx.send("❌ You're not at war with this civilization!")
                    return

            # Check for pending offer from the offerer to this user
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id FROM peace_offers 
                    WHERE offerer_id = ? AND receiver_id = ? AND status = 'pending'
                ''', (offerer_id, user_id))

                offer = cursor.fetchone()
                if not offer:
                    await ctx.send("❌ No pending peace offer from this civilization!")
                    return

                # Accept the peace
                war_id = war[0]
                cursor.execute('''
                    UPDATE wars SET result = 'peace', ended_at = ?
                    WHERE id = ?
                ''', (datetime.utcnow(), war_id))

                # Update peace offer status
                cursor.execute('''
                    UPDATE peace_offers SET status = 'accepted', responded_at = ?
                    WHERE id = ?
                ''', (datetime.utcnow(), offer[0]))

                conn.commit()

            # Happiness boost for both
            self.civ_manager.update_population(user_id, {"happiness": 15})
            self.civ_manager.update_population(offerer_id, {"happiness": 15})

            embed = create_embed(
                "🕊️ Peace Achieved!",
                f"**{civ['name']}** has accepted peace from **{offerer_civ['name']}**! The war is over.",
                guilded.Color.green()
            )

            if civ.get('ideology') == 'pacifist' or offerer_civ.get('ideology') == 'pacifist':
                embed.add_field(name="Pacifist Influence",
                                value="The peace movement was strengthened by pacifist ideals!",
                                inline=False)

            await ctx.send(embed=embed)

            # Try to mention the target
            try:
                await ctx.send(f"{target.mention} 🕊️ **Peace Accepted!** {civ['name']} (led by {ctx.author.display_name}) has accepted your peace offer! The war is over.")
            except Exception:
                await ctx.send(f"🕊️ **Peace Accepted!** {civ['name']} (led by {ctx.author.display_name}) has accepted the peace offer! The war is over.")

            # Log events
            self.db.log_event(user_id, "peace_accepted", "Peace Accepted", f"Accepted peace with {offerer_civ['name']}")
            self.db.log_event(offerer_id, "peace_accepted", "Peace Accepted", f"Peace accepted by {civ['name']}")

        except Exception as e:
            logger.error(f"Error in accept_peace command: {e}", exc_info=True)
            await ctx.send("❌ Failed to accept peace. Try again later.")

    @commands.command(name='cards')
    @check_cooldown_decorator(minutes=5)
    async def manage_cards(self, ctx, card_name: str = None):
        """View or select a card for the current tech level"""
        try:
            user_id = str(ctx.author.id)
            civ = self.civ_manager.get_civilization(user_id)

            if not civ:
                await ctx.send("❌ You need to start a civilization first! Use `.start`")
                return

            tech_level = civ['military']['tech_level']

            if tech_level > 10:
                await ctx.send("❌ You have reached the maximum tech level (10). No more cards available!")
                return

            card_selection = self.db.get_card_selection(user_id, tech_level)

            if not card_selection:
                await ctx.send(f"❌ No card selection available for tech level {tech_level}. You may have already chosen a card or need to advance your tech level.")
                return

            if card_name:
                # Attempt to select a card
                selected_card = self.db.select_card(user_id, tech_level, card_name)
                if not selected_card:
                    await ctx.send(f"❌ Invalid card name '{card_name}'. Use `.cards` to see available options.")
                    return

                # Apply the card effect
                self.civ_manager.apply_card_effect(user_id, selected_card)

                embed = create_embed(
                    "🎴 Card Selected!",
                    f"You have chosen **{selected_card['name']}**: {selected_card['description']}",
                    guilded.Color.gold()
                )
                self.db.log_event(user_id, "card_selected", f"Card Selected: {selected_card['name']}",
                                  selected_card['description'], selected_card['effect'])
                await ctx.send(embed=embed)
            else:
                # Display available cards
                embed = create_embed(
                    f"🎴 Tech Level {tech_level} Cards",
                    "Choose a card using `.cards <card_name>`",
                    guilded.Color.blue()
                )
                cards_text = "\n".join([f"**{card['name']}**: {card['description']}" for card in card_selection['available_cards']])
                embed.add_field(name="Available Cards", value=cards_text or "No cards available", inline=False)
                await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in cards command: {e}", exc_info=True)
            await ctx.send("❌ An error occurred while managing cards. Please try again.")

    @commands.command(name='debug_military')
    async def debug_military(self, ctx, target_mention: str = None):
        """Debug command to check military and user data"""
        try:
            user_id = str(ctx.author.id)

            if target_mention:
                # Try to get the member from the mention
                target = await self._get_member_from_mention(ctx, target_mention)
                if not target:
                    await ctx.send("❌ Could not find that user. Make sure you're mentioning a valid user in this server.")
                    return

                target_id = str(target.id)
                await ctx.send(f"🔍 Debug Info:\n- Author ID: {user_id}\n- Target ID: {target_id}\n- Target Mention: {getattr(target, 'mention', str(target))}")

                # Check if target has a civilization
                target_civ = self.civ_manager.get_civilization(target_id)
                if target_civ:
                    await ctx.send(f"✅ Target civilization found: {target_civ['name']}")
                else:
                    await ctx.send("❌ Target does not have a civilization")

                # Check if war exists between users
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT * FROM wars 
                        WHERE ((attacker_id = ? AND defender_id = ?) OR (attacker_id = ? AND defender_id = ?))
                        AND result = 'ongoing'
                    ''', (user_id, target_id, target_id, user_id))

                    war = cursor.fetchone()
                    if war:
                        await ctx.send(f"⚔️ War exists between users: {war}")
                    else:
                        await ctx.send("❌ No ongoing war between these users")
            else:
                # Just show own data
                civ = self.civ_manager.get_civilization(user_id)
                if civ:
                    await ctx.send(f"✅ Your civilization: {civ['name']}\n- Soldiers: {civ['military']['soldiers']}\n- Spies: {civ['military']['spies']}")
                else:
                    await ctx.send("❌ You don't have a civilization")

        except Exception as e:
            logger.error(f"Error in debug command: {e}", exc_info=True)
            await ctx.send(f"❌ Debug error: {e}")

    def _calculate_military_strength(self, civ):
        """Calculate total military strength of a civilization"""
        try:
            soldiers = civ['military']['soldiers']
            spies = civ['military']['spies']
            tech_level = civ['military']['tech_level']
            bonuses = civ.get('bonuses', {})

            base_strength = soldiers * 10 + spies * 5
            tech_bonus = tech_level * 50
            territory_bonus = civ['territory']['land_size'] / 100
            defense_bonus = bonuses.get('defense_strength', 0) / 100

            return (base_strength + tech_bonus + territory_bonus) * (1 + defense_bonus)
        except KeyError as e:
            logger.error(f"Error calculating military strength - missing key {e}", exc_info=True)
            return 0
        except Exception as e:
            logger.error(f"Error calculating military strength: {e}", exc_info=True)
            return 0


async def setup(bot):
    await bot.add_cog(MilitaryCommands(bot))
