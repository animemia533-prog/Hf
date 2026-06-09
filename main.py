import os
import re
import hashlib
import logging
import urllib.parse
import asyncio
import math
import time
from contextlib import asynccontextmanager

import aiohttp

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

# ── ENV CONFIG ────────────────────────────────────────

BOT_TOKEN        = os.getenv("BOT_TOKEN", "")
API_ID           = int(os.getenv("API_ID", "0"))
API_HASH         = os.getenv("API_HASH", "")
STORAGE_CHANNEL  = int(os.getenv("STORAGE_CHANNEL", "0"))
SECRET_KEY       = os.getenv("SECRET_KEY", "mysecretkey123")
BASE_URL         = os.getenv("BASE_URL", "http://localhost:8000")
PORT             = int(os.getenv("PORT", 8000))
ALLOWED_USERS    = os.getenv("ALLOWED_USERS", "")
FIREBASE_URL     = os.getenv("FIREBASE_URL", "")
SERVER_NAME      = os.getenv("SERVER_NAME", "Player")

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

pyro: Client = None

# ── IN-MEMORY USER SETUP STORE ────────────────────────
user_setup: dict = {}

# ── QUALITY BUFFER ─────────────────────────────────────
quality_buffer: dict = {}
QUALITY_COUNT = 3


def assign_qualities(videos: list) -> dict:
    sorted_vids = sorted(enumerate(videos), key=lambda x: x[1]["size"])
    quality_names = ["480p", "720p", "1080p"]
    if len(sorted_vids) == 2:
        quality_names = ["480p", "1080p"]
    result = {}
    for i, (orig_idx, _) in enumerate(sorted_vids):
        result[orig_idx] = quality_names[i] if i < len(quality_names) else f"quality{i}"
    return result


# ── HELPERS ───────────────────────────────────────────

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


def make_download_link(msg_id, filename):
    safe = urllib.parse.quote(filename)
    code = generate_code(msg_id, filename)
    return f"{BASE_URL}/dl/{msg_id}/{safe}?code={code}&dl=1"


def verify_code(msg_id, filename, code):
    return generate_code(msg_id, filename) == code


def extract_episode(text: str):
    if not text:
        return None
    t = text.upper()
    ep_num = None
    ep_match = re.search(r'\bEP(?:ISODE)?\s*[-:→►\s]*\s*(\d{1,3})\b', t)
    if ep_match:
        ep_num = int(ep_match.group(1))
    if ep_num is None:
        e_match = re.search(r'\bE(\d{1,3})\b', t)
        if e_match:
            ep_num = int(e_match.group(1))
    if ep_num is None:
        cleaned = re.sub(r'\bS\d{1,2}\b', '', t)
        nums = re.findall(r'\b(\d{1,2})\b', cleaned)
        if nums:
            ep_num = int(nums[0])
    return ep_num


def extract_quality(text: str):
    if not text:
        return None
    q_match = re.search(r'\b(1080[Pp]|720[Pp]|480[Pp])\b', text)
    if q_match:
        return q_match.group(1).lower()
    return None


def get_extension(filename: str, fallback: str = "mp4") -> str:
    if filename and "." in filename:
        return filename.rsplit(".", 1)[-1].lower()
    return fallback


