import asyncio
import html
import json
import logging
import os
import re
import traceback
from datetime import datetime

import requests
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Bot,
    BotCommand,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ==================== CONFIG (DEFAULTS) ====================
MAIN_TOKEN = "8238526174:AAEc1DAYIq4QsyTWFua0gBDUA7jmJhCUZP4"
DEFAULT_OWNER_ID = 5574675470
DEFAULT_OWNER_NAME = "SANJU"
DEFAULT_SUPPORT = "@thehiddenreserve"
DEFAULT_FORCE = ["@Sanjuownersmm"]

API_URL = "https://ftosint.world/api/number"
API_KEY = "lightnum2info"

DB_FILE = "data.json"
TOKEN_RE = re.compile(r"^\d{6,12}:[A-Za-z0-9_\-]{30,45}$")

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger("CloneBot")

RUNNING = {}
MAIN_APP = None

# ==================== DATABASE ====================
DB = {"main": {"users": [], "groups": []}, "clones": {}, "settings": {}}

def load_db():
    global DB
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                DB = json.load(f)
        except Exception:
            pass
    DB.setdefault("main", {"users": [], "groups": []})
    DB["main"].setdefault("users", [])
    DB["main"].setdefault("groups", [])
    DB.setdefault("clones", {})
    DB.setdefault("settings", {})
    s = DB["settings"]
    s.setdefault("owner_name", DEFAULT_OWNER_NAME)
    s.setdefault("owner_id", DEFAULT_OWNER_ID)
    s.setdefault("support", DEFAULT_SUPPORT)
    s.setdefault("force_channels", list(DEFAULT_FORCE))

def save_db():
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(DB, f, indent=2, ensure_ascii=False)

# ---------- SETTINGS ACCESS ----------
def cfg(key, default=None):
    return DB["settings"].get(key, default)

def owner_name():
    return cfg("owner_name", DEFAULT_OWNER_NAME)

def owner_id():
    return cfg("owner_id", DEFAULT_OWNER_ID)

def support():
    return cfg("support", DEFAULT_SUPPORT)

def force_channels():
    ch = DB["settings"].get("force_channels")
    if not ch:
        ch = list(DEFAULT_FORCE)
        DB["settings"]["force_channels"] = ch
    return ch

def is_owner(uid):
    return uid == owner_id()

# ==================== DATA HELPERS ====================
def bucket(context: ContextTypes.DEFAULT_TYPE):
    if context.bot_data.get("is_clone"):
        tok = context.bot.token
        c = DB["clones"].setdefault(tok, {
            "owner_id": context.bot_data.get("owner_id"),
            "owner_name": context.bot_data.get("owner_name") or "",
            "username": "",
            "users": [],
            "groups": [],
        })
        c.setdefault("users", [])
        c.setdefault("groups", [])
        return c
    return DB["main"]

def add_user(context, uid):
    try:
        b = bucket(context)
        if uid not in b["users"]:
            b["users"].append(uid)
            save_db()
    except Exception as e:
        logger.error(f"add_user: {e}")

def add_group(context, chat_id, title, ctype):
    b = bucket(context)
    for g in b["groups"]:
        if g["id"] == chat_id:
            g["title"] = title
            return False
    b["groups"].append({"id": chat_id, "title": title, "type": ctype})
    save_db()
    return True

def is_admin_of(context, uid):
    if context.bot_data.get("is_clone"):
        return uid == context.bot_data.get("owner_id")
    return uid == owner_id()

# ---------- OWNER / SUPPORT ----------
def owner_line(context):
    return f"👑 Oᴡɴᴇʀ : {owner_name()}  |  🆔 {owner_id()}"

def support_line():
    return f"💬 Sᴜᴘᴘᴏʀᴛ : {support()}"

def link_of(ch):
    ch = str(ch)
    if ch.startswith("@"):
        return "https://t.me/" + ch[1:]
    return "https://t.me/" + ch

# ==================== API ====================
def fetch_number(number):
    try:
        r = requests.get(API_URL, params={"key": API_KEY, "num": number}, timeout=25)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception as e:
        logger.error(f"API error: {e}")
        return None

def format_result(query, records, truecaller=None):
    total = len(records)
    sep = "━━━━━━━━━━━━━━━━━━"
    out = ["📞 𝗡𝗨𝗠𝗕𝗘𝗥 𝗜𝗡𝗙𝗢", "", "Nᴜᴍʙᴇʀ Dᴀᴛᴀʙᴀꜱᴇ ✅", "",
           f"🔭 Qᴜᴇʀʏ : {query}", f"✍️ Rᴇᴄᴏʀᴅꜱ : {total} | Page 1/1"]
    if truecaller:
        out.append(f"☎️ Tʀᴜᴇᴄᴀʟʟᴇʀ : {truecaller}")
    for i, rec in enumerate(records, 1):
        email = rec.get("email", "N/A")
        if str(email).strip() in ("", "N/A", "None", "null"):
            email = "Nᴏᴛ Aᴠᴀɪʟᴀʙʟᴇ ❌"
        out += ["", sep, f"📰 Rᴇᴄᴏʀᴅ {i}/{total}", sep, "",
                f"📲 Nᴜᴍʙᴇʀ : {rec.get('mobile', 'N/A')}",
                f"👤 Nᴀᴍᴇ : {rec.get('name', 'N/A')}",
                f"👥 Fᴀᴛʜᴇʀ : {rec.get('fname', 'N/A')}",
                f"📞 Aʟᴛ Nᴜᴍ : {rec.get('alt', 'N/A')}",
                f"🔎 Cɪʀᴄʟᴇ : {rec.get('circle', 'N/A')}",
                f"🏡 Aᴅᴅʀᴇꜱꜱ : {rec.get('address', 'N/A')}",
                f"📧 Eᴍᴀɪʟ : {email}",
                f"💳 Iᴅ : {rec.get('id', 'N/A')}"]
    out += ["", "⚠️ DISCLAIMER", "  🎓 Educational use only",
            "  🚫 Misuse is illegal", "  📜 User is responsible", "",
            f"💬 Sᴜᴘᴘᴏʀᴛ : {support()}"]
    return "\n".join(out)

