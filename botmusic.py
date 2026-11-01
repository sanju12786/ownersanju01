"""
Telegram Music Bot + Colorful 3D Web Admin Panel (single file, Termux friendly).

Run:   python music_bot.py
Needs: pip install -U python-telegram-bot httpx flask requests pillow

Koi .env nahi - saari settings neeche CONFIG section mein hain.
Private chat + GROUP dono mein kaam karta hai (group mein /play ya seedha naam bhejo).

ADMIN COMMANDS (sirf admins):
  /admin                     - admin panel (colorful buttons)
  /channels                  - channel list (optional, force-join band hai)
  /stats /ban /unban /broadcast /cancel /panel
"""
import asyncio
import functools
import hmac
import html
import inspect
import io
import logging
import re
import secrets
import sqlite3
import sys
import threading
import time

import httpx
import requests
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from jinja2 import DictLoader
from markupsafe import Markup
from telegram import Bot, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, Conflict, Forbidden, InvalidToken, NetworkError, RetryAfter, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ======================================================================
# CONFIG  (yahin sab kuch edit karein)
# ======================================================================
BOT_TOKEN = "8603249647:AAH07nonukCkLPmCF76JQ7Y0IuVK9lkIU4M"      # <-- BotFather wala (naya) token yahan daalo

ADMIN_IDS = {8244241281, 5574675470}

API_BASE = "https://music-api-2-production-1d61.up.railway.app"

OWNER_USERNAME = "@thehiddenreserve"

# Song card ke upar jo naam dikhega
BRAND_NAME = "SANJU MUSIC"

# Telegram ke coloured buttons (Bot API 9.4+). Support na ho to auto plain buttons.
COLOR_BUTTONS = True

# Web admin panel
ADMIN_PASSWORD = "Sanju@12345"               # <-- isse zaroor badal lein
SECRET_KEY = "change-this-long-random-secret-key-2026"
PORT = 8080
PUBLIC_URL = ""                              # e.g. "https://your-panel-url" (optional)

DB_PATH = "bot.db"
SEARCH_CACHE_SECONDS = 600                   # same gaana dobara -> API hit nahi, turant play
COVER_MAX_BYTES = 200_000                    # Telegram thumbnail limit

# ======================================================================
# DATABASE
# ======================================================================
_lock = threading.RLock()
_conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
_conn.row_factory = sqlite3.Row
for _pragma in ("PRAGMA journal_mode=WAL", "PRAGMA busy_timeout=8000", "PRAGMA synchronous=NORMAL"):
    try:
        _conn.execute(_pragma)
    except sqlite3.Error:
        pass

DEFAULT_WELCOME = (
    "🎧 <b>Hey {name}!</b> 🔥\n\n"
    "Gaane ka naam bhejo — <b>turant HD quality</b> mein bajega 🔊\n\n"
    "📝 Example: <code>Kesariya</code>"
)

