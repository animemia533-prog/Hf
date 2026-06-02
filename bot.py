import os
import hashlib
import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ─── CONFIG (set these in .env or directly here) ────────────────────────────
BOT_TOKEN        = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
STORAGE_CHANNEL  = os.getenv("STORAGE_CHANNEL", "-100XXXXXXXXXX")   # private channel id
BASE_URL         = os.getenv("BASE_URL", "https://filetolink.run.place")
SECRET_KEY       = os.getenv("SECRET_KEY", "mysecretkey123")         # for hash generation
ALLOWED_USERS    = os.getenv("ALLOWED_USERS", "")                    # comma-separated user IDs, empty = all allowed
# ────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def is_allowed(user_id: int) -> bool:
    """Check if user is allowed to use the bot."""
    if not ALLOWED_USERS.strip():
        return True  # open to all
    allowed = [uid.strip() for uid in ALLOWED_USERS.split(",")]
    return str(user_id) in allowed


def generate_code(msg_id: int, filename: str) -> str:
    """Generate a deterministic hash code for the streaming link."""
    raw = f"{SECRET_KEY}:{msg_id}:{filename}"
    return hashlib.md5(raw.encode()).hexdigest()[:24]


def clean_filename(name: str) -> str:
    """Remove special chars and spaces for URL-safe filename."""
    name = re.sub(r'[^\w\s\-\.\[\]@]', '', name)
    return name.strip().replace(" ", "%20")


def make_stream_link(msg_id: int, filename: str) -> str:
    """Build the streaming link."""
    safe_name = clean_filename(filename)
    code = generate_code(msg_id, filename)
    return f"{BASE_URL}/dl/{msg_id}/{safe_name}?code={code}"


# ─── HANDLERS ───────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_allowed(user.id):
        await update.message.reply_text("⛔ You are not authorized to use this bot.")
        return

    text = (
        "👋 *Video Storage Bot*\n\n"
        "Koi bhi video/document bhejo — main use private channel mein save kar ke "
        "aapko ek *streaming link* deta hoon.\n\n"
        "📌 *Supported:*\n"
        "• Video files\n"
        "• Document (any size)\n"
        "• Audio files\n\n"
        "Bas file bhejo! 🚀"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_allowed(user.id):
        await update.message.reply_text("⛔ You are not authorized.")
        return

    msg = update.message

    # Determine media type and filename
    file_obj = None
    filename = "video"

    if msg.video:
        file_obj = msg.video
        filename = msg.video.file_name or f"video_{msg.video.file_unique_id}.mp4"
    elif msg.document:
        file_obj = msg.document
        filename = msg.document.file_name or f"doc_{msg.document.file_unique_id}"
    elif msg.audio:
        file_obj = msg.audio
        filename = msg.audio.file_name or f"audio_{msg.audio.file_unique_id}.mp3"
    elif msg.video_note:
        file_obj = msg.video_note
        filename = f"videonote_{msg.video_note.file_unique_id}.mp4"
    else:
        await msg.reply_text("❌ Sirf video, document, ya audio files bhejein.")
        return

    # Send processing message
    processing_msg = await msg.reply_text("⏳ Processing... Please wait.")

    try:
        # Forward to private storage channel
        forwarded = await context.bot.copy_message(
            chat_id=STORAGE_CHANNEL,
            from_chat_id=msg.chat_id,
            message_id=msg.message_id,
        )

        storage_msg_id = forwarded.message_id

        # Generate streaming link
        stream_link = make_stream_link(storage_msg_id, filename)

        # Build response
        file_size_mb = round(file_obj.file_size / (1024 * 1024), 2) if file_obj.file_size else "?"
        
        response_text = (
            f"✅ *File Saved Successfully!*\n\n"
            f"📁 *File:* `{filename}`\n"
            f"📦 *Size:* {file_size_mb} MB\n"
            f"🆔 *Storage ID:* `{storage_msg_id}`\n\n"
            f"🔗 *Streaming Link:*\n`{stream_link}`"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("▶️ Stream / Download", url=stream_link)],
        ])

        await processing_msg.delete()
        await msg.reply_text(response_text, parse_mode="Markdown", reply_markup=keyboard)

        logger.info(f"File '{filename}' saved. Storage msg_id={storage_msg_id}, link={stream_link}")

    except Exception as e:
        await processing_msg.edit_text(f"❌ Error: {str(e)}")
        logger.error(f"Error handling media: {e}")


async def get_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /getlink <message_id> <filename>
    Manually generate a link for an already-stored message.
    """
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: `/getlink <message_id> <filename>`\n"
            "Example: `/getlink 74009 S01E07_1080p.mkv`",
            parse_mode="Markdown"
        )
        return

    try:
        msg_id = int(args[0])
        filename = " ".join(args[1:])
        link = make_stream_link(msg_id, filename)
        await update.message.reply_text(
            f"🔗 *Generated Link:*\n`{link}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ Open Link", url=link)]
            ])
        )
    except ValueError:
        await update.message.reply_text("❌ Invalid message ID. It must be a number.")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot stats/info."""
    if not is_allowed(update.effective_user.id):
        return
    text = (
        f"📊 *Bot Info*\n\n"
        f"🗄 *Storage Channel:* `{STORAGE_CHANNEL}`\n"
        f"🌐 *Base URL:* `{BASE_URL}`\n"
        f"👤 *Your ID:* `{update.effective_user.id}`\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ─── MAIN ───────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("getlink", get_link))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(MessageHandler(
        filters.VIDEO | filters.Document.ALL | filters.AUDIO | filters.VIDEO_NOTE,
        handle_media
    ))

    logger.info("Bot started polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
