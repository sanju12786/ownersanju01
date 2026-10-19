import json
import logging
import os
import re
import html
import requests

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
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

# ================== CONFIG ==================
BOT_TOKEN = "8769961686:AAEYsUp_NYNxdrw-Ok_ubFzuTNsqKzbjxL8"
ADMIN_IDS = [8616498446, 6162626480, 5574675470]
API_URL = "https://ftosint.world/api/number"
API_KEY = "lightnum2info"
OWNER = "@piyush devloper  |  @linuxvatan"
DATA_FILE = "data.json"

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger("NumberBot")

# ================== STORAGE ==================
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                d.setdefault("groups", [])
                d.setdefault("users", [])
                return d
        except Exception:
            pass
    return {"groups": [], "users": []}

def save_data(d):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)

DATA = load_data()

def add_chat(chat_id, title, ctype):
    for g in DATA["groups"]:
        if g["id"] == chat_id:
            g["title"] = title or g.get("title", "")
            g["type"] = ctype
            save_data(DATA)
            return False
    DATA["groups"].append({"id": chat_id, "title": title or str(chat_id), "type": ctype})
    save_data(DATA)
    return True

def remove_chat(chat_id):
    before = len(DATA["groups"])
    DATA["groups"] = [g for g in DATA["groups"] if g["id"] != chat_id]
    save_data(DATA)
    return len(DATA["groups"]) < before

def add_user(uid):
    if uid not in DATA["users"]:
        DATA["users"].append(uid)
        save_data(DATA)

def is_admin(uid):
    return uid in ADMIN_IDS

# ================== API ==================
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
    out = []
    out.append("📞 𝗡𝗨𝗠𝗕𝗘𝗥 𝗜𝗡𝗙𝗢")
    out.append("")
    out.append("Nᴜᴍʙᴇʀ Dᴀᴛᴀʙᴀꜱᴇ ✅")
    out.append("")
    out.append(f"🔭 Qᴜᴇʀʏ : {query}")
    out.append(f"✍️ Rᴇᴄᴏʀᴅꜱ : {total} | Page 1/1")
    if truecaller:
        out.append(f"☎️ Tʀᴜᴇᴄᴀʟʟᴇʀ : {truecaller}")

    for i, rec in enumerate(records, 1):
        out.append("")
        out.append(sep)
        out.append(f"📰 Rᴇᴄᴏʀᴅ {i}/{total}")
        out.append(sep)
        out.append("")
        out.append(f"📲 Nᴜᴍʙᴇʀ : {rec.get('mobile', 'N/A')}")
        out.append(f"👤 Nᴀᴍᴇ : {rec.get('name', 'N/A')}")
        out.append(f"👥 Fᴀᴛʜᴇʀ : {rec.get('fname', 'N/A')}")
        out.append(f"📞 Aʟᴛ Nᴜᴍ : {rec.get('alt', 'N/A')}")
        out.append(f"🔎 Cɪʀᴄʟᴇ : {rec.get('circle', 'N/A')}")
        out.append(f"🏡 Aᴅᴅʀᴇꜱꜱ : {rec.get('address', 'N/A')}")
        out.append(f"💳 Iᴅ : {rec.get('id', 'N/A')}")

    out.append("")
    out.append("⚠️ DISCLAIMER")
    out.append("  🎓 Educational use only")
    out.append("  🚫 Misuse is illegal")
    out.append("  📜 User is responsible")
    out.append("")
    out.append(f"👑 Oᴡɴᴇʀ : {OWNER}")
    return "\n".join(out)

