import discord
from discord.ext import commands
from dotenv import load_dotenv
import os
import asyncio
from pathlib import Path

# ---------- Load .env file ----------
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

TOKEN = os.getenv("DISCORD_TOKEN")
VOICE_CHANNEL_ID_STR = os.getenv("VOICE_CHANNEL_ID", "950886798748442675")

if TOKEN is None or VOICE_CHANNEL_ID_STR is None:
    raise ValueError("DISCORD_TOKEN or VOICE_CHANNEL_ID not found in .env!")

VOICE_CHANNEL_ID = int(VOICE_CHANNEL_ID_STR)

# ---------- Config ----------
SOUNDS_DIR = "sounds"
SOUNDS_PER_PAGE = 4

# ---------- Intents ----------
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

voice_client: discord.VoiceClient | None = None

# ---------- Helper Functions ----------

def get_sound_file(user_id: int, action: str):
    """Get a WAV file for the user, fallback to default."""
    user_file = f"{user_id}_{action}.wav"
    if os.path.exists(os.path.join(SOUNDS_DIR, user_file)):
        return os.path.join(SOUNDS_DIR, user_file)
    return os.path.join(SOUNDS_DIR, f"default_{action}.wav")

def list_sounds():
    """Return all WAV files in the sounds directory."""
    if not os.path.exists(SOUNDS_DIR):
        return []
    return sorted(f for f in os.listdir(SOUNDS_DIR) if f.lower().endswith(".wav"))

async def play_sound(vc: discord.VoiceClient, sound_file: str):
    """Play a WAV file in the connected voice channel."""
    if not vc.is_connected():
        return
    if vc.is_playing():
        vc.stop()
    vc.play(discord.FFmpegPCMAudio(sound_file))
    while vc.is_playing():
        await asyncio.sleep(0.1)

# ---------- UI ----------

class SoundboardView(discord.ui.View):
    def __init__(self, vc: discord.VoiceClient, sounds: list[str]):
        super().__init__(timeout=None)
        self.vc = vc
        self.sounds = sounds
        self.page = 0
        self.max_pages = max(1, (len(sounds) - 1) // SOUNDS_PER_PAGE + 1)
        self.build()

    def build(self):
        self.clear_items()
        start = self.page * SOUNDS_PER_PAGE
        end = start + SOUNDS_PER_PAGE
        for sound in self.sounds[start:end]:
            label = os.path.splitext(sound)[0][:80]

            async def callback(interaction: discord.Interaction, sound=sound):
                if not self.vc or not self.vc.is_connected():
                    await interaction.response.send_message(
                        "❌ Bot is not connected to voice.",
                        ephemeral=True
                    )
                    return
                if not interaction.user.voice or interaction.user.voice.channel != self.vc.channel:
                    await interaction.response.send_message(
                        "🔊 You must be in the voice channel.",
                        ephemeral=True
                    )
                    return
                await interaction.response.defer()
                await play_sound(self.vc, os.path.join(SOUNDS_DIR, sound))

            button = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary)
            button.callback = callback
            self.add_item(button)

        # Navigation buttons
        prev_btn = discord.ui.Button(
            label="⏮",
            style=discord.ButtonStyle.primary,
            disabled=self.page == 0,
            row=1
        )
        next_btn = discord.ui.Button(
            label="⏭",
            style=discord.ButtonStyle.primary,
            disabled=self.page >= self.max_pages - 1,
            row=1
        )
        prev_btn.callback = self.prev_page
        next_btn.callback = self.next_page
        self.add_item(prev_btn)
        self.add_item(next_btn)

    async def prev_page(self, interaction: discord.Interaction):
        self.page -= 1
        self.build()
        await interaction.response.edit_message(content=self.title(), view=self)

    async def next_page(self, interaction: discord.Interaction):
        self.page += 1
        self.build()
        await interaction.response.edit_message(content=self.title(), view=self)

    def title(self):
        return f"🎵 **Sounds (Page {self.page + 1}/{self.max_pages}) – click to play:**"

# ---------- Events ----------

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

@bot.event
async def on_voice_state_update(member, before, after):
    global voice_client
    if member.bot:
        return

    guild = member.guild
    voice_channel = guild.get_channel(VOICE_CHANNEL_ID)
    if voice_channel is None:
        return

    # -------- User joins the monitored voice channel --------
    if after.channel == voice_channel and before.channel != voice_channel:
        if not voice_client or not voice_client.is_connected():
            voice_client = await voice_channel.connect()

            sounds = list_sounds()
            # Use the same text channel as original code (voice channel ID)
            text_channel = guild.get_channel(VOICE_CHANNEL_ID)
            if text_channel and sounds:
                await text_channel.send(
                    view=SoundboardView(voice_client, sounds)
                )

        # Play the user's join sound
        join_sound = get_sound_file(member.id, "join")
        if os.path.exists(join_sound):
            await play_sound(voice_client, join_sound)

    # -------- User leaves the monitored voice channel --------
    if before.channel == voice_channel and after.channel != voice_channel:
        if voice_client and voice_client.is_connected():
            leave_sound = get_sound_file(member.id, "leave")
            if os.path.exists(leave_sound):
                await play_sound(voice_client, leave_sound)

        # Disconnect if no non-bot members remain
        non_bot_members = [m for m in voice_channel.members if not m.bot]
        if not non_bot_members and voice_client:
            await voice_client.disconnect()
            voice_client = None

# ---------- Run the bot ----------
bot.run(TOKEN)
