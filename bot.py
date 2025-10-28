import discord
from discord.ext import commands
from discord import app_commands
import json
import asyncio
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
# Konfiguration laden
# ============================================
load_dotenv()

# Token aus Umgebungsvariable
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = os.getenv('GUILD_ID')
TEAM_SIZE = os.getenv('TEAM_SIZE', '25')
DATA_FILE = 'teams_data.json'

# Validierung
if not TOKEN:
    logger.error("DISCORD_TOKEN nicht gesetzt!")
    exit(1)
if not GUILD_ID:
    logger.error("GUILD_ID nicht gesetzt!")
    exit(1)

try:
    GUILD_ID = int(GUILD_ID)
    TEAM_SIZE = int(TEAM_SIZE)
except ValueError as e:
    logger.error(f"Fehler beim Konvertieren der Konfiguration: {e}")
    exit(1)

logger.info(f"Konfiguration geladen: Guild ID = {GUILD_ID}, Team Size = {TEAM_SIZE}")

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
# Globale Variablen
# ============================================
teams: Dict[int, dict] = {}
teams_category: Optional[discord.CategoryChannel] = None

# ============================================
# Data Persistence
# ============================================
def save_teams_data():
    """Speichert Team-Daten in JSON (für Wiederherstellung nach Neustart)"""
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
        logger.info(f"Teams-Daten gespeichert: {len(teams)} Teams")
    except Exception as e:
        logger.error(f"Fehler beim Speichern der Teams-Daten: {e}")

async def load_teams_data(guild: discord.Guild):
    """Lädt Team-Daten aus JSON"""
    global teams, teams_category
    
    if not os.path.exists(DATA_FILE):
        logger.info("Keine gespeicherten Team-Daten gefunden")
        return
    
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Kategorie wiederherstellen
        if data.get('category_id'):
            teams_category = guild.get_channel(data['category_id'])
        
        # Teams wiederherstellen
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
                logger.info(f"Team {team_num} wiederhergestellt ({len(team_data['members'])} Mitglieder)")
            else:
                logger.warning(f"Team {team_num} konnte nicht vollständig wiederhergestellt werden")
        
        logger.info(f"Insgesamt {len(teams)} Teams wiederhergestellt")
    except Exception as e:
        logger.error(f"Fehler beim Laden der Teams-Daten: {e}")

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
        
        try:
            # Prüfen ob User bereits in einem Team ist
            for team_num, team_data in teams.items():
                if user.id in team_data['members']:
                    await interaction.response.send_message(
                        f"❌ Du bist bereits in **Team {team_num}**!",
                        ephemeral=True
                    )
                    return
            
            # Freies Team finden
            assigned_team = None
            for team_num in sorted(teams.keys()):
                if len(teams[team_num]['members']) < TEAM_SIZE:
                    assigned_team = team_num
                    break
            
            # Neues Team erstellen falls nötig
            if assigned_team is None:
                assigned_team = len(teams) + 1
                await create_team(guild, assigned_team)
            
            # User zum Team hinzufügen
            teams[assigned_team]['members'].append(user.id)
            member_role = teams[assigned_team]['role']
            await user.add_roles(member_role)
            
            # Daten speichern
            save_teams_data()
            
            await interaction.response.send_message(
                f"✅ Willkommen in **Team {assigned_team}**!\n"
                f"🎮 Du hast jetzt Zugriff auf:\n"
                f"• {teams[assigned_team]['text'].mention}\n"
                f"• {teams[assigned_team]['voice'].mention}",
                ephemeral=True
            )
            
            # Benachrichtigung im Team-Channel
            team_channel = teams[assigned_team]['text']
            await team_channel.send(
                f"🎉 {user.mention} ist **Team {assigned_team}** beigetreten! "
                f"Mitglieder: **{len(teams[assigned_team]['members'])}/{TEAM_SIZE}**"
            )
            
            logger.info(f"User {user.name} (ID: {user.id}) Team {assigned_team} beigetreten")
            
        except Exception as e:
            logger.error(f"Fehler beim Team-Beitritt: {e}")
            await interaction.response.send_message(
                "❌ Ein Fehler ist aufgetreten. Bitte versuche es später erneut.",
                ephemeral=True
            )

