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
from fastapi.middleware.cors import CORSMiddleware
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

message_cache: dict = {}
MESSAGE_CACHE_LIMIT = 50

user_setup: dict = {}

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


def make_embed_link(msg_id, filename):
    safe = urllib.parse.quote(filename)
    code = generate_code(msg_id, filename)
    return f"{BASE_URL}/watch/{msg_id}/{safe}?code={code}"


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


async def copy_with_floodwait(context, chat_id, from_chat_id, message_id, max_retries=10):
    for attempt in range(max_retries):
        try:
            return await context.bot.copy_message(
                chat_id=chat_id,
                from_chat_id=from_chat_id,
                message_id=message_id,
            )
        except FloodWait as e:
            logger.warning(f"FloodWait: {e.x}s wait (attempt {attempt+1})")
            await asyncio.sleep(e.x + 1)
        except Exception as e:
            err_str = str(e)
            m = re.search(r'(?:flood|retry).*?(\d+)\s*sec', err_str, re.IGNORECASE)
            if m:
                wait_s = int(m.group(1))
                await asyncio.sleep(wait_s + 1)
                continue
            raise
    raise RuntimeError("Max retries exceeded for copy_message.")


async def save_to_firebase_with_retry(slug, season, ep_num, stream_link, quality=None, download_link=None, max_retries=10):
    for attempt in range(max_retries):
        try:
            return await save_to_firebase(slug, season, ep_num, stream_link, quality, download_link)
        except FloodWait as e:
            await asyncio.sleep(e.x + 1)
    return False


def get_extension(filename: str, fallback: str = "mp4") -> str:
    if filename and "." in filename:
        return filename.rsplit(".", 1)[-1].lower()
    return fallback


async def save_to_firebase(slug, season, ep_num, stream_link, quality=None, download_link=None):
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
                    logger.error(f"Firebase error {resp.status}: {await resp.text()}")
                    return False

            if quality is None or quality == "1080p":
                url2 = f"{db_url}/added_today/{date_str}/{slug}.json"
                payload2 = {"e": ep_num, "s": season_num, "timestamp": now_ts}
                async with session.put(url2, json=payload2) as resp:
                    if resp.status != 200:
                        logger.warning(f"added_today failed {resp.status}")
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
            "*Examples:*\n"
            "`/setup attack-on-titan 1`\n"
            "`/setup mushoku-tensei 2`",
            parse_mode="Markdown",
        )
        return
    slug = args[0].lower().strip()
    raw_season = args[1].strip()
    season = f"S{raw_season}" if raw_season.isdigit() else raw_season.upper()
    user_setup[update.effective_user.id] = {"slug": slug, "season": season}
    await update.message.reply_text(
        f"✅ *Setup Saved!*\n\n"
        f"🎌 *Anime Slug:* `{slug}`\n"
        f"📺 *Season:* `{season}`\n\n"
        f"Ab video forward karo!",
        parse_mode="Markdown",
    )


async def clear_setup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    uid = update.effective_user.id
    user_setup.pop(uid, None)
    quality_buffer.pop(uid, None)
    await update.message.reply_text("🗑️ Setup clear ho gaya.", parse_mode="Markdown")


