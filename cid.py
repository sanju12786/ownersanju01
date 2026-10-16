#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║  FTOSINT + FAMILY ID  —  TELEGRAM OSINT BOT                      ║
║  Lookups: Number / Leak / Address / Vehicle / Identity / GST     ║
║  Output : Small-caps record blocks + aligned COLUMN layout       ║
║  Features: Admin Panel, Force Join, Error DM, Broadcast          ║
║  Buy @thehiddenreserve  •  By @thehiddenreserve                  ║
╚══════════════════════════════════════════════════════════════════╝
"""

import asyncio
import html
import json
import logging
import math
import os
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
from telegram.error import TelegramError
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

BOT_TOKEN   = os.getenv("BOT_TOKEN", "8036729272:AAFSzpvCKk2y6dLIOUS1irB1BK23_RPD7oQ")
CHAT_ID     = os.getenv("CHAT_ID", "5574675470")            # admin DM / log chat
ADMIN_IDS   = [int(x) for x in os.getenv("ADMIN_IDS", "5574675470").split(",")]

FT_KEY      = "cobra-limited-land"                          # ftosint.world key
FT_BASE     = "https://ftosint.world/api"
FAM_KEY     = "Navratri"                                    # family api key
FAM_BASE    = "https://sahilxher.madewith.me/api"

FORCE_CHANNELS = ["@Sanjuownersmm"]
DATA_FILE      = "botdata.json"
HTTP_TIMEOUT   = 45
MAX_ROWS       = 5                     # ek page me kitne record
MAX_VAL        = 200                   # ek value ki max length
SEP            = "━" * 18

BUY_LINE = "🛒 Buy @thehiddenreserve"
BY_LINE  = "👨‍💻 By @thehiddenreserve"
DIVIDER  = "─" * 30
DISCLAIMER = (
    "⚠️ <b>DISCLAIMER</b>\n"
    "🎓 Educational use only\n"
    "🚫 Misuse is illegal\n"
    "📜 User is responsible"
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("osint-bot")

# ════════════════════════════════════════════════════════════════════
#  ░░ 2. STORAGE  ░░
# ════════════════════════════════════════════════════════════════════

class Store:
    def __init__(self, path: str = DATA_FILE):
        self.path = path
        self.users: Dict[str, dict] = {}
        self.channels: List[str] = list(FORCE_CHANNELS)
        self.stats: Dict[str, int] = {"lookups": 0, "errors": 0, "joins": 0}
        self.errors: List[dict] = []
        self.load()

    def load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.users = d.get("users", {})
            self.channels = d.get("channels", list(FORCE_CHANNELS))
            self.stats = {**self.stats, **d.get("stats", {})}
            self.errors = d.get("errors", [])[-50:]
        except Exception as e:                                    # noqa
            log.warning("Store load fail: %s", e)

    def save(self) -> None:
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "users": self.users,
                        "channels": self.channels,
                        "stats": self.stats,
                        "errors": self.errors[-50:],
                    },
                    f, ensure_ascii=False, indent=2,
                )
            os.replace(tmp, self.path)
        except Exception as e:                                    # noqa
            log.warning("Store save fail: %s", e)

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

# ════════════════════════════════════════════════════════════════════
#  ░░ 3. STYLING / FORMAT HELPERS  ░░
# ════════════════════════════════════════════════════════════════════

_SMALL = {
    "a": "ᴀ", "b": "ʙ", "c": "ᴄ", "d": "ᴅ", "e": "ᴇ", "f": "ꜰ", "g": "ɢ", "h": "ʜ",
    "i": "ɪ", "j": "ᴊ", "k": "ᴋ", "l": "ʟ", "m": "ᴍ", "n": "ɴ", "o": "ᴏ", "p": "ᴘ",
    "q": "ǫ", "r": "ʀ", "s": "ꜱ", "t": "ᴛ", "u": "ᴜ", "v": "ᴠ", "w": "ᴡ", "x": "x",
    "y": "ʏ", "z": "ᴢ",
}


def sc(t: Any) -> str:
    """lowercase -> small caps (uppercase waisa hi)."""
    return "".join(_SMALL.get(c, c) for c in str(t))


def bs(t: Any) -> str:
    """Bold sans-serif unicode."""
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
    """Visual width — emoji/CJK = 2 cells (column alignment ke liye)."""
    n = 0
    for ch in str(s):
        n += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return n


def esc(t: Any) -> str:
    return html.escape(str(t), quote=False)


def trunc(s: Any, n: int = MAX_VAL) -> str:
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
        f"{lk['icon']} {bs(lk['title'])}",
        "",
        f"{sc(lk.get('sub', 'Database'))} ✅",
        "",
        f"🔭 {sc('Query')} : {esc(trunc(query, 60))}",
    ]
    if total is not None:
        lines.append(f"✍️ {sc('Records')} : {total} | {sc('Page')} {page}/{pages}")
    return "\n".join(lines)


def rows_cols(rows: List[Tuple[str, str, Any]]) -> str:
    """Emoji + small-caps label + aligned ':' + value — proper columns."""
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
                  total: int, max_rows: int = MAX_ROWS) -> List[str]:
    """Har record ek alag <pre> block — split-safe."""
    blocks = []
    for i, r in enumerate(records[:max_rows], 1):
        body = [
            SEP,
            f"📰 {sc('Record')} {i}/{total}",
            SEP,
            "",
            rows_cols([(e, l, get_path(r, p)) for e, l, p in fields]),
        ]
        blocks.append(pre("\n".join(body)))
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


def footer(elapsed: float, extra: str = "") -> str:
    head = f"⏱ <code>{elapsed:.2f}s</code>"
    if extra:
        head += f"  |  {extra}"
    return (
        f"{head}\n{DIVIDER}\n"
        f"{BUY_LINE}\n{BY_LINE}\n"
        f"{DIVIDER}\n{DISCLAIMER}"
    )


async def send_chunks(msg, chunks: List[str], **kw) -> None:
    """Chunks ko limit ke andar group karke bhejta hai (pre safe)."""
    limit = 3600
    buf = ""
    for c in chunks:
        if not c:
            continue
        if buf and len(buf) + len(c) + 1 > limit:
            await msg.reply_text(buf.rstrip(), **kw)
            buf = ""
        buf += c + "\n"
    if buf.strip():
        await msg.reply_text(buf.rstrip(), **kw)

# ════════════════════════════════════════════════════════════════════
#  ░░ 4. LOOKUP REGISTRY  ░░
#  fields = [(emoji, Label, json.path), ...]
# ════════════════════════════════════════════════════════════════════

LOOKUPS: Dict[str, dict] = {
    # ── Number & Leak ──────────────────────────────────────────────
    "number": dict(
        icon="📞", title="NUMBER INFO", sub="Number Database", cat="num",
        base=FT_BASE, ep="number", param="num", kind="records",
        hint="10 digit mobile number bhejo\n<i>Example: 9876543210</i>",
        count_key="total",
        fields=[
            ("📲", "Number", "mobile"), ("👤", "Name", "name"),
            ("👥", "Father", "fname"), ("📞", "Alt Num", "alt"),
            ("🔎", "Circle", "circle"), ("🏡", "Address", "address"),
            ("💳", "Id", "id"), ("📧", "Email", "email"),
        ],
    ),
    "numleak": dict(
        icon="🔎", title="NUMBER LEAK", sub="HiTeck + ICMR Leak Database", cat="num",
        base=FT_BASE, ep="numleak", param="num", kind="custom",
        hint="Mobile number bhejo\n<i>Example: 9876543210</i>",
    ),
    "address": dict(
        icon="📍", title="ADDRESS LOOKUP", sub="Address Database", cat="num",
        base=FT_BASE, ep="address", param="address", kind="records",
        hint="Address ya area ka naam bhejo\n<i>Example: Okhla Delhi</i>",
        count_key="total",
        fields=[
            ("👤", "Name", "name"), ("📲", "Mobile", "mobile"),
            ("📞", "Alt Num", "alternate"), ("👥", "Father", "father_name"),
            ("🏡", "Address", "address"), ("💳", "Aadhaar", "aadhar"),
            ("🔎", "Circle", "circle"),
        ],
    ),
    "nametoinfo": dict(
        icon="👤", title="NAME TO INFO", sub="Name Database", cat="num",
        base=FT_BASE, ep="nametoinfo", param="name", kind="records",
        hint="Naam bhejo\n<i>Example: RAHUL</i>",
        count_key="total",
        fields=[
            ("👤", "Name", "name"), ("📲", "Mobile", "mobile"),
            ("👥", "Father", "father_name"), ("🏡", "Address", "address"),
            ("💳", "Aadhaar", "aadhar"), ("🔎", "Circle", "circle"),
            ("📞", "Alt Num", "alternate"),
        ],
    ),
    "namesearch": dict(
        icon="👤", title="NAME SEARCH", sub="Name + Place Database", cat="num",
        base=FT_BASE, ep="namesearch", param="q", extra_param="from", kind="records",
        hint="<b>Naam,Sheher</b> format me bhejo\n<i>Example: Ramesh,Delhi</i>",
        count_key="total",
        fields=[
            ("👤", "Name", "name"), ("📲", "Mobile", "mobile"),
            ("👥", "Father", "father_name"), ("🏡", "Address", "address"),
            ("💳", "Aadhaar", "aadhar"), ("🔎", "Circle", "circle"),
            ("📞", "Alt Num", "alternate"),
        ],
    ),

    # ── Vehicle ────────────────────────────────────────────────────
    "vehicle": dict(
        icon="🚗", title="VEHICLE TO OWNER", sub="RC Database", cat="veh",
        base=FT_BASE, ep="vehicle", param="vehicle", kind="object",
        hint="Registration number bhejo\n<i>Example: KA01AB1234</i>",
        fields=[
            ("🚗", "Reg No", "regNo"), ("👤", "Owner", "owner"),
            ("👥", "Father", "ownerFatherName"), ("🚙", "Model", "vehicle"),
            ("🏭", "Maker", "manufacturer"), ("🔧", "Variant", "variant"),
            ("📋", "Class", "vehicleClass"), ("⛽", "Fuel", "fuelType"),
            ("📅", "Reg Date", "regDate"), ("🏢", "RTO", "regAuthority"),
            ("🔩", "Chassis", "chassis"), ("⚙️", "Engine", "engine"),
            ("🛡", "Insurer", "insuranceCompanyName"), ("🧾", "Policy No", "insurancePolicyNumber"),
            ("🛡", "Insurance Upto", "insuranceUpto"), ("🏦", "Financier", "financerName"),
            ("📮", "Pincode", "pincode"), ("📌", "Status", "status"),
        ],
    ),
    "veh2num": dict(
        icon="🚗", title="VEHICLE TO MOBILE", sub="RC Mobile Database", cat="veh",
        base=FT_BASE, ep="veh2num", param="vehicle", kind="object",
        hint="Registration number bhejo\n<i>Example: KL41V3504</i>",
        fields=[
            ("🚗", "Vehicle", "vehicle"), ("👤", "Owner", "owner_name"),
            ("📲", "Mobile", "mobile_number"), ("🔩", "Chassis", "chassis_number"),
            ("⚙️", "Engine", "engine_number"),
        ],
    ),
    "fastag": dict(
        icon="🏷", title="FASTAG LOOKUP", sub="FASTag Database", cat="veh",
        base=FT_BASE, ep="fastag", param="vehicle", kind="custom",
        hint="Registration number bhejo\n<i>Example: KA01AB1234</i>",
    ),
    "challan": dict(
        icon="🧾", title="CHALLAN LOOKUP", sub="Challan Database", cat="veh",
        base=FT_BASE, ep="challan", param="vehicle", kind="custom",
        hint="Registration number bhejo\n<i>Example: KA01AB1234</i>",
    ),
    "rcpdf": dict(
        icon="📄", title="RC PDF", sub="RC Document", cat="veh",
        base=FT_BASE, ep="rcpdf", param="vehicle", kind="text",
        hint="Registration number bhejo\n<i>Example: KA01AB1234</i>",
    ),
    "rcchip": dict(
        icon="📄", title="RC PDF CHIP", sub="RC Document", cat="veh",
        base=FT_BASE, ep="rcchip", param="vehicle", kind="text",
        hint="Registration number bhejo\n<i>Example: KA01AB1234</i>",
    ),
    "vinfo": dict(
        icon="📘", title="RC DETAILS", sub="VInfo Database", cat="veh",
        base=FT_BASE, ep="vinfo", param="reg", kind="custom",
        hint="Registration number bhejo\n<i>Example: MH16BZ7090</i>",
    ),
    "puc": dict(
        icon="🌿", title="PUC CERTIFICATE", sub="PUC Document", cat="veh",
        base=FT_BASE, ep="puc", param="reg", kind="text",
        hint="Registration number bhejo\n<i>Example: MH16BZ7090</i>",
    ),
    "hw": dict(
        icon="⚙️", title="CHASSIS / ENGINE", sub="Hardware Database", cat="veh",
        base=FT_BASE, ep="hw", param="chasi", kind="custom",
        hint="Chassis ya engine number bhejo\n<i>Example: MA3NYFB1SKD530868</i>",
    ),
    "hpt": dict(
        icon="📝", title="HP / FINANCIER RECORD", sub="Hypothecation Database", cat="veh",
        base=FT_BASE, ep="hpt", param="reg", kind="custom",
        hint="Registration number bhejo\n<i>Example: KA01AB1234</i>",
    ),
    "vehindex": dict(
        icon="📋", title="VEHICLE INDEX", sub="Index Database", cat="veh",
        base=FT_BASE, ep="vehindex", param="reg", kind="records",
        hint="Registration number bhejo\n<i>Example: MH16BZ7090</i>",
        count_key="total",
        fields=[("🚗", "Reg No", "reg"), ("🔩", "Chassis", "chassis"),
                ("⚙️", "Engine", "engine"), ("📌", "Index", "ok")],
    ),

    # ── Identity & GST ─────────────────────────────────────────────
    "aadhar": dict(
        icon="🆔", title="AADHAAR LOOKUP", sub="Aadhaar Database", cat="idn",
        base=FT_BASE, ep="aadhar", param="num", kind="records",
        hint="12 digit Aadhaar number bhejo\n<i>Example: 393933081942</i>",
        count_key="total",
        fields=[
            ("👤", "Name", "name"), ("📲", "Mobile", "mobile"),
            ("👥", "Father", "father_name"), ("🏡", "Address", "address"),
            ("🔎", "Circle", "circle"), ("💳", "Aadhaar", "aadhar"),
        ],
    ),
    "family": dict(
        icon="👨‍👩‍👧", title="FAMILY ID", sub="Family Database", cat="idn",
        base=FAM_BASE, ep="family", param="term", kind="custom",
        hint="Aadhaar / Family ID bhejo\n<i>Example: 701984830542</i>",
    ),
    "pan": dict(
        icon="🪪", title="PAN TO GST", sub="GST Database", cat="idn",
        base=FT_BASE, ep="pan", param="pan", kind="records",
        hint="PAN number bhejo\n<i>Example: ABCDE1234F</i>",
        count_key="total",
        fields=[("🧾", "GSTIN", "gstin"), ("📌", "Auth Status", "auth_status"),
                ("📍", "State", "state")],
    ),
    "paninfo": dict(
        icon="🪪", title="PAN INFO", sub="PAN Database", cat="idn",
        base=FT_BASE, ep="paninfo", param="pan", kind="object",
        hint="PAN number bhejo\n<i>Example: BNZPM2501F</i>",
        fields=[
            ("🪪", "PAN", "pan"), ("👤", "Full Name", "customerName"),
            ("🔤", "First", "firstName"), ("🔤", "Middle", "middleName"),
            ("🔤", "Last", "lastName"), ("📅", "DOB", "dob"),
            ("📌", "Status", "panStatus"),
        ],
    ),
    "pantogstin": dict(
        icon="🪪", title="PAN TO GSTIN", sub="GST Database", cat="idn",
        base=FT_BASE, ep="pantogstin", param="pan", kind="records",
        hint="PAN number bhejo\n<i>Example: ANXPV7978A</i>",
        count_key="total",
        fields=[
            ("🧾", "GSTIN", "gstin"), ("🏢", "Legal Name", "lgnm"),
            ("🏪", "Trade Name", "tradeNam"), ("📌", "Status", "sts"),
            ("🏭", "Type", "ctb"), ("📋", "Duty", "dty"),
            ("📅", "Reg Date", "rgdt"), ("🏡", "Address", "pradr.address"),
        ],
    ),
    "gstin": dict(
        icon="🧾", title="GSTIN INFO", sub="GST Database", cat="idn",
        base=FT_BASE, ep="gstin", param="gstin", kind="object",
        hint="GSTIN bhejo\n<i>Example: 07AABCF8078M1Z3</i>",
        fields=[
            ("🧾", "GSTIN", "gstin"), ("🏢", "Legal Name", "lgnm"),
            ("🏪", "Trade Name", "tradeNam"), ("📌", "Status", "sts"),
            ("🏭", "Entity", "ctb"), ("📋", "Duty", "dty"),
            ("📅", "Reg Date", "rgdt"), ("🕒", "Last Update", "lstupdt"),
            ("⚖️", "State Juris", "stj"), ("⚖️", "Central Juris", "ctj"),
            ("📧", "E-Invoice", "einvoiceStatus"), ("🏡", "Address", "pradr.address"),
        ],
    ),
    "name2gstin": dict(
        icon="🔎", title="NAME TO GSTIN", sub="GST Database", cat="idn",
        base=FT_BASE, ep="name2gstin", param="name", kind="records",
        hint="Company / firm ka naam bhejo\n<i>Example: FLIPKART</i>",
        count_key="total",
        fields=[
            ("🧾", "GSTIN", "gstin"), ("🏢", "Company", "company"),
            ("🏪", "Trade Name", "trade_name"), ("📌", "Status", "status"),
            ("🏭", "Entity", "entity_type"), ("📋", "Business", "business_type"),
            ("📅", "Reg Date", "registration_date"), ("⚖️", "Jurisdiction", "jurisdiction"),
            ("🏡", "Address", "address"),
        ],
    ),
    "gstin2pan": dict(
        icon="🔄", title="GSTIN TO PAN", sub="PAN Database", cat="idn",
        base=FT_BASE, ep="gstin2pan", param="gstin", kind="object",
        hint="GSTIN bhejo\n<i>Example: 07AABCF8078M1Z3</i>",
        fields=[("🧾", "GSTIN", "gstin"), ("🪪", "PAN", "pan"),
                ("📍", "State", "state")],
    ),
    "gstreturns": dict(
        icon="🧾", title="GST RETURNS", sub="Returns Database", cat="idn",
        base=FT_BASE, ep="gstreturns", param="gstin", extra_param="financial_year",
        kind="records",
        hint="<b>GSTIN,FY</b> bhejo\n<i>Example: 07AABCF8078M1Z3,2023-24</i>",
        count_key="total_returns",
        fields=[
            ("📄", "Return", "return_type"), ("📅", "Period", "return_period"),
            ("🕒", "Filed On", "date_of_filing"), ("📌", "Status", "status"),
            ("🔖", "ARN", "arn"), ("📮", "Mode", "mode_of_filing"),
        ],
    ),
    "voter": dict(
        icon="🗳", title="VOTER ID LOOKUP", sub="Voter Database", cat="idn",
        base=FT_BASE, ep="voter", param="id", kind="custom",
        hint="EPIC number bhejo\n<i>Example: ZNO1150077</i>",
    ),

    # ── Utility ────────────────────────────────────────────────────
    "pincode": dict(
        icon="📍", title="PINCODE INFO", sub="Postal Database", cat="utl",
        base=FT_BASE, ep="pincode", param="pin", kind="custom",
        hint="6 digit pincode bhejo\n<i>Example: 110001</i>",
    ),
    "ifsc": dict(
        icon="🏦", title="IFSC INFO", sub="Bank Database", cat="utl",
        base=FT_BASE, ep="ifsc", param="ifsc", kind="custom",
        hint="IFSC code bhejo\n<i>Example: SBIN0001234</i>",
    ),
}

CATEGORIES = [
    ("num", "📞 Number & Leak", "number numleak address nametoinfo namesearch"),
    ("veh", "🚗 Vehicle & RC", "vehicle veh2num fastag challan rcpdf rcchip vinfo puc hw hpt vehindex"),
    ("idn", "🪪 Identity & GST", "aadhar family pan paninfo pantogstin gstin name2gstin gstin2pan gstreturns voter"),
    ("utl", "📍 Utility", "pincode ifsc"),
]


def btn_label(lid: str) -> str:
    lk = LOOKUPS[lid]
    return f"{lk['icon']} {lk['title'].title()}"

# ════════════════════════════════════════════════════════════════════
#  ░░ 5. CUSTOM PARSERS  ░░  (list[str] chunks return karte hai)
# ════════════════════════════════════════════════════════════════════

def p_numleak(p: dict) -> List[str]:
    chunks: List[str] = []
    for ckey, name in (("chain", "HiTeckGroop"), ("icmr", "ICMR 2025")):
        ch = p.get(ckey) or {}
        recs = ch.get("records") or []
        if not recs:
            continue
        chunks.append(pre(
            f"{SEP}\n◆ {bs(ch.get('title', name))} — {len(recs)} {sc('records')}\n{SEP}"
        ))
        if "FullName" in recs[0]:
            fields = [("📲", "Phone", "Phone"), ("👤", "Name", "FullName"),
                      ("👥", "Father", "FatherName"), ("💳", "Doc/Aadhaar", "DocumentNumber"),
                      ("🏡", "Address", "Adres")]
        else:
            fields = [("👤", "Name", "name"), ("🎂", "Age", "age"),
                      ("⚧", "Gender", "gender"), ("🏙", "District", "district"),
                      ("📍", "State", "state"), ("📲", "Phone", "phone")]
        chunks += record_blocks(recs, fields, len(recs), max_rows=4)
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
        return record_blocks(recs, fields, len(recs))
    return [auto_block({k: v for k, v in p.items() if k not in SKIP_KEYS})]


def p_vinfo(p: dict) -> List[str]:
    d = p.get("data") or {}
    cust = d.get("customer_details") or {}
    sg = (d.get("meta_data", {}).get("signzy_response", {}) or {}).get("result", {}) or {}
    rows = [
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
    ]
    return [pre(rows_cols(rows))]


def p_hw(p: dict) -> List[str]:
    veh = (p.get("vehicles") or [{}])[0]
    cust = veh.get("customer_details") or {}
    res = (veh.get("meta_data", {}).get("signzy_response", {}) or {}).get("result", {}) or {}
    rows = [
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
    ]
    return [pre(rows_cols(rows))]


def p_hpt(p: dict) -> List[str]:
    if p.get("success") is False:
        return [pre(f"❌ {esc(p.get('error', 'Provider unavailable'))}")]
    return [auto_block({k: v for k, v in p.items() if k not in SKIP_KEYS})]


def p_voter(p: dict) -> List[str]:
    recs = extract_records(p)
    if not recs:
        return [pre("❌ Koi voter record nahi mila.")]
    c = recs[0].get("content") or recs[0]
    rows = [
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
    ]
    return [pre(rows_cols(rows))]


def p_pincode(p: dict) -> List[str]:
    chunks = [pre(rows_cols([
        ("📮", "Pincode", p.get("pincode")),
        ("📍", "State", p.get("state")),
        ("🏙", "District", p.get("district")),
        ("🗺", "Division", p.get("division")),
        ("🌍", "Region", p.get("region")),
        ("🏳", "Country", p.get("country")),
        ("🏤", "Total Offices", p.get("total_offices")),
    ]))]
    offs = p.get("post_offices") or []
    if offs:
        chunks.append(pre(f"{SEP}\n🏤 {bs('POST OFFICES')} ({len(offs)})\n{SEP}"))
        fields = [("🏤", "Post Office", "name"), ("🏷", "Type", "branch_type"),
                  ("🚚", "Delivery", "delivery_status"), ("🏙", "District", "district")]
        chunks += record_blocks(offs, fields, len(offs), max_rows=8)
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
                    meta += f"{SEP}\n▪️ {sc(k.replace('_', ' '))} : {esc(p[k])}\n"
        if meta:
            chunks.append(pre(meta.rstrip()))
        chunks += record_blocks(recs, fields, len(recs), max_rows=10)
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
#  ░░ 6. API CALLER  ░░
# ════════════════════════════════════════════════════════════════════

def build_url(lk: dict, value: str) -> Tuple[str, Dict[str, str]]:
    key = FAM_KEY if lk["base"] == FAM_BASE else FT_KEY
    params = {"key": key, lk["param"]: value}
    if lk.get("extra_param"):
        parts = [x.strip() for x in value.split(",")]
        params[lk["param"]] = parts[0]
        params[lk["extra_param"]] = parts[1] if len(parts) > 1 else ""
    return f"{lk['base']}/{lk['ep']}", params


async def call_api(lk: dict, value: str) -> Tuple[bool, Any, float, str]:
    url, params = build_url(lk, value)
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as cx:
            r = await cx.get(url, params=params)
            elapsed = time.time() - t0
            try:
                return True, r.json(), elapsed, str(r.url)
            except Exception:                                  # noqa
                return True, {"_text": r.text}, elapsed, str(r.url)
    except Exception as e:                                     # noqa
        return False, f"{type(e).__name__}: {e}", time.time() - t0, url

# ════════════════════════════════════════════════════════════════════
#  ░░ 7. KEYBOARDS  ░░
# ════════════════════════════════════════════════════════════════════

def main_menu_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(t, callback_data=f"cat:{c}")] for c, t, _ in CATEGORIES]
    rows.append([
        InlineKeyboardButton("🆔 My ID", callback_data="myid"),
        InlineKeyboardButton("📖 Help", callback_data="help"),
    ])
    rows.append([
        InlineKeyboardButton("⌨️ Commands", callback_data="commands"),
        InlineKeyboardButton("ℹ️ About", callback_data="about"),
    ])
    if is_admin:
        rows.append([InlineKeyboardButton("👑 ADMIN PANEL", callback_data="admin:home")])
    return InlineKeyboardMarkup(rows)


def category_kb(cid: str) -> InlineKeyboardMarkup:
    ids = dict((c[0], c[2]) for c in CATEGORIES).get(cid, "").split()
    rows = [[InlineKeyboardButton(btn_label(lid), callback_data=f"lk:{lid}")] for lid in ids]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="menu")])
    return InlineKeyboardMarkup(rows)


def join_kb(channels: List[str]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"📢 Join {ch}", url=f"https://t.me/{ch.lstrip('@')}")]
            for ch in channels]
    rows.append([InlineKeyboardButton("✅ Joined — Verify", callback_data="checkjoin")])
    return InlineKeyboardMarkup(rows)


def admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Stats", callback_data="admin:stats"),
         InlineKeyboardButton("👥 Users", callback_data="admin:users")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin:broadcast")],
        [InlineKeyboardButton("🔗 Force Join List", callback_data="admin:channels"),
         InlineKeyboardButton("➕ Add Channel", callback_data="admin:addch")],
        [InlineKeyboardButton("🧾 API Error Log", callback_data="admin:errors"),
         InlineKeyboardButton("🗑 Clear Errors", callback_data="admin:clrerr")],
        [InlineKeyboardButton("⬅️ Main Menu", callback_data="menu")],
    ])

# ════════════════════════════════════════════════════════════════════
#  ░░ 8. FORCE JOIN  ░░
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
    if not user or user.is_bot:
        return True
    if await joined_all(context, user.id):
        return True
    txt = (
        "🔒 <b>Pehle Channel Join Karo!</b>\n\n"
        "Bot use karne ke liye neeche wale channel me join karna zaroori hai.\n"
        "Join karne ke baad <b>✅ Joined — Verify</b> dabao."
    )
    kb = join_kb(STORE.channels)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await update.effective_message.reply_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
    return False

# ════════════════════════════════════════════════════════════════════
#  ░░ 9. ERROR REPORT  ░░
# ════════════════════════════════════════════════════════════════════

async def report_error(context: ContextTypes.DEFAULT_TYPE, user, lk: dict,
                       value: str, err: str, url: str) -> None:
    STORE.log_error({"lookup": lk["ep"], "value": value, "error": err[:600],
                     "user": getattr(user, "id", 0)})
    msg = (
        "🚨 <b>API ERROR</b>\n"
        f"👤 {esc(getattr(user, 'full_name', '?'))} | <code>{getattr(user, 'id', 0)}</code>\n"
        f"🔗 <code>{esc(lk['title'])}</code> → <code>{esc(value)}</code>\n"
        f"🌐 <code>{esc(url)}</code>\n"
        f"📄 <code>{esc(err[:500])}</code>"
    )
    targets = list(ADMIN_IDS)
    try:
        if CHAT_ID:
            targets.append(int(CHAT_ID))
    except ValueError:
        pass
    for t in set(targets):
        try:
            await context.bot.send_message(t, msg, parse_mode=ParseMode.HTML)
        except TelegramError as e:
            log.warning("error DM fail %s: %s", t, e)

# ════════════════════════════════════════════════════════════════════
#  ░░ 10. LOOKUP EXECUTION  ░░
# ════════════════════════════════════════════════════════════════════

async def run_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE,
                     lid: str, value: str) -> None:
    lk = LOOKUPS[lid]
    msg = update.effective_message
    user = update.effective_user

    wait = await msg.reply_text(
        f"{lk['icon']} {bs(lk['title'])}\n🔍 <code>{esc(trunc(value, 60))}</code> dhoond raha hoon...",
        parse_mode=ParseMode.HTML,
    )

    ok, payload, elapsed, url = await call_api(lk, value)

    if not ok:
        await wait.edit_text(
            f"❌ <b>API ERROR</b>\n"
            f"🔗 {lk['icon']} {esc(lk['title'])}\n"
            f"📄 <code>{esc(str(payload)[:300])}</code>\n\n"
            f"👨‍💻 Dev ko DM kar diya gaya hai.",
            parse_mode=ParseMode.HTML,
        )
        await report_error(context, user, lk, value, str(payload), url)
        return

    chunks: List[str] = []

    try:
        # ── plain text (RC PDF / PUC) ─────────────────────────────
        if lk["kind"] == "text" or (isinstance(payload, dict) and payload.get("_text")):
            body = payload.get("_text", "") if isinstance(payload, dict) else str(payload)
            chunks.append(pre(make_header(lk, value)))
            chunks.append(pre(esc(body.strip()[:3000]) or "No data"))

        # ── custom ────────────────────────────────────────────────
        elif lk["kind"] == "custom":
            chunks.append(pre(make_header(lk, value)))
            chunks += CUSTOM_PARSERS[lk["ep"]](payload)

        # ── records ───────────────────────────────────────────────
        elif lk["kind"] == "records":
            recs = extract_records(payload)
            if not recs:
                chunks.append(pre(make_header(lk, value, 0) + "\n\n❌ Koi record nahi mila."))
            else:
                try:
                    total = int(payload.get(lk.get("count_key", "total"), len(recs)))
                except Exception:                              # noqa
                    total = len(recs)
                total = total or len(recs)
                pages = max(1, math.ceil(total / MAX_ROWS))
                chunks.append(pre(make_header(lk, value, total, pages)))
                chunks += record_blocks(recs, lk["fields"], total)

        # ── object ────────────────────────────────────────────────
        else:
            data = payload.get("data", payload) if isinstance(payload, dict) else payload
            if not isinstance(data, dict):
                data = {}
            chunks.append(pre(
                make_header(lk, value) + "\n\n" +
                rows_cols([(e, l, get_path(data, p)) for e, l, p in lk["fields"]])
            ))

    except Exception as e:                                        # noqa
        await wait.edit_text(
            f"⚠️ <b>Parse Error</b>\n<code>{esc(type(e).__name__)}: {esc(str(e)[:200])}</code>\n\n"
            f"👨‍💻 Dev ko DM kar diya gaya hai.",
            parse_mode=ParseMode.HTML,
        )
        await report_error(context, user, lk, value, f"{type(e).__name__}: {e}", url)
        return

    chunks.append(footer(elapsed))
    await wait.delete()
    await send_chunks(msg, chunks, parse_mode=ParseMode.HTML)
    STORE.bump(user.id)

# ════════════════════════════════════════════════════════════════════
#  ░░ 11. STATIC TEXTS  ░░
# ════════════════════════════════════════════════════════════════════

START_TXT = (
    "╔══════════════════════════╗\n"
    "   🕵️ <b>OSINT LOOKUP BOT</b>\n"
    "╚══════════════════════════╝\n\n"
    "📞 Number & Leak\n🚗 Vehicle & RC\n🪪 Aadhaar / PAN / GST\n"
    "👨‍👩‍👧 Family ID\n📍 Pincode & IFSC\n\n"
    "Neeche se category chuno 👇\n"
    "<i>Tip: /commands se saari commands dekho.</i>"
)

HELP_TXT = (
    "📖 <b>HELP / GUIDE</b>\n"
    f"{DIVIDER}\n\n"
    "<b>Kaise use kare?</b>\n"
    "1️⃣ Category chuno\n2️⃣ Lookup button dabao\n"
    "3️⃣ Value bhejo — result turant milega\n\n"
    "<b>Input format:</b>\n"
    "• 📞 Number: <code>9876543210</code>\n"
    "• 🚗 Vehicle: <code>KA01AB1234</code>\n"
    "• 🆔 Aadhaar: 12 digits\n"
    "• 🪪 PAN: <code>ABCDE1234F</code>\n"
    "• 🧾 GSTIN: 15 characters\n"
    "• 👤 Namesearch: <code>Naam,Sheher</code>\n"
    "• 🧾 GST Returns: <code>GSTIN,2023-24</code>\n\n"
    "<b>Group me:</b> bot ko mention ya reply karo.\n\n"
    f"{DIVIDER}\n{BUY_LINE}\n{BY_LINE}\n{DIVIDER}\n{DISCLAIMER}"
)

COMMANDS_TXT = (
    "⌨️ <b>COMMAND LIST</b>\n"
    f"{DIVIDER}\n\n"
    "/start — 🚀 Bot start / main menu\n"
    "/menu — 📋 Main menu kholo\n"
    "/help — 📖 Poori guide\n"
    "/commands — ⌨️ Ye list\n"
    "/id — 🆔 Apni Telegram ID\n"
    "/about — ℹ️ Bot info\n"
    "/cancel — ❌ Current lookup cancel\n"
    "/stats — 📊 Bot stats\n"
    "/admin — 👑 Admin panel\n"
    "/broadcast — 📢 Broadcast (admin)\n\n"
    "<i>Baaki sab kuch buttons se chalta hai.</i>"
)

ABOUT_TXT = (
    "ℹ️ <b>ABOUT</b>\n"
    f"{DIVIDER}\n\n"
    "🕵️ <b>OSINT Lookup Bot</b>\n"
    "Number • Leak • Address • Vehicle • RC • Aadhaar\n"
    "PAN • GST • Family ID • Voter • Pincode • IFSC\n\n"
    f"🛒 {BUY_LINE}\n👨‍💻 {BY_LINE}\n\n"
    f"{DIVIDER}\n{DISCLAIMER}"
)

# ════════════════════════════════════════════════════════════════════
#  ░░ 12. HANDLERS  ░░
# ════════════════════════════════════════════════════════════════════

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u = update.effective_user
    if u and not u.is_bot:
        STORE.add_user(u)
    if not await gate(update, context):
        return
    context.user_data.pop("await", None)
    context.user_data.pop("state", None)
    await update.effective_message.reply_text(
        START_TXT, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(is_admin(u.id))
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await gate(update, context):
        return
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
    context.user_data.pop("await", None)
    context.user_data.pop("state", None)
    await update.effective_message.reply_text(
        "❌ Cancel kar diya. Menu wapas 👇",
        reply_markup=main_menu_kb(is_admin(update.effective_user.id)))


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await gate(update, context):
        return
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("❌ Ye admin panel nahi hai.")
        return
    await update.effective_message.reply_text(
        "👑 <b>ADMIN PANEL</b>\nKya karna hai?", parse_mode=ParseMode.HTML, reply_markup=admin_kb()
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("❌ Admin only.")
        return
    await update.effective_message.reply_text(
        f"📊 <b>STATS</b>\n\n"
        f"👥 Users: <code>{len(STORE.users)}</code>\n"
        f"🔍 Lookups: <code>{STORE.stats.get('lookups', 0)}</code>\n"
        f"🚨 API Errors: <code>{STORE.stats.get('errors', 0)}</code>\n"
        f"📢 Channels: <code>{len(STORE.channels)}</code>\n"
        f"🕒 {datetime.utcnow().strftime('%d-%m-%Y %H:%M')} UTC",
        parse_mode=ParseMode.HTML, reply_markup=admin_kb())


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("❌ Admin only.")
        return
    context.user_data["state"] = "broadcast"
    await update.effective_message.reply_text(
        "📢 <b>BROADCAST MODE</b>\n\nJo message bhejna hai wo bhejo "
        "(text / photo / koi bhi).\nCancel: /cancel", parse_mode=ParseMode.HTML)


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u = update.effective_user
    c = update.effective_chat
    await update.effective_message.reply_text(
        f"🆔 <b>Your ID:</b> <code>{u.id}</code>\n"
        f"💬 <b>Chat ID:</b> <code>{c.id}</code>\n"
        f"📛 <b>Type:</b> {c.type}\n"
        f"👑 <b>Admin:</b> {'Yes' if is_admin(u.id) else 'No'}",
        parse_mode=ParseMode.HTML,
    )


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if not msg or not msg.text:
        return
    user = update.effective_user
    if not user or user.is_bot:
        return

    if context.user_data.get("state") == "broadcast" and is_admin(user.id):
        context.user_data.pop("state", None)
        await do_broadcast(update, context, msg)
        return

    if context.user_data.get("state") == "addch" and is_admin(user.id):
        context.user_data.pop("state", None)
        ch = msg.text.strip()
        if not ch.startswith("@"):
            ch = "@" + ch
        if ch not in STORE.channels:
            STORE.channels.append(ch)
            STORE.save()
        await msg.reply_text(f"✅ Channel add ho gaya: <code>{esc(ch)}</code>\n"
                             f"Ab force-join list: {', '.join(STORE.channels)}",
                             parse_mode=ParseMode.HTML)
        return

    in_group = msg.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
    if in_group and not context.user_data.get("await"):
        me = await context.bot.get_me()
        mentioned = f"@{me.username}".lower() in msg.text.lower()
        replied = bool(msg.reply_to_message and msg.reply_to_message.from_user
                       and msg.reply_to_message.from_user.id == me.id)
        if not (mentioned or replied):
            return

    if not await gate(update, context):
        return

    value = msg.text.strip()
    if in_group:
        value = value.replace(f"@{context.bot.username}", "").strip()

    lid = context.user_data.get("await")
    if not lid:
        await msg.reply_text("Neeche se koi lookup chuno 👇",
                             reply_markup=main_menu_kb(is_admin(user.id)))
        return

    context.user_data.pop("await", None)
    await run_lookup(update, context, lid, value)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    data = q.data
    user = q.from_user

    if data == "checkjoin":
        if await joined_all(context, user.id):
            await q.answer("✅ Verified! Welcome")
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
            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(is_admin(user.id)),
        )
        return

    if data.startswith("cat:"):
        cid = data.split(":", 1)[1]
        title = dict((c[0], c[1]) for c in CATEGORIES).get(cid, "Menu")
        await q.message.edit_text(f"<b>{title}</b>\n\nKonsi lookup chahiye?",
                                  parse_mode=ParseMode.HTML, reply_markup=category_kb(cid))
        return

    if data.startswith("lk:"):
        lid = data.split(":", 1)[1]
        lk = LOOKUPS[lid]
        context.user_data["await"] = lid
        await q.message.edit_text(
            f"{lk['icon']} {bs(lk['title'])}\n\n{lk['hint']}\n\n<i>Value type karke bhejo.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Cancel", callback_data="menu")]]),
        )
        return

    if data.startswith("admin:"):
        if not is_admin(user.id):
            await q.answer("Admin only", show_alert=True)
            return
        await admin_router(update, context, data.split(":", 1)[1])
        return


async def admin_router(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str) -> None:
    q = update.callback_query
    if action == "home":
        await q.message.edit_text("👑 <b>ADMIN PANEL</b>", parse_mode=ParseMode.HTML,
                                  reply_markup=admin_kb())
    elif action == "stats":
        await q.message.edit_text(
            f"📊 <b>STATS</b>\n\n"
            f"👥 Users: <code>{len(STORE.users)}</code>\n"
            f"🔍 Lookups: <code>{STORE.stats.get('lookups', 0)}</code>\n"
            f"🚨 API Errors: <code>{STORE.stats.get('errors', 0)}</code>\n"
            f"📢 Force Channels: <code>{len(STORE.channels)}</code>\n"
            f"🕒 {datetime.utcnow().strftime('%d-%m-%Y %H:%M')} UTC",
            parse_mode=ParseMode.HTML, reply_markup=admin_kb())
    elif action == "users":
        top = sorted(STORE.users.values(), key=lambda x: x.get("lookups", 0), reverse=True)[:10]
        body = "\n".join(
            f"{i+1}. {esc(u['name'][:20])} — <code>{u['id']}</code> — {u.get('lookups', 0)}🔍"
            for i, u in enumerate(top)) or "Koi user nahi."
        await q.message.edit_text(f"👥 <b>TOP USERS</b>\n\n{body}", parse_mode=ParseMode.HTML,
                                  reply_markup=admin_kb())
    elif action == "broadcast":
        context.user_data["state"] = "broadcast"
        await q.message.edit_text(
            "📢 <b>BROADCAST</b>\n\nJo message bhejna hai wo bhejo (text/photo/koi bhi).\n"
            "Cancel ke liye /cancel.", parse_mode=ParseMode.HTML)
    elif action == "channels":
        body = "\n".join(f"• <code>{esc(c)}</code>" for c in STORE.channels) or "Koi nahi."
        await q.message.edit_text(f"🔗 <b>FORCE JOIN CHANNELS</b>\n\n{body}",
                                  parse_mode=ParseMode.HTML, reply_markup=admin_kb())
    elif action == "addch":
        context.user_data["state"] = "addch"
        await q.message.edit_text("➕ Channel ka @username bhejo (jaise @MyChannel)")
    elif action == "errors":
        if not STORE.errors:
            await q.message.edit_text("🧾 Koi error nahi. Sab clean ✅", reply_markup=admin_kb())
            return
        lines = [
            f"• <code>{esc(e['lookup'])}</code> | <code>{esc(e['value'][:18])}</code>\n"
            f"  <i>{esc(e['error'][:90])}</i>"
            for e in STORE.errors[-8:]
        ]
        await q.message.edit_text("🧾 <b>LAST API ERRORS</b>\n\n" + "\n".join(lines),
                                  parse_mode=ParseMode.HTML, reply_markup=admin_kb())
    elif action == "clrerr":
        STORE.errors = []
        STORE.save()
        await q.message.edit_text("🗑 Error log clear ho gaya.", reply_markup=admin_kb())


async def do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, msg) -> None:
    sent = failed = 0
    for uid in list(STORE.users.keys()):
        try:
            await msg.copy(chat_id=int(uid))
            sent += 1
            await asyncio.sleep(0.05)
        except TelegramError:
            failed += 1
    await msg.reply_text(f"✅ Broadcast done\n✔️ Sent: {sent}\n❌ Failed: {failed}")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Handler error", exc_info=context.error)
    for t in set(ADMIN_IDS):
        try:
            await context.bot.send_message(
                t, f"🧨 <b>BOT ERROR</b>\n<code>{esc(str(context.error)[:400])}</code>",
                parse_mode=ParseMode.HTML)
        except TelegramError:
            pass


async def post_init(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand("start", "🚀 Bot start / main menu"),
        BotCommand("menu", "📋 Main menu"),
        BotCommand("help", "📖 Guide / input format"),
        BotCommand("commands", "⌨️ Saari commands"),
        BotCommand("id", "🆔 Apni Telegram ID"),
        BotCommand("about", "ℹ️ Bot ke baare me"),
        BotCommand("cancel", "❌ Cancel current lookup"),
        BotCommand("stats", "📊 Bot stats"),
        BotCommand("admin", "👑 Admin panel"),
        BotCommand("broadcast", "📢 Broadcast (admin)"),
    ])
    me = await app.bot.get_me()
    log.info("Bot up: @%s", me.username)

# ════════════════════════════════════════════════════════════════════
#  ░░ 13. MAIN  ░░
# ════════════════════════════════════════════════════════════════════

def main() -> None:
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .concurrent_updates(True)
        .build()
    )

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
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)

    log.info("Polling start...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()