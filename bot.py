"""
AnimeVerse Upload Bot — Simple Edition
Flow:
  1. /setup anime-slug S1
  2. Ek ek episode ki file bhejo
  3. /done → sab VoE pe upload
"""

import re
import os
import time
import asyncio
import requests
import logging
from pyrogram import Client, filters
from pyrogram.types import Message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_ID       = int(os.environ.get("API_ID", "0"))
API_HASH     = os.environ.get("API_HASH", "")
BOT_TOKEN    = os.environ.get("BOT_TOKEN", "")
VOE_KEY      = os.environ.get("VOE_KEY", "")
ALLOWED_USER = int(os.environ.get("ALLOWED_USER", "0"))

LIMIT_BYTES  = 500 * 1024 * 1024  # 500MB

# ══════════════════════════════════════════════════════
#   STATE
# ══════════════════════════════════════════════════════

session = {"anime_id": None, "season": None, "done_eps": 0}
# ep_buffer[ep_num] = { file_id, size, name, tg_msg }
ep_buffer = {}


def reset_all():
    session.update({"anime_id": None, "season": None, "done_eps": 0})
    ep_buffer.clear()


# ══════════════════════════════════════════════════════
#   CAPTION PARSER
# ══════════════════════════════════════════════════════

def parse_ep(text):
    """Sirf EP number chahiye"""
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


def upload_to_voe_stream(file_id, filename):
    """20MB tak — stream karke upload"""
    try:
        sr = requests.get(
            "https://voe.sx/api/upload/server",
            params={"key": VOE_KEY},
            timeout=30
        )
        sdata = sr.json()
        if sdata.get("status") != 200:
            return None, "VoE server error: {}".format(sdata)
        upload_url = sdata["result"]

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
        logger.info("VoE upload: {}".format(udata))

        if udata.get("status") == 200:
            result = udata.get("result", [{}])
            if isinstance(result, list) and result:
                fc = result[0].get("code") or result[0].get("filecode") or result[0].get("file_code", "")
            else:
                fc = ""
            if fc:
                return "https://voe.sx/e/{}".format(fc), None

        return None, "VoE response: {}".format(udata)

    except Exception as e:
        logger.error("VoE stream: {}".format(e))
        return None, str(e)


def upload_to_voe_bytes(file_bytes, filename):
    """20MB se badi files ke liye"""
    try:
        sr = requests.get(
            "https://voe.sx/api/upload/server",
            params={"key": VOE_KEY},
            timeout=30
        )
        sdata = sr.json()
        if sdata.get("status") != 200:
            return None, "VoE server error: {}".format(sdata)
        upload_url = sdata["result"]

        upload_res = requests.post(
            upload_url,
            params={"key": VOE_KEY},
            files={"file": (filename, file_bytes, "video/mp4")},
            timeout=600
        )
        udata = upload_res.json()

        if udata.get("status") == 200:
            result = udata.get("result", [{}])
            if isinstance(result, list) and result:
                fc = result[0].get("code") or result[0].get("filecode") or result[0].get("file_code", "")
            else:
                fc = ""
            if fc:
                return "https://voe.sx/e/{}".format(fc), None

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
    filled = int(20 * current / total)
    bar = "█" * filled + "░" * (20 - filled)
    percent = int(100 * current / total)
    done_mb = round(current / 1024 / 1024, 1)
    total_mb = round(total / 1024 / 1024, 1)
    return "[{}] {}%\n{} MB / {} MB".format(bar, percent, done_mb, total_mb)


# ══════════════════════════════════════════════════════
#   PROCESS EPISODE
# ══════════════════════════════════════════════════════

async def process_ep(client, chat_id, ep_num, f):
    anime_id = session["anime_id"]
    season   = session["season"]
    ep_key   = "E{}".format(str(ep_num).zfill(2))
    fname    = f.get("name") or "{}_{}_{}. mp4".format(anime_id, season, ep_key)
    file_id  = f["file_id"]
    size_mb  = round(f["size"] / (1024 * 1024), 1)

    status_msg = await client.send_message(
        chat_id,
        "📤 **{}** ({}MB) VoE pe upload ho raha hai...".format(ep_key, size_mb)
    )

    if f["size"] <= 20 * 1024 * 1024:
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
                await status_msg.edit("📥 **{}** download ho raha hai...\n\n{}".format(ep_key, bar))
            except Exception:
                pass

        tg_msg = f.get("tg_msg")
        if tg_msg:
            file_data = await client.download_media(tg_msg, in_memory=True, progress=progress)
            file_bytes = bytes(file_data.getvalue())
            await status_msg.edit("✅ Download done! VoE pe upload ho raha hai... **{}**".format(ep_key))
            loop = asyncio.get_event_loop()
            voe_link, err = await loop.run_in_executor(None, upload_to_voe_bytes, file_bytes, fname)
        else:
            voe_link, err = None, "Message reference nahi mila"

    session["done_eps"] += 1

    if voe_link:
        await status_msg.edit(
            "✅ **{} Done!**\n"
            "🔗 `{}`\n"
            "📺 `{}` | `{}`".format(ep_key, voe_link, anime_id, season)
        )
    else:
        await status_msg.edit("❌ **{} Fail!** Error: {}".format(ep_key, err))


