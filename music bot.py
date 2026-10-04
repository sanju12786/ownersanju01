"""Telegram Music Bot + Web Admin Panel (single file, Termux friendly).

Run:  python music_bot.py

.env example:
    BOT_TOKEN=123:ABC
    ADMIN_IDS=8244241281
    ADMIN_PASSWORD=strongpassword
    PUBLIC_URL=https://your-panel-url
"""
import sys

# ======================================================================
# CONFIG
# ======================================================================
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv optional
    pass

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Admin IDs: built-in + optional comma separated ADMIN_IDS in .env
ADMIN_IDS = {8244241281, 5574675470}
ADMIN_IDS |= {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}

API_BASE = os.getenv("API_BASE", "https://music-api-2-production.up.railway.app").rstrip("/")

# Owner + force-join channel
OWNER_USERNAME = "@thehiddenreserve"
CHANNEL_USERNAME = "@Sanjuownersmm"
CHANNEL_URL = "https://t.me/Sanjuownersmm"

# Web admin panel
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
SECRET_KEY = os.getenv("SECRET_KEY", "") or os.urandom(24).hex()
PORT = int(os.getenv("PORT", "8080"))
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")  # optional, shown by /panel


# ======================================================================
# DATABASE
# ======================================================================
import sqlite3
import threading

DB_PATH = os.getenv("DB_PATH", "bot.db")

_lock = threading.Lock()
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row

DEFAULT_WELCOME = (
    "🎶 <b>Welcome {name}!</b> 🎶\n\n"
    "✨ Main ek fast <b>Music Downloader Bot</b> hoon.\n\n"
    "🔎 Kisi bhi gaane ka naam bhejo\n"
    "🖼 Song ke banner ke saath\n"
    "▶️ Seedha play — bina download wait ke\n"
    "⚡ Fast • Free • Easy\n\n"
    "📝 Example: <code>Kesariya</code>\n"
    "👉 Ya use karo: <code>/play Kesariya</code>\n\n"
    f"👑 Owner: {OWNER_USERNAME}\n"
    f"📢 Channel: {CHANNEL_USERNAME}\n\n"
    f"💬 Update ya problem ke liye DM karein: {OWNER_USERNAME}\n\n"
    "👇 Neeche diye buttons use karein"
)

DEFAULTS = {
    "maintenance": "0",
    "force_channel": CHANNEL_USERNAME,
    "owner_username": OWNER_USERNAME,
    "results_limit": "5",
    "welcome_banner": "",
    "welcome_text": DEFAULT_WELCOME,
    "broadcast_status": "",
}
DEFAULTS_VERSION = "3"


def _exec(sql, params=()):
    with _lock:
        cur = _conn.execute(sql, params)
        _conn.commit()
        return cur


def _all(sql, params=()):
    with _lock:
        return _conn.execute(sql, params).fetchall()


def _one(sql, params=()):
    with _lock:
        return _conn.execute(sql, params).fetchone()