# ============================================
# Team-Erstellung
# ============================================
async def create_team(guild: discord.Guild, team_number: int):
    """Erstellt ein neues Team mit Rollen und Kanälen"""
    global teams_category
    
    logger.info(f"Erstelle Team {team_number}...")
    
    try:
        # Rollen erstellen
        member_role = await guild.create_role(
            name=f"Team {team_number} Member",
            color=discord.Color.blue(),
            mentionable=True
        )
        
        coach_role = await guild.create_role(
            name=f"Team {team_number} Coach",
            color=discord.Color.gold(),
            mentionable=True
        )
        
        # Berechtigungen definieren
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
        
        # Text-Channel erstellen
        text_channel = await guild.create_text_channel(
            name=f"team-{team_number}-chat",
            category=teams_category,
            overwrites=overwrites,
            position=team_number
        )
        
        # Voice-Channel erstellen
        voice_channel = await guild.create_voice_channel(
            name=f"Team {team_number} Voice",
            category=teams_category,
            overwrites=overwrites,
            position=team_number + 100
        )
        
        # Team-Dictionary aktualisieren
        teams[team_number] = {
            'members': [],
            'role': member_role,
            'coach_role': coach_role,
            'text': text_channel,
            'voice': voice_channel
        }
        
        # Willkommensnachricht
        embed = discord.Embed(
            title=f"🎮 Willkommen bei Team {team_number}!",
            description=(
                f"Dies ist euer privater Team-Chat. Nur Mitglieder mit der Rolle {member_role.mention} "
                f"können diesen Kanal sehen.\n\n"
                f"**📊 Kapazität:** 0/{TEAM_SIZE} Mitglieder\n"
                f"**🎤 Voice:** {voice_channel.mention}\n\n"
                f"Viel Erfolg!"
            ),
            color=discord.Color.blue()
        )
        await text_channel.send(embed=embed)
        
        # Daten speichern
        save_teams_data()
        
        logger.info(f"Team {team_number} erfolgreich erstellt!")
        
    except Exception as e:
        logger.error(f"Fehler beim Erstellen von Team {team_number}: {e}")
        raise

