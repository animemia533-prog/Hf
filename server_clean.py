import os
import base64
import asyncio
import aiohttp
from aiohttp import web
from pyrogram import Client
from pyrogram.errors import FloodWait, FileReferenceExpired, FileReferenceEmpty

BOT_TOKEN      = os.getenv("BOT_TOKEN", "")
API_ID         = int(os.getenv("API_ID", "0"))
API_HASH       = os.getenv("API_HASH", "")
STRING_SESSION = os.getenv("STRING_SESSION", "")
FIREBASE_URL   = os.getenv("FIREBASE_URL", "")
PORT           = int(os.getenv("PORT", 8080))

# Userbot — Saved Messages se stream karega
userbot = Client(
    "streamer",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=STRING_SESSION,
    no_updates=True,
)

def decode(enc: str) -> str:
    pad = 4 - len(enc) % 4
    if pad != 4:
        enc += "=" * pad
    return base64.urlsafe_b64decode(enc.encode()).decode()

def encode(file_id: str) -> str:
    return base64.urlsafe_b64encode(file_id.encode()).decode().rstrip("=")

async def refresh_from_firebase(enc: str) -> str | None:
    """Firebase se message fetch karke fresh file_id lo"""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{FIREBASE_URL}/Animes.json") as r:
                if r.status != 200:
                    return None
                data = await r.json()
        if not data:
            return None

        for anime, seasons in data.items():
            if not isinstance(seasons, dict):
                continue
            for season, episodes in seasons.items():
                if not isinstance(episodes, dict):
                    continue
                for ep, info in episodes.items():
                    if not isinstance(info, dict):
                        continue
                    if enc not in info.get("link", ""):
                        continue
                    chat_id    = info.get("chat_id")
                    message_id = info.get("message_id")
                    if not chat_id or not message_id:
                        return None
                    msg = await userbot.get_messages(int(chat_id), int(message_id))
                    if not msg:
                        return None
                    new_fid = None
                    if msg.video:
                        new_fid = msg.video.file_id
                    elif msg.document:
                        new_fid = msg.document.file_id
                    if new_fid:
                        # Firebase update
                        new_enc  = encode(new_fid)
                        new_link = info["link"].rsplit("/", 1)[0] + "/" + new_enc
                        async with aiohttp.ClientSession() as s:
                            await s.patch(
                                f"{FIREBASE_URL}/Animes/{anime}/{season}/{ep}.json",
                                json={"link": new_link}
                            )
                        print(f"✅ Refreshed: {anime}/{season}/{ep}")
                        return new_fid
    except Exception as e:
        print(f"Refresh error: {e}")
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

async def do_stream(request, file_id: str, enc: str, download: bool = False):
    range_header = request.headers.get("Range", "")
    offset = 0
    if range_header.startswith("bytes="):
        try:
            start = int(range_header[6:].split("-")[0])
            offset = start // (1024 * 1024)
        except:
            pass

    headers = {
        "Content-Type": "video/mp4",
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-cache",
    }
    if download:
        headers["Content-Disposition"] = "attachment; filename=video.mp4"

    for attempt in range(2):
        try:
            resp = web.StreamResponse(
                status=206 if range_header else 200,
                headers=headers
            )
            await resp.prepare(request)

            async for chunk in userbot.stream_media(file_id, offset=offset):
                try:
                    await resp.write(chunk)
                except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                    try: await resp.write_eof()
                    except: pass
                    return resp

            try: await resp.write_eof()
            except: pass
            return resp

        except (FileReferenceExpired, FileReferenceEmpty):
            if attempt == 0:
                print(f"⚠️ Expired — refreshing...")
                new_fid = await refresh_from_firebase(enc)
                if new_fid:
                    file_id = new_fid
                    continue
            # Refresh nahi hua
            return web.Response(
                text="<h3 style='font-family:sans-serif;text-align:center;margin-top:40vh;color:#ff4444'>❌ Link expire ho gaya!<br><small>Bot se dobara forward karo</small></h3>",
                content_type="text/html",
                status=410
            )

        except FloodWait as e:
            print(f"FloodWait: {e.value}s")
            await asyncio.sleep(e.value)
            break

        except Exception as e:
            err = str(e)
            if "closing transport" not in err and "Connection" not in err:
                print(f"Error: {err}")
            break

    return web.Response(text="Error", status=500)

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
    return await do_stream(request, file_id, enc)

async def handle_download(request):
    enc = request.match_info["enc"]
    try:
        file_id = decode(enc)
    except:
        return web.Response(text="Invalid", status=400)
    return await do_stream(request, file_id, enc, download=True)

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
    return await do_stream(request, file_id, enc)

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
    print(f"🌐 Server: http://0.0.0.0:{PORT}")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
