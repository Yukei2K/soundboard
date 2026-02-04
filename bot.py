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

# ---------- Intents ----------
intents = discord.Intents.all()  # ensures all events are captured
bot = commands.Bot(command_prefix="!", intents=intents)

voice_client = None  # global voice client

# ---------- Helper Functions ----------

def get_sound_file(user_id: int, action: str):
    """Get a WAV file for the user, fallback to default."""
    user_file = f"{user_id}_{action}.wav"
    if os.path.exists(os.path.join(SOUNDS_DIR, user_file)):
        return os.path.join(SOUNDS_DIR, user_file)
    return os.path.join(SOUNDS_DIR, f"default_{action}.wav")

def list_sounds():
    """Return all WAV files in the sounds directory."""
    return [f for f in os.listdir(SOUNDS_DIR) if f.endswith(".wav")]

def get_text_channel_for_voice(voice_channel: discord.VoiceChannel):
    """Return a text channel corresponding to a voice channel."""
    guild = voice_channel.guild

    # 1️⃣ Look for a text channel with the same name
    for channel in guild.text_channels:
        if channel.name == voice_channel.name:
            return channel

    # 2️⃣ Look for a text channel in the same category
    if voice_channel.category:
        for channel in voice_channel.category.text_channels:
            return channel

    return

async def play_sound(vc: discord.VoiceClient, sound_file: str):
    """Play a WAV file in the connected voice channel."""
    if not vc.is_connected():
        return
    vc.play(discord.FFmpegPCMAudio(sound_file))
    while vc.is_playing():
        await asyncio.sleep(0.1)

# ---------- Events ----------

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

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
        # Connect bot if not connected
        if not voice_client or not voice_client.is_connected():
            voice_client = await voice_channel.connect()
            # Send message in the channel with the same ID as the voice channel
            text_channel = guild.get_channel(VOICE_CHANNEL_ID)
            await text_channel.send(
                f"Available sounds: {', '.join(list_sounds())}"
            )
        # Play the user's join sound
        sound_file = get_sound_file(member.id, "join")
        await play_sound(voice_client, sound_file)

    # -------- User leaves the monitored voice channel --------
    if before.channel == voice_channel and after.channel != voice_channel:
        if voice_client and voice_client.is_connected():
            # Play the user's leave sound
            sound_file = get_sound_file(member.id, "leave")
            await play_sound(voice_client, sound_file)

        # Disconnect if no non-bot members remain
        non_bot_members = [m for m in voice_channel.members if not m.bot]
        if len(non_bot_members) == 0 and voice_client:
            await voice_client.disconnect()
            voice_client = None

# ---------- Run the bot ----------
bot.run(TOKEN)
