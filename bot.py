import os
import re
import base64
import asyncio
import aiohttp
import logging
import time
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

BOT_TOKEN    = os.getenv("BOT_TOKEN", "")
API_ID       = int(os.getenv("API_ID", "0"))
API_HASH     = os.getenv("API_HASH", "")
SERVER_URL   = os.getenv("SERVER_URL", "")
VOE_API_KEY  = os.getenv("VOE_API_KEY", "")
FIREBASE_URL = os.getenv("FIREBASE_URL", "")

bot = Client(
    "anime_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True
)

user_setup: dict = {}

def encode(file_id: str) -> str:
    return base64.urlsafe_b64encode(file_id.encode()).decode().rstrip("=")

def extract_episode(text: str) -> str | None:
    if not text:
        return None
    match = re.search(r'\b(\d{1,3})\b', text)
    if match:
        return f"E{int(match.group(1)):02d}"
    return None

def progress_bar(percent: int, length: int = 20) -> str:
    filled = int(length * percent / 100)
    return f"[{'█' * filled}{'░' * (length - filled)}] {percent}%"

async def voe_submit(download_url: str, filename: str = "video.mp4") -> tuple | None:
    try:
        async with aiohttp.ClientSession() as session:
            params = {"key": VOE_API_KEY, "url": download_url, "filename": filename}
            async with session.get("https://voe.sx/api/upload/url", params=params) as resp:
                data = await resp.json()
                logging.info(f"VOE submit: {data}")
                if not (data.get("success") or data.get("status") == 200):
                    logging.error(f"VOE error: {data}")
                    return None
                result = data.get("result") or {}
                fc = result.get("filecode") or result.get("file_code")
                if fc:
                    return ("done", fc)
                qid = data.get("queueID") or data.get("queue_id") or result.get("id")
                if qid:
                    return ("queued", str(qid))
    except Exception as e:
        logging.error(f"VOE submit error: {e}")
    return None

async def voe_poll(queue_id: str, status_msg, anime, season, episode) -> str | None:
    last_pct = -1
    for _ in range(120):
        await asyncio.sleep(10)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://voe.sx/api/upload/url/list?key={VOE_API_KEY}") as resp:
                    data = await resp.json()
                    items = (data.get("list") or {}).get("data", [])
                    item = next((i for i in items if str(i.get("id")) == queue_id), items[0] if items else None)
                    if not item:
                        continue
                    pct = int(item.get("percent") or 0)
                    fc  = item.get("file_code") or item.get("filecode")
                    if int(item.get("status") or 0) == 3 or (pct >= 100 and fc):
                        return fc
                    if pct != last_pct:
                        last_pct = pct
                        try:
                            await status_msg.edit_text(
                                f"📥 **VOE upload ho raha hai...**\n\n"
                                f"📺 `{anime}` › S{season} › {episode}\n\n"
                                f"{progress_bar(pct)}"
                            )
                        except:
                            pass
        except Exception as e:
            logging.error(f"Poll error: {e}")
    return None

async def firebase_save(anime, season, episode, voe_link) -> bool:
    try:
        payload = {"link": voe_link, "server": "VOE", "time": int(time.time())}
        async with aiohttp.ClientSession() as session:
            async with session.put(
                f"{FIREBASE_URL}/Animes/{anime}/S{season}/{episode}.json",
                json=payload
            ) as r:
                return r.status == 200
    except Exception as e:
        logging.error(f"Firebase error: {e}")
        return False

# ── Commands ──────────────────────────────────────────────────────────────────

@bot.on_message(filters.command("start"))
async def cmd_start(client, msg: Message):
    await msg.reply_text(
        "🎬 **Anime Upload Bot**\n\n"
        "`/setup anime-slug season`\n"
        "Example: `/setup naruto 1`\n\n"
        "Phir videos forward karo!\n"
        "Caption mein episode number: `01`, `7`, `12`\n\n"
        "`/status` — current setup"
    )

@bot.on_message(filters.command("setup"))
async def cmd_setup(client, msg: Message):
    parts = msg.text.split()
    if len(parts) != 3:
        await msg.reply_text("❌ Format: `/setup anime-slug season`\nExample: `/setup naruto 1`")
        return
    try:
        season = int(parts[2])
    except:
        await msg.reply_text("❌ Season number hona chahiye!")
        return
    user_setup[msg.from_user.id] = {"anime": parts[1].lower(), "season": season}
    await msg.reply_text(f"✅ **Setup!**\n📺 `{parts[1]}` › S{season}\n\nAb videos forward karo!")

@bot.on_message(filters.command("status"))
async def cmd_status(client, msg: Message):
    setup = user_setup.get(msg.from_user.id)
    if not setup:
        await msg.reply_text("⚠️ `/setup anime-slug season` karo pehle.")
    else:
        await msg.reply_text(f"📌 `{setup['anime']}` › S{setup['season']}")

@bot.on_message(filters.video | filters.document)
async def handle_video(client, msg: Message):
    setup = user_setup.get(msg.from_user.id)
    if not setup:
        await msg.reply_text("⚠️ Pehle `/setup anime-slug season` karo!")
        return

    file_id, file_name = None, "video.mp4"
    if msg.video:
        file_id   = msg.video.file_id
        file_name = msg.video.file_name or "video.mp4"
    elif msg.document and (msg.document.mime_type or "").startswith("video"):
        file_id   = msg.document.file_id
        file_name = msg.document.file_name or "video.mp4"
    if not file_id:
        return

    episode = extract_episode(msg.caption or file_name or "")
    if not episode:
        await msg.reply_text(
            f"⚠️ Episode number nahi mila!\n"
            f"Caption mein number hona chahiye: `01`, `7`, `12`"
        )
        return

    anime  = setup["anime"]
    season = setup["season"]
    enc    = encode(file_id)

    # Download URL — VOE ke liye
    download_url = f"{SERVER_URL}/download/{enc}"

    status_msg = await msg.reply_text(
        f"📤 **VOE pe bhej raha hoon...**\n\n"
        f"📺 `{anime}` › S{season} › {episode}\n\n"
        f"{progress_bar(0)}"
    )

    result = await voe_submit(download_url, file_name)
    if not result:
        await status_msg.edit_text(
            f"❌ VOE submit fail!\n\n"
            f"📺 `{anime}` › S{season} › {episode}\n"
            f"VOE API key check karo."
        )
        return

    kind, value = result
    file_code = value if kind == "done" else await voe_poll(value, status_msg, anime, season, episode)

    if not file_code:
        await status_msg.edit_text(f"❌ VOE timeout!\n📺 `{anime}` › S{season} › {episode}")
        return

    voe_link = f"https://voe.sx/e/{file_code}"
    await status_msg.edit_text(f"{progress_bar(100)}\n\n💾 Firebase save ho raha hai...")
    saved = await firebase_save(anime, season, episode, voe_link)

    await status_msg.edit_text(
        f"✅ **Done!**\n\n"
        f"📺 `{anime}` › S{season} › {episode}\n\n"
        f"🎬 `{voe_link}`\n\n"
        f"{'💾 Firebase ✅' if saved else '⚠️ Firebase fail!'}"
    )

if __name__ == "__main__":
    print("🤖 Anime Bot start!")
    bot.run()
