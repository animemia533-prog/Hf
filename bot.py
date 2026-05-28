"""
AnimeVerse Upload Bot — Pyrogram + VOE + Firebase REST Edition
Railway variables: API_ID, API_HASH, BOT_TOKEN, VOE_KEY, ALLOWED_USER,
                   FIREBASE_URL, FIREBASE_SECRET (optional, agar rules locked hain)
"""

import re
import os
import json
import time
import asyncio
import requests
import logging
from pyrogram import Client, filters
from pyrogram.types import Message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_ID        = int(os.environ.get("API_ID", "0"))
API_HASH      = os.environ.get("API_HASH", "")
BOT_TOKEN     = os.environ.get("BOT_TOKEN", "")
VOE_KEY       = os.environ.get("VOE_KEY", "")
ALLOWED_USER  = int(os.environ.get("ALLOWED_USER", "0"))

# Firebase REST — sirf yahi do chahiye
# FIREBASE_URL  : e.g. https://animeverse-9eada-default-rtdb.firebaseio.com
# FIREBASE_SECRET: Database secret (optional) — Firebase Console → Project Settings → Service Accounts → Database secrets
FIREBASE_URL    = os.environ.get("FIREBASE_URL", "").rstrip("/")
FIREBASE_SECRET = os.environ.get("FIREBASE_SECRET", "")   # optional auth

LIMIT_BYTES = 500 * 1024 * 1024  # 500 MB


# ══════════════════════════════════════════════════════
#   FIREBASE REST HELPERS
# ══════════════════════════════════════════════════════

def _fb_params():
    """Query params for Firebase REST — auth token agar secret diya ho."""
    if FIREBASE_SECRET:
        return {"auth": FIREBASE_SECRET}
    return {}


def save_to_firebase(anime_id, season, ep_num, voe_link):
    """
    PUT  /Animes/{anime_id}/{season}/E{ep_num}.json
    Body: {"link": "...", "server": "Player4K", "time": <unix>}
    """
    if not FIREBASE_URL:
        logger.warning("FIREBASE_URL nahi mila, Firebase skip")
        return False
    try:
        ep_key  = "E{}".format(str(ep_num).zfill(2))
        url     = "{}/Animes/{}/{}/{}.json".format(FIREBASE_URL, anime_id, season, ep_key)
        payload = {
            "link":   voe_link,
            "server": "Player4K",
            "time":   int(time.time())
        }
        resp = requests.put(url, json=payload, params=_fb_params(), timeout=15)
        if resp.status_code == 200:
            logger.info("Firebase REST saved: Animes/{}/{}/{}".format(anime_id, season, ep_key))
            return True
        else:
            logger.error("Firebase REST error {}: {}".format(resp.status_code, resp.text))
            return False
    except Exception as e:
        logger.error("Firebase REST exception: {}".format(e))
        return False


# ══════════════════════════════════════════════════════
#   STATE
# ══════════════════════════════════════════════════════

session   = {"anime_id": None, "season": None, "done_eps": 0}
ep_buffer = {}


def reset_all():
    session.update({"anime_id": None, "season": None, "done_eps": 0})
    ep_buffer.clear()


# ══════════════════════════════════════════════════════
#   CAPTION PARSER
# ══════════════════════════════════════════════════════

def parse_caption(text):
    if not text:
        return None, None
    t = text.upper()

    ep_num = None
    ep_match = re.search(r'\bEP(?:ISODE)?\s*[-:.\s]*(\d{1,3})\b', t)
    if ep_match:
        ep_num = int(ep_match.group(1))

    if not ep_num:
        e_match = re.search(r'\bE(\d{1,3})\b', t)
        if e_match:
            ep_num = int(e_match.group(1))

    if not ep_num:
        cleaned = re.sub(r'\bS\d{1,2}\b', '', t)
        nums = re.findall(r'\b(\d{1,3})\b', cleaned)
        if nums:
            ep_num = int(nums[0])

    quality = None
    q_match = re.search(r'\b(1080P|720P|480P)\b', t)
    if q_match:
        quality = q_match.group(1).replace("P", "p")

    return ep_num, quality