# ==================== FORCE JOIN ====================
async def check_join(context, uid):
    for ch in force_channels():
        try:
            m = await context.bot.get_chat_member(ch, uid)
            if m.status not in ("member", "administrator", "creator"):
                return False
        except Exception:
            continue
    return True

def join_kb():
    rows = []
    for ch in force_channels():
        rows.append([InlineKeyboardButton(f"📢 ᴊᴏɪɴ {ch}", url=link_of(ch))])
    rows.append([InlineKeyboardButton("✅ ᴊᴏɪɴᴇᴅ ✓ ᴄʜᴇᴄᴋ", callback_data="check_join")])
    return InlineKeyboardMarkup(rows)

def force_text():
    chans = "\n".join([f"  📢 <b>{c}</b>" for c in force_channels()])
    return (
        "🔐 <b>Fᴏʀᴄᴇ Jᴏɪɴ Rᴇǫᴜɪʀᴇᴅ</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "  🙏 Bᴏᴛ ᴜsᴇ ᴋᴀʀɴᴇ sᴇ ᴘᴇʜʟᴇ ᴊᴏɪɴ ᴋᴀʀᴇ\n\n"
        f"{chans}\n\n"
        "  ➤ ᴊᴏɪɴ ᴋᴀʀᴋᴇ <b>✅ ᴊᴏɪɴᴇᴅ</b> ᴅᴀʙᴀʏᴇ 👇"
    )

async def guard(update, context):
    user = update.effective_user
    if user is None:
        return True
    if await check_join(context, user.id):
        return True
    try:
        if update.callback_query and update.callback_query.message:
            await update.callback_query.message.reply_text(
                force_text(), parse_mode=ParseMode.HTML, reply_markup=join_kb())
        elif update.effective_message:
            await update.effective_message.reply_text(
                force_text(), parse_mode=ParseMode.HTML, reply_markup=join_kb())
    except Exception as e:
        logger.error(f"guard send: {e}")
    return False

# ==================== TEXTS ====================
def welcome_text(context, name="Dᴏꜱᴛ"):
    return (
        "╔══════════════════════════════╗\n"
        "   ✨ 𝗡 𝗨 𝗠 𝗕 𝗘 𝗥  ✦  𝗟 𝗢 𝗢 𝗞 𝗨 𝗣  ✦  𝗕 𝗢 𝗧 ✨\n"
        "╚══════════════════════════════╝\n"
        "\n"
        f"╭───── 🎉 <b>Hᴇʟʟᴏ {name}</b> 🎉 ─────╮\n"
        "   🌸 Sᴡᴀɢᴀᴛ ʜᴀɪ ᴀᴀᴘᴋᴀ ʙʜᴀɪ! 💐\n"
        "╰──────────────────────────────╯\n"
        "\n"
        "  📱 Kɪsɪ ʙʜɪ ᴍᴏʙɪʟᴇ ɴᴜᴍʙᴇʀ ᴋɪ\n"
        "  🔥 <b>ᴘᴜʀɪ ᴅᴇᴛᴀɪʟs</b> ᴊᴜsᴛ ᴇᴋ ᴄʟɪᴄᴋ ᴍᴇ!\n"
        "\n"
        "┏━━━━━━━━━━━━━━━━━━━━━━┓\n"
        "┃   ✅  <b>Kʏᴀ Kʏᴀ Mɪʟᴇɢᴀ?</b>\n"
        "┗━━━━━━━━━━━━━━━━━━━━━━┛\n"
        "  ➤ 👤 Nᴀᴍᴇ & Fᴀᴛʜᴇʀ Nᴀᴍᴇ\n"
        "  ➤ 📞 Aʟᴛᴇʀɴᴀᴛᴇ Nᴜᴍʙᴇʀ\n"
        "  ➤ 🔎 Cɪʀᴄʟᴇ / Oᴘᴇʀᴀᴛᴏʀ\n"
        "  ➤ 🏡 Pᴜʀᴀ Aᴅᴅʀᴇꜱꜱ\n"
        "  ➤ 📧 Gᴍᴀɪʟ / Eᴍᴀɪʟ\n"
        "  ➤ 💳 Iᴅ Nᴜᴍʙᴇʀ\n"
        "\n"
        "┏━━━━━━━━━━━━━━━━━━━━━━┓\n"
        "┃   📌  <b>Kᴀɪsᴇ Usᴇ Kᴀʀᴇ?</b>\n"
        "┗━━━━━━━━━━━━━━━━━━━━━━┛\n"
        "  1️⃣ ɴᴇᴇᴄʜᴇ <b>🔎 ʟᴏᴏᴋᴜᴘ ʙᴜᴛᴛᴏɴ</b> ᴅᴀʙᴀʏᴇ\n"
        "  2️⃣ ʏᴀ sɪᴅʜᴀ <b>10 ᴅɪɢɪᴛ ɴᴜᴍʙᴇʀ</b> sᴇɴᴅ ᴋᴀʀᴇ\n"
        "\n"
        "  🚀 <i>Aᴘɴᴀ ᴋʜᴜᴅ ᴋᴀ ʙᴏᴛ ʙᴀɴᴀɴᴇ ᴋᴇ ʟɪʏᴇ</i>\n"
        "  <i>/clone ᴅᴀʙᴀʏᴇ ᴀᴜʀ ᴀᴘɴᴀ ᴛᴏᴋᴇɴ ʙʜᴇᴊᴇ ✨</i>\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  {owner_line(context)}\n"
        f"  {support_line()}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"     ✦ ᴍᴀᴅᴇ ᴡɪᴛʜ ❤️ ʙʏ {owner_name()} ✦"
    )