async def save_to_firebase(slug, season, ep_num, stream_link, quality=None, download_link=None) -> bool:
    try:
        from datetime import datetime, timezone
        ep_key     = f"E{ep_num}"
        db_url     = FIREBASE_URL.rstrip("/")
        now_ts     = int(time.time())
        season_num = int(re.sub(r'[^\d]', '', season) or "1")
        date_str   = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if quality:
            ep_path = f"anime_links/{slug}/{season}/{ep_key}/{quality}"
        else:
            ep_path = f"anime_links/{slug}/{season}/{ep_key}"

        url1 = f"{db_url}/{ep_path}.json"
        payload1 = {"link": stream_link, "server": SERVER_NAME, "time": now_ts}
        if download_link:
            payload1["dl_link"] = download_link

        async with aiohttp.ClientSession() as session:
            async with session.put(url1, json=payload1) as resp:
                if resp.status == 200:
                    logger.info(f"Firebase saved: {ep_path}")
                else:
                    text = await resp.text()
                    logger.error(f"Firebase error {resp.status}: {text}")
                    return False

            if quality is None or quality == "1080p":
                url2 = f"{db_url}/added_today/{date_str}/{slug}.json"
                payload2 = {"e": ep_num, "s": season_num, "timestamp": now_ts}
                async with session.put(url2, json=payload2) as resp:
                    if resp.status == 200:
                        logger.info(f"added_today saved: {date_str}/{slug} S{season_num}E{ep_num}")
                    else:
                        text = await resp.text()
                        logger.warning(f"added_today failed {resp.status}: {text}")
        return True
    except Exception as e:
        logger.error(f"Firebase save error: {e}")
        return False


# ── BOT HANDLERS ──────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return
    await update.message.reply_text(
        "👋 *Video Storage Bot*\n\n"
        "📌 *Setup karo:*\n`/setup <anime-slug> <season>`\n"
        "_Example: /setup attack-on-titan 1_\n\n"
        "Phir video forward karo — caption mein episode number hona chahiye "
        "jaise `Episode 7`, `Ep 01`, `EP-12` etc.\n\n"
        "Bot automatically filename banayega! 🚀",
        parse_mode="Markdown",
    )


async def setup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "❌ *Usage:* `/setup <anime-slug> <season-number>`\n\n"
            "*Examples:*\n`/setup attack-on-titan 1`\n`/setup mushoku-tensei 2`",
            parse_mode="Markdown",
        )
        return
    slug = args[0].lower().strip()
    raw_season = args[1].strip()
    season = f"S{raw_season}" if raw_season.isdigit() else raw_season.upper()
    user_setup[update.effective_user.id] = {"slug": slug, "season": season}
    logger.info(f"User {update.effective_user.id} setup: slug={slug}, season={season}")
    await update.message.reply_text(
        f"✅ *Setup Saved!*\n\n🎌 *Anime Slug:* `{slug}`\n📺 *Season:* `{season}`\n\n"
        f"Ab video forward karo aur caption mein episode number likhna na bhoolo!\n"
        f"_Supported: Episode 7 / Ep 01 / EP-12 / E07_",
        parse_mode="Markdown",
    )


async def clear_setup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    uid = update.effective_user.id
    user_setup.pop(uid, None)
    quality_buffer.pop(uid, None)
    await update.message.reply_text("🗑️ Setup clear ho gaya. `/setup` se naya set karo.", parse_mode="Markdown")