def init():
    with _lock:
        _conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users(
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_at TEXT DEFAULT (datetime('now','localtime')),
                last_seen TEXT DEFAULT (datetime('now','localtime')),
                banned INTEGER DEFAULT 0,
                downloads INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS downloads(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                video_id TEXT,
                title TEXT,
                ts TEXT DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS files(
                video_id TEXT PRIMARY KEY,
                file_id TEXT,
                title TEXT
            );
            CREATE TABLE IF NOT EXISTS settings(
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        for k, v in DEFAULTS.items():
            _conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (k, v))
        # new defaults (channel / owner / welcome) apply once to old databases
        row = _conn.execute("SELECT value FROM settings WHERE key='defaults_ver'").fetchone()
        if not row or row["value"] != DEFAULTS_VERSION:
            for k in ("welcome_text", "force_channel", "owner_username"):
                _conn.execute("UPDATE settings SET value=? WHERE key=?", (DEFAULTS[k], k))
            _conn.execute(
                "INSERT INTO settings(key, value) VALUES('defaults_ver', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (DEFAULTS_VERSION,),
            )
        _conn.commit()


# ---------- settings ----------
def get_setting(key):
    row = _one("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else DEFAULTS.get(key, "")


def set_setting(key, value):
    _exec("INSERT INTO settings(key, value) VALUES(?, ?) "
          "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


# ---------- users ----------
def upsert_user(user):
    _exec(
        """
        INSERT INTO users(user_id, username, first_name) VALUES(?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name,
            last_seen=datetime('now','localtime')
        """,
        (user.id, user.username, user.first_name),
    )


def is_banned(user_id):
    row = _one("SELECT banned FROM users WHERE user_id=?", (user_id,))
    return bool(row and row["banned"])


def set_ban(user_id, banned):
    cur = _exec("UPDATE users SET banned=? WHERE user_id=?", (1 if banned else 0, user_id))
    return cur.rowcount > 0


def all_user_ids(include_banned=False):
    sql = "SELECT user_id FROM users" + ("" if include_banned else " WHERE banned=0")
    return [r["user_id"] for r in _all(sql)]


def list_users(search="", limit=25, offset=0):
    where, params = "", []
    if search:
        like = f"%{search}%"
        where = "WHERE CAST(user_id AS TEXT) LIKE ? OR username LIKE ? OR first_name LIKE ?"
        params = [like, like, like]
    total = _one(f"SELECT COUNT(*) c FROM users {where}", params)["c"]
    rows = _all(
        f"SELECT * FROM users {where} ORDER BY last_seen DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    return rows, total


def top_users(limit=5):
    return _all(
        "SELECT user_id, first_name, username, downloads FROM users "
        "WHERE downloads>0 ORDER BY downloads DESC LIMIT ?", (limit,)
    )


# ---------- downloads ----------
def log_download(user_id, video_id, title):
    _exec("INSERT INTO downloads(user_id, video_id, title) VALUES(?, ?, ?)", (user_id, video_id, title))
    _exec("UPDATE users SET downloads = downloads + 1 WHERE user_id=?", (user_id,))


def get_cached(video_id):
    return _one("SELECT * FROM files WHERE video_id=?", (video_id,))


def cache_file(video_id, file_id, title):
    _exec("INSERT INTO files(video_id, file_id, title) VALUES(?, ?, ?) "
          "ON CONFLICT(video_id) DO UPDATE SET file_id=excluded.file_id, title=excluded.title",
          (video_id, file_id, title))


def recent_downloads(limit=15):
    return _all(
        """
        SELECT d.*, u.username, u.first_name FROM downloads d
        LEFT JOIN users u ON u.user_id = d.user_id
        ORDER BY d.id DESC LIMIT ?
        """,
        (limit,),
    )


def list_downloads(search="", limit=25, offset=0):
    where, params = "", []
    if search:
        like = f"%{search}%"
        where = "WHERE d.title LIKE ? OR CAST(d.user_id AS TEXT) LIKE ? OR u.username LIKE ? OR u.first_name LIKE ?"
        params = [like, like, like, like]
    base = "FROM downloads d LEFT JOIN users u ON u.user_id = d.user_id " + where
    total = _one(f"SELECT COUNT(*) c {base}", params)["c"]
    rows = _all(
        f"SELECT d.*, u.username, u.first_name {base} ORDER BY d.id DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    return rows, total


def list_files(search="", limit=25, offset=0):
    where, params = "", []
    if search:
        where = "WHERE title LIKE ? OR video_id LIKE ?"
        params = [f"%{search}%", f"%{search}%"]
    total = _one(f"SELECT COUNT(*) c FROM files {where}", params)["c"]
    rows = _all(
        "SELECT f.*, (SELECT COUNT(*) FROM downloads d WHERE d.video_id=f.video_id) dl "
        f"FROM files f {where} ORDER BY f.rowid DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    return rows, total


def top_songs(limit=10):
    return _all(
        "SELECT title, video_id, COUNT(*) c FROM downloads GROUP BY video_id ORDER BY c DESC LIMIT ?", (limit,)
    )


def stats():
    q = lambda sql: _one(sql)["c"]  # noqa: E731
    return {
        "users": q("SELECT COUNT(*) c FROM users"),
        "banned": q("SELECT COUNT(*) c FROM users WHERE banned=1"),
        "new_today": q("SELECT COUNT(*) c FROM users WHERE date(joined_at)=date('now','localtime')"),
        "active_today": q("SELECT COUNT(*) c FROM users WHERE date(last_seen)=date('now','localtime')"),
        "downloads": q("SELECT COUNT(*) c FROM downloads"),
        "downloads_today": q("SELECT COUNT(*) c FROM downloads WHERE date(ts)=date('now','localtime')"),
        "cached": q("SELECT COUNT(*) c FROM files"),
    }


# ======================================================================
# TELEGRAM BOT
# ======================================================================
import asyncio
import functools
import html
import io
import logging
import re

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


log = logging.getLogger("musicbot")

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{6,20}$")
MAX_BYTES = 49 * 1024 * 1024  # Telegram bot upload limit is 50 MB


# ---------------------------------------------------------------- helpers
def esc(value) -> str:
    return html.escape(str(value or ""))


def fmt_dur(sec) -> str:
    try:
        sec = int(sec)
    except (TypeError, ValueError):
        return ""
    return f"{sec // 60}:{sec % 60:02d}"


def safe_filename(title: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]+', " ", title or "song").strip()[:80] or "song"
    return f"{name}.mp3"


def owner_url() -> str:
    return "https://t.me/" + (get_setting("owner_username") or OWNER_USERNAME).lstrip("@")


def channel_url() -> str:
    ch = (get_setting("force_channel") or CHANNEL_USERNAME).strip()
    if ch.startswith("@"):
        return "https://t.me/" + ch.lstrip("@")
    return CHANNEL_URL


async def api_get(path: str, **params) -> httpx.Response:
    async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15), follow_redirects=True) as client:
        return await client.get(f"{API_BASE}{path}", params=params)


# ---------------------------------------------------------------- keyboards
def main_kb(is_admin=False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🎵 Gaana Dhundo", callback_data="menu:search")],
        [
            InlineKeyboardButton("ℹ️ Help", callback_data="menu:help"),
            InlineKeyboardButton("👑 Owner", url=owner_url()),
        ],
        [InlineKeyboardButton("📢 Our Channel", url=channel_url())],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton("🛠 Admin Panel", callback_data="admin:home")])
    return InlineKeyboardMarkup(rows)


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="menu:home")]])


def song_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("📢 Channel", url=channel_url()),
            InlineKeyboardButton("👑 Owner", url=owner_url()),
        ]]
    )


def admin_kb() -> InlineKeyboardMarkup:
    maint_on = get_setting("maintenance") == "1"
    rows = [
        [
            InlineKeyboardButton("📊 Stats", callback_data="admin:stats"),
            InlineKeyboardButton("🔥 Top Songs", callback_data="admin:top"),
        ],
        [
            InlineKeyboardButton("📣 Broadcast", callback_data="admin:bc"),
            InlineKeyboardButton(f"🔧 Maintenance: {'ON 🔴' if maint_on else 'OFF 🟢'}", callback_data="admin:maint"),
        ],
    ]
    if PUBLIC_URL:
        rows.append([InlineKeyboardButton("🌐 Web Panel", url=PUBLIC_URL + "/")])
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="menu:home")])
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------- gate
async def deny(update: Update, text: str, markup=None):
    q = update.callback_query
    if q:
        await q.answer(text[:190], show_alert=True)
        if markup and q.message:
            await q.message.reply_text(text, reply_markup=markup)
    elif update.effective_message:
        await update.effective_message.reply_text(text, reply_markup=markup)


