#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FTOSINT Telegram Bot  ·  v3.0
-----------------------------
• 2 bot tokens (dual instance, ek hi process)
• Column / table design output
• Force-join channel: @Sanjuownersmm
• Empty lookup -> DM contacts (API ka msg hide)
• Credit: @owner_sanju
• Admin panel + broadcast

Install  : pip install python-telegram-bot==21.6 requests
Run      : python bot.py
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ChatAction, ParseMode
from telegram.error import Forbidden, RetryAfter, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ══════════════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════════════
BOT_TOKENS = [
    "8036729272:AAFSzpvCKk2y6dLIOUS1irB1BK23_RPD7oQ",
    "8301154986:AAGGj-fkUoQ_JOYMq4l8QH4gdl2ZsDU2H8A",
]

ADMIN_IDS = {
    6162626480,
    1120314768,
    1559855604,
    5574675470,
}

API_BASE     = "https://ftosint.world/api"
API_KEY      = "cobra-limited-land"
HTTP_TIMEOUT = 30
HTTP_RETRIES = 3

# ── CREDIT / CONTACTS / CHANNEL ──────────────────────────────────────────
CREDIT        = "@owner_sanju"
DM_CONTACTS   = ["@owner_sanju", "@thehiddenreserve"]
CHANNEL_USER  = "Sanjuownersmm"
CHANNEL_AT    = "@Sanjuownersmm"
CHANNEL_LINK  = f"https://t.me/{CHANNEL_USER}"
STRIP_KEYS    = {"by", "credit", "credit_by"}

DATA_DIR   = Path(__file__).parent / "data"
USERS_FILE = DATA_DIR / "users.json"
STATS_FILE = DATA_DIR / "stats.json"
DATA_DIR.mkdir(exist_ok=True)

BOT_NAME  = "FTOSINT Bot"
MSG_LIMIT = 3900

# column widths
LCOL, VCOL = 16, 30

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("ftosint-bot")


# ══════════════════════════════════════════════════════════════════════════
#  STATIC TEXT
# ══════════════════════════════════════════════════════════════════════════
DISCLAIMER = (
    "\n\n⚠️ <b>DISCLAIMER</b>\n"
    "  🎓 Educational use only\n"
    "  🚫 Misuse is illegal\n"
    "  📜 User is responsible"
)

def credit_line() -> str:
    return f"\n\n➤ <b>by</b> @{CREDIT.lstrip('@')}"

def dm_line() -> str:
    return "\n".join(f"➤ {c}" for c in DM_CONTACTS)

NO_RESULT = (
    "❌ <b>RESULT NAHI MILA</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "Is lookup ke liye DM kare:\n"
    f"{dm_line()}"
)

WELCOME = (
    "👋 <b>Welcome to {name}</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "🔍 India ka OSINT toolkit — phone, vehicle, address,\n"
    "GST, PAN, voter aur 20+ lookups ek hi jagah.\n\n"
    "<b>Kaise use karein:</b>\n"
    "• Menu buttons se lookup chuno\n"
    "• Ya seedha value bhej do — khud detect ho jayega\n"
    "  <i>(number · vehicle · PAN · GSTIN · IFSC · pincode · voter)</i>"
)

JOIN_TEXT = (
    "📢 <b>CHANNEL JOIN ZAROORI</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "Bot use karne ke liye pehle\n"
    "channel join karna hoga.\n\n"
    f"➤ {CHANNEL_AT}"
)


# ══════════════════════════════════════════════════════════════════════════
#  ENDPOINT REGISTRY
# ══════════════════════════════════════════════════════════════════════════
ENDPOINTS: Dict[str, Dict[str, Any]] = {
    "number":     {"title": "Number Lookup",          "emoji": "📞", "params": ["num"],       "optional": [],       "binary": False},
    "numleak":    {"title": "Number Leak",            "emoji": "🔎", "params": ["num"],       "optional": [],       "binary": False},
    "nametoinfo": {"title": "Name to Info",           "emoji": "👤", "params": ["name"],      "optional": [],       "binary": False},
    "namesearch": {"title": "Name Search",            "emoji": "👤", "params": ["q"],         "optional": ["from"], "binary": False},
    "voter":      {"title": "Voter ID Lookup",        "emoji": "🗳", "params": ["id"],        "optional": [],       "binary": False},

    "vehicle":    {"title": "Vehicle to Owner",       "emoji": "🚗", "params": ["vehicle"],   "optional": [],       "binary": False},
    "veh2num":    {"title": "Vehicle to Mobile",      "emoji": "🚗", "params": ["vehicle"],   "optional": [],       "binary": False},
    "fastag":     {"title": "FASTag Lookup",          "emoji": "🏷", "params": ["vehicle"],   "optional": [],       "binary": False},
    "challan":    {"title": "Challan Lookup",         "emoji": "🧾", "params": ["vehicle"],   "optional": [],       "binary": False},
    "vinfo":      {"title": "VInfo RC Details",       "emoji": "📘", "params": ["reg"],       "optional": [],       "binary": False},
    "puc":        {"title": "PUC Certificate",        "emoji": "🌿", "params": ["reg"],       "optional": [],       "binary": True},
    "hw":         {"title": "Chassis / Engine",       "emoji": "⚙️", "params": ["chasi"],     "optional": [],       "binary": False},
    "hpt":        {"title": "HP / Financier Record",  "emoji": "📝", "params": ["reg"],       "optional": [],       "binary": False},
    "vehindex":   {"title": "Vehicle Index",          "emoji": "📋", "params": ["reg"],       "optional": [],       "binary": False},
    "rcpdf":      {"title": "RC PDF",                 "emoji": "📄", "params": ["vehicle"],   "optional": [],       "binary": True},
    "rcchip":     {"title": "RC PDF (Chip)",          "emoji": "📄", "params": ["vehicle"],   "optional": [],       "binary": True},

    "address":    {"title": "Address Lookup",         "emoji": "📍", "params": ["address"],   "optional": [],       "binary": False},
    "pincode":    {"title": "Pincode Lookup",         "emoji": "📍", "params": ["pin"],       "optional": [],       "binary": False},

    "ifsc":       {"title": "IFSC Lookup",            "emoji": "🏦", "params": ["ifsc"],      "optional": [],       "binary": False},
    "pan":        {"title": "PAN to GST",             "emoji": "🪪", "params": ["pan"],       "optional": [],       "binary": False},
    "paninfo":    {"title": "PAN to Info",            "emoji": "🪪", "params": ["pan"],       "optional": [],       "binary": False},
    "pantogstin": {"title": "PAN to GSTIN",           "emoji": "🪪", "params": ["pan"],       "optional": [],       "binary": False},
    "aadhar":     {"title": "Aadhaar Lookup",         "emoji": "🆔", "params": ["num"],       "optional": [],       "binary": False},
    "gstin":      {"title": "GSTIN to Info",          "emoji": "🪪", "params": ["gstin"],     "optional": [],       "binary": False},
    "gstin2pan":  {"title": "GSTIN to PAN",           "emoji": "🔄", "params": ["gstin"],     "optional": [],       "binary": False},
    "name2gstin": {"title": "Name to GSTIN",          "emoji": "🔎", "params": ["name"],      "optional": [],       "binary": False},
    "gstreturns": {"title": "GST Returns",            "emoji": "🧾", "params": ["gstin"],     "optional": ["financial_year"], "binary": False},
}

