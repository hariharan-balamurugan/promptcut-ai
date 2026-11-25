import os
import re
import uuid
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# Load .env from project root.
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Save received music here.
MUSIC_DIR = BASE_DIR / "backend" / "music" / "tamil"
MUSIC_DIR.mkdir(parents=True, exist_ok=True)

MAX_FILE_SIZE = 20 * 1024 * 1024
ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".aac"}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Welcome to PromptCut Tamil Music Bot!\n\n"
        "Send an audio file that you own or are authorized to use. "
        "I'll save it and register it in the PromptCut music catalog."
    )


async def receive_music(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message

    if message.audio:
        audio_file = message.audio
        original_name = audio_file.file_name or "tamil_song.mp3"
        track_title = audio_file.title or Path(original_name).stem
        track_artist = audio_file.performer or "Unknown artist"
    elif message.document:
        audio_file = message.document
        original_name = audio_file.file_name or "tamil_song.mp3"
        track_title = Path(original_name).stem
        track_artist = "Unknown artist"
    else:
        await message.reply_text("Please send an audio file.")
        return

    extension = Path(original_name).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        await message.reply_text(
            "Unsupported format. Send MP3, WAV, M4A, OGG or AAC."
        )
        return

    if audio_file.file_size and audio_file.file_size > MAX_FILE_SIZE:
        await message.reply_text("File is too large. Maximum size is 20 MB.")
        return

    safe_name = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        Path(original_name).name,
    )
    unique_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
    destination = MUSIC_DIR / unique_name

    try:
        telegram_file = await context.bot.get_file(audio_file.file_id)
        await telegram_file.download_to_drive(custom_path=str(destination))

        # Import locally so the bot can still start with a clear error if
        # the catalog module is missing or its dependencies are unavailable.
        from app.services.music_catalog import register_track

        track = register_track(
            destination,
            title=track_title,
            artist=track_artist,
            language="tamil",
            category="tamil",
            mood="general",
            source="telegram_bot",
            license_name="user_supplied_unverified",
        )

        await message.reply_text(
            "Music received and registered successfully!\n\n"
            f"Title: {track['title']}\n"
            f"Artist: {track['artist']}\n"
            f"Music ID: {track['music_id']}\n"
            f"Saved in: backend/music/tamil/{unique_name}\n\n"
            "License status: unverified. Use it only if you have the "
            "necessary rights."
        )

        print(
            "Music saved and registered:",
            track["music_id"],
            destination,
        )

    except Exception as error:
        print("Music registration error:", error)
        # Keep the downloaded file for recovery if catalog registration fails.
        await message.reply_text(
            "The audio was downloaded, but catalog registration failed. "
            "Check the terminal error before sending it again."
        )


def main():
    if not BOT_TOKEN:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN missing in project .env file."
        )

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(
            filters.AUDIO | filters.Document.AUDIO,
            receive_music,
        )
    )

    print("PromptCut Tamil Music Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