def help_text(context):
    return (
        "╔══════════════════════════════╗\n"
        "        📖 𝗛 𝗘 𝗟 𝗣  ✦  𝗠 𝗘 𝗡 𝗨\n"
        "╚══════════════════════════════╝\n"
        "\n"
        "┏━━━━━━━━━━━━━━━━━━━━━━┓\n"
        "┃   🚀  <b>Cᴏᴍᴍᴀɴᴅꜱ</b>\n"
        "┗━━━━━━━━━━━━━━━━━━━━━━┛\n"
        "  ➤ /start    → ᴡᴇʟᴄᴏᴍᴇ ᴍᴇɴᴜ\n"
        "  ➤ /lookup   → ɴᴜᴍʙᴇʀ ᴘᴜᴄʜᴇ\n"
        "  ➤ /clone    → ᴀᴘɴᴀ ʙᴏᴛ ʙᴀɴᴀᴇ\n"
        "  ➤ /settings → sᴇᴛᴛɪɴɢꜱ (ᴏᴡɴᴇʀ)\n"
        "  ➤ /help     → ʏᴇ ᴍᴇɴᴜ\n"
        "\n"
        "┏━━━━━━━━━━━━━━━━━━━━━━┓\n"
        "┃   🔎  <b>Lᴏᴏᴋᴜᴘ</b>\n"
        "┗━━━━━━━━━━━━━━━━━━━━━━┛\n"
        "  ➤ sɪᴅʜᴀ <b>10 ᴅɪɢɪᴛ</b> ɴᴜᴍʙᴇʀ sᴇɴᴅ ᴋᴀʀᴇ\n"
        "\n"
        "  🔐 <b>Nᴏᴛᴇ :</b> Bᴏᴛ ᴜsᴇ ᴋᴀʀɴᴇ ᴋᴇ ʟɪʏᴇ ᴄʜᴀɴɴᴇʟ\n"
        f"  {', '.join(force_channels())} ᴊᴏɪɴ ᴋᴀʀɴᴀ ʜᴏɢᴀ\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  {support_line()}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

def clone_info_text(context):
    return (
        "╔══════════════════════════════╗\n"
        "      🚀 𝗖 𝗟 𝗢 𝗡 𝗘  ✦  𝗕 𝗢 𝗧\n"
        "╚══════════════════════════════╝\n"
        "\n"
        "  ✨ Aᴘɴᴀ ᴋʜᴜᴅ ᴋᴀ ʟᴏᴏᴋᴜᴘ ʙᴏᴛ ʙᴀɴᴀᴇ!\n"
        "\n"
        "┏━━━━━━━━━━━━━━━━━━━━━━┓\n"
        "┃   📌  <b>Sᴛᴇᴘs</b>\n"
        "┗━━━━━━━━━━━━━━━━━━━━━━┛\n"
        "  1️⃣ @BotFather ᴘᴇ /newbot sᴇ ɴᴀʏᴀ ʙᴏᴛ ʙᴀɴᴀᴇ\n"
        "  2️⃣ ᴜsᴋᴀ <b>ᴛᴏᴋᴇɴ</b> ᴄᴏᴘʏ ᴋᴀʀᴇ\n"
        "  3️⃣ ʏᴀʜᴀ ᴘᴀsᴛᴇ ᴋᴀʀᴋᴇ sᴇɴᴅ ᴋᴀʀᴇ\n"
        "\n"
        "  ⚡ Bᴀᴀs ᴛᴏᴋᴇɴ ᴅᴀʟᴛᴇ ʜɪ ᴀᴀᴘᴋᴀ ʙᴏᴛ ᴄʜᴀʟ ᴊᴀʏᴇɢᴀ 🎉\n"
        "  🎁 ʙɪʟᴋᴜʟ ꜰʀᴇᴇ — ᴋᴜᴄʜ ɴᴀʜɪ ʟᴀɢᴇɢᴀ!\n"
        "\n"
        "  🔐 <b>Nᴏᴛᴇ :</b> ᴀᴀᴘᴋᴇ ᴄʟᴏɴᴇ ʙᴏᴛ ᴋᴇ sᴀᴀʀᴇ ᴜsᴇʀs\n"
        f"  ᴋᴏ {', '.join(force_channels())} ᴊᴏɪɴ ᴋᴀʀɴᴀ ʜᴏɢᴀ\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  {owner_line(context)}\n"
        f"  {support_line()}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "  👇 <b>Aᴘɴᴀ ʙᴏᴛ ᴛᴏᴋᴇɴ ʙʜᴇᴊᴇ</b>"
    )

def settings_text():
    chans = "\n".join([f"   • {c}" for c in force_channels()]) or "   ɴᴏɴᴇ"
    return (
        "╔══════════════════════════════╗\n"
        "       ⚙️ 𝗦 𝗘 𝗧 𝗧 𝗜 𝗡 𝗚 𝗦\n"
        "╚══════════════════════════════╝\n"
        "\n"
        f"👑 Oᴡɴᴇʀ Nᴀᴍᴇ : <b>{owner_name()}</b>\n"
        f"🆔 Oᴡɴᴇʀ ID : <code>{owner_id()}</code>\n"
        f"💬 Sᴜᴘᴘᴏʀᴛ : <b>{support()}</b>\n"
        f"📢 Fᴏʀᴄᴇ Cʜᴀɴɴᴇʟꜱ :\n{chans}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "  👇 ᴄʜᴀɴɢᴇ ᴋᴀʀɴᴇ ᴋᴇ ʟɪʏᴇ ɴᴇᴇᴄʜᴇ ᴅᴀʙᴀʏᴇ"
    )

# ==================== KEYBOARDS ====================
def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 ʟ ᴏ ᴏ ᴋ ᴜ ᴘ  ɴ ᴜ ᴍ ʙ ᴇ ʀ", callback_data="lookup")],
        [
            InlineKeyboardButton("📖 ʜᴇʟᴘ", callback_data="help"),
            InlineKeyboardButton("👤 ᴏᴡɴᴇʀ", callback_data="owner"),
        ],
        [InlineKeyboardButton("🚀 ᴄʟᴏɴᴇ ᴍʏ ᴏᴡɴ ʙᴏᴛ", callback_data="clone")],
        [InlineKeyboardButton("⚙️ ꜱᴇᴛᴛɪɴɢꜱ", callback_data="set_open")],
        [InlineKeyboardButton("📢 ᴜᴘᴅᴀᴛᴇꜱ ᴄʜᴀɴɴᴇʟ", url=link_of(force_channels()[0]))],
    ])

