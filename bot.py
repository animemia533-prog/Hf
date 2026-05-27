import os
import requests
import logging
from pyrogram import Client, filters
from pyrogram.types import Message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")


def upload_to_gofile(file_bytes, filename):
    try:
        r = requests.get("https://api.gofile.io/servers", timeout=10)
        server = r.json()["data"]["servers"][0]["name"]
        r2 = requests.post(
            "https://{}.gofile.io/uploadFile".format(server),
            files={"file": (filename, file_bytes)},
            timeout=300
        )
        data = r2.json()
        if data.get("status") == "ok":
            return data["data"]["downloadPage"]
    except Exception as e:
        logger.error("Gofile: {}".format(e))
    return None


def upload_to_fileio(file_bytes, filename):
    try:
        r = requests.post(
            "https://file.io",
            files={"file": (filename, file_bytes)},
            data={"expires": "1d", "maxDownloads": 100},
            timeout=300
        )
        data = r.json()
        if data.get("success"):
            return data["link"]
    except Exception as e:
        logger.error("File.io: {}".format(e))
    return None


app = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


@app.on_message(filters.command("start"))
async def start(client, message: Message):
    await message.reply("👋 Hello! Koi bhi file bhejo — download link bana dunga! 🔗\n\n2GB tak files support hain!")


@app.on_message(filters.video | filters.document | filters.audio | filters.photo | filters.voice | filters.video_note)
async def handle_file(client, message: Message):
    if message.video:
        media = message.video
        filename = "video_{}.mp4".format(media.file_unique_id)
        size = media.file_size or 0
    elif message.document:
        media = message.document
        filename = media.file_name or "doc_{}".format(media.file_unique_id)
        size = media.file_size or 0
    elif message.audio:
        media = message.audio
        filename = media.file_name or "audio_{}.mp3".format(media.file_unique_id)
        size = media.file_size or 0
    elif message.photo:
        media = message.photo
        filename = "photo_{}.jpg".format(media.file_unique_id)
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
        "File mili: {}\nSize: {}MB\n\nDownload kar raha hoon...".format(filename, size_mb)
    )

    try:
        file_bytes = await client.download_media(message, in_memory=True)
        file_bytes = bytes(file_bytes.getvalue())

        await wait.edit("Upload ho raha hai gofile pe... ({}MB)".format(size_mb))
        link = upload_to_gofile(file_bytes, filename)

        if not link:
            await wait.edit("Backup server try kar raha hoon...")
            link = upload_to_fileio(file_bytes, filename)

        if link:
            await wait.edit(
                "Done!\n\nDownload Link:\n{}\n\nFile: {} - {}MB".format(link, filename, size_mb)
            )
        else:
            await wait.edit("Upload fail. Dobara try karo.")

    except Exception as e:
        logger.error("Error: {}".format(e))
        await wait.edit("Error: {}".format(str(e)[:300]))


if __name__ == "__main__":
    logger.info("Bot start ho raha hai...")
    app.run()
