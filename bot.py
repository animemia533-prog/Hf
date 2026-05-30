import os
import asyncio
from pyrogram import Client, filters
from aiohttp import web

# Railway Settings
API_ID = int(os.environ.get("API_ID", 31340851))
API_HASH = os.environ.get("API_HASH", "46161798cbd9a770749f51afa869b77b")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8891809367:AAFynilh5Iekf8V00Fd89lFBydM46kw1ezU")
BASE_URL = os.environ.get("BASE_URL", "https://hf-production-897a.up.railway.app")

app = Client("railway_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True, ipv6=False)

# --- STREAMING LOGIC ---
async def stream_handler(request):
    file_id = request.match_info.get('file_id')
    
    # Ye function Telegram se file ko stream karega
    async def file_sender():
        async for chunk in app.stream_media(file_id):
            yield chunk

    return web.Response(
        body=file_sender(),
        content_type='video/mp4' # Aap ise general document ke liye bhi badal sakte hain
    )

async def home(request):
    return web.Response(text="Bot is Online and Streaming! ✅")

# --- BOT HANDLERS ---
@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply_text("👋 Welcome! Send me any Video to get a direct streaming link.")

@app.on_message(filters.private & (filters.video | filters.document))
async def handle_media(client, message):
    file_id = message.document.file_id if message.document else message.video.file_id
    file_name = message.document.file_name if message.document else "video.mp4"
    
    stream_link = f"{BASE_URL}/{file_id}"
    
    await message.reply_text(
        f"🎬 **File Ready to Stream!**\n\n"
        f"📦 **Name:** `{file_name}`\n"
        f"🔗 **Link:** `{stream_link}`\n\n"
        f"⚡ *Note: Is link ko MX Player ya VLC mein paste karke bhi dekh sakte hain.*"
    )

async def main():
    web_app = web.Application()
    web_app.router.add_get("/", home)
    web_app.router.add_get("/{file_id}", stream_handler)
    
    runner = web.AppRunner(web_app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    await web.TCPSite(runner, "0.0.0.0", port).start()

    await app.start()
    print("🤖 Streaming Bot Started!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
