import os
import base64
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8080")

bot = Client(
    "tgbot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True
)

def encode(file_id: str) -> str:
    return base64.urlsafe_b64encode(file_id.encode()).decode().rstrip("=")

@bot.on_message(filters.command("start"))
async def start(client, message: Message):
    await message.reply_text(
        "🎬 **Video Streaming Bot**\n\n"
        "Koi bhi video forward karo — streaming link milega!\n"
        "✅ Koi size limit nahi!"
    )

@bot.on_message(filters.video | filters.document | filters.video_note)
async def handle_video(client, message: Message):
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

    enc = encode(file_id)
    stream_url   = f"{SERVER_URL}/{enc}"
    watch_url    = f"{SERVER_URL}/watch/{enc}"
    download_url = f"{SERVER_URL}/download/{enc}"

    size_mb = file_size / (1024 * 1024) if file_size else 0
    size_text = f"{size_mb:.1f} MB" if size_mb > 0 else "N/A"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Stream Karo", url=watch_url)],
        [InlineKeyboardButton("⬇️ Download Karo", url=download_url)],
    ])

    await message.reply_text(
        f"✅ **Link Ready!**\n\n"
        f"📁 **File:** `{file_name}`\n"
        f"📦 **Size:** {size_text}\n\n"
        f"🔗 **Streaming Link:**\n`{stream_url}`",
        reply_markup=keyboard
    )

if __name__ == "__main__":
    print("🤖 Bot start!")
    bot.run()
