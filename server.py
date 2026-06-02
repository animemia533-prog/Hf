import os
import hashlib
import logging
import urllib.parse
import asyncio
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, HTMLResponse
from pyrogram import Client
from pyrogram.errors import FloodWait

# ─── CONFIG ────────────────────────────────────────────────────────────────
API_ID          = int(os.getenv("API_ID", "0"))
API_HASH        = os.getenv("API_HASH", "")
BOT_TOKEN       = os.getenv("BOT_TOKEN", "")
STORAGE_CHANNEL = int(os.getenv("STORAGE_CHANNEL", "0"))
SECRET_KEY      = os.getenv("SECRET_KEY", "mysecretkey123")
PORT            = int(os.getenv("PORT", 8000))
# ───────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="TG Stream Server")
pyro_client: Client = None


@app.on_event("startup")
async def startup():
    global pyro_client
    pyro_client = Client(
        "stream_bot",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        in_memory=True,
    )
    await pyro_client.start()
    logger.info("Pyrogram client started.")


@app.on_event("shutdown")
async def shutdown():
    if pyro_client:
        await pyro_client.stop()


def verify_code(msg_id: int, filename: str, code: str) -> bool:
    raw = f"{SECRET_KEY}:{msg_id}:{filename}"
    expected = hashlib.md5(raw.encode()).hexdigest()[:24]
    return code == expected


async def file_generator(pyro: Client, message, offset: int = 0, limit: int = None) -> AsyncGenerator[bytes, None]:
    """Stream file chunks from Telegram using Pyrogram."""
    async for chunk in pyro.stream_media(message, offset=offset, limit=limit):
        yield chunk


@app.get("/")
async def index():
    return HTMLResponse("""
    <html>
    <head><title>TG Stream</title></head>
    <body style='font-family:sans-serif;text-align:center;padding:80px;background:#0f0f0f;color:#fff'>
    <h1 style='font-size:3em'>🎬</h1>
    <h2>TG Stream Server</h2>
    <p style='color:#aaa'>Telegram Video Streaming — Online ✅</p>
    </body></html>
    """)


@app.get("/dl/{msg_id}/{filename:path}")
async def stream_file(msg_id: int, filename: str, code: str, request: Request):
    """
    Streaming endpoint.
    /dl/{msg_id}/{filename}?code={hash}
    """
    decoded_filename = urllib.parse.unquote(filename)

    # Verify link code
    if not verify_code(msg_id, decoded_filename, code):
        raise HTTPException(status_code=403, detail="❌ Invalid or expired link.")

    # Fetch message from storage channel
    try:
        message = await pyro_client.get_messages(STORAGE_CHANNEL, msg_id)
    except FloodWait as e:
        await asyncio.sleep(e.value)
        message = await pyro_client.get_messages(STORAGE_CHANNEL, msg_id)
    except Exception as e:
        logger.error(f"Error fetching message: {e}")
        raise HTTPException(status_code=404, detail="File not found.")

    if not message or message.empty:
        raise HTTPException(status_code=404, detail="Message not found in storage.")

    # Get media object
    media = message.video or message.document or message.audio or message.video_note
    if not media:
        raise HTTPException(status_code=404, detail="No media in this message.")

    file_size = media.file_size
    mime_type = getattr(media, "mime_type", "application/octet-stream")

    # Handle Range requests (for video seeking)
    range_header = request.headers.get("range")
    offset = 0
    limit = None
    status_code = 200

    response_headers = {
        "Content-Type": mime_type,
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'inline; filename="{decoded_filename}"',
        "Content-Length": str(file_size),
    }

    if range_header:
        # Parse: bytes=start-end
        range_val = range_header.replace("bytes=", "")
        parts = range_val.split("-")
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if parts[1] else file_size - 1

        chunk_size = 1024 * 1024  # 1MB chunks
        offset = start // chunk_size
        limit = ((end - start) // chunk_size) + 1

        response_headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        response_headers["Content-Length"] = str(end - start + 1)
        status_code = 206

    logger.info(f"Streaming msg_id={msg_id} | {decoded_filename} | size={file_size} | range={range_header}")

    return StreamingResponse(
        file_generator(pyro_client, message, offset=offset, limit=limit),
        status_code=status_code,
        headers=response_headers,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=PORT)