async def current_setup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    setup = user_setup.get(update.effective_user.id)
    if not setup:
        await update.message.reply_text("⚠️ Koi setup nahi hai. `/setup` se set karo.", parse_mode="Markdown")
        return
    await update.message.reply_text(
        f"📋 *Current Setup:*\n\n🎌 *Anime:* `{setup['slug']}`\n📺 *Season:* `{setup['season']}`",
        parse_mode="Markdown",
    )


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return

    msg = update.message
    uid = update.effective_user.id
    file_obj = None
    raw_name = ""

    if msg.video:
        file_obj = msg.video
        raw_name = msg.video.file_name or ""
    elif msg.document:
        file_obj = msg.document
        raw_name = msg.document.file_name or ""
    elif msg.audio:
        file_obj = msg.audio
        raw_name = msg.audio.file_name or ""
    elif msg.video_note:
        file_obj = msg.video_note
        raw_name = ""
    else:
        await msg.reply_text("❌ Sirf video, document, ya audio files bhejein.")
        return

    caption_text = msg.caption or ""
    ep_num = extract_episode(caption_text)
    if ep_num is None and raw_name:
        ep_num = extract_episode(raw_name)

    setup = user_setup.get(uid)

    if setup:
        if ep_num is None:
            await msg.reply_text(
                "⚠️ *Episode number nahi mila!*\n\n"
                "Caption mein episode number likhna zaroori hai.\n"
                "*Supported formats:*\n`Episode 7` | `Ep 01` | `EP-12` | `E07`\n\n"
                "_Video forward karte waqt caption mein likho._",
                parse_mode="Markdown",
            )
            return

        ext = get_extension(raw_name, fallback="mp4" if (msg.video or msg.video_note) else "mkv")
        file_size = file_obj.file_size or 0
        processing = await msg.reply_text("⏳ Processing...")

        try:
            forwarded = await context.bot.copy_message(
                chat_id=STORAGE_CHANNEL,
                from_chat_id=msg.chat_id,
                message_id=msg.message_id,
            )
            storage_msg_id = forwarded.message_id

            if uid not in quality_buffer:
                quality_buffer[uid] = {}
            if ep_num not in quality_buffer[uid]:
                quality_buffer[uid][ep_num] = []

            quality_buffer[uid][ep_num].append({
                "size": file_size,
                "sid":  storage_msg_id,
                "ext":  ext,
            })

            collected = len(quality_buffer[uid][ep_num])
            await processing.delete()

            if collected < QUALITY_COUNT:
                remaining = QUALITY_COUNT - collected
                await msg.reply_text(
                    f"✅ *Video {collected}/{QUALITY_COUNT} mila!*\n\n"
                    f"🎬 *Episode:* `E{ep_num}`\n"
                    f"📦 *Size:* {round(file_size/(1024*1024), 2)} MB\n\n"
                    f"⏳ Abhi aur *{remaining}* video{'s' if remaining > 1 else ''} bhejo is episode ke liye...",
                    parse_mode="Markdown",
                )
                return

            videos = quality_buffer[uid][ep_num]
            quality_map = assign_qualities(videos)

            results = []
            for i, vid in enumerate(videos):
                quality = quality_map[i]
                filename = f"{setup['slug']}-{setup['season']}-E{ep_num}-{quality}.{vid['ext']}"
                stream_link = make_stream_link(vid["sid"], filename)
                download_link = make_download_link(vid["sid"], filename)
                fb_saved = await save_to_firebase(setup["slug"], setup["season"], ep_num, stream_link, quality, download_link)
                results.append({
                    "quality": quality,
                    "link":    stream_link,
                    "dl_link": download_link,
                    "size_mb": round(vid["size"] / (1024*1024), 2),
                    "saved":   fb_saved,
                })

            del quality_buffer[uid][ep_num]

            quality_lines = "\n".join([
                f"  {'✅' if r['saved'] else '⚠️'} *{r['quality']}* — {r['size_mb']} MB\n"
                f"  ▶️ Stream: `{r['link']}`\n"
                f"  ⬇️ Download: `{r['dl_link']}`"
                for r in sorted(results, key=lambda x: x["quality"], reverse=True)
            ])

            await msg.reply_text(
                f"🎉 *Teeno Quality Save Ho Gayi!*\n\n"
                f"🎌 *Anime:* `{setup['slug']}`\n"
                f"📺 *Season:* `{setup['season']}`\n"
                f"🎬 *Episode:* `E{ep_num}`\n"
                f"📅 *Added Today:* ✅\n\n"
                f"🔗 *Links:*\n{quality_lines}",
                parse_mode="Markdown",
            )

        except Exception as e:
            logger.error(f"handle_media error: {e}")
            await msg.reply_text(f"❌ Error: {e}")

    else:
        filename = raw_name or f"video_{file_obj.file_unique_id}.mp4"
        processing = await msg.reply_text("⏳ Processing...")
        try:
            forwarded = await context.bot.copy_message(
                chat_id=STORAGE_CHANNEL,
                from_chat_id=msg.chat_id,
                message_id=msg.message_id,
            )
            storage_msg_id = forwarded.message_id
            stream_link = make_stream_link(storage_msg_id, filename)
            download_link = make_download_link(storage_msg_id, filename)
            file_size_mb = round(file_obj.file_size / (1024 * 1024), 2) if file_obj.file_size else "?"
            await processing.delete()
            await msg.reply_text(
                f"✅ *File Saved!*\n\n"
                f"📁 *File:* `{filename}`\n"
                f"📦 *Size:* {file_size_mb} MB\n"
                f"🆔 *Storage ID:* `{storage_msg_id}`\n\n"
                f"▶️ *Stream Link:*\n`{stream_link}`\n\n"
                f"⬇️ *Download Link:*\n`{download_link}`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("▶️ Stream", url=stream_link)],
                    [InlineKeyboardButton("⬇️ Download", url=download_link)],
                ]),
            )
        except Exception as e:
            logger.error(f"handle_media error: {e}")
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


