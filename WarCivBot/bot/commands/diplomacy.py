import random
import guilded
from guilded.ext import commands
import json
import logging
from bot.utils import format_number, check_cooldown_decorator, create_embed

logger = logging.getLogger(__name__)

class DiplomacyCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.civ_manager = bot.civ_manager

    @commands.command(name='ally')
    @check_cooldown_decorator(minutes=30)
    async def create_alliance(self, ctx, target: str = None, alliance_name: str = None):
        """Create an alliance with another civilization"""
        if not target or not alliance_name:
            await ctx.send("🤝 **Alliance Creation**\nUsage: `.ally @user <alliance_name>`\nCreate a mutual defense pact with another civilization.")
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
            await ctx.send("❌ Please mention a valid user to ally with!")
            return
            
        if target_id == user_id:
            await ctx.send("❌ You cannot ally with yourself!")
            return
            
        target_civ = self.civ_manager.get_civilization(target_id)
        if not target_civ:
            await ctx.send("❌ Target user doesn't have a civilization!")
            return
            
        # Check if already at war
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COUNT(*) FROM wars 
            WHERE ((attacker_id = ? AND defender_id = ?) OR (attacker_id = ? AND defender_id = ?)) 
            AND result = 'ongoing'
        ''', (user_id, target_id, target_id, user_id))
        
        if cursor.fetchone()[0] > 0:
            await ctx.send("❌ You cannot ally with a civilization you are at war with!")
            return
            
        # Check if alliance already exists
        cursor.execute('''
            SELECT * FROM alliances 
            WHERE (leader_id = ? OR leader_id = ?) 
            AND (members LIKE '%' || ? || '%' OR members LIKE '%' || ? || '%')
        ''', (user_id, target_id, user_id, target_id))
        
        existing = cursor.fetchone()
        if existing:
            await ctx.send("❌ One of you is already in an alliance!")
            return
            
        # Create alliance proposal (simplified - in real implementation, would require target acceptance)
        success_chance = 0.7  # Base 70% acceptance rate
        
        # Apply diplomacy modifiers
        diplomacy_modifier = self.civ_manager.calculate_total_modifier(user_id, "diplomacy_success")
        success_chance *= diplomacy_modifier
        
        # Ideology compatibility
        if civ.get('ideology') == target_civ.get('ideology'):
            success_chance += 0.2  # Same ideology bonus
        elif civ.get('ideology') == 'fascism' and target_civ.get('ideology') == 'democracy':
            success_chance -= 0.3  # Ideological enemies
        elif civ.get('ideology') == 'democracy' and target_civ.get('ideology') == 'fascism':
            success_chance -= 0.3
            
        if random.random() < success_chance:
            # Alliance accepted
            try:
                cursor.execute('''
                    INSERT INTO alliances (name, leader_id, members)
                    VALUES (?, ?, ?)
                ''', (alliance_name, user_id, json.dumps([user_id, target_id])))
                
                conn.commit()
                
                embed = create_embed(
                    "🤝 Alliance Formed!",
                    f"**{alliance_name}** has been established between **{civ['name']}** and **{target_civ['name']}**!",
                    guilded.Color.green()
                )
                
                embed.add_field(
                    name="Alliance Benefits",
                    value="• Mutual defense pact\n• Resource sharing available\n• Coordinated military actions\n• Trade bonuses",
                    inline=False
                )
                
                await ctx.send(embed=embed)
                
                # Notify target
                try:
                    target_user = await self.bot.fetch_user(int(target_id))
                    await target_user.send(f"🤝 **Alliance Formed!** Your civilization has joined the **{alliance_name}** alliance with {civ['name']}!")
                except:
                    pass
                    
                # Log events
                self.db.log_event(user_id, "alliance", "Alliance Formed", f"Created alliance '{alliance_name}' with {target_civ['name']}")
                self.db.log_event(target_id, "alliance", "Alliance Formed", f"Joined alliance '{alliance_name}' with {civ['name']}")
                
            except Exception as e:
                logger.error(f"Error creating alliance: {e}")
                await ctx.send("❌ Failed to create alliance. Please try again.")
        else:
            # Alliance rejected
            embed = create_embed(
                "🤝 Alliance Rejected",
                f"**{target_civ['name']}** has declined your alliance proposal.",
                guilded.Color.red()
            )
            
            # Diplomatic consequence
            self.civ_manager.update_population(user_id, {"happiness": -5})
            embed.add_field(name="Consequence", value="Your people are disappointed by the diplomatic failure. (-5 happiness)", inline=False)
            
            await ctx.send(embed=embed)

    @commands.command(name='break')
    @check_cooldown_decorator(minutes=60)
    async def break_alliance(self, ctx):
        """Break your current alliance"""
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return
            
        # Find user's alliance
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM alliances 
            WHERE members LIKE '%' || ? || '%'
        ''', (user_id,))
        
        alliance = cursor.fetchone()
        if not alliance:
            await ctx.send("❌ You are not currently in an alliance!")
            return
            
        alliance_dict = dict(alliance)
        members = json.loads(alliance_dict['members'])
        
        if len(members) <= 2:
            # Dissolve the alliance if only 2 members
            cursor.execute('DELETE FROM alliances WHERE id = ?', (alliance_dict['id'],))
        else:
            # Remove user from alliance
            members.remove(user_id)
            cursor.execute('UPDATE alliances SET members = ? WHERE id = ?', (json.dumps(members), alliance_dict['id']))
            
        conn.commit()
        
        # Happiness penalty for breaking alliance
        self.civ_manager.update_population(user_id, {"happiness": -10})
        
        embed = create_embed(
            "💔 Alliance Broken",
            f"Your civilization has left the **{alliance_dict['name']}** alliance.",
            guilded.Color.red()
        )
        embed.add_field(name="Consequence", value="Breaking diplomatic ties has upset your people. (-10 happiness)", inline=False)
        
        await ctx.send(embed=embed)
        
        # Notify other alliance members
        for member_id in members:
            if member_id != user_id:
                try:
                    member_user = await self.bot.fetch_user(int(member_id))
                    await member_user.send(f"💔 **Alliance Update**: {civ['name']} has left the **{alliance_dict['name']}** alliance.")
                except:
                    pass
                    
        self.db.log_event(user_id, "alliance_break", "Alliance Broken", f"Left the {alliance_dict['name']} alliance")

    @commands.command(name='send')
    @check_cooldown_decorator(minutes=10)
    async def send_resources(self, ctx, target: str = None, resource_type: str = None, amount: int = None):
        """Send resources to an ally"""
        if not target or not resource_type or amount is None:
            await ctx.send("📦 **Resource Transfer**\nUsage: `.send @user <resource> <amount>`\nResources: gold, food, wood, stone")
            return
            
        if resource_type not in ['gold', 'food', 'wood', 'stone']:
            await ctx.send("❌ Invalid resource type! Choose from: gold, food, wood, stone")
            return
            
        if amount < 1:
            await ctx.send("❌ Amount must be positive!")
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
            await ctx.send("❌ Please mention a valid user to send resources to!")
            return
            
        target_civ = self.civ_manager.get_civilization(target_id)
        if not target_civ:
            await ctx.send("❌ Target user doesn't have a civilization!")
            return
            
        # Check if can afford
        if not self.civ_manager.can_afford(user_id, {resource_type: amount}):
            await ctx.send(f"❌ You don't have {format_number(amount)} {resource_type}!")
            return
            
        # Check if allied (optional - could allow sending to anyone)
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COUNT(*) FROM alliances 
            WHERE members LIKE '%' || ? || '%' AND members LIKE '%' || ? || '%'
        ''', (user_id, target_id))
        
        is_allied = cursor.fetchone()[0] > 0
        
        # Calculate transfer efficiency
        transfer_efficiency = 0.9  # 90% efficiency (10% lost in transport)
        if is_allied:
            transfer_efficiency = 0.95  # 95% efficiency for allies
            
        received_amount = int(amount * transfer_efficiency)
        
        # Process transfer
        self.civ_manager.spend_resources(user_id, {resource_type: amount})
        self.civ_manager.update_resources(target_id, {resource_type: received_amount})
        
        # Create success embed
        resource_icons = {"gold": "🪙", "food": "🌾", "wood": "🪵", "stone": "🪨"}
        
        embed = create_embed(
            "📦 Resources Sent",
            f"Successfully sent resources to **{target_civ['name']}**!",
            guilded.Color.blue()
        )
        
        embed.add_field(
            name="Transfer Details",
            value=f"{resource_icons[resource_type]} Sent: {format_number(amount)} {resource_type.capitalize()}\n{resource_icons[resource_type]} Received: {format_number(received_amount)} {resource_type.capitalize()}\n📊 Efficiency: {int(transfer_efficiency * 100)}%",
            inline=False
        )
        
        if is_allied:
            embed.add_field(name="Alliance Bonus", value="Higher transfer efficiency due to alliance!", inline=False)
            
        await ctx.send(embed=embed)
        
        # Notify recipient
        try:
            target_user = await self.bot.fetch_user(int(target_id))
            await target_user.send(f"📦 **Resources Received!** {civ['name']} has sent you {format_number(received_amount)} {resource_type}!")
        except:
            pass
            
        # Log the transfer
        self.db.log_event(user_id, "resource_transfer", "Resources Sent", f"Sent {amount} {resource_type} to {target_civ['name']}")
        self.db.log_event(target_id, "resource_transfer", "Resources Received", f"Received {received_amount} {resource_type} from {civ['name']}")

    @commands.command(name='trade')
    @check_cooldown_decorator(minutes=20)
    async def trade_resources(self, ctx, target: str = None, offer_resource: str = None, offer_amount: int = None, 
                            request_resource: str = None, request_amount: int = None):
        """Propose a resource trade with another civilization"""
        if not all([target, offer_resource, offer_amount, request_resource, request_amount]):
            await ctx.send("💰 **Resource Trading**\nUsage: `.trade @user <offer_resource> <offer_amount> <request_resource> <request_amount>`\nExample: `.trade @user gold 100 food 200`")
            return
            
        valid_resources = ['gold', 'food', 'wood', 'stone']
        if offer_resource not in valid_resources or request_resource not in valid_resources:
            await ctx.send(f"❌ Invalid resource! Choose from: {', '.join(valid_resources)}")
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
            await ctx.send("❌ Please mention a valid user to trade with!")
            return
            
        target_civ = self.civ_manager.get_civilization(target_id)
        if not target_civ:
            await ctx.send("❌ Target user doesn't have a civilization!")
            return
            
        # Check if can afford the offer
        if not self.civ_manager.can_afford(user_id, {offer_resource: offer_amount}):
            await ctx.send(f"❌ You don't have {format_number(offer_amount)} {offer_resource} to offer!")
            return
            
        # Check if target can afford what's requested
        if not self.civ_manager.can_afford(target_id, {request_resource: request_amount}):
            await ctx.send(f"❌ Target doesn't have {format_number(request_amount)} {request_resource}!")
            return
            
        # Calculate trade fairness and acceptance chance
        resource_values = {"gold": 1.0, "food": 0.5, "wood": 0.8, "stone": 0.9}
        
        offer_value = offer_amount * resource_values[offer_resource]
        request_value = request_amount * resource_values[request_resource]
        
        fairness_ratio = offer_value / request_value if request_value > 0 else 0
        
        # Base acceptance chance based on fairness
        if fairness_ratio >= 1.2:
            acceptance_chance = 0.9  # Very favorable to target
        elif fairness_ratio >= 1.0:
            acceptance_chance = 0.7  # Fair trade
        elif fairness_ratio >= 0.8:
            acceptance_chance = 0.5  # Slightly unfavorable
        else:
            acceptance_chance = 0.2  # Very unfavorable
            
        # Apply diplomacy modifier
        diplomacy_modifier = self.civ_manager.calculate_total_modifier(user_id, "diplomacy_success")
        acceptance_chance *= diplomacy_modifier
        
        # Apply ideology modifier
        if civ.get('ideology') == 'democracy':
            acceptance_chance += 0.1  # Democracy bonus to trade
            
        if random.random() < acceptance_chance:
            # Trade accepted
            self.civ_manager.spend_resources(user_id, {offer_resource: offer_amount})
            self.civ_manager.update_resources(user_id, {request_resource: request_amount})
            
            self.civ_manager.spend_resources(target_id, {request_resource: request_amount})
            self.civ_manager.update_resources(target_id, {offer_resource: offer_amount})
            
            resource_icons = {"gold": "🪙", "food": "🌾", "wood": "🪵", "stone": "🪨"}
            
            embed = create_embed(
                "💰 Trade Successful!",
                f"Trade completed between **{civ['name']}** and **{target_civ['name']}**!",
                guilded.Color.green()
            )
            
            embed.add_field(
                name="Your Side",
                value=f"Gave: {resource_icons[offer_resource]} {format_number(offer_amount)} {offer_resource.capitalize()}\nReceived: {resource_icons[request_resource]} {format_number(request_amount)} {request_resource.capitalize()}",
                inline=True
            )
            
            embed.add_field(
                name="Their Side",
                value=f"Gave: {resource_icons[request_resource]} {format_number(request_amount)} {request_resource.capitalize()}\nReceived: {resource_icons[offer_resource]} {format_number(offer_amount)} {offer_resource.capitalize()}",
                inline=True
            )
            
            # Happiness bonus for successful trade
            self.civ_manager.update_population(user_id, {"happiness": 3})
            self.civ_manager.update_population(target_id, {"happiness": 3})
            
            await ctx.send(embed=embed)
            
            # Notify target
            try:
                target_user = await self.bot.fetch_user(int(target_id))
                await target_user.send(f"💰 **Trade Completed!** Successfully traded with {civ['name']}!")
            except:
                pass
                
        else:
            # Trade rejected
            embed = create_embed(
                "💰 Trade Rejected",
                f"**{target_civ['name']}** has declined your trade offer.",
                guilded.Color.red()
            )
            
            fairness_text = "Fair" if 0.9 <= fairness_ratio <= 1.1 else "Unfavorable" if fairness_ratio < 0.9 else "Very Favorable"
            embed.add_field(name="Trade Analysis", value=f"Fairness: {fairness_text}\nAcceptance Chance: {int(acceptance_chance * 100)}%", inline=False)
            
            await ctx.send(embed=embed)

    @commands.command(name='mail')
    @check_cooldown_decorator(minutes=5)
    async def send_diplomatic_message(self, ctx, target: str = None, *, message: str = None):
        """Send a diplomatic message to another civilization"""
        if not target or not message:
            await ctx.send("📜 **Diplomatic Mail**\nUsage: `.mail @user <message>`\nSend diplomatic communications to other civilizations.")
            return
            
        if len(message) > 500:
            await ctx.send("❌ Message too long! Maximum 500 characters.")
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
            await ctx.send("❌ Please mention a valid user to send mail to!")
            return
            
        target_civ = self.civ_manager.get_civilization(target_id)
        if not target_civ:
            await ctx.send("❌ Target user doesn't have a civilization!")
            return
            
        # Send the diplomatic message
        try:
            target_user = await self.bot.fetch_user(int(target_id))
            
            embed = create_embed(
                "📜 Diplomatic Message",
                f"**From**: {civ['name']} (led by {ctx.author.name})\n**To**: {target_civ['name']}",
                guilded.Color.blue()
            )
            embed.add_field(name="Message", value=message, inline=False)
            embed.add_field(name="Reply", value="Use `.mail @user <message>` to respond", inline=False)
            
            await target_user.send(embed=embed)
            
            await ctx.send(f"📜 **Diplomatic message sent to {target_civ['name']}!**")
            
            # Log the diplomatic message
            self.db.log_event(user_id, "diplomacy", "Message Sent", f"Sent diplomatic message to {target_civ['name']}")
            
        except Exception as e:
            logger.error(f"Error sending diplomatic message: {e}")
            await ctx.send("❌ Failed to send diplomatic message. The recipient might have DMs disabled.")

    @commands.command(name='coalition')
    @check_cooldown_decorator(minutes=120)
    async def form_coalition(self, ctx, target_alliance: str = None):
        """Form a coalition against another alliance"""
        if not target_alliance:
            await ctx.send("⚔️ **Coalition Warfare**\nUsage: `.coalition <target_alliance_name>`\nForm a coalition to declare war on another alliance.")
            return
            
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return
            
        # Find user's alliance
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM alliances 
            WHERE members LIKE '%' || ? || '%'
        ''', (user_id,))
        
        user_alliance = cursor.fetchone()
        if not user_alliance:
            await ctx.send("❌ You must be in an alliance to form a coalition!")
            return
            
        # Find target alliance
        cursor.execute('SELECT * FROM alliances WHERE name = ?', (target_alliance,))
        target_alliance_data = cursor.fetchone()
        
        if not target_alliance_data:
            await ctx.send(f"❌ Alliance '{target_alliance}' not found!")
            return
            
        if user_alliance['name'] == target_alliance:
            await ctx.send("❌ You cannot form a coalition against your own alliance!")
            return
            
        user_alliance_dict = dict(user_alliance)
        target_alliance_dict = dict(target_alliance_data)
        
        # Calculate coalition success chance
        user_members = json.loads(user_alliance_dict['members'])
        target_members = json.loads(target_alliance_dict['members'])
        
        # Coalition is more likely to succeed if user's alliance is larger or stronger
        success_chance = min(0.8, len(user_members) / max(1, len(target_members)))
        
        if random.random() < success_chance:
            # Coalition formed successfully
            embed = create_embed(
                "⚔️ Coalition Formed!",
                f"**{user_alliance_dict['name']}** has formed a coalition against **{target_alliance}**!",
                guilded.Color.red()
            )
            
            embed.add_field(
                name="Coalition Effects",
                value="• All members can attack target alliance\n• Reduced diplomatic penalties\n• Coordinated military bonuses",
                inline=False
            )
            
            # Notify all members of both alliances
            all_affected = user_members + target_members
            for member_id in all_affected:
                if member_id != user_id:
                    try:
                        member_user = await self.bot.fetch_user(int(member_id))
                        if member_id in user_members:
                            await member_user.send(f"⚔️ **Coalition Formed!** Your alliance has formed a coalition against {target_alliance}!")
                        else:
                            await member_user.send(f"⚔️ **Coalition Against You!** {user_alliance_dict['name']} has formed a coalition against your alliance!")
                    except:
                        pass
                        
            await ctx.send(embed=embed)
            
        else:
            embed = create_embed(
                "⚔️ Coalition Failed",
                f"Your attempt to form a coalition against **{target_alliance}** has failed.",
                guilded.Color.red()
            )
            embed.add_field(name="Consequence", value="Failed diplomacy has consequences. (-10 happiness)", inline=False)
            
            # Penalty for failed coalition
            self.civ_manager.update_population(user_id, {"happiness": -10})
            
            await ctx.send(embed=embed)