# ============================================
# Setup Command
# ============================================
@tree.command(
    name="setup_ticket",
    description="Erstellt das Ticket-System für Team-Beitritte",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_ticket(interaction: discord.Interaction):
    """Richtet das Team-Beitritts-System ein"""
    global teams_category
    
    await interaction.response.defer(ephemeral=True)
    
    guild = interaction.guild
    
    try:
        # Teams-Kategorie finden oder erstellen
        for category in guild.categories:
            if category.name == "Teams":
                teams_category = category
                break
        
        if not teams_category:
            teams_category = await guild.create_category("Teams")
            logger.info("Teams-Kategorie erstellt")
        
        ticket_channel = interaction.channel
        
        # Embed erstellen
        embed = discord.Embed(
            title="🎮 Team Beitreten",
            description=(
                "Willkommen! Klicke auf den Button unten, um automatisch einem Team beizutreten.\n\n"
                f"**📊 Team-Kapazität:** {TEAM_SIZE} Spieler pro Team\n"
                f"**🔄 Automatisch:** Wenn alle Teams voll sind, wird automatisch ein neues erstellt!\n\n"
                "**Was bekommst du?**\n"
                "✅ Zugriff auf deinen privaten Team-Chat\n"
                "✅ Zugriff auf deinen Team Voice-Channel\n"
                "✅ Team-Rolle\n"
            ),
            color=discord.Color.green()
        )
        embed.set_footer(text="Viel Spaß in deinem Team!")
        
        # Button-View erstellen und senden
        view = JoinTeamView()
        await ticket_channel.send(embed=embed, view=view)
        
        # Daten speichern
        save_teams_data()
        
        await interaction.followup.send(
            f"✅ Ticket-System wurde in diesem Channel erstellt!\n"
            f"📁 Teams-Kategorie: {teams_category.mention}",
            ephemeral=True
        )
        
        logger.info(f"Ticket-System in {ticket_channel.name} erstellt")
        
    except Exception as e:
        logger.error(f"Fehler beim Setup: {e}")
        await interaction.followup.send(
            f"❌ Fehler beim Setup: {str(e)}",
            ephemeral=True
        )

# ============================================
# Leave Team Command
# ============================================
@tree.command(
    name="leave_team",
    description="Verlässt dein aktuelles Team",
    guild=discord.Object(id=GUILD_ID)
)
async def leave_team(interaction: discord.Interaction):
    """Ermöglicht Usern, ihr Team zu verlassen"""
    user = interaction.user
    
    try:
        # Team finden
        user_team = None
        for team_num, team_data in teams.items():
            if user.id in team_data['members']:
                user_team = team_num
                break
        
        if not user_team:
            await interaction.response.send_message(
                "❌ Du bist in keinem Team!",
                ephemeral=True
            )
            return
        
        # User aus Team entfernen
        teams[user_team]['members'].remove(user.id)
        member_role = teams[user_team]['role']
        await user.remove_roles(member_role)
        
        # Daten speichern
        save_teams_data()
        
        await interaction.response.send_message(
            f"✅ Du hast **Team {user_team}** verlassen.",
            ephemeral=True
        )
        
        # Benachrichtigung im Team-Channel
        team_channel = teams[user_team]['text']
        await team_channel.send(
            f"👋 {user.mention} hat das Team verlassen. "
            f"Mitglieder: **{len(teams[user_team]['members'])}/{TEAM_SIZE}**"
        )
        
        logger.info(f"User {user.name} (ID: {user.id}) hat Team {user_team} verlassen")
        
    except Exception as e:
        logger.error(f"Fehler beim Team-Verlassen: {e}")
        await interaction.response.send_message(
            "❌ Ein Fehler ist aufgetreten. Bitte versuche es später erneut.",
            ephemeral=True
        )

# ============================================
# Team Info Command
# ============================================
@tree.command(
    name="team_info",
    description="Zeigt Informationen über alle Teams",
    guild=discord.Object(id=GUILD_ID)
)
async def team_info(interaction: discord.Interaction):
    """Zeigt eine Übersicht über alle Teams"""
    try:
        if not teams:
            await interaction.response.send_message(
                "ℹ️ Es gibt noch keine Teams.",
                ephemeral=True
            )
            return
        
        embed = discord.Embed(
            title="📊 Team-Übersicht",
            description=f"Insgesamt **{len(teams)}** Teams",
            color=discord.Color.blue()
        )
        
        for team_num in sorted(teams.keys()):
            team_data = teams[team_num]
            member_count = len(team_data['members'])
            status = "🟢 Offen" if member_count < TEAM_SIZE else "🔴 Voll"
            
            embed.add_field(
                name=f"Team {team_num} {status}",
                value=f"Mitglieder: {member_count}/{TEAM_SIZE}",
                inline=True
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    except Exception as e:
        logger.error(f"Fehler bei Team-Info: {e}")
        await interaction.response.send_message(
            "❌ Ein Fehler ist aufgetreten.",
            ephemeral=True
        )

# ============================================
# Bot Events
# ============================================
@bot.event
async def on_ready():
    """Wird ausgeführt, wenn der Bot bereit ist"""
    logger.info(f'Bot ist eingeloggt als {bot.user}')
    logger.info(f'Verbunden mit {len(bot.guilds)} Server(n)')
    
    # Commands synchronisieren
    try:
        synced = await tree.sync(guild=discord.Object(id=GUILD_ID))
        logger.info(f'{len(synced)} Slash Command(s) synchronisiert')
    except Exception as e:
        logger.error(f'Fehler beim Synchronisieren: {e}')
    
    # Persistent View registrieren
    bot.add_view(JoinTeamView())
    
    # Teams-Daten laden
    guild = bot.get_guild(GUILD_ID)
    if guild:
        await load_teams_data(guild)
    
    logger.info('Bot ist bereit!')

@bot.event
async def on_error(event, *args, **kwargs):
    """Globaler Error Handler"""
    logger.error(f"Fehler in Event {event}", exc_info=True)

# ============================================
# Graceful Shutdown
# ============================================
async def shutdown():
    """Sauberes Herunterfahren"""
    logger.info("Fahre Bot herunter...")
    save_teams_data()
    await bot.close()

# ============================================
# Bot starten
# ============================================
if __name__ == "__main__":
    try:
        logger.info("Starte Discord Team Join Bot...")
        bot.run(TOKEN)
    except KeyboardInterrupt:
        logger.info("Bot wurde durch Benutzer beendet")
    except Exception as e:
        logger.error(f"Kritischer Fehler: {e}", exc_info=True)
    finally:
        save_teams_data()