HINTS = {
    "num": "📱 10-digit mobile number\n<code>9876543210</code>",
    "vehicle": "🚗 Registration number\n<code>KA01AB1234</code>",
    "reg": "🚗 Registration number\n<code>MH16BZ7090</code>",
    "chasi": "⚙️ Chassis number\n<code>MA3NYFB1SKD530868</code>",
    "pin": "📍 6-digit pincode\n<code>110001</code>",
    "ifsc": "🏦 IFSC code\n<code>SBIN0001234</code>",
    "pan": "🪪 PAN number\n<code>ABCDE1234F</code>",
    "gstin": "🪪 15-char GSTIN\n<code>07AABCF8078M1Z3</code>",
    "name": "👤 Name\n<code>RAHUL</code>",
    "q": "👤 Name to search\n<code>Ramesh</code>",
    "address": "📍 Address\n<code>Okhla Delhi</code>",
    "id": "🗳 Voter ID\n<code>ZNO1150077</code>",
    "financial_year": "📅 Financial year\n<code>2023-24</code>",
    "from": "🏙 City (optional)\n<code>Delhi</code>",
}


# ══════════════════════════════════════════════════════════════════════════
#  FIELD LABELS
# ══════════════════════════════════════════════════════════════════════════
LABELS: Dict[str, str] = {
    "mobile": "📱 Mobile",     "number": "📱 Number",   "num": "📱 Number",
    "name": "👤 Name",         "full_name": "👤 Name",  "owner": "👤 Owner",
    "fname": "👨 Father",      "father_name": "👨 Father", "father": "👨 Father",
    "address": "📍 Address",   "alt": "☎️ Alt No",     "alt_mobile": "☎️ Alt No",
    "circle": "🏙 Circle",     "email": "✉️ Email",    "id": "🆔 ID",
    "total": "🔢 Total",       "status": "📌 Status",   "state": "🗺 State",
    "district": "🏙 District", "city": "🏙 City",       "pincode": "📍 Pincode",
    "pin": "📍 Pincode",       "vehicle": "🚗 Vehicle", "reg": "🚗 Reg No",
    "reg_no": "🚗 Reg No",     "regno": "🚗 Reg No",    "chassis": "⚙️ Chassis",
    "chasi": "⚙️ Chassis",     "engine": "🔧 Engine",   "engine_no": "🔧 Engine",
    "make": "🏭 Make",         "model": "🚙 Model",     "fuel": "⛽ Fuel",
    "fuel_type": "⛽ Fuel",    "color": "🎨 Colour",    "class": "📦 Class",
    "type": "🏷 Type",         "fit_up_to": "📅 Valid Till", "valid": "📅 Valid",
    "gstin": "🪪 GSTIN",       "pan": "🪪 PAN",         "aadhaar": "🆔 Aadhaar",
    "ifsc": "🏦 IFSC",         "bank": "🏦 Bank",       "branch": "🏦 Branch",
    "micr": "🔢 MICR",         "trade_name": "🏢 Trade Name",
    "legal_name": "🏢 Legal Name", "business": "🏢 Business",
    "business_type": "🏷 Type", "reg_date": "📅 Reg Date", "regdate": "📅 Reg Date",
    "taxpayer_type": "🏷 Taxpayer", "gst_status": "📌 GST Status",
    "financier": "🏦 Financier", "hp": "🏦 HP",         "hp_name": "🏦 Financier",
    "return_type": "🧾 Return", "financial_year": "📅 Fin. Year",
    "fy": "📅 Fin. Year",      "period": "📅 Period",   "due_date": "⏰ Due",
    "filing_date": "📅 Filed", "arn": "🔢 ARN",         "taxable": "💰 Taxable",
    "challan_no": "🔢 Challan", "challan": "🔢 Challan","amount": "💰 Amount",
    "offence": "🚨 Offence",   "date": "📅 Date",       "place": "📍 Place",
    "voter": "🗳 Voter ID",    "epic": "🗳 EPIC",       "part": "🔢 Part",
    "age": "🎂 Age",           "gender": "⚧ Gender",    "dob": "🎂 DOB",
    "relation": "👨 Relation", "relative": "👨 Relative",
    "fastag": "🏷 FASTag",     "tag_id": "🏷 Tag ID",   "wallet": "💰 Wallet",
    "puc_no": "🌿 PUC No",     "puc": "🌿 PUC",        "expiry": "📅 Expiry",
    "expiry_date": "📅 Expiry","issued": "📅 Issued",   "issuer": "🏢 Issuer",
    "code": "🔢 Code",         "area": "📍 Area",       "region": "🗺 Region",
    "division": "🏙 Division", "office": "🏢 Office",   "taluk": "🏙 Taluk",
    "message": "💬 Message",   "msg": "💬 Message",     "error": "❌ Error",
}

def label_for(key: str) -> str:
    k = str(key).strip().lower().replace(" ", "_")
    if k in LABELS:
        return LABELS[k]
    pretty = re.sub(r"[_\-]+", " ", k).strip().title()
    if len(pretty) > LCOL - 2:
        pretty = pretty[:LCOL - 3] + "."
    return f"🔹 {pretty}"


