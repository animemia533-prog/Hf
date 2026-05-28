"""
AnimeVerse Upload Bot — Auto Parallel Upload + Firebase
"""

import re
import os
import json
import time
import asyncio
import requests
import logging
from concurrent.futures import ThreadPoolExecutor
from pyrogram import Client, filters, idle
from pyrogram.types import Message
import firebase_admin
from firebase_admin import credentials, db as firebase_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_ID             = int(os.environ.get("API_ID", "0"))
API_HASH           = os.environ.get("API_HASH", "")
BOT_TOKEN          = os.environ.get("BOT_TOKEN", "")
VOE_KEY            = os.environ.get("VOE_KEY", "")
ALLOWED_USER       = int(os.environ.get("ALLOWED_USER", "0"))
FIREBASE_DB_URL    = os.environ.get("FIREBASE_DB_URL", "")
FIREBASE_CRED_JSON = os.environ.get("FIREBASE_CRED_JSON", "")

LIMIT_BYTES = 500 * 1024 * 1024  # 500MB

download_semaphore = None
executor = ThreadPoolExecutor(max_workers=8)

# ══════════════════════════════════════════════════════
#   FIREBASE INIT
# ══════════════════════════════════════════════════════

try:
    cred_dict = json.loads(FIREBASE_CRED_JSON)
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred, {
        "databaseURL": FIREBASE_DB_URL
    })
    logger.info("Firebase connected!")
except Exception as e:
    logger.error("Firebase init error: {}".format(e))


def save_to_firebase(slug, season, ep_key, voe_link):
    try:
        ref = firebase_db.reference("Animes/{}/{}/{}".format(slug, season, ep_key))
        ref.set({
            "link":   voe_link,
            "server": "Player4u",
            "time":   int(time.time())
        })
        logger.info("Firebase saved: {}/{}/{}".format(slug, season, ep_key))
        return True
    except Exception as e:
        logger.error("Firebase error: {}".format(e))
        return False


# ══════════════════════════════════════════════════════
#   STATE
# ══════════════════════════════════════════════════════

session   = {"anime_id": None, "season": None, "done_eps": 0}
uploading = set()


def reset_all():
    session.update({"anime_id": None, "season": None, "done_eps": 0})
    uploading.clear()


# ══════════════════════════════════════════════════════
#   CAPTION PARSER
# ══════════════════════════════════════════════════════

def parse_ep(text):
    if not text:
        return None
    t = text.upper()

    m = re.search(r'\bEP(?:ISODE)?\s*[-:.\s]*(\d{1,3})\b', t)
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


# ══════════════════════════════════════════════════════
#   VOE HELPERS
# ══════════════════════════════════════════════════════

def extract_voe_link(udata):
    fc = None

    if udata.get("success") and udata.get("file"):
        f  = udata["file"]
        fc = f.get("file_code") or f.get("filecode") or f.get("code", "")

    elif udata.get("status") == 200:
        result = udata.get("result", [{}])
        if isinstance(result, list) and result:
            fc = (
                result[0].get("file_code") or
                result[0].get("filecode") or
                result[0].get("code", "")
            )

    if fc:
        return "https://voe.sx/e/{}".format(fc)
    return None


def get_voe_upload_url():
    sr = requests.get(
        "https://voe.sx/api/upload/server",
        params={"key": VOE_KEY},
        timeout=30
    )
    sdata = sr.json()
    if sdata.get("status") != 200:
        return None, "VoE server error: {}".format(sdata)
    return sdata["result"], None


def get_telegram_url(file_id):
    try:
        r = requests.get(
            "https://api.telegram.org/bot{}/getFile".format(BOT_TOKEN),
            params={"file_id": file_id},
            timeout=30
        )
        data = r.json()
        if data.get("ok"):
            return "https://api.telegram.org/file/bot{}/{}".format(
                BOT_TOKEN, data["result"]["file_path"]
            )
        return None
    except Exception as e:
        logger.error("getFile: {}".format(e))
        return None


def upload_to_voe_stream(file_id, filename):
    try:
        upload_url, err = get_voe_upload_url()
        if err:
            return None, err

        tg_url = get_telegram_url(file_id)
        if not tg_url:
            return None, "Telegram URL nahi mila (file 20MB se badi hai?)"

        with requests.get(tg_url, stream=True, timeout=300) as tg_stream:
            tg_stream.raise_for_status()
            upload_res = requests.post(
                upload_url,
                params={"key": VOE_KEY},
                files={"file": (filename, tg_stream.raw, "video/mp4")},
                timeout=600
            )

        udata = upload_res.json()
        logger.info("VoE stream response: {}".format(udata))

        voe_link = extract_voe_link(udata)
        if voe_link:
            return voe_link, None
        return None, "VoE response: {}".format(udata)

    except Exception as e:
        logger.error("VoE stream: {}".format(e))
        return None, str(e)