def result_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 ɴᴇᴡ ʟᴏᴏᴋᴜᴘ", callback_data="lookup")],
        [
            InlineKeyboardButton("👤 ᴏᴡɴᴇʀ", callback_data="owner"),
            InlineKeyboardButton("📖 ʜᴇʟᴘ", callback_data="help"),
        ],
    ])

def admin_kb(context):
    if context.bot_data.get("is_clone"):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 ꜱᴛᴀᴛꜱ", callback_data="adm_stats")],
            [InlineKeyboardButton("📢 ʙʀᴏᴀᴅᴄᴀꜱᴛ", callback_data="adm_broadcast")],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 ꜱᴛᴀᴛꜱ", callback_data="adm_stats")],
        [InlineKeyboardButton("📋 ᴄʟᴏɴᴇ ʟɪꜱᴛ", callback_data="adm_clones")],
        [InlineKeyboardButton("📢 ᴍᴀɪɴ ʙʀᴏᴀᴅᴄᴀꜱᴛ", callback_data="adm_broadcast")],
        [InlineKeyboardButton("🚀 ᴘʀᴏᴍᴏᴛᴇ (ᴀʟʟ ᴄʟᴏɴᴇꜱ)", callback_data="adm_promote")],
        [InlineKeyboardButton("⚙️ ꜱᴇᴛᴛɪɴɢꜱ", callback_data="set_open")],
    ])

def settings_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ ᴏᴡɴᴇʀ ɴᴀᴍᴇ", callback_data="set_owner_name"),
         InlineKeyboardButton("🆔 ᴏᴡɴᴇʀ ɪᴅ", callback_data="set_owner_id")],
        [InlineKeyboardButton("💬 ꜱᴜᴘᴘᴏʀᴛ", callback_data="set_support")],
        [InlineKeyboardButton("➕ ᴀᴅᴅ ᴄʜᴀɴɴᴇʟ/ɢʀᴏᴜᴘ", callback_data="set_add_chan")],
        [InlineKeyboardButton("➖ ʀᴇᴍᴏᴠᴇ ᴄʜᴀɴɴᴇʟ/ɢʀᴏᴜᴘ", callback_data="set_rm_list")],
        [InlineKeyboardButton("📋 ʟɪꜱᴛ ᴄʜᴀɴɴᴇʟꜱ", callback_data="set_list_chan")],
        [InlineKeyboardButton("🔙 ᴄʟᴏꜱᴇ", callback_data="set_close")],
    ])

def rm_kb():
    rows = []
    for i, ch in enumerate(force_channels()):
        rows.append([InlineKeyboardButton(f"❌ {ch}", callback_data=f"rmch|{i}")])
    rows.append([InlineKeyboardButton("🔙 ʙᴀᴄᴋ", callback_data="set_open")])
    return InlineKeyboardMarkup(rows)

def admin_text(context):
    return (
        "╔══════════════════════════════╗\n"
        "       🛠 𝗔 𝗗 𝗠 𝗜 𝗡  ✦  𝗣 𝗔 𝗡 𝗘 𝗟\n"
        "╚══════════════════════════════╝\n"
        "\n"
        "  ⚡ ᴘᴜʀᴀ ᴄᴏɴᴛʀᴏʟ ᴀᴀᴘᴋᴇ ʜᴀᴀᴛʜ ᴍᴇ 👇\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  {owner_line(context)}"
    )

# ==================== LOOKUP ====================
async def do_lookup(update, context, number):
    msg = await update.effective_message.reply_text("🔎 <b>Sᴇᴀʀᴄʜɪɴɢ...</b>", parse_mode=ParseMode.HTML)
    data = fetch_number(number)
    if data is None or not data.get("success"):
        await msg.edit_text("❌ <b>API ᴇʀʀᴏʀ!</b> ᴛʜᴏᴅɪ ᴅᴇʀ ʙᴀᴀᴅ ᴛʀʏ ᴋᴀʀᴇ.", parse_mode=ParseMode.HTML)
        return
    records = data.get("results", [])
    if not records:
        await msg.edit_text(
            "📞 𝗡𝗨𝗠𝗕𝗘𝗥 𝗜𝗡𝗙𝗢\n\n"
            f"🔭 Qᴜᴇʀʏ : {number}\n\n❌ Kᴏɪ ʀᴇᴄᴏʀᴅ ɴᴀʜɪ ᴍɪʟᴀ.\n\n"
            f"💬 Sᴜᴘᴘᴏʀᴛ : {support()}",
            reply_markup=result_kb())
        return
    result = format_result(number, records, data.get("truecaller_name"))
    await msg.edit_text(f"<code>{html.escape(result)}</code>",
                        parse_mode=ParseMode.HTML, reply_markup=result_kb())