# ══════════════════════════════════════════════════════════════════════════
#  STORAGE
# ══════════════════════════════════════════════════════════════════════════
def _load(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:                                   # noqa: BLE001
        log.warning("load %s failed: %s", path.name, e)
    return default


def _save(path: Path, obj: Any) -> None:
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except Exception as e:                                   # noqa: BLE001
        log.warning("save %s failed: %s", path.name, e)


def load_users() -> Dict[str, dict]:
    return _load(USERS_FILE, {})


def save_users(u: Dict[str, dict]) -> None:
    _save(USERS_FILE, u)


def load_stats() -> dict:
    return _load(STATS_FILE, {
        "total_lookups": 0,
        "per_endpoint": {},
        "broadcasts": 0,
        "no_result": 0,
        "started": datetime.now(timezone.utc).isoformat(),
    })


def save_stats(s: dict) -> None:
    _save(STATS_FILE, s)


def register_user(update: Update) -> None:
    u = update.effective_user
    if not u:
        return
    users = load_users()
    key = str(u.id)
    if key not in users:
        users[key] = {
            "id": u.id,
            "username": u.username or "",
            "name": u.full_name,
            "joined": datetime.now(timezone.utc).isoformat(),
            "lookups": 0,
            "banned": False,
            "channel_ok": False,
        }
        log.info("new user %s (@%s)", u.id, u.username)
    else:
        users[key]["username"] = u.username or ""
        users[key]["name"] = u.full_name
    save_users(users)


def bump_counter(user_id: int, endpoint: Optional[str] = None) -> None:
    s = load_stats()
    if endpoint:
        s["total_lookups"] = s.get("total_lookups", 0) + 1
        s.setdefault("per_endpoint", {})
        s["per_endpoint"][endpoint] = s["per_endpoint"].get(endpoint, 0) + 1
    save_stats(s)

    users = load_users()
    k = str(user_id)
    if k in users:
        users[k]["lookups"] = users[k].get("lookups", 0) + 1
        save_users(users)


# ══════════════════════════════════════════════════════════════════════════
#  API CLIENT
# ══════════════════════════════════════════════════════════════════════════
class APIError(Exception):
    pass


SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "ftosint-tg-bot/3.0", "Accept": "*/*"})


def api_call(endpoint: str, params: Dict[str, Any], binary: bool = False) -> Any:
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    clean["key"] = API_KEY
    url = f"{API_BASE}/{endpoint}"

    last: Optional[Exception] = None
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            r = SESSION.get(url, params=clean, timeout=HTTP_TIMEOUT)
            if r.status_code == 429 or (500 <= r.status_code < 600 and attempt < HTTP_RETRIES):
                time.sleep(1.5 * attempt)
                continue
            r.raise_for_status()
            if binary:
                return r.content
            if not r.content:
                return None
            try:
                return r.json()
            except ValueError:
                return r.text
        except requests.RequestException as e:
            last = e
            if attempt < HTTP_RETRIES:
                time.sleep(1.5 * attempt)
    raise APIError(str(last) if last else "unknown error")


def run_lookup(endpoint: str, raw: str) -> Any:
    spec = ENDPOINTS[endpoint]
    names = spec["params"] + spec["optional"]
    parts = [p.strip() for p in re.split(r"[|,]", raw, maxsplit=len(names) - 1)]

    if not parts or not parts[0]:
        raise APIError("empty value")
    if len(parts) < len(spec["params"]):
        raise APIError("needed " + " | ".join(spec["params"] + spec["optional"]))

    kwargs: Dict[str, Any] = {}
    for i, n in enumerate(names):
        if i < len(parts) and parts[i]:
            kwargs[n] = parts[i]
    return api_call(endpoint, kwargs, binary=spec["binary"])


# ══════════════════════════════════════════════════════════════════════════
#  CREDIT STRIPPER + EMPTY DETECTOR
# ══════════════════════════════════════════════════════════════════════════
def strip_credit(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: strip_credit(v) for k, v in obj.items()
                if str(k).strip().lower() not in STRIP_KEYS}
    if isinstance(obj, list):
        return [strip_credit(i) for i in obj]
    return obj


DM_WORDS = ("dm ", " dm", "telegram", "contact", "join ", "not found",
            "no data", "no record", "invalid", "please", "try again",
            "unavailable", "failed", "upgrade", "plan")

def is_empty(data: Any) -> bool:
    """True = result nahi mila (API ka 'dm karo' message bhi yahin aata hai)."""
    if data is None:
        return True
    if isinstance(data, (bytes, bytearray)):
        return len(data) < 200
    if isinstance(data, str):
        s = data.strip().lower()
        if not s:
            return True
        return any(w in s for w in DM_WORDS)
    if isinstance(data, dict):
        if data.get("success") is False:
            return True
        for key in ("results", "records", "data", "result", "items", "list"):
            v = data.get(key)
            if isinstance(v, list):
                if not v:
                    return True
                clean = [strip_credit(r) for r in v]
                return all(not r for r in clean)
        core = {k: v for k, v in data.items()
                if str(k).lower() not in SKIP_META and str(k).lower() not in STRIP_KEYS}
        return len(core) == 0
    if isinstance(data, list):
        return len(data) == 0
    return False


# ══════════════════════════════════════════════════════════════════════════
#  TABLE / COLUMN RENDERER
# ══════════════════════════════════════════════════════════════════════════
def esc(t: Any) -> str:
    return html.escape(str(t), quote=False)


def stringify(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, (list, tuple)):
        return ", ".join(stringify(x) for x in v) or "—"
    if isinstance(v, dict):
        return ", ".join(f"{k}: {stringify(x)}" for k, x in v.items()) or "—"
    s = str(v).strip()
    return s if s and s.upper() != "N/A" else "—"


def _border(l: str, m: str, r: str) -> str:
    return l + "━" * (LCOL + 4) + m + "━" * (VCOL + 4) + r


TOP_B = _border("┏", "┳", "┓")
MID_B = _border("┣", "╋", "┫")
BOT_B = _border("┗", "┻", "┛")
HEAD_R = "┃ " + "FIELD".ljust(LCOL) + "┃ " + "VALUE"
BLANK_R = "┃ " + " " * LCOL + "┃"


def table_title(title: str) -> str:
    return f"┏━━ {title} " + "━" * 26


def cell_rows(label: str, value: str, width: int = VCOL) -> List[str]:
    parts = textwrap.wrap(value, width) or ["—"]
    out = [f"┃ {label.ljust(LCOL)}┃ {parts[0]}"]
    for p in parts[1:]:
        out.append(f"┃ {' ' * LCOL}┃ {p}")
    return out