# ── TELEGRAM BOT APPLICATION (global) ─────────────────
tg_app = Application.builder().token(BOT_TOKEN).build()

tg_app.add_handler(CommandHandler("start",       start))
tg_app.add_handler(CommandHandler("setup",       setup_cmd))
tg_app.add_handler(CommandHandler("mysetup",     current_setup_cmd))
tg_app.add_handler(CommandHandler("clearsetup",  clear_setup_cmd))
tg_app.add_handler(CommandHandler("getlink",     get_link_cmd))
tg_app.add_handler(MessageHandler(
    filters.VIDEO | filters.Document.ALL | filters.AUDIO | filters.VIDEO_NOTE,
    handle_media,
))


# ── FASTAPI LIFESPAN ──────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global pyro

    # Pyrogram start karo (file streaming ke liye)
    pyro = Client(
        "stream_session",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        in_memory=True,
    )
    await pyro.start()
    logger.info("Pyrogram client started.")

    # PTB bot initialize karo (webhook ke liye)
    await tg_app.initialize()
    await tg_app.start()
    logger.info("PTB bot initialized.")

    # Webhook set karo Telegram pe (sirf HF Spaces pe)
    if BASE_URL and BASE_URL != "http://localhost:8000":
        webhook_url = f"{BASE_URL.rstrip('/')}/webhook"
        await tg_app.bot.set_webhook(
            url=webhook_url,
            allowed_updates=Update.ALL_TYPES,
        )
        logger.info(f"✅ Webhook set: {webhook_url}")
    else:
        logger.warning("⚠️ BASE_URL localhost hai — webhook set nahi hua. HF Spaces pe BASE_URL env var zaroori hai.")

    yield  # Server yahan chalta hai

    # Cleanup
    await tg_app.stop()
    await tg_app.shutdown()
    await pyro.stop()
    logger.info("Bot aur Pyrogram band ho gaye.")


# ── FASTAPI APP ───────────────────────────────────────

web_app = FastAPI(title="TG Stream Server", lifespan=lifespan)


@web_app.get("/")
async def index():
    return HTMLResponse("""
    <html><body style='font-family:sans-serif;text-align:center;padding:80px;background:#0f0f0f;color:#fff'>
    <h1>🎬 TG Stream Server</h1><p style='color:#aaa'>Online ✅</p>
    </body></html>
    """)


# ── WEBHOOK ENDPOINT (polling ki jagah) ───────────────

@web_app.post("/webhook")
async def telegram_webhook(request: Request):
    """Telegram updates yahan aayenge — polling nahi, webhook se"""
    try:
        data = await request.json()
        update = Update.de_json(data, tg_app.bot)
        await tg_app.process_update(update)
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
    return {"ok": True}


