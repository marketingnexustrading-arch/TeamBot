import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from dotenv import load_dotenv
from typing import Dict, Optional
import logging

# ============================================
# Logging Setup
# ============================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('TeamBot')

# ============================================
# Load Configuration
# ============================================
load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = os.getenv('GUILD_ID')
TEAM_SIZE = os.getenv('TEAM_SIZE', '25')
DATA_FILE = 'teams_data.json'
CATEGORY_NAME = 'My Team'

if not TOKEN:
    logger.error("DISCORD_TOKEN not set!")
    exit(1)

try:
    if GUILD_ID:
        GUILD_ID = int(GUILD_ID)
    TEAM_SIZE = int(TEAM_SIZE)
except ValueError as e:
    logger.error(f"Error converting configuration: {e}")
    exit(1)

logger.info(f"Configuration loaded: Guild ID = {GUILD_ID}, Team Size = {TEAM_SIZE}")

# ============================================
# Bot Setup
# ============================================
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)
tree = bot.tree

# ============================================
# Global Variables
# ============================================
teams: Dict[int, dict] = {}
teams_category: Optional[discord.CategoryChannel] = None

# ============================================
# Helper: Get or Create Category
# ============================================
async def get_or_create_category(guild: discord.Guild) -> discord.CategoryChannel:
    """Finds or creates the My Team category - GUARANTEED not None!"""
    global teams_category
    
    logger.info(f"🔍 Searching for category '{CATEGORY_NAME}'...")
    
    # 1. Check if already stored in variable
    if teams_category and teams_category.guild.id == guild.id:
        logger.info(f"✅ Category already in variable: {teams_category.name} (ID: {teams_category.id})")
        return teams_category
    
    # 2. Search in all categories
    for category in guild.categories:
        logger.info(f"   Checking category: '{category.name}'")
        if category.name == CATEGORY_NAME:
            teams_category = category
            logger.info(f"✅ Category found: {category.name} (ID: {category.id})")
            return teams_category
    
    # 3. Not found - MUST be created
    logger.warning(f"⚠️  Category '{CATEGORY_NAME}' not found - creating new...")
    teams_category = await guild.create_category(
        name=CATEGORY_NAME,
        position=999  # At the bottom
    )
    logger.info(f"✅ Category created: {teams_category.name} (ID: {teams_category.id})")
    
    return teams_category

# ============================================
# Data Persistence
# ============================================
def save_teams_data():
    """Saves team data to JSON"""
    try:
        data = {
            'teams': {
                team_num: {
                    'members': team_data['members'],
                    'role_id': team_data['role'].id,
                    'coach_role_id': team_data['coach_role'].id,
                    'text_channel_id': team_data['text'].id,
                    'voice_channel_id': team_data['voice'].id
                }
                for team_num, team_data in teams.items()
            },
            'category_id': teams_category.id if teams_category else None
        }
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        logger.info(f"💾 Team data saved: {len(teams)} teams")
    except Exception as e:
        logger.error(f"❌ Error saving team data: {e}")

async def load_teams_data(guild: discord.Guild):
    """Loads team data from JSON"""
    global teams, teams_category
    
    if not os.path.exists(DATA_FILE):
        logger.info("ℹ️  No saved team data found")
        return
    
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if data.get('category_id'):
            teams_category = guild.get_channel(data['category_id'])
            if teams_category:
                logger.info(f"✅ Category loaded from data: {teams_category.name}")
        
        for team_num_str, team_data in data.get('teams', {}).items():
            team_num = int(team_num_str)
            
            role = guild.get_role(team_data['role_id'])
            coach_role = guild.get_role(team_data['coach_role_id'])
            text_channel = guild.get_channel(team_data['text_channel_id'])
            voice_channel = guild.get_channel(team_data['voice_channel_id'])
            
            if all([role, coach_role, text_channel, voice_channel]):
                teams[team_num] = {
                    'members': team_data['members'],
                    'role': role,
                    'coach_role': coach_role,
                    'text': text_channel,
                    'voice': voice_channel
                }
                logger.info(f"✅ Team {team_num} restored ({len(team_data['members'])} members)")
            else:
                logger.warning(f"⚠️  Team {team_num} could not be fully restored")
        
        logger.info(f"✅ Total of {len(teams)} teams restored")
    except Exception as e:
        logger.error(f"❌ Error loading team data: {e}")

