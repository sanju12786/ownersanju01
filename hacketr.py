#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║  FTOSINT + FAMILY ID  —  TELEGRAM OSINT BOT                      ║
║  Single-message output  •  Admin panel se sab editable           ║
║  Termux / VPS / Replit — kahin bhi chalega                       ║
║  Buy @thehiddenreserve  •  By @thehiddenreserve                  ║
╚══════════════════════════════════════════════════════════════════╝

INSTALL:
    pip install "python-telegram-bot>=21" httpx

RUN:
    python bot.py
"""

import asyncio
import html
import json
import logging
import math
import os
import signal
import sys
import time
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ChatType, ParseMode
from telegram.error import Conflict, NetworkError, TelegramError, TimedOut
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ════════════════════════════════════════════════════════════════════
#  ░░ 1. CONFIG  ░░
# ════════════════════════════════════════════════════════════════════

BOT_TOKEN = os.getenv("BOT_TOKEN", "8036729272:AAFSzpvCKk2y6dLIOUS1irB1BK23_RPD7oQ")
CHAT_ID   = os.getenv("CHAT_ID", "5574675470")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "5574675470").split(",")]

DATA_FILE  = "botdata.json"
LOCK_FILE  = "bot.lock"
HTTP_TIMEOUT = 45
MSG_LIMIT  = 3900          # ek message ki safe limit
SEP        = "━" * 18
DIVIDER    = "─" * 30

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("osint-bot")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext.Updater").setLevel(logging.WARNING)

# ════════════════════════════════════════════════════════════════════
#  ░░ 2. DEFAULTS  ░░
# ════════════════════════════════════════════════════════════════════

DEFAULT_SETTINGS: Dict[str, Any] = {
    "ft_key":   "cobra-limited-land",
    "ft_base":  "https://ftosint.world/api",
    "fam_key":  "Navratri",
    "fam_base": "https://sahilxher.madewith.me/api",
    "buy_line": "🛒 Buy @thehiddenreserve",
    "by_line":  "👨‍💻 By @thehiddenreserve",
    "disclaimer": "⚠️ Educational use only\n🚫 Misuse is illegal\n📜 User is responsible",
    "max_rows": 5,
    "max_val":  200,
    "file_mode": False,
}

SETTING_SPECS: Dict[str, Tuple[str, str]] = {
    "ft_key":   ("🔑 FTOSINT API Key", "ftosint.world ka key"),
    "ft_base":  ("🌐 FTOSINT Base URL", "jaise https://ftosint.world/api"),
    "fam_key":  ("🔑 Family API Key", "family api ka key"),
    "fam_base": ("🌐 Family Base URL", "jaise https://site.com/api"),
    "buy_line": ("🛒 Buy Line", "result footer me dikhta hai"),
    "by_line":  ("👨‍💻 Credit Line", "result footer me dikhta hai"),
    "disclaimer": ("⚠️ Disclaimer", "footer ka disclaimer text"),
    "max_rows": ("📄 Max Records", "ek result me kitne record"),
    "max_val":  ("✂️ Max Value Length", "lambe value truncate honge"),
}

# ════════════════════════════════════════════════════════════════════
#  ░░ 3. STORAGE  ░░
# ════════════════════════════════════════════════════════════════════

class Store:
    def __init__(self, path: str = DATA_FILE):
        self.path = path
        self.users: Dict[str, dict] = {}
        self.channels: List[str] = ["@Sanjuownersmm"]
        self.settings: Dict[str, Any] = dict(DEFAULT_SETTINGS)
        self.lookups: Dict[str, dict] = {}          # admin overrides / custom
        self.stats: Dict[str, int] = {"lookups": 0, "errors": 0, "joins": 0}
        self.errors: List[dict] = []
        self.load()

    # ── io ────────────────────────────────────────────────────────
    def load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.users = d.get("users", {})
            self.channels = d.get("channels", self.channels)
            self.settings = {**DEFAULT_SETTINGS, **d.get("settings", {})}
            self.lookups = d.get("lookups", {})
            self.stats = {**self.stats, **d.get("stats", {})}
            self.errors = d.get("errors", [])[-50:]
        except Exception as e:                                   # noqa
            log.warning("Store load fail: %s", e)

    def save(self) -> None:
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({
                    "users": self.users,
                    "channels": self.channels,
                    "settings": self.settings,
                    "lookups": self.lookups,
                    "stats": self.stats,
                    "errors": self.errors[-50:],
                }, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception as e:                                   # noqa
            log.warning("Store save fail: %s", e)

    # ── users ─────────────────────────────────────────────────────
    def add_user(self, u) -> bool:
        uid = str(u.id)
        new = uid not in self.users
        if new:
            self.stats["joins"] += 1
        self.users[uid] = {
            "id": u.id,
            "name": u.full_name,
            "username": u.username or "",
            "first_seen": self.users.get(uid, {}).get("first_seen", datetime.utcnow().isoformat()),
            "lookups": self.users.get(uid, {}).get("lookups", 0),
        }
        self.save()
        return new

    def bump(self, uid: int, key: str = "lookups") -> None:
        self.stats[key] = self.stats.get(key, 0) + 1
        u = self.users.get(str(uid))
        if u:
            u["lookups"] = u.get("lookups", 0) + 1
        self.save()

    def log_error(self, entry: dict) -> None:
        self.stats["errors"] += 1
        self.errors.append({**entry, "at": datetime.utcnow().isoformat()})
        self.errors = self.errors[-50:]
        self.save()


STORE = Store()


def CFG(key: str) -> Any:
    return STORE.settings.get(key, DEFAULT_SETTINGS.get(key))


def max_rows() -> int:
    try:
        return max(1, int(CFG("max_rows")))
    except Exception:                                            # noqa
        return 5


def max_val() -> int:
    try:
        return max(40, int(CFG("max_val")))
    except Exception:                                            # noqa
        return 200

# ════════════════════════════════════════════════════════════════════
#  ░░ 4. LOOKUP REGISTRY (built-in)  ░░
#  fields = [(emoji, Label, json.path), ...]
# ════════════════════════════════════════════════════════════════════

BUILTIN: Dict[str, dict] = {
    "number": dict(
        icon="📞", title="NUMBER INFO", sub="Number Database", cat="num", auth="ft",
        ep="number", param="num", kind="records", count_key="total",
        hint="10 digit mobile number bhejo\n<i>Example: 9876543210</i>",
        fields=[("📲", "Number", "mobile"), ("👤", "Name", "name"),
                ("👥", "Father", "fname"), ("📞", "Alt Num", "alt"),
                ("🔎", "Circle", "circle"), ("🏡", "Address", "address"),
                ("💳", "Id", "id"), ("📧", "Email", "email")],
    ),
    "numleak": dict(
        icon="🔎", title="NUMBER LEAK", sub="HiTeck + ICMR Database", cat="num", auth="ft",
        ep="numleak", param="num", kind="custom",
        hint="Mobile number bhejo\n<i>Example: 9876543210</i>",
    ),
    "address": dict(
        icon="📍", title="ADDRESS LOOKUP", sub="Address Database", cat="num", auth="ft",
        ep="address", param="address", kind="records", count_key="total",
        hint="Address ya area ka naam bhejo\n<i>Example: Okhla Delhi</i>",
        fields=[("👤", "Name", "name"), ("📲", "Mobile", "mobile"),
                ("📞", "Alt Num", "alternate"), ("👥", "Father", "father_name"),
                ("🏡", "Address", "address"), ("💳", "Aadhaar", "aadhar"),
                ("🔎", "Circle", "circle")],
    ),
    "nametoinfo": dict(
        icon="👤", title="NAME TO INFO", sub="Name Database", cat="num", auth="ft",
        ep="nametoinfo", param="name", kind="records", count_key="total",
        hint="Naam bhejo\n<i>Example: RAHUL</i>",
        fields=[("👤", "Name", "name"), ("📲", "Mobile", "mobile"),
                ("👥", "Father", "father_name"), ("🏡", "Address", "address"),
                ("💳", "Aadhaar", "aadhar"), ("🔎", "Circle", "circle"),
                ("📞", "Alt Num", "alternate")],
    ),
    "namesearch": dict(
        icon="👤", title="NAME SEARCH", sub="Name + Place Database", cat="num", auth="ft",
        ep="namesearch", param="q", extra_param="from", kind="records", count_key="total",
        hint="<b>Naam,Sheher</b> format me bhejo\n<i>Example: Ramesh,Delhi</i>",
        fields=[("👤", "Name", "name"), ("📲", "Mobile", "mobile"),
                ("👥", "Father", "father_name"), ("🏡", "Address", "address"),
                ("💳", "Aadhaar", "aadhar"), ("🔎", "Circle", "circle"),
                ("📞", "Alt Num", "alternate")],
    ),

    "vehicle": dict(
        icon="🚗", title="VEHICLE TO OWNER", sub="RC Database", cat="veh", auth="ft",
        ep="vehicle", param="vehicle", kind="object",
        hint="Registration number bhejo\n<i>Example: KA01AB1234</i>",
        fields=[("🚗", "Reg No", "regNo"), ("👤", "Owner", "owner"),
                ("👥", "Father", "ownerFatherName"), ("🚙", "Model", "vehicle"),
                ("🏭", "Maker", "manufacturer"), ("🔧", "Variant", "variant"),
                ("📋", "Class", "vehicleClass"), ("⛽", "Fuel", "fuelType"),
                ("📅", "Reg Date", "regDate"), ("🏢", "RTO", "regAuthority"),
                ("🔩", "Chassis", "chassis"), ("⚙️", "Engine", "engine"),
                ("🛡", "Insurer", "insuranceCompanyName"), ("🧾", "Policy No", "insurancePolicyNumber"),
                ("🛡", "Insurance Upto", "insuranceUpto"), ("🏦", "Financier", "financerName"),
                ("📮", "Pincode", "pincode"), ("📌", "Status", "status")],
    ),
    "veh2num": dict(
        icon="🚗", title="VEHICLE TO MOBILE", sub="RC Mobile Database", cat="veh", auth="ft",
        ep="veh2num", param="vehicle", kind="object",
        hint="Registration number bhejo\n<i>Example: KL41V3504</i>",
        fields=[("🚗", "Vehicle", "vehicle"), ("👤", "Owner", "owner_name"),
                ("📲", "Mobile", "mobile_number"), ("🔩", "Chassis", "chassis_number"),
                ("⚙️", "Engine", "engine_number")],
    ),
    "fastag": dict(icon="🏷", title="FASTAG LOOKUP", sub="FASTag Database", cat="veh",
                   auth="ft", ep="fastag", param="vehicle", kind="custom",
                   hint="Registration number bhejo\n<i>Example: KA01AB1234</i>"),
    "challan": dict(icon="🧾", title="CHALLAN LOOKUP", sub="Challan Database", cat="veh",
                    auth="ft", ep="challan", param="vehicle", kind="custom",
                    hint="Registration number bhejo\n<i>Example: KA01AB1234</i>"),
    "rcpdf": dict(icon="📄", title="RC PDF", sub="RC Document", cat="veh", auth="ft",
                  ep="rcpdf", param="vehicle", kind="text",
                  hint="Registration number bhejo\n<i>Example: KA01AB1234</i>"),
    "rcchip": dict(icon="📄", title="RC PDF CHIP", sub="RC Document", cat="veh", auth="ft",
                   ep="rcchip", param="vehicle", kind="text",
                   hint="Registration number bhejo\n<i>Example: KA01AB1234</i>"),
    "vinfo": dict(icon="📘", title="RC DETAILS", sub="VInfo Database", cat="veh", auth="ft",
                  ep="vinfo", param="reg", kind="custom",
                  hint="Registration number bhejo\n<i>Example: MH16BZ7090</i>"),
    "puc": dict(icon="🌿", title="PUC CERTIFICATE", sub="PUC Document", cat="veh", auth="ft",
                ep="puc", param="reg", kind="text",
                hint="Registration number bhejo\n<i>Example: MH16BZ7090</i>"),
    "hw": dict(icon="⚙️", title="CHASSIS / ENGINE", sub="Hardware Database", cat="veh", auth="ft",
               ep="hw", param="chasi", kind="custom",
               hint="Chassis ya engine number bhejo\n<i>Example: MA3NYFB1SKD530868</i>"),
    "hpt": dict(icon="📝", title="HP / FINANCIER", sub="Hypothecation Database", cat="veh",
                auth="ft", ep="hpt", param="reg", kind="custom",
                hint="Registration number bhejo\n<i>Example: KA01AB1234</i>"),
    "vehindex": dict(icon="📋", title="VEHICLE INDEX", sub="Index Database", cat="veh", auth="ft",
                     ep="vehindex", param="reg", kind="records", count_key="total",
                     hint="Registration number bhejo\n<i>Example: MH16BZ7090</i>",
                     fields=[("🚗", "Reg No", "reg"), ("🔩", "Chassis", "chassis"),
                             ("⚙️", "Engine", "engine"), ("📌", "Index", "ok")]),

    "aadhar": dict(
        icon="🆔", title="AADHAAR LOOKUP", sub="Aadhaar Database", cat="idn", auth="ft",
        ep="aadhar", param="num", kind="records", count_key="total",
        hint="12 digit Aadhaar number bhejo\n<i>Example: 393933081942</i>",
        fields=[("👤", "Name", "name"), ("📲", "Mobile", "mobile"),
                ("👥", "Father", "father_name"), ("🏡", "Address", "address"),
                ("🔎", "Circle", "circle"), ("💳", "Aadhaar", "aadhar")],
    ),
    "family": dict(icon="👨‍👩‍👧", title="FAMILY ID", sub="Family Database", cat="idn",
                   auth="fam", ep="family", param="term", kind="custom",
                   hint="Aadhaar / Family ID bhejo\n<i>Example: 701984830542</i>"),
    "pan": dict(icon="🪪", title="PAN TO GST", sub="GST Database", cat="idn", auth="ft",
                ep="pan", param="pan", kind="records", count_key="total",
                hint="PAN number bhejo\n<i>Example: ABCDE1234F</i>",
                fields=[("🧾", "GSTIN", "gstin"), ("📌", "Auth Status", "auth_status"),
                        ("📍", "State", "state")]),
    "paninfo": dict(
        icon="🪪", title="PAN INFO", sub="PAN Database", cat="idn", auth="ft",
        ep="paninfo", param="pan", kind="object",
        hint="PAN number bhejo\n<i>Example: BNZPM2501F</i>",
        fields=[("🪪", "PAN", "pan"), ("👤", "Full Name", "customerName"),
                ("🔤", "First", "firstName"), ("🔤", "Middle", "middleName"),
                ("🔤", "Last", "lastName"), ("📅", "DOB", "dob"),
                ("📌", "Status", "panStatus")],
    ),
    "pantogstin": dict(
        icon="🪪", title="PAN TO GSTIN", sub="GST Database", cat="idn", auth="ft",
        ep="pantogstin", param="pan", kind="records", count_key="total",
        hint="PAN number bhejo\n<i>Example: ANXPV7978A</i>",
        fields=[("🧾", "GSTIN", "gstin"), ("🏢", "Legal Name", "lgnm"),
                ("🏪", "Trade Name", "tradeNam"), ("📌", "Status", "sts"),
                ("🏭", "Type", "ctb"), ("📋", "Duty", "dty"),
                ("📅", "Reg Date", "rgdt"), ("🏡", "Address", "pradr.address")],
    ),
    "gstin": dict(
        icon="🧾", title="GSTIN INFO", sub="GST Database", cat="idn", auth="ft",
        ep="gstin", param="gstin", kind="object",
        hint="GSTIN bhejo\n<i>Example: 07AABCF8078M1Z3</i>",
        fields=[("🧾", "GSTIN", "gstin"), ("🏢", "Legal Name", "lgnm"),
                ("🏪", "Trade Name", "tradeNam"), ("📌", "Status", "sts"),
                ("🏭", "Entity", "ctb"), ("📋", "Duty", "dty"),
                ("📅", "Reg Date", "rgdt"), ("🕒", "Last Update", "lstupdt"),
                ("⚖️", "State Juris", "stj"), ("⚖️", "Central Juris", "ctj"),
                ("📧", "E-Invoice", "einvoiceStatus"), ("🏡", "Address", "pradr.address")],
    ),
    "name2gstin": dict(
        icon="🔎", title="NAME TO GSTIN", sub="GST Database", cat="idn", auth="ft",
        ep="name2gstin", param="name", kind="records", count_key="total",
        hint="Company / firm ka naam bhejo\n<i>Example: FLIPKART</i>",
        fields=[("🧾", "GSTIN", "gstin"), ("🏢", "Company", "company"),
                ("🏪", "Trade Name", "trade_name"), ("📌", "Status", "status"),
                ("🏭", "Entity", "entity_type"), ("📋", "Business", "business_type"),
                ("📅", "Reg Date", "registration_date"), ("⚖️", "Jurisdiction", "jurisdiction"),
                ("🏡", "Address", "address")],
    ),
    "gstin2pan": dict(icon="🔄", title="GSTIN TO PAN", sub="PAN Database", cat="idn", auth="ft",
                      ep="gstin2pan", param="gstin", kind="object",
                      hint="GSTIN bhejo\n<i>Example: 07AABCF8078M1Z3</i>",
                      fields=[("🧾", "GSTIN", "gstin"), ("🪪", "PAN", "pan"),
                              ("📍", "State", "state")]),
    "gstreturns": dict(
        icon="🧾", title="GST RETURNS", sub="Returns Database", cat="idn", auth="ft",
        ep="gstreturns", param="gstin", extra_param="financial_year", kind="records",
        count_key="total_returns",
        hint="<b>GSTIN,FY</b> bhejo\n<i>Example: 07AABCF8078M1Z3,2023-24</i>",
        fields=[("📄", "Return", "return_type"), ("📅", "Period", "return_period"),
                ("🕒", "Filed On", "date_of_filing"), ("📌", "Status", "status"),
                ("🔖", "ARN", "arn"), ("📮", "Mode", "mode_of_filing")],
    ),
    "voter": dict(icon="🗳", title="VOTER ID LOOKUP", sub="Voter Database", cat="idn",
                  auth="ft", ep="voter", param="id", kind="custom",
                  hint="EPIC number bhejo\n<i>Example: ZNO1150077</i>"),

    "pincode": dict(icon="📍", title="PINCODE INFO", sub="Postal Database", cat="utl",
                    auth="ft", ep="pincode", param="pin", kind="custom",
                    hint="6 digit pincode bhejo\n<i>Example: 110001</i>"),
    "ifsc": dict(icon="🏦", title="IFSC INFO", sub="Bank Database", cat="utl", auth="ft",
                 ep="ifsc", param="ifsc", kind="custom",
                 hint="IFSC code bhejo\n<i>Example: SBIN0001234</i>"),
}

CATEGORIES: List[Tuple[str, str]] = [
    ("num", "📞 Number & Leak"),
    ("veh", "🚗 Vehicle & RC"),
    ("idn", "🪪 Identity & GST"),
    ("utl", "📍 Utility"),
]


def all_lookups() -> Dict[str, dict]:
    """built-in + admin overrides (deleted hatakar)."""
    d: Dict[str, dict] = {}
    for k, v in BUILTIN.items():
        ov = STORE.lookups.get(k)
        if ov and ov.get("deleted"):
            continue
        d[k] = {**v, **(ov or {})}
    for k, v in STORE.lookups.items():
        if k in BUILTIN or v.get("deleted"):
            continue
        d[k] = v
    return d


def cats_with_items() -> List[Tuple[str, str, List[str]]]:
    lk = all_lookups()
    out = []
    for cid, title in CATEGORIES:
        ids = [k for k, v in lk.items() if v.get("cat") == cid]
        if ids:
            out.append((cid, title, ids))
    extra = sorted({v.get("cat") for v in lk.values()} - {c[0] for c in CATEGORIES})
    for cid in extra:
        if not cid:
            continue
        ids = [k for k, v in lk.items() if v.get("cat") == cid]
        if ids:
            out.append((cid, f"📂 {cid}", ids))
    return out

# ════════════════════════════════════════════════════════════════════
#  ░░ 5. STYLING HELPERS  ░░
# ════════════════════════════════════════════════════════════════════

_SMALL = {
    "a": "ᴀ", "b": "ʙ", "c": "ᴄ", "d": "ᴅ", "e": "ᴇ", "f": "ꜰ", "g": "ɢ", "h": "ʜ",
    "i": "ɪ", "j": "ᴊ", "k": "ᴋ", "l": "ʟ", "m": "ᴍ", "n": "ɴ", "o": "ᴏ", "p": "ᴘ",
    "q": "ǫ", "r": "ʀ", "s": "ꜱ", "t": "ᴛ", "u": "ᴜ", "v": "ᴠ", "w": "ᴡ", "x": "x",
    "y": "ʏ", "z": "ᴢ",
}


def sc(t: Any) -> str:
    return "".join(_SMALL.get(c, c) for c in str(t))


def bs(t: Any) -> str:
    out = []
    for ch in str(t):
        o = ord(ch)
        if 65 <= o <= 90:
            out.append(chr(0x1D5D4 + o - 65))
        elif 97 <= o <= 122:
            out.append(chr(0x1D5EE + o - 97))
        elif 48 <= o <= 57:
            out.append(chr(0x1D7EC + o - 48))
        else:
            out.append(ch)
    return "".join(out)


def vlen(s: str) -> int:
    n = 0
    for ch in str(s):
        n += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return n


def esc(t: Any) -> str:
    return html.escape(str(t), quote=False)


def trunc(s: Any, n: Optional[int] = None) -> str:
    n = n or max_val()
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def clean(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, (list, tuple)):
        v = ", ".join(str(x) for x in v)
    if isinstance(v, dict):
        v = ", ".join(f"{k}:{x}" for k, x in v.items())
    s = str(v).strip()
    return "-" if s.lower() in ("", "n/a", "na", "null", "none", "nil", "-") else s


def get_path(d: Any, path: str, default: str = "-") -> str:
    cur = d
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return default
        if cur is None:
            return default
    return clean(cur)


SKIP_KEYS = {"success", "by", "response_time_ms", "cached", "cached_at",
             "api", "usage", "_text", "message"}


def pre(t: str) -> str:
    return f"<pre>{t}</pre>"


def make_header(lk: dict, query: str, total: Optional[int] = None,
                pages: int = 1, page: int = 1) -> str:
    lines = [
        f"{lk.get('icon', '🔍')} {bs(lk.get('title', 'LOOKUP'))}",
        "",
        f"{sc(lk.get('sub', 'Database'))} ✅",
        "",
        f"🔭 {sc('Query')} : {esc(trunc(query, 60))}",
    ]
    if total is not None:
        lines.append(f"✍️ {sc('Records')} : {total} | {sc('Page')} {page}/{pages}")
    return "\n".join(lines)


def rows_cols(rows: List[Tuple[str, str, Any]]) -> str:
    if not rows:
        return ""
    keys = [f"{e} {sc(l)}" for e, l, _ in rows]
    width = max(vlen(k) for k in keys) + 1
    out = []
    for (e, l, v), k in zip(rows, keys):
        pad = " " * max(1, width - vlen(k))
        out.append(f"{k}{pad}: {esc(trunc(clean(v)))}")
    return "\n".join(out)


def record_blocks(records: List[dict], fields: List[Tuple[str, str, str]],
                  total: int, max_rec: int) -> List[str]:
    blocks = []
    for i, r in enumerate(records[:max_rec], 1):
        blocks.append(pre("\n".join([
            SEP, f"📰 {sc('Record')} {i}/{total}", SEP, "",
            rows_cols([(e, l, get_path(r, p)) for e, l, p in fields]),
        ])))
    return blocks


def auto_rows(obj: dict, depth: int = 0) -> List[Tuple[str, str, Any]]:
    rows: List[Tuple[str, str, Any]] = []
    for k, v in obj.items():
        if k in SKIP_KEYS:
            continue
        label = k.replace("_", " ").strip().title()
        if isinstance(v, dict) and depth < 1:
            for k2, v2 in v.items():
                if isinstance(v2, (dict, list)):
                    continue
                rows.append(("▫️", f"{label} · {k2.replace('_', ' ').title()}", v2))
        else:
            rows.append(("▪️", label, v))
    return rows


def auto_block(obj: dict) -> str:
    return pre(rows_cols(auto_rows(obj)))


def extract_records(payload: Any) -> List[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for k in ("results", "records", "data", "members", "family", "list", "rows", "items"):
        v = payload.get(k)
        if isinstance(v, list) and v:
            return [x for x in v if isinstance(x, dict)]
        if isinstance(v, dict):
            for k2 in ("results", "records", "members", "family", "list", "rows"):
                v2 = v.get(k2)
                if isinstance(v2, list) and v2:
                    return [x for x in v2 if isinstance(x, dict)]
    return []


def footer(elapsed: float) -> str:
    return (
        f"⏱ <code>{elapsed:.2f}s</code>\n{DIVIDER}\n"
        f"{CFG('buy_line')}\n{CFG('by_line')}\n{DIVIDER}\n"
        f"⚠️ <b>DISCLAIMER</b>\n{CFG('disclaimer')}"
    )

# ════════════════════════════════════════════════════════════════════
#  ░░ 6. CUSTOM PARSERS (list[str] chunks)  ░░
# ════════════════════════════════════════════════════════════════════

def p_numleak(p: dict) -> List[str]:
    chunks: List[str] = []
    for ckey, name in (("chain", "HiTeckGroop"), ("icmr", "ICMR 2025")):
        ch = p.get(ckey) or {}
        recs = ch.get("records") or []
        if not recs:
            continue
        chunks.append(pre(f"{SEP}\n◆ {bs(ch.get('title', name))} — {len(recs)} {sc('records')}\n{SEP}"))
        if "FullName" in recs[0]:
            fields = [("📲", "Phone", "Phone"), ("👤", "Name", "FullName"),
                      ("👥", "Father", "FatherName"), ("💳", "Doc/Aadhaar", "DocumentNumber"),
                      ("🏡", "Address", "Adres")]
        else:
            fields = [("👤", "Name", "name"), ("🎂", "Age", "age"),
                      ("⚧", "Gender", "gender"), ("🏙", "District", "district"),
                      ("📍", "State", "state"), ("📲", "Phone", "phone")]
        chunks += record_blocks(recs, fields, len(recs), min(4, max_rows()))
    return chunks or [pre("❌ Koi record nahi mila.")]


def p_fastag(p: dict) -> List[str]:
    if p.get("success") is False:
        return [pre(f"❌ {esc(p.get('error', 'No record'))}")]
    return [auto_block({k: v for k, v in p.items() if k not in SKIP_KEYS})]


def p_challan(p: dict) -> List[str]:
    if p.get("success") is False and not extract_records(p):
        return [pre(f"❌ {esc(p.get('error', 'No challan'))}")]
    recs = extract_records(p)
    if recs:
        keys: List[str] = []
        for r in recs[:5]:
            for k, v in r.items():
                if k not in keys and not isinstance(v, (dict, list)):
                    keys.append(k)
        fields = [("▪️", k.replace("_", " ").title(), k) for k in keys[:8]]
        return record_blocks(recs, fields, len(recs), max_rows())
    return [auto_block({k: v for k, v in p.items() if k not in SKIP_KEYS})]


def p_vinfo(p: dict) -> List[str]:
    d = p.get("data") or {}
    cust = d.get("customer_details") or {}
    sg = (d.get("meta_data", {}).get("signzy_response", {}) or {}).get("result", {}) or {}
    return [pre(rows_cols([
        ("🚗", "Reg No", d.get("registration_number") or p.get("reg")),
        ("👤", "Owner", cust.get("full_name")),
        ("🔩", "Chassis", d.get("chassis_number")),
        ("⚙️", "Engine", d.get("engine_number")),
        ("🏡", "Address", (cust.get("communication_address") or {}).get("address_line")),
        ("📅", "Reg Date", d.get("registration_date")),
        ("🏢", "RTO", sg.get("regAuthority")),
        ("🚙", "Model", sg.get("model")),
        ("⛽", "Fuel", sg.get("type")),
        ("🛡", "Insurance Upto", sg.get("vehicleInsuranceUpto")),
        ("🌿", "PUCC Upto", sg.get("puccUpto")),
        ("📌", "Status", sg.get("status")),
    ]))]


def p_hw(p: dict) -> List[str]:
    veh = (p.get("vehicles") or [{}])[0]
    cust = veh.get("customer_details") or {}
    res = (veh.get("meta_data", {}).get("signzy_response", {}) or {}).get("result", {}) or {}
    return [pre(rows_cols([
        ("🚗", "Reg No", p.get("reg")),
        ("🔎", "Matched By", p.get("matched_by")),
        ("👤", "Owner", cust.get("full_name") or res.get("owner")),
        ("🔩", "Chassis", veh.get("chassis_number") or res.get("chassis")),
        ("⚙️", "Engine", veh.get("engine_number") or res.get("engine")),
        ("🚙", "Model", res.get("model")),
        ("⛽", "Fuel", res.get("type")),
        ("📅", "Reg Date", res.get("regDate")),
        ("🏢", "RTO", res.get("regAuthority")),
        ("📌", "Status", res.get("status")),
        ("🏭", "VIN Maker", (p.get("vin") or {}).get("manufacturer")),
        ("📆", "VIN Year", (p.get("vin") or {}).get("model_year")),
    ]))]


def p_hpt(p: dict) -> List[str]:
    if p.get("success") is False:
        return [pre(f"❌ {esc(p.get('error', 'Provider unavailable'))}")]
    return [auto_block({k: v for k, v in p.items() if k not in SKIP_KEYS})]


def p_voter(p: dict) -> List[str]:
    recs = extract_records(p)
    if not recs:
        return [pre("❌ Koi voter record nahi mila.")]
    c = recs[0].get("content") or recs[0]
    return [pre(rows_cols([
        ("🎫", "EPIC No", c.get("epicNumber")),
        ("👤", "Name", c.get("fullName") or c.get("applicantFirstName")),
        ("🔤", "Name (Local)", c.get("fullNameL1")),
        ("👥", "Relation", c.get("relationName")),
        ("🔗", "Relation Type", c.get("relationType")),
        ("🎂", "Age", c.get("age")),
        ("⚧", "Gender", c.get("gender")),
        ("🏛", "Assembly", c.get("asmblyName")),
        ("🏛", "Parliament", c.get("prlmntName")),
        ("🏙", "District", c.get("districtValue")),
        ("📍", "State", c.get("stateName")),
        ("🔢", "Part No", c.get("partNumber")),
        ("🏫", "Polling Station", c.get("psbuildingName")),
        ("🚪", "Room", c.get("psRoomDetails")),
        ("📌", "Status", "Active" if c.get("isActive") else "Inactive"),
    ]))]


def p_pincode(p: dict) -> List[str]:
    chunks = [pre(rows_cols([
        ("📮", "Pincode", p.get("pincode")), ("📍", "State", p.get("state")),
        ("🏙", "District", p.get("district")), ("🗺", "Division", p.get("division")),
        ("🌍", "Region", p.get("region")), ("🏳", "Country", p.get("country")),
        ("🏤", "Total Offices", p.get("total_offices")),
    ]))]
    offs = p.get("post_offices") or []
    if offs:
        chunks.append(pre(f"{SEP}\n🏤 {bs('POST OFFICES')} ({len(offs)})\n{SEP}"))
        fields = [("🏤", "Post Office", "name"), ("🏷", "Type", "branch_type"),
                  ("🚚", "Delivery", "delivery_status"), ("🏙", "District", "district")]
        chunks += record_blocks(offs, fields, len(offs), min(8, max_rows()))
    return chunks


def p_ifsc(p: dict) -> List[str]:
    b = p.get("bank") or {}
    br = p.get("branch") or {}
    cd = p.get("codes") or {}
    sv = p.get("services") or {}
    return [pre(rows_cols([
        ("🏦", "IFSC", p.get("ifsc")), ("🏢", "Bank", b.get("name")),
        ("🏷", "Category", b.get("category")), ("🏛", "HQ", b.get("headquarters")),
        ("🌐", "Website", b.get("website")), ("🔁", "SWIFT", b.get("swift_code")),
        ("🏤", "Branch", br.get("name")), ("🏡", "Address", br.get("full_address")),
        ("🏙", "City", br.get("city")), ("🏙", "District", br.get("district")),
        ("📍", "State", br.get("state")), ("📮", "Pincode", br.get("pincode")),
        ("🔢", "MICR", cd.get("micr")), ("📲", "UPI", cd.get("upi_id")),
        ("💸", "RTGS", sv.get("rtgs")), ("💸", "NEFT", sv.get("neft")),
        ("💸", "IMPS", sv.get("imps")), ("📲", "UPI Svc", sv.get("upi")),
    ]))]


def p_family(p: Any) -> List[str]:
    if isinstance(p, dict) and p.get("success") is False and not extract_records(p):
        return [pre(f"❌ {esc(p.get('error') or p.get('message') or 'No family record')}")]
    recs = extract_records(p)
    if recs:
        keys: List[str] = []
        for r in recs[:5]:
            for k, v in r.items():
                if k not in keys and not isinstance(v, (dict, list)):
                    keys.append(k)
        fields = [("👤", k.replace("_", " ").title(), k) for k in keys[:8]]
        chunks: List[str] = []
        meta = ""
        if isinstance(p, dict):
            for k in ("family_id", "ration_card", "head_name", "address", "state"):
                if p.get(k):
                    meta += f"▪️ {sc(k.replace('_', ' '))} : {esc(p[k])}\n"
        if meta:
            chunks.append(pre(meta.rstrip()))
        chunks += record_blocks(recs, fields, len(recs), max_rows())
        return chunks
    if isinstance(p, dict):
        return [auto_block({k: v for k, v in p.items() if k not in SKIP_KEYS})]
    return [pre(esc(str(p)))]


CUSTOM_PARSERS = {
    "numleak": p_numleak, "fastag": p_fastag, "challan": p_challan, "vinfo": p_vinfo,
    "hw": p_hw, "hpt": p_hpt, "voter": p_voter, "pincode": p_pincode,
    "ifsc": p_ifsc, "family": p_family,
}

# ════════════════════════════════════════════════════════════════════
#  ░░ 7. API CALLER  ░░
# ════════════════════════════════════════════════════════════════════

def resolve_base(lk: dict) -> str:
    if lk.get("url"):
        return str(lk["url"]).rstrip("/")
    auth = lk.get("auth", "ft")
    default = CFG("fam_base") if auth == "fam" else CFG("ft_base")
    return f"{str(lk.get('base') or default).rstrip('/')}/{lk.get('ep', '')}"


def build_url(lk: dict, value: str) -> Tuple[str, Dict[str, str]]:
    auth = lk.get("auth", "ft")
    key = CFG("fam_key") if auth == "fam" else CFG("ft_key")
    params = {"key": key, lk.get("param", "q"): value}
    if lk.get("extra_param"):
        parts = [x.strip() for x in value.split(",")]
        params[lk.get("param", "q")] = parts[0]
        params[lk["extra_param"]] = parts[1] if len(parts) > 1 else ""
    return resolve_base(lk), params


async def call_api(lk: dict, value: str) -> Tuple[bool, Any, float, str]:
    url, params = build_url(lk, value)
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as cx:
            r = await cx.get(url, params=params)
            el = time.time() - t0
            try:
                return True, r.json(), el, str(r.url)
            except Exception:                                    # noqa
                return True, {"_text": r.text}, el, str(r.url)
    except Exception as e:                                       # noqa
        return False, f"{type(e).__name__}: {e}", time.time() - t0, url

# ════════════════════════════════════════════════════════════════════
#  ░░ 8. KEYBOARDS  ░░
# ════════════════════════════════════════════════════════════════════

def main_menu_kb(is_adm: bool = False) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(t, callback_data=f"cat:{c}")] for c, t, _ in cats_with_items()]
    rows.append([InlineKeyboardButton("🆔 My ID", callback_data="myid"),
                 InlineKeyboardButton("📖 Help", callback_data="help")])
    rows.append([InlineKeyboardButton("⌨️ Commands", callback_data="commands"),
                 InlineKeyboardButton("ℹ️ About", callback_data="about")])
    if is_adm:
        rows.append([InlineKeyboardButton("👑 ADMIN PANEL", callback_data="adm:home")])
    return InlineKeyboardMarkup(rows)


def category_kb(cid: str) -> InlineKeyboardMarkup:
    lk = all_lookups()
    ids = [k for k, v in lk.items() if v.get("cat") == cid]
    rows = [[InlineKeyboardButton(f"{lk[i].get('icon','🔹')} {lk[i].get('title', i).title()}",
                                  callback_data=f"lk:{i}")] for i in ids]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="menu")])
    return InlineKeyboardMarkup(rows)


def join_kb(channels: List[str]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"📢 Join {c}", url=f"https://t.me/{c.lstrip('@')}")]
            for c in channels]
    rows.append([InlineKeyboardButton("✅ Joined — Verify", callback_data="checkjoin")])
    return InlineKeyboardMarkup(rows)


def admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Stats", callback_data="adm:stats"),
         InlineKeyboardButton("👥 Users", callback_data="adm:users")],
        [InlineKeyboardButton("🔑 API Keys & URL", callback_data="adm:keys"),
         InlineKeyboardButton("⚙️ Limits", callback_data="adm:limits")],
        [InlineKeyboardButton("🔧 Lookups Manage", callback_data="adm:lks"),
         InlineKeyboardButton("➕ Add Lookup", callback_data="adm:wiz")],
        [InlineKeyboardButton("📢 Channels", callback_data="adm:chs"),
         InlineKeyboardButton("🏷 Branding", callback_data="adm:brand")],
        [InlineKeyboardButton("🧾 Error Log", callback_data="adm:errs"),
         InlineKeyboardButton("🗑 Clear Errors", callback_data="adm:clrerr")],
        [InlineKeyboardButton("📣 Broadcast", callback_data="adm:bc"),
         InlineKeyboardButton("📎 File Mode: ON/OFF", callback_data="adm:file")],
        [InlineKeyboardButton("⬅️ Main Menu", callback_data="menu")],
    ])


def keys_kb() -> InlineKeyboardMarkup:
    rows = []
    for k, (name, _) in SETTING_SPECS.items():
        if k in ("max_rows", "max_val"):
            continue
        rows.append([InlineKeyboardButton(f"{name} — edit", callback_data=f"adm:set:{k}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="adm:home")])
    return InlineKeyboardMarkup(rows)


def limits_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📄 Max Records = {CFG('max_rows')}", callback_data="adm:set:max_rows")],
        [InlineKeyboardButton(f"✂️ Max Value Len = {CFG('max_val')}", callback_data="adm:set:max_val")],
        [InlineKeyboardButton("⬅️ Back", callback_data="adm:home")],
    ])


def brand_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Buy Line", callback_data="adm:set:buy_line")],
        [InlineKeyboardButton("👨‍💻 Credit Line", callback_data="adm:set:by_line")],
        [InlineKeyboardButton("⚠️ Disclaimer", callback_data="adm:set:disclaimer")],
        [InlineKeyboardButton("⬅️ Back", callback_data="adm:home")],
    ])


def lk_edit_kb(lid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏷 Title", callback_data=f"adm:lkf:{lid}:title"),
         InlineKeyboardButton("😀 Icon", callback_data=f"adm:lkf:{lid}:icon")],
        [InlineKeyboardButton("📝 Subtitle", callback_data=f"adm:lkf:{lid}:sub"),
         InlineKeyboardButton("📂 Category", callback_data=f"adm:lkf:{lid}:cat")],
        [InlineKeyboardButton("🌐 URL / Endpoint", callback_data=f"adm:lkf:{lid}:url"),
         InlineKeyboardButton("🔤 Param", callback_data=f"adm:lkf:{lid}:param")],
        [InlineKeyboardButton("🧩 Type", callback_data=f"adm:lkf:{lid}:kind"),
         InlineKeyboardButton("💡 Hint", callback_data=f"adm:lkf:{lid}:hint")],
        [InlineKeyboardButton("📋 Fields", callback_data=f"adm:lkf:{lid}:fields")],
        [InlineKeyboardButton("🗑 Delete", callback_data=f"adm:lkd:{lid}"),
         InlineKeyboardButton("⬅️ Back", callback_data="adm:lks")],
    ])

# ════════════════════════════════════════════════════════════════════
#  ░░ 9. FORCE JOIN  ░░
# ════════════════════════════════════════════════════════════════════

async def joined_all(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    for ch in STORE.channels:
        try:
            m = await context.bot.get_chat_member(ch, user_id)
            if m.status in ("left", "kicked"):
                return False
        except TelegramError as e:
            log.warning("join check fail %s: %s", ch, e)
    return True


async def gate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user or user.is_bot or is_admin(user.id):
        return True
    if await joined_all(context, user.id):
        return True
    txt = ("🔒 <b>Pehle Channel Join Karo!</b>\n\n"
           "Join karne ke baad <b>✅ Joined — Verify</b> dabao.")
    kb = join_kb(STORE.channels)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await update.effective_message.reply_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
    return False

# ════════════════════════════════════════════════════════════════════
#  ░░ 10. ERROR REPORT  ░░
# ════════════════════════════════════════════════════════════════════

async def report_error(context: ContextTypes.DEFAULT_TYPE, user, lk: dict,
                       value: str, err: str, url: str) -> None:
    STORE.log_error({"lookup": lk.get("ep", "?"), "value": value,
                     "error": err[:600], "user": getattr(user, "id", 0)})
    msg = ("🚨 <b>API ERROR</b>\n"
           f"👤 {esc(getattr(user, 'full_name', '?'))} | <code>{getattr(user, 'id', 0)}</code>\n"
           f"🔗 <code>{esc(lk.get('title', '?'))}</code> → <code>{esc(value)}</code>\n"
           f"🌐 <code>{esc(url)}</code>\n📄 <code>{esc(err[:400])}</code>")
    targets = list(ADMIN_IDS)
    try:
        if CHAT_ID:
            targets.append(int(CHAT_ID))
    except ValueError:
        pass
    for t in set(targets):
        try:
            await context.bot.send_message(t, msg, parse_mode=ParseMode.HTML)
        except TelegramError:
            pass

# ════════════════════════════════════════════════════════════════════
#  ░░ 11. RESULT BUILDER (single message)  ░░
# ════════════════════════════════════════════════════════════════════

def build_result(lk: dict, payload: Any, value: str, elapsed: float,
                 max_rec: int) -> Tuple[str, bool]:
    """Return (text, trimmed?)."""
    chunks: List[str] = []
    trimmed = False

    if lk.get("kind") == "text" or (isinstance(payload, dict) and payload.get("_text")):
        body = payload.get("_text", "") if isinstance(payload, dict) else str(payload)
        chunks.append(pre(make_header(lk, value)))
        chunks.append(pre(esc(body.strip()[:2600]) or "No data"))

    elif lk.get("kind") == "custom":
        parser = CUSTOM_PARSERS.get(lk.get("ep"))
        chunks.append(pre(make_header(lk, value)))
        chunks += parser(payload) if parser else [auto_block(payload if isinstance(payload, dict) else {})]

    elif lk.get("kind") == "records":
        recs = extract_records(payload)
        if not recs:
            chunks.append(pre(make_header(lk, value, 0) + "\n\n❌ Koi record nahi mila."))
        else:
            try:
                total = int(payload.get(lk.get("count_key", "total"), len(recs)))
            except Exception:                                    # noqa
                total = len(recs)
            total = total or len(recs)
            pages = max(1, math.ceil(total / max(1, max_rec)))
            shown = min(max_rec, len(recs))
            chunks.append(pre(make_header(lk, value, total, pages)))
            chunks += record_blocks(recs, lk.get("fields", []), total, max_rec)
            if shown < total:
                trimmed = True

    else:  # object
        data = payload.get("data", payload) if isinstance(payload, dict) else payload
        if not isinstance(data, dict):
            data = {}
        chunks.append(pre(make_header(lk, value) + "\n\n" +
                          rows_cols([(e, l, get_path(data, p)) for e, l, p in lk.get("fields", [])])))

    text = "\n".join(chunks)
    note = "\n\n<i>…baaki record chhote kar diye gaye.</i>" if trimmed else ""
    return f"{text}\n\n{footer(elapsed)}{note}", trimmed

# ════════════════════════════════════════════════════════════════════
#  ░░ 12. LOOKUP EXECUTION  ░░
# ════════════════════════════════════════════════════════════════════

async def run_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE,
                     lid: str, value: str) -> None:
    lk = all_lookups().get(lid)
    msg = update.effective_message
    user = update.effective_user
    if not lk:
        await msg.reply_text("❌ Ye lookup delete ho gaya.")
        return

    wait = await msg.reply_text(
        f"{lk.get('icon','🔍')} {bs(lk.get('title','LOOKUP'))}\n"
        f"🔍 <code>{esc(trunc(value, 60))}</code> dhoond raha hoon...",
        parse_mode=ParseMode.HTML)

    ok, payload, elapsed, url = await call_api(lk, value)

    if not ok:
        await wait.edit_text(
            f"❌ <b>API ERROR</b>\n🔗 {lk.get('icon','')} {esc(lk.get('title',''))}\n"
            f"📄 <code>{esc(str(payload)[:250])}</code>\n\n👨‍💻 Admin ko DM bhej diya.",
            parse_mode=ParseMode.HTML)
        await report_error(context, user, lk, value, str(payload), url)
        return

    # single message, record count adjust karke fit karo
    text, _ = build_result(lk, payload, value, elapsed, max_rows())
    n = max_rows()
    while len(text) > MSG_LIMIT and n > 1:
        n -= 1
        text, _ = build_result(lk, payload, value, elapsed, n)

    try:
        await wait.delete()
    except TelegramError:
        pass

    if CFG("file_mode"):
        fname = f"{lid}_{str(value).replace('/', '_')[:20]}.txt"
        plain = text.replace("<pre>", "").replace("</pre>", "")
        with open(fname, "w", encoding="utf-8") as f:
            f.write(plain)
        await msg.reply_document(open(fname, "rb"),
                                 caption=f"{lk.get('icon','')} <b>{esc(lk.get('title',''))}</b> — "
                                         f"<code>{esc(value)}</code>\n⏱ <code>{elapsed:.2f}s</code>",
                                 parse_mode=ParseMode.HTML)
        try:
            os.remove(fname)
        except OSError:
            pass
    else:
        if len(text) <= MSG_LIMIT:
            await msg.reply_text(text, parse_mode=ParseMode.HTML)
        else:
            # extreme case — 2 message
            cut = text.rfind("\n", 0, MSG_LIMIT)
            await msg.reply_text(text[:cut], parse_mode=ParseMode.HTML)
            await msg.reply_text(text[cut:].strip(), parse_mode=ParseMode.HTML)

    STORE.bump(user.id)

# ════════════════════════════════════════════════════════════════════
#  ░░ 13. STATIC TEXTS  ░░
# ════════════════════════════════════════════════════════════════════

START_TXT = ("╔══════════════════════════╗\n"
             "   🕵️ <b>OSINT LOOKUP BOT</b>\n"
             "╚══════════════════════════╝\n\n"
             "📞 Number & Leak\n🚗 Vehicle & RC\n🪪 Aadhaar / PAN / GST\n"
             "👨‍👩‍👧 Family ID\n📍 Pincode & IFSC\n\n"
             "Neeche se category chuno 👇")

HELP_TXT = ("📖 <b>HELP / GUIDE</b>\n" + DIVIDER + "\n\n"
            "<b>Kaise use kare?</b>\n1️⃣ Category chuno\n2️⃣ Lookup button dabao\n"
            "3️⃣ Value bhejo — pura result ek hi message me milega\n\n"
            "<b>Input format:</b>\n"
            "• 📞 Number: <code>9876543210</code>\n"
            "• 🚗 Vehicle: <code>KA01AB1234</code>\n"
            "• 🆔 Aadhaar: 12 digits\n"
            "• 🪪 PAN: <code>ABCDE1234F</code>\n"
            "• 🧾 GSTIN: 15 characters\n"
            "• 👤 Namesearch: <code>Naam,Sheher</code>\n"
            "• 🧾 GST Returns: <code>GSTIN,2023-24</code>\n\n"
            "<b>Group me:</b> bot ko mention ya reply karo.\n\n"
            "<i>Result copy karne ke liye long-press karo.</i>")

COMMANDS_TXT = ("⌨️ <b>COMMAND LIST</b>\n" + DIVIDER + "\n\n"
                "/start — 🚀 Start / main menu\n"
                "/menu — 📋 Main menu\n"
                "/help — 📖 Guide\n"
                "/commands — ⌨️ Ye list\n"
                "/id — 🆔 Apni Telegram ID\n"
                "/about — ℹ️ Bot info\n"
                "/cancel — ❌ Cancel\n"
                "/stats — 📊 Stats\n"
                "/admin — 👑 Admin panel\n"
                "/broadcast — 📢 Broadcast (admin)\n"
                "/reload — 🔄 Config reload (admin)")

ABOUT_TXT = ("ℹ️ <b>ABOUT</b>\n" + DIVIDER + "\n\n"
             "🕵️ <b>OSINT Lookup Bot</b>\n"
             "Number • Leak • Address • Vehicle • RC • Aadhaar\n"
             "PAN • GST • Family ID • Voter • Pincode • IFSC\n\n"
             f"🛒 {CFG('buy_line')}\n👨‍💻 {CFG('by_line')}\n\n"
             "📦 Powered by <code>ftosint.world</code>")

# ════════════════════════════════════════════════════════════════════
#  ░░ 14. WIZARD / EDIT STATE  ░░
# ════════════════════════════════════════════════════════════════════

WIZ_STEPS: List[Tuple[str, str]] = [
    ("id",     "🆔 <b>Step 1/11</b>\nLookup ID bhejo (chhota, bina space)\n<i>Example: mynum</i>"),
    ("icon",   "😀 <b>Step 2/11</b>\nEmoji icon bhejo\n<i>Example: 📞</i>"),
    ("title",  "🏷 <b>Step 3/11</b>\nTitle bhejo\n<i>Example: MY NUMBER INFO</i>"),
    ("sub",    "📝 <b>Step 4/11</b>\nSubtitle bhejo\n<i>Example: My Database</i>"),
    ("cat",    "📂 <b>Step 5/11</b>\nCategory bhejo: <code>num</code> / <code>veh</code> / <code>idn</code> / <code>utl</code>"),
    ("url",    "🌐 <b>Step 6/11</b>\nFull API URL bhejo\n<i>Example: https://ftosint.world/api/number</i>"),
    ("param",  "🔤 <b>Step 7/11</b>\nParam name bhejo\n<i>Example: num</i>"),
    ("auth",   "🔑 <b>Step 8/11</b>\nAuth key: <code>ft</code> ya <code>fam</code>"),
    ("kind",   "🧩 <b>Step 9/11</b>\nType: <code>object</code> / <code>records</code> / <code>custom</code>"),
    ("fields", "📋 <b>Step 10/11</b>\nFields bhejo — har line ek field:\n"
               "<i>Format: 📲 Number = mobile</i>\n(object/records ke liye, custom ho to <code>skip</code>)"),
    ("hint",   "💡 <b>Step 11/11</b>\nHint text bhejo (user ko dikhega)"),
]

KIND_LABEL = {"object": "object", "records": "records", "custom": "custom", "text": "text"}


def parse_fields(raw: str) -> List[Tuple[str, str, str]]:
    out: List[Tuple[str, str, str]] = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line or "=" not in line:
            continue
        left, path = line.split("=", 1)
        left, path = left.strip(), path.strip()
        parts = left.split(" ", 1)
        if len(parts) == 2 and len(parts[0]) <= 4:
            emoji, label = parts[0], parts[1]
        else:
            emoji, label = "▪️", left
        if path:
            out.append((emoji, label, path))
    return out


def fields_to_text(fields: List[Tuple[str, str, str]]) -> str:
    return "\n".join(f"{e} {l} = {p}" for e, l, p in fields)

# ════════════════════════════════════════════════════════════════════
#  ░░ 15. HANDLERS  ░░
# ════════════════════════════════════════════════════════════════════

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u = update.effective_user
    if u and not u.is_bot:
        STORE.add_user(u)
    if not await gate(update, context):
        return
    for k in ("await", "state", "edit", "wiz"):
        context.user_data.pop(k, None)
    await update.effective_message.reply_text(
        START_TXT, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(is_admin(u.id)))


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        HELP_TXT, parse_mode=ParseMode.HTML,
        reply_markup=main_menu_kb(is_admin(update.effective_user.id)))


async def cmd_commands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        COMMANDS_TXT, parse_mode=ParseMode.HTML,
        reply_markup=main_menu_kb(is_admin(update.effective_user.id)))


async def cmd_about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        ABOUT_TXT, parse_mode=ParseMode.HTML,
        reply_markup=main_menu_kb(is_admin(update.effective_user.id)))


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    for k in ("await", "state", "edit", "wiz"):
        context.user_data.pop(k, None)
    await update.effective_message.reply_text(
        "❌ Cancel kar diya.", reply_markup=main_menu_kb(is_admin(update.effective_user.id)))


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u, c = update.effective_user, update.effective_chat
    await update.effective_message.reply_text(
        f"🆔 <b>Your ID:</b> <code>{u.id}</code>\n💬 <b>Chat ID:</b> <code>{c.id}</code>\n"
        f"👑 <b>Admin:</b> {'Yes' if is_admin(u.id) else 'No'}", parse_mode=ParseMode.HTML)


async def cmd_reload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    STORE.load()
    await update.effective_message.reply_text("🔄 Config reload ho gaya (botdata.json se).")


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("❌ Admin only.")
        return
    await update.effective_message.reply_text(
        "👑 <b>ADMIN PANEL</b>\nSab kuch yahin se set karo.", parse_mode=ParseMode.HTML,
        reply_markup=admin_kb())


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    await update.effective_message.reply_text(
        f"📊 <b>STATS</b>\n\n👥 Users: <code>{len(STORE.users)}</code>\n"
        f"🔍 Lookups: <code>{STORE.stats.get('lookups', 0)}</code>\n"
        f"🚨 Errors: <code>{STORE.stats.get('errors', 0)}</code>\n"
        f"🔧 Lookups: <code>{len(all_lookups())}</code>\n"
        f"📢 Channels: <code>{len(STORE.channels)}</code>",
        parse_mode=ParseMode.HTML, reply_markup=admin_kb())


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    context.user_data["state"] = "broadcast"
    await update.effective_message.reply_text(
        "📢 <b>BROADCAST MODE</b>\nJo bhejna hai wo bhejo.\nCancel: /cancel",
        parse_mode=ParseMode.HTML)

# ── text router ─────────────────────────────────────────────────────

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if not msg or not msg.text:
        return
    user = update.effective_user
    if not user or user.is_bot:
        return
    text = msg.text.strip()

    # 1) broadcast
    if context.user_data.get("state") == "broadcast" and is_admin(user.id):
        context.user_data.pop("state", None)
        await do_broadcast(msg)
        return

    # 2) single-field edit
    ed = context.user_data.get("edit")
    if ed and is_admin(user.id):
        context.user_data.pop("edit", None)
        await apply_edit(msg, ed, text)
        return

    # 3) add-lookup wizard
    wiz = context.user_data.get("wiz")
    if wiz and is_admin(user.id):
        await wiz_step(msg, context, wiz, text)
        return

    # 4) add channel
    if context.user_data.get("state") == "addch" and is_admin(user.id):
        context.user_data.pop("state", None)
        ch = text if text.startswith("@") else "@" + text
        if ch not in STORE.channels:
            STORE.channels.append(ch)
            STORE.save()
        await msg.reply_text(f"✅ Channel add: <code>{esc(ch)}</code>", parse_mode=ParseMode.HTML)
        return

    # 5) group gate
    in_group = msg.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
    if in_group and not context.user_data.get("await"):
        me = await context.bot.get_me()
        if not (f"@{me.username}".lower() in text.lower() or
                (msg.reply_to_message and msg.reply_to_message.from_user
                 and msg.reply_to_message.from_user.id == me.id)):
            return

    if not await gate(update, context):
        return

    value = text.replace(f"@{context.bot.username}", "").strip() if in_group else text
    lid = context.user_data.get("await")
    if not lid:
        await msg.reply_text("Neeche se koi lookup chuno 👇",
                             reply_markup=main_menu_kb(is_admin(user.id)))
        return
    context.user_data.pop("await", None)
    await run_lookup(update, context, lid, value)


async def apply_edit(msg, ed: dict, text: str) -> None:
    if ed.get("target") == "setting":
        key = ed["key"]
        if key in ("max_rows", "max_val"):
            try:
                STORE.settings[key] = int(text)
            except ValueError:
                await msg.reply_text("❌ Number bhejo.")
                return
        else:
            STORE.settings[key] = text
        STORE.save()
        await msg.reply_text(f"✅ <b>{esc(ed['name'])}</b> update ho gaya.", parse_mode=ParseMode.HTML,
                             reply_markup=admin_kb())
        return

    if ed.get("target") == "lookup":
        lid, field = ed["lid"], ed["field"]
        cur = STORE.lookups.get(lid) or dict(BUILTIN.get(lid, {}))
        cur.pop("deleted", None)
        if field == "fields":
            cur["fields"] = [list(t) for t in parse_fields(text)] if text.lower() != "skip" else []
        elif field == "url":
            cur["url"] = text
            cur.pop("ep", None)
            cur.pop("base", None)
        else:
            cur[field] = text
        STORE.lookups[lid] = cur
        STORE.save()
        await msg.reply_text(f"✅ <code>{esc(lid)}</code> ka <b>{esc(field)}</b> update ho gaya.",
                             parse_mode=ParseMode.HTML, reply_markup=lk_edit_kb(lid))
        return


async def wiz_step(msg, context: ContextTypes.DEFAULT_TYPE, wiz: dict, text: str) -> None:
    step = wiz["step"]
    key = WIZ_STEPS[step][0]
    data = wiz["data"]

    if key == "id":
        lid = text.replace(" ", "_").lower()
        if lid in all_lookups():
            await msg.reply_text("❌ Ye ID already hai. Dusra bhejo.")
            return
        data["id"] = lid
    elif key == "cat":
        data["cat"] = text.split()[0].lower() or "utl"
    elif key == "url":
        data["url"] = text
    elif key == "auth":
        data["auth"] = "fam" if "fam" in text.lower() else "ft"
    elif key == "kind":
        data["kind"] = text.lower() if text.lower() in KIND_LABEL else "object"
    elif key == "fields":
        data["fields"] = [] if text.lower() == "skip" else [list(t) for t in parse_fields(text)]
    else:
        data[key] = text

    wiz["step"] += 1
    if wiz["step"] >= len(WIZ_STEPS):
        lid = data.pop("id")
        data.setdefault("sub", "Database")
        data.setdefault("param", "q")
        data.setdefault("auth", "ft")
        data.setdefault("kind", "object")
        data.setdefault("fields", [])
        data.setdefault("hint", "Value bhejo")
        STORE.lookups[lid] = data
        STORE.save()
        context.user_data.pop("wiz", None)
        await msg.reply_text(
            f"✅ Lookup add ho gaya: {esc(data.get('icon',''))} <b>{esc(data.get('title', lid))}</b>\n"
            f"ID: <code>{esc(lid)}</code>", parse_mode=ParseMode.HTML, reply_markup=admin_kb())
        return

    context.user_data["wiz"] = wiz
    await msg.reply_text(WIZ_STEPS[wiz["step"]][1], parse_mode=ParseMode.HTML)

# ── callback router ─────────────────────────────────────────────────

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    data = q.data
    user = q.from_user

    if data == "checkjoin":
        if await joined_all(context, user.id):
            await q.answer("✅ Verified!")
            await q.message.edit_text(START_TXT, parse_mode=ParseMode.HTML,
                                      reply_markup=main_menu_kb(is_admin(user.id)))
        else:
            await q.answer("❌ Abhi join nahi kiya!", show_alert=True)
        return

    if not await gate(update, context):
        return
    await q.answer()

    if data == "menu":
        context.user_data.pop("await", None)
        await q.message.edit_text(START_TXT, parse_mode=ParseMode.HTML,
                                  reply_markup=main_menu_kb(is_admin(user.id)))
        return
    if data == "help":
        await q.message.edit_text(HELP_TXT, parse_mode=ParseMode.HTML,
                                  reply_markup=main_menu_kb(is_admin(user.id)))
        return
    if data == "commands":
        await q.message.edit_text(COMMANDS_TXT, parse_mode=ParseMode.HTML,
                                  reply_markup=main_menu_kb(is_admin(user.id)))
        return
    if data == "about":
        await q.message.edit_text(ABOUT_TXT, parse_mode=ParseMode.HTML,
                                  reply_markup=main_menu_kb(is_admin(user.id)))
        return
    if data == "myid":
        await q.message.edit_text(
            f"🆔 <b>Your ID:</b> <code>{user.id}</code>\n"
            f"💬 <b>Chat ID:</b> <code>{q.message.chat_id}</code>\n"
            f"👑 <b>Admin:</b> {'Yes' if is_admin(user.id) else 'No'}",
            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(is_admin(user.id)))
        return
    if data.startswith("cat:"):
        cid = data.split(":", 1)[1]
        await q.message.edit_text(f"<b>Konsi lookup chahiye?</b>",
                                  parse_mode=ParseMode.HTML, reply_markup=category_kb(cid))
        return
    if data.startswith("lk:"):
        lid = data.split(":", 1)[1]
        lk = all_lookups().get(lid)
        if not lk:
            await q.message.edit_text("❌ Lookup nahi mila.", reply_markup=main_menu_kb(is_admin(user.id)))
            return
        context.user_data["await"] = lid
        await q.message.edit_text(
            f"{lk.get('icon','🔍')} {bs(lk.get('title', lid))}\n\n{lk.get('hint','Value bhejo')}\n\n"
            "<i>Value type karke bhejo.</i>", parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Cancel", callback_data="menu")]]))
        return

    if data.startswith("adm:"):
        if not is_admin(user.id):
            await q.answer("Admin only", show_alert=True)
            return
        await admin_router(update, context, data)


async def admin_router(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    q = update.callback_query
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else "home"

    if action == "home":
        await q.message.edit_text("👑 <b>ADMIN PANEL</b>", parse_mode=ParseMode.HTML, reply_markup=admin_kb())

    elif action == "stats":
        await q.message.edit_text(
            f"📊 <b>STATS</b>\n\n👥 Users: <code>{len(STORE.users)}</code>\n"
            f"🔍 Lookups: <code>{STORE.stats.get('lookups', 0)}</code>\n"
            f"🚨 Errors: <code>{STORE.stats.get('errors', 0)}</code>\n"
            f"🔧 Total Lookups: <code>{len(all_lookups())}</code>\n"
            f"📢 Channels: <code>{len(STORE.channels)}</code>",
            parse_mode=ParseMode.HTML, reply_markup=admin_kb())

    elif action == "users":
        top = sorted(STORE.users.values(), key=lambda x: x.get("lookups", 0), reverse=True)[:10]
        body = "\n".join(f"{i+1}. {esc(u['name'][:20])} — <code>{u['id']}</code> — {u.get('lookups',0)}🔍"
                         for i, u in enumerate(top)) or "Koi user nahi."
        await q.message.edit_text(f"👥 <b>TOP USERS</b>\n\n{body}",
                                  parse_mode=ParseMode.HTML, reply_markup=admin_kb())

    elif action == "keys":
        await q.message.edit_text(
            "🔑 <b>API KEYS & URL</b>\n\n"
            f"FT Key: <code>{esc(str(CFG('ft_key'))[:22])}…</code>\n"
            f"FT Base: <code>{esc(CFG('ft_base'))}</code>\n"
            f"FAM Key: <code>{esc(str(CFG('fam_key'))[:22])}…</code>\n"
            f"FAM Base: <code>{esc(CFG('fam_base'))}</code>\n\n"
            "Edit karne ke liye button dabao 👇",
            parse_mode=ParseMode.HTML, reply_markup=keys_kb())

    elif action == "limits":
        await q.message.edit_text(
            f"⚙️ <b>LIMITS</b>\n\n📄 Max Records: <code>{CFG('max_rows')}</code>\n"
            f"✂️ Max Value: <code>{CFG('max_val')}</code>",
            parse_mode=ParseMode.HTML, reply_markup=limits_kb())

    elif action == "brand":
        await q.message.edit_text("🏷 <b>BRANDING</b>", parse_mode=ParseMode.HTML, reply_markup=brand_kb())

    elif action == "file":
        STORE.settings["file_mode"] = not CFG("file_mode")
        STORE.save()
        await q.answer(f"File Mode: {'ON' if CFG('file_mode') else 'OFF'}")
        await q.message.edit_text(
            f"📎 File Mode: <b>{'ON' if CFG('file_mode') else 'OFF'}</b>\n\n"
            "ON hone par result .txt file me milega (full data, bina trim).",
            parse_mode=ParseMode.HTML, reply_markup=admin_kb())

    elif action == "set":
        key = parts[2]
        name, desc = SETTING_SPECS.get(key, (key, ""))
        context.user_data["edit"] = {"target": "setting", "key": key, "name": name}
        cur = CFG(key)
        await q.message.edit_text(
            f"✏️ <b>{esc(name)}</b>\n<i>{esc(desc)}</i>\n\n"
            f"Abhi: <code>{esc(str(cur)[:200])}</code>\n\nNaya value bhejo.\nCancel: /cancel",
            parse_mode=ParseMode.HTML)

    elif action == "lks":
        lk = all_lookups()
        rows = [[InlineKeyboardButton(f"{v.get('icon','🔹')} {v.get('title', k)}",
                                      callback_data=f"adm:lk:{k}")] for k, v in sorted(lk.items())]
        rows.append([InlineKeyboardButton("⬅️ Back", callback_data="adm:home")])
        await q.message.edit_text(f"🔧 <b>LOOKUPS ({len(lk)})</b>\nKisiko edit karo:",
                                  parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))

    elif action == "lk":
        lid = parts[2]
        lk = all_lookups().get(lid)
        if not lk:
            await q.message.edit_text("❌ Nahi mila.", reply_markup=admin_kb())
            return
        await q.message.edit_text(
            f"🔧 <b>{esc(lk.get('title', lid))}</b>\n"
            f"ID: <code>{esc(lid)}</code>\nCat: <code>{esc(lk.get('cat',''))}</code>\n"
            f"Type: <code>{esc(lk.get('kind',''))}</code>\n"
            f"Param: <code>{esc(lk.get('param',''))}</code>\n"
            f"URL: <code>{esc(resolve_base(lk))}</code>",
            parse_mode=ParseMode.HTML, reply_markup=lk_edit_kb(lid))

    elif action == "lkf":
        lid, field = parts[2], parts[3]
        lk = all_lookups().get(lid, {})
        context.user_data["edit"] = {"target": "lookup", "lid": lid, "field": field}
        cur = fields_to_text([tuple(f) for f in lk.get("fields", [])]) if field == "fields" \
            else lk.get(field) or lk.get("ep") or ""
        await q.message.edit_text(
            f"✏️ <b>{esc(lid)}</b> → <b>{esc(field)}</b>\n\n"
            f"Abhi:\n<pre>{esc(str(cur)[:900])}</pre>\n\nNaya value bhejo.\nCancel: /cancel",
            parse_mode=ParseMode.HTML)

    elif action == "lkd":
        lid = parts[2]
        if lid in BUILTIN:
            STORE.lookups[lid] = {"deleted": True}
        else:
            STORE.lookups.pop(lid, None)
        STORE.save()
        await q.message.edit_text(f"🗑 <code>{esc(lid)}</code> delete ho gaya.",
                                  parse_mode=ParseMode.HTML, reply_markup=admin_kb())

    elif action == "wiz":
        context.user_data["wiz"] = {"step": 0, "data": {}}
        await q.message.edit_text(WIZ_STEPS[0][1], parse_mode=ParseMode.HTML)

    elif action == "chs":
        body = "\n".join(f"{i}. <code>{esc(c)}</code>" for i, c in enumerate(STORE.channels)) or "Koi nahi."
        rows = [[InlineKeyboardButton(f"❌ {c}", callback_data=f"adm:chd:{i}")]
                for i, c in enumerate(STORE.channels)]
        rows.append([InlineKeyboardButton("➕ Add Channel", callback_data="adm:cha"),
                     InlineKeyboardButton("⬅️ Back", callback_data="adm:home")])
        await q.message.edit_text(f"📢 <b>FORCE JOIN</b>\n\n{body}\n\nHatane ke liye tap karo:",
                                  parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))

    elif action == "cha":
        context.user_data["state"] = "addch"
        await q.message.edit_text("➕ Channel ka @username bhejo (jaise @MyChannel)")

    elif action == "chd":
        i = int(parts[2])
        if 0 <= i < len(STORE.channels):
            removed = STORE.channels.pop(i)
            STORE.save()
            await q.answer(f"Removed {removed}")
        await admin_router(update, context, "adm:chs")

    elif action == "bc":
        context.user_data["state"] = "broadcast"
        await q.message.edit_text("📢 <b>BROADCAST</b>\nJo bhejna hai wo bhejo. Cancel: /cancel",
                                  parse_mode=ParseMode.HTML)

    elif action == "errs":
        if not STORE.errors:
            await q.message.edit_text("🧾 Koi error nahi ✅", reply_markup=admin_kb())
            return
        lines = [f"• <code>{esc(e['lookup'])}</code> | <code>{esc(e['value'][:18])}</code>\n"
                 f"  <i>{esc(e['error'][:90])}</i>" for e in STORE.errors[-8:]]
        await q.message.edit_text("🧾 <b>LAST ERRORS</b>\n\n" + "\n".join(lines),
                                  parse_mode=ParseMode.HTML, reply_markup=admin_kb())

    elif action == "clrerr":
        STORE.errors = []
        STORE.stats["errors"] = 0
        STORE.save()
        await q.message.edit_text("🗑 Error log clear.", reply_markup=admin_kb())


async def do_broadcast(msg) -> None:
    sent = failed = 0
    for uid in list(STORE.users.keys()):
        try:
            await msg.copy(chat_id=int(uid))
            sent += 1
            await asyncio.sleep(0.05)
        except TelegramError:
            failed += 1
    await msg.reply_text(f"✅ Done\n✔️ Sent: {sent}\n❌ Failed: {failed}")

# ════════════════════════════════════════════════════════════════════
#  ░░ 16. ERROR HANDLER  ░░
# ════════════════════════════════════════════════════════════════════

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    if isinstance(err, Conflict):
        log.warning("Conflict — dusra instance chal raha hai?")
        return
    if isinstance(err, (TimedOut, NetworkError)):
        log.warning("Network: %s", err)
        return
    log.error("Handler error", exc_info=err)
    for t in set(ADMIN_IDS):
        try:
            await context.bot.send_message(
                t, f"🧨 <b>BOT ERROR</b>\n<code>{esc(str(err)[:400])}</code>",
                parse_mode=ParseMode.HTML)
        except TelegramError:
            pass

# ════════════════════════════════════════════════════════════════════
#  ░░ 17. BOOT  ░░
# ════════════════════════════════════════════════════════════════════

async def post_init(app: Application) -> None:
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
    except TelegramError as e:
        log.warning("delete_webhook fail: %s", e)
    await app.bot.set_my_commands([
        BotCommand("start", "🚀 Start / main menu"),
        BotCommand("menu", "📋 Main menu"),
        BotCommand("help", "📖 Guide"),
        BotCommand("commands", "⌨️ Saari commands"),
        BotCommand("id", "🆔 Apni Telegram ID"),
        BotCommand("about", "ℹ️ Bot info"),
        BotCommand("cancel", "❌ Cancel"),
        BotCommand("stats", "📊 Stats"),
        BotCommand("admin", "👑 Admin panel"),
        BotCommand("broadcast", "📢 Broadcast (admin)"),
        BotCommand("reload", "🔄 Config reload"),
    ])
    me = await app.bot.get_me()
    log.info("Bot up: @%s", me.username)


def build_app() -> Application:
    app = (ApplicationBuilder().token(BOT_TOKEN).post_init(post_init)
           .concurrent_updates(True).build())
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("commands", cmd_commands))
    app.add_handler(CommandHandler("about", cmd_about))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("reload", cmd_reload))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    return app


def acquire_lock() -> None:
    pid = os.getpid()
    if os.path.exists(LOCK_FILE):
        try:
            old = int(open(LOCK_FILE).read().strip() or 0)
            if old and old != pid and os.path.exists(f"/proc/{old}"):
                log.warning("⚠️  Dusra instance shayad chal raha hai (pid %s). "
                            "Conflict aaye to purana band karo.", old)
        except Exception:                                        # noqa
            pass
    try:
        with open(LOCK_FILE, "w") as f:
            f.write(str(pid))
    except OSError:
        pass


def main() -> None:
    acquire_lock()
    while True:
        try:
            log.info("Polling start...")
            build_app().run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
                close_loop=False,
            )
            break
        except Conflict:
            log.warning("Conflict — 5 sec baad retry (dusra instance band karo).")
            time.sleep(5)
        except KeyboardInterrupt:
            log.info("Bye.")
            break
        except Exception as e:                                   # noqa
            log.exception("Crash: %s — 5 sec baad retry", e)
            time.sleep(5)


if __name__ == "__main__":
    main()