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

LOUDNORM_I = os.getenv("LOUDNORM_I", "-45")

# ---------- Config ----------
SOUNDS_DIR = "sounds"
SOUNDS_PER_PAGE = 10

# ---------- Intents ----------
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

voice_client: discord.VoiceClient | None = None
soundboard_message: discord.Message | None = None  # Track the last soundboard message

# ---------- Helper Functions ----------

def get_sound_file(user_id: int, action: str):
    """Get an MP3 file for the user, fallback to default."""
    user_file = f"{user_id}_{action}.mp3"
    if os.path.exists(os.path.join(SOUNDS_DIR, user_file)):
        return os.path.join(SOUNDS_DIR, user_file)
    return os.path.join(SOUNDS_DIR, f"default_{action}.mp3")

def list_sounds():
    """Return all MP3 files in the sounds directory, excluding _join and _leave files."""
    if not os.path.exists(SOUNDS_DIR):
        return []
    all_files = sorted(f for f in os.listdir(SOUNDS_DIR) if f.lower().endswith(".mp3"))
    # Exclude join/leave files
    return [f for f in all_files if not (f.endswith("_join.mp3") or f.endswith("_leave.mp3"))]

async def play_sound(vc: discord.VoiceClient, sound_file: str):
    """Play an MP3 file in the connected voice channel with real-time loudness normalization."""
    if not vc.is_connected():
        return
    if vc.is_playing():
        vc.stop()

    # Use FFmpeg's loudnorm filter to normalize the audio dynamically
    audio_source = discord.FFmpegPCMAudio(
        sound_file, 
        options=f"-af loudnorm=I={LOUDNORM_I}:LRA=11:TP=-2.0"
    )
    vc.play(audio_source)
    
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
                        "❌ Bot ist nicht mit einem Voice Channel verbunden.",
                        ephemeral=True
                    )
                    return
                if not interaction.user.voice or interaction.user.voice.channel != self.vc.channel:
                    await interaction.response.send_message(
                        "🔊 Du musst in einem Voice Channel sein.",
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
            row=2  # Changed from 1 to 2 for a new row
        )
        next_btn = discord.ui.Button(
            label="⏭",
            style=discord.ButtonStyle.primary,
            disabled=self.page >= self.max_pages - 1,
            row=2  # Changed from 1 to 2 for a new row
        )
        prev_btn.callback = self.prev_page
        next_btn.callback = self.next_page
        self.add_item(prev_btn)
        self.add_item(next_btn)

    async def prev_page(self, interaction: discord.Interaction):
        self.page -= 1
        self.build()
        await interaction.response.edit_message(content=None, view=self)

    async def next_page(self, interaction: discord.Interaction):
        self.page += 1
        self.build()
        await interaction.response.edit_message(content=None, view=self)

# ---------- Events ----------

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

@bot.event
async def on_voice_state_update(member, before, after):
    global voice_client, soundboard_message
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
            text_channel = guild.get_channel(VOICE_CHANNEL_ID)
            if text_channel and sounds:
                # Delete old message if exists
                try:
                    if soundboard_message:
                        await soundboard_message.delete()
                except:
                    pass
                # Send initial soundboard and track the message (no text)
                soundboard_message = await text_channel.send(
                    content=None,
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

            # Delete the last soundboard message when bot leaves
            try:
                if soundboard_message:
                    await soundboard_message.delete()
            except:
                pass
            soundboard_message = None

# -------- Auto-refresh soundboard when someone sends a message --------
@bot.event
async def on_message(message: discord.Message):
    global soundboard_message, voice_client

    # Ignore bot messages
    if message.author.bot:
        return

    # Only respond in the monitored text channel
    if message.channel.id != VOICE_CHANNEL_ID:
        return

    # Make sure voice_client is connected
    if not voice_client or not voice_client.is_connected():
        return

    sounds = list_sounds()
    if not sounds:
        return

    # Delete previous soundboard message if exists
    try:
        if soundboard_message:
            await soundboard_message.delete()
    except:
        pass

    # Send new message with the soundboard view (no text)
    soundboard_message = await message.channel.send(
        content=None,
        view=SoundboardView(voice_client, sounds)
    )

# ---------- Run the bot ----------
bot.run(TOKEN)
