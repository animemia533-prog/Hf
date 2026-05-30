import os
import asyncio
from pyrogram import Client, filters
from aiohttp import web

# Railway Variables (Inhe Railway dashboard mein set karna mat bhulna)
API_ID = int(os.environ.get("API_ID", 31340851))
API_HASH = os.environ.get("API_HASH", "46161798cbd9a770749f51afa869b77b")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8891809367:AAFynilh5Iekf8V00Fd89lFBydM46kw1ezU")

# Aapka Railway app ka URL (e.g., https://your-app-production.up.railway.app)
# Ise Railway settings se copy karke Variables mein daalein
BASE_URL = os.environ.get("BASE_URL", "https://your-railway-url.com")

app = Client(
    "railway_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True,
    ipv6=False 
)

# --- Web Server ---
async def health_check(request):
    return web.Response(text="Streaming Bot is Active on Railway! ✅")

async def stream_handler(request):
    f_id = request.match_info.get('file_id')
    return web.Response(text=f"Server Working! File ID: {f_id}")

# --- Bot Handlers ---
@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply_text("🔥 **Railway se Connect ho gaya hoon!**\n\nAb mujhe koi video ya file bhejo.")

@app.on_message(filters.private & (filters.document | filters.video))
async def handle_file(client, message):
    file_id = message.document.file_id if message.document else message.video.file_id
    file_name = message.document.file_name if message.document else "video.mp4"
    
    # Asli Link Generation
    # Dhyan rahe BASE_URL settings mein hona chahiye
    final_link = f"{BASE_URL}/{file_id}"
    
    await message.reply_text(
        f"📥 **File mil gayi!**\n\n"
        f"**Name:** `{file_name}`\n"
        f"**Link:** `{final_link}`\n\n"
        "Note: Abhi yeh link sirf testing ke liye hai."
    )

async def main():
    web_app = web.Application()
    web_app.router.add_get("/", health_check)
    web_app.router.add_get("/{file_id}", stream_handler)
    
    runner = web.AppRunner(web_app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    await web.TCPSite(runner, "0.0.0.0", port).start()

    await app.start()
    print("🤖 Bot Online!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