# ============================================
# Join Team Button View
# ============================================
class JoinTeamView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="Join Team", style=discord.ButtonStyle.primary, emoji="🎮", custom_id="join_team_button")
    async def join_team_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        guild = interaction.guild
        
        logger.info(f"🎮 User {user.name} wants to join a team")
        
        try:
            # Check if user is already in a team
            for team_num, team_data in teams.items():
                if user.id in team_data['members']:
                    await interaction.response.send_message(
                        f"❌ You are already in **Team {team_num}**!",
                        ephemeral=True
                    )
                    return
            
            # Find free team
            assigned_team = None
            for team_num in sorted(teams.keys()):
                if len(teams[team_num]['members']) < TEAM_SIZE:
                    assigned_team = team_num
                    break
            
            # Create new team if necessary
            if assigned_team is None:
                assigned_team = len(teams) + 1
                logger.info(f"📦 Creating new Team {assigned_team}")
                await create_team(guild, assigned_team)
            
            # Add user to team
            teams[assigned_team]['members'].append(user.id)
            member_role = teams[assigned_team]['role']
            await user.add_roles(member_role)
            
            save_teams_data()
            
            await interaction.response.send_message(
                f"✅ Welcome to **Team {assigned_team}**!\n"
                f"🎮 You now have access to:\n"
                f"• {teams[assigned_team]['text'].mention}\n"
                f"• {teams[assigned_team]['voice'].mention}",
                ephemeral=True
            )
            
            team_channel = teams[assigned_team]['text']
            await team_channel.send(
                f"🎉 {user.mention} joined **Team {assigned_team}**! "
                f"Members: **{len(teams[assigned_team]['members'])}/{TEAM_SIZE}**"
            )
            
            logger.info(f"✅ User {user.name} (ID: {user.id}) joined Team {assigned_team}")
            
        except Exception as e:
            logger.error(f"❌ Error during team join: {e}", exc_info=True)
            try:
                await interaction.response.send_message(
                    "❌ An error occurred. Please try again later.",
                    ephemeral=True
                )
            except:
                pass

# ============================================
# Team Creation
# ============================================
async def create_team(guild: discord.Guild, team_number: int):
    """Creates a new team with roles and channels"""
    logger.info(f"🔨 Creating Team {team_number}...")
    
    try:
        # STEP 1: Category MUST exist!
        logger.info(f"🔨 Step 1: Get/Create category...")
        category = await get_or_create_category(guild)
        logger.info(f"✅ Category ready: {category.name} (ID: {category.id})")
        
        # STEP 2: Create roles
        logger.info(f"🔨 Step 2: Creating roles...")
        member_role = await guild.create_role(
            name=f"Team {team_number} Member",
            color=discord.Color.blue(),
            mentionable=True
        )
        logger.info(f"✅ Member role created: {member_role.name}")
        
        coach_role = await guild.create_role(
            name=f"Team {team_number} Coach",
            color=discord.Color.gold(),
            mentionable=True
        )
        logger.info(f"✅ Coach role created: {coach_role.name}")
        
        # STEP 3: Define permissions
        logger.info(f"🔨 Step 3: Defining permissions...")
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            member_role: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                connect=True,
                speak=True
            ),
            coach_role: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                manage_messages=True,
                connect=True,
                speak=True,
                mute_members=True,
                deafen_members=True
            )
        }
        
        # STEP 4: Create text channel
        logger.info(f"🔨 Step 4: Creating text channel under category '{category.name}'...")
        text_channel = await guild.create_text_channel(
            name=f"team-{team_number}-chat",
            category=category,
            overwrites=overwrites
        )
        logger.info(f"✅ Text channel created: {text_channel.name} (Category: {text_channel.category.name if text_channel.category else 'NONE!'})")
        
        # STEP 5: Create voice channel
        logger.info(f"🔨 Step 5: Creating voice channel under category '{category.name}'...")
        voice_channel = await guild.create_voice_channel(
            name=f"Team {team_number} Voice",
            category=category,
            overwrites=overwrites
        )
        logger.info(f"✅ Voice channel created: {voice_channel.name} (Category: {voice_channel.category.name if voice_channel.category else 'NONE!'})")
        
        # STEP 6: Save team
        logger.info(f"🔨 Step 6: Saving team data...")
        teams[team_number] = {
            'members': [],
            'role': member_role,
            'coach_role': coach_role,
            'text': text_channel,
            'voice': voice_channel
        }
        
        # STEP 7: Welcome message
        logger.info(f"🔨 Step 7: Sending welcome message...")
        embed = discord.Embed(
            title=f"🎮 Welcome to Team {team_number}!",
            description=(
                f"This is your private team chat. Only members with the role {member_role.mention} "
                f"can see this channel.\n\n"
                f"**📊 Capacity:** 0/{TEAM_SIZE} members\n"
                f"**🎤 Voice:** {voice_channel.mention}\n\n"
                f"Good luck!"
            ),
            color=discord.Color.blue()
        )
        await text_channel.send(embed=embed)
        
        save_teams_data()
        
        logger.info(f"✅✅✅ Team {team_number} SUCCESSFULLY created under category '{category.name}'!")
        
    except Exception as e:
        logger.error(f"❌❌❌ CRITICAL ERROR creating Team {team_number}: {e}", exc_info=True)
        raise