# ══════════════════════════════════════════════════════
#   VOE UPLOAD
# ══════════════════════════════════════════════════════

def get_telegram_url(file_id):
    try:
        r = requests.get(
            "https://api.telegram.org/bot{}/getFile".format(BOT_TOKEN),
            params={"file_id": file_id},
            timeout=30
        )
        data = r.json()
        if data.get("ok"):
            return "https://api.telegram.org/file/bot{}/{}".format(BOT_TOKEN, data["result"]["file_path"])
        return None
    except Exception as e:
        logger.error("getFile: {}".format(e))
        return None


def get_voe_server():
    try:
        sr = requests.get(
            "https://voe.sx/api/upload/server",
            params={"key": VOE_KEY},
            timeout=30
        )
        sdata = sr.json()
        if sdata.get("status") == 200:
            return sdata["result"], None
        return None, "VoE server error: {}".format(sdata)
    except Exception as e:
        return None, str(e)


def parse_voe_response(udata):
    if udata.get("success"):
        file_obj = udata.get("file") or {}
        fc = file_obj.get("file_code") or file_obj.get("code") or ""
        if fc:
            return "https://voe.sx/e/{}".format(fc), None
    if udata.get("status") == 200:
        result = udata.get("result", [{}])
        if isinstance(result, list) and result:
            fc = result[0].get("code") or result[0].get("filecode") or result[0].get("file_code", "")
        else:
            fc = ""
        if fc:
            return "https://voe.sx/e/{}".format(fc), None
    return None, "VoE response: {}".format(udata)


def upload_to_voe_stream(file_id, filename):
    upload_url, err = get_voe_server()
    if not upload_url:
        return None, err
    tg_url = get_telegram_url(file_id)
    if not tg_url:
        return None, "Telegram URL nahi mila"
    try:
        with requests.get(tg_url, stream=True, timeout=300) as tg_stream:
            tg_stream.raise_for_status()
            upload_res = requests.post(
                upload_url,
                params={"key": VOE_KEY},
                files={"file": (filename, tg_stream.raw, "video/mp4")},
                timeout=600
            )
        udata = upload_res.json()
        logger.info("VoE stream: {}".format(udata))
        return parse_voe_response(udata)
    except Exception as e:
        return None, str(e)


def upload_to_voe_bytes(file_bytes, filename):
    upload_url, err = get_voe_server()
    if not upload_url:
        return None, err
    try:
        upload_res = requests.post(
            upload_url,
            params={"key": VOE_KEY},
            files={"file": (filename, file_bytes, "video/mp4")},
            timeout=600
        )
        udata = upload_res.json()
        logger.info("VoE bytes: {}".format(udata))
        return parse_voe_response(udata)
    except Exception as e:
        return None, str(e)


# ══════════════════════════════════════════════════════
#   PROGRESS BAR
# ══════════════════════════════════════════════════════

def progress_bar(current, total):
    if total == 0:
        return ""
    filled  = int(20 * current / total)
    bar     = "█" * filled + "░" * (20 - filled)
    percent = int(100 * current / total)
    done_mb  = round(current / 1024 / 1024, 1)
    total_mb = round(total   / 1024 / 1024, 1)
    return "[{}] {}%\n{} MB / {} MB".format(bar, percent, done_mb, total_mb)


# ══════════════════════════════════════════════════════
#   PROCESS SINGLE EPISODE  (buffer mode)
# ══════════════════════════════════════════════════════