def render_table(rows: List[tuple], title: str) -> str:
    lines = [table_title(title), HEAD_R, MID_B]
    for label, value in rows:
        if value is None:
            lines.append(BLANK_R)
            continue
        if isinstance(value, list):                    # nested block
            lines.append(BLANK_R)
            for sub_label, sub_val in value:
                lines += cell_rows("  " + sub_label, sub_val)
            continue
        lines += cell_rows(label, value)
    lines.append(BOT_B)
    return "\n".join(lines)


def record_to_rows(rec: Dict[str, Any]) -> List[tuple]:
    rows: List[tuple] = []
    for k, v in rec.items():
        if isinstance(v, dict) and v:
            rows.append((label_for(k), None))
            rows.append((None, [(label_for(k2), stringify(v2)) for k2, v2 in v.items()]))
        else:
            rows.append((label_for(k), stringify(v)))
    return rows


ENVELOPE_KEYS = ("results", "records", "data", "result", "items", "list")
SKIP_META = {"success", "status_code", "code", "message", "msg", "error",
             "count", "page", "limit"}


def render_data(data: Any) -> str:
    if data is None:
        return "┏━━ 📭 EMPTY\n┗" + "━" * 30 + "\nNo data returned."
    if isinstance(data, str):
        return data.strip()

    data = strip_credit(data)

    if isinstance(data, dict):
        for key in ENVELOPE_KEYS:
            val = data.get(key)
            if isinstance(val, list):
                blocks: List[str] = []
                total = len(val)
                for i, rec in enumerate(val, 1):
                    if isinstance(rec, dict):
                        blocks.append(render_table(record_to_rows(rec),
                                                   f"🧾 RECORD {i}/{total}"))
                    else:
                        blocks.append(render_table(
                            [("🔹 Value", stringify(rec))], f"🧾 RECORD {i}/{total}"))
                meta = {k: v for k, v in data.items()
                        if k != key and not isinstance(v, (list, dict))
                        and str(k).lower() not in SKIP_META}
                if meta:
                    blocks.append(render_table(
                        [(label_for(k), stringify(v)) for k, v in meta.items()],
                        "📌 SUMMARY"))
                return "\n\n".join(blocks)
        return render_table(record_to_rows(data), "📋 DETAILS")

    if isinstance(data, list):
        return "\n\n".join(
            render_table(record_to_rows(it), f"🧾 RECORD {i}/{len(data)}")
            if isinstance(it, dict) else
            render_table([("🔹 Value", stringify(it))], f"🧾 RECORD {i}/{len(data)}")
            for i, it in enumerate(data, 1)
        ) or "┏━━ 📭 EMPTY\n┗" + "━" * 30

    return stringify(data)


def chunks(text: str, size: int = MSG_LIMIT) -> List[str]:
    if len(text) <= size:
        return [text]
    out, cur = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > size:
            out.append(line[:size])
            line = line[size:]
        if len(cur) + len(line) > size:
            out.append(cur)
            cur = ""
        cur += line
    if cur:
        out.append(cur)
    return out


def header(endpoint: str, value: str) -> str:
    s = ENDPOINTS[endpoint]
    return (
        f"{s['emoji']} <b>{esc(s['title'].upper())}</b>\n"
        f"<code>{esc(value)}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
    )


def footer() -> str:
    return credit_line() + DISCLAIMER


# ══════════════════════════════════════════════════════════════════════════
#  KEYBOARDS
# ══════════════════════════════════════════════════════════════════════════
CATEGORIES = {
    "phone":   ("📱 Phone / Person", ["number", "numleak", "nametoinfo", "namesearch", "voter"]),
    "vehicle": ("🚗 Vehicle",        ["vehicle", "veh2num", "fastag", "challan", "vinfo",
                                      "puc", "hw", "hpt", "vehindex", "rcpdf", "rcchip"]),
    "address": ("📍 Address / Geo",  ["address", "pincode"]),
    "tax":     ("🏦 Tax / Identity", ["ifsc", "pan", "paninfo", "pantogstin", "aadhar",
                                      "gstin", "gstin2pan", "name2gstin", "gstreturns"]),
}


def main_menu() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(label, callback_data=f"cat:{key}")]
            for key, (label, _) in CATEGORIES.items()]
    rows.append([InlineKeyboardButton("📋 Poori List", callback_data="help")])
    rows.append([
        InlineKeyboardButton("📢 Channel", url=CHANNEL_LINK),
        InlineKeyboardButton("➤ Owner", url=f"https://t.me/{CREDIT.lstrip('@')}"),
    ])
    rows.append([InlineKeyboardButton("🆔 My ID", callback_data="myid")])
    return InlineKeyboardMarkup(rows)


def cat_menu(key: str) -> InlineKeyboardMarkup:
    _, items = CATEGORIES[key]
    rows, row = [], []
    for ep in items:
        s = ENDPOINTS[ep]
        row.append(InlineKeyboardButton(f"{s['emoji']} {s['title']}", callback_data=f"lk:{ep}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="menu")])
    return InlineKeyboardMarkup(rows)


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("✖️ Cancel", callback_data="cancel")]])


def join_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel", url=CHANNEL_LINK)],
        [InlineKeyboardButton("✅ Verify / Continue", callback_data="verify")],
    ])


def admin_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Stats", callback_data="ad:stats"),
         InlineKeyboardButton("👥 Users", callback_data="ad:users")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="ad:broadcast"),
         InlineKeyboardButton("📤 Export", callback_data="ad:export")],
        [InlineKeyboardButton("🔎 Test API", callback_data="ad:test"),
         InlineKeyboardButton("📡 Endpoint Usage", callback_data="ad:usage")],
        [InlineKeyboardButton("🤖 Bots / Tokens", callback_data="ad:bots")],
        [InlineKeyboardButton("♻️ Reload Panel", callback_data="ad:panel")],
    ])


# ══════════════════════════════════════════════════════════════════════════
#  RUNTIME STATE
# ══════════════════════════════════════════════════════════════════════════
PENDING: Dict[int, str] = {}
AWAITING_BROADCAST: Dict[int, bool] = {}
JOIN_CACHE: Dict[int, float] = {}
JOIN_TTL = 600


