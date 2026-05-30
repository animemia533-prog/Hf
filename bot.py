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

# --- SAFER ENCODING ---
def encode_id(s):
    # Base64 karke characters replace karna taaki URL mein dikkat na ho
    b = base64.urlsafe_b64encode(s.encode()).decode()
    return b.replace("=", "")

def decode_id(s):
    # Padding wapas add karna
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode()

# --- STABLE STREAMING ---
async def stream_handler(request):
    try:
        encoded_id = request.match_info.get('file_id')
        file_id = decode_id(encoded_id)
        
        response = web.StreamResponse()
        response.content_type = 'video/mp4'
        # Range headers support (Isse video seek/forward ho payegi)
        response.headers['Accept-Ranges'] = 'bytes'
        
        await response.prepare(request)

        async for chunk in app.stream_media(file_id):
            try:
                await response.write(chunk)
            except (ConnectionResetError, RuntimeError):
                # Agar user browser band kar de toh error na aaye
                break
        
        return response
    except Exception as e:
        print(f"❌ Error: {e}")
        return web.Response(text="Error loading video", status=500)

async def home(request):
    return web.Response(text="Streaming Server is Active! 🚀")

# --- BOT HANDLERS ---
@app.on_message(filters.private & (filters.video | filters.document))
async def handle_media(client, message):
    file_id = message.document.file_id if message.document else message.video.file_id
    
    # URL safe ID banana
    safe_id = encode_id(file_id)
    stream_link = f"{BASE_URL}/{safe_id}"
    
    await message.reply_text(f"✅ **Link Taiyar!**\n\n`{stream_link}`")

async def main():
    web_app = web.Application()
    web_app.router.add_get("/", home)
    web_app.router.add_get("/{file_id}", stream_handler)
    
    runner = web.AppRunner(web_app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    await web.TCPSite(runner, "0.0.0.0", port).start()

    await app.start()
    print("🤖 Bot Online with Stable Streaming!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