async def current_setup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    setup = user_setup.get(update.effective_user.id)
    if not setup:
        await update.message.reply_text("⚠️ Koi setup nahi hai. `/setup` se set karo.", parse_mode="Markdown")
        return
    await update.message.reply_text(
        f"📋 *Current Setup:*\n\n"
        f"🎌 *Anime:* `{setup['slug']}`\n"
        f"📺 *Season:* `{setup['season']}`",
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
                "*Supported:* `Episode 7` | `Ep 01` | `EP-12` | `E07`",
                parse_mode="Markdown",
            )
            return

        ext = get_extension(raw_name, fallback="mp4" if (msg.video or msg.video_note) else "mkv")
        file_size = file_obj.file_size or 0

        if ext == "mkv":
            await msg.reply_text(
                "⚠️ *MKV file detect hui!*\n\nMobile browsers mein play nahi hogi. MP4 use karo.",
                parse_mode="Markdown",
            )

        processing = await msg.reply_text("⏳ Processing...")
        try:
            forwarded = await copy_with_floodwait(
                context, chat_id=STORAGE_CHANNEL,
                from_chat_id=msg.chat_id, message_id=msg.message_id,
            )
            storage_msg_id = forwarded.message_id

            if uid not in quality_buffer:
                quality_buffer[uid] = {}
            if ep_num not in quality_buffer[uid]:
                quality_buffer[uid][ep_num] = []

            quality_buffer[uid][ep_num].append({"size": file_size, "sid": storage_msg_id, "ext": ext})
            collected = len(quality_buffer[uid][ep_num])
            await processing.delete()

            if collected < QUALITY_COUNT:
                remaining = QUALITY_COUNT - collected
                await msg.reply_text(
                    f"✅ *Video {collected}/{QUALITY_COUNT} mila!*\n\n"
                    f"🎬 *Episode:* `E{ep_num}`\n"
                    f"📦 *Size:* {round(file_size/(1024*1024), 2)} MB\n\n"
                    f"⏳ Aur *{remaining}* video bhejo...",
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
                embed_link = make_embed_link(vid["sid"], filename)

                if vid.get("fb_saved"):
                    fb_saved = True
                else:
                    fb_saved = await save_to_firebase_with_retry(
                        setup["slug"], setup["season"], ep_num, stream_link, quality, download_link
                    )
                    vid["fb_saved"] = fb_saved

                results.append({
                    "quality": quality, "link": stream_link,
                    "dl_link": download_link, "embed_link": embed_link,
                    "size_mb": round(vid["size"] / (1024*1024), 2), "saved": fb_saved,
                })

            del quality_buffer[uid][ep_num]

            quality_lines = "\n".join([
                f"  {'✅' if r['saved'] else '⚠️'} *{r['quality']}* — {r['size_mb']} MB\n"
                f"  ▶️ Stream: `{r['link']}`\n"
                f"  🖼️ Embed: `{r['embed_link']}`\n"
                f"  ⬇️ Download: `{r['dl_link']}`"
                for r in sorted(results, key=lambda x: x["quality"], reverse=True)
            ])

            await msg.reply_text(
                f"🎉 *Teeno Quality Save Ho Gayi!*\n\n"
                f"🎌 *Anime:* `{setup['slug']}`\n"
                f"📺 *Season:* `{setup['season']}`\n"
                f"🎬 *Episode:* `E{ep_num}`\n\n"
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
            forwarded = await copy_with_floodwait(
                context, chat_id=STORAGE_CHANNEL,
                from_chat_id=msg.chat_id, message_id=msg.message_id,
            )
            storage_msg_id = forwarded.message_id
            stream_link = make_stream_link(storage_msg_id, filename)
            download_link = make_download_link(storage_msg_id, filename)
            embed_link = make_embed_link(storage_msg_id, filename)
            file_size_mb = round(file_obj.file_size / (1024*1024), 2) if file_obj.file_size else "?"
            await processing.delete()
            await msg.reply_text(
                f"✅ *File Saved!*\n\n"
                f"📁 *File:* `{filename}`\n"
                f"📦 *Size:* {file_size_mb} MB\n"
                f"🆔 *Storage ID:* `{storage_msg_id}`\n\n"
                f"▶️ *Stream:*\n`{stream_link}`\n\n"
                f"🖼️ *Embed:*\n`{embed_link}`\n\n"
                f"⬇️ *Download:*\n`{download_link}`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("▶️ Stream", url=stream_link)],
                    [InlineKeyboardButton("🖼️ Embed", url=embed_link)],
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
        embed_link = make_embed_link(msg_id, filename)
        dl_link = make_download_link(msg_id, filename)
        await update.message.reply_text(
            f"🔗 *Stream:*\n`{link}`\n\n"
            f"🖼️ *Embed:*\n`{embed_link}`\n\n"
            f"⬇️ *Download:*\n`{dl_link}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ Open", url=link)],
                [InlineKeyboardButton("🖼️ Embed", url=embed_link)],
            ]),
        )
    except ValueError:
        await update.message.reply_text("❌ Invalid message ID.")


