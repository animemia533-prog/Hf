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

BOT_TOKEN       = os.getenv("BOT_TOKEN", "")
API_ID          = int(os.getenv("API_ID", "0"))
API_HASH        = os.getenv("API_HASH", "")
SERVER_URL      = os.getenv("SERVER_URL", "")
FIREBASE_URL    = os.getenv("FIREBASE_URL", "")
STORAGE_CHANNEL = int(os.getenv("STORAGE_CHANNEL", "0"))

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
    t = text.upper()
    m = re.search(r'\bEP(?:ISODE)?\s*[-:→►\s]*\s*(\d{1,3})\b', t)
    if m:
        return f"E{int(m.group(1)):02d}"
    m = re.search(r'\bE(\d{1,3})\b', t)
    if m:
        return f"E{int(m.group(1)):02d}"
    cleaned = re.sub(r'\bS\d{1,2}\b', '', t)
    nums = re.findall(r'\b(\d{1,3})\b', cleaned)
    if nums:
        return f"E{int(nums[0]):02d}"
    return None

async def firebase_save(anime, season, episode, stream_link, chat_id, message_id) -> bool:
    try:
        payload = {
            "link": stream_link,
            "server": "Player1",
            "time": int(time.time()),
            "chat_id": str(chat_id),
            "message_id": str(message_id)
        }
        async with aiohttp.ClientSession() as session:
            async with session.put(
                f"{FIREBASE_URL}/Animes/{anime}/S{season}/{episode}.json",
                json=payload
            ) as r:
                return r.status == 200
    except Exception as e:
        logging.error(f"Firebase: {e}")
        return False

@bot.on_message(filters.command("start"))
async def cmd_start(client, msg: Message):
    await msg.reply_text(
        "🎬 **Anime Upload Bot**\n\n"
        "`/setup anime-slug season`\n"
        "Example: `/setup naruto 1`\n\n"
        "Phir videos forward karo!\n"
        "Caption mein episode number: `01`, `7`, `12`"
    )

@bot.on_message(filters.command("setup"))
async def cmd_setup(client, msg: Message):
    parts = msg.text.split()
    if len(parts) != 3:
        await msg.reply_text("❌ `/setup anime-slug season`")
        return
    try:
        season = int(parts[2])
    except:
        await msg.reply_text("❌ Season number chahiye!")
        return
    user_setup[msg.from_user.id] = {"anime": parts[1].lower(), "season": season}
    await msg.reply_text(f"✅ `{parts[1]}` › S{season} — Forward karo!")

@bot.on_message(filters.command("status"))
async def cmd_status(client, msg: Message):
    setup = user_setup.get(msg.from_user.id)
    if not setup:
        await msg.reply_text("⚠️ `/setup anime-slug season` karo.")
    else:
        await msg.reply_text(f"📌 `{setup['anime']}` › S{setup['season']}")

@bot.on_message(filters.video | filters.document)
async def handle_video(client, msg: Message):
    setup = user_setup.get(msg.from_user.id)
    if not setup:
        await msg.reply_text("⚠️ Pehle `/setup anime-slug season` karo!")
        return

    file_name = "video.mp4"
    if msg.video:
        file_name = msg.video.file_name or "video.mp4"
    elif msg.document:
        if not (msg.document.mime_type or "").startswith("video"):
            return
        file_name = msg.document.file_name or "video.mp4"
    else:
        return

    episode = extract_episode(msg.caption or "")
    if not episode:
        episode = extract_episode(file_name)
    if not episode:
        await msg.reply_text(
            f"⚠️ Episode detect nahi hua!\n"
            f"Caption: `{(msg.caption or '')[:80]}`\n"
            f"Caption mein `Episode - 04` ya `E04` hona chahiye."
        )
        return

    anime  = setup["anime"]
    season = setup["season"]

    status = await msg.reply_text(
        f"⏳ Storage channel mein copy ho raha hai...\n"
        f"📺 `{anime}` › S{season} › {episode}"
    )

    # Video ko STORAGE_CHANNEL mein copy karo
    try:
        stored = await client.copy_message(
            chat_id      = STORAGE_CHANNEL,
            from_chat_id = msg.chat.id,
            message_id   = msg.id,
            caption      = f"🎌 {anime} | S{season} | {episode}"
        )
    except Exception as e:
        logging.error(f"copy_message error: {e}")
        await status.edit_text(
            f"❌ Storage channel mein copy nahi hua!\n"
            f"Error: `{e}`\n\n"
            f"✅ Check karo:\n"
            f"1. Bot ko `STORAGE_CHANNEL` ka **Admin** banao\n"
            f"2. `STORAGE_CHANNEL` env variable sahi hai?"
        )
        return

    stored_file = stored.video or stored.document
    if not stored_file:
        await status.edit_text("❌ Stored message mein file nahi mili!")
        return

    enc         = encode(stored_file.file_id)
    stream_link = f"{SERVER_URL}/{enc}"

    # STORAGE_CHANNEL ka chat_id + stored message_id Firebase mein save karo
    ok = await firebase_save(
        anime, season, episode,
        stream_link,
        STORAGE_CHANNEL,
        stored.id
    )

    await status.edit_text(
        f"✅ **Done!**\n\n"
        f"📺 `{anime}` › S{season} › {episode}\n\n"
        f"🔗 `{stream_link}`\n\n"
        f"{'💾 Firebase ✅' if ok else '⚠️ Firebase fail!'}"
    )

if __name__ == "__main__":
    print("🤖 Bot start!")
    bot.run()
