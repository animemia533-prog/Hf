import os
import asyncio
import binascii
from pyrogram import Client, filters
from aiohttp import web

# Settings
API_ID = int(os.environ.get("API_ID", 31340851))
API_HASH = os.environ.get("API_HASH", "46161798cbd9a770749f51afa869b77b")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8891809367:AAFynilh5Iekf8V00Fd89lFBydM46kw1ezU")
BASE_URL = os.environ.get("BASE_URL", "https://hf-production-897a.up.railway.app")

app = Client("railway_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)

# 🎥 Streaming Logic with HEX Fix
async def stream_handler(request):
    try:
        hex_id = request.match_info.get('file_id')
        # Hex ko wapas asli File ID mein badalna
        file_id = binascii.unhexlify(hex_id).decode()
        
        response = web.StreamResponse()
        response.content_type = 'video/mp4'
        await response.prepare(request)

        async for chunk in app.stream_media(file_id):
            await response.write(chunk)
        return response
    except Exception as e:
        print(f"Error: {e}")
        return web.Response(text="Invalid Link or File", status=400)

# 🤖 Bot Handlers
@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("✅ **Bot Online!** Video bhejo link ke liye.")

@app.on_message(filters.private & (filters.video | filters.document))
async def handle_media(client, message):
    file_id = message.document.file_id if message.document else message.video.file_id
    
    # File ID ko Hex mein badalna (No symbols like _ or -)
    safe_id = binascii.hexlify(file_id.encode()).decode()
    stream_link = f"{BASE_URL}/{safe_id}"
    
    await message.reply_text(f"🎬 **Streaming Link:**\n`{stream_link}`")

async def main():
    web_app = web.Application()
    web_app.router.add_get("/{file_id}", stream_handler)
    runner = web.AppRunner(web_app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080))).start()

    await app.start()
    print("🤖 Bot is Online with HEX Fix!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
