import os
import asyncio
from pyrogram import Client, filters
from aiohttp import web

# Railway Variables se data uthayega
API_ID = int(os.environ.get("API_ID", 31340851))
API_HASH = os.environ.get("API_HASH", "46161798cbd9a770749f51afa869b77b")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8891809367:AAFynilh5Iekf8V00Fd89lFBydM46kw1ezU")

app = Client(
    "railway_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True
)

async def health_check(request):
    return web.Response(text="Railway Bot is Alive! 🚀")

async def main():
    # Web server setup (Optional for Railway but good for logs)
    server = web.Application()
    server.router.add_get("/", health_check)
    runner = web.AppRunner(server)
    await runner.setup()
    
    # Railway automatically assigns a port, default is 8080
    port = int(os.environ.get("PORT", 8080))
    await web.TCPSite(runner, "0.0.0.0", port).start()

    await app.start()
    print("🤖 Bot is running on Railway!")
    await asyncio.Event().wait()

@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("✅ Railway Hosting Successful!")

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
