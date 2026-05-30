import os
import base64
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8080")

def encode_file_id(file_id: str) -> str:
    return base64.urlsafe_b64encode(file_id.encode()).decode().rstrip("=")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 *Video Streaming Bot*\n\nKoi bhi video forward karo — streaming link milega!\n\n✅ Koi size limit nahi!",
        parse_mode="Markdown"
    )

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    file_id = None
    file_name = "video.mp4"
    file_size = 0

    if message.video:
        file_id = message.video.file_id
        file_name = message.video.file_name or "video.mp4"
        file_size = message.video.file_size or 0
    elif message.document and message.document.mime_type and message.document.mime_type.startswith("video"):
        file_id = message.document.file_id
        file_name = message.document.file_name or "video.mp4"
        file_size = message.document.file_size or 0
    elif message.video_note:
        file_id = message.video_note.file_id
        file_name = "video_note.mp4"
        file_size = message.video_note.file_size or 0

    if not file_id:
        await message.reply_text("❌ Video nahi mila!")
        return

    encoded = encode_file_id(file_id)
    stream_url  = f"{SERVER_URL}/{encoded}"
    watch_url   = f"{SERVER_URL}/watch/{encoded}"
    download_url = f"{SERVER_URL}/download/{encoded}"

    size_mb = file_size / (1024 * 1024) if file_size else 0
    size_text = f"{size_mb:.1f} MB" if size_mb > 0 else "N/A"

    keyboard = [
        [InlineKeyboardButton("▶️ Stream Karo", url=watch_url)],
        [InlineKeyboardButton("⬇️ Download Karo", url=download_url)],
    ]

    text = (
        f"✅ *Link Ready!*\n\n"
        f"📁 *File:* `{file_name}`\n"
        f"📦 *Size:* {size_text}\n\n"
        f"🔗 *Streaming Link:*\n`{stream_url}`\n\n"
        f"🎬 *Player Link:*\n`{watch_url}`"
    )

    await message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_other(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚠️ Sirf video files support hain!")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO | filters.VIDEO_NOTE, handle_video))
    app.add_handler(MessageHandler(filters.ALL, handle_other))
    print(f"🤖 Bot start! Server: {SERVER_URL}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