# ================== TEXTS ==================
def welcome_text(name="Dᴏꜱᴛ"):
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
        "  ➤ 💳 Iᴅ Nᴜᴍʙᴇʀ\n"
        "\n"
        "┏━━━━━━━━━━━━━━━━━━━━━━┓\n"
        "┃   📌  <b>Kᴀɪsᴇ Usᴇ Kᴀʀᴇ?</b>\n"
        "┗━━━━━━━━━━━━━━━━━━━━━━┛\n"
        "  1️⃣ ɴᴇᴇᴄʜᴇ <b>🔎 ʟᴏᴏᴋᴜᴘ ʙᴜᴛᴛᴏɴ</b> ᴅᴀʙᴀʏᴇ\n"
        "  2️⃣ ʏᴀ sɪᴅʜᴀ <b>10 ᴅɪɢɪᴛ ɴᴜᴍʙᴇʀ</b> sᴇɴᴅ ᴋᴀʀᴇ\n"
        "\n"
        "  💡 <i>Tɪᴘ : Gʀᴏᴜᴘ ᴍᴇ ʙᴏᴛ ᴀᴅᴅ ᴋᴀʀᴋᴇ ʙʜɪ ᴜsᴇ ᴋᴀʀ sᴀᴋᴛᴇ ʜᴏ</i>\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  👑 <b>Oᴡɴᴇʀ :</b> {OWNER}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "     ✦ ᴍᴀᴅᴇ ᴡɪᴛʜ ❤️ ʙʏ ᴘɪʏᴜꜱʜ ✦"
    )

HELP_TEXT = (
    "╔══════════════════════════════╗\n"
    "        📖 𝗛 𝗘 𝗟 𝗣  ✦  𝗠 𝗘 𝗡 𝗨\n"
    "╚══════════════════════════════╝\n"
    "\n"
    "┏━━━━━━━━━━━━━━━━━━━━━━┓\n"
    "┃   🚀  <b>Cᴏᴍᴍᴀɴᴅꜱ</b>\n"
    "┗━━━━━━━━━━━━━━━━━━━━━━┛\n"
    "  ➤ /start   → ᴡᴇʟᴄᴏᴍᴇ ᴍᴇɴᴜ\n"
    "  ➤ /lookup  → ɴᴜᴍʙᴇʀ ᴘᴜᴄʜᴇ\n"
    "  ➤ /help    → ʏᴇ ᴍᴇɴᴜ\n"
    "\n"
    "┏━━━━━━━━━━━━━━━━━━━━━━┓\n"
    "┃   🔎  <b>Lᴏᴏᴋᴜᴘ Kᴀɪsᴇ Kᴀʀᴇ</b>\n"
    "┗━━━━━━━━━━━━━━━━━━━━━━┛\n"
    "  ➤ sɪᴅʜᴀ <b>10 ᴅɪɢɪᴛ</b> ɴᴜᴍʙᴇʀ sᴇɴᴅ ᴋᴀʀᴇ\n"
    "  ➤ ʏᴀ 🔎 ʙᴜᴛᴛᴏɴ ᴅᴀʙᴀʏᴇ\n"
    "\n"
    "  📌 Gʀᴏᴜᴘ ᴍᴇ ʙᴏᴛ ᴀᴅᴅ ᴋᴀʀᴋᴇ sɪᴅʜᴀ\n"
    "  ɴᴜᴍʙᴇʀ ʙʜᴇᴊ sᴀᴋᴛᴇ ʜᴏ ✅\n"
    "\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    f"  👑 <b>Oᴡɴᴇʀ :</b> {OWNER}\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━"
)

ADMIN_TEXT = (
    "╔══════════════════════════════╗\n"
    "       🛠 𝗔 𝗗 𝗠 𝗜 𝗡  ✦  𝗣 𝗔 𝗡 𝗘 𝗟\n"
    "╚══════════════════════════════╝\n"
    "\n"
    "  ⚡ ᴘᴜʀᴀ ᴄᴏɴᴛʀᴏʟ ᴀᴀᴘᴋᴇ ʜᴀᴀᴛʜ ᴍᴇ 👇\n"
    "\n"
    "  ➤ ➕ Cʜᴀᴛ ᴀᴅᴅ/ʀᴇᴍᴏᴠᴇ ᴋᴀʀᴇ\n"
    "  ➤ 📋 Cʜᴀᴛ ʟɪꜱᴛ ᴅᴇᴋʜᴇ\n"
    "  ➤ 📊 Bᴏᴛ sᴛᴀᴛꜱ ᴅᴇᴋʜᴇ\n"
    "  ➤ 📢 Sᴀʙ ᴍᴇ ʙʀᴏᴀᴅᴄᴀꜱᴛ ʙʜᴇᴊᴇ\n"
    "\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━"
)

