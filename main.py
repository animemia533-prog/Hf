
AnimeVerse Upload Bot — Caption Auto-Detect Mode
=================================================
Install:  pip install pyTelegramBotAPI firebase-admin
Run:      python bot.py

Flow:
  1. /setup anime-id S1   → anime aur season set karo (ek baar)
  2. Saari files ek saath forward karo (kisi bhi order mein)
  3. Bot caption se Episode + Quality auto-detect karega
  4. Same episode ki files group → Storage → Firebase save
  5. /done → sab complete hone pe confirm karo
"""

import re
import telebot
import firebase_admin
from firebase_admin import credentials, db

# ══════════════════════════════════════════════════════
#   SETTINGS — Sirf yahan apna data daalo
# ══════════════════════════════════════════════════════

BOT_TOKEN       = "8906093291:AAFnAaJwAYTJiTExqHn2N-aqEbtneR_sByo"
BOT_USERNAME    = "D0file_Bot"         # @ke bina
ALLOWED_USER    = 7373324949

STORAGE_CHANNEL = -1003963251495
FIREBASE_URL    = "https://animeverse-9eada-default-rtdb.firebaseio.com/"
FIREBASE_CRED   = "key.json"

# Kitni qualities per episode? (3 = 480p+720p+1080p)
# Jab yeh count pura ho → auto save
QUALITIES_PER_EP = 3

# ══════════════════════════════════════════════════════
#   INIT
# ══════════════════════════════════════════════════════

cred = credentials.Certificate(FIREBASE_CRED)
firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_URL})

bot = telebot.TeleBot(BOT_TOKEN)

_cid = str(STORAGE_CHANNEL).replace("-100", "")
# Delivery link format: https://t.me/BOT_USERNAME?start=MSG_ID

# ══════════════════════════════════════════════════════
#   STATE
# ══════════════════════════════════════════════════════

session = {
    "anime_id" : None,
    "season"   : None,
    "done_eps" : 0,
}

# ep_buffer[ep_num] = [ {chat_id, msg_id, size, quality}, ... ]
ep_buffer = {}

def reset_all():
    session.update({"anime_id": None, "season": None, "done_eps": 0})
    ep_buffer.clear()

# ══════════════════════════════════════════════════════
#   CAPTION PARSER
# ══════════════════════════════════════════════════════

def parse_caption(text: str):
    """
    Caption/filename se sirf pehla number nikaalega — koi keyword zaroori nahi.

    Examples:
      "07"               → 7
      "Naruto 05 720p"   → 5
      "102 [1080p]"      → 102
      "S2 11 480p"       → 11  (S2 aur 480 skip)
      "2"                → 2

    Returns: (ep_num: int or None, quality: str or None)
    """
    if not text:
        return None, None

    t = text.upper()

    # --- Quality pehle nikaal do taaki wo episode number na bane ---
    quality = None
    q_match = re.search(r'\b(1080P?|720P?|480P?)\b', t)
    if q_match:
        quality = q_match.group(1)
        if not quality.endswith("P"):
            quality += "P"
        quality = quality.replace("P", "p")   # → "720p"
        t = t[:q_match.start()] + t[q_match.end():]

    # --- Season number hata do (S1, S2 ... S99) ---
    t = re.sub(r'\bS\d{1,2}\b', '', t)

    # --- Pehla standalone number lo (1 se 3 digit) ---
    ep_num = None
    nums = re.findall(r'\b(\d{1,3})\b', t)
    if nums:
        ep_num = int(nums[0])

    return ep_num, quality

# ══════════════════════════════════════════════════════
#   FIREBASE
# ══════════════════════════════════════════════════════

def save_to_firebase(anime_id, season, ep_num, quality_dict):
    ep_key = f"E{ep_num}"
    if not quality_dict:
        print(f"  ⚠️ Empty dict — skip Firebase for {ep_key}")
        return ep_key
    db.reference(f"anime_links/{anime_id}/{season}/{ep_key}").update(quality_dict)
    print(f"  ✅ Firebase: anime_links/{anime_id}/{season}/{ep_key}")
    return ep_key

# ══════════════════════════════════════════════════════
#   STORAGE FORWARD
# ══════════════════════════════════════════════════════

def forward_to_storage(from_chat_id, msg_id, new_caption):
    try:
        sent = bot.copy_message(
            chat_id      = STORAGE_CHANNEL,
            from_chat_id = from_chat_id,
            message_id   = msg_id,
            caption      = new_caption,
        )
        # Link format: https://t.me/BotUsername?start=MSG_ID
        return f"https://t.me/{BOT_USERNAME}?start={sent.message_id}"
    except Exception as e:
        print(f"  ❌ Forward error: {e}")
        return None

# ══════════════════════════════════════════════════════
#   PROCESS EPISODE
# ══════════════════════════════════════════════════════

def process_ep(chat_id, ep_num, files):
    anime_id = session["anime_id"]
    season   = session["season"]
    ep_key   = f"E{ep_num}"

    # Size ke hisaab se sort — chota=480p, beech=720p, bada=1080p
    sorted_files = sorted(files, key=lambda x: x["size"])
    quality_map = {0: "480p", 1: "720p", 2: "1080p"}
    for i, f in enumerate(sorted_files):
        f["quality"] = quality_map.get(i, f"part{i+1}")

    quality_dict = {}
    for f in files:
        quality = f["quality"]
        size_mb = round(f["size"] / (1024 * 1024), 1)

        caption = (
            f"🎌 {anime_id}\n"
            f"📺 {season} | {ep_key} | {quality} | {size_mb}MB\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )

        link = forward_to_storage(f["chat_id"], f["msg_id"], caption)
        if link:
            quality_dict[quality] = link

    saved_key = save_to_firebase(anime_id, season, ep_num, quality_dict)
    session["done_eps"] += 1

    if quality_dict:
        q_lines = "\n".join([f"  • {q}: ✅" for q in quality_dict])
        bot.send_message(chat_id, f"""
