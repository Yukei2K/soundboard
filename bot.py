import asyncio
import math
import os
import time
from pathlib import Path

from discord.ext import commands
from dotenv import load_dotenv

import discord

load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

TOKEN = os.getenv("DISCORD_TOKEN")

SOUNDS_DIR = Path(__file__).with_name("sounds")

JOIN_FILE = os.getenv("JOIN_FILE", "join.mp3")
LEAVE_FILE = os.getenv("LEAVE_FILE", "leave.mp3")

TARGET_VOICE_CHANNEL_ID = int(
    os.getenv("TARGET_VOICE_CHANNEL_ID", "950886798748442675")
)

_last_sounds_message: discord.Message | None = None

TARGET_LUFS = float(os.getenv("TARGET_LUFS", "-28"))  # -16 ist gut für Discord
TARGET_TP = float(os.getenv("TARGET_TP", "-1.5"))  # True Peak Limit
TARGET_LRA = float(os.getenv("TARGET_LRA", "11"))  # Loudness Range

AUDIO_FILTER = f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TP}:LRA={TARGET_LRA}:linear=true"

TIMEOUT = int(os.getenv("TIMEOUT", "6000"))

JOIN_DELAY = float(os.getenv("JOIN_DELAY", "0.8"))
LEAVE_DELAY = float(os.getenv("LEAVE_DELAY", "0.8"))


# ---- Per-User Sounds aus .env: PERSON_<NAME>=ID und <NAME>_JOIN/<NAME>_LEAVE=DATEI ----
def load_user_sounds_from_env_person_prefix() -> tuple[dict[int, str], dict[int, str]]:
    join_map: dict[int, str] = {}
    leave_map: dict[int, str] = {}

    for key, val in os.environ.items():
        if not key.startswith("PERSON_"):
            continue
        if not val or not val.strip().isdigit():
            continue

        name = key[len("PERSON_") :].strip()  # z.B. "MAX"
        if not name:
            continue

        user_id = int(val.strip())

        join_file = os.getenv(f"{name}_JOIN", "").strip()
        leave_file = os.getenv(f"{name}_LEAVE", "").strip()

        if join_file:
            join_map[user_id] = join_file
        if leave_file:
            leave_map[user_id] = leave_file

    return join_map, leave_map


USER_JOIN_SOUNDS, USER_LEAVE_SOUNDS = load_user_sounds_from_env_person_prefix()

# ---- Intents ----
intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True
intents.message_content = True  # <-- ADD THIS

bot = commands.Bot(command_prefix="!", intents=intents)

_last_play = 0.0
COOLDOWN_SECONDS = 1.0


def list_sound_files_public() -> list[Path]:
    """Sounds für /sounds: keine custom_ Dateien anzeigen."""
    if not SOUNDS_DIR.exists():
        return []
    files: list[Path] = []
    for p in SOUNDS_DIR.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in (".mp3", ".wav", ".ogg", ".opus"):
            continue
        if p.stem.lower().startswith("custom_"):
            continue
        files.append(p)
    files.sort(key=lambda x: x.name.lower())
    return files


def get_sound_path(filename: str) -> Path:
    return (SOUNDS_DIR / filename).resolve()


def humans_in_channel(channel: discord.VoiceChannel) -> int:
    return sum(1 for m in channel.members if not m.bot)


async def play_file_in_voice(vc: discord.VoiceClient, file_path: Path):
    global _last_play
    if not file_path.exists():
        return

    now = time.time()
    if now - _last_play < COOLDOWN_SECONDS:
        return
    _last_play = now

    if vc.is_playing():
        vc.stop()

    source = discord.FFmpegPCMAudio(str(file_path), options=f'-vn -af "{AUDIO_FILTER}"')

    vc.play(source)


async def play_with_delay(vc: discord.VoiceClient, file_path: Path, delay: float):
    await asyncio.sleep(max(0.0, delay))
    if vc is None or not vc.is_connected():
        return
    await play_file_in_voice(vc, file_path)


# ---------- UI: Buttons / Pages ----------
class SoundButton(discord.ui.Button):
    def __init__(self, filename: str):
        super().__init__(label=Path(filename).stem, style=discord.ButtonStyle.secondary)
        self.filename = filename

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message(
                "Kein Server-Kontext.", ephemeral=True
            )

        vc = guild.voice_client
        if vc is None or not vc.is_connected():
            return await interaction.response.send_message(
                "Ich bin in keinem Voice-Channel.", ephemeral=True
            )

        # Nur im gleichen Channel abspielbar
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message(
                "Du bist in keinem Voice-Channel.", ephemeral=True
            )
        if vc.channel and interaction.user.voice.channel.id != vc.channel.id:
            return await interaction.response.send_message(
                "Du musst im gleichen Voice-Channel wie ich sein.", ephemeral=True
            )

        file_path = get_sound_path(self.filename)
        await play_file_in_voice(vc, file_path)
        #
        # Disable ephemeral auto-reply for user
        #
        # await interaction.response.send_message(f"▶️ Spiele: **{Path(self.filename).stem}**", ephemeral=True)
        #
        await interaction.response.defer(
            ephemeral=True
        )  # tells Discord “I got this” but show nothing


class PrevButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="⬅️ Prev", style=discord.ButtonStyle.primary, row=4)

    async def callback(self, interaction: discord.Interaction):
        view: SoundPagerView = self.view  # type: ignore
        view.page = max(0, view.page - 1)
        await view.refresh(interaction)


class NextButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Next ➡️", style=discord.ButtonStyle.primary, row=4)

    async def callback(self, interaction: discord.Interaction):
        view: SoundPagerView = self.view  # type: ignore
        view.page = min(view.max_page, view.page + 1)
        await view.refresh(interaction)


class SoundPagerView(discord.ui.View):
    def __init__(self, files: list[Path], page: int = 0, per_page: int = 20):
        super().__init__(timeout=TIMEOUT)
        self.files = files
        self.page = page
        self.per_page = per_page
        self.max_page = max(0, math.ceil(len(files) / per_page) - 1)
        self.render()

    def render(self):
        self.clear_items()
        start = self.page * self.per_page
        end = start + self.per_page
        page_files = self.files[start:end]

        for f in page_files:
            self.add_item(SoundButton(f.name))

        self.add_item(PrevButton())
        self.add_item(NextButton())

    async def refresh(self, interaction: discord.Interaction):
        self.render()
        await interaction.response.edit_message(
            content=f"Sounds (Seite {self.page + 1}/{self.max_page + 1}) – klicke zum Abspielen:",
            view=self,
        )


@bot.event
async def on_ready():
    print(f"Online als {bot.user} (ID: {bot.user.id})")
    if not SOUNDS_DIR.exists():
        print(f"⚠️ Ordner fehlt: {SOUNDS_DIR} (lege 'sounds/' neben bot.py an)")
    print(f"User join sounds geladen: {len(USER_JOIN_SOUNDS)}")
    print(f"User leave sounds geladen: {len(USER_LEAVE_SOUNDS)}")


async def refresh_voice_channel_sounds(channel: discord.TextChannel):
    global _last_sounds_message

    files = list_sound_files_public()
    if not files:
        return

    view = SoundPagerView(files=files, page=0, per_page=20)

    # delete the previous soundboard message (ONLY that one)
    if _last_sounds_message:
        try:
            await _last_sounds_message.delete()
        except (discord.NotFound, discord.Forbidden):
            pass
        finally:
            _last_sounds_message = None

    # send a brand new message (this bumps it)
    _last_sounds_message = await channel.send(
        content=f"🎵 **Sounds** (Seite 1/{view.max_page + 1}) – klick zum Abspielen:",
        view=view,
    )


_last_refresh = 0.0


@bot.event
async def on_message(message: discord.Message):
    global _last_refresh

    if message.author.bot:
        return

    if message.channel.id != TARGET_VOICE_CHANNEL_ID:
        return

    now = time.time()
    if now - _last_refresh < 1.2:
        return

    _last_refresh = now
    await refresh_voice_channel_sounds(message.channel)


# ---------- Auto-Join + Join/Leave Sounds ----------
@bot.event
async def on_voice_state_update(
    member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
):
    if member.bot:
        return

    guild = member.guild
    vc = guild.voice_client

    target_channel = guild.get_channel(TARGET_VOICE_CHANNEL_ID)
    if not isinstance(target_channel, discord.VoiceChannel):
        return

    # -------- USER JOINED TARGET CHANNEL --------
    if after.channel and after.channel.id == TARGET_VOICE_CHANNEL_ID:
        humans = humans_in_channel(target_channel)

        # first human joined → bot connects
        if humans == 1 and (vc is None or not vc.is_connected()):
            try:
                await target_channel.connect()
            except Exception:
                return

            # 🔊 play join sound
            filename = USER_JOIN_SOUNDS.get(member.id, JOIN_FILE)
            path = get_sound_path(filename)
            asyncio.create_task(play_with_delay(guild.voice_client, path, JOIN_DELAY))

            # 🎵 send soundboard to voice channel chat
            await refresh_voice_channel_sounds(target_channel)
        return

    # -------- USER LEFT TARGET CHANNEL --------
    if before.channel and before.channel.id == TARGET_VOICE_CHANNEL_ID:
        if vc is None or not vc.is_connected():
            return

        humans_left = humans_in_channel(target_channel)

        # play leave sound if others remain
        if humans_left > 0:
            filename = USER_LEAVE_SOUNDS.get(member.id, LEAVE_FILE)
            path = get_sound_path(filename)
            asyncio.create_task(play_with_delay(vc, path, LEAVE_DELAY))

        # last human left → bot disconnects
        if humans_left == 0:
            # delete the last soundboard message if it exists
            global _last_sounds_message
            if _last_sounds_message:
                try:
                    await _last_sounds_message.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
                finally:
                    _last_sounds_message = None

            await asyncio.sleep(0.2)
            await vc.disconnect()

        return


if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN fehlt. Prüfe deine .env oder Environment-Variablen."
    )
    raise RuntimeError(
        "DISCORD_TOKEN fehlt. Prüfe deine .env oder Environment-Variablen."
    )

bot.run(TOKEN)