@web_app.get("/watch/{msg_id}/{filename:path}")
async def watch_file(msg_id: int, filename: str, code: str):
    decoded = urllib.parse.unquote(filename)
    if not verify_code(msg_id, decoded, code):
        raise HTTPException(status_code=403, detail="Invalid or expired link.")

    stream_url = f"/dl/{msg_id}/{urllib.parse.quote(decoded)}?code={code}"
    safe_title = decoded.replace('"', '&quot;')

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{safe_title}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box }}
  body {{ background:#000; display:flex; flex-direction:column; align-items:center;
          justify-content:center; min-height:100vh; font-family:sans-serif; color:#fff }}
  video {{ width:100%; max-width:960px; max-height:90vh; background:#000 }}
  .title {{ margin-top:12px; font-size:14px; color:#aaa; max-width:960px;
             white-space:nowrap; overflow:hidden; text-overflow:ellipsis; padding:0 12px }}
</style>
</head>
<body>
<video src="{stream_url}" controls autoplay preload="auto" playsinline controlslist="nodownload"></video>
<div class="title">{safe_title}</div>
</body>
</html>"""
    return HTMLResponse(html)


@web_app.get("/dl/{msg_id}/{filename:path}")
async def stream_file(msg_id: int, filename: str, code: str, request: Request, dl: int = 0):
    decoded = urllib.parse.unquote(filename)

    if not verify_code(msg_id, decoded, code):
        raise HTTPException(status_code=403, detail="Invalid or expired link.")

    try:
        message = await pyro.get_messages(STORAGE_CHANNEL, msg_id)
    except FloodWait as e:
        await asyncio.sleep(e.x)
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
    CHUNK_SIZE = 2 * 1024 * 1024

    range_header = request.headers.get("range")
    start = 0
    end = file_size - 1

    if range_header:
        parts = range_header.replace("bytes=", "").split("-")
        start = int(parts[0]) if parts[0] else 0
        end   = int(parts[1]) if parts[1] else file_size - 1

    content_length  = end - start + 1
    offset          = start // CHUNK_SIZE
    first_chunk_cut = start % CHUNK_SIZE
    limit           = math.ceil(content_length / CHUNK_SIZE)
    safe_filename   = urllib.parse.quote(decoded)

    response_headers = {
        "Content-Type":               mime_type,
        "Accept-Ranges":              "bytes",
        "Content-Disposition":        f"{'attachment' if dl else 'inline'}; filename*=UTF-8''{safe_filename}",
        "Content-Length":             str(content_length),
        "Cache-Control":              "no-store",
        "Access-Control-Allow-Origin":   "*",
        "Access-Control-Allow-Headers":  "Range, Content-Type",
        "Access-Control-Expose-Headers": "Content-Range, Accept-Ranges, Content-Length",
    }
    if range_header:
        response_headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"

    async def generator():
        bytes_sent  = 0
        chunk_index = 0
        try:
            async for chunk in pyro.stream_media(message, offset=offset, limit=limit):
                if chunk_index == 0:
                    chunk = chunk[first_chunk_cut:]
                remaining = content_length - bytes_sent
                if len(chunk) > remaining:
                    chunk = chunk[:remaining]
                yield chunk
                bytes_sent  += len(chunk)
                chunk_index += 1
                if bytes_sent >= content_length:
                    break
        except Exception as e:
            logger.error(f"Stream error msg_id={msg_id}: {e}")

    status_code = 206 if range_header else 200
    logger.info(f"Streaming msg_id={msg_id} | {decoded} | bytes {start}-{end}/{file_size}")
    return StreamingResponse(generator(), status_code=status_code, headers=response_headers)


# ── ENTRY POINT ───────────────────────────────────────

if __name__ == "__main__":
    import sys
    if sys.platform != "win32":
        try:
            import uvloop
            asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        except ImportError:
            pass
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    config = uvicorn.Config(web_app, host="0.0.0.0", port=PORT, log_level="info", loop="asyncio")
    server = uvicorn.Server(config)
    loop.run_until_complete(server.serve())
