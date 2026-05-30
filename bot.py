import os
import asyncio
from pyrogram import Client, filters
from aiohttp import web

# Railway Variables
API_ID = int(os.environ.get("API_ID", 31340851))
API_HASH = os.environ.get("API_HASH", "46161798cbd9a770749f51afa869b77b")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8891809367:AAFynilh5Iekf8V00Fd89lFBydM46kw1ezU")

app = Client(
    "railway_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True,
    ipv6=False  # <--- Ye line IPv6 block ko bypass karegi
)

# Web server for Railway health check
async def health_check(request):
    return web.Response(text="Bot is Alive on Railway! ✅")

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    print(f"Start command received from: {message.from_user.id}")
    await message.reply_text("🔥 **Railway se Connect ho gaya hoon!**")

@app.on_message(filters.private & (filters.document | filters.video))
async def handle_file(client, message):
    await message.reply_text("✅ File mil gayi! System working.")

async def main():
    # Web server logic
    web_app = web.Application()
    web_app.router.add_get("/", health_check)
    runner = web.AppRunner(web_app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    await web.TCPSite(runner, "0.0.0.0", port).start()

    print("🚀 Connecting to Telegram...")
    await app.start()
    print("🤖 Bot is officially ONLINE on Railway!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    # Stable loop for Railway
    asyncio.get_event_loop().run_until_complete(main())
