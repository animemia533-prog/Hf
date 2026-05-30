import os
import asyncio
from pyrogram import Client, filters
from aiohttp import web

# Variables
API_ID = int(os.environ.get("API_ID", 31340851))
API_HASH = os.environ.get("API_HASH", "46161798cbd9a770749f51afa869b77b")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "Yahan_Naya_Token_Daalein")
BASE_URL = os.environ.get("BASE_URL", "https://hf-production-897a.up.railway.app")

app = Client(
    "railway_final",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True
)

@app.on_message(filters.command("start"))
async def start(client, message):
    print(f"Start command received from {message.from_user.id}")
    await message.reply_text("👋 **Bot Active Hai!** Railway par link generation chalu hai.")

@app.on_message(filters.private & (filters.video | filters.document))
async def handle_media(client, message):
    file_id = message.document.file_id if message.document else message.video.file_id
    # Simple direct ID link (No encoding issues)
    stream_link = f"{BASE_URL}/{file_id}"
    await message.reply_text(f"🎬 **Direct Link:**\n`{stream_link}`")

async def main():
    # Web server for health check
    web_app = web.Application()
    web_app.router.add_get("/", lambda r: web.Response(text="Running"))
    web_app.router.add_get("/{file_id}", lambda r: web.Response(text="Streaming..."))
    
    runner = web.AppRunner(web_app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080))).start()

    print("🚀 Bot starting...")
    await app.start()
    
    # Connection test
    me = await app.get_me()
    print(f"✅ Logged in as @{me.username}")
    
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
