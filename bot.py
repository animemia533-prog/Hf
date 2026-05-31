import os
import re
import base64
import asyncio
import aiohttp
import logging
import time
from pyrogram import Client, filters
from pyrogram.types import Message

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

def extract_episode(caption: str) -> str | None:
    if not caption:
        return None
    match = re.search(r'\b(\d{1,3})\b', caption)
    if match:
        ep = int(match.group(1))
        return f"E{ep:02d}"
    return None

def progress_bar(percent: int, length: int = 20) -> str:
    """Black fill progress bar"""
    filled = int(length * percent / 100)
    empty  = length - filled
    bar    = "█" * filled + "░" * empty
    return f"[{bar}] {percent}%"

async def voe_remote_upload(stream_url: str) -> str | None:
    """VOE pe URL submit karo aur queue_id lo"""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://voe.sx/api/upload/url?key={VOE_API_KEY}&url={stream_url}"
            async with session.get(url) as resp:
                data = await resp.json()
                logging.info(f"VOE upload response: {data}")
                if data.get("success") or data.get("status") == 200:
                    # Direct file_code mila
                    result = data.get("result", {})
                    if isinstance(result, dict):
                        fc = result.get("filecode") or result.get("file_code")
                        if fc:
                            return ("done", fc)
                    # Queue ID mila
                    qid = data.get("queueID") or data.get("queue_id")
                    if qid:
                        return ("queued", str(qid))
                return None
    except Exception as e:
        logging.error(f"VOE submit error: {e}")
        return None

async def voe_check_status(queue_id: str) -> dict | None:
    """VOE upload list se status check karo"""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://voe.sx/api/upload/url/list?key={VOE_API_KEY}"
            async with session.get(url) as resp:
                data = await resp.json()
                items = (data.get("list") or {}).get("data", [])
                for item in items:
                    if str(item.get("id")) == str(queue_id):
                        return item
                # Agar queue_id match na ho toh latest item
                if items:
                    return items[0]
        return None
    except Exception as e:
        logging.error(f"VOE status error: {e}")
        return None

async def firebase_save(anime: str, season: int, episode: str, voe_link: str) -> bool:
    try:
        path = f"Animes/{anime}/S{season}/{episode}.json"
        url  = f"{FIREBASE_URL}/{path}"
        payload = {"link": voe_link, "server": "VOE", "time": int(time.time())}
        async with aiohttp.ClientSession() as session:
            async with session.put(url, json=payload) as resp:
                return resp.status == 200
    except Exception as e:
        logging.error(f"Firebase error: {e}")
        return False

# ── Commands ──────────────────────────────────────────────────────────────────

@bot.on_message(filters.command("start"))
async def cmd_start(client, msg: Message):
    await msg.reply_text(
        "🎬 **Anime Upload Bot**\n\n"
        "**Setup:** `/setup anime-slug season`\n"
        "Example: `/setup naruto 1`\n\n"
        "Phir videos forward karo — caption mein episode number hona chahiye\n"
        "**Status:** `/status`"
    )

@bot.on_message(filters.command("setup"))
async def cmd_setup(client, msg: Message):
    parts = msg.text.split()
    if len(parts) != 3:
        await msg.reply_text("❌ Format: `/setup anime-slug season`\nExample: `/setup naruto 1`")
        return
    _, anime_slug, season_str = parts
    try:
        season = int(season_str)
    except:
        await msg.reply_text("❌ Season number hona chahiye!")
        return
    user_setup[msg.from_user.id] = {"anime": anime_slug.lower(), "season": season}
    await msg.reply_text(
        f"✅ **Setup ho gaya!**\n\n"
        f"📺 Anime: `{anime_slug}`\n"
        f"📁 Season: `S{season}`\n\n"
        f"Ab videos forward karo!"
    )

@bot.on_message(filters.command("status"))
async def cmd_status(client, msg: Message):
    setup = user_setup.get(msg.from_user.id)
    if not setup:
        await msg.reply_text("⚠️ Koi setup nahi.\n`/setup anime-slug season` se shuru karo.")
    else:
        await msg.reply_text(
            f"📌 **Current Setup:**\n\n"
            f"📺 Anime: `{setup['anime']}`\n"
            f"📁 Season: `S{setup['season']}`"
        )