DEFAULTS = {
    "maintenance": "0",
    "owner_username": OWNER_USERNAME,
    "welcome_banner": "",
    "welcome_text": DEFAULT_WELCOME,
    "broadcast_status": "",
    "broadcast_running": "0",
    "notify_admins": "1",
    # song cover (thumbnail) - admin panel se badal sakte hain
    "song_cover": "",          # custom logo / GIF ka direct URL
    "use_yt_thumb": "1",       # 1 = custom cover na ho to YouTube thumbnail
}
DEFAULTS_VERSION = "13"


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
            CREATE TABLE IF NOT EXISTS channels(
                chat TEXT PRIMARY KEY,
                title TEXT,
                link TEXT
            );
            """
        )
        for k, v in DEFAULTS.items():
            _conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (k, v))
        row = _conn.execute("SELECT value FROM settings WHERE key='defaults_ver'").fetchone()
        if not row or row["value"] != DEFAULTS_VERSION:
            for k in ("welcome_text", "owner_username"):
                _conn.execute("UPDATE settings SET value=? WHERE key=?", (DEFAULTS[k], k))
            _conn.execute(
                "INSERT INTO settings(key, value) VALUES('defaults_ver', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (DEFAULTS_VERSION,),
            )
        _conn.commit()


def get_setting(key):
    row = _one("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else DEFAULTS.get(key, "")


def set_setting(key, value):
    _exec("INSERT INTO settings(key, value) VALUES(?, ?) "
          "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


# ---------- channels (optional, force-join abhi band hai) ----------
def list_channels():
    return _all("SELECT * FROM channels ORDER BY rowid")


def add_channel(chat, title, link, aliases=()):
    with _lock:
        for a in aliases:
            _conn.execute("DELETE FROM channels WHERE lower(chat)=lower(?)", (a,))
        _conn.execute(
            "INSERT INTO channels(chat, title, link) VALUES(?, ?, ?) "
            "ON CONFLICT(chat) DO UPDATE SET title=excluded.title, link=excluded.link",
            (chat, title, link),
        )
        _conn.commit()


def del_channels(keys):
    n = 0
    with _lock:
        for k in keys:
            n += _conn.execute("DELETE FROM channels WHERE lower(chat)=lower(?)", (k,)).rowcount
        _conn.commit()
    return n


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


def user_total_downloads(user_id):
    row = _one("SELECT downloads FROM users WHERE user_id=?", (user_id,))
    return row["downloads"] if row else 0


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


def clear_file_cache():
    return _exec("DELETE FROM files").rowcount


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
        where = ("WHERE d.title LIKE ? OR CAST(d.user_id AS TEXT) LIKE ? "
                 "OR u.username LIKE ? OR u.first_name LIKE ?")
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


def db_stats():
    q = lambda sql: _one(sql)["c"]  # noqa: E731
    return {
        "users": q("SELECT COUNT(*) c FROM users"),
        "banned": q("SELECT COUNT(*) c FROM users WHERE banned=1"),
        "new_today": q("SELECT COUNT(*) c FROM users WHERE date(joined_at)=date('now','localtime')"),
        "active_today": q("SELECT COUNT(*) c FROM users WHERE date(last_seen)=date('now','localtime')"),
        "downloads": q("SELECT COUNT(*) c FROM downloads"),
        "downloads_today": q("SELECT COUNT(*) c FROM downloads WHERE date(ts)=date('now','localtime')"),
        "cached": q("SELECT COUNT(*) c FROM files"),
        "channels": q("SELECT COUNT(*) c FROM channels"),
    }


# ======================================================================
# TELEGRAM BOT
# ======================================================================
log = logging.getLogger("musicbot")

# python-telegram-bot ke version ke hisaab se sahi argument naam (na mile to bina thumb)
try:
    _AUDIO_PARAMS = set(inspect.signature(Bot.send_audio).parameters)
except (TypeError, ValueError):
    _AUDIO_PARAMS = set()
THUMB_KW = "thumbnail" if "thumbnail" in _AUDIO_PARAMS else ("thumb" if "thumb" in _AUDIO_PARAMS else None)

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{6,20}$")
MAX_BYTES = 49 * 1024 * 1024  # Telegram bot upload limit ~50 MB
MAX_DURATION = 24 * 3600

AUDIO_TYPES = ("audio/", "application/octet-stream", "video/mp4", "video/x-m4a")

# search cache: query -> (timestamp, item)  (repeat search = 0 network)
_search_cache = {}


# ---------------------------------------------------------------- helpers
def esc(value) -> str:
    return html.escape(str(value or ""))


def fmt_dur(sec) -> str:
    try:
        sec = int(sec)
    except (TypeError, ValueError):
        return ""
    if sec <= 0 or sec > MAX_DURATION:
        return ""
    return f"{sec // 60}:{sec % 60:02d}"


def safe_filename(title: str, ext: str = "mp3") -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", title or "song").strip()[:80] or "song"
    return f"{name}.{ext}"


def clip(text: str, limit: int) -> str:
    """HTML-safe truncate - tag kabhi beech mein nahi katega."""
    if len(text) <= limit:
        return text
    out = text[: max(0, limit - 1)]
    if out.count("<") > out.count(">"):
        cut = out.rfind("<")
        if cut > 0:
            out = out[:cut]
    return out + "…"


_SMALLCAP = {
    "a": "ᴀ", "b": "ʙ", "c": "ᴄ", "d": "ᴅ", "e": "ᴇ", "f": "ꜰ", "g": "ɢ", "h": "ʜ",
    "i": "ɪ", "j": "ᴊ", "k": "ᴋ", "l": "ʟ", "m": "ᴍ", "n": "ɴ", "o": "ᴏ", "p": "ᴘ",
    "q": "ǫ", "r": "ʀ", "s": "ꜱ", "t": "ᴛ", "u": "ᴜ", "v": "ᴠ", "w": "ᴡ", "x": "x",
    "y": "ʏ", "z": "ᴢ",
}


def lab(text: str) -> str:
    """Label style: uppercase -> sans-serif bold, lowercase -> small caps (values plain)."""
    out = []
    for ch in text:
        if "A" <= ch <= "Z":
            out.append(chr(0x1D5E6 + ord(ch) - 65))
        elif ch in _SMALLCAP:
            out.append(_SMALLCAP[ch])
        else:
            out.append(ch)
    return "".join(out)


def owner_url() -> str:
    return "https://t.me/" + (get_setting("owner_username") or OWNER_USERNAME).lstrip("@")


def chat_ref(value: str):
    value = str(value).strip()
    return int(value) if value.lstrip("-").isdigit() else value


async def api_get(path: str, **params) -> httpx.Response:
    async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15), follow_redirects=True) as client:
        return await client.get(f"{API_BASE}{path}", params=params)


# ---------------------------------------------------------------- 3D logo (Pillow)
_LOGO = {"bytes": None, "file_id": None, "tried": False}


def make_logo():
    """3D-style extruded music logo banner. Returns PNG bytes or None."""
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont
    except ImportError:
        return None
    try:
        W, H = 1000, 560
        img = Image.new("RGB", (W, H))
        d = ImageDraw.Draw(img)
        for y in range(H):
            t = y / H
            d.line([(0, y), (W, y)], fill=(int(20 + 70 * t), int(8 + 14 * t), int(60 + 80 * (1 - t))))
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse([40, 60, 560, 520], fill=(255, 60, 170, 150))
        gd.ellipse([520, 120, 980, 460], fill=(0, 200, 255, 90))
        glow = glow.filter(ImageFilter.GaussianBlur(70))
        img = Image.alpha_composite(img.convert("RGBA"), glow)
        d = ImageDraw.Draw(img)

        def note(dx, dy, fill):
            d.ellipse([dx + 60, dy + 260, dx + 170, dy + 330], fill=fill)
            d.ellipse([dx + 230, dy + 230, dx + 340, dy + 300], fill=fill)
            d.rectangle([dx + 150, dy + 90, dx + 170, dy + 295], fill=fill)
            d.rectangle([dx + 320, dy + 60, dx + 340, dy + 265], fill=fill)
            d.polygon([(dx + 150, dy + 90), (dx + 340, dy + 60),
                       (dx + 340, dy + 120), (dx + 150, dy + 150)], fill=fill)

        ox, oy, depth = 100, 90, 34
        for i in range(depth, 0, -1):
            k = i / depth
            note(ox + int(i * 0.9), oy + int(i * 0.9),
                 (int(70 + 120 * (1 - k)), int(10 + 30 * (1 - k)), int(140 + 90 * k)))
        note(ox, oy, (255, 214, 64, 255))
        note(ox - 4, oy - 4, (255, 240, 150, 255))
        note(ox, oy, (255, 196, 40, 255))

        font = font2 = None
        for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVuSans-Bold.ttf",
                  "/system/fonts/Roboto-Bold.ttf", "/system/fonts/DroidSans-Bold.ttf", "arialbd.ttf"):
            try:
                font, font2 = ImageFont.truetype(p, 120), ImageFont.truetype(p, 40)
                break
            except OSError:
                continue
        if font is None:
            try:
                font, font2 = ImageFont.load_default(size=120), ImageFont.load_default(size=40)
            except TypeError:
                font = font2 = ImageFont.load_default()
        tx = 500
        for word, ty, top in (("MUSIC", 130, (0, 230, 255)), ("BOT", 260, (255, 90, 190))):
            for i in range(22, 0, -1):
                d.text((tx + i, ty + i), word, font=font, fill=(25 + i, 8, 70 + i * 3))
            d.text((tx, ty), word, font=font, fill=top)
        d.text((tx, 410), "Fast • Free • HD Music", font=font2, fill=(255, 255, 255))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "PNG")
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        log.warning("logo generate failed: %s", exc)
        return None


async def get_logo_bytes():
    if not _LOGO["tried"]:
        _LOGO["tried"] = True
        _LOGO["bytes"] = await asyncio.to_thread(make_logo)
    return _LOGO["bytes"]


# ---------------------------------------------------------------- COLORED keyboards
def _style_supported() -> bool:
    try:
        return "style" in inspect.signature(InlineKeyboardButton.__init__).parameters
    except (TypeError, ValueError):
        return False


STYLE_SUPPORTED = _style_supported()


def _maybe_disable_colors(exc) -> bool:
    """Agar coloured buttons ki wajah se Telegram error de to colours band karke normal buttons chalao."""
    global COLOR_BUTTONS
    if not COLOR_BUTTONS:
        return False
    msg = str(exc).lower()
    if any(w in msg for w in ("button", "style", "reply markup", "keyboard", "unknown field")):
        COLOR_BUTTONS = False
        log.warning("Coloured buttons support nahi -> auto band (%s). Normal buttons chalenge.", exc)
        return True
    return False


def btn(text: str, style: str = None, **kw) -> InlineKeyboardButton:
    """style: 'primary' (blue) | 'success' (green) | 'danger' (red) -> Telegram coloured button."""
    if style and COLOR_BUTTONS and STYLE_SUPPORTED:
        kw["style"] = style
    return InlineKeyboardButton(text, **kw)


def main_kb(is_admin=False) -> InlineKeyboardMarkup:
    rows = [
        [btn("🟢 🎵 Gaana Dhundo", "success", callback_data="menu:search")],
        [
            btn("🔵 ℹ️ Help", "primary", callback_data="menu:help"),
            btn("🔴 👑 Owner", "danger", url=owner_url()),
        ],
    ]
    if is_admin:
        rows.append([btn("🔵 🛠 Admin Panel", "primary", callback_data="admin:home")])
    return InlineKeyboardMarkup(rows)


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[btn("🏠 Home", "primary", callback_data="menu:home")]])


def song_kb() -> InlineKeyboardMarkup:
    """Song ke neeche: gaana change karo / home / owner."""
    return InlineKeyboardMarkup([
        [btn("🟢 🔄 Change Song", "success", callback_data="menu:search")],
        [
            btn("🔵 🏠 Home", "primary", callback_data="menu:home"),
            btn("🔴 👑 Owner", "danger", url=owner_url()),
        ],
    ])


def admin_kb() -> InlineKeyboardMarkup:
    maint_on = get_setting("maintenance") == "1"
    notify_on = get_setting("notify_admins") == "1"
    rows = [
        [
            btn("📊 Stats", "primary", callback_data="admin:stats"),
            btn("🔥 Top Songs", "success", callback_data="admin:top"),
        ],
        [
            btn("📣 Broadcast", "danger", callback_data="admin:bc"),
            btn("📢 Channels", "primary", callback_data="admin:ch"),
        ],
        [btn(f"🔧 Maintenance: {'ON 🔴' if maint_on else 'OFF 🟢'}",
             "danger" if maint_on else "success", callback_data="admin:maint")],
        [btn(f"🔔 Play Alerts: {'ON 🟢' if notify_on else 'OFF 🔴'}",
             "success" if notify_on else "danger", callback_data="admin:notify")],
    ]
    if PUBLIC_URL:
        rows.append([btn("🌐 Web Panel", "primary", url=PUBLIC_URL + "/")])
    rows.append([btn("🏠 Home", "primary", callback_data="menu:home")])
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------- gate (ban / maintenance)
async def _answer(q, text: str = "", alert: bool = False):
    """Callback answer - dobara answer karne par crash nahi hota."""
    if q is None:
        return
    try:
        await q.answer(text[:190], show_alert=alert)
    except (BadRequest, TelegramError):
        pass


async def deny(update: Update, text: str, markup=None):
    q = update.callback_query
    if q:
        await _answer(q, text, alert=True)
        if markup and q.message:
            try:
                await q.message.reply_text(text, reply_markup=markup)
            except TelegramError:
                pass
    elif update.effective_message:
        try:
            await update.effective_message.reply_text(text, reply_markup=markup)
        except TelegramError:
            pass


async def gate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Sirf ban aur maintenance check. Force-join band hai."""
    user = update.effective_user
    if not user:
        return False
    try:
        upsert_user(user)
    except sqlite3.Error as exc:
        log.warning("upsert_user failed: %s", exc)
    if user.id in ADMIN_IDS:
        return True
    if is_banned(user.id):
        await deny(update, "🚫 Aapko is bot se ban kar diya gaya hai.\n\n"
                           f"Help ke liye owner se baat karein: {get_setting('owner_username')}")
        return False
    if get_setting("maintenance") == "1":
        await deny(update, "🛠 Bot abhi maintenance mein hai. Thodi der baad try karein.")
        return False
    return True


