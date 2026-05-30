import os
import asyncio
from pyrogram import Client, filters
from aiohttp import web

# Railway Variables
API_ID = int(os.environ.get("API_ID", 31340851))
API_HASH = os.environ.get("API_HASH", "46161798cbd9a770749f51afa869b77b")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8891809367:AAFynilh5Iekf8V00Fd89lFBydM46kw1ezU")

# --- FIX: Asli Link Yahan Daalein ---
BASE_URL = os.environ.get("BASE_URL", "https://hf-production-897a.up.railway.app")

app = Client(
    "railway_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True,
    ipv6=False 
)

# Web server logic
async def health_check(request):
    return web.Response(text="Railway Bot is Online! ✅")

async def stream_handler(request):
    f_id = request.match_info.get('file_id')
    return web.Response(text=f"Success! Server is reading File ID: {f_id}")

# Bot Handlers
@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply_text("🔥 **Bot Railway par Ready hai!**\n\nAb mujhe video bhejein.")

@app.on_message(filters.private & (filters.document | filters.video))
async def handle_file(client, message):
    file_id = message.document.file_id if message.document else message.video.file_id
    # Link generate ho raha hai asli domain ke saath
    final_link = f"{BASE_URL}/{file_id}"
    
    await message.reply_text(f"📥 **File Link Taiyar!**\n\n`{final_link}`")

async def main():
    web_app = web.Application()
    web_app.router.add_get("/", health_check)
    web_app.router.add_get("/{file_id}", stream_handler)
    
    runner = web.AppRunner(web_app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    await web.TCPSite(runner, "0.0.0.0", port).start()

    await app.start()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