def upload_to_voe_bytes(file_bytes, filename):
    try:
        upload_url, err = get_voe_upload_url()
        if err:
            return None, err

        upload_res = requests.post(
            upload_url,
            params={"key": VOE_KEY},
            files={"file": (filename, file_bytes, "video/mp4")},
            timeout=600
        )

        udata = upload_res.json()
        logger.info("VoE bytes response: {}".format(udata))

        voe_link = extract_voe_link(udata)
        if voe_link:
            return voe_link, None
        return None, "VoE response: {}".format(udata)

    except Exception as e:
        logger.error("VoE bytes: {}".format(e))
        return None, str(e)


# ══════════════════════════════════════════════════════
#   PROGRESS BAR
# ══════════════════════════════════════════════════════

def progress_bar(current, total):
    if total == 0:
        return ""
    filled   = int(20 * current / total)
    bar      = "█" * filled + "░" * (20 - filled)
    percent  = int(100 * current / total)
    done_mb  = round(current / 1024 / 1024, 1)
    total_mb = round(total / 1024 / 1024, 1)
    return "[{}] {}%\n{} MB / {} MB".format(bar, percent, done_mb, total_mb)


# ══════════════════════════════════════════════════════
#   UPLOAD TASK
# ══════════════════════════════════════════════════════

async def upload_task(client, chat_id, ep_num, f):
    global download_semaphore

    anime_id = session["anime_id"]
    season   = session["season"]
    ep_key   = "E{}".format(str(ep_num).zfill(2))
    fname    = f.get("name") or "{}_{}_{}.mp4".format(anime_id, season, ep_key)
    file_id  = f["file_id"]
    size_mb  = round(f["size"] / (1024 * 1024), 1)

    status_msg = await client.send_message(
        chat_id,
        "📤 **{}** ({}MB) upload shuru...".format(ep_key, size_mb)
    )

    try:
        loop = asyncio.get_event_loop()

        if f["size"] <= 20 * 1024 * 1024:
            voe_link, err = await loop.run_in_executor(
                executor, upload_to_voe_stream, file_id, fname
            )
        else:
            last_update = [0]

            async def progress(current, total):
                now = time.time()
                if now - last_update[0] < 3:
                    return
                last_update[0] = now
                bar = progress_bar(current, total)
                try:
                    await status_msg.edit(
                        "📥 **{}** download ho raha hai...\n\n{}".format(ep_key, bar)
                    )
                except Exception:
                    pass

            tg_msg = f.get("tg_msg")
            if not tg_msg:
                await status_msg.edit(
                    "❌ **{}** message reference nahi mila.".format(ep_key)
                )
                return

            async with download_semaphore:
                await status_msg.edit(
                    "📥 **{}** download shuru...".format(ep_key)
                )
                file_data = await client.download_media(
                    tg_msg, in_memory=True, progress=progress
                )

            file_bytes = bytes(file_data.getvalue())
            del file_data

            await status_msg.edit(
                "⬆️ **{}** VoE pe ja raha hai...".format(ep_key)
            )

            voe_link, err = await loop.run_in_executor(
                executor, upload_to_voe_bytes, file_bytes, fname
            )

        session["done_eps"] += 1

        if voe_link:
            saved     = save_to_firebase(anime_id, season, ep_key, voe_link)
            fb_status = "💾 Firebase ✅" if saved else "💾 Firebase ❌"
            await status_msg.edit(
                "✅ **{} Done!**\n"
                "🔗 `{}`\n"
                "📺 `{}` | `{}`\n"
                "{}".format(ep_key, voe_link, anime_id, season, fb_status)
            )
        else:
            await status_msg.edit(
                "❌ **{} Fail!** `{}`".format(ep_key, err)
            )

    except Exception as e:
        logger.error("upload_task {}: {}".format(ep_key, e))
        await status_msg.edit(
            "❌ **{}** unexpected error: `{}`".format(ep_key, str(e))
        )

    finally:
        uploading.discard(ep_num)


# ══════════════════════════════════════════════════════
#   BOT INIT
# ══════════════════════════════════════════════════════

app = Client(
    "bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=16
)


def is_allowed(message):
    if ALLOWED_USER == 0:
        return True
    return message.from_user.id == ALLOWED_USER


