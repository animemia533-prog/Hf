import os
import base64
import asyncio
import threading
from flask import Flask, Response, redirect, request, render_template_string
from pyrogram import Client
from pyrogram.errors import FloodWait
import time

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")

# Pyrogram client (bot mode - no size limit for streaming)
pyro_client = Client(
    "stream_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True
)

loop = asyncio.new_event_loop()

def start_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

threading.Thread(target=start_loop, args=(loop,), daemon=True).start()

def run_async(coro):
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=30)

def start_pyrogram():
    run_async(pyro_client.start())
    print("✅ Pyrogram client started!")

PLAYER_HTML = """<!DOCTYPE html>
<html><head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Stream</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{background:#0a0a0f;display:flex;align-items:center;justify-content:center;min-height:100vh;font-family:sans-serif;color:#eee}
        .wrap{width:100%;max-width:860px;padding:16px}
        h2{text-align:center;color:#64b5f6;margin-bottom:14px;font-size:1.2rem}
        video{width:100%;border-radius:10px;background:#000;box-shadow:0 4px 30px rgba(0,0,0,.5)}
        p{text-align:center;margin-top:10px;color:#666;font-size:.8rem}
    </style>
</head>
<body>
<div class="wrap">
    <h2>🎬 Video Player</h2>
    <video controls autoplay playsinline preload="metadata">
        <source src="/stream/{{ enc }}" type="video/mp4">
    </video>
    <p>Telegram se stream ho raha hai</p>
</div>
</body></html>"""

def decode(encoded: str) -> str:
    pad = 4 - len(encoded) % 4
    if pad != 4:
        encoded += "=" * pad
    return base64.urlsafe_b64decode(encoded.encode()).decode()

async def get_file_stream(file_id: str, offset: int = 0, limit: int = None):
    """Pyrogram se file stream karo - koi size limit nahi"""
    async for chunk in pyro_client.stream_media(file_id, offset=offset, limit=limit):
        yield chunk

@app.route("/")
def index():
    return "<h2 style='color:#64b5f6;text-align:center;margin-top:40vh;font-family:sans-serif'>🎬 TG Streamer - Ready!</h2>"

@app.route("/<encoded>")
def clean_stream(encoded):
    if encoded in ("watch", "stream", "download", "favicon.ico"):
        return "Not found", 404
    try:
        file_id = decode(encoded)
    except Exception:
        return "Invalid link", 400
    return _do_stream(file_id)

@app.route("/stream/<encoded>")
def stream(encoded):
    try:
        file_id = decode(encoded)
    except Exception:
        return "Invalid link", 400
    return _do_stream(file_id)

@app.route("/watch/<encoded>")
def watch(encoded):
    return render_template_string(PLAYER_HTML, enc=encoded)

@app.route("/download/<encoded>")
def download(encoded):
    try:
        file_id = decode(encoded)
    except Exception:
        return "Invalid link", 400
    return _do_stream(file_id, download=True)

def _do_stream(file_id: str, download: bool = False):
    range_header = request.headers.get("Range", "")
    
    offset = 0
    limit = None
    status = 200
    content_range = None

    # File size pata karo
    try:
        msg_info = run_async(pyro_client.get_messages(
            # dummy - we use stream_media directly
            "me", 1
        ))
    except:
        pass

    # Range header parse karo
    if range_header and range_header.startswith("bytes="):
        try:
            ranges = range_header[6:].split("-")
            start = int(ranges[0]) if ranges[0] else 0
            # 1MB chunks mein stream karo
            offset = start // (1024 * 1024)
            status = 206
        except:
            pass

    def generate():
        try:
            async def stream_gen():
                async for chunk in pyro_client.stream_media(file_id, offset=offset):
                    yield chunk

            # Sync wrapper
            agen = stream_gen()
            while True:
                try:
                    chunk = run_async(agen.__anext__())
                    yield chunk
                except StopAsyncIteration:
                    break
                except Exception as e:
                    print(f"Stream error: {e}")
                    break
        except Exception as e:
            print(f"Generate error: {e}")

    headers = {
        "Content-Type": "video/mp4",
        "Accept-Ranges": "bytes",
    }
    
    if download:
        headers["Content-Disposition"] = "attachment"

    return Response(generate(), status=status, headers=headers)

if __name__ == "__main__":
    print("🚀 Pyrogram client start ho raha hai...")
    start_pyrogram()
    port = int(os.getenv("PORT", 8080))
    print(f"🌐 Server: http://localhost:{port}")
    app.run(host="0.0.0.0", port=port)
