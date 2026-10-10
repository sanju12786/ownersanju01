# -*- coding: utf-8 -*-
"""
==========================================================================
   SMM PANEL TELEGRAM BOT  -  FULL VERSION (English, icon based UI)
==========================================================================
Install :  pkg update -y && pkg install python -y
           pip install pyTelegramBotAPI requests
Run     :  python smm_bot.py

Only the CONFIG block below is needed for the first run. Everything else
(API URL, API key, UPI ID, gateway, channels, markup, welcome text) can be
changed later from the bot's ADMIN PANEL and is stored in smm.db.
"""
import telebot, sqlite3, requests, threading, time, html, urllib.parse
from telebot import types

# ============================ CONFIG ======================================
BOT_TOKEN = "8753100894:AAHl401BCF6zA3aM6RYoamit5KUrnlHqR1Y"   # <-- BOT TOKEN

# SUPER ADMIN CHAT IDs (each of these can open the admin panel)
ADMIN_IDS = [
    5574675470,   # <-- ADMIN CHAT ID 1
    0,            # <-- ADMIN CHAT ID 2  (replace 0 with the second chat id)
]

# These values are saved to the database only on the FIRST run.
# Change them later from Admin Panel -> API Settings / Payment Settings.
DEFAULT_API_URL = "https://smmresell.com/api/v2"        # <-- API URL
DEFAULT_API_KEY = "0e56664ec1750b55f00c3a44dc080830"    # <-- API KEY
DEFAULT_UPI_ID  = "2008vivek@fam"                       # <-- UPI ID

DB_FILE  = "smm.db"
PER_PAGE = 8
# ==========================================================================

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
conn.row_factory = sqlite3.Row
lock = threading.Lock()
st = {}  # per-user temporary state


# ============================== DATABASE ==================================
def db(sql, args=(), fetch=None):
    with lock:
        cur = conn.execute(sql, args)
        if fetch == "one":
            res = cur.fetchone()
        elif fetch == "all":
            res = cur.fetchall()
        else:
            res = cur.lastrowid
        conn.commit()
        return res


def scalar(sql, args=()):
    r = db(sql, args, "one")
    return r[0] if r and r[0] is not None else 0