# ══════════════════════════════════════════════════════
#   BOT
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
        "**Step 2:** Har episode ki ek file bhejo\n"
        "**Step 3:** `/done` jab sab bhej do\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📋 `/status` — buffer dekho\n"
        "🔄 `/reset` — session clear karo\n\n"
        "500MB tak support! 🚀"
    )


@app.on_message(filters.command("setup"))
async def cmd_setup(client, message: Message):
    if not is_allowed(message):
        return
    parts = message.text.strip().split()
    if len(parts) < 3:
        await message.reply("❌ Format: `/setup anime-slug S1`")
        return
    slug = parts[1].lower()
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
        "Ab har episode ki ek file bhejo!\n"
        "Bot caption se EP number khud detect karega 🤖\n"
        "/done jab sab bhej do.".format(slug, season_raw)
    )


@app.on_message(filters.command("done"))
async def cmd_done(client, message: Message):
    if not is_allowed(message):
        return
    if not ep_buffer:
        await message.reply("✅ Koi pending episode nahi!")
        return
    pending = sorted(ep_buffer.keys())
    await message.reply("⚙️ **{} episodes upload ho rahe hain...**".format(len(pending)))
    for ep_num in pending:
        f = ep_buffer.pop(ep_num)
        await process_ep(client, message.chat.id, ep_num, f)
    total = session["done_eps"]
    await message.reply(
        "🏁 **Sab Complete!**\n"
        "✅ **{} episodes** VoE pe upload!\n"
        "📺 `{}` | `{}`\n\n"
        "Naye season ke liye `/setup` karo.".format(total, session["anime_id"], session["season"])
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
        "⏳ Buffer: `{} episodes`\n".format(len(ep_buffer))
    ]
    for ep_num in sorted(ep_buffer.keys()):
        ep_key = "E{}".format(str(ep_num).zfill(2))
        size_mb = round(ep_buffer[ep_num]["size"] / (1024 * 1024), 1)
        lines.append("  {}: {}MB ready".format(ep_key, size_mb))
    await message.reply("\n".join(lines))


@app.on_message(filters.command("reset"))
async def cmd_reset(client, message: Message):
    if not is_allowed(message):
        return
    reset_all()
    await message.reply("🔄 **Reset done!** `/setup anime-slug S1` se shuru karo.")


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

    # EP detect karo — caption pehle, phir filename
    ep_num = parse_ep(caption) or parse_ep(file_name)

    if not ep_num:
        await message.reply(
            "⚠️ **Episode detect nahi hua!**\n"
            "Caption: `{}`\n\n"
            "Caption mein `EP04` ya `Episode 04` ya `E04` hona chahiye.".format(caption[:100])
        )
        return

    ep_key  = "E{}".format(str(ep_num).zfill(2))
    size_mb = round(file_size / (1024 * 1024), 1)

    # Agar same EP dobara aayi — overwrite karo (updated file)
    if ep_num in ep_buffer:
        ep_buffer[ep_num] = {
            "file_id": file_id,
            "size":    file_size,
            "name":    file_name,
            "tg_msg":  message,
        }
        await message.reply(
            "🔄 **{}** update hua! ({}MB)\n"
            "`{}` | `{}`\n"
            "/done se upload karo.".format(ep_key, size_mb, session["anime_id"], session["season"])
        )
    else:
        ep_buffer[ep_num] = {
            "file_id": file_id,
            "size":    file_size,
            "name":    file_name,
            "tg_msg":  message,
        }
        await message.reply(
            "📥 **{}** buffer mein! ({}MB)\n"
            "`{}` | `{}`\n"
            "Aur episodes bhejo ya /done karo.".format(ep_key, size_mb, session["anime_id"], session["season"])
        )


if __name__ == "__main__":
    logger.info("Bot start ho raha hai...")
    app.run()
