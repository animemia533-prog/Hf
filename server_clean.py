import os
import base64
import asyncio
import aiohttp
from aiohttp import web
from pyrogram import Client
from pyrogram.errors import FloodWait

BOT_TOKEN      = os.getenv("BOT_TOKEN", "")
API_ID         = int(os.getenv("API_ID", "0"))
API_HASH       = os.getenv("API_HASH", "")
STRING_SESSION = os.getenv("STRING_SESSION", "")
FIREBASE_URL   = os.getenv("FIREBASE_URL", "")
PORT           = int(os.getenv("PORT", 8080))

STORAGE_CHANNEL = -1003753814792  # Fixed storage channel ID

userbot = Client(
    "streamer",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=STRING_SESSION,
    no_updates=True,
)

def decode(enc: str) -> tuple[int, int]:
    """base64 decode karke (chat_id, message_id) return karo"""
    pad = 4 - len(enc) % 4
    if pad != 4:
        enc += "=" * pad
    raw = base64.urlsafe_b64decode(enc.encode()).decode()
    chat_id, message_id = raw.split(":")
    return int(chat_id), int(message_id)

async def get_message(enc: str):
    """Directly storage channel se message lo — no Firebase lookup needed"""
    try:
        chat_id, message_id = decode(enc)
        msg = await userbot.get_messages(chat_id, message_id)
        return msg
    except Exception as e:
        print(f"get_message error: {e}")
        return None

PLAYER = """<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stream</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#000;display:flex;align-items:center;justify-content:center;min-height:100vh}}
video{{width:100%;max-height:100vh}}
</style></head><body>
<video controls autoplay playsinline preload="metadata">
  <source src="/stream/{enc}" type="video/mp4">
</video>
</body></html>"""

async def do_stream(request, enc: str, download: bool = False):
    range_header = request.headers.get("Range", "")
    offset = 0
    if range_header.startswith("bytes="):
        try:
            start = int(range_header[6:].split("-")[0])
            offset = start // (1024 * 1024)
        except:
            pass

    headers = {
        "Content-Type":  "video/mp4",
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-cache",
    }
    if download:
        headers["Content-Disposition"] = "attachment; filename=video.mp4"

    # Storage channel se directly message lo
    msg = await get_message(enc)
    if not msg or not msg.id:
        return web.Response(
            text="Video nahi mila — bot se dobara forward karo",
            status=404
        )

    try:
        resp = web.StreamResponse(
            status=206 if range_header else 200,
            headers=headers
        )
        await resp.prepare(request)

        async for chunk in userbot.stream_media(msg, offset=offset):
            try:
                await resp.write(chunk)
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                break

        try: await resp.write_eof()
        except: pass
        return resp

    except FloodWait as e:
        await asyncio.sleep(e.value)
        return web.Response(text="Server busy, retry karo", status=503)
    except Exception as e:
        print(f"Stream error: {e}")
        return web.Response(text="Stream error", status=500)

async def handle_index(request):
    return web.Response(
        text="<h2 style='color:#64b5f6;text-align:center;margin-top:40vh;font-family:sans-serif'>🎬 TG Streamer</h2>",
        content_type="text/html"
    )

async def handle_watch(request):
    enc = request.match_info["enc"]
    return web.Response(text=PLAYER.format(enc=enc), content_type="text/html")

async def handle_stream(request):
    enc = request.match_info["enc"]
    if request.method == "HEAD":
        return web.Response(headers={"Content-Type": "video/mp4", "Accept-Ranges": "bytes"})
    return await do_stream(request, enc)

async def handle_download(request):
    enc = request.match_info["enc"]
    return await do_stream(request, enc, download=True)

async def handle_clean(request):
    enc = request.match_info["enc"]
    if enc == "favicon.ico":
        return web.Response(status=404)
    if request.method == "HEAD":
        return web.Response(headers={"Content-Type": "video/mp4", "Accept-Ranges": "bytes"})
    return await do_stream(request, enc)

async def main():
    await userbot.start()
    me = await userbot.get_me()
    print(f"✅ Userbot: {me.first_name}")
    print(f"📦 Storage Channel: {STORAGE_CHANNEL}")

    app = web.Application(client_max_size=0)
    app.router.add_get("/", handle_index)
    app.router.add_get("/watch/{enc}", handle_watch)
    app.router.add_route("*", "/stream/{enc}", handle_stream)
    app.router.add_get("/download/{enc}", handle_download)
    app.router.add_route("*", "/{enc}", handle_clean)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"🌐 Ready: http://0.0.0.0:{PORT}")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
