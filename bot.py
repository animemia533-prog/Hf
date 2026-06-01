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

BOT_TOKEN        = os.getenv("BOT_TOKEN", "")
API_ID           = int(os.getenv("API_ID", "0"))
API_HASH         = os.getenv("API_HASH", "")
SERVER_URL       = os.getenv("SERVER_URL", "")
FIREBASE_URL     = os.getenv("FIREBASE_URL", "")
STORAGE_CHANNEL  = int(os.getenv("STORAGE_CHANNEL_ID", "0"))  # Railway env se aayega

bot = Client(
    "anime_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True
)

user_setup: dict = {}

def encode(chat_id: int, message_id: int) -> str:
    """chat_id:message_id ko base64 mein encode karo"""
    raw = f"{chat_id}:{message_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")

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
            "link":       stream_link,
            "server":     "Player1",
            "time":       int(time.time()),
            "chat_id":    str(chat_id),
            "message_id": str(message_id)
        }
        async with aiohttp.ClientSession() as session:
            async with session.put(
                f"{FIREBASE_URL}/Animes/{anime}/S{season}/{episode}.json",
                json=payload
            ) as r:
                return r.status == 200
    except Exception as e:
        logging.error(f"Firebase error: {e}")
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
    await msg.reply_text(f"✅ `{parts[1]}` › S{season} — Ab videos forward karo!")

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

    # Sirf video files accept karo
    is_video = False
    if msg.video:
        is_video = True
    elif msg.document and (msg.document.mime_type or "").startswith("video"):
        is_video = True

    if not is_video:
        return

    episode = extract_episode(msg.caption or (msg.video.file_name if msg.video else None) or (msg.document.file_name if msg.document else None) or "")
    if not episode:
        await msg.reply_text("⚠️ Episode number nahi mila! Caption mein likho: `01`, `7`, `12`")
        return

    anime  = setup["anime"]
    season = setup["season"]

    # Step 1: Processing message
    processing = await msg.reply_text("⏳ Storage channel mein copy ho raha hai...")

    try:
        # Step 2: Bot video ko Storage Channel mein copy kare
        if STORAGE_CHANNEL == 0:
            await processing.edit_text("❌ STORAGE_CHANNEL_ID set nahi hai!")
            return

        copied = await client.copy_message(
            chat_id=STORAGE_CHANNEL,
            from_chat_id=msg.chat.id,
            message_id=msg.id
        )

        # Step 3: Storage channel ka chat_id aur message_id encode karo
        enc         = encode(STORAGE_CHANNEL, copied.id)
        stream_link = f"{SERVER_URL}/{enc}"

        # Step 4: Firebase mein storage channel info save karo
        ok = await firebase_save(
            anime, season, episode,
            stream_link,
            STORAGE_CHANNEL,   # <-- storage channel ka ID
            copied.id          # <-- copied message ka ID
        )

        await processing.edit_text(
            f"✅ **Done!**\n\n"
            f"📺 `{anime}` › S{season} › {episode}\n\n"
            f"📦 Storage Channel Message ID: `{copied.id}`\n"
            f"🔗 `{stream_link}`\n\n"
            f"{'💾 Firebase ✅' if ok else '⚠️ Firebase fail!'}"
        )

    except Exception as e:
        logging.error(f"Copy error: {e}")
        await processing.edit_text(f"❌ Copy failed: `{e}`\n\nBot ko Storage Channel mein admin banao!")

if __name__ == "__main__":
    print("🤖 Bot start!")
    bot.run()