@bot.on_message(filters.video | filters.document)
async def handle_video(client, msg: Message):
    setup = user_setup.get(msg.from_user.id)
    if not setup:
        await msg.reply_text("⚠️ Pehle `/setup anime-slug season` karo!")
        return

    file_id = None
    file_name = "video.mp4"
    if msg.video:
        file_id = msg.video.file_id
        file_name = msg.video.file_name or "video.mp4"
    elif msg.document and msg.document.mime_type and msg.document.mime_type.startswith("video"):
        file_id = msg.document.file_id
        file_name = msg.document.file_name or "video.mp4"
    if not file_id:
        return

    caption  = msg.caption or file_name or ""
    episode  = extract_episode(caption)
    if not episode:
        await msg.reply_text(
            f"⚠️ Episode number nahi mila!\n"
            f"Caption mein number hona chahiye: `01`, `1`, `12`\n"
            f"File: `{file_name}`"
        )
        return

    anime  = setup["anime"]
    season = setup["season"]

    # ── Step 1: Submit to VOE ─────────────────────────────────────────────────
    status_msg = await msg.reply_text(
        f"📤 **VOE pe bhej raha hoon...**\n\n"
        f"📺 `{anime}` › S{season} › {episode}\n\n"
        f"{progress_bar(0)}"
    )

    enc        = encode(file_id)
    stream_url = f"{SERVER_URL}/{enc}"
    result     = await voe_remote_upload(stream_url)

    if not result:
        await status_msg.edit_text(
            f"❌ VOE submit fail!\n\n"
            f"📺 `{anime}` › S{season} › {episode}"
        )
        return

    kind, value = result

    # Agar seedha file_code mila — done!
    if kind == "done":
        voe_link = f"https://voe.sx/e/{value}"
        await status_msg.edit_text(f"{progress_bar(100)}\n\n💾 Firebase save ho raha hai...")
        saved = await firebase_save(anime, season, episode, voe_link)
        await status_msg.edit_text(
            f"✅ **Done!**\n\n"
            f"📺 `{anime}` › S{season} › {episode}\n\n"
            f"🎬 VOE Link:\n`{voe_link}`\n\n"
            f"{'💾 Firebase saved!' if saved else '⚠️ Firebase fail — manually save karo'}"
        )
        return

    # ── Step 2: Queue mein hai — poll karo ───────────────────────────────────
    queue_id = value
    await status_msg.edit_text(
        f"⏳ **VOE queue mein hai...**\n\n"
        f"📺 `{anime}` › S{season} › {episode}\n\n"
        f"{progress_bar(0)}\n\n"
        f"Queue ID: `{queue_id}`"
    )

    last_bar = -1
    file_code = None

    for attempt in range(120):  # Max 20 minute
        await asyncio.sleep(10)
        item = await voe_check_status(queue_id)

        if not item:
            continue

        percent   = int(item.get("percent") or 0)
        status_no = int(item.get("status") or 0)
        fc        = item.get("file_code") or item.get("filecode")

        # Status 3 = complete
        if status_no == 3 or percent >= 100:
            if fc:
                file_code = fc
            break

        # Bar sirf tab update karo jab change ho
        if percent != last_bar:
            last_bar = percent
            try:
                await status_msg.edit_text(
                    f"📥 **VOE download kar raha hai...**\n\n"
                    f"📺 `{anime}` › S{season} › {episode}\n\n"
                    f"{progress_bar(percent)}\n\n"
                    f"⚡ Speed: {item.get('speed') or 0} KB/s"
                )
            except:
                pass

    if not file_code:
        # List se dhundho agar poll se nahi mila
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://voe.sx/api/upload/url/list?key={VOE_API_KEY}"
                async with session.get(url) as resp:
                    data = await resp.json()
                    items = (data.get("list") or {}).get("data", [])
                    for i in items:
                        if str(i.get("id")) == str(queue_id) or int(i.get("percent", 0)) == 100:
                            file_code = i.get("file_code") or i.get("filecode")
                            break
        except:
            pass

    if not file_code:
        await status_msg.edit_text(
            f"❌ VOE upload timeout!\n\n"
            f"📺 `{anime}` › S{season} › {episode}\n"
            f"Queue ID: `{queue_id}`\n\n"
            f"VOE dashboard pe manually check karo."
        )
        return

    # ── Step 3: Firebase save ─────────────────────────────────────────────────
    voe_link = f"https://voe.sx/e/{file_code}"
    await status_msg.edit_text(
        f"{progress_bar(100)}\n\n"
        f"💾 Firebase mein save ho raha hai..."
    )
    saved = await firebase_save(anime, season, episode, voe_link)

    await status_msg.edit_text(
        f"✅ **Done!**\n\n"
        f"📺 `{anime}` › S{season} › {episode}\n\n"
        f"🎬 VOE Link:\n`{voe_link}`\n\n"
        f"{'💾 Firebase saved! ✅' if saved else '⚠️ Firebase fail — manually save karo'}"
    )

if __name__ == "__main__":
    print("🤖 Anime Bot start!")
    bot.run()
