import random
import asyncio
import guilded
from guilded.ext import commands
from datetime import datetime, timedelta
import logging
from bot.utils import format_number, check_cooldown_decorator, create_embed

logger = logging.getLogger(__name__)

class EconomyCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.civ_manager = bot.civ_manager

    @commands.command(name='gather')
    @check_cooldown_decorator(minutes=1)
    async def gather_resources(self, ctx):
        """Gather random resources from your territory"""
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return
            
        # Random resource generation
        possible_resources = ['gold', 'wood', 'stone', 'food']
        gathered = {}
        
        for resource in possible_resources:
            if random.random() < 0.7:  # 70% chance for each resource
                base_amount = random.randint(10, 50)
                # Apply territory modifier
                territory_modifier = civ['territory']['land_size'] / 1000
                amount = int(base_amount * territory_modifier)
                gathered[resource] = amount
        
        if not gathered:
            await ctx.send("🔍 Your scouts searched but found nothing of value this time.")
            return
            
        # Apply luck modifier
        luck_modifier = self.civ_manager.calculate_total_modifier(user_id, "luck")
        if luck_modifier > 1.0:
            for resource in gathered:
                gathered[resource] = int(gathered[resource] * luck_modifier)
        
        # Update resources
        self.civ_manager.update_resources(user_id, gathered)
        
        # Create result embed
        embed = create_embed(
            "🔍 Resource Gathering",
            f"Your scouts return with valuable resources!",
            guilded.Color.green()
        )
        
        resource_icons = {"gold": "🪙", "wood": "🪵", "stone": "🪨", "food": "🌾"}
        resource_text = "\n".join([f"{resource_icons[res]} {format_number(amt)} {res.capitalize()}" 
                                  for res, amt in gathered.items()])
        embed.add_field(name="Resources Gathered", value=resource_text, inline=False)
        
        await ctx.send(embed=embed)

    @commands.command(name='farm')
    @check_cooldown_decorator(minutes=1)
    async def farm_food(self, ctx):
        """Farm food for your civilization"""
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return
            
        # Calculate food production
        base_food = random.randint(20, 80)
        citizen_bonus = civ['population']['citizens'] // 10
        territory_bonus = civ['territory']['land_size'] // 500
        
        total_food = base_food + citizen_bonus + territory_bonus
        
        # Apply ideology modifier
        if civ.get('ideology') == 'communism':
            total_food = int(total_food * 1.1)  # Communism bonus
            
        # Random events
        event_text = ""
        if random.random() < 0.1:  # 10% chance
            event_multiplier = random.choice([0.5, 1.5, 2.0])
            total_food = int(total_food * event_multiplier)
            
            if event_multiplier < 1:
                event_text = "🦗 Locust swarm damaged some crops!"
            else:
                event_text = "🌈 Perfect weather blessed your harvest!"
        
        self.civ_manager.update_resources(user_id, {"food": total_food})
        
        embed = create_embed(
            "🌾 Farming",
            f"Your farmers worked the fields and produced {format_number(total_food)} food!",
            guilded.Color.green()
        )
        
        if event_text:
            embed.add_field(name="Special Event", value=event_text, inline=False)
            
        await ctx.send(embed=embed)

    @commands.command(name='mine')
    @check_cooldown_decorator(minutes=1)
    async def mine_resources(self, ctx):
        """Mine stone and wood from your territory"""
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return
            
        # Mining yields
        stone_yield = random.randint(15, 60)
        wood_yield = random.randint(10, 40)
        
        # Tech level bonus
        tech_bonus = 1 + (civ['military']['tech_level'] * 0.1)
        stone_yield = int(stone_yield * tech_bonus)
        wood_yield = int(wood_yield * tech_bonus)
        
        # Small chance for bonus gold
        bonus_gold = 0
        if random.random() < 0.2:  # 20% chance
            bonus_gold = random.randint(5, 25)
            
        updates = {"stone": stone_yield, "wood": wood_yield}
        if bonus_gold > 0:
            updates["gold"] = bonus_gold
            
        self.civ_manager.update_resources(user_id, updates)
        
        embed = create_embed(
            "⛏️ Mining Operation",
            "Your miners have extracted resources from the earth!",
            guilded.Color.blue()
        )
        
        result_text = f"🪨 {format_number(stone_yield)} Stone\n🪵 {format_number(wood_yield)} Wood"
        if bonus_gold > 0:
            result_text += f"\n🪙 {format_number(bonus_gold)} Gold (Lucky find!)"
            
        embed.add_field(name="Resources Extracted", value=result_text, inline=False)
        
        await ctx.send(embed=embed)

    @commands.command(name='harvest')
    @check_cooldown_decorator(minutes=10)
    async def harvest_food(self, ctx):
        """Large harvest with longer cooldown"""
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return
            
        # Large food production
        base_harvest = random.randint(100, 200)
        population_bonus = civ['population']['citizens'] // 5
        happiness_bonus = civ['population']['happiness'] // 2
        
        total_harvest = base_harvest + population_bonus + happiness_bonus
        
        # Apply ideology bonuses
        if civ.get('ideology') == 'theocracy':
            total_harvest = int(total_harvest * 1.1)  # Divine blessing
            
        self.civ_manager.update_resources(user_id, {"food": total_harvest})
        
        # Happiness increase from successful harvest
        self.civ_manager.update_population(user_id, {"happiness": 3})
        
        embed = create_embed(
            "🌽 Great Harvest",
            f"A bountiful harvest brings {format_number(total_harvest)} food to your civilization!",
            guilded.Color.gold()
        )
        embed.add_field(name="Morale Boost", value="Citizens are happy! (+3 happiness)", inline=False)
        
        await ctx.send(embed=embed)

    @commands.command(name='drill')
    @check_cooldown_decorator(minutes=5)
    async def drill_minerals(self, ctx):
        """Extract rare minerals with advanced drilling"""
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return
            
        # Requires higher tech level
        if civ['military']['tech_level'] < 2:
            await ctx.send("❌ You need Tech Level 2 or higher to use advanced drilling equipment!")
            return
            
        # High-value resource extraction
        rare_minerals = random.randint(50, 150)
        gold_value = rare_minerals * 2  # Convert to gold
        
        # Chance for extra bonus
        bonus_text = ""
        if random.random() < 0.15:  # 15% chance
            bonus_gold = random.randint(100, 300)
            gold_value += bonus_gold
            bonus_text = f"💎 Struck a rich vein! (+{format_number(bonus_gold)} gold)"
        
        self.civ_manager.update_resources(user_id, {"gold": gold_value, "stone": rare_minerals // 2})
        
        embed = create_embed(
            "🏗️ Deep Drilling",
            f"Advanced drilling equipment extracted valuable minerals worth {format_number(gold_value)} gold!",
            guilded.Color.purple()
        )
        
        if bonus_text:
            embed.add_field(name="Lucky Strike!", value=bonus_text, inline=False)
            
        await ctx.send(embed=embed)

    @commands.command(name='fish')
    @check_cooldown_decorator(minutes=2)
    async def fish_resources(self, ctx):
        """Fish for food or occasionally find treasure"""
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return
            
        # Fishing results
        if random.random() < 0.8:  # 80% chance for food
            food_caught = random.randint(15, 45)
            self.civ_manager.update_resources(user_id, {"food": food_caught})
            
            embed = create_embed(
                "🎣 Fishing",
                f"Your fishermen caught {format_number(food_caught)} food from the waters!",
                guilded.Color.teal()
            )
        else:  # 20% chance for treasure
            treasure_gold = random.randint(20, 100)
            self.civ_manager.update_resources(user_id, {"gold": treasure_gold})
            
            embed = create_embed(
                "🎣 Fishing - Lucky Find!",
                f"Your nets pulled up a treasure chest worth {format_number(treasure_gold)} gold!",
                guilded.Color.gold()
            )
            
        await ctx.send(embed=embed)

    @commands.command(name='tax')
    @check_cooldown_decorator(minutes=2)  # 1 hour cooldown
    async def collect_taxes(self, ctx):
        """Collect taxes from your citizens"""
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return
            
        population = civ['population']
        
        # Base tax calculation
        base_tax = population['citizens'] * 2
        happiness_modifier = population['happiness'] / 100  # Happy citizens pay more
        territory_modifier = civ['territory']['land_size'] / 1000
        
        total_tax = int(base_tax * happiness_modifier * territory_modifier)
        
        # Ideology effects
        ideology = civ.get('ideology', '')
        if ideology == 'democracy':
            total_tax = int(total_tax * 1.1)  # Democratic bonus
        elif ideology == 'fascism':
            total_tax = int(total_tax * 1.2)  # Forced taxation
            self.civ_manager.update_population(user_id, {"happiness": -5})
        elif ideology == 'communism':
            total_tax = int(total_tax * 0.8)  # Lower individual taxes
            
        self.civ_manager.update_resources(user_id, {"gold": total_tax})
        
        # Slight happiness decrease from taxation
        self.civ_manager.update_population(user_id, {"happiness": -2})
        
        embed = create_embed(
            "💰 Tax Collection",
            f"Collected {format_number(total_tax)} gold in taxes from your citizens.",
            guilded.Color.gold()
        )
        
        if ideology == 'fascism':
            embed.add_field(name="Regime Effect", value="Forced taxation decreased happiness by 5!", inline=False)
            
        await ctx.send(embed=embed)

    @commands.command(name='lottery')
    @check_cooldown_decorator(minutes=1)
    async def play_lottery(self, ctx, bet: int = None):
        """Gamble gold for a chance at the jackpot"""
        if bet is None:
            await ctx.send("💸 **Lottery** - Risk it all for glory!\nUsage: `.lottery <gold_amount>`\nMinimum bet: 50 gold")
            return
            
        if bet < 50:
            await ctx.send("❌ Minimum lottery bet is 50 gold!")
            return
            
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return
            
        if not self.civ_manager.can_afford(user_id, {"gold": bet}):
            await ctx.send(f"❌ You don't have {format_number(bet)} gold to bet!")
            return
            
        # Spend the bet
        self.civ_manager.spend_resources(user_id, {"gold": bet})
        
        # Lottery chances
        roll = random.random()
        
        if roll < 0.01:  # 1% - Massive jackpot
            winnings = bet * 50
            result = f"🎰 **MEGA JACKPOT!** You won {format_number(winnings)} gold!"
            color = guilded.Color.gold()
        elif roll < 0.05:  # 4% - Big win
            winnings = bet * 10
            result = f"🎰 **Big Win!** You won {format_number(winnings)} gold!"
            color = guilded.Color.green()
        elif roll < 0.20:  # 15% - Small win
            winnings = bet * 2
            result = f"🎰 **Winner!** You won {format_number(winnings)} gold!"
            color = guilded.Color.green()
        elif roll < 0.40:  # 20% - Break even
            winnings = bet
            result = f"🎰 **Break Even** - You got your {format_number(bet)} gold back."
            color = guilded.Color.blue()
        else:  # 60% - Loss
            winnings = 0
            result = f"🎰 **No Luck** - Better luck next time!"
            color = guilded.Color.red()
            
        if winnings > 0:
            self.civ_manager.update_resources(user_id, {"gold": winnings})
            
        embed = create_embed("🎰 Lottery Results", result, color)
        embed.add_field(name="Bet Amount", value=f"{format_number(bet)} gold", inline=True)
        if winnings > 0:
            embed.add_field(name="Winnings", value=f"{format_number(winnings)} gold", inline=True)
            
        await ctx.send(embed=embed)

    @commands.command(name='invest')
    @check_cooldown_decorator(minutes=3)  # 2 hour cooldown
    async def invest_gold(self, ctx, amount: int = None):
        """Invest gold for delayed profit"""
        if amount is None:
            await ctx.send("💼 **Investment Banking**\nUsage: `.invest <gold_amount>`\nReturns profit after 2 hours with 80% success rate.")
            return
            
        if amount < 100:
            await ctx.send("❌ Minimum investment is 100 gold!")
            return
            
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return
            
        if not self.civ_manager.can_afford(user_id, {"gold": amount}):
            await ctx.send(f"❌ You don't have {format_number(amount)} gold to invest!")
            return
            
        # Spend the investment
        self.civ_manager.spend_resources(user_id, {"gold": amount})
        
        embed = create_embed(
            "💼 Investment Made",
            f"Invested {format_number(amount)} gold in the market.\nCheck back in 2 hours to see your returns!",
            guilded.Color.blue()
        )
        
        await ctx.send(embed=embed)
        
        # Schedule the return after 2 hours
        async def investment_return():
            await asyncio.sleep(60)  # 2 hours in seconds
            
            # 80% chance of profit
            if random.random() < 0.8:
                profit_multiplier = random.uniform(1.2, 1.8)  # 20-80% profit
                returns = int(amount * profit_multiplier)
                
                self.civ_manager.update_resources(user_id, {"gold": returns})
                
                try:
                    user = await self.bot.fetch_user(int(user_id))
                    await user.send(f"💰 **Investment Return**: Your investment of {format_number(amount)} gold has returned {format_number(returns)} gold! (Profit: {format_number(returns - amount)})")
                except:
                    pass  # User might have DMs disabled
            else:
                # 20% chance of loss
                loss_multiplier = random.uniform(0.3, 0.7)  # Return 30-70% of investment
                returns = int(amount * loss_multiplier)
                
                self.civ_manager.update_resources(user_id, {"gold": returns})
                
                try:
                    user = await self.bot.fetch_user(int(user_id))
                    await user.send(f"📉 **Investment Loss**: Market crash! Your investment of {format_number(amount)} gold only returned {format_number(returns)} gold. (Loss: {format_number(amount - returns)})")
                except:
                    pass
        
        # Start the investment return task
        asyncio.create_task(investment_return())

    @commands.command(name='raidcaravan')
    @check_cooldown_decorator(minutes=45)
    async def raid_caravan(self, ctx):
        """Raid NPC merchant caravans for loot"""
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return
            
        military = civ['military']
        
        # Need soldiers for raiding
        if military['soldiers'] < 5:
            await ctx.send("❌ You need at least 5 soldiers to raid caravans!")
            return
            
        # Success chance based on military strength
        base_success = 0.6
        soldier_bonus = min(0.3, military['soldiers'] / 100)  # Max 30% bonus
        spy_bonus = min(0.1, military['spies'] / 50)  # Max 10% bonus
        
        success_chance = base_success + soldier_bonus + spy_bonus
        
        # Apply ideology modifier
        if civ.get('ideology') == 'anarchy':
            success_chance += 0.1  # Anarchy bonus for raiding
            
        if random.random() < success_chance:
            # Successful raid
            loot = {
                "gold": random.randint(100, 400),
                "food": random.randint(50, 150),
                "wood": random.randint(20, 80),
                "stone": random.randint(15, 60)
            }
            
            # Small chance for special loot
            if random.random() < 0.1:
                bonus_gold = random.randint(200, 500)
                loot["gold"] += bonus_gold
                
            self.civ_manager.update_resources(user_id, loot)
            
            embed = create_embed(
                "🏴‍☠️ Caravan Raid - Success!",
                "Your raiders ambushed a wealthy merchant caravan!",
                guilded.Color.green()
            )
            
            loot_text = "\n".join([f"{'🪙' if res == 'gold' else '🌾' if res == 'food' else '🪵' if res == 'wood' else '🪨'} {format_number(amt)} {res.capitalize()}" 
                                  for res, amt in loot.items() if amt > 0])
            embed.add_field(name="Loot Acquired", value=loot_text, inline=False)
            
        else:
            # Failed raid - lose some soldiers
            soldier_loss = random.randint(1, 3)
            self.civ_manager.update_military(user_id, {"soldiers": -soldier_loss})
            
            embed = create_embed(
                "🏴‍☠️ Caravan Raid - Failed!",
                f"The caravan's guards were too strong! You lost {soldier_loss} soldiers in the failed attack.",
                guilded.Color.red()
            )
            
        await ctx.send(embed=embed)
