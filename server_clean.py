import os
import base64
import asyncio
import threading
from flask import Flask, Response, request, render_template_string
from pyrogram import Client

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_ID    = int(os.getenv("API_ID", "0"))
API_HASH  = os.getenv("API_HASH", "")

app = Flask(__name__)

_loop = asyncio.new_event_loop()

_client = Client(
    "streamer",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True,
)

def _start_client():
    asyncio.set_event_loop(_loop)
    _loop.run_until_complete(_client.start())
    print("✅ Pyrogram connected!")
    _loop.run_forever()

threading.Thread(target=_start_client, daemon=True).start()

# Flask start hone se pehle client ready hone do
import time
time.sleep(5)

def run(coro):
    return asyncio.run_coroutine_threadsafe(coro, _loop).result(timeout=60)

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
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a0f;display:flex;align-items:center;
     justify-content:center;min-height:100vh;font-family:sans-serif;color:#eee}
.w{width:100%;max-width:860px;padding:16px}
h2{text-align:center;color:#64b5f6;margin-bottom:14px}
video{width:100%;border-radius:10px;background:#000}
p{text-align:center;margin-top:10px;color:#666;font-size:.8rem}
</style></head><body>
<div class="w">
  <h2>🎬 Video Player</h2>
  <video controls autoplay playsinline preload="auto">
    <source src="/stream/{{enc}}" type="video/mp4">
  </video>
  <p>Telegram se directly stream ho raha hai</p>
</div>
</body></html>"""

def _make_stream(file_id: str, download: bool = False):
    range_header = request.headers.get("Range", "")
    offset = 0
    if range_header.startswith("bytes="):
        try:
            start = int(range_header[6:].split("-")[0])
            offset = start // (1024 * 1024)
        except:
            pass

    def generate():
        async def _gen():
            async for chunk in _client.stream_media(file_id, offset=offset):
                yield chunk

        agen = _gen().__aiter__()
        while True:
            try:
                fut = asyncio.run_coroutine_threadsafe(agen.__anext__(), _loop)
                chunk = fut.result(timeout=30)
                yield chunk
            except StopAsyncIteration:
                break
            except Exception as e:
                print(f"Chunk error: {e}")
                break

    headers = {
        "Content-Type": "video/mp4",
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-cache",
    }
    if download:
        headers["Content-Disposition"] = "attachment; filename=video.mp4"

    status = 206 if range_header else 200
    return Response(generate(), status=status, headers=headers)

@app.route("/")
def index():
    return "<h2 style='color:#64b5f6;text-align:center;margin-top:40vh;font-family:sans-serif'>🎬 TG Streamer — Ready!</h2>"

@app.route("/watch/<enc>")
def watch(enc):
    return render_template_string(PLAYER, enc=enc)

@app.route("/stream/<enc>", methods=["GET", "HEAD"])
def stream(enc):
    try:
        file_id = decode(enc)
    except:
        return "Invalid", 400
    if request.method == "HEAD":
        return Response(headers={"Content-Type": "video/mp4", "Accept-Ranges": "bytes"})
    return _make_stream(file_id)

@app.route("/download/<enc>")
def download(enc):
    try:
        return _make_stream(decode(enc), download=True)
    except:
        return "Error", 500

@app.route("/<enc>", methods=["GET", "HEAD"])
def clean_url(enc):
    if enc == "favicon.ico":
        return "", 404
    try:
        file_id = decode(enc)
    except:
        return "Invalid", 400
    if request.method == "HEAD":
        return Response(headers={"Content-Type": "video/mp4", "Accept-Ranges": "bytes"})
    return _make_stream(file_id)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    print(f"🌐 http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, threaded=True)