# ══════════════════════════════════════════════════════════════════════════
#  FORCE JOIN
# ══════════════════════════════════════════════════════════════════════════
async def is_member(bot, uid: int) -> bool:
    now = time.time()
    cached = JOIN_CACHE.get(uid)
    if cached and now - cached < JOIN_TTL:
        return True
    try:
        m = await bot.get_chat_member(f"@{CHANNEL_USER}", uid)
        ok = str(m.status) in ("member", "administrator", "creator", "restricted")
    except TelegramError as e:
        log.warning("join check failed: %s", e)
        ok = True                                   # check fail -> allow
    if ok:
        JOIN_CACHE[uid] = now
    return ok


async def require_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """True = joined (aage badho). False = join prompt bhej diya."""
    uid = update.effective_user.id
    if await is_member(context.bot, uid):
        return True

    kb = join_kb()
    if update.callback_query:
        try:
            await update.callback_query.message.reply_text(
                JOIN_TEXT, parse_mode=ParseMode.HTML, reply_markup=kb)
        except TelegramError:
            pass
    elif update.message:
        await update.message.reply_text(JOIN_TEXT, parse_mode=ParseMode.HTML, reply_markup=kb)
    return False


# ══════════════════════════════════════════════════════════════════════════
#  CORE LOOKUP
# ══════════════════════════════════════════════════════════════════════════
async def execute_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE,
                         endpoint: str, value: str) -> None:
    chat = update.effective_chat
    user = update.effective_user
    spec = ENDPOINTS[endpoint]

    await context.bot.send_chat_action(chat.id, ChatAction.TYPING)

    names = spec["params"] + spec["optional"]
    if len(names) > 1 and "|" not in value and "," not in value and not spec["optional"]:
        await chat.send_message(
            f"❌ Need {len(spec['params'])} values separated by <code>|</code>\n"
            f"Example: <code>{' | '.join(names)}</code>",
            parse_mode=ParseMode.HTML)
        return

    head = header(endpoint, value)

    try:
        data = await asyncio.to_thread(run_lookup, endpoint, value)
    except APIError as e:
        await chat.send_message(
            head + f"❌ <b>Lookup failed</b>\n<code>{esc(e)}</code>" + footer(),
            parse_mode=ParseMode.HTML)
        return
    except Exception as e:                                   # noqa: BLE001
        log.exception("lookup crash")
        await chat.send_message(f"❌ Unexpected error: <code>{esc(e)}</code>",
                                parse_mode=ParseMode.HTML)
        return

    bump_counter(user.id, endpoint)

    # ── result nahi mila -> API ka msg hide ───────────────────────────
    if is_empty(data):
        s = load_stats()
        s["no_result"] = s.get("no_result", 0) + 1
        save_stats(s)
        await chat.send_message(head + NO_RESULT + footer(), parse_mode=ParseMode.HTML)
        return

    # ── PDF endpoints ─────────────────────────────────────────────────
    if spec["binary"]:
        if isinstance(data, (bytes, bytearray)) and len(data) >= 200:
            await chat.send_document(
                document=data,
                filename=f"{endpoint}_{re.sub(r'[^A-Za-z0-9]', '', value)}.pdf",
                caption=(head + footer())[:1024],
                parse_mode=ParseMode.HTML)
            return
        txt = (data.decode("utf-8", "ignore")
               if isinstance(data, (bytes, bytearray)) else render_data(data))
        await chat.send_message(head + f"<pre>{esc(txt[:3000])}</pre>" + footer(),
                                parse_mode=ParseMode.HTML)
        return

    # ── text result ───────────────────────────────────────────────────
    body = render_data(data)
    parts = chunks(body)
    total = len(parts)

    for i, part in enumerate(parts):
        chunk_head = head if i == 0 else f"<i>… ({i + 1}/{total})</i>\n"
        tail = footer() if i == total - 1 else ""
        text = f"{chunk_head}<pre>{esc(part)}</pre>{tail}"
        try:
            await chat.send_message(text, parse_mode=ParseMode.HTML,
                                    disable_web_page_preview=True)
        except TelegramError:
            await chat.send_message(f"{chunk_head}<pre>{esc(part)}</pre>{tail}",
                                    parse_mode=ParseMode.HTML)


# ══════════════════════════════════════════════════════════════════════════
#  HELP
# ══════════════════════════════════════════════════════════════════════════
def help_text() -> str:
    lines = ["📋 <b>POORI LIST</b>", "━━━━━━━━━━━━━━━━━━━━━━", ""]
    for _, (label, eps) in CATEGORIES.items():
        lines.append(f"<b>{label}</b>")
        for ep in eps:
            s = ENDPOINTS[ep]
            lines.append(f"  {s['emoji']} {s['title']}  ·  <code>/{ep}</code>")
        lines.append("")
    lines.append("<i>Command zaroori nahi — buttons se bhi sab ho jata hai.</i>")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════
#  USER HANDLERS
# ══════════════════════════════════════════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update)
    PENDING.pop(update.effective_user.id, None)

    if not await require_join(update, context):
        return

    await update.message.reply_text(
        WELCOME.format(name=BOT_NAME) + footer(),
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
        disable_web_page_preview=True)


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update)
    PENDING.pop(update.effective_user.id, None)
    if not await require_join(update, context):
        return
    await update.message.reply_text("📂 <b>Category chuno</b>",
                                    parse_mode=ParseMode.HTML, reply_markup=main_menu())


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update)
    await update.message.reply_text(help_text(), parse_mode=ParseMode.HTML,
                                    disable_web_page_preview=True)


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update)
    u = update.effective_user
    await update.message.reply_text(
        f"🆔 <b>Your ID:</b> <code>{u.id}</code>\n"
        f"💬 <b>Chat ID:</b> <code>{update.effective_chat.id}</code>\n"
        f"👤 {esc(u.full_name)}", parse_mode=ParseMode.HTML)


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    PENDING.pop(update.effective_user.id, None)
    AWAITING_BROADCAST.pop(update.effective_user.id, None)
    await update.message.reply_text("✖️ Cancelled.", reply_markup=main_menu())