async def gate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Registers the user and applies ban / maintenance / force-join checks."""
    user = update.effective_user
    if not user:
        return False
    upsert_user(user)
    if user.id in ADMIN_IDS:
        return True
    if is_banned(user.id):
        await deny(update, "🚫 Aapko is bot se ban kar diya gaya hai.\n\n"
                           f"Help ke liye owner se baat karein: {get_setting('owner_username')}")
        return False
    if get_setting("maintenance") == "1":
        await deny(update, "🛠 Bot abhi maintenance mein hai. Thodi der baad try karein.")
        return False
    channel = get_setting("force_channel").strip()
    if channel:
        try:
            member = await context.bot.get_chat_member(channel, user.id)
            if member.status in ("left", "kicked"):
                markup = InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("📢 Channel Join Karo", url=channel_url())],
                        [InlineKeyboardButton("✅ Maine Join Kar Liya", callback_data="chk")],
                    ]
                )
                await deny(
                    update,
                    "🔒 Bot use karne ke liye sabse pehle hamara channel join karna zaroori hai.\n\n"
                    "1️⃣ Neeche 'Channel Join Karo' dabayein\n"
                    "2️⃣ Join karke '✅ Maine Join Kar Liya' dabayein",
                    markup,
                )
                return False
        except TelegramError as exc:  # bot not admin in channel, wrong name, ...
            log.warning("force-join check failed for %s: %s (bot ko channel mein admin banayein)", channel, exc)
    return True


def admin_only(fn):
    @functools.wraps(fn)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or update.effective_user.id not in ADMIN_IDS:
            if update.callback_query:
                await update.callback_query.answer("Admin only.", show_alert=True)
            return
        return await fn(update, context)

    return wrapper


# ---------------------------------------------------------------- welcome / help
async def send_welcome(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user):
    name = esc(user.first_name)
    text = get_setting("welcome_text").replace("{name}", name)
    kb = main_kb(user.id in ADMIN_IDS)
    banner = get_setting("welcome_banner").strip()
    if banner and len(text) <= 1000:
        try:
            await context.bot.send_photo(chat_id, banner, caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
            return
        except TelegramError as exc:
            log.warning("welcome banner failed: %s", exc)
    try:
        await context.bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=kb)
    except BadRequest:  # admin saved invalid HTML in welcome text
        await context.bot.send_message(chat_id, re.sub(r"<[^>]+>", "", text), reply_markup=kb)


HELP_TEXT = (
    "ℹ️ <b>Help / Guide</b>\n\n"
    "1️⃣ Gaane ka naam bhejo ya <code>/play naam</code> likho\n"
    "2️⃣ Sabse best match ka ek gaana banner ke saath seedha play ho jayega 🎧\n"
    "3️⃣ Ek time par ek hi gaana chalega ⏳\n\n"
    "📌 <b>Commands</b>\n"
    "/start - Bot start karein\n"
    "/play &lt;naam&gt; - Gaana search karein\n"
    "/help - Ye guide\n\n"
    "👑 Owner: {owner}\n"
    "💬 Update / problem ke liye DM: {owner}\n"
    "📢 Channel: {channel}"
)


def help_text() -> str:
    return HELP_TEXT.format(owner=esc(get_setting("owner_username")), channel=esc(get_setting("force_channel") or CHANNEL_USERNAME))


# ---------------------------------------------------------------- user commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await gate(update, context):
        return
    await send_welcome(context, update.effective_chat.id, update.effective_user)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await gate(update, context):
        return
    await update.message.reply_text(help_text(), parse_mode=ParseMode.HTML, reply_markup=main_kb(update.effective_user.id in ADMIN_IDS))


async def play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await gate(update, context):
        return
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text("🎵 Usage: /play <gaane ka naam>\nExample: /play Kesariya")
        return
    await do_search(update, context, query)


async def on_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'Maine join kar liya' button."""
    q = update.callback_query
    if not await gate(update, context):
        return
    await q.answer("✅ Verified! Welcome 🎉")
    await send_welcome(context, q.message.chat_id, update.effective_user)


async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not await gate(update, context):
        return
    action = (q.data or "")[5:]
    await q.answer()
    if action == "search":
        await q.message.reply_text("🔎 Gaane ka naam bhejo, jaise:\n<code>Kesariya</code>", parse_mode=ParseMode.HTML)
    elif action == "help":
        await q.message.reply_text(help_text(), parse_mode=ParseMode.HTML, reply_markup=back_kb())
    else:
        await send_welcome(context, q.message.chat_id, update.effective_user)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else 0
    # admin broadcast mode (started from admin panel button)
    if uid in ADMIN_IDS and context.user_data.pop("await_bc", False):
        text = update.message.text_html
        ids = all_user_ids()
        await update.message.reply_text(f"📣 Broadcast shuru: {len(ids)} users ko bhej raha hoon…")
        context.application.create_task(_broadcast(context, update.effective_chat.id, ids, text))
        return
    if not await gate(update, context):
        return
    query = (update.message.text or "").strip()
    if query:
        await do_search(update, context, query[:100])


async def do_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str):
    """Search -> sirf 1 best result -> seedha play."""
    msg = update.message
    await context.bot.send_chat_action(msg.chat_id, ChatAction.TYPING)
    try:
        resp = await api_get("/search", q=query, limit=1)
        resp.raise_for_status()
        results = (resp.json().get("results")) or []
    except Exception as exc:
        log.warning("search failed for %r: %s", query, exc)
        await msg.reply_text("❌ Search mein problem aayi, thodi der baad try karein.", reply_markup=back_kb())
        return

    item = next((r for r in results if r.get("id") and VIDEO_ID.match(str(r["id"]))), None)
    if not item:
        await msg.reply_text(f"😕 '{query}' ke liye kuch nahi mila. Doosra naam try karein.", reply_markup=back_kb())
        return

    meta = context.application.bot_data.setdefault("meta", {})
    if len(meta) > 3000:
        meta.clear()
    meta[item["id"]] = item
    await deliver(context, msg.chat_id, update.effective_user.id, item["id"], item)