✅ *{saved_key} Saved!*
{q_lines}
🔗 `anime_links/{anime_id}/{season}/{saved_key}`
""", parse_mode="Markdown")
    else:
        bot.send_message(chat_id, f"""
❌ *{saved_key} Failed!*
Bot ko storage channel ka *Admin* banao!
""", parse_mode="Markdown")

# ══════════════════════════════════════════════════════
#   COMMANDS
# ══════════════════════════════════════════════════════

@bot.message_handler(commands=["start"])
def cmd_start(msg):
    args = msg.text.split()

    # User ne ?start=MSG_ID se open kiya → file deliver karo
    if len(args) > 1:
        try:
            msg_id = int(args[1])
            bot.copy_message(
                chat_id      = msg.chat.id,
                from_chat_id = STORAGE_CHANNEL,
                message_id   = msg_id,
            )
        except Exception as e:
            print(f"Delivery error: {e}")
            bot.reply_to(msg, "❌ File nahi mili. Link expire ho gaya ya galat hai.")
        return

    # Admin ka /start — help dikhao
    if msg.from_user.id == ALLOWED_USER:
        bot.reply_to(msg, """
🎌 *AnimeVerse Upload Bot v2*
━━━━━━━━━━━━━━━━━━━━━━━━━

*Step 1:* `/setup anime-id S1`
*Step 2:* Saari files forward karo ek saath
*Step 3:* `/done` jab sab bhej do

━━━━━━━━━━━━━━━━━━━━━━━━━
*Other commands:*
📋 `/status` — buffer dekho
🔍 `/check anime-id S1 5`
🔄 `/reset`
""", parse_mode="Markdown")


@bot.message_handler(commands=["help"])
def cmd_help(msg):
    if msg.from_user.id != ALLOWED_USER:
        return
    bot.reply_to(msg, "📌 Commands: /setup /status /done /reset /check")


@bot.message_handler(commands=["setup"])
def cmd_setup(msg):
    if msg.from_user.id != ALLOWED_USER:
        return
    try:
        parts    = msg.text.split()
        anime_id = parts[1]
        season   = parts[2].upper()
        reset_all()
        session["anime_id"] = anime_id
        session["season"]   = season
        bot.reply_to(msg, f"""
✅ *Setup Done!*
📺 Anime: `{anime_id}`
🎬 Season: `{season}`

Ab saari files ek saath forward karo! 🚀
Bot caption dekh ke khud group karega.
""", parse_mode="Markdown")
    except:
        bot.reply_to(msg, "❌ Format: `/setup anime-id S1`", parse_mode="Markdown")


@bot.message_handler(commands=["done"])
def cmd_done(msg):
    if msg.from_user.id != ALLOWED_USER:
        return
    pending = list(ep_buffer.keys())
    if pending:
        bot.reply_to(msg, f"⚙️ *{len(pending)} pending episodes process ho rahe hain...*",
                     parse_mode="Markdown")
        for ep_num in sorted(pending):
            files = ep_buffer.pop(ep_num)
            process_ep(msg.chat.id, ep_num, files)

    total = session["done_eps"]
    bot.send_message(msg.chat.id, f"""
🏁 *Sab Complete!*
✅ *{total} episodes* Firebase mein save!
📺 `{session['anime_id']}` | `{session['season']}`

