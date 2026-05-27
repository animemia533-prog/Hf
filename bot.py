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


def get_file_path_via_api(file_id):
    try:
        r = requests.get(
            "https://api.telegram.org/bot{}/getFile".format(BOT_TOKEN),
            params={"file_id": file_id},
            timeout=30
        )
        data = r.json()
        logger.info("getFile response: {}".format(data))
        if data.get("ok"):
            file_path = data["result"]["file_path"]
            return "https://api.telegram.org/file/bot{}/{}".format(BOT_TOKEN, file_path)
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
                return None, "VoE upload fail: {}".format(sd)

        return None, "VoE timeout"

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
        "File mili: {}\nSize: {}MB\n\nURL nikal raha hoon...".format(filename, size_mb)
    )

    # Bot API se direct URL nikalo (20MB limit apply hogi sirf getFile pe)
    direct_url = get_file_path_via_api(file_id)

    if not direct_url:
        # 20MB se badi file hai — Pyrogram se download karke upload karna hoga
        await wait.edit(
            "File badi hai ({}MB), Telegram se download kar raha hoon...\n"
            "(Ye 2-5 min le sakta hai)".format(size_mb)
        )
        try:
            file_bytes = await client.download_media(message, in_memory=True)
            file_bytes = bytes(file_bytes.getvalue())

            # Gofile pe upload karo direct link ke liye
            await wait.edit("Intermediate upload ho raha hai...")
            r = requests.get("https://api.gofile.io/servers", timeout=10)
            server = r.json()["data"]["servers"][0]["name"]
            r2 = requests.post(
                "https://{}.gofile.io/uploadFile".format(server),
                files={"file": (filename, file_bytes)},
                timeout=300
            )
            gdata = r2.json()
            if gdata.get("status") == "ok":
                direct_url = gdata["data"].get("directLink", "")
                if not direct_url:
                    await wait.edit(
                        "Gofile link (direct nahi mila):\n{}".format(gdata["data"]["downloadPage"])
                    )
                    return
            else:
                await wait.edit("Intermediate upload fail. Dobara try karo.")
                return
        except Exception as e:
            await wait.edit("Download error: {}".format(str(e)[:200]))
            return

    if not VOE_KEY:
        await wait.edit("Direct URL:\n{}\n\nVOE_KEY Railway mein set karo.".format(direct_url))
        return

    await wait.edit(
        "VoE pe upload ho raha hai...\nSize: {}MB\n(2-5 min wait karo)".format(size_mb)
    )

    voe_link, err = voe_remote_upload(direct_url, filename)

    if voe_link:
        await wait.edit(
            "Done! 🎬\n\nVoE Link:\n{}\n\nFile: {} - {}MB".format(voe_link, filename, size_mb)
        )
    else:
        await wait.edit(
            "VoE issue: {}\n\nTemp URL:\n{}".format(err, direct_url)
        )


if __name__ == "__main__":
    logger.info("Bot start ho raha hai...")
    app.run()