async def process_ep(client, chat_id, ep_num, files):
    anime_id = session["anime_id"]
    season   = session["season"]
    ep_key   = "E{}".format(str(ep_num).zfill(2))

    sorted_files = sorted(files, key=lambda x: x["size"])

    await client.send_message(
        chat_id,
        "⚙️ **{} — VoE Upload Shuru...**\n{} file(s) ⏳".format(ep_key, len(sorted_files))
    )

    all_success = []

    for f in sorted_files:
        quality  = f.get("quality") or "480p"
        size_mb  = round(f["size"] / (1024 * 1024), 1)
        fname    = "{}_{}_{}_{}.mp4".format(anime_id, season, ep_key, quality)
        file_id  = f["file_id"]

        status_msg = await client.send_message(
            chat_id,
            "📤 `{}` ({}MB) upload ho raha hai...".format(quality, size_mb)
        )

        if f["size"] <= 20 * 1024 * 1024:
            loop = asyncio.get_event_loop()
            voe_link, err = await loop.run_in_executor(None, upload_to_voe_stream, file_id, fname)
        else:
            last_update = [0]
            tg_msg      = f.get("tg_msg")

            async def progress(current, total):
                now = time.time()
                if now - last_update[0] < 3:
                    return
                last_update[0] = now
                bar = progress_bar(current, total)
                try:
                    await status_msg.edit("📥 Download: `{}`\n\n{}".format(quality, bar))
                except Exception:
                    pass

            if tg_msg:
                file_data  = await client.download_media(tg_msg, in_memory=True, progress=progress)
                file_bytes = bytes(file_data.getvalue())
                await status_msg.edit("✅ Download done!\n⬆️ VoE pe upload ho raha hai `{}`...".format(quality))
                loop = asyncio.get_event_loop()
                voe_link, err = await loop.run_in_executor(None, upload_to_voe_bytes, file_bytes, fname)
            else:
                voe_link, err = None, "Message reference nahi mila"

        if voe_link:
            saved    = save_to_firebase(anime_id, season, ep_num, voe_link)
            fb_status = "✅ Firebase saved!" if saved else "⚠️ Firebase save fail"
            all_success.append({"quality": quality, "link": voe_link})
            await status_msg.edit(
                "✅ `{}` done!\n🔗 `{}`\n{}".format(quality, voe_link, fb_status)
            )
        else:
            await status_msg.edit("❌ `{}` fail: {}".format(quality, err))

        time.sleep(1)

    session["done_eps"] += 1

    if all_success:
        q_lines = "\n".join(["• {}: `{}`".format(x["quality"], x["link"]) for x in all_success])
        await client.send_message(
            chat_id,
            "🎉 **{} Complete!**\n\n{}\n\n📁 Firebase: `Animes/{}/{}/{}`".format(
                ep_key, q_lines, anime_id, season, ep_key
            )
        )
    else:
        await client.send_message(chat_id, "❌ **{} Fail!**".format(ep_key))


# ══════════════════════════════════════════════════════
#   BOT COMMANDS
# ══════════════════════════════════════════════════════

app = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


def is_allowed(message):
    if ALLOWED_USER == 0:
        return True
    return message.from_user.id == ALLOWED_USER


@app.on_message(filters.command("start"))
async def cmd_start(client, message: Message):
    if not is_allowed(message):
        return
    await message.reply(
        "🎌 **AnimeVerse Upload Bot**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "**Step 1:** `/setup anime-slug S1`\n"
        "**Step 2:** Saari files forward karo\n"
        "**Step 3:** `/done` — upload shuru!\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📋 `/status` | 🔄 `/reset`\n\n"
        "500MB tak support! 🚀\n"
        "VoE link auto Firebase mein save hoga! 🔥"
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
        "Ab saari files forward karo!\n"
        "Caption se EP + Quality auto-detect hoga 🤖\n"
        "/done jab sab bhej do.".format(slug, season_raw)
    )


@app.on_message(filters.command("done"))
async def cmd_done(client, message: Message):
    if not is_allowed(message):
        return
    if not ep_buffer:
        await message.reply("✅ Koi pending episode nahi!")
        return
    pending = list(ep_buffer.keys())
    await message.reply("⚙️ **{} pending episodes process ho rahe hain...**".format(len(pending)))
    for ep_num in sorted(pending):
        files = ep_buffer.pop(ep_num)
        await process_ep(client, message.chat.id, ep_num, files)
    await message.reply(
        "🏁 **Sab Complete!**\n"
        "✅ **{} episodes** VoE + Firebase!\n"
        "📺 `{}` | `{}`".format(session["done_eps"], session["anime_id"], session["season"])
    )