Naya season ke liye `/setup` karo.
""", parse_mode="Markdown")


@bot.message_handler(commands=["status"])
def cmd_status(msg):
    if msg.from_user.id != ALLOWED_USER:
        return
    if not session["anime_id"]:
        bot.reply_to(msg, "ℹ️ Koi session nahi.\n`/setup anime-id S1` se shuru karo.")
        return
    lines = [
        f"📋 *Status:*\n━━━━━━━━━━━━━━━━━━━━",
        f"📺 `{session['anime_id']}` | `{session['season']}`",
        f"✅ Saved: `{session['done_eps']} episodes`",
        f"⏳ Buffer: `{len(ep_buffer)} episodes`\n"
    ]
    for ep_num in sorted(ep_buffer.keys()):
        files = ep_buffer[ep_num]
        quals = [f["quality"] for f in files]
        lines.append(f"  E{ep_num}: {', '.join(quals)} ({len(files)}/{QUALITIES_PER_EP})")
    bot.reply_to(msg, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=["reset"])
def cmd_reset(msg):
    if msg.from_user.id != ALLOWED_USER:
        return
    reset_all()
    bot.reply_to(msg, "🔄 *Reset done!* `/setup anime-id S1` se shuru karo.", parse_mode="Markdown")


@bot.message_handler(commands=["check"])
def cmd_check(msg):
    if msg.from_user.id != ALLOWED_USER:
        return
    try:
        parts    = msg.text.split()
        anime_id = parts[1]
        season   = parts[2].upper()
        ep_num   = str(parts[3])
        data = db.reference(f"anime_links/{anime_id}/{season}/E{ep_num}").get()
        if data:
            lines = [f"📊 *{anime_id} | {season} | E{ep_num}*\n━━━━━━━━━━━━━━━━"]
            for q, link in data.items():
                lines.append(f"• {q}: `{str(link)[:55]}`")
            bot.reply_to(msg, "\n".join(lines), parse_mode="Markdown")
        else:
            bot.reply_to(msg, f"❌ E{ep_num} Firebase mein nahi mila")
    except:
        bot.reply_to(msg, "❌ Format: `/check anime-id S1 5`", parse_mode="Markdown")

# ══════════════════════════════════════════════════════
#   FILE HANDLER
# ══════════════════════════════════════════════════════

@bot.message_handler(content_types=["document", "video"])
def handle_file(msg):
    if msg.from_user.id != ALLOWED_USER:
        return

    if not session["anime_id"]:
        bot.reply_to(msg, "❌ Pehle `/setup anime-id S1` karo!", parse_mode="Markdown")
        return

    file_obj  = msg.document or msg.video
    file_size = file_obj.file_size or 0
    file_name = getattr(file_obj, "file_name", None) or "video"
    caption   = msg.caption or ""

    # Sirf episode number detect karo (quality size se assign hogi)
    ep_num, _ = parse_caption(caption)
    if not ep_num:
        ep_num, _ = parse_caption(file_name)

    if not ep_num:
        bot.reply_to(msg, f"⚠️ *Episode detect nahi hua!*\nCaption: `{caption[:80]}`\nCaption mein `Episode - 04` ya `E04` hona chahiye.", parse_mode="Markdown")
        return

    quality = "pending"  # Size se assign hogi process_ep mein

    # Buffer mein add
    if ep_num not in ep_buffer:
        ep_buffer[ep_num] = []

    # Duplicate file check — same size ki file dobara aayi?
    existing_sizes = [f["size"] for f in ep_buffer[ep_num]]
    if file_size in existing_sizes:
        bot.reply_to(msg, f"⚠️ *{ep_key} — Same file dobara aai! Skip kar raha hoon.*", parse_mode="Markdown")
        return

    ep_buffer[ep_num].append({
        "chat_id": msg.chat.id,
        "msg_id" : msg.message_id,
        "size"   : file_size,
        "quality": quality,
        "name"   : file_name,
    })

    count   = len(ep_buffer[ep_num])
    size_mb = round(file_size / (1024 * 1024), 1)
    ep_key  = f"E{ep_num}"

    if count >= QUALITIES_PER_EP:
        bot.reply_to(msg, f"""
📥 `{quality}` | `{size_mb}MB`
⚙️ *{ep_key} complete! Save ho raha hai...*
""", parse_mode="Markdown")
        files = ep_buffer.pop(ep_num)
        process_ep(msg.chat.id, ep_num, files)
    else:
        remaining = QUALITIES_PER_EP - count
        bot.reply_to(msg, f"""
📥 `{quality}` | `{size_mb}MB`
📦 *{ep_key}:* {count}/{QUALITIES_PER_EP} | aur *{remaining}* chahiye
""", parse_mode="Markdown")

# ══════════════════════════════════════════════════════
#   RUN
# ══════════════════════════════════════════════════════

print("=" * 50)
print("  🤖 AnimeVerse Bot v2 — Caption Mode")
print(f"  📦 Storage: t.me/c/{_cid}/")
print("  Ctrl+C se band karo")
print("=" * 50)

bot.polling(none_stop=True, interval=1)
