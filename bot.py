import os
import time
import requests
import logging
from pyrogram import Client, filters
from pyrogram.types import Message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
VOE_KEY = os.environ.get("VOE_KEY", "")


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


def upload_to_tmpfiles(file_bytes, filename):
    try:
        r = requests.post(
            "https://tmpfiles.org/api/v1/upload",
            files={"file": (filename, file_bytes)},
            timeout=300
        )
        data = r.json()
        logger.info("tmpfiles: {}".format(data))
        if data.get("status") == "success":
            page_url = data["data"]["url"]
            direct_url = page_url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
            return direct_url
    except Exception as e:
        logger.error("tmpfiles: {}".format(e))
    return None


def voe_remote_upload(direct_url, filename):
    try:
        r = requests.get(
            "https://voe.sx/api/upload/url",
            params={"key": VOE_KEY, "url": direct_url, "name": filename},
            timeout=30
        )
        data = r.json()
        logger.info("VoE start: {}".format(data))

        if not data.get("status"):
            return None, "VoE start fail: {}".format(data)

        file_code = data.get("file_code") or data.get("filecode")
        if not file_code:
            return None, "file_code nahi mila"

        for i in range(120):
            time.sleep(5)
            sr = requests.get(
                "https://voe.sx/api/upload/url/status",
                params={"key": VOE_KEY, "file_code": file_code},
                timeout=15
            )
            sd = sr.json()
            logger.info("VoE status {}: {}".format(i, sd))
            s = str(sd.get("status", "")).lower()
            if s == "done" or sd.get("completed") or s == "200":
                return "https://voe.sx/{}".format(file_code), None
            elif s in ["error", "failed", "404"]:
                return None, "VoE fail: {}".format(sd)

        return None, "VoE timeout"
    except Exception as e:
        logger.error("VoE: {}".format(e))
        return None, str(e)


app = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


@app.on_message(filters.command("start"))
async def start(client, message: Message):
    await message.reply("👋 Hello! Video ya file bhejo — VoE streaming link milega! 🎬")


@app.on_message(filters.video | filters.document | filters.audio | filters.voice | filters.video_note)
async def handle_file(client, message: Message):
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
    elif message.audio:
        media = message.audio
        filename = media.file_name or "audio_{}.mp3".format(media.file_unique_id)
        size = media.file_size or 0
        file_id = media.file_id
    elif message.voice:
        media = message.voice
        filename = "voice_{}.ogg".format(media.file_unique_id)
        size = media.file_size or 0
        file_id = media.file_id
    elif message.video_note:
        media = message.video_note
        filename = "vnote_{}.mp4".format(media.file_unique_id)
        size = media.file_size or 0
        file_id = media.file_id
    else:
        return

    size_mb = round(size / 1024 / 1024, 1)
    wait = await message.reply(
        "📥 File mili!\n📁 {}\n📦 {}MB\n\nShuru ho raha hai...".format(filename, size_mb)
    )

    try:
        direct_url = get_telegram_url(file_id)

        if not direct_url:
            # Badi file — progress ke saath download karo
            last_update = [0]

            async def progress(current, total):
                now = time.time()
                if now - last_update[0] < 3:
                    return
                last_update[0] = now
                bar = progress_bar(current, total)
                try:
                    await wait.edit(
                        "📥 Telegram se download ho raha hai...\n\n{}\n\n⏳ Thoda wait karo...".format(bar)
                    )
                except Exception:
                    pass

            await wait.edit(
                "📥 Telegram se download ho raha hai...\n\n[░░░░░░░░░░░░░░░░░░░░] 0%\n0 MB / {} MB\n\n⏳ Thoda wait karo...".format(size_mb)
            )

            file_data = await client.download_media(message, in_memory=True, progress=progress)
            file_bytes = bytes(file_data.getvalue())

            await wait.edit(
                "✅ Download complete!\n📦 {}MB\n\n⬆️ Temporary server pe upload ho raha hai...".format(size_mb)
            )
            direct_url = upload_to_tmpfiles(file_bytes, filename)

            if not direct_url:
                await wait.edit("❌ Temporary upload fail. Dobara try karo.")
                return

        logger.info("Direct URL: {}".format(direct_url))

        if not VOE_KEY:
            await wait.edit("🔗 URL:\n{}\n\n⚠️ VOE_KEY set nahi hai.".format(direct_url))
            return

        await wait.edit(
            "🎬 VoE pe upload ho raha hai...\n📦 {}MB\n\n[░░░░░░░░░░░░░░░░░░░░]\n⏳ 2-5 min lag sakta hai...".format(size_mb)
        )

        voe_link, err = voe_remote_upload(direct_url, filename)

        if voe_link:
            await wait.edit(
                "✅ Done!\n\n🎬 VoE Streaming Link:\n{}\n\n📁 File: {}\n📦 Size: {}MB".format(
                    voe_link, filename, size_mb
                )
            )
        else:
            await wait.edit(
                "⚠️ VoE issue: {}\n\n🔗 Temp link:\n{}".format(err, direct_url)
            )

    except Exception as e:
        logger.error("Error: {}".format(e))
        await wait.edit("❌ Error: {}".format(str(e)[:300]))


if __name__ == "__main__":
    logger.info("Bot start ho raha hai...")
    app.run()