def admin_only(fn):
    @functools.wraps(fn)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or update.effective_user.id not in ADMIN_IDS:
            if update.callback_query:
                await _answer(update.callback_query, "Admin only.", alert=True)
            return
        return await fn(update, context)

    return wrapper


# ---------------------------------------------------------------- welcome / help
async def _welcome_once(context, chat_id: int, text: str, banner: str, kb, is_group: bool = False):
    if len(text) <= 1000:
        if banner:
            try:
                await context.bot.send_photo(chat_id, banner, caption=text,
                                             parse_mode=ParseMode.HTML, reply_markup=kb)
                return
            except TelegramError as exc:
                log.warning("welcome banner failed: %s", exc)
        elif not is_group:  # group mein bada logo har baar na bhejein
            try:
                if _LOGO["file_id"]:
                    await context.bot.send_photo(chat_id, _LOGO["file_id"], caption=text,
                                                 parse_mode=ParseMode.HTML, reply_markup=kb)
                    return
                data = await get_logo_bytes()
                if data:
                    sent = await context.bot.send_photo(
                        chat_id, InputFile(io.BytesIO(data), filename="logo.png"),
                        caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
                    _LOGO["file_id"] = sent.photo[-1].file_id
                    return
            except TelegramError as exc:
                log.warning("logo send failed: %s", exc)
    await context.bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def send_welcome(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user, is_group: bool = False):
    text = get_setting("welcome_text").replace("{name}", esc(user.first_name))
    banner = get_setting("welcome_banner").strip()
    for attempt in (1, 2):
        kb = main_kb(user.id in ADMIN_IDS)
        try:
            await _welcome_once(context, chat_id, text, banner, kb, is_group)
            return
        except BadRequest as exc:
            if attempt == 1 and _maybe_disable_colors(exc):
                continue
            log.warning("welcome failed: %s", exc)
            break
        except TelegramError as exc:
            log.warning("welcome failed: %s", exc)
            break
    try:  # last resort: plain text
        await context.bot.send_message(chat_id, re.sub(r"<[^>]+>", "", text))
    except TelegramError:
        pass


def help_text() -> str:
    return (
        "ℹ️ <b>Help / Guide</b>\n\n"
        "1️⃣ Gaane ka naam bhejo ya <code>/play naam</code> likho\n"
        "2️⃣ Best match gaana cover ke saath turant play ho jayega 🎧\n"
        "3️⃣ Group mein bhi chalta hai — <code>/play naam</code>\n\n"
        "📌 <b>Commands</b>\n"
        "/start - Bot start karein\n"
        "/play &lt;naam&gt; - Gaana play karein\n"
        "/help - Ye guide\n\n"
        f"👑 Owner: {esc(get_setting('owner_username'))}\n"
        f"💬 Update / problem ke liye DM: {esc(get_setting('owner_username'))}"
    )


def search_prompt() -> str:
    return (
        f"🎧 <b>{lab('Gaana Bhejo')}</b>\n"
        "<blockquote>Gaane ka naam type karke bhejo — turant bajega 🎵\n"
        "📝 Example: <code>Kesariya</code></blockquote>"
    )


# ---------------------------------------------------------------- user commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await gate(update, context):
        return
    is_group = update.effective_chat.type in ("group", "supergroup")
    await send_welcome(context, update.effective_chat.id, update.effective_user, is_group)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await gate(update, context):
        return
    await update.message.reply_text(help_text(), parse_mode=ParseMode.HTML,
                                    reply_markup=main_kb(update.effective_user.id in ADMIN_IDS))


async def play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await gate(update, context):
        return
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text("🎵 Usage: /play <gaane ka naam>\nExample: /play Kesariya")
        return
    await do_search(update, context, query)


async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not await gate(update, context):
        return
    action = (q.data or "")[5:]
    await _answer(q)
    if action == "search":
        await q.message.reply_text(search_prompt(), parse_mode=ParseMode.HTML)
    elif action == "help":
        await q.message.reply_text(help_text(), parse_mode=ParseMode.HTML, reply_markup=back_kb())
    else:
        is_group = q.message.chat.type in ("group", "supergroup")
        await send_welcome(context, q.message.chat_id, update.effective_user, is_group)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else 0
    if uid in ADMIN_IDS and context.user_data is not None and context.user_data.pop("await_bc", False):
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
    """Search -> best result -> TURANT play (repeat search cache se 0 network)."""
    msg = update.message
    key = " ".join(query.lower().split())

    # 1) cache hit -> bina API ke turant bajao
    hit = _search_cache.get(key)
    if hit and time.time() - hit[0] < SEARCH_CACHE_SECONDS:
        await _play_item(context, msg.chat_id, update.effective_user, hit[1], query)
        return

    context.application.create_task(context.bot.send_chat_action(msg.chat_id, ChatAction.UPLOAD_VOICE))
    try:
        resp = await api_get("/search", q=query, limit=1)
        resp.raise_for_status()
        results = (resp.json().get("results")) or []
    except Exception as exc:  # noqa: BLE001
        log.warning("search failed for %r: %s", query, exc)
        await msg.reply_text("❌ Search mein problem aayi, thodi der baad try karein.", reply_markup=back_kb())
        return

    item = next((r for r in results if r.get("id") and VIDEO_ID.match(str(r["id"]))), None)
    if not item:
        await msg.reply_text(f"😕 '{query}' ke liye kuch nahi mila. Doosra naam try karein.", reply_markup=back_kb())
        return

    if len(_search_cache) > 500:
        _search_cache.clear()
    _search_cache[key] = (time.time(), item)
    await _play_item(context, msg.chat_id, update.effective_user, item, query)


async def _play_item(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user, item: dict, query: str):
    meta = context.application.bot_data.setdefault("meta", {})
    if len(meta) > 3000:
        meta.clear()
    meta[item["id"]] = item
    await deliver(context, chat_id, user, item["id"], item, query)


# ---------------------------------------------------------------- SONG CARD (theme)
def song_card(vid: str, title: str, meta: dict, bot_username: str,
              requester: str = "", fancy: bool = True) -> str:
    """Aesthetic streaming-card caption. fancy=False -> plain fallback (no blockquote)."""
    brand = lab(BRAND_NAME) if fancy else BRAND_NAME
    dur = fmt_dur(meta.get("duration"))
    who = (requester or "").strip()[:32]

    lines = [
        f"🎧 <b>{brand}</b>",
        "━━━━━━━━━━━━━━━",
        f"🎵 <b>{lab('Now Playing')}</b>",
        "",
    ]

    block = [f"🎶 <b>{lab('Title')}</b>", esc(title[:90])]
    extras = []
    if dur:
        extras.append(f"⏱ {dur}")
    if who:
        extras.append(f"👤 {esc(who)}")
    if extras:
        block += ["", "   •   ".join(extras)]

    if fancy:
        lines.append("<blockquote>" + "\n".join(block) + "</blockquote>")
    else:
        lines += block

    lines += ["", f"❥ <b>{lab('Enjoy the beat')}</b>", f"🎧 @{esc(bot_username or 'bot')}"]
    return clip("\n".join(lines), 1024)


# ---------------------------------------------------------------- COVER (thumbnail)
async def _download_image(url: str):
    """Custom cover (jpg/png/gif) - 200KB se chhota hona chahiye."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            r = await client.get(url)
        if r.status_code != 200:
            return None
        if not r.headers.get("content-type", "").lower().startswith("image"):
            return None
        if not r.content or len(r.content) > COVER_MAX_BYTES:
            return None
        return r.content
    except Exception as exc:  # noqa: BLE001
        log.info("custom cover fetch failed: %s", exc)
        return None


async def fetch_yt_thumb(vid: str):
    for name in ("hqdefault", "mqdefault"):
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                r = await client.get(f"https://i.ytimg.com/vi/{vid}/{name}.jpg")
            if r.status_code != 200:
                continue
            if not r.headers.get("content-type", "").startswith("image"):
                continue
            if not (2_000 < len(r.content) < COVER_MAX_BYTES):
                continue
            return r.content
        except Exception as exc:  # noqa: BLE001
            log.info("thumb fetch failed for %s/%s: %s", vid, name, exc)
    return None


async def fetch_cover(vid: str):
    """Custom cover pehle (panel se), warna YouTube thumbnail."""
    custom = get_setting("song_cover").strip()
    if custom:
        data = await _download_image(custom)
        if data:
            return data
        log.info("custom cover unusable, YouTube thumbnail try kar raha hoon")
    if get_setting("use_yt_thumb") == "1":
        return await fetch_yt_thumb(vid)
    return None


# ---------------------------------------------------------------- ADMIN PLAY NOTIFICATION
async def notify_admins(context: ContextTypes.DEFAULT_TYPE, user, vid: str, title: str, chat_title: str = ""):
    if get_setting("notify_admins") != "1":
        return
    uname = f"@{esc(user.username)}" if user.username else "—"
    text = (
        "🔔 <b>New Song Played!</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"👤 <b>User:</b> <a href=\"tg://user?id={user.id}\">{esc(user.first_name) or 'User'}</a>\n"
        f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
        f"🔗 <b>Username:</b> {uname}\n"
        + (f"💬 <b>Chat:</b> {esc(chat_title)}\n" if chat_title else "")
        + f"🎵 <b>Song:</b> {esc(title)}\n"
        f"🎬 <b>Link:</b> https://youtu.be/{esc(vid)}\n"
        f"🔢 <b>User total plays:</b> {user_total_downloads(user.id)}\n"
        f"🕒 <b>Time:</b> {time.strftime('%d-%m-%Y %I:%M:%S %p')}"
    )
    for admin_id in ADMIN_IDS:
        if admin_id == user.id:
            continue
        try:
            await context.bot.send_message(admin_id, text, parse_mode=ParseMode.HTML,
                                           disable_web_page_preview=True)
        except TelegramError as exc:
            log.info("admin notify failed for %s: %s", admin_id, exc)


def after_play(context: ContextTypes.DEFAULT_TYPE, user, vid: str, title: str, chat_title: str = ""):
    try:
        log_download(user.id, vid, title)
    except sqlite3.Error as exc:
        log.warning("log_download failed: %s", exc)
    context.application.create_task(notify_admins(context, user, vid, title, chat_title))


async def deliver(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user, vid: str, meta: dict, query: str = ""):
    """Ek hi message: cover (thumbnail) ke saath song play + aesthetic card caption."""
    user_id = user.id
    busy = context.application.bot_data.setdefault("busy", set())
    if user_id in busy:
        await context.bot.send_message(chat_id, "⏳ Pehla gaana abhi aa raha hai, thoda wait karein.")
        return
    busy.add(user_id)

    meta = meta or {}
    title = (meta.get("title") or "Song").strip()[:140] or "Song"
    bot_username = context.application.bot_data.get("bot_username") or context.bot.username or "bot"
    requester = user.first_name or ""
    caption = song_card(vid, title, meta, bot_username, requester, True)
    plain_caption = song_card(vid, title, meta, bot_username, requester, False)
    performer = (meta.get("channel") or BRAND_NAME)[:64]
    try:
        duration = int(meta.get("duration") or 0) or None
    except (TypeError, ValueError):
        duration = None
    if duration and (duration <= 0 or duration > MAX_DURATION):
        duration = None

    try:
        chat_title = context.application.bot_data.get("chat_titles", {}).get(chat_id, "")
    except Exception:  # noqa: BLE001
        chat_title = ""

    context.application.create_task(context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_VOICE))

    async def _send_once(kw):
        try:
            return await context.bot.send_audio(**kw)
        except RetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 1)
            return await context.bot.send_audio(**kw)

    async def send(audio, timeout, thumb):
        kw = dict(
            chat_id=chat_id, audio=audio, title=title[:64], performer=performer, duration=duration,
            caption=caption, parse_mode=ParseMode.HTML, reply_markup=song_kb(),
            read_timeout=timeout, write_timeout=timeout, connect_timeout=30,
        )
        if thumb and THUMB_KW:
            kw[THUMB_KW] = InputFile(io.BytesIO(thumb), filename="cover.jpg")
        try:
            return await _send_once(kw)
        except BadRequest as exc:
            log.info("send_audio BadRequest: %s", exc)
            msg = str(exc).lower()
            changed = False
            if _maybe_disable_colors(exc):
                kw["reply_markup"] = song_kb()
                changed = True
            if thumb and THUMB_KW and "thumb" in msg:
                kw.pop(THUMB_KW, None)
                changed = True
            if any(w in msg for w in ("parse", "entit", "blockquote", "tag")):
                kw["caption"] = plain_caption
                changed = True
            if not changed:
                raise
            return await _send_once(kw)

    try:
        # 1) cached file_id -> sabse fast (cover file_id ke andar hi hota hai)
        cached = get_cached(vid)
        if cached and cached["file_id"]:
            try:
                await _send_once(dict(
                    chat_id=chat_id, audio=cached["file_id"], caption=caption,
                    parse_mode=ParseMode.HTML, reply_markup=song_kb(),
                    title=title[:64], performer=performer, duration=duration,
                ))
                after_play(context, user, vid, cached["title"] or title, chat_title)
                return
            except TelegramError as exc:
                log.info("cached file_id for %s no longer valid (%s)", vid, exc)

        # cover pehle le lo, phir turant URL se play
        thumb = await fetch_cover(vid)

        try:
            sent = await send(f"{API_BASE}/download?id={vid}", 120, thumb)
            if sent and sent.audio:
                cache_file(vid, sent.audio.file_id, title)
            after_play(context, user, vid, title, chat_title)
            return
        except TelegramError as exc:
            log.info("direct URL play failed for %s (%s), fallback to upload", vid, exc)

        # 3) fallback: download karke upload
        resp = await api_get("/download", id=vid)
        ctype = (resp.headers.get("content-type") or "").lower()
        if resp.status_code != 200 or not ctype.startswith(AUDIO_TYPES):
            raise RuntimeError(f"download api returned {resp.status_code} {ctype}")
        data = resp.content
        if not data:
            raise RuntimeError("download api returned empty body")
        if len(data) > MAX_BYTES:
            await context.bot.send_message(chat_id, "❌ Ye file 50MB se badi hai, Telegram bot se nahi bhej sakte.")
            return
        ext = "m4a" if ("mp4" in ctype or "m4a" in ctype) else "mp3"

        def mk():
            return InputFile(io.BytesIO(data), filename=safe_filename(title, ext))

        try:
            sent = await send(mk(), 180, thumb)
        except TelegramError as exc:
            log.info("upload with cover failed (%s), retry without cover", exc)
            if not thumb:
                raise
            sent = await send(mk(), 180, None)
        if sent and sent.audio:
            cache_file(vid, sent.audio.file_id, title)
        after_play(context, user, vid, title, chat_title)
    except Exception as exc:  # noqa: BLE001
        log.exception("play failed for %s: %s", vid, exc)
        try:
            await context.bot.send_message(chat_id, "❌ Gaana play nahi ho paya. Dobara try karein.")
        except TelegramError:
            pass
    finally:
        busy.discard(user_id)


# ---------------------------------------------------------------- admin
def stats_text() -> str:
    s = db_stats()
    return (
        "📊 <b>Bot Stats</b>\n\n"
        f"👥 Users: <b>{s['users']}</b> (🚫 banned: {s['banned']})\n"
        f"🆕 Aaj naye: <b>{s['new_today']}</b>\n"
        f"🟢 Aaj active: <b>{s['active_today']}</b>\n"
        f"⬇️ Total plays: <b>{s['downloads']}</b> (aaj: {s['downloads_today']})\n"
        f"💾 Cached songs: <b>{s['cached']}</b>"
    )


def channels_text() -> str:
    rows = list_channels()
    body = "\n".join(
        f"{i}. 📢 <b>{esc(r['title'])}</b>\n     <code>{esc(r['chat'])}</code>" for i, r in enumerate(rows, 1)
    ) or "Koi channel save nahi hai (force-join band hai, bot bina join bhi chalega)."
    return (
        "📢 <b>Channels</b> <i>(optional — force-join abhi OFF hai)</i>\n\n"
        f"{body}\n\n"
        "➕ <code>/addchannel @username</code>\n"
        "➖ <code>/delchannel @username</code>"
    )


async def _edit(q, text: str, kb):
    try:
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb,
                                  disable_web_page_preview=True)
    except BadRequest:
        try:
            await q.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except TelegramError:
            pass


@admin_only
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛠 <b>Admin Panel</b>\n\nNeeche se option chuno 👇",
                                    parse_mode=ParseMode.HTML, reply_markup=admin_kb())


@admin_only
async def on_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    action = (q.data or "")[6:]
    await _answer(q)
    back = InlineKeyboardMarkup([[btn("🔙 Admin Panel", "primary", callback_data="admin:home")]])
    if action == "home":
        await _edit(q, "🛠 <b>Admin Panel</b>\n\nNeeche se option chuno 👇", admin_kb())
    elif action == "stats":
        await _edit(q, stats_text(), back)
    elif action == "top":
        rows = top_songs(10)
        body = "\n".join(f"{i}. 🎵 {esc(r['title'])} — <b>{r['c']}</b>"
                         for i, r in enumerate(rows, 1)) or "Abhi koi data nahi."
        await _edit(q, f"🔥 <b>Top Songs</b>\n\n{body}", back)
    elif action == "ch":
        await _edit(q, channels_text(), back)
    elif action == "maint":
        set_setting("maintenance", "0" if get_setting("maintenance") == "1" else "1")
        await _edit(q, "🛠 <b>Admin Panel</b>\n\nMaintenance mode update ho gaya ✅", admin_kb())
    elif action == "notify":
        set_setting("notify_admins", "0" if get_setting("notify_admins") == "1" else "1")
        await _edit(q, "🛠 <b>Admin Panel</b>\n\nPlay alerts update ho gaye ✅", admin_kb())
    elif action == "bc":
        context.user_data["await_bc"] = True
        await _edit(
            q,
            "📣 <b>Broadcast</b>\n\nAb wo message bhejo jo sabko bhejna hai (HTML allowed).\nCancel: /cancel",
            back,
        )


# ---- channel management (optional) ----
@admin_only
async def channels_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(channels_text(), parse_mode=ParseMode.HTML)


@admin_only
async def addchannel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage:\n/addchannel @username")
        return
    ref = context.args[0]
    if not ref.lstrip("-").isdigit() and not ref.startswith("@"):
        ref = "@" + ref
    link = context.args[1] if len(context.args) > 1 else ""
    try:
        chat = await context.bot.get_chat(chat_ref(ref))
    except TelegramError as exc:
        await update.message.reply_text(
            f"❌ Channel nahi mila.\n<code>{esc(exc)}</code>", parse_mode=ParseMode.HTML)
        return
    if not link:
        link = f"https://t.me/{chat.username}" if chat.username else (chat.invite_link or "")
    aliases = [ref] + (["@" + chat.username] if chat.username else [])
    add_channel(str(chat.id), chat.title or ref, link, aliases)
    await update.message.reply_text(f"✅ Channel save ho gaya: <b>{esc(chat.title)}</b>",
                                    parse_mode=ParseMode.HTML)


@admin_only
async def delchannel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /delchannel @username")
        return
    ref = context.args[0]
    if not ref.lstrip("-").isdigit() and not ref.startswith("@"):
        ref = "@" + ref
    keys = [ref]
    try:
        chat = await context.bot.get_chat(chat_ref(ref))
        keys.append(str(chat.id))
        if chat.username:
            keys.append("@" + chat.username)
    except TelegramError:
        pass
    n = del_channels(keys)
    await update.message.reply_text("🗑 Channel hata diya." if n else "❌ Ye channel list mein nahi mila.")


@admin_only
async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data is not None:
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
    if get_setting("broadcast_running") == "1":
        await update.message.reply_text("⏳ Ek broadcast abhi chal raha hai. Khatam hone ka wait karein.")
        return
    ids = all_user_ids()
    await update.message.reply_text(f"📣 Broadcast shuru: {len(ids)} users ko bhej raha hoon…")
    context.application.create_task(_broadcast(context, update.effective_chat.id, ids, text))


async def _broadcast(context: ContextTypes.DEFAULT_TYPE, admin_chat: int, ids: list, text: str):
    set_setting("broadcast_running", "1")
    ok = failed = 0
    try:
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
            except TelegramError:
                failed += 1
            await asyncio.sleep(0.05)
    finally:
        set_setting("broadcast_running", "0")
        set_setting("broadcast_status",
                    f"Done at {time.strftime('%Y-%m-%d %H:%M:%S')} — sent: {ok}, failed: {failed}, total: {len(ids)}")
    try:
        await context.bot.send_message(admin_chat, f"✅ Broadcast complete.\n📨 Sent: {ok}\n❌ Failed: {failed}")
    except TelegramError:
        pass


@admin_only
async def panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if PUBLIC_URL:
        await update.message.reply_text(
            "🛠 Web Admin Panel",
            reply_markup=InlineKeyboardMarkup([[btn("🌐 Open Panel", "primary", url=PUBLIC_URL + "/")]]),
        )
    else:
        await update.message.reply_text(
            f"Panel local chal raha hai: http://localhost:{PORT}\n(PUBLIC_URL code mein set nahi hai.)")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    err = context.error
    if err is None:
        return
    if isinstance(err, Conflict):
        log.error("⚠️ CONFLICT: ye bot kisi aur jagah bhi chal raha hai. Baaki saare instances band karein.")
        return
    if isinstance(err, Forbidden):
        return  # group/channel mein permission nahi
    if isinstance(err, BadRequest) and _maybe_disable_colors(err):
        pass
    else:
        log.error("Unhandled error", exc_info=err)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("⚠️ Kuch gadbad ho gayi. Ek baar dobara try karein.")
    except TelegramError:
        pass


async def post_init(application: Application):
    me = await application.bot.get_me()
    application.bot_data["bot_username"] = me.username
    application.bot_data.setdefault("chat_titles", {})
    log.info("✅ Bot online: @%s (id %s)", me.username, me.id)
    log.info("ℹ️ Group mein plain text chahiye to BotFather -> /setprivacy -> Disable karein (warna /play use karein).")
    try:
        await application.bot.set_my_commands([
            BotCommand("start", "Bot start karein"),
            BotCommand("play", "Gaana play karein"),
            BotCommand("help", "Help / guide"),
        ])
    except TelegramError as exc:
        log.info("set_my_commands failed: %s", exc)


def build_app() -> Application:
    application = Application.builder().token(BOT_TOKEN).concurrent_updates(True).post_init(post_init).build()
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
    application.add_handler(CommandHandler("channels", channels_cmd))
    application.add_handler(CommandHandler("addchannel", addchannel_cmd))
    application.add_handler(CommandHandler("delchannel", delchannel_cmd))
    application.add_handler(CallbackQueryHandler(on_menu, pattern=r"^menu:"))
    application.add_handler(CallbackQueryHandler(on_admin, pattern=r"^admin:"))
    group_or_private = (
        filters.ChatType.PRIVATE | filters.ChatType.GROUP | filters.ChatType.SUPERGROUP
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & group_or_private, on_text)
    )
    application.add_error_handler(on_error)
    return application


# ======================================================================
# WEB ADMIN PANEL  (colorful + 3D logo)
# ======================================================================
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
:root{--bg1:#0b0720;--bg2:#1a0b3d;--card:rgba(255,255,255,.07);--line:rgba(255,255,255,.14);--text:#f2f0ff;--mut:#a9a4cf;
--pink:#ff4fa3;--cyan:#27e1ff;--yel:#ffd84d;--grn:#45e08f;--vio:#a678ff;--org:#ff9a52;--red:#ff5c6c}
*{box-sizing:border-box}
body{margin:0;color:var(--text);font:15px/1.5 system-ui,sans-serif;min-height:100vh;
background:radial-gradient(circle at 15% 10%,#3a1170 0,transparent 40%),radial-gradient(circle at 85% 20%,#0a4a7a 0,transparent 40%),linear-gradient(160deg,var(--bg1),var(--bg2)) fixed}
.scene{width:var(--s);height:var(--s);perspective:700px;display:inline-block;vertical-align:middle}
.cube{width:100%;height:100%;position:relative;transform-style:preserve-3d;animation:spin 9s linear infinite}
.cube span{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:calc(var(--s)*.55);
border:2px solid rgba(255,255,255,.65);box-shadow:inset 0 0 18px rgba(255,255,255,.45),0 0 18px rgba(255,79,163,.5);opacity:.94}
.cube .f1{background:linear-gradient(135deg,#ff4fa3,#7b2ff7);transform:translateZ(calc(var(--s)/2))}
.cube .f2{background:linear-gradient(135deg,#27e1ff,#3a7bff);transform:rotateY(180deg) translateZ(calc(var(--s)/2))}
.cube .f3{background:linear-gradient(135deg,#ffd84d,#ff7a3d);transform:rotateY(90deg) translateZ(calc(var(--s)/2))}
.cube .f4{background:linear-gradient(135deg,#45e08f,#10a8a0);transform:rotateY(-90deg) translateZ(calc(var(--s)/2))}
.cube .f5{background:linear-gradient(135deg,#a678ff,#ff4fa3);transform:rotateX(90deg) translateZ(calc(var(--s)/2))}
.cube .f6{background:linear-gradient(135deg,#27e1ff,#45e08f);transform:rotateX(-90deg) translateZ(calc(var(--s)/2))}
@keyframes spin{from{transform:rotateX(-22deg) rotateY(0)}to{transform:rotateX(-22deg) rotateY(360deg)}}
.brand{display:flex;align-items:center;gap:12px;margin-right:16px}
.brand b{font-size:18px;background:linear-gradient(90deg,var(--pink),var(--yel),var(--cyan));-webkit-background-clip:text;background-clip:text;color:transparent}
nav{display:flex;gap:6px;align-items:center;padding:12px 20px;background:rgba(10,6,30,.7);backdrop-filter:blur(10px);border-bottom:1px solid var(--line);flex-wrap:wrap;position:sticky;top:0;z-index:5}
nav a{color:var(--mut);text-decoration:none;padding:6px 12px;border-radius:10px;transition:.2s}
nav a:hover,nav a.on{color:#fff;background:linear-gradient(90deg,rgba(255,79,163,.35),rgba(39,225,255,.35))}nav .sp{flex:1}
main{max-width:1150px;margin:24px auto;padding:0 16px}
h1{font-size:24px;margin:0 0 16px;background:linear-gradient(90deg,var(--yel),var(--pink));-webkit-background-clip:text;background-clip:text;color:transparent}
h2{font-size:16px;margin:26px 0 10px;color:var(--cyan)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px;backdrop-filter:blur(8px)}
.grid .card{transition:transform .25s,box-shadow .25s}
.grid .card:hover{transform:translateY(-6px) rotateX(8deg);box-shadow:0 14px 30px rgba(0,0,0,.45)}
.grid .card:nth-child(1){border-top:4px solid var(--pink)}.grid .card:nth-child(2){border-top:4px solid var(--cyan)}
.grid .card:nth-child(3){border-top:4px solid var(--grn)}.grid .card:nth-child(4){border-top:4px solid var(--yel)}
.grid .card:nth-child(5){border-top:4px solid var(--org)}.grid .card:nth-child(6){border-top:4px solid var(--red)}
.grid .card:nth-child(7){border-top:4px solid var(--vio)}.grid .card:nth-child(8){border-top:4px solid var(--pink)}
.card .n{font-size:28px;font-weight:800}.card .l{color:var(--mut);font-size:13px}
.grid .card:nth-child(1) .n{color:var(--pink)}.grid .card:nth-child(2) .n{color:var(--cyan)}.grid .card:nth-child(3) .n{color:var(--grn)}
.grid .card:nth-child(4) .n{color:var(--yel)}.grid .card:nth-child(5) .n{color:var(--org)}.grid .card:nth-child(6) .n{color:var(--red)}
.grid .card:nth-child(7) .n{color:var(--vio)}.grid .card:nth-child(8) .n{color:var(--pink)}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--line);font-size:14px}
th{font-weight:700;white-space:nowrap;color:#0b0720}
tr:last-child td{border:0}tr:hover td{background:rgba(255,255,255,.06)}
th:nth-child(1){background:linear-gradient(90deg,#ff4fa3,#ff86c1)}th:nth-child(2){background:linear-gradient(90deg,#27e1ff,#7df0ff)}
th:nth-child(3){background:linear-gradient(90deg,#ffd84d,#ffe98f)}th:nth-child(4){background:linear-gradient(90deg,#45e08f,#8cf5bd)}
th:nth-child(5){background:linear-gradient(90deg,#a678ff,#c9adff)}th:nth-child(6){background:linear-gradient(90deg,#ff9a52,#ffc08f)}
th:nth-child(7){background:linear-gradient(90deg,#ff7ad0,#ffade4)}th:nth-child(8){background:linear-gradient(90deg,#7df0c9,#b4f9e1)}
td:nth-child(1){color:var(--pink);background:rgba(255,79,163,.07)}td:nth-child(2){color:var(--cyan);background:rgba(39,225,255,.06)}
td:nth-child(3){color:var(--yel);background:rgba(255,216,77,.06)}td:nth-child(4){color:var(--grn);background:rgba(69,224,143,.06)}
td:nth-child(5){color:#c4a3ff;background:rgba(166,120,255,.07)}td:nth-child(6){color:var(--org);background:rgba(255,154,82,.07)}
td:nth-child(7){color:#ff9fdc;background:rgba(255,122,208,.06)}td:nth-child(8){color:#9af5d9;background:rgba(125,240,201,.06)}
.wrap{overflow-x:auto}
input,textarea,select{width:100%;background:rgba(0,0,0,.35);border:1px solid var(--line);color:var(--text);padding:10px;border-radius:10px;font:inherit}
input:focus,textarea:focus{outline:2px solid var(--cyan)}
label{display:block;margin:14px 0 6px;color:var(--yel);font-size:13px}
button,.btn{background:linear-gradient(135deg,var(--pink),var(--vio));color:#fff;border:0;padding:9px 16px;border-radius:10px;font:inherit;cursor:pointer;text-decoration:none;display:inline-block;box-shadow:0 4px 0 rgba(0,0,0,.35);transition:.15s}
button:hover,.btn:hover{transform:translateY(-2px)}button:active{transform:translateY(2px);box-shadow:none}
button.red{background:linear-gradient(135deg,#ff5c6c,#d62b52)}button.grn{background:linear-gradient(135deg,#45e08f,#10a8a0);color:#04221a}
button.sm,.btn.sm{padding:5px 11px;font-size:13px}
.flash{background:rgba(39,225,255,.15);border:1px solid var(--cyan);padding:10px 14px;border-radius:10px;margin-bottom:14px}
.tag{font-size:12px;padding:2px 10px;border-radius:99px;background:var(--line)}.tag.red{background:#5a2030;color:#ffb3bd}.tag.grn{background:#12432f;color:#8cf0bd}
.row{display:flex;gap:10px;align-items:center}.row input{flex:1}.pg{display:flex;gap:6px;margin-top:14px;align-items:center;color:var(--mut)}
.login{max-width:360px;margin:9vh auto;text-align:center}.login .scene{margin:10px 0 24px}
.login form{text-align:left}.chk{display:flex;gap:10px;align-items:center;margin-top:14px}.chk input{width:auto}
small{color:var(--mut)}code{background:rgba(0,0,0,.4);padding:1px 6px;border-radius:6px;font-size:12px;color:var(--yel)}
.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
.cover{display:flex;gap:14px;align-items:center;margin-top:10px;flex-wrap:wrap}
.cover img{width:120px;height:68px;object-fit:cover;border-radius:10px;border:1px solid var(--line);background:#000}
</style></head><body>
{% if session.get('admin') %}
<nav><div class="brand">{{ cube(34) }}<b>Music Bot</b></div>
<a href="{{ url_for('page_dashboard') }}" class="{{ 'on' if request.endpoint=='page_dashboard' }}">📊 Dashboard</a>
<a href="{{ url_for('page_users') }}" class="{{ 'on' if request.endpoint=='page_users' }}">👥 Users</a>
<a href="{{ url_for('page_downloads') }}" class="{{ 'on' if request.endpoint=='page_downloads' }}">⬇️ Plays</a>
<a href="{{ url_for('page_songs') }}" class="{{ 'on' if request.endpoint=='page_songs' }}">💾 Songs</a>
<a href="{{ url_for('page_broadcast') }}" class="{{ 'on' if request.endpoint=='page_broadcast' }}">📣 Broadcast</a>
<a href="{{ url_for('page_settings') }}" class="{{ 'on' if request.endpoint=='page_settings' }}">⚙️ Settings</a>
<span class="sp"></span>
<form method="post" action="{{ url_for('page_logout') }}" style="margin:0"><input type="hidden" name="csrf" value="{{ csrf() }}"><button class="sm red">🚪 Logout</button></form>
</nav>{% endif %}
<main>
{% for m in get_flashed_messages() %}<div class="flash">{{ m }}</div>{% endfor %}
{% block body %}{% endblock %}
</main></body></html>""",
    "login.html": """{% extends "base.html" %}{% block title %}Login{% endblock %}
{% block body %}<div class="login card">{{ cube(96) }}<h1>🔐 Admin Login</h1>
<form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}">
<label>🔑 Password</label><input type="password" name="password" autofocus required>
<p><button style="width:100%">Login</button></p></form></div>{% endblock %}""",
    "dashboard.html": """{% extends "base.html" %}{% block title %}Dashboard{% endblock %}
{% block body %}<h1>📊 Dashboard</h1>
<div class="grid">
<div class="card"><div class="n">👥 {{ s.users }}</div><div class="l">Total users</div></div>
<div class="card"><div class="n">🆕 {{ s.new_today }}</div><div class="l">New today</div></div>
<div class="card"><div class="n">🟢 {{ s.active_today }}</div><div class="l">Active today</div></div>
<div class="card"><div class="n">⬇️ {{ s.downloads }}</div><div class="l">Total plays</div></div>
<div class="card"><div class="n">📥 {{ s.downloads_today }}</div><div class="l">Plays today</div></div>
<div class="card"><div class="n">🚫 {{ s.banned }}</div><div class="l">Banned</div></div>
<div class="card"><div class="n">💾 {{ s.cached }}</div><div class="l">Cached songs</div></div>
</div>
<div class="two">
<div><h2>🔥 Top songs</h2><div class="wrap"><table><tr><th>#</th><th>🎵 Song</th><th>⬇️ Plays</th></tr>
{% for r in top %}<tr><td>{{ loop.index }}</td><td>{{ r.title }}</td><td>{{ r.c }}</td></tr>{% else %}<tr><td colspan="3"><small>Abhi koi data nahi.</small></td></tr>{% endfor %}</table></div></div>
<div><h2>🏆 Top users</h2><div class="wrap"><table><tr><th>#</th><th>🆔 ID</th><th>👤 Name</th><th>⬇️ Plays</th></tr>
{% for u in tusers %}<tr><td>{{ loop.index }}</td><td>{{ u.user_id }}</td><td>{{ u.first_name or '' }} {% if u.username %}<small>@{{ u.username }}</small>{% endif %}</td><td>{{ u.downloads }}</td></tr>{% else %}<tr><td colspan="4"><small>Abhi koi data nahi.</small></td></tr>{% endfor %}</table></div></div>
</div>
<h2>🕒 Recent plays</h2><div class="wrap"><table><tr><th>🕒 Time</th><th>👤 User</th><th>🎵 Song</th></tr>
{% for r in recent %}<tr><td>{{ r.ts }}</td><td>{{ r.first_name or '' }} {% if r.username %}<small>@{{ r.username }}</small>{% endif %}</td><td>{{ r.title }}</td></tr>
{% else %}<tr><td colspan="3"><small>Abhi koi data nahi.</small></td></tr>{% endfor %}</table></div>
{% endblock %}""",
    "users.html": """{% extends "base.html" %}{% block title %}Users{% endblock %}
{% block body %}<h1>👥 Users <small>({{ total }})</small></h1>
<form class="row" method="get"><input name="q" value="{{ q }}" placeholder="🔎 ID, username ya naam se search"><button>Search</button></form>
<br><div class="wrap"><table><tr><th>🆔 ID</th><th>👤 Name</th><th>🔗 Username</th><th>📅 Joined</th><th>🕒 Last seen</th><th>⬇️ Plays</th><th>📌 Status</th><th>⚡ Action</th></tr>
{% for u in users %}<tr>
<td><code>{{ u.user_id }}</code></td><td>{{ u.first_name or '' }}</td><td>{% if u.username %}@{{ u.username }}{% else %}<small>-</small>{% endif %}</td>
<td>{{ u.joined_at }}</td><td>{{ u.last_seen }}</td><td>{{ u.downloads }}</td>
<td>{% if u.banned %}<span class="tag red">🚫 banned</span>{% else %}<span class="tag grn">✅ active</span>{% endif %}</td>
<td><form method="post" action="{{ url_for('page_ban', uid=u.user_id) }}" style="margin:0">
<input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="back" value="{{ request.full_path }}">
<input type="hidden" name="banned" value="{{ 0 if u.banned else 1 }}">
{% if u.banned %}<button class="sm grn">✅ Unban</button>{% else %}<button class="sm red">🚫 Ban</button>{% endif %}</form></td>
</tr>{% else %}<tr><td colspan="8"><small>Koi user nahi mila.</small></td></tr>{% endfor %}</table></div>
<div class="pg">
{% if page > 1 %}<a class="btn sm" href="?q={{ q|urlencode }}&page={{ page-1 }}">← Prev</a>{% endif %}
<span>Page {{ page }} / {{ pages }}</span>
{% if page < pages %}<a class="btn sm" href="?q={{ q|urlencode }}&page={{ page+1 }}">Next →</a>{% endif %}</div>
{% endblock %}""",
    "downloads.html": """{% extends "base.html" %}{% block title %}Plays{% endblock %}
{% block body %}<h1>⬇️ Plays <small>({{ total }})</small></h1>
<form class="row" method="get"><input name="q" value="{{ q }}" placeholder="🔎 Song, user ID ya username"><button>Search</button></form>
<br><div class="wrap"><table><tr><th>#</th><th>🕒 Time</th><th>🆔 User ID</th><th>👤 Name</th><th>🔗 Username</th><th>🎵 Song</th><th>🎬 Video ID</th></tr>
{% for r in rows %}<tr><td>{{ r.id }}</td><td>{{ r.ts }}</td><td><code>{{ r.user_id }}</code></td><td>{{ r.first_name or '' }}</td>
<td>{% if r.username %}@{{ r.username }}{% else %}<small>-</small>{% endif %}</td><td>{{ r.title }}</td><td><code>{{ r.video_id }}</code></td></tr>
{% else %}<tr><td colspan="7"><small>Koi play nahi mila.</small></td></tr>{% endfor %}</table></div>
<div class="pg">
{% if page > 1 %}<a class="btn sm" href="?q={{ q|urlencode }}&page={{ page-1 }}">← Prev</a>{% endif %}
<span>Page {{ page }} / {{ pages }}</span>
{% if page < pages %}<a class="btn sm" href="?q={{ q|urlencode }}&page={{ page+1 }}">Next →</a>{% endif %}</div>
{% endblock %}""",
    "songs.html": """{% extends "base.html" %}{% block title %}Songs{% endblock %}
{% block body %}<h1>💾 Cached Songs <small>({{ total }})</small></h1>
<form class="row" method="get"><input name="q" value="{{ q }}" placeholder="🔎 Song ya video ID"><button>Search</button></form>
<br><div class="wrap"><table><tr><th>🎬 Video ID</th><th>🎵 Title</th><th>⬇️ Plays</th><th>📁 File ID</th></tr>
{% for r in rows %}<tr><td><code>{{ r.video_id }}</code></td><td>{{ r.title }}</td><td>{{ r.dl }}</td><td><small>{{ (r.file_id or '')[:24] }}…</small></td></tr>
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
<div class="chk"><input type="checkbox" id="n" name="notify_admins" value="1" {{ 'checked' if cfg.notify_admins=='1' }}><label for="n" style="margin:0;color:var(--text)">🔔 Play alerts (jab koi gaana sune to admins ko Telegram notification)</label></div>
<label>👑 Owner username</label>
<input name="owner_username" value="{{ cfg.owner_username }}" placeholder="@thehiddenreserve">
<label>🖼 Welcome banner image URL (khali = auto 3D logo)</label>
<input name="welcome_banner" value="{{ cfg.welcome_banner }}" placeholder="https://...jpg">
<label>👋 Welcome message (HTML allowed, {name} = user ka naam)</label>
<textarea name="welcome_text" rows="10">{{ cfg.welcome_text }}</textarea>

<h2>🎨 Song cover (gaane ke neeche lagne wala logo / GIF)</h2>
<label>Cover image ya GIF ka direct URL (khali = YouTube thumbnail)</label>
<input name="song_cover" value="{{ cfg.song_cover }}" placeholder="https://...jpg  ya  https://...gif">
<div class="cover">
{% if cfg.song_cover %}<img src="{{ cfg.song_cover }}" alt="cover">{% endif %}
<small>Image 200KB se chhoti rakhein (Telegram thumbnail limit). GIF bhi chalega.</small>
</div>
<div class="chk"><input type="checkbox" id="yt" name="use_yt_thumb" value="1" {{ 'checked' if cfg.use_yt_thumb=='1' }}><label for="yt" style="margin:0;color:var(--text)">🖼 Custom cover na ho to YouTube thumbnail use karein</label></div>

<p><button>💾 Save</button></p></form></div>

<h2>🧹 Song cache</h2>
<div class="card"><form method="post" action="{{ url_for('page_cache_clear') }}">
<input type="hidden" name="csrf" value="{{ csrf() }}">
<p><small>Cover badalne ke baad cache clear karein, warna purane gaane purane cover ke saath bajenge.</small></p>
<button class="red" onclick="return confirm('Song cache clear karna hai?')">🗑 Cache clear</button></form></div>
{% endblock %}""",
}
app.jinja_loader = DictLoader(TEMPLATES)