# ── FASTAPI ───────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global pyro
    # ✅ FIX: in_memory=False — session disk pe save hogi /data/ mein
    # Railway mein Volume mount karo: /data
    SESSION_PATH = os.getenv("SESSION_PATH", "/data/stream_session")
    os.makedirs(os.path.dirname(SESSION_PATH), exist_ok=True)
    pyro = Client(
        SESSION_PATH,
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        no_updates=True,
        sleep_threshold=60,
        max_concurrent_transmissions=8,
    )
    await pyro.start()
    logger.info("Pyrogram client started.")
    yield
    await pyro.stop()


web_app = FastAPI(title="TG Stream Server", lifespan=lifespan)

web_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "HEAD", "OPTIONS"],
    allow_headers=["Range", "Content-Type", "Authorization"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length", "Content-Type"],
)


@web_app.get("/")
async def index():
    return HTMLResponse("""
    <html><body style='font-family:sans-serif;text-align:center;padding:80px;background:#0f0f0f;color:#fff'>
    <h1>🎬 TG Stream Server</h1><p style='color:#aaa'>Online ✅</p>
    </body></html>
    """)


@web_app.get("/watch/{msg_id}/{filename:path}")
async def watch_file(msg_id: int, filename: str, code: str):
    decoded = urllib.parse.unquote(filename)
    if not verify_code(msg_id, decoded, code):
        raise HTTPException(status_code=403, detail="Invalid or expired link.")

    stream_url = f"/dl/{msg_id}/{urllib.parse.quote(decoded)}?code={code}"
    safe_title = decoded.replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>{safe_title}</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/plyr/3.7.8/plyr.min.css">