# ==================== SETTINGS APPLY ====================
async def apply_setting(update, context, key):
    text = (update.message.text or "").strip()

    if key == "owner_name":
        DB["settings"]["owner_name"] = text
    elif key == "owner_id":
        if not text.lstrip("-").isdigit():
            context.user_data["setting"] = key
            await update.message.reply_text("❌ ꜱɪʀꜰ ɴᴜᴍʙᴇʀ ᴅᴀʟᴇ (ID). ᴅᴏʙᴀʀᴀ ʙʜᴇᴊᴇ:")
            return
        DB["settings"]["owner_id"] = int(text)
    elif key == "support":
        DB["settings"]["support"] = text if text.startswith("@") else "@" + text
    elif key == "add_chan":
        ch = None
        if getattr(update.message, "forward_from_chat", None):
            c = update.message.forward_from_chat
            ch = f"@{c.username}" if c.username else str(c.id)
        else:
            ch = text
        if ch and ch not in force_channels():
            DB["settings"]["force_channels"].append(ch)
        else:
            await update.message.reply_text("ℹ️ ᴘᴇʜʟᴇ sᴇ ᴀᴅᴅ ʜᴀɪ.")
    save_db()
    await update.message.reply_text("✅ <b>ꜱᴀᴠᴇ ʜᴏ ɢᴀʏᴀ!</b>\n\n" + settings_text(),
                                    parse_mode=ParseMode.HTML, reply_markup=settings_kb())

