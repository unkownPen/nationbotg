import random
import guilded
from guilded.ext import commands
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class DiplomacyCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.civ_manager = bot.civ_manager
        self.pending_trades = {}  # Temp storage for pending trades {trade_id: details}
        self.pending_alliances = {}  # Temp storage for pending alliances {alliance_id: details}

    @commands.command(name='ally')
    async def propose_alliance(self, ctx, target: str = None, alliance_name: str = None):
        """Propose an alliance with another civilization"""
        if not target or not alliance_name:
            await ctx.send("🤝 **Alliance Proposal**\nUsage: `.ally @user <alliance_name>`\nPropose a mutual defense pact with another civilization.")
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
            
        # Generate unique alliance ID
        alliance_id = str(random.randint(100000, 999999))
        
        # Store pending alliance
        self.pending_alliances[alliance_id] = {
            "proposer_id": user_id,
            "target_id": target_id,
            "alliance_name": alliance_name,
            "expires": datetime.now() + timedelta(minutes=30)  # Expires in 30 min
        }
        
        # Send proposal in channel with ping
        embed = create_embed(
            "🤝 Alliance Proposal Received!",
            f"From **{civ['name']}** (led by {ctx.author.name})",
            guilded.Color.blue()
        )
        
        embed.add_field(
            name="Proposed Alliance",
            value=f"Alliance Name: **{alliance_name}**\nBenefits: Mutual defense, resource sharing, coordinated actions",
            inline=False
        )
        
        embed.add_field(
            name="How to Respond",
            value=f"Use `.acceptally {alliance_id}` to accept\nOr `.rejectally {alliance_id}` to reject\nProposal expires in 30 minutes.",
            inline=False
        )
        
        await ctx.send(f"<@{target_id}>", embed=embed)
        
        await ctx.send(f"🤝 **Alliance Proposed!** Your proposal for **{alliance_name}** has been sent to **{target_civ['name']}**.")
        
        # Log proposal
        self.db.log_event(user_id, "alliance_proposal", "Alliance Proposed", f"Proposed alliance '{alliance_name}' to {target_civ['name']}")

    @commands.command(name='acceptally')
    async def accept_alliance(self, ctx, alliance_id: str):
        """Accept a pending alliance proposal"""
        user_id = str(ctx.author.id)
        
        if alliance_id not in self.pending_alliances:
            await ctx.send("❌ Invalid or expired alliance ID!")
            return
            
        proposal = self.pending_alliances[alliance_id]
        
        if user_id != proposal["target_id"]:
            await ctx.send("❌ This alliance proposal isn't for you!")
            return
            
        if datetime.now() > proposal["expires"]:
            await ctx.send("❌ This alliance proposal has expired!")
            del self.pending_alliances[alliance_id]
            return
            
        # Create the alliance
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO alliances (name, leader_id, members)
                VALUES (?, ?, ?)
            ''', (proposal["alliance_name"], proposal["proposer_id"], json.dumps([proposal["proposer_id"], proposal["target_id"]])))
            
            conn.commit()
            
            embed = create_embed(
                "🤝 Alliance Formed!",
                f"**{proposal['alliance_name']}** has been established!",
                guilded.Color.green()
            )
            
            embed.add_field(
                name="Alliance Benefits",
                value="• Mutual defense pact\n• Resource sharing available\n• Coordinated military actions\n• Trade bonuses",
                inline=False
            )
            
            await ctx.send(embed=embed)
            
            # Notify proposer in channel
            await ctx.send(f"<@{proposal['proposer_id']}> 🤝 **Alliance Accepted!** Your proposal for **{proposal['alliance_name']}** has been accepted!")
            
            # Log events
            self.db.log_event(proposal["proposer_id"], "alliance", "Alliance Formed", f"Created alliance '{proposal['alliance_name']}'")
            self.db.log_event(user_id, "alliance", "Alliance Formed", f"Joined alliance '{proposal['alliance_name']}'")
            
            del self.pending_alliances[alliance_id]
            
        except Exception as e:
            logger.error(f"Error creating alliance: {e}")
            await ctx.send("❌ Failed to form alliance. Please try again.")

    @commands.command(name='rejectally')
    async def reject_alliance(self, ctx, alliance_id: str):
        """Reject a pending alliance proposal"""
        user_id = str(ctx.author.id)
        
        if alliance_id not in self.pending_alliances:
            await ctx.send("❌ Invalid or expired alliance ID!")
            return
            
        proposal = self.pending_alliances[alliance_id]
        
        if user_id != proposal["target_id"]:
            await ctx.send("❌ This alliance proposal isn't for you!")
            return
            
        # Notify proposer in channel
        await ctx.send(f"<@{proposal['proposer_id']}> 🤝 **Alliance Rejected!** Your proposal for **{proposal['alliance_name']}** has been rejected.")
        
        await ctx.send("🤝 **Alliance Rejected!** You've declined the proposal.")
        
        # Log
        self.db.log_event(user_id, "alliance_reject", "Alliance Rejected", f"Rejected alliance {alliance_id}")
        self.db.log_event(proposal["proposer_id"], "alliance_reject", "Alliance Rejected", f"Alliance {alliance_id} rejected by target")
        
        del self.pending_alliances[alliance_id]

    @commands.command(name='break')
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
        
        # Notify other alliance members in channel
        for member_id in members:
            if member_id != user_id:
                await ctx.send(f"<@{member_id}> 💔 **Alliance Update**: {civ['name']} has left the **{alliance_dict['name']}** alliance.")
                
        self.db.log_event(user_id, "alliance_break", "Alliance Broken", f"Left the {alliance_dict['name']} alliance")

    @commands.command(name='send')
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
        
        # Notify recipient in channel
        await ctx.send(f"<@{target_id}> 📦 **Resources Received!** {civ['name']} has sent you {format_number(received_amount)} {resource_type}!")
        
        # Log the transfer
        self.db.log_event(user_id, "resource_transfer", "Resources Sent", f"Sent {amount} {resource_type} to {target_civ['name']}")
        self.db.log_event(target_id, "resource_transfer", "Resources Received", f"Received {received_amount} {resource_type} from {civ['name']}")

    @commands.command(name='trade')
    async def propose_trade(self, ctx, target: str = None, offer_resource: str = None, offer_amount: int = None, 
                            request_resource: str = None, request_amount: int = None):
        """Propose a resource trade with another civilization (requires acceptance)"""
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
            
        # Generate unique trade ID
        trade_id = str(random.randint(100000, 999999))
        
        # Store pending trade
        self.pending_trades[trade_id] = {
            "proposer_id": user_id,
            "target_id": target_id,
            "offer_resource": offer_resource,
            "offer_amount": offer_amount,
            "request_resource": request_resource,
            "request_amount": request_amount,
            "expires": datetime.now() + timedelta(minutes=30)  # Expires in 30 min
        }
        
        # Send proposal in channel with ping
        resource_icons = {"gold": "🪙", "food": "🌾", "wood": "🪵", "stone": "🪨"}
        
        embed = create_embed(
            "💰 Trade Proposal Received!",
            f"From **{civ['name']}** (led by {ctx.author.name})",
            guilded.Color.blue()
        )
        
        embed.add_field(
            name="Proposed Trade",
            value=f"They offer: {resource_icons[offer_resource]} {format_number(offer_amount)} {offer_resource.capitalize()}\nThey request: {resource_icons[request_resource]} {format_number(request_amount)} {request_resource.capitalize()}",
            inline=False
        )
        
        embed.add_field(
            name="How to Respond",
            value=f"Use `.accepttrade {trade_id}` to accept\nOr `.rejecttrade {trade_id}` to reject\nProposal expires in 30 minutes.",
            inline=False
        )
        
        # Add trade GIF
        trade_gif = '<iframe src="https://giphy.com/embed/5RNNQvq3fhYlOYDIQ2" width="480" height="288" style="" frameBorder="0" class="giphy-embed" allowFullScreen></iframe><p><a href="https://giphy.com/gifs/cat-crypto-typing-5RNNQvq3fhYlOYDIQ2">via GIPHY</a></p>'
        
        await ctx.send(f"<@{target_id}>\n{trade_gif}", embed=embed)
        
        await ctx.send(f"💰 **Trade Proposed!** Your offer has been sent to **{target_civ['name']}**.")
        
        # Log proposal
        self.db.log_event(user_id, "trade_proposal", "Trade Proposed", f"Proposed trade to {target_civ['name']}: {offer_amount} {offer_resource} for {request_amount} {request_resource}")

    @commands.command(name='accepttrade')
    async def accept_trade(self, ctx, trade_id: str):
        """Accept a pending trade proposal"""
        user_id = str(ctx.author.id)
        
        if trade_id not in self.pending_trades:
            await ctx.send("❌ Invalid or expired trade ID!")
            return
            
        trade = self.pending_trades[trade_id]
        
        if user_id != trade["target_id"]:
            await ctx.send("❌ This trade proposal isn't for you!")
            return
            
        if datetime.now() > trade["expires"]:
            await ctx.send("❌ This trade proposal has expired!")
            del self.pending_trades[trade_id]
            return
            
        # Check if both can still afford
        if not self.civ_manager.can_afford(trade["proposer_id"], {trade["offer_resource"]: trade["offer_amount"]}):
            await ctx.send("❌ The proposer no longer has the offered resources!")
            del self.pending_trades[trade_id]
            return
            
        if not self.civ_manager.can_afford(user_id, {trade["request_resource"]: trade["request_amount"]}):
            await ctx.send("❌ You no longer have the requested resources!")
            del self.pending_trades[trade_id]
            return
            
        # Execute trade
        self.civ_manager.spend_resources(trade["proposer_id"], {trade["offer_resource"]: trade["offer_amount"]})
        self.civ_manager.update_resources(trade["proposer_id"], {trade["request_resource"]: trade["request_amount"]})
        
        self.civ_manager.spend_resources(user_id, {trade["request_resource"]: trade["request_amount"]})
        self.civ_manager.update_resources(user_id, {trade["offer_resource"]: trade["offer_amount"]})
        
        # Notify proposer in channel
        await ctx.send(f"<@{trade['proposer_id']}> 💰 **Trade Accepted!** Your trade proposal has been accepted!")
        
        await ctx.send("💰 **Trade Accepted!** The exchange has been completed.")
        
        # Log
        self.db.log_event(user_id, "trade_accept", "Trade Accepted", f"Accepted trade {trade_id}")
        self.db.log_event(trade["proposer_id"], "trade_accept", "Trade Accepted", f"Trade {trade_id} accepted by target")
        
        del self.pending_trades[trade_id]

    @commands.command(name='rejecttrade')
    async def reject_trade(self, ctx, trade_id: str):
        """Reject a pending trade proposal"""
        user_id = str(ctx.author.id)
        
        if trade_id not in self.pending_trades:
            await ctx.send("❌ Invalid or expired trade ID!")
            return
            
        trade = self.pending_trades[trade_id]
        
        if user_id != trade["target_id"]:
            await ctx.send("❌ This trade proposal isn't for you!")
            return
            
        # Notify proposer in channel
        await ctx.send(f"<@{trade['proposer_id']}> 💰 **Trade Rejected!** Your trade proposal has been rejected.")
        
        await ctx.send("💰 **Trade Rejected!** You've declined the proposal.")
        
        # Log
        self.db.log_event(user_id, "trade_reject", "Trade Rejected", f"Rejected trade {trade_id}")
        self.db.log_event(trade["proposer_id"], "trade_reject", "Trade Rejected", f"Trade {trade_id} rejected by target")
        
        del self.pending_trades[trade_id]

    @commands.command(name='mail')
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
            
        # Store the message in the database
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO messages (sender_id, recipient_id, message)
            VALUES (?, ?, ?)
        ''', (user_id, target_id, message))
        conn.commit()
        
        # Send the diplomatic message in channel with GIF
        mail_gif = '<iframe src="https://giphy.com/embed/f0tufxEr372ZLuA07V" width="480" height="365" style="" frameBorder="0" class="giphy-embed" allowFullScreen></iframe><p><a href="https://giphy.com/gifs/email-aol-youve-got-mail-f0tufxEr372ZLuA07V">via GIPHY</a></p>'
        
        embed = create_embed(
            "📜 Diplomatic Message",
            f"**From**: {civ['name']} (led by {ctx.author.name})\n**To**: {target_civ['name']}",
            guilded.Color.blue()
        )
        embed.add_field(name="Message", value=message, inline=False)
        embed.add_field(name="Reply", value="Use `.mail @user <message>` to respond", inline=False)
        
        await ctx.send(f"<@{target_id}>\n{mail_gif}", embed=embed)
        
        await ctx.send("📜 **Sent diplomatic message**")
        
        # Log
        self.db.log_event(user_id, "diplomatic_message", "Message Sent", f"Sent message to {target_civ['name']}")

    @commands.command(name='inbox')
    async def check_inbox(self, ctx):
        """Check your pending alliance, trade proposals, and diplomatic messages"""
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return
            
        embed = create_embed(
            "📬 Inbox",
            f"Pending proposals and messages for **{civ['name']}**",
            guilded.Color.blue()
        )
        
        # Check pending alliances
        alliance_proposals = []
        for alliance_id, proposal in self.pending_alliances.items():
            if proposal["target_id"] == user_id and datetime.now() < proposal["expires"]:
                proposer_civ = self.civ_manager.get_civilization(proposal["proposer_id"])
                alliance_proposals.append(
                    f"**Alliance ID**: {alliance_id}\n"
                    f"From: **{proposer_civ['name']}**\n"
                    f"Alliance Name: **{proposal['alliance_name']}**\n"
                    f"Respond with: `.acceptally {alliance_id}` or `.rejectally {alliance_id}`\n"
                    f"Expires: <t:{int(proposal['expires'].timestamp())}:R>"
                )
        
        # Check pending trades
        trade_proposals = []
        for trade_id, trade in self.pending_trades.items():
            if trade["target_id"] == user_id and datetime.now() < trade["expires"]:
                proposer_civ = self.civ_manager.get_civilization(trade["proposer_id"])
                resource_icons = {"gold": "🪙", "food": "🌾", "wood": "🪵", "stone": "🪨"}
                trade_proposals.append(
                    f"**Trade ID**: {trade_id}\n"
                    f"From: **{proposer_civ['name']}**\n"
                    f"Offers: {resource_icons[trade['offer_resource']]} {format_number(trade['offer_amount'])} {trade['offer_resource'].capitalize()}\n"
                    f"Requests: {resource_icons[trade['request_resource']]} {format_number(trade['request_amount'])} {trade['request_resource'].capitalize()}\n"
                    f"Respond with: `.accepttrade {trade_id}` or `.rejecttrade {trade_id}`\n"
                    f"Expires: <t:{int(trade['expires'].timestamp())}:R>"
                )
        
        # Check diplomatic messages
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT sender_id, message, timestamp FROM messages 
            WHERE recipient_id = ? 
            ORDER BY timestamp DESC 
            LIMIT 10
        ''', (user_id,))
        messages = cursor.fetchall()
        
        diplomatic_messages = []
        for msg in messages:
            sender_civ = self.civ_manager.get_civilization(msg['sender_id'])
            diplomatic_messages.append(
                f"**From**: {sender_civ['name']}\n"
                f"**Message**: {msg['message']}\n"
                f"**Received**: <t:{int(datetime.fromisoformat(msg['timestamp']).timestamp())}:R>"
            )
        
        # Add fields to embed
        embed.add_field(
            name="Alliance Proposals",
            value="\n\n".join(alliance_proposals) if alliance_proposals else "No pending alliance proposals.",
            inline=False
        )
        embed.add_field(
            name="Trade Proposals",
            value="\n\n".join(trade_proposals) if trade_proposals else "No pending trade proposals.",
            inline=False
        )
        embed.add_field(
            name="Diplomatic Messages",
            value="\n\n".join(diplomatic_messages) if diplomatic_messages else "No diplomatic messages received.",
            inline=False
        )
        
        await ctx.send(embed=embed)

    @commands.command(name='coalition')
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
            
            # Notify all members of both alliances in channel
            all_affected = user_members + target_members
            for member_id in all_affected:
                if member_id != user_id:
                    if member_id in user_members:
                        await ctx.send(f"<@{member_id}> ⚔️ **Coalition Formed!** Your alliance has formed a coalition against {target_alliance}!")
                    else:
                        await ctx.send(f"<@{member_id}> ⚔️ **Coalition Against You!** {user_alliance_dict['name']} has formed a coalition against your alliance!")
                        
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
            self.civ_manager.update_population(user_id, {"happiness": -10})
            
            await ctx.send(embed=embed)
