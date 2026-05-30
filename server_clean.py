import os
import base64
import requests
from flask import Flask, Response, redirect, request, render_template_string

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
TELEGRAM_FILE = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

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

def get_tg_url(file_id: str):
    r = requests.get(f"{TELEGRAM_API}/getFile", params={"file_id": file_id})
    d = r.json()
    if d.get("ok"):
        return f"{TELEGRAM_FILE}/{d['result']['file_path']}"
    return None

@app.route("/")
def index():
    return "<h2 style='color:#64b5f6;text-align:center;margin-top:40vh;font-family:sans-serif'>🎬 TG Streamer</h2>"

# ✅ Clean URL: domain.com/{encoded} → seedha stream
@app.route("/<encoded>")
def clean_stream(encoded):
    # /watch/ aur /stream/ routes ke liye skip
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
    url = get_tg_url(file_id)
    if not url:
        return "File nahi mila", 404
    return redirect(url)

def _do_stream(file_id: str):
    url = get_tg_url(file_id)
    if not url:
        return "File nahi mila ya expire ho gayi", 404

    range_header = request.headers.get("Range")
    headers = {"Range": range_header} if range_header else {}
    tg = requests.get(url, headers=headers, stream=True)

    resp_headers = {
        "Content-Type": tg.headers.get("Content-Type", "video/mp4"),
        "Accept-Ranges": "bytes",
    }
    for h in ("Content-Range", "Content-Length"):
        if h in tg.headers:
            resp_headers[h] = tg.headers[h]

    def gen():
        for chunk in tg.iter_content(65536):
            if chunk:
                yield chunk

    return Response(gen(), status=tg.status_code, headers=resp_headers)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    print(f"🌐 http://localhost:{port}")
    app.run(host="0.0.0.0", port=port)
