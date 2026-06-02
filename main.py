"""
main.py — Runs both the Telegram bot and the FastAPI stream server
in a single Railway service using asyncio.
"""
import asyncio
import os
import hashlib
import logging
import urllib.parse
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, HTMLResponse
from pyrogram import Client
from pyrogram.errors import FloodWait
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ─── CONFIG ────────────────────────────────────────────────────────────────
BOT_TOKEN        = os.getenv("BOT_TOKEN", "")
API_ID           = int(os.getenv("API_ID", "0"))
API_HASH         = os.getenv("API_HASH", "")
STORAGE_CHANNEL  = int(os.getenv("STORAGE_CHANNEL", "0"))
SECRET_KEY       = os.getenv("SECRET_KEY", "mysecretkey123")
BASE_URL         = os.getenv("BASE_URL", "http://localhost:8000")
PORT             = int(os.getenv("PORT", 8000))
ALLOWED_USERS    = os.getenv("ALLOWED_USERS", "")
# ───────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Shared Pyrogram client
pyro: Client = None


# ══════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ══════════════════════════════════════════════════════

def is_allowed(user_id: int) -> bool:
    if not ALLOWED_USERS.strip():
        return True
    return str(user_id) in [u.strip() for u in ALLOWED_USERS.split(",")]


def generate_code(msg_id: int, filename: str) -> str:
    raw = f"{SECRET_KEY}:{msg_id}:{filename}"
    return hashlib.md5(raw.encode()).hexdigest()[:24]


def clean_filename(name: str) -> str:
    return name.strip()


def make_stream_link(msg_id: int, filename: str) -> str:
    safe = urllib.parse.quote(filename)
    code = generate_code(msg_id, filename)
    return f"{BASE_URL}/dl/{msg_id}/{safe}?code={code}"


def verify_code(msg_id: int, filename: str, code: str) -> bool:
    return generate_code(msg_id, filename) == code


# ══════════════════════════════════════════════════════
#  TELEGRAM BOT HANDLERS
# ══════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return
    await update.message.reply_text(
        "👋 *Video Storage Bot*\n\n"
        "Koi bhi video/document bhejo — main use private channel mein save kar ke "
        "aapko ek *streaming link* deta hoon.\n\n"
        "📌 *Supported:* Video, Document, Audio\n\n"
        "Bas file bhejo! 🚀",
        parse_mode="Markdown",
    )


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return

    msg = update.message
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

    processing = await msg.reply_text("⏳ Processing...")

    try:
        # Pyrogram se forward karo — koi size limit nahi
        forwarded = await pyro.copy_message(
            chat_id=STORAGE_CHANNEL,
            from_chat_id=msg.chat_id,
            message_id=msg.message_id,
        )
        storage_msg_id = forwarded.id
        stream_link = make_stream_link(storage_msg_id, filename)
        file_size_mb = round(file_obj.file_size / (1024 * 1024), 2) if file_obj.file_size else "?"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("▶️ Stream / Download", url=stream_link)],
        ])

        await processing.delete()
        await msg.reply_text(
            f"✅ *File Saved Successfully!*\n\n"
            f"📁 *File:* `{filename}`\n"
            f"📦 *Size:* {file_size_mb} MB\n"
            f"🆔 *Storage ID:* `{storage_msg_id}`\n\n"
            f"🔗 *Streaming Link:*\n`{stream_link}`",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    except Exception as e:
        await processing.edit_text(f"❌ Error: {e}")
        logger.error(f"handle_media error: {e}")


async def get_link_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: `/getlink <message_id> <filename>`", parse_mode="Markdown"
        )
        return
    try:
        msg_id = int(args[0])
        filename = " ".join(args[1:])
        link = make_stream_link(msg_id, filename)
        await update.message.reply_text(
            f"🔗 *Link:*\n`{link}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("▶️ Open", url=link)]]),
        )
    except ValueError:
        await update.message.reply_text("❌ Invalid message ID.")


# ══════════════════════════════════════════════════════
#  FASTAPI STREAM SERVER
# ══════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    global pyro
    pyro = Client("stream_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)
    await pyro.start()
    logger.info("Pyrogram client started.")
    yield
    await pyro.stop()


web_app = FastAPI(title="TG Stream Server", lifespan=lifespan)


@web_app.get("/")
async def index():
    return HTMLResponse("""
    <html><body style='font-family:sans-serif;text-align:center;padding:80px;background:#0f0f0f;color:#fff'>
    <h1>🎬 TG Stream Server</h1><p style='color:#aaa'>Online ✅</p>
    </body></html>
    """)


@web_app.get("/dl/{msg_id}/{filename:path}")
async def stream_file(msg_id: int, filename: str, code: str, request: Request):
    decoded = urllib.parse.unquote(filename)

    if not verify_code(msg_id, decoded, code):
        raise HTTPException(status_code=403, detail="Invalid or expired link.")

    try:
        message = await pyro.get_messages(STORAGE_CHANNEL, msg_id)
    except FloodWait as e:
        await asyncio.sleep(e.value)
        message = await pyro.get_messages(STORAGE_CHANNEL, msg_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Error: {e}")

    if not message or message.empty:
        raise HTTPException(status_code=404, detail="Message not found.")

    media = message.video or message.document or message.audio or message.video_note
    if not media:
        raise HTTPException(status_code=404, detail="No media in message.")

    file_size = media.file_size
    mime_type = getattr(media, "mime_type", "application/octet-stream")

    range_header = request.headers.get("range")
    offset, limit, status_code = 0, None, 200

    response_headers = {
        "Content-Type": mime_type,
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'inline; filename="{decoded}"',
        "Content-Length": str(file_size),
    }

    if range_header:
        parts = range_header.replace("bytes=", "").split("-")
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if parts[1] else file_size - 1
        chunk_size = 1024 * 1024
        offset = start // chunk_size
        limit = ((end - start) // chunk_size) + 1
        response_headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        response_headers["Content-Length"] = str(end - start + 1)
        status_code = 206

    async def generator():
        async for chunk in pyro.stream_media(message, offset=offset, limit=limit):
            yield chunk

    logger.info(f"Streaming msg_id={msg_id} | {decoded}")
    return StreamingResponse(generator(), status_code=status_code, headers=response_headers)


# ══════════════════════════════════════════════════════
#  MAIN — Run both together
# ══════════════════════════════════════════════════════

async def run_bot():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("getlink", get_link_cmd))
    app.add_handler(MessageHandler(
        filters.VIDEO | filters.Document.ALL | filters.AUDIO | filters.VIDEO_NOTE,
        handle_media,
    ))
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    logger.info("Bot started polling.")
    return app


async def run_server():
    config = uvicorn.Config(web_app, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    bot_app = await run_bot()
    try:
        await run_server()
    finally:
        await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
