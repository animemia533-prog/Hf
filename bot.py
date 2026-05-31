import os
import re
import base64
import asyncio
import aiohttp
import logging
from pyrogram import Client, filters
from pyrogram.types import Message

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

BOT_TOKEN   = os.getenv("BOT_TOKEN", "")
API_ID      = int(os.getenv("API_ID", "0"))
API_HASH    = os.getenv("API_HASH", "")
SERVER_URL  = os.getenv("SERVER_URL", "")
VOE_API_KEY = os.getenv("VOE_API_KEY", "")
FIREBASE_URL = os.getenv("FIREBASE_URL", "")  # e.g. https://animeverse-9eada-default-rtdb.firebaseio.com

bot = Client(
    "anime_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True
)

# User ka current setup store karo (memory mein)
# { user_id: { "anime": "naruto", "season": 1 } }
user_setup: dict = {}

def encode(file_id: str) -> str:
    return base64.urlsafe_b64encode(file_id.encode()).decode().rstrip("=")

def extract_episode(caption: str) -> str | None:
    """Caption mein se episode number dhundho"""
    if not caption:
        return None
    # Match: 01, 1, 03, 3, 12, 75 — pure numbers
    match = re.search(r'\b(\d{1,3})\b', caption)
    if match:
        ep = int(match.group(1))
        return f"E{ep:02d}"  # E01, E03, E12
    return None

async def voe_remote_upload(stream_url: str) -> str | None:
    """VOE pe remote upload karo aur embed link wapas lo"""
    try:
        async with aiohttp.ClientSession() as session:
            # Step 1: Remote upload start karo
            upload_url = f"https://voe.sx/api/upload/url?key={VOE_API_KEY}&url={stream_url}"
            async with session.get(upload_url) as resp:
                data = await resp.json()
                if not data.get("status"):
                    logging.error(f"VOE upload failed: {data}")
                    return None
                
                file_code = data.get("file_code") or (data.get("result", {}) or {}).get("file_code")
                if not file_code:
                    # Poll karo agar async upload hai
                    return await voe_poll_upload(session, data)
                
                return f"https://voe.sx/e/{file_code}"
    except Exception as e:
        logging.error(f"VOE error: {e}")
        return None

async def voe_poll_upload(session, initial_data) -> str | None:
    """VOE async upload ka wait karo"""
    try:
        poll_url = f"https://voe.sx/api/upload/url/status?key={VOE_API_KEY}"
        for _ in range(30):  # 5 minute tak try karo
            await asyncio.sleep(10)
            async with session.get(poll_url) as resp:
                data = await resp.json()
                results = data.get("result", [])
                for item in results:
                    if item.get("status") == "200":
                        fc = item.get("file_code")
                        if fc:
                            return f"https://voe.sx/e/{fc}"
    except Exception as e:
        logging.error(f"VOE poll error: {e}")
    return None

async def firebase_save(anime: str, season: int, episode: str, voe_link: str):
    """Firebase Realtime DB mein save karo"""
    try:
        import time
        path = f"Animes/{anime}/S{season}/{episode}.json"
        url  = f"{FIREBASE_URL}/{path}"
        payload = {
            "link": voe_link,
            "server": "VOE",
            "time": int(time.time())
        }
        async with aiohttp.ClientSession() as session:
            async with session.put(url, json=payload) as resp:
                if resp.status == 200:
                    logging.info(f"Firebase saved: {path}")
                    return True
                else:
                    logging.error(f"Firebase error: {resp.status}")
                    return False
    except Exception as e:
        logging.error(f"Firebase error: {e}")
        return False

# ── Commands ─────────────────────────────────────────────────────────────────

@bot.on_message(filters.command("start"))
async def cmd_start(client, msg: Message):
    await msg.reply_text(
        "🎬 **Anime Upload Bot**\n\n"
        "**Setup karo:**\n"
        "`/setup anime-slug season`\n"
        "Example: `/setup naruto 1`\n\n"
        "**Phir videos forward karo** — caption mein episode number hona chahiye\n"
        "Example caption: `01`, `Episode 3`, `12`\n\n"
        "**Current setup dekhne ke liye:** `/status`"
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
        await msg.reply_text("❌ Season number hona chahiye, jaise: `/setup naruto 1`")
        return
    
    user_setup[msg.from_user.id] = {"anime": anime_slug.lower(), "season": season}
    await msg.reply_text(
        f"✅ **Setup ho gaya!**\n\n"
        f"📺 Anime: `{anime_slug}`\n"
        f"📁 Season: `S{season}`\n\n"
        f"Ab videos forward karo — caption mein episode number likhna!"
    )

@bot.on_message(filters.command("status"))
async def cmd_status(client, msg: Message):
    setup = user_setup.get(msg.from_user.id)
    if not setup:
        await msg.reply_text("⚠️ Koi setup nahi hai.\n`/setup anime-slug season` se shuru karo.")
    else:
        await msg.reply_text(
            f"📌 **Current Setup:**\n\n"
            f"📺 Anime: `{setup['anime']}`\n"
            f"📁 Season: `S{setup['season']}`"
        )

@bot.on_message(filters.video | filters.document)
async def handle_video(client, msg: Message):
    # Setup check
    setup = user_setup.get(msg.from_user.id)
    if not setup:
        await msg.reply_text("⚠️ Pehle `/setup anime-slug season` karo!")
        return

    # File check
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

    # Episode number caption se dhundho
    caption = msg.caption or file_name or ""
    episode = extract_episode(caption)
    if not episode:
        await msg.reply_text(
            f"⚠️ Episode number nahi mila!\n"
            f"Caption mein number hona chahiye jaise: `01`, `1`, `12`\n"
            f"File name: `{file_name}`"
        )
        return

    anime  = setup["anime"]
    season = setup["season"]

    status_msg = await msg.reply_text(
        f"⏳ Processing...\n\n"
        f"📺 `{anime}` → S{season} → {episode}\n"
        f"🔗 Streaming link bana raha hoon..."
    )

    # Streaming link banao
    enc = encode(file_id)
    stream_url = f"{SERVER_URL}/{enc}"

    # VOE pe upload karo
    await status_msg.edit_text(
        f"⏳ VOE pe upload ho raha hai...\n\n"
        f"📺 `{anime}` → S{season} → {episode}"
    )

    voe_link = await voe_remote_upload(stream_url)

    if not voe_link:
        await status_msg.edit_text(
            f"❌ VOE upload fail hua!\n\n"
            f"📺 `{anime}` → S{season} → {episode}\n"
            f"🔗 Streaming link:\n`{stream_url}`"
        )
        return

    # Firebase mein save karo
    await status_msg.edit_text(f"💾 Firebase mein save ho raha hai...")
    saved = await firebase_save(anime, season, episode, voe_link)

    if saved:
        await status_msg.edit_text(
            f"✅ **Done!**\n\n"
            f"📺 Anime: `{anime}`\n"
            f"📁 Path: `S{season}/{episode}`\n\n"
            f"🎬 VOE Link:\n`{voe_link}`\n\n"
            f"💾 Firebase: `Animes/{anime}/S{season}/{episode}`"
        )
    else:
        await status_msg.edit_text(
            f"⚠️ **VOE done, Firebase fail!**\n\n"
            f"🎬 VOE Link:\n`{voe_link}`\n\n"
            f"Manually save karo: `Animes/{anime}/S{season}/{episode}`"
        )

if __name__ == "__main__":
    print("🤖 Anime Bot start!")
    bot.run()