<style>
  *, *::before, *::after {{ margin:0; padding:0; box-sizing:border-box }}
  html, body {{ background:#0a0a0a; min-height:100vh; display:flex; flex-direction:column;
    align-items:center; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
    color:#fff; overflow-x:hidden }}
  .player-wrapper {{ width:100%; max-width:960px; position:relative }}
  .plyr {{ width:100%; --plyr-color-main:#e50914; --plyr-video-background:#000 }}
  .title-bar {{ width:100%; max-width:960px; padding:10px 14px; font-size:13px; color:#888;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
    background:#111; border-top:1px solid #222 }}
  .status-bar {{ width:100%; max-width:960px; padding:8px 14px; font-size:12px;
    background:#0a0a0a; display:flex; gap:16px; flex-wrap:wrap }}
  .status-bar span {{ color:#777 }}
  .status-bar b {{ color:#aaa }}
  #error-msg {{ display:none; background:#1a0000; border:1px solid #600; color:#f66;
    padding:16px 20px; border-radius:8px; margin:20px; font-size:14px;
    text-align:center; max-width:600px }}
  #loading-overlay {{ position:absolute; top:0; left:0; right:0; bottom:0;
    background:#000; display:flex; flex-direction:column; align-items:center;
    justify-content:center; gap:12px; z-index:10; transition:opacity 0.3s }}
  .spinner {{ width:40px; height:40px; border:3px solid #333;
    border-top-color:#e50914; border-radius:50%;
    animation:spin 0.8s linear infinite }}
  @keyframes spin {{ to {{ transform:rotate(360deg) }} }}
  #loading-overlay p {{ color:#666; font-size:13px }}
  #loading-overlay.hidden {{ opacity:0; pointer-events:none }}
</style>
</head>
<body>
<div class="player-wrapper">
  <div id="loading-overlay">
    <div class="spinner"></div>
    <p>Loading video...</p>
  </div>
  <video id="player" playsinline controls crossorigin="anonymous">
    <source src="{stream_url}" type="video/mp4">
  </video>
</div>
<div class="title-bar">{safe_title}</div>
<div class="status-bar">
  <span>Status: <b id="st-status">Loading...</b></span>
  <span>Buffered: <b id="st-buf">0%</b></span>
  <span>Resolution: <b id="st-quality">—</b></span>
</div>
<div id="error-msg"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/plyr/3.7.8/plyr.min.js"></script>
<script>
(function() {{
  const videoEl = document.getElementById('player');
  const overlay = document.getElementById('loading-overlay');
  const errBox  = document.getElementById('error-msg');
  const stStatus  = document.getElementById('st-status');
  const stBuf     = document.getElementById('st-buf');
  const stQuality = document.getElementById('st-quality');

  const player = new Plyr('#player', {{
    controls: ['play-large','play','rewind','fast-forward','progress',
               'current-time','duration','mute','volume','settings','pip','fullscreen'],
    settings: ['speed'],
    speed: {{ selected:1, options:[0.5,0.75,1,1.25,1.5,2] }},
    keyboard: {{ focused:true, global:true }},
    fullscreen: {{ enabled:true, fallback:true, iosNative:true }},
    storage: {{ enabled:true, key:'plyr' }},
  }});

  function hideOverlay() {{
    overlay.classList.add('hidden');
    setTimeout(() => overlay.style.display = 'none', 300);
  }}

  videoEl.addEventListener('canplay', hideOverlay);
  videoEl.addEventListener('playing', () => {{
    hideOverlay();
    stStatus.textContent = '▶ Playing';
    stStatus.style.color = '#4caf50';
  }});
  videoEl.addEventListener('waiting', () => {{
    stStatus.textContent = '⏳ Buffering...';
    stStatus.style.color = '#ff9800';
  }});
  videoEl.addEventListener('pause', () => {{
    stStatus.textContent = '⏸ Paused';
    stStatus.style.color = '#aaa';
  }});
  videoEl.addEventListener('ended', () => {{
    stStatus.textContent = '✅ Ended';
    stStatus.style.color = '#888';
  }});
  videoEl.addEventListener('loadedmetadata', () => {{
    const w = videoEl.videoWidth, h = videoEl.videoHeight;
    if (w && h) stQuality.textContent = w + 'x' + h;
    stStatus.textContent = '✅ Ready';
    stStatus.style.color = '#4caf50';
  }});

  setInterval(() => {{
    if (!videoEl.buffered || !videoEl.buffered.length || !videoEl.duration) return;
    const buf = videoEl.buffered.end(videoEl.buffered.length - 1);
    stBuf.textContent = Math.round((buf / videoEl.duration) * 100) + '%';
  }}, 1000);

  let retries = 0;
  videoEl.addEventListener('error', function() {{
    const err = videoEl.error;
    const codes = {{1:'Aborted',2:'Network error',3:'Decode error',4:'Format not supported'}};
    const msg = err ? ('Error ' + err.code + ': ' + (codes[err.code] || 'Unknown')) : 'Load failed';
    if (retries < 3) {{
      retries++;
      stStatus.textContent = '🔄 Retrying (' + retries + '/3)...';
      stStatus.style.color = '#ff9800';
      setTimeout(() => {{
        const src = videoEl.querySelector('source').src.split('&_r=')[0];
        videoEl.querySelector('source').src = src + '&_r=' + Date.now();
        videoEl.load();
      }}, 2000 * retries);
    }} else {{
      overlay.style.display = 'none';
      errBox.style.display = 'block';
      errBox.innerHTML = '❌ <b>' + msg + '</b><br><br>'
        + '<a href="{stream_url}" style="color:#e50914">📥 Direct Stream Link</a>';
      stStatus.textContent = '❌ Error';
      stStatus.style.color = '#f44';
    }}
  }});

  window.addEventListener('orientationchange', () => {{
    if (Math.abs(window.orientation) === 90 && player.playing) player.fullscreen.enter();
  }});
}})();
</script>
</body>
</html>"""
    return HTMLResponse(html)


@web_app.get("/dl/{msg_id}/{filename:path}")
async def stream_file(msg_id: int, filename: str, code: str, request: Request, dl: int = 0):
    decoded = urllib.parse.unquote(filename)
    if not verify_code(msg_id, decoded, code):
        raise HTTPException(status_code=403, detail="Invalid or expired link.")

    if msg_id in message_cache:
        message = message_cache[msg_id]
    else:
        try:
            message = await pyro.get_messages(STORAGE_CHANNEL, msg_id)
            if len(message_cache) >= MESSAGE_CACHE_LIMIT:
                del message_cache[next(iter(message_cache))]
            message_cache[msg_id] = message
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
    mime_type = getattr(media, "mime_type", None)
    ext = decoded.rsplit(".", 1)[-1].lower() if "." in decoded else ""
    mime_map = {"mp4":"video/mp4","mkv":"video/x-matroska","webm":"video/webm",
                "avi":"video/x-msvideo","mov":"video/quicktime"}
    if not mime_type or mime_type == "application/octet-stream":
        mime_type = mime_map.get(ext, "video/mp4")

    CHUNK_SIZE = 1 * 1024 * 1024
    range_header = request.headers.get("range")
    start = 0
    end = file_size - 1

    if range_header:
        parts = range_header.replace("bytes=", "").split("-")
        start = int(parts[0]) if parts[0] else 0
        end   = int(parts[1]) if parts[1] else file_size - 1

    start = max(0, min(start, file_size - 1))
    end   = max(start, min(end, file_size - 1))
    content_length  = end - start + 1
    offset          = start // CHUNK_SIZE
    first_chunk_cut = start % CHUNK_SIZE
    limit           = math.ceil((content_length + first_chunk_cut) / CHUNK_SIZE)
    safe_filename   = urllib.parse.quote(decoded)

    response_headers = {
        "Content-Type":        mime_type,
        "Accept-Ranges":       "bytes",
        "Content-Disposition": f"{'attachment' if dl else 'inline'}; filename*=UTF-8''{safe_filename}",
        "Content-Length":      str(content_length),
        "Cache-Control":       "public, max-age=3600",
        "Access-Control-Allow-Origin":   "*",
        "Access-Control-Allow-Headers":  "Range, Content-Type",
        "Access-Control-Expose-Headers": "Content-Range, Accept-Ranges, Content-Length",
    }
    if range_header:
        response_headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"

    async def generator():
        bytes_sent = 0
        chunk_index = 0
        try:
            async for chunk in pyro.stream_media(message, offset=offset, limit=limit):
                if chunk_index == 0:
                    chunk = chunk[first_chunk_cut:]
                remaining = content_length - bytes_sent
                if remaining <= 0:
                    break
                if len(chunk) > remaining:
                    chunk = chunk[:remaining]
                if chunk:
                    yield chunk
                    bytes_sent += len(chunk)
                chunk_index += 1
                if bytes_sent >= content_length:
                    break
        except Exception as e:
            logger.error(f"Stream error msg_id={msg_id}: {e}")
        if bytes_sent < content_length:
            yield b"\x00" * (content_length - bytes_sent)

    status_code = 206 if range_header else 200
    logger.info(f"Streaming msg_id={msg_id} | {decoded} | bytes {start}-{end}/{file_size}")
    return StreamingResponse(generator(), status_code=status_code, headers=response_headers)


# ── MAIN ──────────────────────────────────────────────

async def run_bot():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",      start))
    app.add_handler(CommandHandler("setup",      setup_cmd))
    app.add_handler(CommandHandler("mysetup",    current_setup_cmd))
    app.add_handler(CommandHandler("clearsetup", clear_setup_cmd))
    app.add_handler(CommandHandler("getlink",    get_link_cmd))
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
        await asyncio.gather(run_server())
    finally:
        await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())