# ================== KEYBOARDS ==================
def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 ʟ ᴏ ᴏ ᴋ ᴜ ᴘ  ɴ ᴜ ᴍ ʙ ᴇ ʀ", callback_data="lookup")],
        [
            InlineKeyboardButton("📖 ʜᴇʟᴘ", callback_data="help"),
            InlineKeyboardButton("👤 ᴏᴡɴᴇʀ", callback_data="owner"),
        ],
        [InlineKeyboardButton("📢 ᴜᴘᴅᴀᴛᴇꜱ", url="https://t.me/linuxvatan")],
    ])

def result_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 ɴᴇᴡ ʟᴏᴏᴋᴜᴘ", callback_data="lookup")],
        [
            InlineKeyboardButton("👤 ᴏᴡɴᴇʀ", callback_data="owner"),
            InlineKeyboardButton("📖 ʜᴇʟᴘ", callback_data="help"),
        ],
    ])

def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ ᴛʜɪꜱ ᴄʜᴀᴛ ᴀᴅᴅ ᴋᴀʀᴇ", callback_data="adm_add")],
        [InlineKeyboardButton("➖ ᴛʜɪꜱ ᴄʜᴀᴛ ʀᴇᴍᴏᴠᴇ ᴋᴀʀᴇ", callback_data="adm_remove")],
        [
            InlineKeyboardButton("📋 ᴄʜᴀᴛ ʟɪꜱᴛ", callback_data="adm_list"),
            InlineKeyboardButton("📊 ꜱᴛᴀᴛꜱ", callback_data="adm_stats"),
        ],
        [InlineKeyboardButton("📢 ʙʀᴏᴀᴅᴄᴀꜱᴛ", callback_data="adm_broadcast")],
    ])

# ================== HANDLERS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    add_user(update.effective_user.id)
    name = update.effective_user.first_name or "Dᴏꜱᴛ"
    await update.message.reply_text(
        welcome_text(html.escape(name)),
        parse_mode=ParseMode.HTML,
        reply_markup=main_kb(),
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML, reply_markup=main_kb())

async def lookup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["awaiting"] = True
    await update.message.reply_text(
        "🔎 <b>Nᴜᴍʙᴇʀ Lᴏᴏᴋᴜᴘ</b>\n\n📲 Aʙ 10 ᴅɪɢɪᴛ ɴᴜᴍʙᴇʀ ʙʜᴇᴊᴇ 👇",
        parse_mode=ParseMode.HTML,
    )

