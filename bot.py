import os
import requests
import logging
from flask import Flask, request as freq
import telebot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
SPACE_URL = os.environ.get("SPACE_URL", "").rstrip("/")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)


def upload_to_gofile(file_bytes, filename):
    try:
        r = requests.get("https://api.gofile.io/servers", timeout=10)
        server = r.json()["data"]["servers"][0]["name"]
        r2 = requests.post(
            "https://{}.gofile.io/uploadFile".format(server),
            files={"file": (filename, file_bytes)},
            timeout=120
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
            timeout=120
        )
        data = r.json()
        if data.get("success"):
            return data["link"]
    except Exception as e:
        logger.error("File.io: {}".format(e))
    return None


def get_file_info(message):
    if message.video:
        f = message.video
        return f.file_id, f.file_unique_id, "video_{}.mp4".format(f.file_unique_id), f.file_size or 0
    elif message.document:
        f = message.document
        return f.file_id, f.file_unique_id, f.file_name or "doc_{}".format(f.file_unique_id), f.file_size or 0
    elif message.audio:
        f = message.audio
        return f.file_id, f.file_unique_id, "audio_{}.mp3".format(f.file_unique_id), f.file_size or 0
    elif message.photo:
        f = message.photo[-1]
        return f.file_id, f.file_unique_id, "photo_{}.jpg".format(f.file_unique_id), f.file_size or 0
    elif message.voice:
        f = message.voice
        return f.file_id, f.file_unique_id, "voice_{}.ogg".format(f.file_unique_id), f.file_size or 0
    elif message.video_note:
        f = message.video_note
        return f.file_id, f.file_unique_id, "vnote_{}.mp4".format(f.file_unique_id), f.file_size or 0
    return None, None, None, 0


@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(message, "👋 Hello! File ya video bhejo, main download link bana dunga! 🔗")


@bot.message_handler(content_types=["video", "document", "audio", "photo", "voice", "video_note"])
def handle_file(message):
    file_id, unique_id, filename, size = get_file_info(message)
    if not file_id:
        bot.reply_to(message, "Ye file type support nahi hai.")
        return

    size_mb = round(size / 1024 / 1024, 1)
    wait = bot.reply_to(message, "File mili: {}\nSize: {}MB\nLink bana raha hoon...".format(filename, size_mb))

    if size > 20 * 1024 * 1024:
        bot.edit_message_text(
            "File {}MB ki hai. Bot API 20MB se badi files allow nahi karta.".format(size_mb),
            message.chat.id, wait.message_id
        )
        return

    try:
        file_info = bot.get_file(file_id)
        file_bytes = bot.download_file(file_info.file_path)

        bot.edit_message_text("Upload ho raha hai...", message.chat.id, wait.message_id)
        link = upload_to_gofile(file_bytes, filename)

        if not link:
            bot.edit_message_text("Backup try kar raha hoon...", message.chat.id, wait.message_id)
            link = upload_to_fileio(file_bytes, filename)

        if link:
            bot.edit_message_text(
                "Done!\n\nDownload Link:\n{}\n\nFile: {} - {}MB".format(link, filename, size_mb),
                message.chat.id, wait.message_id
            )
        else:
            bot.edit_message_text("Upload fail. Dobara try karo.", message.chat.id, wait.message_id)

    except Exception as e:
        logger.error("Error: {}".format(e))
        bot.edit_message_text("Error: {}".format(str(e)[:200]), message.chat.id, wait.message_id)


@app.route("/{}".format(BOT_TOKEN), methods=["POST"])
def webhook():
    update = telebot.types.Update.de_json(freq.get_json())
    bot.process_new_updates([update])
    return "OK", 200


@app.route("/")
def index():
    return "Bot is running!", 200


if __name__ == "__main__":
    if SPACE_URL:
        webhook_url = "{}/{}".format(SPACE_URL, BOT_TOKEN)
        bot.remove_webhook()
        bot.set_webhook(url=webhook_url)
        logger.info("Webhook set: {}".format(webhook_url))
        app.run(host="0.0.0.0", port=7860)
    else:
        logger.info("Polling mode")
        bot.remove_webhook()
        bot.infinity_polling()
