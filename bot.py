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

def parse_episode(text: str) -> int | None:
    if not text:
        return None
    t = text.upper()
    m = re.search(r'\bEP(?:ISODE)?\s*[-:→►\s]*\s*(\d{1,3})\b', t)
    if m:
        return int(m.group(1))
    m = re.search(r'\bE(\d{1,3})\b', t)
    if m:
        return int(m.group(1))
    cleaned = re.sub(r'\bS\d{1,2}\b', '', t)
    nums = re.findall(r'\b(\d{1,3})\b', cleaned)
    if nums:
        return int(nums[0])
    return None

async def firebase_save(anime, season, episode, stream_link, message_id) -> bool:
    try:
        payload = {
            "link": stream_link,
            "server": "Player1",
            "time": int(time.time()),
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
        "Caption mein episode number hona chahiye."
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

    file_obj  = msg.video or msg.document
    file_size = file_obj.file_size or 0
    file_name = getattr(file_obj, "file_name", None) or "video.mp4"

    ep_num = parse_episode(msg.caption or "")
    if not ep_num:
        ep_num = parse_episode(file_name)
    if not ep_num:
        await msg.reply_text(
            f"⚠️ Episode detect nahi hua!\n"
            f"Caption: `{(msg.caption or '')[:80]}`\n"
            f"Caption mein `Episode - 04` ya `E04` hona chahiye."
        )
        return

    anime   = setup["anime"]
    season  = setup["season"]
    episode = f"E{ep_num:02d}"

    status = await msg.reply_text(
        f"⏳ Storage mein copy ho raha hai...\n"
        f"📺 `{anime}` › S{season} › {episode}"
    )

    try:
        stored = await client.copy_message(
            chat_id      = STORAGE_CHANNEL,
            from_chat_id = msg.chat.id,
            message_id   = msg.id,
            caption      = f"🎌 {anime}\n📺 S{season} | {episode}"
        )

        if stored is None:
            await status.edit_text("⏳ Copy nahi hua, forward try ho raha hai...")
            forwarded = await client.forward_messages(
                chat_id      = STORAGE_CHANNEL,
                from_chat_id = msg.chat.id,
                message_ids  = msg.id
            )
            stored = forwarded[0] if forwarded else None

        if stored is None:
            await status.edit_text(
                "❌ Forward bhi fail ho gaya!\n\n"
                "Check karo:\n"
                "1. Bot Storage Channel ka **Admin** hai?\n"
                "2. `STORAGE_CHANNEL` ID sahi hai?"
            )
            return

        stored_msg_id = stored.id

    except Exception as e:
        logging.error(f"Storage copy error: {e}")
        await status.edit_text(
            f"❌ Storage mein copy nahi hua!\n"
            f"Error: {e}\n\n"
            f"Bot ko Storage Channel ka **Admin** banao!"
        )
        return

    stored_file_id = None
    if stored.video:
        stored_file_id = stored.video.file_id
    elif stored.document:
        stored_file_id = stored.document.file_id

    if not stored_file_id:
        await status.edit_text("❌ Stored file_id nahi mila!")
        return

    enc         = encode(stored_file_id)
    stream_link = f"{SERVER_URL}/{enc}"

    ok = await firebase_save(anime, season, episode, stream_link, stored_msg_id)

    await status.edit_text(
        f"✅ **Done!**\n\n"
        f"📺 `{anime}` › S{season} › {episode}\n\n"
        f"🔗 `{stream_link}`\n\n"
        f"{'💾 Firebase ✅' if ok else '⚠️ Firebase fail!'}"
    )

if __name__ == "__main__":
    print("🤖 Bot start!")
    bot.run()
