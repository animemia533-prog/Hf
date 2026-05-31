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
upload_queue: asyncio.Queue = None

def encode(file_id: str) -> str:
    return base64.urlsafe_b64encode(file_id.encode()).decode().rstrip("=")

def extract_episode(caption: str) -> str | None:
    if not caption:
        return None
    match = re.search(r'\b(\d{1,3})\b', caption)
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
                logging.info(f"VOE: {data}")
                if not (data.get("success") or data.get("status") == 200):
                    return None
                result = data.get("result", {})
                fc = (result or {}).get("filecode") or (result or {}).get("file_code")
                if fc:
                    return ("done", fc)
                qid = data.get("queueID") or data.get("queue_id") or (result or {}).get("id")
                if qid:
                    return ("queued", str(qid))
    except Exception as e:
        logging.error(f"VOE submit: {e}")
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
            logging.error(f"Poll: {e}")
    return None

async def firebase_save(anime, season, episode, voe_link) -> bool:
    try:
        payload = {"link": voe_link, "server": "VOE", "time": int(time.time())}
        async with aiohttp.ClientSession() as session:
            async with session.put(f"{FIREBASE_URL}/Animes/{anime}/S{season}/{episode}.json", json=payload) as r:
                return r.status == 200
    except Exception as e:
        logging.error(f"Firebase: {e}")
        return False

async def process_video(msg, anime, season, episode, file_id, file_name):
    status_msg = await msg.reply_text(
        f"⏳ **Queue se utha raha hoon...**\n\n"
        f"📺 `{anime}` › S{season} › {episode}\n\n"
        f"{progress_bar(0)}"
    )

    enc = encode(file_id)

    # ✅ Download URL — VOE isko properly download kar sakta hai
    download_url = f"{SERVER_URL}/download/{enc}"

    result = await voe_submit(download_url, file_name)
    if not result:
        await status_msg.edit_text(f"❌ VOE fail!\n📺 `{anime}` › S{season} › {episode}")
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

async def queue_worker():
    while True:
        item = await upload_queue.get()
        try:
            await process_video(*item)
        except Exception as e:
            logging.error(f"Worker: {e}")
        finally:
            upload_queue.task_done()
            await asyncio.sleep(2)

@bot.on_message(filters.command("start"))
async def cmd_start(_, msg):
    await msg.reply_text(
        "🎬 **Anime Upload Bot**\n\n"
        "`/setup anime-slug season`\n"
        "Example: `/setup naruto 1`\n\n"
        "Phir videos forward karo — caption mein number chahiye\n"
        "`/status` — queue dekho"
    )

@bot.on_message(filters.command("setup"))
async def cmd_setup(_, msg):
    parts = msg.text.split()
    if len(parts) != 3:
        await msg.reply_text("❌ `/setup anime-slug season`")
        return
    try:
        season = int(parts[2])
    except:
        await msg.reply_text("❌ Season number hona chahiye!")
        return
    user_setup[msg.from_user.id] = {"anime": parts[1].lower(), "season": season}
    await msg.reply_text(f"✅ `{parts[1]}` › S{season} — Ab forward karo!")

@bot.on_message(filters.command("status"))
async def cmd_status(_, msg):
    setup = user_setup.get(msg.from_user.id)
    q = upload_queue.qsize() if upload_queue else 0
    if not setup:
        await msg.reply_text("⚠️ `/setup anime-slug season` karo pehle.")
    else:
        await msg.reply_text(f"📌 `{setup['anime']}` › S{setup['season']}\n⏳ Queue: {q} videos")

@bot.on_message(filters.video | filters.document)
async def handle_video(_, msg):
    setup = user_setup.get(msg.from_user.id)
    if not setup:
        await msg.reply_text("⚠️ Pehle `/setup anime-slug season` karo!")
        return

    file_id, file_name = None, "video.mp4"
    if msg.video:
        file_id  = msg.video.file_id
        file_name = msg.video.file_name or "video.mp4"
    elif msg.document and (msg.document.mime_type or "").startswith("video"):
        file_id  = msg.document.file_id
        file_name = msg.document.file_name or "video.mp4"
    if not file_id:
        return

    episode = extract_episode(msg.caption or file_name or "")
    if not episode:
        await msg.reply_text(f"⚠️ Episode number nahi mila!\nCaption: `{(msg.caption or '')[:50]}`")
        return

    await upload_queue.put((msg, setup["anime"], setup["season"], episode, file_id, file_name))
    await msg.reply_text(
        f"📋 **Queue #{upload_queue.qsize()}**\n\n"
        f"📺 `{setup['anime']}` › S{setup['season']} › {episode}\n"
        f"📁 `{file_name}`"
    )

async def main():
    global upload_queue
    upload_queue = asyncio.Queue()
    await bot.start()
    print("🤖 Anime Bot start!")
    asyncio.create_task(queue_worker())
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