@app.on_message(filters.command("status"))
async def cmd_status(client, message: Message):
    if not is_allowed(message):
        return
    if not session["anime_id"]:
        await message.reply("ℹ️ Koi session nahi.\n`/setup anime-slug S1` se shuru karo.")
        return
    lines = [
        "📋 **Status:**\n━━━━━━━━━━━━━━━━━━━━",
        "📺 `{}` | `{}`".format(session["anime_id"], session["season"]),
        "✅ Done: `{} episodes`".format(session["done_eps"]),
        "⏳ Buffer: `{} episodes`".format(len(ep_buffer))
    ]
    for ep_num in sorted(ep_buffer.keys()):
        ep_key = "E{}".format(str(ep_num).zfill(2))
        lines.append("  {}: {} file(s)".format(ep_key, len(ep_buffer[ep_num])))
    await message.reply("\n".join(lines))


@app.on_message(filters.command("reset"))
async def cmd_reset(client, message: Message):
    if not is_allowed(message):
        return
    reset_all()
    await message.reply("🔄 **Reset done!**")


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
        await message.reply("❌ File {}MB. Limit 500MB hai.".format(round(file_size / 1024 / 1024, 1)))
        return

    ep_num, quality = parse_caption(caption)
    if not ep_num:
        ep_num, quality = parse_caption(file_name)

    if not ep_num:
        await message.reply(
            "⚠️ **Episode detect nahi hua!**\n"
            "Caption: `{}`\n\n"
            "Caption mein `EP04` ya `Episode - 04` hona chahiye.".format(caption[:100])
        )
        return

    ep_key  = "E{}".format(str(ep_num).zfill(2))
    size_mb = round(file_size / (1024 * 1024), 1)
    quality = quality or "1080p"

    wait = await message.reply(
        "📥 File mili!\n"
        "📦 **{}** | `{}` | `{}`\n"
        "🎬 `{}` | `{}` | `{}`\n\n"
        "Upload shuru ho raha hai...".format(
            ep_key, quality, "{}MB".format(size_mb),
            session["anime_id"], session["season"], file_name
        )
    )

    fname = "{}_{}_{}_{}.mp4".format(session["anime_id"], session["season"], ep_key, quality)

    if file_size <= 20 * 1024 * 1024:
        await wait.edit("🎬 VoE pe upload ho raha hai...\n**{}** `{}` ({}MB)".format(ep_key, quality, size_mb))
        loop = asyncio.get_event_loop()
        voe_link, err = await loop.run_in_executor(None, upload_to_voe_stream, file_id, fname)
    else:
        last_update = [0]

        async def progress(current, total):
            now = time.time()
            if now - last_update[0] < 3:
                return
            last_update[0] = now
            bar = progress_bar(current, total)
            try:
                await wait.edit("📥 Download ho raha hai...\n**{}** `{}`\n\n{}".format(ep_key, quality, bar))
            except Exception:
                pass

        await wait.edit(
            "📥 Download ho raha hai...\n**{}** `{}` ({}MB)\n\n[░░░░░░░░░░░░░░░░░░░░] 0%".format(
                ep_key, quality, size_mb
            )
        )
        file_data  = await client.download_media(message, in_memory=True, progress=progress)
        file_bytes = bytes(file_data.getvalue())

        await wait.edit("✅ Download done!\n⬆️ VoE pe upload ho raha hai... **{}**".format(ep_key))
        loop = asyncio.get_event_loop()
        voe_link, err = await loop.run_in_executor(None, upload_to_voe_bytes, file_bytes, fname)

    if voe_link:
        saved     = save_to_firebase(session["anime_id"], session["season"], ep_num, voe_link)
        fb_status = "✅ Firebase saved!" if saved else "⚠️ Firebase save fail"
        session["done_eps"] += 1
        await wait.edit(
            "✅ **Done!**\n\n"
            "📦 **{}** | `{}` | {}MB\n"
            "🎬 `{}` | `{}`\n\n"
            "🔗 VoE: `{}`\n"
            "{}".format(
                ep_key, quality, size_mb,
                session["anime_id"], session["season"],
                voe_link, fb_status
            )
        )
    else:
        await wait.edit("❌ Upload fail: {}\n**{}**".format(err, ep_key))


if __name__ == "__main__":
    if not FIREBASE_URL:
        logger.warning("⚠️  FIREBASE_URL set nahi hai — Firebase save kaam nahi karega!")
    logger.info("Bot start ho raha hai...")
    app.run()
