import os
import base64
import asyncio
from aiohttp import web
from pyrogram import Client
from pyrogram.errors import FloodWait

BOT_TOKEN      = os.getenv("BOT_TOKEN", "")
API_ID         = int(os.getenv("API_ID", "0"))
API_HASH       = os.getenv("API_HASH", "")
STRING_SESSION = os.getenv("STRING_SESSION", "")
PORT           = int(os.getenv("PORT", 8080))

# Userbot — string session se (fast, no size limit)
userbot = Client(
    "userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=STRING_SESSION,
    no_updates=True,  # Updates ki zaroorat nahi server ko
)

def decode(enc: str) -> str:
    pad = 4 - len(enc) % 4
    if pad != 4:
        enc += "=" * pad
    return base64.urlsafe_b64decode(enc.encode()).decode()

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

async def stream_file(request, file_id: str, download: bool = False):
    range_header = request.headers.get("Range", "")
    offset = 0

    if range_header.startswith("bytes="):
        try:
            start = int(range_header[6:].split("-")[0])
            offset = start // (1024 * 1024)
        except:
            pass

    resp_headers = {
        "Content-Type": "video/mp4",
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-cache",
    }
    if download:
        resp_headers["Content-Disposition"] = "attachment; filename=video.mp4"

    response = web.StreamResponse(
        status=206 if range_header else 200,
        headers=resp_headers
    )
    await response.prepare(request)

    try:
        async for chunk in userbot.stream_media(file_id, offset=offset):
            try:
                await response.write(chunk)
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                break
    except FloodWait as e:
        print(f"FloodWait: {e.value}s")
        await asyncio.sleep(e.value)
    except Exception as e:
        err = str(e)
        if "closing transport" not in err and "Connection" not in err:
            print(f"Stream error: {err}")

    try:
        await response.write_eof()
    except:
        pass
    return response

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
    try:
        file_id = decode(enc)
    except:
        return web.Response(text="Invalid", status=400)
    if request.method == "HEAD":
        return web.Response(headers={"Content-Type": "video/mp4", "Accept-Ranges": "bytes"})
    return await stream_file(request, file_id)

async def handle_download(request):
    enc = request.match_info["enc"]
    try:
        file_id = decode(enc)
    except:
        return web.Response(text="Invalid", status=400)
    return await stream_file(request, file_id, download=True)

async def handle_clean(request):
    enc = request.match_info["enc"]
    if enc == "favicon.ico":
        return web.Response(status=404)
    try:
        file_id = decode(enc)
    except:
        return web.Response(text="Invalid", status=400)
    if request.method == "HEAD":
        return web.Response(headers={"Content-Type": "video/mp4", "Accept-Ranges": "bytes"})
    return await stream_file(request, file_id)

async def main():
    print("🔗 Userbot connect ho raha hai...")
    await userbot.start()
    me = await userbot.get_me()
    print(f"✅ Userbot ready: {me.first_name}")

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
    print(f"🌐 Server ready: http://0.0.0.0:{PORT}")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
