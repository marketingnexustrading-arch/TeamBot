import discord
from discord.ext import commands
from discord import app_commands
import json
import asyncio

# ============================================
# Konfiguration laden
# ============================================
import os
from dotenv import load_dotenv

# .env Datei laden (falls vorhanden)
load_dotenv()

# Token aus Umgebungsvariable oder config.json
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = os.getenv('GUILD_ID')
TEAM_SIZE = os.getenv('TEAM_SIZE', '25')

# Fallback auf config.json wenn .env nicht existiert
if not TOKEN or not GUILD_ID:
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        TOKEN = TOKEN or config['TOKEN']
        GUILD_ID = int(GUILD_ID) if GUILD_ID else config['GUILD_ID']
        TEAM_SIZE = int(TEAM_SIZE) if TEAM_SIZE else config.get('TEAM_SIZE', 25)
    except FileNotFoundError:
        print("❌ Fehler: Weder .env noch config.json gefunden!")
        print("📝 Erstelle eine .env Datei mit DISCORD_TOKEN und GUILD_ID")
        exit(1)
else:
    GUILD_ID = int(GUILD_ID)
    TEAM_SIZE = int(TEAM_SIZE)

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
teams = {}  # Format: {team_number: {'members': [user_ids], 'role': role_obj, 'text': channel, 'voice': channel}}
teams_category = None

# ============================================
# Join Team Button View
# ============================================
class JoinTeamView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # Button bleibt dauerhaft aktiv
    
    @discord.ui.button(label="Join Team", style=discord.ButtonStyle.primary, emoji="🎮", custom_id="join_team_button")
    async def join_team_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Wird ausgeführt, wenn jemand auf 'Join Team' klickt"""
        user = interaction.user
        guild = interaction.guild
        
        # Prüfen ob User bereits in einem Team ist
        for team_num, team_data in teams.items():
            if user.id in team_data['members']:
                await interaction.response.send_message(
                    f"❌ Du bist bereits in **Team {team_num}**!",
                    ephemeral=True
                )
                return
        
        # Freies Team suchen oder neues erstellen
        assigned_team = None
        
        # Suche nach Team mit freien Plätzen
        for team_num in sorted(teams.keys()):
            if len(teams[team_num]['members']) < TEAM_SIZE:
                assigned_team = team_num
                break
        
        # Wenn kein freies Team gefunden, neues erstellen
        if assigned_team is None:
            assigned_team = len(teams) + 1
            await create_team(guild, assigned_team)
        
        # User zum Team hinzufügen
        teams[assigned_team]['members'].append(user.id)
        member_role = teams[assigned_team]['role']
        
        # Rolle zuweisen
        await user.add_roles(member_role)
        
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

# ============================================
# Team-Erstellung
# ============================================
async def create_team(guild: discord.Guild, team_number: int):
    """Erstellt ein neues Team mit Rollen und Kanälen"""
    global teams_category
    
    print(f"📦 Erstelle Team {team_number}...")
    
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
    
    # Berechtigungen für Team-Kanäle
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        member_role: discord.PermissionOverwrite(read_messages=True, send_messages=True, connect=True, speak=True),
        coach_role: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True, connect=True, speak=True)
    }
    
    # Text-Kanal erstellen (unter Teams-Kategorie)
    text_channel = await guild.create_text_channel(
        name=f"team-{team_number}-chat",
        category=teams_category,
        overwrites=overwrites,
        position=team_number  # Sortierung: Team 1, 2, 3...
    )
    
    # Voice-Kanal erstellen (direkt nach Text-Channel)
    voice_channel = await guild.create_voice_channel(
        name=f"Team {team_number} Voice",
        category=teams_category,
        overwrites=overwrites,
        position=team_number + 100  # Voice-Channels unter Text-Channels
    )
    
    # Team-Daten speichern
    teams[team_number] = {
        'members': [],
        'role': member_role,
        'coach_role': coach_role,
        'text': text_channel,
        'voice': voice_channel
    }
    
    # Willkommensnachricht im Team-Channel
    await text_channel.send(
        f"🎮 **Willkommen bei Team {team_number}!**\n\n"
        f"Dies ist euer privater Team-Chat. Nur Mitglieder mit der Rolle {member_role.mention} können diesen Kanal sehen.\n\n"
        f"📊 Kapazität: **0/{TEAM_SIZE}** Mitglieder"
    )
    
    print(f"✅ Team {team_number} erfolgreich erstellt!")

# ============================================
# Setup Command
# ============================================
@tree.command(name="setup_ticket", description="Erstellt das Ticket-System für Team-Beitritte", guild=discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(administrator=True)
async def setup_ticket(interaction: discord.Interaction):
    """Erstellt die grundlegende Struktur: Teams-Kategorie und Ticket-Message"""
    global teams_category
    
    await interaction.response.defer(ephemeral=True)
    
    guild = interaction.guild
    
    # Prüfen ob Teams-Kategorie bereits existiert
    for category in guild.categories:
        if category.name == "Teams":
            teams_category = category
            break
    
    # Teams-Kategorie erstellen (falls nicht vorhanden)
    if not teams_category:
        teams_category = await guild.create_category("Teams")
    
    # Aktuellen Channel verwenden (wo der Command ausgeführt wurde)
    ticket_channel = interaction.channel
    
    # Embed für Ticket-Message
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
    
    # Message mit Button senden
    view = JoinTeamView()
    await ticket_channel.send(embed=embed, view=view)
    
    await interaction.followup.send(
        f"✅ Ticket-System wurde in diesem Channel erstellt!\n"
        f"📁 Teams-Kategorie: {teams_category.mention if teams_category else 'Erstellt'}",
        ephemeral=True
    )

# ============================================
# Bot Events
# ============================================
@bot.event
async def on_ready():
    """Wird ausgeführt, wenn der Bot bereit ist"""
    print(f'✅ Bot ist eingeloggt als {bot.user}')
    print(f'📡 Verbunden mit {len(bot.guilds)} Server(n)')
    
    # Slash Commands synchronisieren
    try:
        synced = await tree.sync(guild=discord.Object(id=GUILD_ID))
        print(f'✅ {len(synced)} Slash Command(s) synchronisiert')
    except Exception as e:
        print(f'❌ Fehler beim Synchronisieren: {e}')
    
    # View persistent machen (damit Button nach Neustart funktioniert)
    bot.add_view(JoinTeamView())
    
    print('🚀 Bot ist bereit!')

# ============================================
# Bot starten
# ============================================
if __name__ == "__main__":
    print("🤖 Starte Discord Team Join Bot...")
    bot.run(TOKEN)