async def send_banner(context: ContextTypes.DEFAULT_TYPE, chat_id: int, vid: str, meta: dict, title: str):
    """Song banner (thumbnail + details) sent before the song."""
    thumb = meta.get("thumbnail") or meta.get("thumb") or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
    if isinstance(thumb, list):  # some APIs return a list of thumbnails
        thumb = (thumb[-1].get("url") if thumb and isinstance(thumb[-1], dict) else thumb[-1]) if thumb else ""
    lines = [f"🎵 <b>{esc(title)}</b>"]
    if meta.get("channel"):
        lines.append(f"👤 {esc(meta['channel'])}")
    dur = fmt_dur(meta.get("duration"))
    if dur:
        lines.append(f"⏱ {dur}")
    lines.append(f"\n🎧 via @{esc(context.bot.username)}")
    caption = "\n".join(lines)[:1000]
    try:
        await context.bot.send_photo(chat_id, thumb, caption=caption, parse_mode=ParseMode.HTML)
    except TelegramError as exc:
        log.info("banner failed for %s: %s", vid, exc)
        try:
            await context.bot.send_message(chat_id, caption, parse_mode=ParseMode.HTML)
        except TelegramError:
            pass


async def deliver(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, vid: str, meta: dict):
    """Banner + song. Pehle seedha URL se play (Telegram khud fetch karta hai),
    fail ho to download karke upload (fallback)."""
    busy = context.application.bot_data.setdefault("busy", set())
    if user_id in busy:
        await context.bot.send_message(chat_id, "⏳ Pehla gaana abhi aa raha hai, thoda wait karein.")
        return
    busy.add(user_id)

    title = meta.get("title") or "Song"
    caption = f"🎧 via @{context.bot.username}"
    performer = (meta.get("channel") or "")[:64] or None
    duration = int(meta["duration"]) if str(meta.get("duration", "")).isdigit() else None
    status = None
    try:
        await send_banner(context, chat_id, vid, meta, title)

        # 1) cached -> instant
        cached = get_cached(vid)
        if cached:
            try:
                await context.bot.send_audio(chat_id, cached["file_id"], caption=caption, reply_markup=song_kb())
                log_download(user_id, vid, cached["title"] or title)
                return
            except TelegramError:
                log.info("cached file_id for %s no longer valid", vid)

        status = await context.bot.send_message(chat_id, "▶️ Gaana play ho raha hai…")
        await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_VOICE)

        # 2) direct play via URL (bot download/upload nahi karta)
        try:
            sent = await context.bot.send_audio(
                chat_id,
                audio=f"{API_BASE}/download?id={vid}",
                title=title[:64],
                performer=performer,
                duration=duration,
                caption=caption,
                reply_markup=song_kb(),
                read_timeout=120,
                write_timeout=120,
                connect_timeout=30,
            )
            if sent.audio:
                cache_file(vid, sent.audio.file_id, title)
            log_download(user_id, vid, title)
            return
        except TelegramError as exc:
            log.info("direct URL play failed for %s (%s), fallback to upload", vid, exc)

        # 3) fallback: download then upload
        resp = await api_get("/download", id=vid)
        ctype = resp.headers.get("content-type", "")
        if resp.status_code != 200 or not ctype.startswith("audio"):
            raise RuntimeError(f"download api returned {resp.status_code} {ctype}")
        data = resp.content
        if len(data) > MAX_BYTES:
            await context.bot.send_message(chat_id, "❌ Ye file 50MB se badi hai, Telegram bot se nahi bhej sakte.")
            return
        sent = await context.bot.send_audio(
            chat_id,
            audio=InputFile(io.BytesIO(data), filename=safe_filename(title)),
            title=title[:64],
            performer=performer,
            duration=duration,
            caption=caption,
            reply_markup=song_kb(),
            read_timeout=180,
            write_timeout=180,
            connect_timeout=30,
        )
        if sent.audio:
            cache_file(vid, sent.audio.file_id, title)
        log_download(user_id, vid, title)
    except Exception as exc:
        log.exception("play failed for %s: %s", vid, exc)
        try:
            await context.bot.send_message(chat_id, "❌ Gaana play nahi ho paya. Dobara try karein.")
        except TelegramError:
            pass
    finally:
        busy.discard(user_id)
        if status:
            try:
                await status.delete()
            except TelegramError:
                pass