def cube_html(size=40):
    faces = "".join(f'<span class="f{i}">🎵</span>' for i in range(1, 7))
    return Markup(f'<div class="scene" style="--s:{int(size)}px"><div class="cube">{faces}</div></div>')


app.jinja_env.globals["cube"] = cube_html


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
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("admin"):
            return redirect(url_for("page_login"))
        return fn(*a, **kw)

    return wrapper


_fails = {}


def _locked(ip) -> bool:
    count, ts = _fails.get(ip, (0, 0))
    if time.time() - ts > 600:
        _fails.pop(ip, None)
        return False
    return count >= 5


def _pager(total: int, page: int):
    pages = max(1, -(-total // PER_PAGE))
    return min(max(1, page), pages), pages


@app.route("/login", methods=["GET", "POST"])
def page_login():
    if request.method == "POST":
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
        if _locked(ip):
            flash("Bahut zyada galat attempts. 10 minute baad try karein.")
        elif ADMIN_PASSWORD and hmac.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
            _fails.pop(ip, None)
            session.clear()
            session["admin"] = True
            session["csrf"] = secrets.token_hex(16)
            return redirect(url_for("page_dashboard"))
        else:
            count, ts = _fails.get(ip, (0, time.time()))
            _fails[ip] = (count + 1, ts)
            flash("Galat password.")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def page_logout():
    session.clear()
    return redirect(url_for("page_login"))


@app.route("/")
@login_required
def page_dashboard():
    return render_template(
        "dashboard.html", s=db_stats(), top=top_songs(10), recent=recent_downloads(15), tusers=top_users(5)
    )


@app.route("/users")
@login_required
def page_users():
    q = request.args.get("q", "").strip()
    page = max(1, request.args.get("page", 1, type=int))
    rows, total = list_users(q, PER_PAGE, (page - 1) * PER_PAGE)
    page, pages = _pager(total, page)
    return render_template("users.html", users=rows, total=total, q=q, page=page, pages=pages)


@app.route("/downloads")
@login_required
def page_downloads():
    q = request.args.get("q", "").strip()
    page = max(1, request.args.get("page", 1, type=int))
    rows, total = list_downloads(q, PER_PAGE, (page - 1) * PER_PAGE)
    page, pages = _pager(total, page)
    return render_template("downloads.html", rows=rows, total=total, q=q, page=page, pages=pages)


@app.route("/songs")
@login_required
def page_songs():
    q = request.args.get("q", "").strip()
    page = max(1, request.args.get("page", 1, type=int))
    rows, total = list_files(q, PER_PAGE, (page - 1) * PER_PAGE)
    page, pages = _pager(total, page)
    return render_template("songs.html", rows=rows, total=total, q=q, page=page, pages=pages)


@app.route("/users/<int:uid>/ban", methods=["POST"])
@login_required
def page_ban(uid):
    if uid in ADMIN_IDS:
        flash("Admin ko ban nahi kar sakte.")
    else:
        banned = request.form.get("banned") == "1"
        set_ban(uid, banned)
        flash(f"User {uid} {'ban' if banned else 'unban'} ho gaya.")
    back = request.form.get("back", "")
    return redirect(back if back.startswith("/users") else url_for("page_users"))


@app.route("/cache/clear", methods=["POST"])
@login_required
def page_cache_clear():
    n = clear_file_cache()
    flash(f"🧹 {n} cached songs clear ho gaye. Agla play naye cover ke saath hoga.")
    return redirect(url_for("page_settings"))


def _run_broadcast(text: str):
    set_setting("broadcast_running", "1")
    ids = all_user_ids()
    ok = failed = 0
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
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
    finally:
        set_setting("broadcast_running", "0")
        set_setting(
            "broadcast_status",
            f"Done at {time.strftime('%Y-%m-%d %H:%M:%S')} — sent: {ok}, failed: {failed}, total: {len(ids)}",
        )


@app.route("/broadcast", methods=["GET", "POST"])
@login_required
def page_broadcast():
    if request.method == "POST":
        text = request.form.get("text", "").strip()
        if text and get_setting("broadcast_running") != "1":
            set_setting("broadcast_running", "1")
            set_setting("broadcast_status", "Running… 0")
            threading.Thread(target=_run_broadcast, args=(text,), daemon=True).start()
            flash("Broadcast shuru ho gaya. Neeche status dekhein.")
        else:
            flash("Pehla broadcast abhi chal raha hai ya message khali hai.")
        return redirect(url_for("page_broadcast"))
    return render_template("broadcast.html", count=len(all_user_ids()), status=get_setting("broadcast_status"))


@app.route("/settings", methods=["GET", "POST"])
@login_required
def page_settings():
    if request.method == "POST":
        set_setting("maintenance", "1" if request.form.get("maintenance") else "0")
        set_setting("notify_admins", "1" if request.form.get("notify_admins") else "0")
        set_setting("use_yt_thumb", "1" if request.form.get("use_yt_thumb") else "0")
        owner = request.form.get("owner_username", "").strip() or OWNER_USERNAME
        set_setting("owner_username", owner if owner.startswith("@") else "@" + owner)
        set_setting("welcome_banner", request.form.get("welcome_banner", "").strip())
        set_setting("welcome_text", request.form.get("welcome_text", "").strip() or DEFAULT_WELCOME)
        set_setting("song_cover", request.form.get("song_cover", "").strip())
        flash("Settings save ho gayi ✅ (cover badla ho to cache clear karein)")
        return redirect(url_for("page_settings"))
    keys = ("maintenance", "notify_admins", "owner_username", "welcome_banner",
            "welcome_text", "song_cover", "use_yt_thumb")
    cfg = {k: get_setting(k) for k in keys}
    return render_template("settings.html", cfg=cfg)


# ======================================================================
# MAIN
# ======================================================================
logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.WARNING)
main_log = logging.getLogger("main")


def run_admin():
    try:
        app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)
    except OSError as exc:
        main_log.error("Web panel start nahi hua (port %s busy ho sakta hai): %s", PORT, exc)