async def do_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE, number: str):
    msg = await update.effective_message.reply_text("🔎 <b>Sᴇᴀʀᴄʜɪɴɢ...</b>", parse_mode=ParseMode.HTML)
    data = fetch_number(number)

    if data is None or not data.get("success"):
        await msg.edit_text("❌ <b>API ᴇʀʀᴏʀ!</b> ᴛʜᴏᴅɪ ᴅᴇʀ ʙᴀᴀᴅ ᴛʀʏ ᴋᴀʀᴇ.", parse_mode=ParseMode.HTML)
        return

    records = data.get("results", [])
    if not records:
        txt = (
            "📞 𝗡𝗨𝗠𝗕𝗘𝗥 𝗜𝗡𝗙𝗢\n\n"
            f"🔭 Qᴜᴇʀʏ : {number}\n\n"
            "❌ Kᴏɪ ʀᴇᴄᴏʀᴅ ɴᴀʜɪ ᴍɪʟᴀ.\n\n"
            f"👑 Oᴡɴᴇʀ : {OWNER}"
        )
        await msg.edit_text(txt, reply_markup=result_kb())
        return

    result = format_result(number, records, data.get("truecaller_name"))
    safe = html.escape(result)
    await msg.edit_text(
        f"<code>{safe}</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=result_kb(),
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if context.user_data.get("broadcast") and is_admin(update.effective_user.id):
        context.user_data["broadcast"] = False
        await do_broadcast(update, context, text)
        return

    digits = re.sub(r"\D", "", text)
    if len(digits) >= 10:
        context.user_data["awaiting"] = False
        await do_lookup(update, context, digits[-10:])
    elif context.user_data.get("awaiting"):
        await update.message.reply_text("⚠️ Sᴀʜɪ <b>10 ᴅɪɢɪᴛ ɴᴜᴍʙᴇʀ</b> ʙʜᴇᴊᴇ ʙʜᴀɪ.", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(
            "🤔 Sᴀᴍᴀᴊʜ ɴᴀʜɪ ᴀᴀʏᴀ.\n\n📲 10 ᴅɪɢɪᴛ ɴᴜᴍʙᴇʀ ʙʜᴇᴊᴇ ᴏʀ /help ᴅᴀʙᴀʏᴇ.",
            parse_mode=ParseMode.HTML,
        )

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "lookup":
        context.user_data["awaiting"] = True
        await q.message.reply_text(
            "🔎 <b>Nᴜᴍʙᴇʀ Lᴏᴏᴋᴜᴘ</b>\n\n📲 Aʙ 10 ᴅɪɢɪᴛ ɴᴜᴍʙᴇʀ ʙʜᴇᴊᴇ 👇",
            parse_mode=ParseMode.HTML,
        )
    elif data == "help":
        await q.message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML, reply_markup=main_kb())
    elif data == "owner":
        await q.message.reply_text(
            "╭──── 👑 <b>Oᴡɴᴇʀ</b> 👑 ────╮\n"
            f"   {OWNER}\n"
            "╰────────────────────╯",
            parse_mode=ParseMode.HTML,
        )

    # ---------- ADMIN ----------
    elif data == "adm_add":
        if not is_admin(q.from_user.id):
            return
        chat = q.message.chat
        added = add_chat(chat.id, chat.title or chat.full_name, chat.type)
        await q.message.reply_text("✅ <b>Cʜᴀᴛ ᴀᴅᴅ ʜᴏ ɢᴀʏᴀ!</b>" if added else "ℹ️ Yᴇ ᴄʜᴀᴛ ᴘᴇʜʟᴇ sᴇ ᴀᴅᴅ ʜᴀɪ.", parse_mode=ParseMode.HTML)
    elif data == "adm_remove":
        if not is_admin(q.from_user.id):
            return
        removed = remove_chat(q.message.chat.id)
        await q.message.reply_text("✅ <b>Rᴇᴍᴏᴠᴇ ʜᴏ ɢᴀʏᴀ!</b>" if removed else "ℹ️ Yᴇ ᴄʜᴀᴛ ʟɪꜱᴛ ᴍᴇ ɴᴀʜɪ ʜᴀɪ.", parse_mode=ParseMode.HTML)
    elif data == "adm_list":
        if not is_admin(q.from_user.id):
            return
        if not DATA["groups"]:
            await q.message.reply_text("📭 Kᴏɪ ᴄʜᴀᴛ ᴀᴅᴅ ɴᴀʜɪ ʜᴀɪ.")
            return
        txt = "📋 <b>Aᴅᴅᴇᴅ Cʜᴀᴛꜱ</b>\n━━━━━━━━━━━━━━━━━━\n"
        for i, g in enumerate(DATA["groups"], 1):
            txt += f"\n{i}. {g['title']}\n   <code>{g['id']}</code> ({g['type']})"
        await q.message.reply_text(txt, parse_mode=ParseMode.HTML)
    elif data == "adm_stats":
        if not is_admin(q.from_user.id):
            return
        txt = (
            "📊 <b>Sᴛᴀᴛꜱ</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"👥 Usᴇʀs : {len(DATA['users'])}\n"
            f"💬 Cʜᴀᴛs : {len(DATA['groups'])}\n"
            f"👑 Aᴅᴍɪɴs : {len(ADMIN_IDS)}"
        )
        await q.message.reply_text(txt, parse_mode=ParseMode.HTML)
    elif data == "adm_broadcast":
        if not is_admin(q.from_user.id):
            return
        context.user_data["broadcast"] = True
        await q.message.reply_text("📢 Jᴏ ᴍᴇꜱꜱᴀɢᴇ ʙʜᴇᴊɴᴀ ʜᴀɪ ᴠᴏ ʙʜᴇᴊᴇ (ᴛᴇxᴛ).", parse_mode=ParseMode.HTML)

# ================== ADMIN ==================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ <b>Aᴀᴘ ᴀᴅᴍɪɴ ɴᴀʜɪ ʜᴏ.</b>", parse_mode=ParseMode.HTML)
        return
    await update.message.reply_text(ADMIN_TEXT, parse_mode=ParseMode.HTML, reply_markup=admin_kb())

async def add_here(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    chat = update.effective_chat
    added = add_chat(chat.id, chat.title or chat.full_name, chat.type)
    await update.message.reply_text("✅ <b>Cʜᴀᴛ ᴀᴅᴅ ʜᴏ ɢᴀʏᴀ!</b>" if added else "ℹ️ Pᴇʜʟᴇ sᴇ ᴀᴅᴅ ʜᴀɪ.", parse_mode=ParseMode.HTML)

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    context.user_data["broadcast"] = True
    await update.message.reply_text("📢 Jᴏ ᴍᴇꜱꜱᴀɢᴇ ʙʜᴇᴊɴᴀ ʜᴀɪ ᴠᴏ ʙʜᴇᴊᴇ.", parse_mode=ParseMode.HTML)

async def do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    targets = list({g["id"] for g in DATA["groups"]} | set(DATA["users"]))
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

# ================== GROUP AUTO-ADD ==================
async def on_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return
    for m in update.message.new_chat_members:
        if m.id == context.bot.id:
            chat = update.effective_chat
            add_chat(chat.id, chat.title or chat.full_name, chat.type)
            await update.message.reply_text(
                "╭───── 🙏 <b>Tʜᴀɴᴋꜱ Bʜᴀɪ!</b> 🙏 ─────╮\n"
                "   🎉 Mᴜᴊʜᴇ ᴀᴅᴅ ᴋᴀʀɴᴇ ᴋᴇ ʟɪʏᴇ ꜱʜᴜᴋʀɪʏᴀ 💐\n"
                "╰───────────────────────────╯\n\n"
                "📲 Kɪꜱɪ ʙʜɪ <b>10 ᴅɪɢɪᴛ ɴᴜᴍʙᴇʀ</b> ᴘᴇ ʀᴇᴘʟʏ ᴋᴀʀᴇɴ ᴏʀ\n"
                "   ꜱᴇɴᴅ ᴋᴀʀᴇɴ — ᴘᴜʀɪ ᴅᴇᴛᴀɪʟ ᴍɪʟᴇɢɪ 🔎\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"  👑 <b>Oᴡɴᴇʀ :</b> {OWNER}\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━",
                parse_mode=ParseMode.HTML,
                reply_markup=main_kb(),
            )

# ================== MAIN ==================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("lookup", lookup_cmd))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("add", add_here))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_members))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🚀 Bot chalu ho gaya...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()