# ══════════════════════════════════════════════════════
#   COMMANDS
# ══════════════════════════════════════════════════════

@app.on_message(filters.command("start"))
async def cmd_start(client, message: Message):
    if not is_allowed(message):
        return
    await message.reply(
        "🎌 **AnimeVerse Upload Bot**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "**Step 1:** `/setup anime-slug S1`\n"
        "**Step 2:** Files bhejo — turant parallel upload shuru!\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📋 `/status` — dekho kya upload ho raha hai\n"
        "🔄 `/reset` — session clear karo\n\n"
        "500MB tak, sab parallel + Firebase! 🚀"
    )


@app.on_message(filters.command("setup"))
async def cmd_setup(client, message: Message):
    if not is_allowed(message):
        return
    parts = message.text.strip().split()
    if len(parts) < 3:
        await message.reply("❌ Format: `/setup anime-slug S1`")
        return
    slug       = parts[1].lower()
    season_raw = parts[2].upper()
    if not season_raw.startswith("S") or not season_raw[1:].isdigit():
        await message.reply("❌ Season format galat! Use: S1, S2, S3...")
        return
    reset_all()
    session["anime_id"] = slug
    session["season"]   = season_raw
    await message.reply(
        "✅ **Setup Done!**\n"
        "📺 Anime: `{}`\n"
        "🎬 Season: `{}`\n\n"
        "Ab files bhejo — har file receive hote hi parallel upload shuru! ⚡\n"
        "VoE link automatically Firebase mein save hoga 🔥".format(slug, season_raw)
    )


@app.on_message(filters.command("status"))
async def cmd_status(client, message: Message):
    if not is_allowed(message):
        return
    if not session["anime_id"]:
        await message.reply(
            "ℹ️ Koi session nahi.\n`/setup anime-slug S1` se shuru karo."
        )
        return
    up_list = ", ".join(
        ["E{}".format(str(e).zfill(2)) for e in sorted(uploading)]
    ) or "Koi nahi"
    await message.reply(
        "📋 **Status:**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📺 `{}` | `{}`\n"
        "✅ Done: `{} episodes`\n"
        "⚙️ Abhi upload ho rahe: `{}`".format(
            session["anime_id"], session["season"],
            session["done_eps"], up_list
        )
    )


@app.on_message(filters.command("reset"))
async def cmd_reset(client, message: Message):
    if not is_allowed(message):
        return
    reset_all()
    await message.reply(
        "🔄 **Reset done!** `/setup anime-slug S1` se shuru karo."
    )


@app.on_message(filters.video | filters.document)
async def handle_file(client, message: Message):
    if not is_allowed(message):
        return
    if not session["anime_id"]:
        await message.reply("❌ Pehle `/setup anime-slug S1` karo!")
        return

    file_obj  = message.video or message.document
    file_id   = file_obj.file_id
    file_size = file_obj.file_size or 0
    file_name = getattr(file_obj, "file_name", None) or "video.mp4"
    caption   = message.caption or ""

    if file_size > LIMIT_BYTES:
        await message.reply(
            "❌ File {}MB. Limit 500MB hai.".format(
                round(file_size / 1024 / 1024, 1)
            )
        )
        return

    ep_num = parse_ep(caption) or parse_ep(file_name)

    if not ep_num:
        await message.reply(
            "⚠️ **Episode detect nahi hua!**\n"
            "Caption: `{}`\n\n"
            "Caption mein `EP04` ya `Episode 04` ya `E04` hona chahiye.".format(
                caption[:100]
            )
        )
        return

    ep_key  = "E{}".format(str(ep_num).zfill(2))
    size_mb = round(file_size / (1024 * 1024), 1)

    if ep_num in uploading:
        await message.reply(
            "⚠️ **{}** pehle se upload ho raha hai! Skip.".format(ep_key)
        )
        return

    uploading.add(ep_num)

    f = {
        "file_id": file_id,
        "size":    file_size,
        "name":    file_name,
        "tg_msg":  message,
    }

    await message.reply(
        "⚡ **{}** ({}MB) — upload shuru!\n"
        "`{}` | `{}`".format(ep_key, size_mb, session["anime_id"], session["season"])
    )

    asyncio.create_task(upload_task(client, message.chat.id, ep_num, f))


# ══════════════════════════════════════════════════════
#   MAIN
# ══════════════════════════════════════════════════════

async def main():
    global download_semaphore
    download_semaphore = asyncio.Semaphore(3)
    await app.start()
    logger.info("Bot chal raha hai... ✅")
    await idle()


if __name__ == "__main__":
    asyncio.run(main())
