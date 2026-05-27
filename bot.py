import os
import time
import requests
import logging
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
VOE_KEY = os.environ.get("VOE_KEY", "")

# Active sessions store karo — {user_id: {slug, season, ep_count}}
sessions = {}

LIMIT_BYTES = 500 * 1024 * 1024  # 500MB


def progress_bar(current, total):
    if total == 0:
        return ""
    filled = int(20 * current / total)
    bar = "█" * filled + "░" * (20 - filled)
    percent = int(100 * current / total)
    done_mb = round(current / 1024 / 1024, 1)
    total_mb = round(total / 1024 / 1024, 1)
    return "[{}] {}%\n{} MB / {} MB".format(bar, percent, done_mb, total_mb)


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
        logger.error("getFile error: {}".format(e))
        return None





def voe_remote_upload(direct_url, filename):
    try:
        r = requests.get(
            "https://voe.sx/api/upload/url",
            params={"key": VOE_KEY, "url": direct_url, "name": filename},
            timeout=30
        )

        # FIX: Empty response check
        if not r.text.strip():
            return None, "VoE empty response (remote start)"

        try:
            data = r.json()
        except Exception:
            return None, "VoE invalid JSON (start): {}".format(r.text[:200])

        logger.info("VoE remote start: {}".format(data))

        if not data.get("status"):
            return None, "VoE start fail: {}".format(data)

        file_code = data.get("file_code") or data.get("filecode")
        if not file_code:
            return None, "file_code nahi mila"

        for i in range(120):
            time.sleep(5)
            try:
                sr = requests.get(
                    "https://voe.sx/api/upload/url/status",
                    params={"key": VOE_KEY, "file_code": file_code},
                    timeout=15
                )

                # FIX: Status response bhi safely parse karo
                if not sr.text.strip():
                    logger.warning("Empty status response, retrying... ({})".format(i))
                    continue

                sd = sr.json()

            except Exception as e:
                logger.warning("Status parse fail {}: {}".format(i, e))
                continue

            logger.info("VoE status {}: {}".format(i, sd))
            s = str(sd.get("status", "")).lower()

            if s == "done" or sd.get("completed") or s == "200":
                return "https://voe.sx/{}".format(file_code), None
            elif s in ["error", "failed", "404"]:
                return None, "VoE fail: {}".format(sd)

        return None, "VoE timeout (10 min)"

    except Exception as e:
        logger.error("VoE remote: {}".format(e))
        return None, str(e)




def catbox_upload(file_path, filename):
    """Catbox pe file upload karo — public temp URL milegi VoE ke liye"""
    try:
        with open(file_path, "rb") as f:
            r = requests.post(
                "https://catbox.moe/user/api.php",
                data={"reqtype": "fileupload", "userhash": ""},
                files={"fileToUpload": (filename, f)},
                timeout=600
            )
        url = r.text.strip()
        if url.startswith("https://"):
            logger.info("Catbox upload success: {}".format(url))
            return url, None
        return None, "Catbox response: {}".format(url[:200])
    except Exception as e:
        logger.error("Catbox upload error: {}".format(e))
        return None, str(e)

app = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


@app.on_message(filters.command("start"))
async def start(client, message: Message):
    await message.reply(
        "👋 Hello! Main VoE Upload Bot hoon!\n\n"
        "📋 Commands:\n\n"
        "▶️ /setup <slug> S<season>\n"
        "   Example: /setup one-piece S1\n"
        "   Phir episodes forward karo!\n\n"
        "📊 /status — current session dekho\n"
        "🔄 /reset — session clear karo\n\n"
        "500MB tak episodes support hain! 🎬"
    )


@app.on_message(filters.command("setup"))
async def setup(client, message: Message):
    user_id = message.from_user.id
    parts = message.text.strip().split()

    if len(parts) < 3:
        await message.reply(
            "❌ Format galat hai!\n\n"
            "✅ Sahi format:\n"
            "/setup <anime-slug> S<season>\n\n"
            "Example:\n"
            "/setup one-piece S1\n"
            "/setup dragon-ball-z S3"
        )
        return

    slug = parts[1].lower()
    season_raw = parts[2].upper()

    if not season_raw.startswith("S") or not season_raw[1:].isdigit():
        await message.reply("❌ Season format galat! Use karo: S1, S2, S3...")
        return

    season = int(season_raw[1:])
    sessions[user_id] = {
        "slug": slug,
        "season": season,
        "ep_count": 0,
        "links": []
    }

    await message.reply(
        "✅ Setup complete!\n\n"
        "🎬 Anime: {}\n"
        "📺 Season: {}\n\n"
        "Ab episodes forward karo — main automatically VoE pe upload karta rahunga!\n"
        "📊 /status se progress dekho\n"
        "🔄 /reset se band karo".format(slug, season)
    )


@app.on_message(filters.command("status"))
async def status(client, message: Message):
    user_id = message.from_user.id
    if user_id not in sessions:
        await message.reply("⚠️ Koi active session nahi.\n/setup se shuru karo.")
        return

    s = sessions[user_id]
    links_text = ""
    if s["links"]:
        links_text = "\n\n📋 Uploaded links:\n"
        for item in s["links"]:
            links_text += "EP{}: {}\n".format(item["ep"], item["link"])

    await message.reply(
        "📊 Current Session:\n\n"
        "🎬 Anime: {}\n"
        "📺 Season: {}\n"
        "✅ Uploaded: {} episodes{}".format(s["slug"], s["season"], s["ep_count"], links_text)
    )


