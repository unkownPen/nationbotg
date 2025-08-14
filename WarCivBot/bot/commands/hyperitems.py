import random
import asyncio
import guilded
from guilded.ext import commands
import logging
from bot.utils import format_number, check_cooldown_decorator, create_embed

logger = logging.getLogger(__name__)

class HyperItemCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.civ_manager = bot.civ_manager

    def _has_hyperitem(self, user_id: str, item_name: str) -> bool:
        """Check if user has a specific HyperItem"""
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            return False
        return item_name in civ.get('hyper_items', [])

    async def _announce_global_attack(self, ctx, attacker_name: str, target_name: str, attack_type: str):
        """Announce world-ending attacks globally"""
        embed = create_embed(
            f"🌍 GLOBAL ALERT: {attack_type.upper()}",
            f"**{attacker_name}** has launched a {attack_type} against **{target_name}**!",
            guilded.Color.red()
        )
        embed.add_field(name="⚠️ World Event", value="This attack affects the global balance of power!", inline=False)
        
        # In a real implementation, this would send to all registered channels
        await ctx.send(embed=embed)

    @commands.command(name='nuke')
    @check_cooldown_decorator(minutes=5)  # 4 hour cooldown
    async def nuclear_strike(self, ctx, target: str = None):
        """Launch a devastating nuclear attack (Nuclear Warhead required)"""
        if not target:
            await ctx.send("☢️ **Nuclear Strike**\nUsage: `.nuke @user`\nRequires: Nuclear Warhead HyperItem\n⚠️ Causes massive destruction!")
            return
            
        user_id = str(ctx.author.id)
        
        if not self._has_hyperitem(user_id, "Nuclear Warhead"):
            await ctx.send("❌ You need a **Nuclear Warhead** HyperItem to use this command!")
            return
            
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need to start a civilization first!")
            return
            
        # Parse target
        if target.startswith('<@') and target.endswith('>'):
            target_id = target[2:-1]
            if target_id.startswith('!'):
                target_id = target_id[1:]
        else:
            await ctx.send("❌ Please mention a valid user to nuke!")
            return
            
        if target_id == user_id:
            await ctx.send("❌ You cannot nuke yourself!")
            return
            
        target_civ = self.civ_manager.get_civilization(target_id)
        if not target_civ:
            await ctx.send("❌ Target user doesn't have a civilization!")
            return
            
        # Check if target has Anti-Nuke Shield
        if self._has_hyperitem(target_id, "Anti-Nuke Shield"):
            # Shield blocks the nuke
            self.civ_manager.use_hyper_item(target_id, "Anti-Nuke Shield")
            
            embed = create_embed(
                "🛡️ Nuclear Strike Blocked!",
                f"**{target_civ['name']}**'s Anti-Nuke Shield completely blocked the nuclear attack!",
                guilded.Color.blue()
            )
            embed.add_field(name="Result", value="No damage was dealt. The shield was consumed.", inline=False)
            
            await ctx.send(embed=embed)
            
            # Notify target
            try:
                target_user = await self.bot.fetch_user(int(target_id))
                await target_user.send(f"🛡️ **Shield Activated!** Your Anti-Nuke Shield blocked a nuclear attack from {civ['name']}!")
            except:
                pass
                
            return
            
        # Consume the Nuclear Warhead
        self.civ_manager.use_hyper_item(user_id, "Nuclear Warhead")
        
        # Calculate massive damage
        population_loss = int(target_civ['population']['citizens'] * random.uniform(0.4, 0.7))  # 40-70% population loss
        military_loss = int(target_civ['military']['soldiers'] * random.uniform(0.6, 0.9))  # 60-90% military loss
        resource_destruction = {
            "gold": int(target_civ['resources']['gold'] * random.uniform(0.3, 0.6)),
            "food": int(target_civ['resources']['food'] * random.uniform(0.5, 0.8)),
            "wood": int(target_civ['resources']['wood'] * random.uniform(0.4, 0.7)),
            "stone": int(target_civ['resources']['stone'] * random.uniform(0.4, 0.7))
        }
        territory_loss = int(target_civ['territory']['land_size'] * random.uniform(0.2, 0.4))
        
        # Apply catastrophic damage
        self.civ_manager.update_population(target_id, {
            "citizens": -population_loss,
            "happiness": -50,  # Massive morale loss
            "hunger": 30  # Nuclear fallout causes famine
        })
        
        self.civ_manager.update_military(target_id, {
            "soldiers": -military_loss,
            "spies": -int(target_civ['military']['spies'] * 0.5)
        })
        
        negative_resources = {res: -amt for res, amt in resource_destruction.items()}
        self.civ_manager.update_resources(target_id, negative_resources)
        
        self.civ_manager.update_resources(target_id, {"territory": {"land_size": -territory_loss}})
        
        # Global announcement
        await self._announce_global_attack(ctx, civ['name'], target_civ['name'], "Nuclear Strike")
        
        # Detailed damage report
        embed = create_embed(
            "☢️ NUCLEAR DEVASTATION",
            f"**{civ['name']}** has nuked **{target_civ['name']}** with catastrophic results!",
            guilded.Color.red()
        )
        
        damage_text = f"💀 Population Lost: {format_number(population_loss)}\n⚔️ Soldiers Lost: {format_number(military_loss)}\n🏞️ Territory Lost: {format_number(territory_loss)} km²"
        embed.add_field(name="Casualties", value=damage_text, inline=True)
        
        destruction_text = "\n".join([f"{'🪙' if res == 'gold' else '🌾' if res == 'food' else '🪨' if res == 'stone' else '🪵'} {format_number(amt)} {res.capitalize()}" 
                                     for res, amt in resource_destruction.items() if amt > 0])
        embed.add_field(name="Resources Destroyed", value=destruction_text, inline=True)
        
        embed.add_field(name="☢️ Fallout Effects", value="Massive happiness loss, increased hunger, civilization in ruins", inline=False)
        
        await ctx.send(embed=embed)
        
        # Log the nuclear attack
        self.db.log_event(user_id, "nuclear_attack", "Nuclear Strike", f"Nuked {target_civ['name']} - massive destruction")
        self.db.log_event(target_id, "nuclear_victim", "Nuclear Attack Victim", f"Civilization devastated by {civ['name']}")

    @commands.command(name='obliterate')
    @check_cooldown_decorator(minutes=13)  # 8 hour cooldown
    async def obliterate_civilization(self, ctx, target: str = None):
        """Completely obliterate a civilization (HyperLaser required)"""
        if not target:
            await ctx.send("💥 **Total Obliteration**\nUsage: `.obliterate @user`\nRequires: HyperLaser HyperItem\n⚠️ COMPLETELY DESTROYS target civilization!")
            return
            
        user_id = str(ctx.author.id)
        
        if not self._has_hyperitem(user_id, "HyperLaser"):
            await ctx.send("❌ You need a **HyperLaser** HyperItem to use this command!")
            return
            
        # Parse target
        if target.startswith('<@') and target.endswith('>'):
            target_id = target[2:-1]
            if target_id.startswith('!'):
                target_id = target_id[1:]
        else:
            await ctx.send("❌ Please mention a valid user to obliterate!")
            return
            
        target_civ = self.civ_manager.get_civilization(target_id)
        if not target_civ:
            await ctx.send("❌ Target user doesn't have a civilization!")
            return
            
        civ = self.civ_manager.get_civilization(user_id)
        
        # Consume the HyperLaser
        self.civ_manager.use_hyper_item(user_id, "HyperLaser")
        
        # TOTAL DESTRUCTION - delete the civilization
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM civilizations WHERE user_id = ?', (target_id,))
            conn.commit()
            
            # Global announcement
            await self._announce_global_attack(ctx, civ['name'], target_civ['name'], "HyperLaser Obliteration")
            
            embed = create_embed(
                "💥 CIVILIZATION OBLITERATED",
                f"**{target_civ['name']}** has been completely erased from existence by **{civ['name']}**'s HyperLaser!",
                guilded.Color.dark_red()
            )
            
            embed.add_field(
                name="💀 Total Annihilation",
                value="• Entire population eliminated\n• All resources destroyed\n• Territory turned to wasteland\n• Civilization must be restarted",
                inline=False
            )
            
            embed.add_field(name="⚡ HyperLaser", value="The most devastating weapon in existence - HyperLaser consumed", inline=False)
            
            await ctx.send(embed=embed)
            
            # Notify target
            try:
                target_user = await self.bot.fetch_user(int(target_id))
                await target_user.send(f"💥 **CIVILIZATION OBLITERATED!** Your civilization has been completely destroyed by {civ['name']}'s HyperLaser! Use `.start <name>` to begin anew.")
            except:
                pass
                
            # Log the obliteration
            self.db.log_event(user_id, "obliteration", "Civilization Obliterated", f"Completely destroyed {target_civ['name']} with HyperLaser")
            
        except Exception as e:
            logger.error(f"Error obliterating civilization: {e}")
            await ctx.send("❌ Failed to obliterate civilization. Please try again.")

    @commands.command(name='shield')
    async def activate_shield(self, ctx):
        """Display Anti-Nuke Shield status"""
        user_id = str(ctx.author.id)
        
        if not self._has_hyperitem(user_id, "Anti-Nuke Shield"):
            await ctx.send("❌ You don't have an **Anti-Nuke Shield** HyperItem!")
            return
            
        civ = self.civ_manager.get_civilization(user_id)
        
        embed = create_embed(
            "🛡️ Anti-Nuke Shield",
            f"**{civ['name']}** is protected by an Anti-Nuke Shield!",
            guilded.Color.blue()
        )
        
        embed.add_field(
            name="Shield Status",
            value="✅ **ACTIVE** - Will automatically block the next nuclear attack",
            inline=False
        )
        
        embed.add_field(
            name="Protection",
            value="• Completely blocks one nuclear strike\n• Shield is consumed after use\n• No damage taken when activated",
            inline=False
        )
        
        await ctx.send(embed=embed)

    @commands.command(name='luckystrike')
    @check_cooldown_decorator(minutes=60)
    async def lucky_strike(self, ctx):
        """Use Lucky Charm for guaranteed critical success on next action"""
        user_id = str(ctx.author.id)
        
        if not self._has_hyperitem(user_id, "Lucky Charm"):
            await ctx.send("❌ You need a **Lucky Charm** HyperItem to use this command!")
            return
            
        # Consume the Lucky Charm
        self.civ_manager.use_hyper_item(user_id, "Lucky Charm")
        
        # Apply temporary luck bonus (would need to implement in actual game logic)
        civ = self.civ_manager.get_civilization(user_id)
        bonuses = civ.get('bonuses', {})
        bonuses['next_action_critical'] = True
        self.civ_manager.db.update_civilization(user_id, {"bonuses": bonuses})
        
        embed = create_embed(
            "🍀 Lucky Charm Activated!",
            f"**{civ['name']}** radiates with mystical fortune!",
            guilded.Color.gold()
        )
        
        embed.add_field(
            name="Effect",
            value="Your next combat action, resource gathering, or diplomacy attempt will have guaranteed critical success!",
            inline=False
        )
        
        embed.add_field(name="Duration", value="Until your next qualifying action", inline=False)
        
        await ctx.send(embed=embed)

    @commands.command(name='propaganda')
    @check_cooldown_decorator(minutes=3)
    async def propaganda_campaign(self, ctx, target: str = None):
        """Use Propaganda Kit to steal enemy soldiers"""
        if not target:
            await ctx.send("📢 **Propaganda Campaign**\nUsage: `.propaganda @user`\nRequires: Propaganda Kit HyperItem")
            return
            
        user_id = str(ctx.author.id)
        
        if not self._has_hyperitem(user_id, "Propaganda Kit"):
            await ctx.send("❌ You need a **Propaganda Kit** HyperItem to use this command!")
            return
            
        # Parse target
        if target.startswith('<@') and target.endswith('>'):
            target_id = target[2:-1]
            if target_id.startswith('!'):
                target_id = target_id[1:]
        else:
            await ctx.send("❌ Please mention a valid user to target!")
            return
            
        target_civ = self.civ_manager.get_civilization(target_id)
        if not target_civ:
            await ctx.send("❌ Target user doesn't have a civilization!")
            return
            
        civ = self.civ_manager.get_civilization(user_id)
        
        # Consume Propaganda Kit
        self.civ_manager.use_hyper_item(user_id, "Propaganda Kit")
        
        # Calculate soldiers stolen
        target_soldiers = target_civ['military']['soldiers']
        soldiers_stolen = int(target_soldiers * random.uniform(0.15, 0.35))  # 15-35% of enemy soldiers
        
        # Apply ideology modifiers
        propaganda_modifier = self.civ_manager.get_ideology_modifier(user_id, "propaganda_success")
        soldiers_stolen = int(soldiers_stolen * propaganda_modifier)
        
        if soldiers_stolen < 1:
            soldiers_stolen = 1
            
        # Transfer soldiers
        self.civ_manager.update_military(target_id, {"soldiers": -soldiers_stolen})
        self.civ_manager.update_military(user_id, {"soldiers": soldiers_stolen})
        
        embed = create_embed(
            "📢 Propaganda Campaign Success!",
            f"**{civ['name']}** has swayed enemy soldiers to defect!",
            guilded.Color.purple()
        )
        
        embed.add_field(
            name="Defectors",
            value=f"⚔️ {format_number(soldiers_stolen)} soldiers joined your cause!",
            inline=True
        )
        
        embed.add_field(
            name="Target",
            value=f"**{target_civ['name']}** lost {format_number(soldiers_stolen)} soldiers",
            inline=True
        )
        
        await ctx.send(embed=embed)
        
        # Notify target
        try:
            target_user = await self.bot.fetch_user(int(target_id))
            await target_user.send(f"📢 **Propaganda Attack!** {civ['name']} has convinced {soldiers_stolen} of your soldiers to defect!")
        except:
            pass

    @commands.command(name='hiremercs')
    @check_cooldown_decorator(minutes=10)
    async def hire_mercenaries(self, ctx):
        """Use Mercenary Contract to instantly hire professional soldiers"""
        user_id = str(ctx.author.id)
        
        if not self._has_hyperitem(user_id, "Mercenary Contract"):
            await ctx.send("❌ You need a **Mercenary Contract** HyperItem to use this command!")
            return
            
        civ = self.civ_manager.get_civilization(user_id)
        
        # Consume Mercenary Contract
        self.civ_manager.use_hyper_item(user_id, "Mercenary Contract")
        
        # Hire mercenaries
        mercenaries_hired = random.randint(50, 150)
        spies_hired = random.randint(5, 15)
        
        self.civ_manager.update_military(user_id, {
            "soldiers": mercenaries_hired,
            "spies": spies_hired
        })
        
        embed = create_embed(
            "⚔️ Mercenaries Hired!",
            f"**{civ['name']}** has recruited professional military units!",
            guilded.Color.orange()
        )
        
        embed.add_field(
            name="Forces Recruited",
            value=f"⚔️ {format_number(mercenaries_hired)} Elite Soldiers\n🕵️ {format_number(spies_hired)} Professional Spies",
            inline=False
        )
        
        embed.add_field(name="Contract", value="Mercenary Contract consumed - these forces are permanently yours!", inline=False)
        
        await ctx.send(embed=embed)

    @commands.command(name='boosttech')
    @check_cooldown_decorator(minutes=5)
    async def boost_technology(self, ctx):
        """Use Ancient Scroll to instantly advance technology"""
        user_id = str(ctx.author.id)
        
        if not self._has_hyperitem(user_id, "Ancient Scroll"):
            await ctx.send("❌ You need an **Ancient Scroll** HyperItem to use this command!")
            return
            
        civ = self.civ_manager.get_civilization(user_id)
        
        # Consume Ancient Scroll
        self.civ_manager.use_hyper_item(user_id, "Ancient Scroll")
        
        # Advance technology
        tech_advance = random.randint(2, 4)
        self.civ_manager.update_military(user_id, {"tech_level": tech_advance})
        
        embed = create_embed(
            "📜 Ancient Knowledge Unlocked!",
            f"**{civ['name']}** has unlocked the secrets of an Ancient Scroll!",
            guilded.Color.gold()
        )
        
        embed.add_field(
            name="Technology Advancement",
            value=f"🔬 Tech Level increased by {tech_advance}!",
            inline=False
        )
        
        embed.add_field(
            name="Benefits",
            value="• Improved military effectiveness\n• Better resource extraction\n• Advanced capabilities unlocked",
            inline=False
        )
        
        await ctx.send(embed=embed)

    @commands.command(name='mintgold')
    @check_cooldown_decorator(minutes=10)
    async def mint_gold(self, ctx):
        """Use Gold Mint to generate large amounts of gold"""
        user_id = str(ctx.author.id)
        
        if not self._has_hyperitem(user_id, "Gold Mint"):
            await ctx.send("❌ You need a **Gold Mint** HyperItem to use this command!")
            return
            
        civ = self.civ_manager.get_civilization(user_id)
        
        # Consume Gold Mint
        self.civ_manager.use_hyper_item(user_id, "Gold Mint")
        
        # Generate massive gold
        base_gold = random.randint(2000, 5000)
        population_bonus = civ['population']['citizens'] * 2
        total_gold = base_gold + population_bonus
        
        self.civ_manager.update_resources(user_id, {"gold": total_gold})
        
        embed = create_embed(
            "🪙 Gold Mint Activated!",
            f"**{civ['name']}** has struck it rich with their Gold Mint!",
            guilded.Color.gold()
        )
        
        embed.add_field(
            name="Gold Generated",
            value=f"🪙 {format_number(total_gold)} Gold",
            inline=False
        )
        
        embed.add_field(name="Source", value="Ancient Gold Mint technology produces wealth from thin air!", inline=False)
        
        await ctx.send(embed=embed)

    @commands.command(name='superharvest')
    @check_cooldown_decorator(minutes=10)
    async def super_harvest(self, ctx):
        """Use Harvest Engine for massive food production"""
        user_id = str(ctx.author.id)
        
        if not self._has_hyperitem(user_id, "Harvest Engine"):
            await ctx.send("❌ You need a **Harvest Engine** HyperItem to use this command!")
            return
            
        civ = self.civ_manager.get_civilization(user_id)
        
        # Consume Harvest Engine
        self.civ_manager.use_hyper_item(user_id, "Harvest Engine")
        
        # Generate massive food
        base_food = random.randint(3000, 7000)
        territory_bonus = civ['territory']['land_size'] * 2
        total_food = base_food + territory_bonus
        
        self.civ_manager.update_resources(user_id, {"food": total_food})
        
        # Happiness bonus from food abundance
        self.civ_manager.update_population(user_id, {"happiness": 15, "hunger": -50})
        
        embed = create_embed(
            "🌾 Super Harvest Complete!",
            f"**{civ['name']}**'s Harvest Engine has produced an incredible bounty!",
            guilded.Color.green()
        )
        
        embed.add_field(
            name="Food Produced",
            value=f"🌾 {format_number(total_food)} Food",
            inline=True
        )
        
        embed.add_field(
            name="Population Effects",
            value="📈 +15 Happiness\n🍽️ Hunger eliminated",
            inline=True
        )
        
        await ctx.send(embed=embed)

    @commands.command(name='superspy')
    @check_cooldown_decorator(minutes=10)
    async def super_spy_mission(self, ctx, target: str = None):
        """Use Spy Network for elite espionage mission"""
        if not target:
            await ctx.send("🕵️ **Elite Spy Mission**\nUsage: `.superspy @user`\nRequires: Spy Network HyperItem\nHigh-success elite espionage operation")
            return
            
        user_id = str(ctx.author.id)
        
        if not self._has_hyperitem(user_id, "Spy Network"):
            await ctx.send("❌ You need a **Spy Network** HyperItem to use this command!")
            return
            
        # Parse target (same logic as other commands)
        if target.startswith('<@') and target.endswith('>'):
            target_id = target[2:-1]
            if target_id.startswith('!'):
                target_id = target_id[1:]
        else:
            await ctx.send("❌ Please mention a valid user to spy on!")
            return
            
        target_civ = self.civ_manager.get_civilization(target_id)
        if not target_civ:
            await ctx.send("❌ Target user doesn't have a civilization!")
            return
            
        civ = self.civ_manager.get_civilization(user_id)
        
        # Consume Spy Network
        self.civ_manager.use_hyper_item(user_id, "Spy Network")
        
        # Elite spy mission with 90% success rate
        if random.random() < 0.9:
            # Multi-effect spy mission
            effects = []
            
            # Steal intelligence (tech)
            if random.random() < 0.7:
                tech_stolen = 1
                self.civ_manager.update_military(user_id, {"tech_level": tech_stolen})
                self.civ_manager.update_military(target_id, {"tech_level": -tech_stolen})
                effects.append(f"🔬 Stole {tech_stolen} tech level")
                
            # Steal resources
            stolen_gold = int(target_civ['resources']['gold'] * random.uniform(0.1, 0.25))
            if stolen_gold > 0:
                self.civ_manager.update_resources(user_id, {"gold": stolen_gold})
                self.civ_manager.update_resources(target_id, {"gold": -stolen_gold})
                effects.append(f"🪙 Stole {format_number(stolen_gold)} gold")
                
            # Sabotage military
            if random.random() < 0.5:
                soldiers_sabotaged = int(target_civ['military']['soldiers'] * random.uniform(0.05, 0.15))
                self.civ_manager.update_military(target_id, {"soldiers": -soldiers_sabotaged})
                effects.append(f"⚔️ Sabotaged {format_number(soldiers_sabotaged)} enemy soldiers")
                
            embed = create_embed(
                "🕵️ Elite Spy Mission Success!",
                f"**{civ['name']}**'s elite operatives have infiltrated **{target_civ['name']}**!",
                guilded.Color.dark_blue()
            )
            
            embed.add_field(name="Mission Results", value="\n".join(effects), inline=False)
            embed.add_field(name="Network Status", value="Spy Network consumed - mission complete", inline=False)
            
            await ctx.send(embed=embed)
            
        else:
            # Rare failure
            embed = create_embed(
                "🕵️ Mission Compromised!",
                f"Elite spy mission against **{target_civ['name']}** was detected!",
                guilded.Color.red()
            )
            embed.add_field(name="Result", value="Spy Network consumed but no intelligence gathered", inline=False)
            
            await ctx.send(embed=embed)

    @commands.command(name='megainvent')
    @check_cooldown_decorator(minutes=5)  # 5 hour cooldown
    async def mega_invention(self, ctx):
        """Use Tech Core to advance multiple technology levels"""
        user_id = str(ctx.author.id)
        
        if not self._has_hyperitem(user_id, "Tech Core"):
            await ctx.send("❌ You need a **Tech Core** HyperItem to use this command!")
            return
            
        civ = self.civ_manager.get_civilization(user_id)
        
        # Consume Tech Core
        self.civ_manager.use_hyper_item(user_id, "Tech Core")
        
        # Massive tech advancement
        tech_levels = random.randint(5, 10)
        self.civ_manager.update_military(user_id, {"tech_level": tech_levels})
        
        embed = create_embed(
            "🔬 TECHNOLOGICAL BREAKTHROUGH!",
            f"**{civ['name']}** has achieved a revolutionary technological advancement!",
            guilded.Color.purple()
        )
        
        embed.add_field(
            name="Advancement",
            value=f"🚀 Tech Level increased by {tech_levels}!",
            inline=False
        )
        
        embed.add_field(
            name="Breakthroughs Unlocked",
            value="• Advanced weapons systems\n• Superior resource extraction\n• Enhanced military capabilities\n• Improved efficiency across all sectors",
            inline=False
        )
        
        await ctx.send(embed=embed)

    @commands.command(name='backstab')
    @check_cooldown_decorator(minutes=180)
    async def assassination_attempt(self, ctx, target: str = None):
        """Use Dagger for assassination attempt"""
        if not target:
            await ctx.send("🗡️ **Assassination Attempt**\nUsage: `.backstab @user`\nRequires: Dagger HyperItem\nRisky but potentially devastating attack")
            return
            
        user_id = str(ctx.author.id)
        
        if not self._has_hyperitem(user_id, "Dagger"):
            await ctx.send("❌ You need a **Dagger** HyperItem to use this command!")
            return
            
        # Parse target
        if target.startswith('<@') and target.endswith('>'):
            target_id = target[2:-1]
            if target_id.startswith('!'):
                target_id = target_id[1:]
        else:
            await ctx.send("❌ Please mention a valid user to target!")
            return
            
        target_civ = self.civ_manager.get_civilization(target_id)
        if not target_civ:
            await ctx.send("❌ Target user doesn't have a civilization!")
            return
            
        civ = self.civ_manager.get_civilization(user_id)
        
        # Consume Dagger
        self.civ_manager.use_hyper_item(user_id, "Dagger")
        
        # 60% success rate for assassination
        if random.random() < 0.6:
            # Successful assassination - major damage
            leadership_crisis = {
                "happiness": -30,
                "citizens": -int(target_civ['population']['citizens'] * 0.1)
            }
            
            military_chaos = {
                "soldiers": -int(target_civ['military']['soldiers'] * 0.2),
                "spies": -int(target_civ['military']['spies'] * 0.3)
            }
            
            self.civ_manager.update_population(target_id, leadership_crisis)
            self.civ_manager.update_military(target_id, military_chaos)
            
            embed = create_embed(
                "🗡️ Assassination Successful!",
                f"**{civ['name']}**'s assassin has eliminated key leaders in **{target_civ['name']}**!",
                guilded.Color.dark_red()
            )
            
            embed.add_field(
                name="Chaos Ensues",
                value="• Leadership crisis causes massive unrest\n• Military command structure disrupted\n• Population flees in panic",
                inline=False
            )
            
            await ctx.send(embed=embed)
            
        else:
            # Failed assassination - diplomatic consequences
            self.civ_manager.update_population(user_id, {"happiness": -15})
            
            embed = create_embed(
                "🗡️ Assassination Failed!",
                f"The assassination attempt against **{target_civ['name']}** was thwarted!",
                guilded.Color.red()
            )
            
            embed.add_field(name="Consequences", value="Failed assassination attempt has caused international outrage! (-15 happiness)", inline=False)
            
            await ctx.send(embed=embed)
            
            # Notify target of attempt
            try:
                target_user = await self.bot.fetch_user(int(target_id))
                await target_user.send(f"🗡️ **Assassination Attempt!** {civ['name']} tried to assassinate your leaders but failed!")
            except:
                pass

    @commands.command(name='bomb')
    @check_cooldown_decorator(minutes=1)
    async def missile_strike(self, ctx, target: str = None):
        """Use Missiles for mid-tier military strike"""
        if not target:
            await ctx.send("🚀 **Missile Strike**\nUsage: `.bomb @user`\nRequires: Missiles HyperItem\nPowerful military attack between conventional and nuclear")
            return
            
        user_id = str(ctx.author.id)
        
        if not self._has_hyperitem(user_id, "Missiles"):
            await ctx.send("❌ You need **Missiles** HyperItem to use this command!")
            return
            
        # Parse target (same logic)
        if target.startswith('<@') and target.endswith('>'):
            target_id = target[2:-1]
            if target_id.startswith('!'):
                target_id = target_id[1:]
        else:
            await ctx.send("❌ Please mention a valid user to bomb!")
            return
            
        target_civ = self.civ_manager.get_civilization(target_id)
        if not target_civ:
            await ctx.send("❌ Target user doesn't have a civilization!")
            return
            
        civ = self.civ_manager.get_civilization(user_id)
        
        # Consume Missiles
        self.civ_manager.use_hyper_item(user_id, "Missiles")
        
        # Moderate but significant damage
        population_loss = int(target_civ['population']['citizens'] * random.uniform(0.1, 0.25))
        military_loss = int(target_civ['military']['soldiers'] * random.uniform(0.2, 0.4))
        resource_damage = {
            "gold": int(target_civ['resources']['gold'] * random.uniform(0.1, 0.2)),
            "wood": int(target_civ['resources']['wood'] * random.uniform(0.15, 0.3)),
            "stone": int(target_civ['resources']['stone'] * random.uniform(0.15, 0.3))
        }
        
        # Apply damage
        self.civ_manager.update_population(target_id, {
            "citizens": -population_loss,
            "happiness": -20
        })
        
        self.civ_manager.update_military(target_id, {"soldiers": -military_loss})
        
        negative_resources = {res: -amt for res, amt in resource_damage.items()}
        self.civ_manager.update_resources(target_id, negative_resources)
        
        embed = create_embed(
            "🚀 Missile Strike Successful!",
            f"**{civ['name']}** has launched a devastating missile attack on **{target_civ['name']}**!",
            guilded.Color.orange()
        )
        
        damage_text = f"💀 {format_number(population_loss)} citizens\n⚔️ {format_number(military_loss)} soldiers"
        embed.add_field(name="Casualties", value=damage_text, inline=True)
        
        destruction_text = "\n".join([f"{'🪙' if res == 'gold' else '🪨' if res == 'stone' else '🪵'} {format_number(amt)} {res.capitalize()}" 
                                     for res, amt in resource_damage.items() if amt > 0])
        embed.add_field(name="Infrastructure Destroyed", value=destruction_text, inline=True)
        
        await ctx.send(embed=embed)
        
        # Notify target
        try:
            target_user = await self.bot.fetch_user(int(target_id))
            await target_user.send(f"🚀 **Missile Attack!** Your civilization has been bombed by {civ['name']}!")
        except:
            pass
