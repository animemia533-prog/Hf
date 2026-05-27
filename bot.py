"""
AnimeVerse Upload Bot — Pyrogram + VOE Edition
Flow:
  1. /setup anime-slug S1
  2. Saari files ek saath forward karo (kisi bhi order mein)
  3. Bot caption se EP number + Quality auto-detect karega
  4. /done → sab upload VoE pe
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
ALLOWED_USER = int(os.environ.get("ALLOWED_USER", "0"))  # Sirf aap use kar sako

LIMIT_BYTES  = 500 * 1024 * 1024  # 500MB

# ══════════════════════════════════════════════════════
#   STATE
# ══════════════════════════════════════════════════════

session = {"anime_id": None, "season": None, "done_eps": 0}
# ep_buffer[ep_num] = [ {file_id, size, quality, name}, ... ]
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


def upload_to_voe_stream(file_id, filename):
    """Telegram CDN se seedha stream karke VoE pe upload karo — koi local storage nahi"""
    try:
        # Step 1: VoE upload server lo
        sr = requests.get(
            "https://voe.sx/api/upload/server",
            params={"key": VOE_KEY},
            timeout=30
        )
        sdata = sr.json()
        logger.info("VoE server: {}".format(sdata))
        if sdata.get("status") != 200:
            return None, "VoE server error: {}".format(sdata)
        upload_url = sdata["result"]

        # Step 2: Telegram URL nikalo
        tg_url = get_telegram_url(file_id)
        if not tg_url:
            return None, "Telegram URL nahi mila (file 20MB se badi hai?)"

        # Step 3: Stream karke VoE pe upload
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
    """Badi files ke liye bytes upload"""
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
        logger.info("VoE bytes upload: {}".format(udata))

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
#   PROCESS EPISODE (single ep upload)
# ══════════════════════════════════════════════════════

async def process_ep(client, chat_id, ep_num, files):
    anime_id = session["anime_id"]
    season   = session["season"]
    ep_key   = "E{}".format(str(ep_num).zfill(2))

    # Size ke hisaab se sort — chota=480p, beech=720p, bada=1080p
    sorted_files = sorted(files, key=lambda x: x["size"])
    quality_map  = {0: "480p", 1: "720p", 2: "1080p"}
    for i, f in enumerate(sorted_files):
        if not f.get("quality") or f["quality"] == "pending":
            f["quality"] = quality_map.get(i, "part{}".format(i + 1))

    await client.send_message(
        chat_id,
        "⚙️ **{} — VoE Upload Shuru...**\n{} files upload hongi ⏳".format(ep_key, len(sorted_files))
    )

    results = {}
    for f in sorted_files:
        quality  = f["quality"]
        size_mb  = round(f["size"] / (1024 * 1024), 1)
        fname    = f.get("name") or "{}_{}_{}_{}.mp4".format(anime_id, season, ep_key, quality)
        file_id  = f["file_id"]

        status_msg = await client.send_message(
            chat_id,
            "📤 `{}` ({}MB) upload ho raha hai...".format(quality, size_mb)
        )

        # Chhoti file — stream upload, badi file — download then upload
        if f["size"] <= 20 * 1024 * 1024:
            loop = asyncio.get_event_loop()
            voe_link, err = await loop.run_in_executor(None, upload_to_voe_stream, file_id, fname)
        else:
            # Pyrogram se download karo
            last_update = [0]

            async def progress(current, total):
                now = time.time()
                if now - last_update[0] < 3:
                    return
                last_update[0] = now
                bar = progress_bar(current, total)
                try:
                    await status_msg.edit("📥 Download: `{}`\n\n{}\n⏳...".format(quality, bar))
                except Exception:
                    pass

            # Find message in chat to download
            # We stored msg_id in buffer
            tg_msg = f.get("tg_msg")
            if tg_msg:
                file_data = await client.download_media(tg_msg, in_memory=True, progress=progress)
                file_bytes = bytes(file_data.getvalue())
                await status_msg.edit("✅ Download done! VoE pe upload ho raha hai... `{}`".format(quality))
                loop = asyncio.get_event_loop()
                voe_link, err = await loop.run_in_executor(None, upload_to_voe_bytes, file_bytes, fname)
            else:
                voe_link, err = None, "Message reference nahi mila"

        if voe_link:
            results[quality] = voe_link
            await status_msg.edit("✅ `{}` done!\n`{}`".format(quality, voe_link))
        else:
            await status_msg.edit("❌ `{}` fail: {}".format(quality, err))

        time.sleep(1)

    session["done_eps"] += 1

    if results:
        q_lines = "\n".join(["• {}: ✅ `{}`".format(q, l) for q, l in results.items()])
        await client.send_message(
            chat_id,
            "🎉 **{} Complete!**\n{}\n\nAnime: `{}` | `{}`".format(ep_key, q_lines, anime_id, season)
        )
    else:
        await client.send_message(
            chat_id,
            "❌ **{} Fail!** VoE key check karo.".format(ep_key)
        )


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
        "🎌 **AnimeVerse Upload Bot — VoE Edition**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "**Step 1:** `/setup anime-slug S1`\n"
        "**Step 2:** Saari files ek saath forward karo\n"
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
        "Ab saari files forward karo!\n"
        "Bot caption se EP + Quality khud detect karega 🤖\n"
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
    total = session["done_eps"]
    await message.reply(
        "🏁 **Sab Complete!**\n"
        "✅ **{} episodes** VoE pe upload!\n"
        "📺 `{}` | `{}`\n\n"
        "Naya season ke liye `/setup` karo.".format(total, session["anime_id"], session["season"])
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
        files = ep_buffer[ep_num]
        ep_key = "E{}".format(str(ep_num).zfill(2))
        lines.append("  {}: {} files".format(ep_key, len(files)))
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

    # Size check
    if file_size > LIMIT_BYTES:
        await message.reply("❌ File {}MB ki hai. Limit 500MB hai.".format(round(file_size / 1024 / 1024, 1)))
        return

    # Caption ya filename se EP detect karo
    ep_num, quality = parse_caption(caption)
    if not ep_num:
        ep_num, quality = parse_caption(file_name)

    if not ep_num:
        await message.reply(
            "⚠️ **Episode detect nahi hua!**\n"
            "Caption: `{}`\n\n"
            "Caption mein `Episode - 04` ya `EP04` ya `E04` hona chahiye.".format(caption[:100])
        )
        return

    ep_key = "E{}".format(str(ep_num).zfill(2))
    size_mb = round(file_size / (1024 * 1024), 1)

    if ep_num not in ep_buffer:
        ep_buffer[ep_num] = []

    # Duplicate check
    existing_sizes = [f["size"] for f in ep_buffer[ep_num]]
    if file_size in existing_sizes:
        await message.reply("⚠️ **{}** — same file dobara aai! Skip.".format(ep_key))
        return

    ep_buffer[ep_num].append({
        "file_id": file_id,
        "size":    file_size,
        "quality": quality or "pending",
        "name":    file_name,
        "tg_msg":  message,  # Reference for large file download
    })

    count = len(ep_buffer[ep_num])
    await message.reply(
        "📥 `{}MB` received\n"
        "📦 **{}** — {} file(s) buffer mein\n"
        "🎬 `{}` | `{}`\n\n"
        "Aur files bhejo ya `/done` karo upload ke liye!".format(
            size_mb, ep_key, count, session["anime_id"], session["season"]
        )
    )


if __name__ == "__main__":
    logger.info("Bot start ho raha hai...")
    app.run()