async def cmd_stats_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update)
    users = load_users()
    me = users.get(str(update.effective_user.id), {})
    s = load_stats()
    rows = [
        ("🔍 My Lookups", str(me.get("lookups", 0))),
        ("📅 Joined", str(me.get("joined", "-"))[:10]),
        ("🌍 Bot Total", str(s.get("total_lookups", 0))),
        ("👥 Total Users", str(len(users))),
    ]
    await update.message.reply_text(
        f"📊 <b>YOUR STATS</b>\n━━━━━━━━━━━━━━━━━━━━━━\n<pre>"
        + esc(render_table(rows, "📈 COUNTER"))
        + "</pre>" + footer(), parse_mode=ParseMode.HTML)


def make_lookup_command(endpoint: str):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        register_user(update)
        uid = update.effective_user.id
        spec = ENDPOINTS[endpoint]

        if context.args:
            PENDING.pop(uid, None)
            await execute_lookup(update, context, endpoint, " ".join(context.args))
            return

        if not await require_join(update, context):
            return

        PENDING[uid] = endpoint
        names = spec["params"] + spec["optional"]
        opt = " <i>(optional)</i>" if spec["optional"] else ""
        await update.message.reply_text(
            f"{spec['emoji']} <b>{esc(spec['title'])}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Bhejo: <code>{' | '.join(names)}</code>{opt}\n\n"
            + "\n\n".join(HINTS.get(n, n) for n in names)
            + "\n\n<i>/cancel se ruk sakte ho</i>",
            parse_mode=ParseMode.HTML, reply_markup=cancel_kb())
    return handler


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update)
    uid = update.effective_user.id
    text = (update.message.text or "").strip()

    if AWAITING_BROADCAST.get(uid) and uid in ADMIN_IDS:
        AWAITING_BROADCAST[uid] = False
        await do_broadcast(update, context, update.message)
        return

    if not await require_join(update, context):
        return

    if uid in PENDING:
        endpoint = PENDING.pop(uid)
        await execute_lookup(update, context, endpoint, text)
        return

    guess = autodetect(text)
    if guess:
        await execute_lookup(update, context, guess, text)
        return

    await update.message.reply_text(
        "🤔 Samajh nahi aaya. Neeche se chuno:",
        reply_markup=main_menu())


def autodetect(text: str) -> Optional[str]:
    t = re.sub(r"\s+", "", text).upper()
    if re.fullmatch(r"\d{10}", t):
        return "number"
    if re.fullmatch(r"\d{12}", t):
        return "aadhar"
    if re.fullmatch(r"\d{6}", t):
        return "pincode"
    if re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", t):
        return "paninfo"
    if re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z]\d", t):
        return "gstin"
    if re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", t):
        return "ifsc"
    if re.fullmatch(r"[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{4}", t):
        return "vehicle"
    if re.fullmatch(r"[A-Z]{3}\d{7}", t):
        return "voter"
    return None


# ══════════════════════════════════════════════════════════════════════════
#  CALLBACKS
# ══════════════════════════════════════════════════════════════════════════
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    uid = q.from_user.id
    register_user(update)

    if data == "verify":
        JOIN_CACHE.pop(uid, None)
        if await is_member(context.bot, uid):
            await q.edit_message_text(
                "✅ <b>Verified!</b> Ab bot use karo.\n\n📂 Category chuno:",
                parse_mode=ParseMode.HTML, reply_markup=main_menu())
        else:
            await q.edit_message_text(
                JOIN_TEXT + "\n\n❌ <i>Abhi join nahi hua, dobara try karo.</i>",
                parse_mode=ParseMode.HTML, reply_markup=join_kb())
        return

    if data == "menu":
        PENDING.pop(uid, None)
        await q.edit_message_text("📂 <b>Category chuno</b>", parse_mode=ParseMode.HTML,
                                  reply_markup=main_menu())
        return

    if data == "help":
        await q.message.reply_text(help_text(), parse_mode=ParseMode.HTML,
                                   disable_web_page_preview=True)
        return

    if data == "myid":
        await q.message.reply_text(f"🆔 <code>{q.from_user.id}</code>",
                                   parse_mode=ParseMode.HTML)
        return

    if data == "cancel":
        PENDING.pop(uid, None)
        await q.edit_message_text("✖️ Cancelled.", reply_markup=main_menu())
        return

    if data.startswith("cat:"):
        if not await is_member(context.bot, uid):
            await q.answer("Pehle channel join karo!", show_alert=True)
            await q.message.reply_text(JOIN_TEXT, parse_mode=ParseMode.HTML,
                                       reply_markup=join_kb())
            return
        key = data.split(":", 1)[1]
        if key in CATEGORIES:
            label, _ = CATEGORIES[key]
            await q.edit_message_text(f"<b>{label}</b>\nKaunsa lookup chahiye?",
                                      parse_mode=ParseMode.HTML, reply_markup=cat_menu(key))
        return

    if data.startswith("lk:"):
        if not await is_member(context.bot, uid):
            await q.answer("Pehle channel join karo!", show_alert=True)
            await q.message.reply_text(JOIN_TEXT, parse_mode=ParseMode.HTML,
                                       reply_markup=join_kb())
            return
        ep = data.split(":", 1)[1]
        if ep not in ENDPOINTS:
            return
        PENDING[uid] = ep
        spec = ENDPOINTS[ep]
        names = spec["params"] + spec["optional"]
        opt = " <i>(optional)</i>" if spec["optional"] else ""
        await q.edit_message_text(
            f"{spec['emoji']} <b>{esc(spec['title'])}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Bhejo: <code>{' | '.join(names)}</code>{opt}\n\n"
            + "\n\n".join(HINTS.get(n, n) for n in names),
            parse_mode=ParseMode.HTML, reply_markup=cancel_kb())
        return

    if data.startswith("ad:"):
        if uid not in ADMIN_IDS:
            await q.answer("Admin only", show_alert=True)
            return
        await handle_admin_callback(update, context, data.split(":", 1)[1])
        return


# ══════════════════════════════════════════════════════════════════════════
#  ADMIN
# ══════════════════════════════════════════════════════════════════════════
def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    rows = [
        ("🤖 Bots", str(len(BOT_TOKENS))),
        ("👥 Users", str(len(load_users()))),
        ("🔍 Lookups", str(load_stats().get("total_lookups", 0))),
        ("📢 Broadcasts", str(load_stats().get("broadcasts", 0))),
    ]
    await update.message.reply_text(
        "🛠 <b>ADMIN PANEL</b>\n━━━━━━━━━━━━━━━━━━━━━━\n<pre>"
        + esc(render_table(rows, "⚙️ OVERVIEW"))
        + "</pre>", parse_mode=ParseMode.HTML, reply_markup=admin_panel())