def init_db():
    with lock:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, username TEXT,
            balance REAL DEFAULT 0, banned INTEGER DEFAULT 0, joined TEXT);
        CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE, hidden INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS services(id INTEGER PRIMARY KEY, cat_id INTEGER, name TEXT,
            api_rate REAL, min INTEGER, max INTEGER, refill INTEGER DEFAULT 0,
            cancel INTEGER DEFAULT 0, hidden INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            service_id INTEGER, link TEXT, qty INTEGER, charge REAL, api_order TEXT,
            status TEXT DEFAULT 'Pending', refunded INTEGER DEFAULT 0, created TEXT);
        CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            amount REAL, utr TEXT, file_id TEXT, status TEXT DEFAULT 'Pending',
            method TEXT DEFAULT 'manual', created TEXT);
        CREATE TABLE IF NOT EXISTS channels(id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT UNIQUE,
            title TEXT, link TEXT);
        CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        """)
        defaults = {
            "api_url": DEFAULT_API_URL, "api_key": DEFAULT_API_KEY,
            "upi_id": DEFAULT_UPI_ID, "upi_name": "SMM Panel",
            "gw_name": "FamPay / BharatPay", "gw_merchant": "", "gw_token": "",
            "gw_url": "", "gw_auto": "0",
            "markup": "20", "min_deposit": "10", "support": "@YourSupport",
            "maintenance": "0", "bot_name": "SMM Panel",
            "welcome": "🚀 Fast, cheap and reliable social media services!\n"
                       "📸 Followers  ❤️ Likes  👁 Views  🔔 Subscribers and more.\n\n"
                       "👇 Choose an option from the menu below.",
        }
        for k, v in defaults.items():
            conn.execute("INSERT OR IGNORE INTO settings VALUES(?,?)", (k, v))
        conn.commit()


def setting(k):
    r = db("SELECT value FROM settings WHERE key=?", (k,), "one")
    return r["value"] if r else ""


def set_setting(k, v):
    db("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))


# ============================== HELPERS ===================================
def e(s):
    return html.escape(str(s))


def now():
    return time.strftime("%Y-%m-%d %H:%M")


def mask(v):
    v = str(v or "")
    if not v:
        return "not set"
    return v[:4] + "•••••" + v[-3:] if len(v) > 9 else "•••••"


def is_super(uid):
    return uid != 0 and uid in ADMIN_IDS


def is_admin(uid):
    if is_super(uid):
        return True
    return db("SELECT 1 FROM admins WHERE id=?", (uid,), "one") is not None


def all_admin_ids():
    ids = {a for a in ADMIN_IDS if a}
    ids |= {r["id"] for r in db("SELECT id FROM admins", fetch="all")}
    return list(ids)


def api(**p):
    p["key"] = setting("api_key")
    try:
        return requests.post(setting("api_url"), data=p, timeout=40).json()
    except Exception as ex:
        return {"error": str(ex)}


def price(rate):
    return round(float(rate) * (1 + float(setting("markup")) / 100), 4)


def ensure(u):
    r = db("SELECT * FROM users WHERE id=?", (u.id,), "one")
    if not r:
        db("INSERT INTO users(id,name,username,joined) VALUES(?,?,?,?)",
           (u.id, u.first_name or "", u.username or "", now()))
        r = db("SELECT * FROM users WHERE id=?", (u.id,), "one")
    return r


def get_user(uid):
    return db("SELECT * FROM users WHERE id=?", (uid,), "one")


def add_bal(uid, amt):
    db("UPDATE users SET balance=balance+? WHERE id=?", (amt, uid))


# Icon picked from the category / service name
ICONS = [
    ("instagram", "📸"), ("youtube", "▶️"), ("facebook", "👍"), ("telegram", "✈️"),
    ("tiktok", "🎵"), ("twitter", "🐦"), ("whatsapp", "💬"), ("spotify", "🎧"),
    ("linkedin", "💼"), ("snapchat", "👻"), ("google", "🔍"), ("website", "🌐"),
    ("traffic", "🌐"), ("follower", "👥"), ("subscriber", "🔔"), ("like", "❤️"),
    ("view", "👁"), ("comment", "💭"), ("share", "🔁"), ("member", "👥"),
    ("watch", "⏱"), ("live", "🔴"), ("story", "⭕"), ("reel", "🎬"), ("music", "🎶"),
]


def icon_for(name):
    n = str(name).lower()
    for key, ic in ICONS:
        if key in n:
            return ic
    return "📁"


# ============================== KEYBOARDS =================================
B_SERV, B_ORDER = "📦 Services", "🛒 New Order"
B_BAL, B_ADD = "💰 Balance", "💳 Add Balance"
B_STAT, B_HIST = "📊 Order Status", "🧾 My Orders"
B_HELP, B_SUP, B_ADM = "❓ Help", "🎧 Support", "👑 Admin Panel"


def menu(uid):
    k = types.ReplyKeyboardMarkup(resize_keyboard=True)
    k.row(B_SERV, B_ORDER)
    k.row(B_BAL, B_ADD)
    k.row(B_STAT, B_HIST)
    k.row(B_HELP, B_SUP)
    if is_admin(uid):
        k.row(B_ADM)
    return k


def ikb(rows):
    """rows = [[(text, data), ...], ...]   data starting with http becomes a URL button."""
    k = types.InlineKeyboardMarkup()
    for r in rows:
        btns = []
        for t, d in r:
            if str(d).startswith("http"):
                btns.append(types.InlineKeyboardButton(t, url=d))
            else:
                btns.append(types.InlineKeyboardButton(t, callback_data=d))
        k.row(*btns)
    return k


# ============================== FORCE JOIN ================================
def missing_channels(uid):
    miss = []
    for ch in db("SELECT * FROM channels", fetch="all"):
        try:
            m = bot.get_chat_member(ch["chat_id"], uid)
            if m.status in ("left", "kicked"):
                miss.append(ch)
        except Exception:
            pass  # bot is not admin in that channel -> skip the check
    return miss


def gate(uid, chat_id):
    """True = continue. False = user still has to join a channel."""
    if is_admin(uid):
        return True
    miss = missing_channels(uid)
    if not miss:
        return True
    rows = [[(f"📣 Join {c['title'][:30]}", c["link"])] for c in miss if c["link"]]
    rows.append([("✅ I Have Joined", "joined")])
    bot.send_message(chat_id, "🔒 <b>Please join our channel(s) to use this bot.</b>\n\n"
                              "After joining, tap <b>✅ I Have Joined</b>.", reply_markup=ikb(rows))
    return False


# ============================== START / INFO ==============================
@bot.message_handler(commands=["start"])
def start(m):
    u = ensure(m.from_user)
    uid = m.from_user.id
    if u["banned"] and not is_admin(uid):
        return bot.send_message(m.chat.id, "🚫 You are banned.")
    st.pop(uid, None)
    if not gate(uid, m.chat.id):
        return
    send_welcome(m.chat.id, m.from_user)


def send_welcome(chat_id, user):
    u = get_user(user.id)
    adm = "\n👑 <b>Admin verified ✅</b>" if is_admin(user.id) else ""
    bot.send_message(
        chat_id,
        f"👋 <b>Welcome {e(user.first_name)}!</b>\n"
        f"━━━━━━━━━━━━━━━━\n🌟 <b>{e(setting('bot_name'))}</b>\n\n{e(setting('welcome'))}\n"
        f"━━━━━━━━━━━━━━━━\n🆔 ID: <code>{u['id']}</code>\n💰 Balance: <b>₹{u['balance']:.2f}</b>{adm}",
        reply_markup=menu(user.id))


@bot.message_handler(commands=["admin"])
def admin_cmd(m):
    if is_admin(m.from_user.id):
        admin_panel(m.chat.id)


def help_msg(m):
    bot.send_message(m.chat.id,
        "❓ <b>Help</b>\n━━━━━━━━━━━━━━━━\n"
        "💳 <b>Add Balance</b> → enter amount → pay with the QR → send UTR and screenshot → admin approves.\n\n"
        "📦 <b>Services</b> → pick a category → pick a service → Order Now.\n\n"
        "🛒 <b>New Order</b> → Service ID → Link → Quantity → Confirm.\n\n"
        "📊 <b>Order Status</b> → enter order ID to see status, refill or cancel.\n\n"
        f"🎧 Support: {e(setting('support'))}")


def support_msg(m):
    bot.send_message(m.chat.id, f"🎧 <b>Support</b>\n\nNeed help? Contact: {e(setting('support'))}")


def balance_msg(m):
    u = get_user(m.from_user.id)
    bot.send_message(m.chat.id, f"💰 <b>Your Balance</b>\n\n🆔 ID: <code>{u['id']}</code>\n💵 Balance: <b>₹{u['balance']:.2f}</b>")


# ============================== SERVICES BROWSE ===========================
def cat_page(chat_id, page=0, msg=None):
    cats = db("""SELECT c.id,c.name,(SELECT COUNT(*) FROM services s WHERE s.cat_id=c.id AND s.hidden=0) n
                 FROM categories c WHERE c.hidden=0 ORDER BY c.id""", fetch="all")
    cats = [c for c in cats if c["n"] > 0]
    if not cats:
        return bot.send_message(chat_id, "❌ No services yet. Ask the admin to sync services.")
    tot = (len(cats) - 1) // PER_PAGE + 1
    page = max(0, min(page, tot - 1))
    rows = [[(f"{icon_for(c['name'])} {c['name'][:38]} ({c['n']})", f"svl:{c['id']}:0")]
            for c in cats[page * PER_PAGE:(page + 1) * PER_PAGE]]
    nav = []
    if page > 0: nav.append(("⬅️ Prev", f"cat:{page-1}"))
    nav.append((f"📄 {page+1}/{tot}", "noop"))
    if page < tot - 1: nav.append(("Next ➡️", f"cat:{page+1}"))
    rows.append(nav)
    txt = "📦 <b>Choose a category:</b>"
    if msg:
        try: return bot.edit_message_text(txt, chat_id, msg, reply_markup=ikb(rows))
        except Exception: return
    bot.send_message(chat_id, txt, reply_markup=ikb(rows))


def svc_page(chat_id, msg, cid, page):
    c = db("SELECT name FROM categories WHERE id=?", (cid,), "one")
    sv = db("SELECT * FROM services WHERE cat_id=? AND hidden=0 ORDER BY id", (cid,), "all")
    tot = max(1, (len(sv) - 1) // PER_PAGE + 1)
    page = max(0, min(page, tot - 1))
    rows = [[(f"{icon_for(s['name'])} {s['id']} • {s['name'][:30]} • ₹{price(s['api_rate']):.2f}", f"svc:{s['id']}")]
            for s in sv[page * PER_PAGE:(page + 1) * PER_PAGE]]
    nav = []
    if page > 0: nav.append(("⬅️ Prev", f"svl:{cid}:{page-1}"))
    nav.append((f"📄 {page+1}/{tot}", "noop"))
    if page < tot - 1: nav.append(("Next ➡️", f"svl:{cid}:{page+1}"))
    rows.append(nav)
    rows.append([("🔙 Categories", "cat:0")])
    bot.edit_message_text(f"{icon_for(c['name'])} <b>{e(c['name'])}</b>\n<i>Rate per 1000</i>", chat_id, msg, reply_markup=ikb(rows))


def svc_text(s):
    c = db("SELECT name FROM categories WHERE id=?", (s["cat_id"],), "one")
    return (f"{icon_for(s['name'])} <b>{e(s['name'])}</b>\n━━━━━━━━━━━━━━━━\n"
            f"🔢 Service ID: <code>{s['id']}</code>\n📁 Category: {e(c['name'] if c else '-')}\n"
            f"💰 Rate / 1000: <b>₹{price(s['api_rate']):.2f}</b>\n"
            f"📉 Min: {s['min']}   📈 Max: {s['max']}\n"
            f"♻️ Refill: {'✅' if s['refill'] else '❌'}   🛑 Cancel: {'✅' if s['cancel'] else '❌'}")


def get_service(sid):
    return db("""SELECT s.* FROM services s JOIN categories c ON c.id=s.cat_id
                 WHERE s.id=? AND s.hidden=0 AND c.hidden=0""", (sid,), "one")


# ============================== ORDER FLOW ================================
def new_order_prompt(m):
    st[m.from_user.id] = {"step": "sid"}
    bot.send_message(m.chat.id, "🔢 Send the <b>Service ID</b>:\n(You can see IDs in the Services menu)\n\n❌ Send /start to cancel.")


def ask_link(uid, chat_id, s):
    st[uid] = {"step": "link", "sid": s["id"]}
    bot.send_message(chat_id, svc_text(s) + "\n\n🔗 Now send your <b>Link</b>:")


def place_order(uid, chat_id):
    s = st.get(uid)
    if not s or "qty" not in s:
        return bot.send_message(chat_id, "❌ Session expired. Please start a New Order again.")
    sv = get_service(s["sid"])
    if not sv:
        st.pop(uid, None)
        return bot.send_message(chat_id, "❌ This service is no longer available.")
    u = get_user(uid)
    charge = round(price(sv["api_rate"]) * s["qty"] / 1000, 4)
    if u["balance"] < charge:
        st.pop(uid, None)
        return bot.send_message(chat_id, f"❌ Not enough balance!\nRequired: ₹{charge:.2f}\nYour balance: ₹{u['balance']:.2f}\n\n💳 Please add balance.")
    r = api(action="add", service=sv["id"], link=s["link"], quantity=s["qty"])
    st.pop(uid, None)
    if isinstance(r, dict) and "order" in r:
        add_bal(uid, -charge)
        oid = db("INSERT INTO orders(user_id,service_id,link,qty,charge,api_order,created) VALUES(?,?,?,?,?,?,?)",
                 (uid, sv["id"], s["link"], s["qty"], charge, str(r["order"]), now()))
        bot.send_message(chat_id, f"✅ <b>Order Placed!</b>\n━━━━━━━━━━━━━━━━\n🆔 Order ID: <code>{oid}</code>\n"
                         f"{icon_for(sv['name'])} {e(sv['name'])}\n🔢 Quantity: {s['qty']}\n💸 Charge: ₹{charge:.2f}",
                         reply_markup=ikb([[("📊 Check Status", f"ost:{oid}")]]))
    else:
        err = r.get("error", r) if isinstance(r, dict) else r
        bot.send_message(chat_id, f"❌ Order failed: {e(err)}\nYour balance was not deducted.")


def refresh_order(o):
    r = api(action="status", order=o["api_order"])
    if isinstance(r, dict) and "status" in r:
        status = str(r["status"])
        db("UPDATE orders SET status=? WHERE id=?", (status, o["id"]))
        low = status.lower()
        if not o["refunded"]:
            if low in ("canceled", "cancelled", "refunded"):
                add_bal(o["user_id"], o["charge"])
                db("UPDATE orders SET refunded=1 WHERE id=?", (o["id"],))
            elif low == "partial":
                try:
                    back = round(o["charge"] * float(r.get("remains", 0)) / o["qty"], 4)
                    add_bal(o["user_id"], back)
                    db("UPDATE orders SET refunded=1 WHERE id=?", (o["id"],))
                except Exception:
                    pass
    return r if isinstance(r, dict) else {}


def order_view(chat_id, oid, uid, edit=None):
    o = db("SELECT * FROM orders WHERE id=?", (oid,), "one")
    if not o or (o["user_id"] != uid and not is_admin(uid)):
        return bot.send_message(chat_id, "❌ Order not found.")
    r = refresh_order(o)
    o = db("SELECT * FROM orders WHERE id=?", (oid,), "one")
    sv = db("SELECT * FROM services WHERE id=?", (o["service_id"],), "one")
    txt = (f"📊 <b>Order #{o['id']}</b>\n━━━━━━━━━━━━━━━━\n📦 {e(sv['name'] if sv else o['service_id'])}\n"
           f"🔗 {e(o['link'])}\n🔢 Quantity: {o['qty']}\n💸 Charge: ₹{o['charge']:.2f}\n"
           f"📌 Status: <b>{e(o['status'])}</b>\n")
    if "start_count" in r:
        txt += f"▶️ Start count: {e(r['start_count'])}   ⏳ Remains: {e(r.get('remains', '-'))}\n"
    btn = [[("🔄 Refresh", f"ost:{oid}")]]
    if sv and sv["refill"]: btn[0].append(("♻️ Refill", f"rf:{oid}"))
    if sv and sv["cancel"]: btn[0].append(("🛑 Cancel", f"cn:{oid}"))
    if edit:
        try: return bot.edit_message_text(txt, chat_id, edit, reply_markup=ikb(btn))
        except Exception: return
    bot.send_message(chat_id, txt, reply_markup=ikb(btn))


def history(m):
    os_ = db("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10", (m.from_user.id,), "all")
    if not os_:
        return bot.send_message(m.chat.id, "📭 You have not placed any orders yet.")
    rows = [[(f"🧾 #{o['id']} • {o['qty']} • {o['status']}", f"ost:{o['id']}")] for o in os_]
    bot.send_message(m.chat.id, "🧾 <b>Your last 10 orders</b>", reply_markup=ikb(rows))


def status_prompt(m):
    st[m.from_user.id] = {"step": "ostatus"}
    bot.send_message(m.chat.id, "🆔 Send your <b>Order ID</b>:")


# ============================== PAYMENTS ==================================
def add_prompt(m):
    st[m.from_user.id] = {"step": "amount"}
    bot.send_message(m.chat.id, f"💳 <b>Add Balance</b>\n\nHow much do you want to add? Send the amount in ₹.\n"
                                f"Minimum: ₹{setting('min_deposit')}")


def send_qr(uid, chat_id, amt):
    upi_id = setting("upi_id")
    upi = (f"upi://pay?pa={upi_id}&pn={urllib.parse.quote(setting('upi_name'))}"
           f"&am={amt}&cu=INR&tn=Bal{uid}")
    url = "https://api.qrserver.com/v1/create-qr-code/?size=500x500&data=" + urllib.parse.quote(upi)
    caption = (f"📱 <b>Pay ₹{amt}</b>\n━━━━━━━━━━━━━━━━\n🏦 UPI ID: <code>{e(upi_id)}</code>\n💰 Amount: <b>₹{amt}</b>\n\n"
               "1️⃣ Scan the QR and pay the exact amount\n2️⃣ Tap <b>I Have Paid</b>\n"
               "3️⃣ Send your UTR number and screenshot\n4️⃣ Admin will approve ✅")
    kb = ikb([[("✅ I Have Paid", "paid"), ("❌ Cancel", "pcancel")]])
    try:
        img = requests.get(url, timeout=30).content
        bot.send_photo(chat_id, img, caption=caption, reply_markup=kb)
    except Exception:
        bot.send_message(chat_id, caption + "\n\n(QR could not load, please pay to the UPI ID)", reply_markup=kb)


def gateway_verify(utr, amt):
    """
    OPTIONAL auto-verify. Set Gateway URL, Merchant ID and Token in
    Admin Panel -> Payment Settings and turn Auto Verify ON.
    Adjust the data keys and the success check below to match the real API
    docs of your gateway (FamPay / BharatPay etc). If it fails, the payment
    simply goes to manual admin approval.
    """
    url = setting("gw_url")
    if setting("gw_auto") != "1" or not url:
        return False
    try:
        r = requests.post(url, data={"merchant_id": setting("gw_merchant"), "token": setting("gw_token"),
                                     "utr": utr, "amount": amt}, timeout=25).json()
        status = str(r.get("status", "")).lower()
        return status in ("success", "paid", "completed", "true") or r.get("success") is True
    except Exception:
        return False


def pay_card(p):
    return (f"💳 <b>Payment #{p['id']}</b>\n👤 User: <code>{p['user_id']}</code>\n💰 Amount: <b>₹{p['amount']}</b>\n"
            f"🧾 UTR: <code>{e(p['utr'])}</code>\n📌 Status: {p['status']}\n🕒 {p['created']}")


def pay_kb(pid):
    return ikb([[("✅ Approve", f"apr:{pid}"), ("❌ Reject", f"rej:{pid}")]])


# ============================== ADMIN PANEL ===============================
def admin_panel(chat_id, edit=None):
    rows = [[("👥 Users", "ad:users"), ("💵 Add / Deduct Balance", "ad:bal")],
            [("🔄 Sync Services", "ad:sync"), ("📋 All Orders", "ad:orders")],
            [("⏳ Pending Payments", "ad:pay"), ("📢 Broadcast", "ad:bcast")],
            [("📣 Channels", "ad:chan"), ("🔌 API Settings", "ad:api")],
            [("🏦 Payment Settings", "ad:pset"), ("⚙️ Bot Settings", "ad:set")],
            [("🗑 Delete Service", "ad:delsvc"), ("🗂 Delete Category", "adc:0")],
            [("♻️ Restore Deleted", "ad:restore"), ("🚫 Ban / Unban", "ad:ban")],
            [("📈 Stats", "ad:stats"), ("🛡 Admins", "ad:admins")]]
    txt = "👑 <b>Admin Panel</b>\nFull control from here 👇"
    if edit:
        try: return bot.edit_message_text(txt, chat_id, edit, reply_markup=ikb(rows))
        except Exception: return
    bot.send_message(chat_id, txt, reply_markup=ikb(rows))


def sync_services():
    data = api(action="services")
    if not isinstance(data, list):
        return f"❌ Sync failed: {data}"
    n = 0
    for s in data:
        cname = str(s.get("category", "Other"))[:80]
        c = db("SELECT * FROM categories WHERE name=?", (cname,), "one")
        if not c:
            db("INSERT INTO categories(name) VALUES(?)", (cname,))
            c = db("SELECT * FROM categories WHERE name=?", (cname,), "one")
        db("""INSERT INTO services(id,cat_id,name,api_rate,min,max,refill,cancel,hidden) VALUES(?,?,?,?,?,?,?,?,?)
              ON CONFLICT(id) DO UPDATE SET cat_id=excluded.cat_id,name=excluded.name,api_rate=excluded.api_rate,
              min=excluded.min,max=excluded.max,refill=excluded.refill,cancel=excluded.cancel""",
           (int(s["service"]), c["id"], str(s["name"]), float(s["rate"]), int(s.get("min", 1)),
            int(s.get("max", 1000000)), 1 if s.get("refill") else 0, 1 if s.get("cancel") else 0, c["hidden"]))
        n += 1
    return f"✅ {n} services synced."


def broadcast(text, admin_chat):
    users = db("SELECT id FROM users WHERE banned=0", fetch="all")
    ok = 0
    for u in users:
        try:
            bot.send_message(u["id"], f"📢 <b>Announcement</b>\n\n{e(text)}")
            ok += 1
        except Exception:
            pass
        time.sleep(0.05)
    bot.send_message(admin_chat, f"📢 Broadcast finished: delivered to {ok}/{len(users)} users.")


def settings_menu(cid, mid, title, items, back="ad:home"):
    """items = [(icon, label, key, kind)]  kind: 'edit' | 'toggle' | 'secret'"""
    rows = []
    for ic, label, key, kind in items:
        v = setting(key)
        if kind == "toggle":
            rows.append([(f"{ic} {label}: {'✅ ON' if v == '1' else '❌ OFF'}", f"tg:{key}")])
        else:
            shown = mask(v) if kind == "secret" else (v[:22] + "…" if len(v) > 22 else v) or "not set"
            rows.append([(f"{ic} {label}: {shown}", f"ed:{key}")])
    if title.startswith("🔌"):
        rows.append([("🧪 Test API (check balance)", "apitest")])
    rows.append([("🔙 Admin Panel", back)])
    bot.edit_message_text(title, cid, mid, reply_markup=ikb(rows))


def channel_menu(cid, mid):
    chans = db("SELECT * FROM channels", fetch="all")
    rows = [[(f"🗑 Remove: {c['title'][:28]}", f"chdel:{c['id']}")] for c in chans]
    rows.append([("➕ Add Channel", "chadd")])
    rows.append([("🔙 Admin Panel", "ad:home")])
    txt = ("📣 <b>Force Join Channels</b>\n\nUsers cannot use the bot until they join these channels.\n"
           "⚠️ The bot must be an <b>Admin</b> in each channel.\n\n"
           + ("\n".join(f"• {e(c['title'])}  <code>{c['chat_id']}</code>" for c in chans) if chans else "No channels added yet."))
    bot.edit_message_text(txt, cid, mid, reply_markup=ikb(rows))


def admins_menu(cid, mid, uid):
    adm = db("SELECT id FROM admins", fetch="all")
    rows = [[(f"🗑 Remove {a['id']}", f"admdel:{a['id']}")] for a in adm] if is_super(uid) else []
    if is_super(uid):
        rows.append([("➕ Add Admin", "admadd")])
    rows.append([("🔙 Admin Panel", "ad:home")])
    txt = ("🛡 <b>Admins</b>\n\nSuper admins (from file):\n"
           + "\n".join(f"• <code>{a}</code>" for a in ADMIN_IDS if a)
           + "\n\nAdded from panel:\n"
           + ("\n".join(f"• <code>{a['id']}</code>" for a in adm) if adm else "None."))
    bot.edit_message_text(txt, cid, mid, reply_markup=ikb(rows))


# ============================== CALLBACKS =================================
@bot.callback_query_handler(func=lambda c: True)
def on_cb(c):
    uid, cid, mid, d = c.from_user.id, c.message.chat.id, c.message.message_id, c.data
    u = ensure(c.from_user)
    if u["banned"] and not is_admin(uid):
        return bot.answer_callback_query(c.id, "Banned", show_alert=True)
    p = d.split(":")
    try:
        if d == "noop":
            return bot.answer_callback_query(c.id)
        if d == "joined":
            if missing_channels(uid):
                return bot.answer_callback_query(c.id, "❌ You have not joined all channels yet.", show_alert=True)
            try: bot.delete_message(cid, mid)
            except Exception: pass
            return send_welcome(cid, c.from_user)
        if not gate(uid, cid):
            return bot.answer_callback_query(c.id)
        if p[0] == "cat": cat_page(cid, int(p[1]), mid)
        elif p[0] == "svl": svc_page(cid, mid, int(p[1]), int(p[2]))
        elif p[0] == "svc":
            s = get_service(int(p[1]))
            if not s:
                return bot.answer_callback_query(c.id, "Service not found", show_alert=True)
            bot.edit_message_text(svc_text(s), cid, mid, reply_markup=ikb(
                [[("🛒 Order Now", f"buy:{s['id']}")], [("🔙 Back", f"svl:{s['cat_id']}:0")]]))
        elif p[0] == "buy":
            s = get_service(int(p[1]))
            if s: ask_link(uid, cid, s)
        elif d == "cf:yes": place_order(uid, cid)
        elif d == "cf:no":
            st.pop(uid, None)
            bot.send_message(cid, "❌ Order cancelled.")
        elif p[0] == "ost": order_view(cid, int(p[1]), uid, mid)
        elif p[0] in ("rf", "cn"):
            o = db("SELECT * FROM orders WHERE id=? AND user_id=?", (int(p[1]), uid), "one")
            if not o:
                return bot.answer_callback_query(c.id, "Order not found", show_alert=True)
            r = api(action="refill", order=o["api_order"]) if p[0] == "rf" else api(action="cancel", orders=o["api_order"])
            bot.send_message(cid, f"{'♻️ Refill' if p[0] == 'rf' else '🛑 Cancel'} response:\n<code>{e(r)}</code>")
        elif d == "paid":
            s = st.get(uid)
            if not s or "amt" not in s:
                return bot.answer_callback_query(c.id, "Session expired. Tap Add Balance again.", show_alert=True)
            s["step"] = "utr"
            bot.send_message(cid, "🧾 Now send your <b>UTR / Transaction ID</b>:")
        elif d == "pcancel":
            st.pop(uid, None)
            bot.send_message(cid, "❌ Cancelled.")
        elif p[0] in ("ad", "adc", "dcat", "apr", "rej", "tg", "ed", "chadd", "chdel", "admadd", "admdel", "apitest"):
            if not is_admin(uid):
                return bot.answer_callback_query(c.id, "Admins only", show_alert=True)
            admin_cb(c, p)
        bot.answer_callback_query(c.id)
    except Exception as ex:
        try: bot.answer_callback_query(c.id, f"Error: {ex}"[:150], show_alert=True)
        except Exception: pass


API_ITEMS = [("🌐", "API URL", "api_url", "edit"), ("🔑", "API Key", "api_key", "secret")]
PAY_ITEMS = [("🏦", "UPI ID", "upi_id", "edit"), ("🪪", "UPI Name", "upi_name", "edit"),
             ("💠", "Gateway Name", "gw_name", "edit"), ("🏪", "Merchant ID", "gw_merchant", "edit"),
             ("🔐", "Gateway Token", "gw_token", "secret"), ("🔗", "Gateway URL", "gw_url", "edit"),
             ("🤖", "Auto Verify", "gw_auto", "toggle")]
SET_ITEMS = [("📈", "Markup %", "markup", "edit"), ("💳", "Min Deposit", "min_deposit", "edit"),
             ("🎧", "Support", "support", "edit"), ("🌟", "Bot Name", "bot_name", "edit"),
             ("👋", "Welcome Message", "welcome", "edit"), ("🛠", "Maintenance", "maintenance", "toggle")]
MENUS = {"api": ("🔌 <b>API Settings</b>\nChange your SMM panel API here.", API_ITEMS),
         "pset": ("🏦 <b>Payment Settings</b>\nChange the UPI ID, or add the gateway (FamPay / BharatPay) Merchant ID and Token.", PAY_ITEMS),
         "set": ("⚙️ <b>Bot Settings</b>", SET_ITEMS)}


def admin_cb(c, p):
    cid, mid, uid = c.message.chat.id, c.message.message_id, c.from_user.id
    a0 = p[0]

    # ---- payment approve / reject ----
    if a0 in ("apr", "rej"):
        pay = db("SELECT * FROM payments WHERE id=?", (int(p[1]),), "one")
        if not pay or pay["status"] != "Pending":
            return bot.answer_callback_query(c.id, "Already processed", show_alert=True)
        if a0 == "apr":
            db("UPDATE payments SET status='Approved' WHERE id=?", (pay["id"],))
            add_bal(pay["user_id"], pay["amount"])
            note, umsg = "✅ Approved", f"✅ Payment approved! ₹{pay['amount']} has been added to your balance."
        else:
            db("UPDATE payments SET status='Rejected' WHERE id=?", (pay["id"],))
            note, umsg = "❌ Rejected", "❌ Your payment was rejected. Please contact support."
        try: bot.send_message(pay["user_id"], umsg)
        except Exception: pass
        newp = db("SELECT * FROM payments WHERE id=?", (pay["id"],), "one")
        try: bot.edit_message_caption(f"{pay_card(newp)}\n\n{note} by <code>{uid}</code>", cid, mid)
        except Exception:
            try: bot.edit_message_text(f"{pay_card(newp)}\n\n{note}", cid, mid)
            except Exception: pass
        return

    # ---- delete category ----
    if a0 == "adc":
        page = int(p[1])
        cats = db("SELECT * FROM categories WHERE hidden=0 ORDER BY id", fetch="all")
        tot = max(1, (len(cats) - 1) // PER_PAGE + 1)
        rows = [[(f"🗑 {icon_for(x['name'])} {x['name'][:34]}", f"dcat:{x['id']}")] for x in cats[page * PER_PAGE:(page + 1) * PER_PAGE]]
        nav = []
        if page > 0: nav.append(("⬅️ Prev", f"adc:{page-1}"))
        nav.append((f"📄 {page+1}/{tot}", "noop"))
        if page < tot - 1: nav.append(("Next ➡️", f"adc:{page+1}"))
        rows += [nav, [("🔙 Admin Panel", "ad:home")]]
        return bot.edit_message_text("🗂 <b>Which category do you want to delete?</b>", cid, mid, reply_markup=ikb(rows))
    if a0 == "dcat":
        db("UPDATE categories SET hidden=1 WHERE id=?", (int(p[1]),))
        db("UPDATE services SET hidden=1 WHERE cat_id=?", (int(p[1]),))
        return bot.send_message(cid, "✅ Category (and its services) removed.")

    # ---- settings edit / toggle ----
    if a0 == "tg":
        set_setting(p[1], "0" if setting(p[1]) == "1" else "1")
        key = "pset" if p[1] == "gw_auto" else "set"
        return settings_menu(cid, mid, *MENUS[key])
    if a0 == "ed":
        st[uid] = {"step": "ad_set", "key": p[1]}
        shown = mask(setting(p[1])) if p[1] in ("api_key", "gw_token") else e(setting(p[1]))
        return bot.send_message(cid, f"✏️ Send the new value for <b>{p[1]}</b>.\nCurrent: <code>{shown}</code>\n\nSend /start to cancel.")
    if a0 == "apitest":
        r = api(action="balance")
        return bot.send_message(cid, f"🧪 API test result:\n<code>{e(r)}</code>")

    # ---- channels ----
    if a0 == "chadd":
        st[uid] = {"step": "ad_chan"}
        return bot.send_message(cid, "📣 Send the channel <b>@username</b> or <b>-100...</b> ID.\n"
                                     "⚠️ Make the bot an Admin of that channel first.")
    if a0 == "chdel":
        db("DELETE FROM channels WHERE id=?", (int(p[1]),))
        return channel_menu(cid, mid)

    # ---- admins ----
    if a0 == "admadd":
        if not is_super(uid):
            return bot.answer_callback_query(c.id, "Super admin only", show_alert=True)
        st[uid] = {"step": "ad_admin"}
        return bot.send_message(cid, "🛡 Send the new admin's <b>chat ID</b>:")
    if a0 == "admdel":
        if not is_super(uid):
            return bot.answer_callback_query(c.id, "Super admin only", show_alert=True)
        db("DELETE FROM admins WHERE id=?", (int(p[1]),))
        return admins_menu(cid, mid, uid)

    # ---- main "ad:" actions ----
    a = p[1]
    if a == "home": admin_panel(cid, mid)
    elif a in MENUS: settings_menu(cid, mid, *MENUS[a])
    elif a == "chan": channel_menu(cid, mid)
    elif a == "admins": admins_menu(cid, mid, uid)
    elif a == "users":
        us = db("SELECT * FROM users ORDER BY joined DESC LIMIT 20", fetch="all")
        t = "👥 <b>Latest 20 Users</b>\n" + "\n".join(
            f"<code>{x['id']}</code> {e(x['name'])} ₹{x['balance']:.2f}{' 🚫' if x['banned'] else ''}" for x in us)
        bot.send_message(cid, t + f"\n\nTotal: {scalar('SELECT COUNT(*) FROM users')}")
    elif a == "bal":
        st[uid] = {"step": "ad_bal"}
        bot.send_message(cid, "💵 Format: <code>USER_ID AMOUNT</code>\nAdd: <code>12345 100</code>\nDeduct: <code>12345 -50</code>")
    elif a == "sync":
        bot.send_message(cid, "⏳ Syncing services...")
        bot.send_message(cid, sync_services())
    elif a == "orders":
        os_ = db("SELECT * FROM orders ORDER BY id DESC LIMIT 15", fetch="all")
        if not os_:
            return bot.send_message(cid, "📭 No orders yet.")
        bot.send_message(cid, "📋 <b>Last 15 Orders</b>", reply_markup=ikb(
            [[(f"🧾 #{o['id']} • U{o['user_id']} • {o['status']}", f"ost:{o['id']}")] for o in os_]))
    elif a == "pay":
        ps = db("SELECT * FROM payments WHERE status='Pending' ORDER BY id", fetch="all")
        if not ps:
            return bot.send_message(cid, "✅ No pending payments.")
        for x in ps:
            if x["file_id"]: bot.send_photo(cid, x["file_id"], caption=pay_card(x), reply_markup=pay_kb(x["id"]))
            else: bot.send_message(cid, pay_card(x), reply_markup=pay_kb(x["id"]))
    elif a == "bcast":
        st[uid] = {"step": "ad_bcast"}
        bot.send_message(cid, "📢 Send the broadcast message:")
    elif a == "delsvc":
        st[uid] = {"step": "ad_delsvc"}
        bot.send_message(cid, "🗑 Send the <b>Service ID</b> you want to remove:")
    elif a == "restore":
        db("UPDATE categories SET hidden=0")
        db("UPDATE services SET hidden=0")
        bot.send_message(cid, "♻️ All deleted services and categories are restored.")
    elif a == "ban":
        st[uid] = {"step": "ad_ban"}
        bot.send_message(cid, "🚫 Send the user ID (toggles ban / unban):")
    elif a == "stats":
        bot.send_message(cid, "📈 <b>Stats</b>\n━━━━━━━━━━━━━━━━\n"
            f"👥 Users: {scalar('SELECT COUNT(*) FROM users')}\n"
            f"🛒 Orders: {scalar('SELECT COUNT(*) FROM orders')}\n"
            f"💸 Sales: ₹{scalar('SELECT SUM(charge) FROM orders'):.2f}\n"
            f"💳 Approved deposits: ₹{scalar('SELECT SUM(amount) FROM payments WHERE status=?', ('Approved',)):.2f}\n"
            f"⏳ Pending payments: {scalar('SELECT COUNT(*) FROM payments WHERE status=?', ('Pending',))}\n"
            f"📦 Services: {scalar('SELECT COUNT(*) FROM services WHERE hidden=0')}\n"
            f"📣 Channels: {scalar('SELECT COUNT(*) FROM channels')}")


# ============================== MESSAGES ==================================
MENU = {B_SERV: lambda m: cat_page(m.chat.id), B_ORDER: new_order_prompt, B_BAL: balance_msg,
        B_ADD: add_prompt, B_STAT: status_prompt, B_HIST: history, B_HELP: help_msg, B_SUP: support_msg,
        B_ADM: lambda m: admin_panel(m.chat.id) if is_admin(m.from_user.id) else None}


@bot.message_handler(content_types=["text", "photo"])
def on_msg(m):
    uid = m.from_user.id
    u = ensure(m.from_user)
    if u["banned"] and not is_admin(uid):
        return bot.reply_to(m, "🚫 You are banned.")
    if setting("maintenance") == "1" and not is_admin(uid):
        return bot.reply_to(m, "🛠 The bot is under maintenance. Please try again later.")
    if not gate(uid, m.chat.id):
        return
    t = (m.text or "").strip()
    if t in MENU:
        st.pop(uid, None)
        return MENU[t](m)
    s = st.get(uid)
    if not s:
        return
    step = s["step"]

    # ---- user steps ----
    if step == "sid":
        if not t.isdigit() or not get_service(int(t)):
            return bot.reply_to(m, "❌ Invalid Service ID. Try again or send /start.")
        ask_link(uid, m.chat.id, get_service(int(t)))
    elif step == "link":
        if not t.startswith("http"):
            return bot.reply_to(m, "❌ Send a valid link (starting with http).")
        s["link"] = t
        s["step"] = "qty"
        sv = get_service(s["sid"])
        bot.send_message(m.chat.id, f"🔢 Send the <b>Quantity</b> ({sv['min']} - {sv['max']}):")
    elif step == "qty":
        sv = get_service(s["sid"])
        if not t.isdigit() or not (sv["min"] <= int(t) <= sv["max"]):
            return bot.reply_to(m, f"❌ Quantity must be between {sv['min']} and {sv['max']}.")
        s["qty"] = int(t)
        charge = round(price(sv["api_rate"]) * s["qty"] / 1000, 4)
        bot.send_message(m.chat.id, f"🧾 <b>Confirm Order</b>\n━━━━━━━━━━━━━━━━\n📦 {e(sv['name'])}\n🔗 {e(s['link'])}\n"
                         f"🔢 Quantity: {s['qty']}\n💸 Charge: <b>₹{charge:.2f}</b>\n💰 Your balance: ₹{u['balance']:.2f}",
                         reply_markup=ikb([[("✅ Confirm", "cf:yes"), ("❌ Cancel", "cf:no")]]))
    elif step == "ostatus":
        st.pop(uid, None)
        if t.isdigit(): order_view(m.chat.id, int(t), uid)
        else: bot.reply_to(m, "❌ Order ID must be a number.")
    elif step == "amount":
        try: amt = round(float(t), 2)
        except Exception: return bot.reply_to(m, "❌ Send a valid amount (for example 100).")
        if amt < float(setting("min_deposit")):
            return bot.reply_to(m, f"❌ Minimum amount is ₹{setting('min_deposit')}.")
        st[uid] = {"step": "wait", "amt": amt}
        send_qr(uid, m.chat.id, amt)
    elif step == "utr":
        if len(t) < 6 or db("SELECT 1 FROM payments WHERE utr=? AND status!='Rejected'", (t,), "one"):
            return bot.reply_to(m, "❌ Invalid UTR, or it was already used.")
        s["utr"] = t
        s["step"] = "shot"
        bot.send_message(m.chat.id, "📸 Now send the payment <b>screenshot</b>:")
    elif step == "shot":
        if not m.photo:
            return bot.reply_to(m, "❌ Please send the screenshot as a photo.")
        fid = m.photo[-1].file_id
        pid = db("INSERT INTO payments(user_id,amount,utr,file_id,created) VALUES(?,?,?,?,?)",
                 (uid, s["amt"], s["utr"], fid, now()))
        st.pop(uid, None)
        if gateway_verify(s["utr"], s["amt"]):
            db("UPDATE payments SET status='Approved', method='gateway' WHERE id=?", (pid,))
            add_bal(uid, s["amt"])
            return bot.send_message(m.chat.id, f"✅ Payment verified automatically! ₹{s['amt']} added to your balance.")
        bot.send_message(m.chat.id, f"✅ Payment request #{pid} submitted.\nYour balance will be updated once the admin approves it.")
        p = db("SELECT * FROM payments WHERE id=?", (pid,), "one")
        for a in all_admin_ids():
            try: bot.send_photo(a, fid, caption="🔔 <b>New Payment</b>\n" + pay_card(p), reply_markup=pay_kb(pid))
            except Exception: pass

    # ---- admin steps ----
    elif step.startswith("ad_") and is_admin(uid):
        st.pop(uid, None)
        if step == "ad_bal":
            try:
                a, b = t.split()
                a, b = int(a), float(b)
                if not get_user(a): return bot.reply_to(m, "❌ User not found.")
                add_bal(a, b)
                bot.reply_to(m, f"✅ Done. New balance: ₹{get_user(a)['balance']:.2f}")
                try: bot.send_message(a, f"{'➕' if b > 0 else '➖'} Admin {'added' if b > 0 else 'deducted'} ₹{abs(b)} {'to' if b > 0 else 'from'} your balance.")
                except Exception: pass
            except Exception:
                bot.reply_to(m, "❌ Format: USER_ID AMOUNT")
        elif step == "ad_bcast":
            bot.reply_to(m, "📢 Broadcast started...")
            threading.Thread(target=broadcast, args=(t, m.chat.id), daemon=True).start()
        elif step == "ad_delsvc":
            if t.isdigit() and db("SELECT 1 FROM services WHERE id=?", (int(t),), "one"):
                db("UPDATE services SET hidden=1 WHERE id=?", (int(t),))
                bot.reply_to(m, "✅ Service removed.")
            else:
                bot.reply_to(m, "❌ Service not found.")
        elif step == "ad_ban":
            if t.isdigit() and get_user(int(t)):
                nb = 0 if get_user(int(t))["banned"] else 1
                db("UPDATE users SET banned=? WHERE id=?", (nb, int(t)))
                bot.reply_to(m, "🚫 User banned." if nb else "✅ User unbanned.")
            else:
                bot.reply_to(m, "❌ User not found.")
        elif step == "ad_set":
            set_setting(s["key"], t)
            bot.reply_to(m, f"✅ <b>{s['key']}</b> updated.\n(Delete your message if it contained a secret.)")
        elif step == "ad_admin":
            if is_super(uid) and t.isdigit():
                db("INSERT OR IGNORE INTO admins(id) VALUES(?)", (int(t),))
                bot.reply_to(m, f"✅ {t} is now an admin.")
            else:
                bot.reply_to(m, "❌ Send a valid chat ID.")
        elif step == "ad_chan":
            ref = t if t.startswith("-100") or t.startswith("@") else "@" + t
            try:
                chat = bot.get_chat(ref)
                link = f"https://t.me/{chat.username}" if chat.username else None
                if not link:
                    try: link = bot.export_chat_invite_link(chat.id)
                    except Exception: link = None
                db("INSERT OR REPLACE INTO channels(chat_id,title,link) VALUES(?,?,?)",
                   (str(chat.id), chat.title or ref, link))
                bot.reply_to(m, f"✅ Channel added: <b>{e(chat.title)}</b>"
                                + ("" if link else "\n⚠️ No join link found. Make the bot an admin of the channel."))
            except Exception as ex:
                bot.reply_to(m, f"❌ Channel not found: {e(ex)}\nMake the bot an admin of the channel and try again.")


# ============================== RUN =======================================
if __name__ == "__main__":
    init_db()
    print("Bot is running...")
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=30)
        except Exception as ex:
            print("Error:", ex)
            time.sleep(5)
