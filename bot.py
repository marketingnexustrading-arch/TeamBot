import discord
from discord.ext import commands
from discord import app_commands
import json
import asyncio

# ============================================
# Konfiguration laden
# ============================================
with open('config.json', 'r') as f:
    config = json.load(f)

TOKEN = config['TOKEN']
GUILD_ID = config['GUILD_ID']
TEAM_SIZE = config['TEAM_SIZE']

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
community_category = None
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
    
    # Text-Kanal erstellen
    text_channel = await guild.create_text_channel(
        name=f"team-{team_number}-chat",
        category=teams_category,
        overwrites=overwrites
    )
    
    # Voice-Kanal erstellen
    voice_channel = await guild.create_voice_channel(
        name=f"Team {team_number} Voice",
        category=teams_category,
        overwrites=overwrites
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
    """Erstellt die grundlegende Struktur: Kategorien, Kanäle und Ticket-Message"""
    global community_category, teams_category
    
    await interaction.response.defer(ephemeral=True)
    
    guild = interaction.guild
    
    # Community-Kategorie erstellen
    if not community_category:
        community_category = await guild.create_category("🌍 Community")
        
        # Allgemeiner Text-Channel
        await guild.create_text_channel(
            name="general",
            category=community_category
        )
        
        # Allgemeiner Voice-Channel
        await guild.create_voice_channel(
            name="General Voice",
            category=community_category
        )
    
    # Teams-Kategorie erstellen
    if not teams_category:
        teams_category = await guild.create_category("🎮 Teams")
    
    # Ticket-Channel erstellen
    ticket_channel = await guild.create_text_channel(
        name="join-team",
        category=community_category
    )
    
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
        f"✅ Ticket-System wurde in {ticket_channel.mention} erstellt!",
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