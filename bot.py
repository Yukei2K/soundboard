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
VOICE_CHANNEL_ID = int(os.getenv("VOICE_CHANNEL_ID", "950886798748442675"))
LOUDNORM_I = os.getenv("VOLUME", "-45")
JOIN_DELAY = float(os.getenv("DELAY", "0.7"))  # ⏱ join sound delay

# ---------- Paths ----------
SOUNDS_DIR = "sounds"
SOUNDBOARD_DIR = os.path.join(SOUNDS_DIR, "soundboard")
USERS_DIR = os.path.join(SOUNDS_DIR, "users")
SOUNDS_PER_PAGE = 10

# ---------- Intents ----------
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

voice_client: discord.VoiceClient | None = None
soundboard_message: discord.Message | None = None

# ---------- Helper Functions ----------

def list_sounds():
    """Return all soundboard MP3 files."""
    if not os.path.exists(SOUNDBOARD_DIR):
        return []

    return sorted(
        f for f in os.listdir(SOUNDBOARD_DIR)
        if f.lower().endswith(".mp3")
    )

def get_user_sound_folder(user_id: int) -> str | None:
    """Find the user folder matching a Discord user ID."""
    if not os.path.exists(USERS_DIR):
        return None

    for folder in os.listdir(USERS_DIR):
        folder_path = os.path.join(USERS_DIR, folder)
        id_file = os.path.join(folder_path, "id.txt")

        if not os.path.isdir(folder_path) or not os.path.exists(id_file):
            continue

        try:
            with open(id_file, "r", encoding="utf-8") as f:
                stored_id = int(f.read().strip())
            if stored_id == user_id:
                return folder_path
        except:
            continue

    return None

def get_join_leave_sound(user_id: int, action: str) -> str | None:
    """Get custom join/leave sound or fallback to default."""
    user_folder = get_user_sound_folder(user_id)
    if user_folder:
        custom = os.path.join(user_folder, f"{action}.mp3")
        if os.path.exists(custom):
            return custom

    default_sound = os.path.join(USERS_DIR, "default", f"{action}.mp3")
    if os.path.exists(default_sound):
        return default_sound

    return None

async def play_sound(vc: discord.VoiceClient, sound_file: str):
    """Play a sound with loudness normalization."""
    if not vc or not vc.is_connected():
        return

    if vc.is_playing():
        vc.stop()

    source = discord.FFmpegPCMAudio(
        sound_file,
        options=f"-af loudnorm=I={LOUDNORM_I}:LRA=11:TP=-2.0"
    )
    vc.play(source)

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
                        "🔊 Du musst im selben Voice Channel sein.",
                        ephemeral=True
                    )
                    return

                await interaction.response.defer()
                await play_sound(self.vc, os.path.join(SOUNDBOARD_DIR, sound))

            button = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary)
            button.callback = callback
            self.add_item(button)

        prev_btn = discord.ui.Button(
            label="⏮",
            style=discord.ButtonStyle.primary,
            disabled=self.page == 0,
            row=2
        )
        next_btn = discord.ui.Button(
            label="⏭",
            style=discord.ButtonStyle.primary,
            disabled=self.page >= self.max_pages - 1,
            row=2
        )

        prev_btn.callback = self.prev_page
        next_btn.callback = self.next_page

        self.add_item(prev_btn)
        self.add_item(next_btn)

    async def prev_page(self, interaction: discord.Interaction):
        self.page -= 1
        self.build()
        await interaction.response.edit_message(view=self)

    async def next_page(self, interaction: discord.Interaction):
        self.page += 1
        self.build()
        await interaction.response.edit_message(view=self)

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
    if not voice_channel:
        return

    # ----- JOIN -----
    if after.channel == voice_channel and before.channel != voice_channel:
        if not voice_client or not voice_client.is_connected():
            voice_client = await voice_channel.connect()

            sounds = list_sounds()
            text_channel = guild.get_channel(VOICE_CHANNEL_ID)

            if text_channel and sounds:
                try:
                    if soundboard_message:
                        await soundboard_message.delete()
                except:
                    pass

                soundboard_message = await text_channel.send(
                    view=SoundboardView(voice_client, sounds)
                )

        join_sound = get_join_leave_sound(member.id, "join")
        if join_sound:
            await asyncio.sleep(JOIN_DELAY)  # ⏱ delay before playing
            await play_sound(voice_client, join_sound)

    # ----- LEAVE -----
    if before.channel == voice_channel and after.channel != voice_channel:
        leave_sound = get_join_leave_sound(member.id, "leave")
        if leave_sound and voice_client:
            await play_sound(voice_client, leave_sound)

        non_bot_members = [m for m in voice_channel.members if not m.bot]
        if not non_bot_members and voice_client:
            await voice_client.disconnect()
            voice_client = None

            try:
                if soundboard_message:
                    await soundboard_message.delete()
            except:
                pass

            soundboard_message = None

# ---------- Auto-refresh soundboard ----------

@bot.event
async def on_message(message: discord.Message):
    global soundboard_message, voice_client

    if message.author.bot:
        return

    if message.channel.id != VOICE_CHANNEL_ID:
        return

    if not voice_client or not voice_client.is_connected():
        return

    sounds = list_sounds()
    if not sounds:
        return

    try:
        if soundboard_message:
            await soundboard_message.delete()
    except:
        pass

    soundboard_message = await message.channel.send(
        view=SoundboardView(voice_client, sounds)
    )

# ---------- Run ----------
bot.run(TOKEN)
