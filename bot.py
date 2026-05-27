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


async def get_telegram_direct_url(client, message):
    try:
        media = message.video or message.document or message.audio or message.voice or message.video_note
        if not media:
            return None
        # Pyrogram se direct CDN URL nikalo
        file = await client.get_file(media.file_id)
        return "https://api.telegram.org/file/bot{}/{}".format(BOT_TOKEN, file.file_path)
    except Exception as e:
        logger.error("URL error: {}".format(e))
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
            return None, "file_code nahi mila response mein"

        # Status check loop
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
                return None, "VoE upload fail: {}".format(sd)

        return None, "VoE timeout (10 min)"

    except Exception as e:
        logger.error("VoE: {}".format(e))
        return None, str(e)


app = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


@app.on_message(filters.command("start"))
async def start(client, message: Message):
    await message.reply(
        "👋 Hello!\n\nVideo ya file bhejo.\n"
        "Main seedha VoE pe upload karke streaming link dunga! 🎬\n\n"
        "2GB tak support hai!"
    )


@app.on_message(filters.video | filters.document | filters.audio | filters.voice | filters.video_note)
async def handle_file(client, message: Message):
    if message.video:
        media = message.video
        filename = media.file_name or "video_{}.mp4".format(media.file_unique_id)
        size = media.file_size or 0
    elif message.document:
        media = message.document
        filename = media.file_name or "doc_{}".format(media.file_unique_id)
        size = media.file_size or 0
    elif message.audio:
        media = message.audio
        filename = media.file_name or "audio_{}.mp3".format(media.file_unique_id)
        size = media.file_size or 0
    elif message.voice:
        media = message.voice
        filename = "voice_{}.ogg".format(media.file_unique_id)
        size = media.file_size or 0
    elif message.video_note:
        media = message.video_note
        filename = "vnote_{}.mp4".format(media.file_unique_id)
        size = media.file_size or 0
    else:
        return

    size_mb = round(size / 1024 / 1024, 1)

    wait = await message.reply(
        "File mili: {}\nSize: {}MB\n\nTelegram URL nikal raha hoon...".format(filename, size_mb)
    )

    try:
        # Telegram direct URL nikalo — koi download nahi
        direct_url = await get_telegram_direct_url(client, message)

        if not direct_url:
            await wait.edit("Telegram URL nahi mila. Dobara try karo.")
            return

        logger.info("Direct URL: {}".format(direct_url))

        if not VOE_KEY:
            await wait.edit("Direct URL:\n{}\n\nVOE_KEY set nahi hai Railway mein.".format(direct_url))
            return

        await wait.edit(
            "VoE pe upload ho raha hai...\nSize: {}MB\n\n(2-5 min lag sakta hai, wait karo)".format(size_mb)
        )

        voe_link, err = voe_remote_upload(direct_url, filename)

        if voe_link:
            await wait.edit(
                "Done!\n\n🎬 VoE Link:\n{}\n\nFile: {} - {}MB".format(voe_link, filename, size_mb)
            )
        else:
            await wait.edit(
                "VoE upload fail: {}\n\nDirect Telegram URL (temporary):\n{}".format(err, direct_url)
            )

    except Exception as e:
        logger.error("Error: {}".format(e))
        await wait.edit("Error: {}".format(str(e)[:300]))


if __name__ == "__main__":
    logger.info("Bot start ho raha hai...")
    app.run()