@app.on_message(filters.command("reset"))
async def reset(client, message: Message):
    user_id = message.from_user.id
    if user_id in sessions:
        s = sessions[user_id]
        if s["links"]:
            links_text = "📋 All Links:\n"
            for item in s["links"]:
                links_text += "EP{} S{}: {}\n".format(item["ep"], s["season"], item["link"])
            await message.reply(
                "🔄 Session reset!\n\n"
                "🎬 Anime: {}\n"
                "✅ Total: {} episodes\n\n{}".format(s["slug"], s["ep_count"], links_text)
            )
        else:
            await message.reply("🔄 Session reset!")
        del sessions[user_id]
    else:
        await message.reply("⚠️ Koi active session nahi tha.")


@app.on_message(filters.video | filters.document)
async def handle_file(client, message: Message):
    user_id = message.from_user.id

    if message.video:
        media = message.video
        filename = media.file_name or "video_{}.mp4".format(media.file_unique_id)
        size = media.file_size or 0
        file_id = media.file_id
    elif message.document:
        media = message.document
        filename = media.file_name or "doc_{}".format(media.file_unique_id)
        size = media.file_size or 0
        file_id = media.file_id
    else:
        return

    size_mb = round(size / 1024 / 1024, 1)

    if size > LIMIT_BYTES:
        await message.reply("❌ File {}MB ki hai. Limit 500MB hai.".format(size_mb))
        return

    session_info = ""
    ep_num = None
    if user_id in sessions:
        s = sessions[user_id]
        s["ep_count"] += 1
        ep_num = s["ep_count"]
        session_info = "\n🎬 {}\n📺 S{} EP{}".format(s["slug"], s["season"], ep_num)

    wait = await message.reply(
        "📥 File mili!\n📁 {}\n📦 {}MB{}\n\nShuru ho raha hai...".format(filename, size_mb, session_info)
    )

    try:
        direct_url = get_telegram_url(file_id)

        if direct_url:
            # ✅ Bot API URL mili (<20MB) — seedha VoE remote upload
            await wait.edit(
                "🎬 VoE pe remote upload ho raha hai...\n📦 {}MB{}\n\n[░░░░░░░░░░░░░░░░░░░░]\n⏳ 2-5 min...".format(
                    size_mb, session_info
                )
            )
            voe_link, err = voe_remote_upload(direct_url, filename)
        else:
            # ✅ 20MB+ file — Pyrogram se download karo, catbox pe upload karo, phir VoE remote upload
            last_update = [0]

            async def progress(current, total):
                now = time.time()
                if now - last_update[0] < 3:
                    return
                last_update[0] = now
                bar = progress_bar(current, total)
                try:
                    await wait.edit(
                        "📥 Telegram se download ho raha hai...{}\n\n{}\n\n⏳ Wait karo...".format(session_info, bar)
                    )
                except Exception:
                    pass

            await wait.edit(
                "📥 Telegram se download ho raha hai...{}\n\n[░░░░░░░░░░░░░░░░░░░░] 0%\n0 MB / {} MB\n\n⏳ Wait karo...".format(
                    session_info, size_mb
                )
            )

            tmp_path = "/tmp/{}".format(filename)
            await client.download_media(message, file_name=tmp_path, progress=progress)

            await wait.edit(
                "✅ Download ho gaya!\n📦 {}MB{}\n\n⬆️ Catbox pe upload ho raha hai (temp)...\n⏳ Wait karo...".format(
                    size_mb, session_info
                )
            )

            # Catbox pe upload karo — free anonymous hosting, VoE isse download kar sakta hai
            loop = asyncio.get_event_loop()
            temp_url, cat_err = await loop.run_in_executor(None, catbox_upload, tmp_path, filename)

            # Temp file delete karo
            try:
                os.remove(tmp_path)
            except Exception:
                pass

            if not temp_url:
                voe_link, err = None, "Catbox upload fail: {}".format(cat_err)
            else:
                await wait.edit(
                    "✅ Temp upload ho gaya!\n📦 {}MB{}\n\n🎬 VoE pe remote upload ho raha hai...\n⏳ 2-5 min...".format(
                        size_mb, session_info
                    )
                )
                voe_link, err = voe_remote_upload(temp_url, filename)

        if voe_link:
            if user_id in sessions and ep_num:
                sessions[user_id]["links"].append({"ep": ep_num, "link": voe_link})

            await wait.edit(
                "✅ Done!\n\n🎬 VoE Link:\n{}\n\n📁 {}\n📦 {}MB{}".format(
                    voe_link, filename, size_mb, session_info
                )
            )
        else:
            if user_id in sessions and ep_num:
                sessions[user_id]["ep_count"] -= 1
            await wait.edit("❌ VoE upload fail: {}".format(err))

    except Exception as e:
        logger.error("Error: {}".format(e))
        if user_id in sessions and ep_num:
            sessions[user_id]["ep_count"] -= 1
        await wait.edit("❌ Error: {}".format(str(e)[:300]))


if __name__ == "__main__":
    logger.info("Bot start ho raha hai...")
    app.run()