# ============================================
# Setup Command
# ============================================
@tree.command(
    name="setup_ticket",
    description="Creates the ticket system for team joining"
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_ticket(interaction: discord.Interaction):
    """Sets up the team joining system"""
    await interaction.response.defer(ephemeral=True)
    
    guild = interaction.guild
    
    try:
        logger.info(f"🎫 Setting up ticket system in {guild.name}")
        
        # Ensure category exists
        category = await get_or_create_category(guild)
        
        ticket_channel = interaction.channel
        
        embed = discord.Embed(
            title="🎮 Join a Team",
            description=(
                "Welcome! Click the button below to automatically join a team.\n\n"
                f"**📊 Team Capacity:** {TEAM_SIZE} players per team\n"
                f"**🔄 Automatic:** If all teams are full, a new one will be created automatically!\n\n"
                "**What you get:**\n"
                "✅ Access to your private team chat\n"
                "✅ Access to your team voice channel\n"
                "✅ Team role\n"
            ),
            color=discord.Color.green()
        )
        embed.set_footer(text="Have fun in your team!")
        
        view = JoinTeamView()
        await ticket_channel.send(embed=embed, view=view)
        
        save_teams_data()
        
        await interaction.followup.send(
            f"✅ Ticket system created in this channel!\n"
            f"📁 Category '{CATEGORY_NAME}': {category.mention}",
            ephemeral=True
        )
        
        logger.info(f"✅ Ticket system successfully set up")
        
    except Exception as e:
        logger.error(f"❌ Error during setup: {e}", exc_info=True)
        await interaction.followup.send(
            f"❌ Error during setup: {str(e)}",
            ephemeral=True
        )

# ============================================
# Leave Team Command
# ============================================
@tree.command(
    name="leave_team",
    description="Leave your current team"
)
async def leave_team(interaction: discord.Interaction):
    """Allows users to leave their team"""
    user = interaction.user
    
    try:
        user_team = None
        for team_num, team_data in teams.items():
            if user.id in team_data['members']:
                user_team = team_num
                break
        
        if not user_team:
            await interaction.response.send_message(
                "❌ You are not in any team!",
                ephemeral=True
            )
            return
        
        teams[user_team]['members'].remove(user.id)
        member_role = teams[user_team]['role']
        await user.remove_roles(member_role)
        
        save_teams_data()
        
        await interaction.response.send_message(
            f"✅ You left **Team {user_team}**.",
            ephemeral=True
        )
        
        team_channel = teams[user_team]['text']
        await team_channel.send(
            f"👋 {user.mention} left the team. "
            f"Members: **{len(teams[user_team]['members'])}/{TEAM_SIZE}**"
        )
        
        logger.info(f"✅ User {user.name} left Team {user_team}")
        
    except Exception as e:
        logger.error(f"❌ Error leaving team: {e}")
        await interaction.response.send_message(
            "❌ An error occurred.",
            ephemeral=True
        )

# ============================================
# Team Info Command
# ============================================
@tree.command(
    name="team_info",
    description="Shows information about all teams"
)
async def team_info(interaction: discord.Interaction):
    """Shows an overview of all teams"""
    try:
        if not teams:
            await interaction.response.send_message(
                "ℹ️ There are no teams yet.",
                ephemeral=True
            )
            return
        
        embed = discord.Embed(
            title="📊 Team Overview",
            description=f"Total of **{len(teams)}** teams",
            color=discord.Color.blue()
        )
        
        for team_num in sorted(teams.keys()):
            team_data = teams[team_num]
            member_count = len(team_data['members'])
            status = "🟢 Open" if member_count < TEAM_SIZE else "🔴 Full"
            
            embed.add_field(
                name=f"Team {team_num} {status}",
                value=f"Members: {member_count}/{TEAM_SIZE}",
                inline=True
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    except Exception as e:
        logger.error(f"❌ Error in team info: {e}")
        await interaction.response.send_message(
            "❌ An error occurred.",
            ephemeral=True
        )

# ============================================
# Bot Events
# ============================================
@bot.event
async def on_ready():
    """Called when the bot is ready"""
    logger.info(f'✅ Bot logged in as {bot.user}')
    logger.info(f'📡 Connected to {len(bot.guilds)} server(s)')
    
    for guild in bot.guilds:
        logger.info(f'  - {guild.name} (ID: {guild.id})')
    
    # Sync commands GLOBALLY (works for all servers)
    try:
        synced = await tree.sync()
        logger.info(f'✅ {len(synced)} slash command(s) globally synced')
        for cmd in synced:
            logger.info(f'  ✓ Command registered: /{cmd.name}')
    except Exception as e:
        logger.error(f'❌ Error syncing commands: {e}')
    
    if GUILD_ID:
        guild = bot.get_guild(GUILD_ID)
        if guild:
            await load_teams_data(guild)
        else:
            logger.warning(f"⚠️  Guild with ID {GUILD_ID} not found!")
    
    bot.add_view(JoinTeamView())
    
    logger.info('🚀 Bot is ready!')

@bot.event
async def on_error(event, *args, **kwargs):
    """Global error handler"""
    logger.error(f"❌ Error in event {event}", exc_info=True)

# ============================================
# Graceful Shutdown
# ============================================
async def shutdown():
    """Clean shutdown"""
    logger.info("👋 Shutting down bot...")
    save_teams_data()
    await bot.close()

# ============================================
# Start Bot
# ============================================
if __name__ == "__main__":
    try:
        logger.info("🤖 Starting Discord Team Join Bot...")
        bot.run(TOKEN)
    except KeyboardInterrupt:
        logger.info("⚠️  Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Critical error: {e}", exc_info=True)
    finally:
        save_teams_data()