async def on_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Purane 'dl:' buttons ke liye (backward compatible)."""
    q = update.callback_query
    if not await gate(update, context):
        return
    vid = (q.data or "")[3:]
    if not VIDEO_ID.match(vid):
        await q.answer("Invalid song.", show_alert=True)
        return
    await q.answer("▶️ Play ho raha hai…")
    meta = context.application.bot_data.get("meta", {}).get(vid, {})
    await deliver(context, q.message.chat_id, update.effective_user.id, vid, meta)


# ---------------------------------------------------------------- admin (buttons)
def stats_text() -> str:
    s = stats()
    return (
        "📊 <b>Bot Stats</b>\n\n"
        f"👥 Users: <b>{s['users']}</b> (🚫 banned: {s['banned']})\n"
        f"🆕 Aaj naye: <b>{s['new_today']}</b>\n"
        f"🟢 Aaj active: <b>{s['active_today']}</b>\n"
        f"⬇️ Total downloads: <b>{s['downloads']}</b> (aaj: {s['downloads_today']})\n"
        f"💾 Cached songs: <b>{s['cached']}</b>"
    )


async def _edit(q, text: str, kb):
    try:
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    except BadRequest:
        try:
            await q.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except TelegramError:
            pass


@admin_only
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛠 <b>Admin Panel</b>\n\nNeeche se option chuno 👇", parse_mode=ParseMode.HTML, reply_markup=admin_kb())


@admin_only
async def on_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    action = (q.data or "")[6:]
    await q.answer()
    back = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin Panel", callback_data="admin:home")]])
    if action == "home":
        await _edit(q, "🛠 <b>Admin Panel</b>\n\nNeeche se option chuno 👇", admin_kb())
    elif action == "stats":
        await _edit(q, stats_text(), back)
    elif action == "top":
        rows = top_songs(10)
        body = "\n".join(f"{i}. 🎵 {esc(r['title'])} — <b>{r['c']}</b>" for i, r in enumerate(rows, 1)) or "Abhi koi data nahi."
        await _edit(q, f"🔥 <b>Top Songs</b>\n\n{body}", back)
    elif action == "maint":
        set_setting("maintenance", "0" if get_setting("maintenance") == "1" else "1")
        await _edit(q, "🛠 <b>Admin Panel</b>\n\nMaintenance mode update ho gaya ✅", admin_kb())
    elif action == "bc":
        context.user_data["await_bc"] = True
        await _edit(
            q,
            "📣 <b>Broadcast</b>\n\nAb wo message bhejo jo sabko bhejna hai (HTML allowed).\nCancel karne ke liye /cancel",
            back,
        )


@admin_only
async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("await_bc", None)
    await update.message.reply_text("❎ Cancel ho gaya.")


@admin_only
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(stats_text(), parse_mode=ParseMode.HTML)


@admin_only
async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _set_ban(update, context, True)


@admin_only
async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _set_ban(update, context, False)


async def _set_ban(update: Update, context: ContextTypes.DEFAULT_TYPE, banned: bool):
    if not context.args or not context.args[0].lstrip("-").isdigit():
        await update.message.reply_text(f"Usage: /{'ban' if banned else 'unban'} <user_id>")
        return
    uid = int(context.args[0])
    if uid in ADMIN_IDS:
        await update.message.reply_text("Admin ko ban nahi kar sakte.")
        return
    ok = set_ban(uid, banned)
    await update.message.reply_text(
        ("🚫 Ban kar diya." if banned else "✅ Unban kar diya.") if ok else "User database mein nahi mila."
    )


@admin_only
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text_html.partition(" ")[2].strip()
    if not text:
        context.user_data["await_bc"] = True
        await update.message.reply_text("📣 Ab wo message bhejo jo sabko bhejna hai (HTML allowed). Cancel: /cancel")
        return
    ids = all_user_ids()
    await update.message.reply_text(f"📣 Broadcast shuru: {len(ids)} users ko bhej raha hoon…")
    context.application.create_task(_broadcast(context, update.effective_chat.id, ids, text))


async def _broadcast(context: ContextTypes.DEFAULT_TYPE, admin_chat: int, ids: list, text: str):
    ok = failed = 0
    for uid in ids:
        try:
            await context.bot.send_message(uid, text, parse_mode=ParseMode.HTML)
            ok += 1
        except RetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 1)
            try:
                await context.bot.send_message(uid, text, parse_mode=ParseMode.HTML)
                ok += 1
            except TelegramError:
                failed += 1
        except (Forbidden, BadRequest, TelegramError):
            failed += 1
        await asyncio.sleep(0.05)
    set_setting("broadcast_status", f"Done at {time.strftime('%Y-%m-%d %H:%M:%S')} — sent: {ok}, failed: {failed}, total: {len(ids)}")
    await context.bot.send_message(admin_chat, f"✅ Broadcast complete.\n📨 Sent: {ok}\n❌ Failed: {failed}")


@admin_only
async def panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if PUBLIC_URL:
        await update.message.reply_text(
            "🛠 Web Admin Panel",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🌐 Open Panel", url=PUBLIC_URL + "/")]]),
        )
    else:
        await update.message.reply_text("PUBLIC_URL .env mein set nahi hai.")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Unhandled error", exc_info=context.error)


# ---------------------------------------------------------------- app factory
def build_app() -> Application:
    application = Application.builder().token(BOT_TOKEN).concurrent_updates(True).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("play", play))
    application.add_handler(CommandHandler("admin", admin_cmd))
    application.add_handler(CommandHandler("stats", stats_cmd))
    application.add_handler(CommandHandler("ban", ban_cmd))
    application.add_handler(CommandHandler("unban", unban_cmd))
    application.add_handler(CommandHandler("broadcast", broadcast_cmd))
    application.add_handler(CommandHandler("cancel", cancel_cmd))
    application.add_handler(CommandHandler("panel", panel_cmd))
    application.add_handler(CallbackQueryHandler(on_download, pattern=r"^dl:"))
    application.add_handler(CallbackQueryHandler(on_check, pattern=r"^chk$"))
    application.add_handler(CallbackQueryHandler(on_menu, pattern=r"^menu:"))
    application.add_handler(CallbackQueryHandler(on_admin, pattern=r"^admin:"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, on_text))
    application.add_error_handler(on_error)
    return application


# ======================================================================
# WEB ADMIN PANEL
# ======================================================================
import hmac
import secrets
import time
from functools import wraps

import requests
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from jinja2 import DictLoader


app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

PER_PAGE = 25

TEMPLATES = {
    "base.html": """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{% block title %}Admin{% endblock %} · Music Bot</title>
