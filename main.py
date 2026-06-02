import os
import hashlib
import logging
import urllib.parse
import asyncio
import math
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

BOT_TOKEN        = os.getenv("BOT_TOKEN", "")
API_ID           = int(os.getenv("API_ID", "0"))
API_HASH         = os.getenv("API_HASH", "")
STORAGE_CHANNEL  = int(os.getenv("STORAGE_CHANNEL", "0"))
SECRET_KEY       = os.getenv("SECRET_KEY", "mysecretkey123")
BASE_URL         = os.getenv("BASE_URL", "http://localhost:8000")
PORT             = int(os.getenv("PORT", 8000))
ALLOWED_USERS    = os.getenv("ALLOWED_USERS", "")

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

pyro: Client = None


def is_allowed(user_id):
    if not ALLOWED_USERS.strip():
        return True
    return str(user_id) in [u.strip() for u in ALLOWED_USERS.split(",")]


def generate_code(msg_id, filename):
    raw = f"{SECRET_KEY}:{msg_id}:{filename}"
    return hashlib.md5(raw.encode()).hexdigest()[:24]


def make_stream_link(msg_id, filename):
    safe = urllib.parse.quote(filename)
    code = generate_code(msg_id, filename)
    return f"{BASE_URL}/dl/{msg_id}/{safe}?code={code}"


def verify_code(msg_id, filename, code):
    return generate_code(msg_id, filename) == code


# ── BOT HANDLERS ──────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return
    await update.message.reply_text(
        "👋 *Video Storage Bot*\n\n"
        "Koi bhi video/document bhejo — main use private channel mein save kar ke "
        "aapko ek *streaming link* deta hoon.\n\nBas file bhejo! 🚀",
        parse_mode="Markdown",
    )


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    msg = update.message
    file_obj, filename = None, "video"

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
        forwarded = await context.bot.copy_message(
            chat_id=STORAGE_CHANNEL,
            from_chat_id=msg.chat_id,
            message_id=msg.message_id,
        )
        storage_msg_id = forwarded.message_id
        stream_link = make_stream_link(storage_msg_id, filename)
        file_size_mb = round(file_obj.file_size / (1024 * 1024), 2) if file_obj.file_size else "?"

        await processing.delete()
        await msg.reply_text(
            f"✅ *File Saved Successfully!*\n\n"
            f"📁 *File:* `{filename}`\n"
            f"📦 *Size:* {file_size_mb} MB\n"
            f"🆔 *Storage ID:* `{storage_msg_id}`\n\n"
            f"🔗 *Streaming Link:*\n`{stream_link}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("▶️ Stream / Download", url=stream_link)]]),
        )
    except Exception as e:
        await processing.edit_text(f"❌ Error: {e}")


async def get_link_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: `/getlink <message_id> <filename>`", parse_mode="Markdown")
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


# ── FASTAPI ───────────────────────────────────────────

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
        # FIXED: Pyrogram Client ka use karke bina list unpacking ke message fetch kiya
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

    CHUNK_SIZE = 1024 * 1024  # 1MB

    range_header = request.headers.get("range")
    start = 0
    end = file_size - 1

    if range_header:
        parts = range_header.replace("bytes=", "").split("-")
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if parts[1] else file_size - 1

    content_length = end - start + 1
    offset = start // CHUNK_SIZE
    first_chunk_cut = start % CHUNK_SIZE
    limit = math.ceil(content_length / CHUNK_SIZE) + 1

    # FIXED: UnicodeEncodeError se bachne ke liye filename ko UTF-8 URL encode kiya gaya hai
    safe_filename = urllib.parse.quote(decoded)

    response_headers = {
        "Content-Type": mime_type,
        "Accept-Ranges": "bytes",
        "Content-Disposition": f"inline; filename*=UTF-8''{safe_filename}",
        "Content-Length": str(content_length),
        "Content-Range": f"bytes {start}-{end}/{file_size}",
    }

    async def generator():
        bytes_sent = 0
        chunk_index = 0
        async for chunk in pyro.stream_media(message, offset=offset, limit=limit):
            if chunk_index == 0:
                chunk = chunk[first_chunk_cut:]
            if bytes_sent + len(chunk) > content_length:
                chunk = chunk[:content_length - bytes_sent]
            yield chunk
            bytes_sent += len(chunk)
            chunk_index += 1
            if bytes_sent >= content_length:
                break

    status_code = 206 if range_header else 200
    logger.info(f"Streaming msg_id={msg_id} | {decoded} | {start}-{end}/{file_size}")
    return StreamingResponse(generator(), status_code=status_code, headers=response_headers)


# ── MAIN ──────────────────────────────────────────────

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