async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                action: str) -> None:
    q = update.callback_query
    uid = q.from_user.id

    if action == "panel":
        await q.edit_message_text("🛠 <b>ADMIN PANEL</b>", parse_mode=ParseMode.HTML,
                                  reply_markup=admin_panel())
        return

    if action == "stats":
        s = load_stats()
        users = load_users()
        now = datetime.now(timezone.utc)
        try:
            started = datetime.fromisoformat(s.get("started", now.isoformat()))
        except ValueError:
            started = now
        days = max((now - started).days, 1)
        active = sum(1 for u in users.values() if u.get("lookups", 0) > 0)
        rows = [
            ("👥 Total Users", str(len(users))),
            ("✅ Active Users", str(active)),
            ("🔍 Total Lookups", str(s.get("total_lookups", 0))),
            ("❌ No Result", str(s.get("no_result", 0))),
            ("📈 Avg / Day", str(s.get("total_lookups", 0) // days)),
            ("📢 Broadcasts", str(s.get("broadcasts", 0))),
            ("🕐 Uptime", f"{days}d"),
            ("🤖 Bots Online", str(len(BOT_TOKENS))),
            ("💾 Storage", f"{USERS_FILE.stat().st_size if USERS_FILE.exists() else 0:,} B"),
        ]
        await q.edit_message_text(
            "📊 <b>BOT STATISTICS</b>\n━━━━━━━━━━━━━━━━━━━━━━\n<pre>"
            + esc(render_table(rows, "📈 STATS"))
            + "</pre>", parse_mode=ParseMode.HTML, reply_markup=admin_panel())
        return

    if action == "bots":
        rows = []
        for i, tok in enumerate(BOT_TOKENS, 1):
            bot_id = tok.split(":")[0]
            rows.append((f"🤖 Bot {i}", f"{bot_id}…{tok[-6:]}"))
        rows.append(("📢 Channel", CHANNEL_AT))
        rows.append(("➤ Credit", CREDIT))
        rows.append(("📨 DM Contacts", ", ".join(DM_CONTACTS)))
        rows.append(("🛡 Admins", str(len(ADMIN_IDS))))
        await q.edit_message_text(
            "🤖 <b>BOT / TOKEN INFO</b>\n━━━━━━━━━━━━━━━━━━━━━━\n<pre>"
            + esc(render_table(rows, "⚙️ CONFIG"))
            + "</pre>", parse_mode=ParseMode.HTML, reply_markup=admin_panel())
        return

    if action == "usage":
        per = load_stats().get("per_endpoint", {})
        if not per:
            await q.edit_message_text("📡 Abhi koi lookup nahi hua.",
                                      reply_markup=admin_panel())
            return
        rows = [(f"{ENDPOINTS.get(ep, {}).get('emoji', '•')} {ep}", str(c))
                for ep, c in sorted(per.items(), key=lambda x: -x[1])[:15]]
        await q.edit_message_text(
            "📡 <b>TOP ENDPOINTS</b>\n━━━━━━━━━━━━━━━━━━━━━━\n<pre>"
            + esc(render_table(rows, "🔝 USAGE"))
            + "</pre>", parse_mode=ParseMode.HTML, reply_markup=admin_panel())
        return

    if action == "users":
        users = load_users()
        banned = sum(1 for u in users.values() if u.get("banned"))
        lines = [
            "👥 <b>USER DATABASE</b>\n━━━━━━━━━━━━━━━━━━━━━━",
            f"Total: <b>{len(users)}</b> · Banned: <b>{banned}</b>\n",
        ]
        for u in list(users.values())[-20:][::-1]:
            flag = "🚫" if u.get("banned") else "✅"
            un = f"@{u['username']}" if u.get("username") else "—"
            lines.append(f"{flag} <code>{u['id']}</code> {esc(u.get('name', ''))[:20]} "
                         f"{esc(un)} · {u.get('lookups', 0)}🔍")
        lines.append("\n<i>Last 20 dikhaye. /export se pura file lo.</i>")
        await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML,
                                  reply_markup=admin_panel())
        return

    if action == "export":
        users = load_users()
        path = DATA_DIR / f"users_export_{int(time.time())}.json"
        path.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")
        with path.open("rb") as f:
            await q.message.reply_document(f, filename=path.name,
                                           caption=f"👥 {len(users)} users exported")
        return

    if action == "test":
        await q.edit_message_text("🔎 Testing <code>number</code>…",
                                  parse_mode=ParseMode.HTML)
        try:
            res = await asyncio.to_thread(api_call, "number", {"num": "7565810401"})
            body = render_data(res) if not is_empty(res) else NO_RESULT
            await q.message.reply_text(
                "✅ <b>API OK</b>\n━━━━━━━━━━━━━━━━━━━━━━\n<pre>"
                + esc(body[:2500]) + "</pre>" + footer(), parse_mode=ParseMode.HTML)
        except Exception as e:                               # noqa: BLE001
            await q.message.reply_text(f"❌ API FAIL\n<code>{esc(e)}</code>",
                                       parse_mode=ParseMode.HTML)
        return

    if action == "broadcast":
        AWAITING_BROADCAST[uid] = True
        await q.edit_message_text(
            "📢 <b>BROADCAST MODE</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Ab apna message bhejo — text, photo, video, document.\n\n"
            "<i>Sab users ko chala jayega.</i>\n/cancel se bahar aa jao.",
            parse_mode=ParseMode.HTML)
        return


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if context.args:
        await do_broadcast(update, context, update.message, text=" ".join(context.args))
        return
    AWAITING_BROADCAST[update.effective_user.id] = True
    await update.message.reply_text(
        "📢 <b>Broadcast mode ON</b>\n\nAb message bhejo (text/photo/video/file).",
        parse_mode=ParseMode.HTML)


async def do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       message, text: Optional[str] = None) -> None:
    users = load_users()
    targets = [int(k) for k, v in users.items() if not v.get("banned")]
    admin_chat = update.effective_chat.id

    if not targets:
        await context.bot.send_message(admin_chat, "❌ Koi user nahi hai.")
        return

    status = await context.bot.send_message(
        admin_chat, f"📢 Broadcasting to <b>{len(targets)}</b> users…\n▓░░░░░░░░░ 0%",
        parse_mode=ParseMode.HTML)

    ok = fail = blocked = 0
    t0 = time.time()

    for i, uid in enumerate(targets, 1):
        try:
            if text is not None:
                await context.bot.send_message(uid, text, parse_mode=ParseMode.HTML,
                                               disable_web_page_preview=True)
            else:
                await message.copy_to(chat_id=uid)
            ok += 1
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 0.5)
            try:
                await message.copy_to(chat_id=uid)
                ok += 1
            except TelegramError:
                fail += 1
        except Forbidden:
            blocked += 1
            users[str(uid)]["banned"] = True
        except TelegramError:
            fail += 1

        if i % 20 == 0 or i == len(targets):
            pct = int(i / len(targets) * 100)
            bar = "▓" * (pct // 10) + "░" * (10 - pct // 10)
            try:
                await context.bot.edit_message_text(
                    chat_id=admin_chat, message_id=status.message_id,
                    text=f"📢 Broadcasting…\n{bar} {pct}%\n✅ {ok}  ⛔ {blocked}  ❌ {fail}")
            except TelegramError:
                pass
        await asyncio.sleep(0.05)

    save_users(users)
    s = load_stats()
    s["broadcasts"] = s.get("broadcasts", 0) + 1
    save_stats(s)

    rows = [
        ("👥 Target", str(len(targets))),
        ("✅ Delivered", str(ok)),
        ("⛔ Blocked", str(blocked)),
        ("❌ Failed", str(fail)),
        ("⏱ Time", f"{time.time() - t0:.1f}s"),
    ]
    await context.bot.edit_message_text(
        chat_id=admin_chat, message_id=status.message_id,
        text="✅ <b>BROADCAST DONE</b>\n━━━━━━━━━━━━━━━━━━━━━━\n<pre>"
             + esc(render_table(rows, "📢 REPORT")) + "</pre>",
        parse_mode=ParseMode.HTML)
    AWAITING_BROADCAST[update.effective_user.id] = False


async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    users = load_users()
    rows = [
        ("👥 Total", str(len(users))),
        ("✅ Active", str(sum(1 for u in users.values() if u.get("lookups", 0) > 0))),
        ("🚫 Blocked", str(sum(1 for u in users.values() if u.get("banned")))),
    ]
    await update.message.reply_text(
        "<pre>" + esc(render_table(rows, "👥 USERS")) + "</pre>",
        parse_mode=ParseMode.HTML)


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    users = load_users()
    path = DATA_DIR / f"users_export_{int(time.time())}.json"
    path.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")
    with path.open("rb") as f:
        await update.message.reply_document(f, filename=path.name,
                                            caption=f"👥 {len(users)} users")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    s = load_stats()
    rows = [
        ("👥 Users", str(len(load_users()))),
        ("🔍 Lookups", str(s.get("total_lookups", 0))),
        ("❌ No Result", str(s.get("no_result", 0))),
        ("📢 Broadcasts", str(s.get("broadcasts", 0))),
    ]
    await update.message.reply_text(
        "<pre>" + esc(render_table(rows, "📊 STATS")) + "</pre>",
        parse_mode=ParseMode.HTML)


async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: <code>/ban 123456789</code>",
                                        parse_mode=ParseMode.HTML)
        return
    users = load_users()
    k = context.args[0].strip()
    if k not in users:
        await update.message.reply_text("❌ User nahi mila.")
        return
    users[k]["banned"] = not users[k].get("banned", False)
    save_users(users)
    await update.message.reply_text(
        f"User <code>{k}</code> {'🚫 banned' if users[k]['banned'] else '✅ unbanned'}.",
        parse_mode=ParseMode.HTML)


