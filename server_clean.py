import os
import base64
import asyncio
from aiohttp import web
from pyrogram import Client

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_ID    = int(os.getenv("API_ID", "0"))
API_HASH  = os.getenv("API_HASH", "")
PORT      = int(os.getenv("PORT", 8080))

client = Client(
    "streamer",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True,
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
body{{background:#0a0a0f;display:flex;align-items:center;
     justify-content:center;min-height:100vh;font-family:sans-serif;color:#eee}}
.w{{width:100%;max-width:860px;padding:16px}}
h2{{text-align:center;color:#64b5f6;margin-bottom:14px}}
video{{width:100%;border-radius:10px;background:#000}}
p{{text-align:center;margin-top:10px;color:#666;font-size:.8rem}}
</style></head><body>
<div class="w">
  <h2>🎬 Video Player</h2>
  <video controls autoplay playsinline preload="auto">
    <source src="/stream/{enc}" type="video/mp4">
  </video>
  <p>Telegram se directly stream ho raha hai</p>
</div>
</body></html>"""

async def stream_file(request, file_id: str, download: bool = False):
    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "video/mp4",
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-cache",
            **({"Content-Disposition": "attachment; filename=video.mp4"} if download else {}),
        }
    )
    await response.prepare(request)
    try:
        async for chunk in client.stream_media(file_id):
            await response.write(chunk)
    except Exception as e:
        print(f"Stream error: {e}")
    await response.write_eof()
    return response

async def handle_watch(request):
    enc = request.match_info["enc"]
    html = PLAYER.format(enc=enc)
    return web.Response(text=html, content_type="text/html")

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

async def handle_index(request):
    return web.Response(
        text="<h2 style='color:#64b5f6;text-align:center;margin-top:40vh;font-family:sans-serif'>🎬 TG Streamer — Ready!</h2>",
        content_type="text/html"
    )

async def main():
    await client.start()
    print("✅ Pyrogram connected!")

    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/watch/{enc}", handle_watch)
    app.router.add_route("*", "/stream/{enc}", handle_stream)
    app.router.add_get("/download/{enc}", handle_download)
    app.router.add_route("*", "/{enc}", handle_clean)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"🌐 Server ready on port {PORT}")

    await asyncio.Event().wait()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
