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

BOT_TOKEN      = os.getenv("BOT_TOKEN", "")
API_ID         = int(os.getenv("API_ID", "0"))
API_HASH       = os.getenv("API_HASH", "")
SERVER_URL     = os.getenv("SERVER_URL", "")
FIREBASE_URL   = os.getenv("FIREBASE_URL", "")
STRING_SESSION = os.getenv("STRING_SESSION", "")

# Userbot — Saved Messages mein copy ke liye
userbot = Client(
    "userbot_copy",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=STRING_SESSION,
    no_updates=True,
)

# Bot — messages receive karne ke liye
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

async def firebase_save(anime, season, episode, stream_link, chat_id, message_id) -> bool:
    try:
        payload = {
            "link": stream_link,
            "server": "Player1",
            "time": int(time.time()),
            "chat_id": chat_id,
            "message_id": message_id
        }
        async with aiohttp.ClientSession() as s:
            async with s.put(
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
        "Videos forward karo — caption mein number: `01`, `7`, `12`"
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
    await msg.reply_text(f"✅ `{parts[1]}` › S{season} — Ab forward karo!")

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
        await msg.reply_text("⚠️ Episode number nahi mila! Caption mein `01`, `7`, `12` likho")
        return

    anime  = setup["anime"]
    season = setup["season"]

    status = await msg.reply_text(
        f"⏳ Saved Messages mein copy ho raha hai...\n"
        f"📺 `{anime}` › S{season} › {episode}"
    )

    try:
        # Userbot se Saved Messages mein forward karo
        saved = await userbot.forward_messages(
            chat_id="me",
            from_chat_id=msg.chat.id,
            message_ids=msg.id
        )

        saved_file_id = None
        if saved.video:
            saved_file_id = saved.video.file_id
        elif saved.document:
            saved_file_id = saved.document.file_id

        if saved_file_id:
            enc         = encode(saved_file_id)
            stream_link = f"{SERVER_URL}/{enc}"
            s_chat_id   = saved.chat.id
            s_msg_id    = saved.id
        else:
            raise Exception("file_id nahi mila")

    except Exception as e:
        logging.error(f"Saved Messages forward error: {e}")
        # Fallback — original use karo
        enc         = encode(file_id)
        stream_link = f"{SERVER_URL}/{enc}"
        s_chat_id   = msg.chat.id
        s_msg_id    = msg.id

    ok = await firebase_save(anime, season, episode, stream_link, s_chat_id, s_msg_id)

    await status.edit_text(
        f"✅ **Done!**\n\n"
        f"📺 `{anime}` › S{season} › {episode}\n\n"
        f"🔗 `{stream_link}`\n\n"
        f"{'💾 Firebase ✅' if ok else '⚠️ Firebase fail!'}"
    )

async def main():
    # Dono clients ek hi loop mein start karo
    await userbot.start()
    print("✅ Userbot ready!")

    await bot.start()
    print("🤖 Bot start!")

    # Dono ko tab tak chalate raho jab tak manually band na ho
    await asyncio.gather(
        userbot.idle(),
        bot.idle(),
    )

if __name__ == "__main__":
    asyncio.run(main())
