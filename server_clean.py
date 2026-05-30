import os
import base64
import asyncio
from flask import Flask, Response, redirect, request, render_template_string
from pyrogram import Client

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")

# Single event loop
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

pyro = Client(
    "streamer",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True
)

# Pyrogram start karo — blocking se pehle
loop.run_until_complete(pyro.start())
print("✅ Pyrogram ready!")

PLAYER_HTML = """<!DOCTYPE html>
<html><head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Stream</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{background:#0a0a0f;display:flex;align-items:center;justify-content:center;min-height:100vh;font-family:sans-serif;color:#eee}
        .wrap{width:100%;max-width:860px;padding:16px}
        h2{text-align:center;color:#64b5f6;margin-bottom:14px}
        video{width:100%;border-radius:10px;background:#000}
        p{text-align:center;margin-top:10px;color:#666;font-size:.8rem}
    </style>
</head><body>
<div class="wrap">
    <h2>🎬 Video Player</h2>
    <video controls autoplay playsinline preload="metadata">
        <source src="/stream/{{ enc }}" type="video/mp4">
    </video>
    <p>Telegram se directly stream ho raha hai</p>
</div>
</body></html>"""

def decode(encoded: str) -> str:
    pad = 4 - len(encoded) % 4
    if pad != 4:
        encoded += "=" * pad
    return base64.urlsafe_b64decode(encoded.encode()).decode()

def _stream_response(file_id: str, download: bool = False):
    def generate():
        async def _gen():
            async for chunk in pyro.stream_media(file_id):
                yield chunk
        
        agen = _gen().__aiter__()
        while True:
            try:
                chunk = loop.run_until_complete(agen.__anext__())
                yield chunk
            except StopAsyncIteration:
                break
            except Exception as e:
                print(f"Stream error: {e}")
                break

    headers = {
        "Content-Type": "video/mp4",
        "Accept-Ranges": "bytes",
    }
    if download:
        headers["Content-Disposition"] = "attachment"
    
    return Response(generate(), status=200, headers=headers)

@app.route("/")
def index():
    return "<h2 style='color:#64b5f6;text-align:center;margin-top:40vh;font-family:sans-serif'>🎬 TG Streamer</h2>"

@app.route("/watch/<enc>")
def watch(enc):
    return render_template_string(PLAYER_HTML, enc=enc)

@app.route("/stream/<enc>")
def stream(enc):
    try:
        file_id = decode(enc)
    except:
        return "Invalid link", 400
    return _stream_response(file_id)

@app.route("/download/<enc>")
def download(enc):
    try:
        file_id = decode(enc)
    except:
        return "Invalid link", 400
    return _stream_response(file_id, download=True)

@app.route("/<enc>")
def clean_url(enc):
    if enc in ("favicon.ico",):
        return "", 404
    try:
        file_id = decode(enc)
    except:
        return "Invalid link", 400
    return _stream_response(file_id)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    print(f"🌐 Server: http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, threaded=False)