# ══════════════════════════════════════════════════════════════════════════
#  ERRORS
# ══════════════════════════════════════════════════════════════════════════
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("handler error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                update.effective_chat.id,
                f"⚠️ Error: <code>{esc(context.error)}</code>",
                parse_mode=ParseMode.HTML)
        except TelegramError:
            pass


# ══════════════════════════════════════════════════════════════════════════
#  APP BUILDER
# ══════════════════════════════════════════════════════════════════════════
async def post_init(app: Application) -> None:
    cmds = [BotCommand("start", "Start / Menu"), BotCommand("menu", "Menu")]
    cmds += [BotCommand(ep, ENDPOINTS[ep]["title"]) for ep in ENDPOINTS]
    cmds += [BotCommand("id", "My ID"), BotCommand("cancel", "Cancel")]
    if ADMIN_IDS:
        cmds += [BotCommand("admin", "Admin panel"),
                 BotCommand("broadcast", "Broadcast")]
    await app.bot.set_my_commands(cmds)


def build_app(token: str) -> Application:
    app = (Application.builder()
           .token(token)
           .post_init(post_init)
           .concurrent_updates(True)
           .read_timeout(30)
           .write_timeout(30)
           .build())

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("stats", cmd_stats_user))

    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("ban", cmd_ban))

    for ep in ENDPOINTS:
        app.add_handler(CommandHandler(ep, make_lookup_command(ep)))

    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL)
        & ~filters.COMMAND, text_router))

    app.add_error_handler(on_error)
    return app


# ══════════════════════════════════════════════════════════════════════════
#  MAIN  ·  dono bots ek hi process mein
# ══════════════════════════════════════════════════════════════════════════
async def _run_bots() -> None:
    apps = [build_app(t) for t in BOT_TOKENS]

    for app in apps:
        await app.initialize()
        await app.start()
        if app.updater:
            await app.updater.start_polling(allowed_updates=Update.ALL_TYPES,
                                            drop_pending_updates=True,
                                            poll_interval=1.0)
        me = await app.bot.get_me()
        log.info("✅ bot online: @%s (id=%s)", me.username, me.id)

    log.info("all %d bots running | channel=%s | credit=%s",
             len(apps), CHANNEL_AT, CREDIT)

    try:
        await asyncio.Event().wait()
    finally:
        for app in apps:
            if app.updater and app.updater.running:
                await app.updater.stop()
            await app.stop()
            await app.shutdown()


def main() -> None:
    log.info("starting %s | bots=%d | admins=%s",
             BOT_NAME, len(BOT_TOKENS), sorted(ADMIN_IDS))
    try:
        asyncio.run(_run_bots())
    except (KeyboardInterrupt, SystemExit):
        log.info("shutdown")


if __name__ == "__main__":
    main()