<style>
:root{--bg:#0f1115;--card:#181b22;--line:#262a33;--text:#e6e8ee;--mut:#8b91a1;--acc:#6c8cff;--red:#ff6b6b;--grn:#4cd08a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,sans-serif}
nav{display:flex;gap:6px;align-items:center;padding:12px 20px;background:var(--card);border-bottom:1px solid var(--line);flex-wrap:wrap}
nav b{margin-right:14px}nav a{color:var(--mut);text-decoration:none;padding:6px 12px;border-radius:8px}
nav a:hover,nav a.on{color:var(--text);background:var(--line)}nav .sp{flex:1}
main{max-width:1100px;margin:24px auto;padding:0 16px}
h1{font-size:22px;margin:0 0 16px}h2{font-size:16px;margin:24px 0 10px;color:var(--mut)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
.card .n{font-size:28px;font-weight:700}.card .l{color:var(--mut);font-size:13px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--line);font-size:14px}
th{color:var(--mut);font-weight:500;background:#14171d;white-space:nowrap}tr:last-child td{border:0}
.wrap{overflow-x:auto}input,textarea,select{width:100%;background:#0f1115;border:1px solid var(--line);color:var(--text);padding:10px;border-radius:8px;font:inherit}
label{display:block;margin:14px 0 6px;color:var(--mut);font-size:13px}
button,.btn{background:var(--acc);color:#fff;border:0;padding:9px 16px;border-radius:8px;font:inherit;cursor:pointer;text-decoration:none;display:inline-block}
button.red{background:var(--red)}button.grn{background:var(--grn);color:#0b1a12}button.sm,.btn.sm{padding:5px 11px;font-size:13px}
.flash{background:#1d2a45;border:1px solid #2b4170;padding:10px 14px;border-radius:8px;margin-bottom:14px}
.tag{font-size:12px;padding:2px 8px;border-radius:99px;background:var(--line)}.tag.red{background:#4a2227;color:#ff9d9d}.tag.grn{background:#173a2a;color:#7fe3ae}
.row{display:flex;gap:10px;align-items:center}.row input{flex:1}.pg{display:flex;gap:6px;margin-top:14px;align-items:center;color:var(--mut)}
.login{max-width:340px;margin:12vh auto}.chk{display:flex;gap:10px;align-items:center;margin-top:14px}.chk input{width:auto}
small{color:var(--mut)}code{background:#0f1115;padding:1px 6px;border-radius:6px;font-size:12px}
.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
</style></head><body>
{% if session.get('admin') %}
<nav><b>🎵 Music Bot</b>
<a href="{{ url_for('dashboard') }}" class="{{ 'on' if request.endpoint=='dashboard' }}">📊 Dashboard</a>
<a href="{{ url_for('users') }}" class="{{ 'on' if request.endpoint=='users' }}">👥 Users</a>
<a href="{{ url_for('downloads_page') }}" class="{{ 'on' if request.endpoint=='downloads_page' }}">⬇️ Downloads</a>
<a href="{{ url_for('songs_page') }}" class="{{ 'on' if request.endpoint=='songs_page' }}">💾 Songs</a>
<a href="{{ url_for('broadcast') }}" class="{{ 'on' if request.endpoint=='broadcast' }}">📣 Broadcast</a>
<a href="{{ url_for('settings') }}" class="{{ 'on' if request.endpoint=='settings' }}">⚙️ Settings</a>
<span class="sp"></span>
<form method="post" action="{{ url_for('logout') }}" style="margin:0"><input type="hidden" name="csrf" value="{{ csrf() }}"><button class="sm red">🚪 Logout</button></form>
</nav>{% endif %}
<main>
{% for m in get_flashed_messages() %}<div class="flash">{{ m }}</div>{% endfor %}
{% block body %}{% endblock %}
</main></body></html>""",
    "login.html": """{% extends "base.html" %}{% block title %}Login{% endblock %}
{% block body %}<div class="login card"><h1>🔐 Admin Login</h1>
<form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}">
<label>🔑 Password</label><input type="password" name="password" autofocus required>
<p><button style="width:100%">Login</button></p></form></div>{% endblock %}""",
    "dashboard.html": """{% extends "base.html" %}{% block title %}Dashboard{% endblock %}
{% block body %}<h1>📊 Dashboard</h1>
<div class="grid">
<div class="card"><div class="n">👥 {{ s.users }}</div><div class="l">Total users</div></div>
<div class="card"><div class="n">🆕 {{ s.new_today }}</div><div class="l">New today</div></div>
<div class="card"><div class="n">🟢 {{ s.active_today }}</div><div class="l">Active today</div></div>
<div class="card"><div class="n">⬇️ {{ s.downloads }}</div><div class="l">Total downloads</div></div>
<div class="card"><div class="n">📥 {{ s.downloads_today }}</div><div class="l">Downloads today</div></div>
<div class="card"><div class="n">🚫 {{ s.banned }}</div><div class="l">Banned</div></div>
<div class="card"><div class="n">💾 {{ s.cached }}</div><div class="l">Cached songs</div></div>
</div>
<div class="two">
<div><h2>🔥 Top songs</h2><div class="wrap"><table><tr><th>#</th><th>🎵 Song</th><th>⬇️ Downloads</th></tr>
{% for r in top %}<tr><td>{{ loop.index }}</td><td>{{ r.title }}</td><td>{{ r.c }}</td></tr>{% else %}<tr><td colspan="3"><small>Abhi koi data nahi.</small></td></tr>{% endfor %}</table></div></div>
<div><h2>🏆 Top users</h2><div class="wrap"><table><tr><th>#</th><th>🆔 ID</th><th>👤 Name</th><th>⬇️ DL</th></tr>
{% for u in tusers %}<tr><td>{{ loop.index }}</td><td>{{ u.user_id }}</td><td>{{ u.first_name or '' }} {% if u.username %}<small>@{{ u.username }}</small>{% endif %}</td><td>{{ u.downloads }}</td></tr>{% else %}<tr><td colspan="4"><small>Abhi koi data nahi.</small></td></tr>{% endfor %}</table></div></div>
</div>
<h2>🕒 Recent downloads</h2><div class="wrap"><table><tr><th>🕒 Time</th><th>👤 User</th><th>🎵 Song</th></tr>
{% for r in recent %}<tr><td>{{ r.ts }}</td><td>{{ r.first_name or '' }} {% if r.username %}<small>@{{ r.username }}</small>{% endif %}</td><td>{{ r.title }}</td></tr>
{% else %}<tr><td colspan="3"><small>Abhi koi data nahi.</small></td></tr>{% endfor %}</table></div>
{% endblock %}""",
    "users.html": """{% extends "base.html" %}{% block title %}Users{% endblock %}
{% block body %}<h1>👥 Users <small>({{ total }})</small></h1>
<form class="row" method="get"><input name="q" value="{{ q }}" placeholder="🔎 ID, username ya naam se search"><button>Search</button></form>
<br><div class="wrap"><table><tr><th>🆔 ID</th><th>👤 Name</th><th>🔗 Username</th><th>📅 Joined</th><th>🕒 Last seen</th><th>⬇️ DL</th><th>📌 Status</th><th>⚡ Action</th></tr>
{% for u in users %}<tr>
<td><code>{{ u.user_id }}</code></td><td>{{ u.first_name or '' }}</td><td>{% if u.username %}@{{ u.username }}{% else %}<small>-</small>{% endif %}</td>
<td>{{ u.joined_at }}</td><td>{{ u.last_seen }}</td><td>{{ u.downloads }}</td>
<td>{% if u.banned %}<span class="tag red">🚫 banned</span>{% else %}<span class="tag grn">✅ active</span>{% endif %}</td>
<td><form method="post" action="{{ url_for('ban', uid=u.user_id) }}" style="margin:0">
<input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="back" value="{{ request.full_path }}">
<input type="hidden" name="banned" value="{{ 0 if u.banned else 1 }}">
{% if u.banned %}<button class="sm grn">✅ Unban</button>{% else %}<button class="sm red">🚫 Ban</button>{% endif %}</form></td>
</tr>{% else %}<tr><td colspan="8"><small>Koi user nahi mila.</small></td></tr>{% endfor %}</table></div>
<div class="pg">
{% if page > 1 %}<a class="btn sm" href="?q={{ q|urlencode }}&page={{ page-1 }}">← Prev</a>{% endif %}
<span>Page {{ page }} / {{ pages }}</span>
{% if page < pages %}<a class="btn sm" href="?q={{ q|urlencode }}&page={{ page+1 }}">Next →</a>{% endif %}</div>
{% endblock %}""",
    "downloads.html": """{% extends "base.html" %}{% block title %}Downloads{% endblock %}
{% block body %}<h1>⬇️ Downloads <small>({{ total }})</small></h1>
<form class="row" method="get"><input name="q" value="{{ q }}" placeholder="🔎 Song, user ID ya username"><button>Search</button></form>
<br><div class="wrap"><table><tr><th>#</th><th>🕒 Time</th><th>🆔 User ID</th><th>👤 Name</th><th>🔗 Username</th><th>🎵 Song</th><th>🎬 Video ID</th></tr>
{% for r in rows %}<tr><td>{{ r.id }}</td><td>{{ r.ts }}</td><td><code>{{ r.user_id }}</code></td><td>{{ r.first_name or '' }}</td>
<td>{% if r.username %}@{{ r.username }}{% else %}<small>-</small>{% endif %}</td><td>{{ r.title }}</td><td><code>{{ r.video_id }}</code></td></tr>
{% else %}<tr><td colspan="7"><small>Koi download nahi mila.</small></td></tr>{% endfor %}</table></div>
<div class="pg">
{% if page > 1 %}<a class="btn sm" href="?q={{ q|urlencode }}&page={{ page-1 }}">← Prev</a>{% endif %}
<span>Page {{ page }} / {{ pages }}</span>
{% if page < pages %}<a class="btn sm" href="?q={{ q|urlencode }}&page={{ page+1 }}">Next →</a>{% endif %}</div>
{% endblock %}""",
    "songs.html": """{% extends "base.html" %}{% block title %}Songs{% endblock %}
{% block body %}<h1>💾 Cached Songs <small>({{ total }})</small></h1>
<form class="row" method="get"><input name="q" value="{{ q }}" placeholder="🔎 Song ya video ID"><button>Search</button></form>
<br><div class="wrap"><table><tr><th>🎬 Video ID</th><th>🎵 Title</th><th>⬇️ Downloads</th><th>📁 File ID</th></tr>
{% for r in rows %}<tr><td><code>{{ r.video_id }}</code></td><td>{{ r.title }}</td><td>{{ r.dl }}</td><td><small>{{ r.file_id[:24] }}…</small></td></tr>
{% else %}<tr><td colspan="4"><small>Koi song nahi mila.</small></td></tr>{% endfor %}</table></div>
<div class="pg">
{% if page > 1 %}<a class="btn sm" href="?q={{ q|urlencode }}&page={{ page-1 }}">← Prev</a>{% endif %}
<span>Page {{ page }} / {{ pages }}</span>
{% if page < pages %}<a class="btn sm" href="?q={{ q|urlencode }}&page={{ page+1 }}">Next →</a>{% endif %}</div>
{% endblock %}""",
    "broadcast.html": """{% extends "base.html" %}{% block title %}Broadcast{% endblock %}
{% block body %}<h1>📣 Broadcast</h1>
<div class="card"><form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}">
<label>✉️ Message (sirf valid Telegram HTML: &lt;b&gt;, &lt;i&gt;, &lt;a href=""&gt;, &lt;code&gt;)</label>
<textarea name="text" rows="6" required></textarea>
<p><small>👥 {{ count }} active users ko jayega.</small></p>
<button onclick="return confirm('Sabhi users ko bhejna hai?')">🚀 Send to all</button></form></div>
<h2>📡 Last broadcast status</h2><div class="card">{{ status or 'Abhi tak koi broadcast nahi hua.' }}</div>
{% endblock %}""",
    "settings.html": """{% extends "base.html" %}{% block title %}Settings{% endblock %}
{% block body %}<h1>⚙️ Settings</h1>
<div class="card"><form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}">
<div class="chk"><input type="checkbox" id="m" name="maintenance" value="1" {{ 'checked' if cfg.maintenance=='1' }}><label for="m" style="margin:0;color:var(--text)">🔧 Maintenance mode (sirf admins bot use kar paayenge)</label></div>
<label>📢 Force-join channel (e.g. @Sanjuownersmm — bot ko us channel mein admin banana hoga; khali = off)</label>
<input name="force_channel" value="{{ cfg.force_channel }}" placeholder="@channelusername">
<label>👑 Owner username</label>
<input name="owner_username" value="{{ cfg.owner_username }}" placeholder="@thehiddenreserve">
<label>🖼 Welcome banner image URL (optional)</label>
<input name="welcome_banner" value="{{ cfg.welcome_banner }}" placeholder="https://...jpg">
<label>👋 Welcome message (HTML allowed, {name} = user ka naam)</label>
<textarea name="welcome_text" rows="12">{{ cfg.welcome_text }}</textarea>
<p><button>💾 Save</button></p></form></div>
{% endblock %}""",
}
app.jinja_loader = DictLoader(TEMPLATES)


# ------------------------------------------------------------ security helpers
def csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


app.jinja_env.globals["csrf"] = csrf_token


@app.before_request
def check_csrf():
    if request.method == "POST":
        sent = request.form.get("csrf", "")
        if not hmac.compare_digest(sent, session.get("csrf", "")):
            abort(400, "Bad CSRF token")


@app.after_request
def secure_headers(resp):
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "no-store"
    return resp


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("admin"):
            return redirect(url_for("login"))
        return fn(*a, **kw)

    return wrapper


_fails = {}  # ip -> (count, first_ts) — tiny brute-force guard


def _locked(ip) -> bool:
    count, ts = _fails.get(ip, (0, 0))
    if time.time() - ts > 600:
        _fails.pop(ip, None)
        return False
    return count >= 5


def _paginate(total: int, page: int):
    return max(1, -(-total // PER_PAGE))


# ------------------------------------------------------------ routes
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
        if _locked(ip):
            flash("Bahut zyada galat attempts. 10 minute baad try karein.")
        elif ADMIN_PASSWORD and hmac.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
            _fails.pop(ip, None)
            session.clear()
            session["admin"] = True
            return redirect(url_for("dashboard"))
        else:
            count, ts = _fails.get(ip, (0, time.time()))
            _fails[ip] = (count + 1, ts)
            flash("Galat password.")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    return render_template(
        "dashboard.html", s=stats(), top=top_songs(10), recent=recent_downloads(15), tusers=top_users(5)
    )


@app.route("/users")
@login_required
def users():
    q = request.args.get("q", "").strip()
    page = max(1, request.args.get("page", 1, type=int))
    rows, total = list_users(q, PER_PAGE, (page - 1) * PER_PAGE)
    return render_template("users.html", users=rows, total=total, q=q, page=page, pages=_paginate(total, page))


@app.route("/downloads")
@login_required
def downloads_page():
    q = request.args.get("q", "").strip()
    page = max(1, request.args.get("page", 1, type=int))
    rows, total = list_downloads(q, PER_PAGE, (page - 1) * PER_PAGE)
    return render_template("downloads.html", rows=rows, total=total, q=q, page=page, pages=_paginate(total, page))


@app.route("/songs")
@login_required
def songs_page():
    q = request.args.get("q", "").strip()
    page = max(1, request.args.get("page", 1, type=int))
    rows, total = list_files(q, PER_PAGE, (page - 1) * PER_PAGE)
    return render_template("songs.html", rows=rows, total=total, q=q, page=page, pages=_paginate(total, page))


@app.route("/users/<int:uid>/ban", methods=["POST"])
@login_required
def ban(uid):
    if uid in ADMIN_IDS:
        flash("Admin ko ban nahi kar sakte.")
    else:
        banned = request.form.get("banned") == "1"
        set_ban(uid, banned)
        flash(f"User {uid} {'ban' if banned else 'unban'} ho gaya.")
    back = request.form.get("back", "")
    return redirect(back if back.startswith("/users") else url_for("users"))


def _run_broadcast(text: str):
    ids = all_user_ids()
    ok = failed = 0
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for i, uid in enumerate(ids, 1):
        try:
            r = requests.post(url, json={"chat_id": uid, "text": text, "parse_mode": "HTML"}, timeout=20)
            if r.status_code == 429:
                time.sleep(int(r.json().get("parameters", {}).get("retry_after", 3)) + 1)
                r = requests.post(url, json={"chat_id": uid, "text": text, "parse_mode": "HTML"}, timeout=20)
            ok, failed = (ok + 1, failed) if r.ok else (ok, failed + 1)
        except requests.RequestException:
            failed += 1
        if i % 25 == 0:
            set_setting("broadcast_status", f"Running… {i}/{len(ids)}")
        time.sleep(0.05)
    set_setting(
        "broadcast_status",
        f"Done at {time.strftime('%Y-%m-%d %H:%M:%S')} — sent: {ok}, failed: {failed}, total: {len(ids)}",
    )


@app.route("/broadcast", methods=["GET", "POST"])
@login_required
def broadcast():
    if request.method == "POST":
        text = request.form.get("text", "").strip()
        if text and not get_setting("broadcast_status").startswith("Running"):
            set_setting("broadcast_status", "Running… 0")
            threading.Thread(target=_run_broadcast, args=(text,), daemon=True).start()
            flash("Broadcast shuru ho gaya. Neeche status dekhein.")
        else:
            flash("Pehla broadcast abhi chal raha hai ya message khali hai.")
        return redirect(url_for("broadcast"))
    return render_template(
        "broadcast.html", count=len(all_user_ids()), status=get_setting("broadcast_status")
    )


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        set_setting("maintenance", "1" if request.form.get("maintenance") else "0")
        set_setting("force_channel", request.form.get("force_channel", "").strip())
        owner = request.form.get("owner_username", "").strip() or OWNER_USERNAME
        set_setting("owner_username", owner if owner.startswith("@") else "@" + owner)
        set_setting("welcome_banner", request.form.get("welcome_banner", "").strip())
        set_setting("welcome_text", request.form.get("welcome_text", "").strip() or DEFAULT_WELCOME)
        flash("Settings save ho gayi ✅")
        return redirect(url_for("settings"))
    keys = ("maintenance", "force_channel", "owner_username", "welcome_banner", "welcome_text")
    cfg = {k: get_setting(k) for k in keys}
    return render_template("settings.html", cfg=cfg)


# ======================================================================
# MAIN
# ======================================================================

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
main_log = logging.getLogger("main")


def run_admin():
    app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    if not BOT_TOKEN:
        sys.exit("BOT_TOKEN set nahi hai (.env file dekhein).")
    init()
    if ADMIN_PASSWORD:
        threading.Thread(target=run_admin, daemon=True).start()
        main_log.info("Admin panel: http://localhost:%s", PORT)
    else:
        main_log.warning("ADMIN_PASSWORD set nahi hai - web admin panel band rahega.")
    main_log.info("Bot polling shuru...")
    build_app().run_polling(drop_pending_updates=True)