# ==================== CLONE ====================
async def do_clone(update, context, token):
    if not await check_join(context, update.effective_user.id):
        await update.message.reply_text(force_text(), parse_mode=ParseMode.HTML, reply_markup=join_kb())
        return

    msg = await update.message.reply_text("🔎 <b>Tᴏᴋᴇɴ ᴠᴇʀɪꜰʏ ʜᴏ ʀᴀʜᴀ ʜᴀɪ...</b>", parse_mode=ParseMode.HTML)

    if token in RUNNING:
        await msg.edit_text("ℹ️ Yᴇ ʙᴏᴛ ᴘᴇʜʟᴇ sᴇ ʀᴜɴ ʜᴏ ʀᴀʜᴀ ʜᴀɪ ✅")
        return

    try:
        tmp = Bot(token)
        me = await tmp.get_me()
        await tmp.shutdown()
    except Exception:
        await msg.edit_text("❌ <b>Iɴᴠᴀʟɪᴅ ᴛᴏᴋᴇɴ!</b> ᴅᴏʙᴀʀᴀ ᴄʜᴇᴄᴋ ᴋᴀʀᴇ.", parse_mode=ParseMode.HTML)
        return

    owner = update.effective_user
    try:
        app = build_app(token, is_clone=True, clone_owner=owner.id, clone_owner_name=owner.first_name)
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
        RUNNING[token] = app
    except Exception as e:
        logger.error(f"clone launch fail: {e}\n{traceback.format_exc()}")
        await msg.edit_text("❌ Bᴏᴛ sᴛᴀʀᴛ ɴᴀʜɪ ʜᴏ ᴘᴀʏᴀ. ᴛʜᴏᴅɪ ᴅᴇʀ ʙᴀᴀᴅ ᴛʀʏ ᴋᴀʀᴇ.")
        return

    DB["clones"][token] = {
        "owner_id": owner.id,
        "owner_name": owner.first_name or "",
        "username": me.username or "",
        "users": DB["clones"].get(token, {}).get("users", []),
        "groups": DB["clones"].get(token, {}).get("groups", []),
        "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    save_db()

    try:
        if MAIN_APP:
            await MAIN_APP.bot.send_message(
                owner_id(),
                "🚀 <b>ɴᴇᴡ ᴄʟᴏɴᴇ ᴄʀᴇᴀᴛᴇᴅ!</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"🤖 Bᴏᴛ : @{me.username}\n"
                f"🆔 Bᴏᴛ ID : <code>{me.id}</code>\n"
                f"👤 Oᴡɴᴇʀ : {owner.first_name}\n"
                f"🆔 Oᴡɴᴇʀ ID : <code>{owner.id}</code>\n"
                f"👤 Usᴇʀɴᴀᴍᴇ : @{owner.username or 'N/A'}\n"
                f"📅 Tɪᴍᴇ : {datetime.now().strftime('%d-%m-%Y %H:%M')}\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "📢 ᴘʀᴏᴍᴏᴛᴇ ᴋᴀʀɴᴇ ᴋᴇ ʟɪʏᴇ /admin ᴅᴀʙᴀʏᴇ",
                parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"notify fail: {e}")

    await msg.edit_text(
        "🎉 <b>Bᴏᴛ sᴜᴄᴄᴇssꜰᴜʟʟʏ ᴄʟᴏɴᴇ ʜᴏ ɢᴀʏᴀ!</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🤖 Aᴀᴘᴋᴀ ʙᴏᴛ : @{me.username}\n"
        "✅ ᴀʙ ᴊᴀᴀᴋᴇ ᴜs ʙᴏᴛ ᴍᴇ /start ᴋᴀʀᴇ\n\n"
        f"💬 Sᴜᴘᴘᴏʀᴛ : {support()}",
        parse_mode=ParseMode.HTML)

# ==================== HANDLERS ====================
async def start(update, context):
    add_user(context, update.effective_user.id)
    if not await guard(update, context):
        return
    name = html.escape(update.effective_user.first_name or "Dᴏꜱᴛ")
    await update.message.reply_text(welcome_text(context, name),
                                    parse_mode=ParseMode.HTML, reply_markup=main_kb())

async def help_cmd(update, context):
    if not await guard(update, context):
        return
    await update.message.reply_text(help_text(context), parse_mode=ParseMode.HTML, reply_markup=main_kb())

async def lookup_cmd(update, context):
    if not await guard(update, context):
        return
    context.user_data["awaiting"] = True
    await update.message.reply_text("🔎 <b>Nᴜᴍʙᴇʀ Lᴏᴏᴋᴜᴘ</b>\n\n📲 Aʙ 10 ᴅɪɢɪᴛ ɴᴜᴍʙᴇʀ ʙʜᴇᴊᴇ 👇",
                                    parse_mode=ParseMode.HTML)

async def clone_cmd(update, context):
    if not await guard(update, context):
        return
    context.user_data["awaiting_clone"] = True
    await update.message.reply_text(clone_info_text(context), parse_mode=ParseMode.HTML)

async def settings_cmd(update, context):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("⛔ ꜱɪʀꜰ ᴏᴡɴᴇʀ ᴋᴇ ʟɪʏᴇ.", parse_mode=ParseMode.HTML)
        return
    await update.message.reply_text(settings_text(), parse_mode=ParseMode.HTML, reply_markup=settings_kb())

async def handle_text(update, context):
    text = update.message.text.strip()

    # ---------- SETTING INPUT ----------
    if context.user_data.get("setting"):
        if text.lower() in ("/cancel", "cancel"):
            context.user_data.pop("setting", None)
            await update.message.reply_text("❌ ᴄᴀɴᴄᴇʟ.", reply_markup=settings_kb())
            return
        key = context.user_data.pop("setting")
        await apply_setting(update, context, key)
        return

    if context.user_data.get("broadcast") and is_admin_of(context, update.effective_user.id):
        context.user_data["broadcast"] = False
        await do_broadcast(update, context, text)
        return
    if context.user_data.get("promote") and is_admin_of(context, update.effective_user.id):
        context.user_data["promote"] = False
        n = await do_promote(context, text)
        await update.message.reply_text(f"🚀 <b>Pʀᴏᴍᴏᴛᴇ ᴅᴏɴᴇ</b> → {n} ᴜsᴇʀs", parse_mode=ParseMode.HTML)
        return

    if TOKEN_RE.match(text):
        context.user_data["awaiting_clone"] = False
        await do_clone(update, context, text)
        return

    if not await guard(update, context):
        return

    digits = re.sub(r"\D", "", text)
    if len(digits) >= 10:
        add_user(context, update.effective_user.id)
        await do_lookup(update, context, digits[-10:])
    elif context.user_data.get("awaiting"):
        await update.message.reply_text("⚠️ Sᴀʜɪ <b>10 ᴅɪɢɪᴛ ɴᴜᴍʙᴇʀ</b> ʙʜᴇᴊᴇ ʙʜᴀɪ.", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text("🤔 Sᴀᴍᴀᴊʜ ɴᴀʜɪ ᴀᴀʏᴀ.\n\n📲 10 ᴅɪɢɪᴛ ɴᴜᴍʙᴇʀ ʙʜᴇᴊᴇ ᴏʀ /help ᴅᴀʙᴀʏᴇ.",
                                        parse_mode=ParseMode.HTML)

# ---------- CALLBACK ----------
async def button(update, context):
    q = update.callback_query
    try:
        await q.answer()
    except Exception as e:
        logger.warning(f"q.answer: {e}")

    try:
        data = q.data or ""

        # ---------- SETTINGS ----------
        if data.startswith("set_") or data.startswith("rmch|"):
            if not is_owner(q.from_user.id):
                await q.answer("⛔ ꜱɪʀꜿ ᴏᴡɴᴇʀ ᴋᴇ ʟɪʏᴇ!", show_alert=True)
                return
            await handle_settings(context, q, data)
            return

        if data == "check_join":
            if await check_join(context, q.from_user.id):
                add_user(context, q.from_user.id)
                txt = welcome_text(context, html.escape(q.from_user.first_name or "Dᴏꜱᴛ"))
                try:
                    await q.message.edit_text(txt, parse_mode=ParseMode.HTML, reply_markup=main_kb())
                except Exception:
                    await q.message.reply_text(txt, parse_mode=ParseMode.HTML, reply_markup=main_kb())
            else:
                await q.answer("❌ ᴘᴇʜʟᴇ ᴄʜᴀɴɴᴇʟ ᴊᴏɪɴ ᴋᴀʀᴇ!", show_alert=True)
            return

        if not data.startswith("adm_"):
            if not await guard(update, context):
                return

        if data == "lookup":
            context.user_data["awaiting"] = True
            await q.message.reply_text("🔎 <b>Nᴜᴍʙᴇʀ Lᴏᴏᴋᴜᴘ</b>\n\n📲 Aʙ 10 ᴅɪɢɪᴛ ɴᴜᴍʙᴇʀ ʙʜᴇᴊᴇ 👇",
                                        parse_mode=ParseMode.HTML)
        elif data == "help":
            await q.message.reply_text(help_text(context), parse_mode=ParseMode.HTML, reply_markup=main_kb())
        elif data == "clone":
            context.user_data["awaiting_clone"] = True
            await q.message.reply_text(clone_info_text(context), parse_mode=ParseMode.HTML)
        elif data == "owner":
            await q.message.reply_text(
                "╭──── 👑 <b>Oᴡɴᴇʀ</b> 👑 ────╮\n"
                f"   {owner_name()}\n"
                f"   🆔 <code>{owner_id()}</code>\n"
                f"   💬 Sᴜᴘᴘᴏʀᴛ : {support()}\n"
                "╰────────────────────╯", parse_mode=ParseMode.HTML)

        # -------- ADMIN --------
        elif data == "adm_stats":
            if not is_admin_of(context, q.from_user.id):
                return
            b = bucket(context)
            txt = ("📊 <b>Sᴛᴀᴛꜱ</b>\n━━━━━━━━━━━━━━━━━━\n"
                   f"👥 Usᴇʀs : {len(b['users'])}\n💬 Cʜᴀᴛs : {len(b['groups'])}\n")
            if not context.bot_data.get("is_clone"):
                txt += f"🚀 Tᴏᴛᴀʟ Cʟᴏɴᴇs : {len(DB['clones'])}\n✅ Rᴜɴɴɪɴɢ : {len(RUNNING)}"
            await q.message.reply_text(txt, parse_mode=ParseMode.HTML)

        elif data == "adm_clones":
            if not is_admin_of(context, q.from_user.id):
                return
            if not DB["clones"]:
                await q.message.reply_text("📭 Kᴏɪ ᴄʟᴏɴᴇ ɴᴀʜɪ ʜᴀɪ.")
                return
            txt = "📋 <b>Cʟᴏɴᴇ Lɪꜱᴛ</b>\n━━━━━━━━━━━━━━━━━━"
            for i, (tok, c) in enumerate(DB["clones"].items(), 1):
                st = "✅" if tok in RUNNING else "⛔"
                txt += (f"\n\n{i}. {st} @{c.get('username') or 'N/A'}\n"
                        f"   👤 {c.get('owner_name')} (<code>{c.get('owner_id')}</code>)\n"
                        f"   👥 {len(c.get('users', []))} users")
            await q.message.reply_text(txt, parse_mode=ParseMode.HTML)

        elif data == "adm_broadcast":
            if not is_admin_of(context, q.from_user.id):
                return
            context.user_data["broadcast"] = True
            await q.message.reply_text("📢 Jᴏ ᴍᴇꜱꜱᴀɢᴇ ʙʜᴇᴊɴᴀ ʜᴀɪ ᴠᴏ ʙʜᴇᴊᴇ.")

        elif data == "adm_promote":
            if not is_admin_of(context, q.from_user.id):
                return
            context.user_data["promote"] = True
            await q.message.reply_text("🚀 Pʀᴏᴍᴏᴛɪᴏɴ ᴍᴇꜱꜱᴀɢᴇ ʙʜᴇᴊᴇ — sᴀʙ ᴄʟᴏɴᴇ ʙᴏᴛs ᴋᴇ ᴜsᴇʀs ᴋᴏ ᴊᴀʏᴇɢᴀ.")

    except Exception as e:
        logger.error(f"button error: {e}\n{traceback.format_exc()}")
        try:
            await q.message.reply_text("⚠️ ᴋᴜᴄʜ ɢᴀʟᴀᴛ ʜᴜᴀ, ᴅᴏʙᴀʀᴀ ᴛʀʏ ᴋᴀʀᴇ.")
        except Exception:
            pass

async def handle_settings(context, q, data):
    if data == "set_open":
        await q.message.reply_text(settings_text(), parse_mode=ParseMode.HTML, reply_markup=settings_kb())
    elif data == "set_owner_name":
        context.user_data["setting"] = "owner_name"
        await q.message.reply_text("✏️ ɴᴀʏᴀ <b>Oᴡɴᴇʀ Nᴀᴍᴇ</b> ʙʜᴇᴊᴇ:", parse_mode=ParseMode.HTML)
    elif data == "set_owner_id":
        context.user_data["setting"] = "owner_id"
        await q.message.reply_text("🆔 ɴᴀʏɪ <b>Oᴡɴᴇʀ ID</b> ʙʜᴇᴊᴇ (ɴᴜᴍʙᴇʀ):", parse_mode=ParseMode.HTML)
    elif data == "set_support":
        context.user_data["setting"] = "support"
        await q.message.reply_text("💬 ɴᴀʏᴀ <b>Sᴜᴘᴘᴏʀᴛ</b> ᴜsᴇʀɴᴀᴍᴇ ʙʜᴇᴊᴇ (@xxxx):", parse_mode=ParseMode.HTML)
    elif data == "set_add_chan":
        context.user_data["setting"] = "add_chan"
        await q.message.reply_text(
            "➕ <b>Cʜᴀɴɴᴇʟ/Gʀᴏᴜᴘ ᴀᴅᴅ ᴋᴀʀᴇ</b>\n\n"
            "  ➤ @ᴜsᴇʀɴᴀᴍᴇ ʙʜᴇᴊᴇ, ʏᴀ\n"
            "  ➤ ᴄʜᴀɴɴᴇʟ ᴋᴀ ᴋᴏɪ ᴍᴇꜱꜱᴀɢᴇ <b>ꜰᴏʀᴡᴀʀᴅ</b> ᴋᴀʀᴇ",
            parse_mode=ParseMode.HTML)
    elif data == "set_rm_list":
        if not force_channels():
            await q.message.reply_text("📭 ᴋᴏɪ ᴄʜᴀɴɴᴇʟ ɴᴀʜɪ.")
            return
        await q.message.reply_text("➖ ᴋɪꜱᴇ ʀᴇᴍᴏᴠᴇ ᴋᴀʀɴᴀ ʜᴀɪ?", reply_markup=rm_kb())
    elif data == "set_list_chan":
        chans = "\n".join([f"  {i+1}. {c}" for i, c in enumerate(force_channels())]) or "  ɴᴏɴᴇ"
        await q.message.reply_text(f"📋 <b>Fᴏʀᴄᴇ Cʜᴀɴɴᴇʟꜱ</b>\n━━━━━━━━━━━━━━━━━━\n{chans}",
                                   parse_mode=ParseMode.HTML)
    elif data == "set_close":
        try:
            await q.message.delete()
        except Exception:
            pass
    elif data.startswith("rmch|"):
        i = int(data.split("|")[1])
        chs = force_channels()
        if 0 <= i < len(chs):
            removed = chs.pop(i)
            save_db()
            await q.message.edit_text(f"✅ ʀᴇᴍᴏᴠᴇ: {removed}", reply_markup=settings_kb())

async def admin(update, context):
    if not is_admin_of(context, update.effective_user.id):
        await update.message.reply_text("⛔ <b>Aᴀᴘ ᴀᴅᴍɪɴ ɴᴀʜɪ ʜᴏ.</b>", parse_mode=ParseMode.HTML)
        return
    await update.message.reply_text(admin_text(context), parse_mode=ParseMode.HTML, reply_markup=admin_kb(context))

async def broadcast_cmd(update, context):
    if not is_admin_of(context, update.effective_user.id):
        return
    context.user_data["broadcast"] = True
    await update.message.reply_text("📢 Jᴏ ᴍᴇꜱꜱᴀɢᴇ ʙʜᴇᴊɴᴀ ʜᴀɪ ᴠᴏ ʙʜᴇᴊᴇ.")

async def do_broadcast(update, context, text):
    b = bucket(context)
    targets = list({g["id"] for g in b["groups"]} | set(b["users"]))
    ok = 0
    for cid in targets:
        try:
            await context.bot.send_message(cid, text, parse_mode=ParseMode.HTML)
            ok += 1
        except Exception:
            try:
                await context.bot.send_message(cid, text)
                ok += 1
            except Exception:
                pass
    await update.message.reply_text(f"✅ <b>Bʀᴏᴀᴅᴄᴀꜱᴛ ᴅᴏɴᴇ</b> → {ok}/{len(targets)}", parse_mode=ParseMode.HTML)

async def do_promote(context, text):
    total = 0
    for tok, app in list(RUNNING.items()):
        c = DB["clones"].get(tok, {})
        for uid in c.get("users", []):
            try:
                await app.bot.send_message(uid, text, parse_mode=ParseMode.HTML)
                total += 1
            except Exception:
                pass
    return total

async def promote_cmd(update, context):
    if not is_admin_of(context, update.effective_user.id):
        return
    context.user_data["promote"] = True
    await update.message.reply_text("🚀 Pʀᴏᴍᴏᴛɪᴏɴ ᴍᴇꜱꜱᴀɢᴇ ʙʜᴇᴊᴇ.")

async def on_new_members(update, context):
    if not update.message or not update.message.new_chat_members:
        return
    for m in update.message.new_chat_members:
        if m.id == context.bot.id:
            chat = update.effective_chat
            add_group(context, chat.id, chat.title or chat.full_name, chat.type)
            await update.message.reply_text(
                "╭───── 🙏 <b>Tʜᴀɴᴋꜱ Bʜᴀɪ!</b> 🙏 ─────╮\n"
                "   🎉 Mᴜᴊʜᴇ ᴀᴅᴅ ᴋᴀʀɴᴇ ᴋᴇ ʟɪʏᴇ ꜱʜᴜᴋʀɪʏᴀ 💐\n"
                "╰───────────────────────────╯\n\n"
                "📲 Kɪꜱɪ ʙʜɪ <b>10 ᴅɪɢɪᴛ ɴᴜᴍʙᴇʀ</b> ᴘᴇ ʀᴇᴘʟʏ ᴋᴀʀᴇɴ ᴏʀ\n"
                "   ꜱᴇɴᴅ ᴋᴀʀᴇɴ — ᴘᴜʀɪ ᴅᴇᴛᴀɪʟ ᴍɪʟᴇɢɪ 🔎\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"  {support_line()}\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━",
                parse_mode=ParseMode.HTML, reply_markup=main_kb())

async def on_error(update, context):
    logger.error("Exception while handling an update:", exc_info=context.error)

async def post_init(app):
    try:
        await app.bot.set_my_commands([
            BotCommand("start", "🏠 Welcome menu"),
            BotCommand("lookup", "🔎 Lookup number"),
            BotCommand("clone", "🚀 Clone your own bot"),
            BotCommand("settings", "⚙️ Settings (owner)"),
            BotCommand("help", "📖 Help"),
        ])
    except Exception as e:
        logger.warning(f"set_my_commands: {e}")

# ==================== APP BUILDER ====================
def build_app(token, is_clone=False, clone_owner=None, clone_owner_name=None):
    app = Application.builder().token(token).post_init(post_init).build()
    app.bot_data["is_clone"] = is_clone
    app.bot_data["owner_id"] = clone_owner
    app.bot_data["owner_name"] = clone_owner_name

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("lookup", lookup_cmd))
    app.add_handler(CommandHandler("clone", clone_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("promote", promote_cmd))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_members))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(on_error)
    return app

# ==================== MAIN ====================
async def run():
    global MAIN_APP
    load_db()

    MAIN_APP = build_app(MAIN_TOKEN)
    await MAIN_APP.initialize()
    await MAIN_APP.start()
    await MAIN_APP.updater.start_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
    print("🚀 MAIN BOT START ✅")

    for token, info in list(DB["clones"].items()):
        try:
            app = build_app(token, is_clone=True,
                            clone_owner=info.get("owner_id"),
                            clone_owner_name=info.get("owner_name"))
            await app.initialize()
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
            RUNNING[token] = app
            print(f"♻️  CLONE RESTORED -> {info.get('username') or token}")
        except Exception as e:
            print(f"❌ clone restore fail {token}: {e}")

    print(f"✅ total running: {len(RUNNING)+1}")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(run())