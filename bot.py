import os
import asyncio
import base64
from pyrogram import Client, filters
from aiohttp import web

# Railway Variables
API_ID = int(os.environ.get("API_ID", 31340851))
API_HASH = os.environ.get("API_HASH", "46161798cbd9a770749f51afa869b77b")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8891809367:AAFynilh5Iekf8V00Fd89lFBydM46kw1ezU")
BASE_URL = os.environ.get("BASE_URL", "https://hf-production-897a.up.railway.app")

app = Client("railway_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True, ipv6=False)

# --- ENCODING HELPERS ---
def encode_id(s):
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")

def decode_id(s):
    padding = "=" * (4 - len(s) % 4)
    return base64.urlsafe_b64decode((s + padding).encode()).decode()

# --- STREAMING LOGIC ---
async def stream_handler(request):
    try:
        # URL se encoded ID nikal kar decode karna
        encoded_id = request.match_info.get('file_id')
        file_id = decode_id(encoded_id)
        
        response = web.StreamResponse()
        response.content_type = 'video/mp4'
        await response.prepare(request)

        # High-speed streaming chunks
        async for chunk in app.stream_media(file_id):
            await response.write(chunk)
        
        return response
    except Exception as e:
        print(f"❌ Stream Error: {e}")
        return web.Response(text="Video loading error. Try again.")

async def home(request):
    return web.Response(text="Bot is Active! ✅")

# --- BOT HANDLERS ---
@app.on_message(filters.private & (filters.video | filters.document))
async def handle_media(client, message):
    file_id = message.document.file_id if message.document else message.video.file_id
    
    # File ID ko safe tarike se encode karna
    safe_id = encode_id(file_id)
    stream_link = f"{BASE_URL}/{safe_id}"
    
    await message.reply_text(f"🎬 **Streaming Link Ready!**\n\n`{stream_link}`")

async def main():
    web_app = web.Application()
    web_app.router.add_get("/", home)
    web_app.router.add_get("/{file_id}", stream_handler)
    
    runner = web.AppRunner(web_app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    await web.TCPSite(runner, "0.0.0.0", port).start()

    await app.start()
    print("🤖 Bot Online with Fixes!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