if __name__ == "__main__":
    if not BOT_TOKEN or BOT_TOKEN.startswith("PASTE_"):
        sys.exit("❌ BOT_TOKEN set nahi hai. File ke upar CONFIG mein BotFather wala token daalo.")
    if not re.fullmatch(r"\d{6,}:[A-Za-z0-9_-]{30,}", BOT_TOKEN):
        sys.exit("❌ BOT_TOKEN ka format galat hai. Token aisa hota hai: 123456789:AAxxxxxxxxxxxxxxxxxxxxxxx "
                 "(quotes ke andar, extra space nahi).")

    init()

    if ADMIN_PASSWORD:
        threading.Thread(target=run_admin, daemon=True).start()
        main_log.info("Admin panel: http://localhost:%s", PORT)
    else:
        main_log.warning("ADMIN_PASSWORD khali hai - web admin panel band rahega.")

    main_log.info("Bot start ho raha hai... (colored buttons: %s)",
                  "ON" if (COLOR_BUTTONS and STYLE_SUPPORTED) else "OFF")
    try:
        build_app().run_polling(drop_pending_updates=True, close_loop=False)
    except InvalidToken:
        sys.exit("❌ Token galat ya revoke ho chuka hai. BotFather se naya token daalo.")
    except NetworkError as exc:
        sys.exit(f"❌ Telegram se connect nahi ho paya (internet check karein): {exc}")
    except KeyboardInterrupt:
        main_log.info("Band kiya gaya.")