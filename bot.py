import json
import logging
import sqlite3
import random
import hashlib
import os
import sys
import time
import requests
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

# =================================================================
# КОНФИГУРАЦИЯ
# =================================================================
BOT_TOKEN = "8978316248:AAF4n6jG5gr4quppre6H1NB7U9LjEjnESqs"
ADMIN_ID = 7753887058
TON_WALLET = "UQDRRRGutl_ccP25XcwbOK-RN2UXuvE1_GFoerlaIDvmwO7I"
TONCENTER_API_KEY = "12237ee2c684a00cd473582230a4d9efea8b51b6baf2322883e4ef52f5d34390"
TONCENTER_URL = "https://toncenter.com/api/v2"

RENDER_URL = os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'syndrome-bot-9.onrender.com')
WEBAPP_URL = "https://syndrome-bot-8.onrender.com"
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
BOT_USERNAME = "nft_takes_gifts_bot"

# =================================================================
# БАЗА ДАННЫХ
# =================================================================
DB_PATH = 'casino.db'

def db_connect():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    with db_connect() as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                balance_ton REAL DEFAULT 0,
                balance_stars INTEGER DEFAULT 0,
                total_deposited_ton REAL DEFAULT 0,
                total_deposited_stars INTEGER DEFAULT 0,
                referral_code TEXT UNIQUE,
                referred_by INTEGER,
                referral_count INTEGER DEFAULT 0,
                free_case_available INTEGER DEFAULT 0,
                gift_items TEXT DEFAULT '[]',
                withdrawn_items TEXT DEFAULT '[]',
                pending_payment_id TEXT,
                pending_payment_time TIMESTAMP,
                pending_stars_amount INTEGER DEFAULT 0,
                pending_stars_charge_id TEXT,
                language TEXT DEFAULT 'ru',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                type TEXT,
                amount REAL,
                currency TEXT,
                tx_hash TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS withdrawal_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                item_name TEXT,
                item_icon TEXT,
                amount REAL,
                currency TEXT,
                wallet TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS stars_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                stars_amount INTEGER,
                charge_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referred_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS live_drops (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                item_name TEXT,
                item_icon TEXT,
                case_name TEXT,
                value_stars INTEGER DEFAULT 0,
                value_ton REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
    logger.info("✅ DB ready")

# =================================================================
# TON VERIFICATION
# =================================================================
def verify_ton_transaction(wallet_address, comment, hours=24):
    try:
        params = {'address': wallet_address, 'limit': 50, 'api_key': TONCENTER_API_KEY}
        r = requests.get(f"{TONCENTER_URL}/getTransactions", params=params, timeout=10)
        if r.status_code != 200: return None
        data = r.json()
        if not data.get('ok'): return None
        cutoff = datetime.now() - timedelta(hours=hours)
        for tx in data.get('result', []):
            in_msg = tx.get('in_msg', {})
            if not in_msg: continue
            if in_msg.get('source','') == wallet_address: continue
            value = int(in_msg.get('value', 0)) / 1_000_000_000
            msg = in_msg.get('message', '')
            if comment.upper() in msg.upper():
                tx_time = datetime.fromtimestamp(tx.get('utime', 0))
                if tx_time > cutoff:
                    return {'hash': tx.get('hash',''), 'amount': value}
        return None
    except Exception as e:
        logger.error(f"TON: {e}")
        return None

# =================================================================
# TELEGRAM STARS PAYMENT
# =================================================================
def create_stars_invoice(user_id, stars_amount):
    try:
        invoice_data = {
            "chat_id": user_id,
            "title": "Пополнение баланса",
            "description": f"Пополнение игрового баланса на {stars_amount} звёзд Telegram.",
            "payload": f"stars_deposit_{user_id}_{int(time.time())}",
            "provider_token": "",
            "currency": "XTR",
            "prices": [{"label": f"{stars_amount} Stars", "amount": stars_amount}]
        }
        r = requests.post(f"{TELEGRAM_API}/sendInvoice", json=invoice_data, timeout=15)
        result = r.json()
        if result.get('ok'): return True, result
        else:
            logger.error(f"Stars invoice failed: {result.get('description')}")
            return False, result
    except Exception as e:
        logger.error(f"Stars invoice exception: {e}")
        return False, str(e)

# =================================================================
# TELEGRAM API HELPERS
# =================================================================
def tg_send(chat_id, text, keyboard=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if keyboard: data["reply_markup"] = json.dumps(keyboard)
    try: return requests.post(f"{TELEGRAM_API}/sendMessage", json=data, timeout=10).json()
    except: return None

def tg_edit(chat_id, msg_id, text, keyboard=None):
    data = {"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": "HTML"}
    if keyboard: data["reply_markup"] = json.dumps(keyboard)
    try: return requests.post(f"{TELEGRAM_API}/editMessageText", json=data, timeout=10).json()
    except: return None

def tg_answer(cb_id, text=""):
    try: return requests.post(f"{TELEGRAM_API}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": text}, timeout=10).json()
    except: return None

def generate_ref_code(user_id):
    return hashlib.md5(f"ref{user_id}{time.time()}".encode()).hexdigest()[:8].upper()

def generate_payment_id(user_id):
    return hashlib.sha256(f"pay{user_id}{time.time()}{random.randint(0,9999)}".encode()).hexdigest()[:16].upper()

# =================================================================
# ДАННЫЕ КЕЙСОВ
# =================================================================
CASES_DATA = {
    "regular": {
        "name_ru": "Обычный кейс", "name_en": "Regular Case",
        "icon": "📦", "price_ton": None, "price_stars": 50, "color": "#9CA3AF",
        "items": [
            {"name_ru": "❤️ Сердечко", "name_en": "❤️ Heart", "icon": "❤️", "chance_demo": 30, "chance_real": 3, "value_stars": 15, "value_ton": 0.5},
            {"name_ru": "🧸 Мишка", "name_en": "🧸 Bear", "icon": "🧸", "chance_demo": 25, "chance_real": 2, "value_stars": 15, "value_ton": 0.5},
            {"name_ru": "🌹 Роза", "name_en": "🌹 Rose", "icon": "🌹", "chance_demo": 20, "chance_real": 2, "value_stars": 25, "value_ton": 0.8},
            {"name_ru": "🎂 Тортик", "name_en": "🎂 Cake", "icon": "🎂", "chance_demo": 10, "chance_real": 1, "value_stars": 50, "value_ton": 1.5},
            {"name_ru": "💍 Кольцо", "name_en": "💍 Ring", "icon": "💍", "chance_demo": 7, "chance_real": 0.5, "value_stars": 100, "value_ton": 3.0},
            {"name_ru": "💎 Кристалл", "name_en": "💎 Crystal", "icon": "💎", "chance_demo": 5, "chance_real": 0.5, "value_stars": 150, "value_ton": 5.0},
            {"name_ru": "💩 Ничего", "name_en": "💩 Nothing", "icon": "💩", "chance_demo": 3, "chance_real": 91, "value_stars": 0, "value_ton": 0},
        ]
    },
    "stars": {
        "name_ru": "Звёздный кейс", "name_en": "Star Case",
        "icon": "⭐", "price_stars": 100, "color": "#FBBF24",
        "items": [
            {"name_ru": "15 Звёзд", "name_en": "15 Stars", "icon": "⭐", "chance_demo": 45, "chance_real": 10, "value_stars": 15},
            {"name_ru": "30 Звёзд", "name_en": "30 Stars", "icon": "🌟", "chance_demo": 30, "chance_real": 5, "value_stars": 30},
            {"name_ru": "50 Звёзд", "name_en": "50 Stars", "icon": "💫", "chance_demo": 25, "chance_real": 3, "value_stars": 50},
            {"name_ru": "75 Звёзд", "name_en": "75 Stars", "icon": "✨", "chance_demo": 20, "chance_real": 1, "value_stars": 75},
            {"name_ru": "150 Звёзд", "name_en": "150 Stars", "icon": "💎", "chance_demo": 5, "chance_real": 0.5, "value_stars": 150},
            {"name_ru": "350 Звёзд", "name_en": "350 Stars", "icon": "👑", "chance_demo": 2, "chance_real": 0.5, "value_stars": 350},
        ]
    },
    "ton": {
        "name_ru": "TON кейс", "name_en": "TON Case",
        "icon": "💎", "price_ton": 1, "price_stars": None, "color": "#0088CC",
        "items": [
            {"name_ru": "0.5 TON", "name_en": "0.5 TON", "icon": "💎", "chance_demo": 45, "chance_real": 10, "value_ton": 0.5},
            {"name_ru": "1 TON", "name_en": "1 TON", "icon": "💎", "chance_demo": 30, "chance_real": 5, "value_ton": 1},
            {"name_ru": "2 TON", "name_en": "2 TON", "icon": "💎", "chance_demo": 15, "chance_real": 3, "value_ton": 2},
            {"name_ru": "3 TON", "name_en": "3 TON", "icon": "💎", "chance_demo": 7, "chance_real": 1, "value_ton": 3},
            {"name_ru": "5 TON", "name_en": "5 TON", "icon": "💎", "chance_demo": 2.5, "chance_real": 0.5, "value_ton": 5},
            {"name_ru": "10 TON", "name_en": "10 TON", "icon": "💎", "chance_demo": 0.5, "chance_real": 0.5, "value_ton": 10},
        ]
    },
    "nft": {
        "name_ru": "NFT кейс", "name_en": "NFT Case",
        "icon": "🐵", "price_ton": 5, "price_stars": 200, "color": "#F472B6",
        "items": [
            {"name_ru": "🐵 NFT Обезьяна", "name_en": "🐵 NFT Monkey", "icon": "🐵", "chance_demo": 8, "chance_real": 1, "value_stars": 1500, "value_ton": 50},
            {"name_ru": "🐍 NFT Змейка", "name_en": "🐍 NFT Snake", "icon": "🐍", "chance_demo": 35, "chance_real": 5, "value_stars": 250, "value_ton": 8},
            {"name_ru": "🎄 NFT Новый Год", "name_en": "🎄 NFT New Year", "icon": "🎄", "chance_demo": 45, "chance_real": 8, "value_stars": 150, "value_ton": 5},
            {"name_ru": "🎃 NFT Хэллоуин", "name_en": "🎃 NFT Halloween", "icon": "🎃", "chance_demo": 12, "chance_real": 3, "value_stars": 400, "value_ton": 15},
            {"name_ru": "🍦 NFT Мороженое", "name_en": "🍦 NFT Ice Cream", "icon": "🍦", "chance_demo": 13, "chance_real": 2, "value_stars": 300, "value_ton": 10},
            {"name_ru": "🎒 NFT Рюкзак", "name_en": "🎒 NFT Backpack", "icon": "🎒", "chance_demo": 5, "chance_real": 0.5, "value_stars": 800, "value_ton": 25},
            {"name_ru": "🍁 NFT Swag Bag", "name_en": "🍁 NFT Swag Bag", "icon": "🍁", "chance_demo": 20, "chance_real": 3, "value_stars": 200, "value_ton": 7},
            {"name_ru": "🐶 NFT Snoop Dogg", "name_en": "🐶 NFT Snoop Dogg", "icon": "🐶", "chance_demo": 7, "chance_real": 1, "value_stars": 600, "value_ton": 20},
        ]
    },
    "free": {
        "name_ru": "Бесплатный кейс", "name_en": "Free Case",
        "icon": "🎁", "color": "#10B981",
        "items": [
            {"name_ru": "🧸 Мишка", "name_en": "🧸 Bear", "icon": "🧸", "chance_demo": 20, "chance_real": 5, "value_stars": 15, "value_ton": 0.5},
            {"name_ru": "❤️ Сердечко", "name_en": "❤️ Heart", "icon": "❤️", "chance_demo": 20, "chance_real": 5, "value_stars": 15, "value_ton": 0.5},
            {"name_ru": "🌹 Роза", "name_en": "🌹 Rose", "icon": "🌹", "chance_demo": 15, "chance_real": 3, "value_stars": 25, "value_ton": 0.8},
            {"name_ru": "🎂 Тортик", "name_en": "🎂 Cake", "icon": "🎂", "chance_demo": 10, "chance_real": 2, "value_stars": 50, "value_ton": 1.5},
            {"name_ru": "💍 Кольцо", "name_en": "💍 Ring", "icon": "💍", "chance_demo": 5, "chance_real": 1, "value_stars": 100, "value_ton": 3.0},
            {"name_ru": "💩 Ничего", "name_en": "💩 Nothing", "icon": "💩", "chance_demo": 30, "chance_real": 84, "value_stars": 0, "value_ton": 0},
        ]
    }
}

def get_cases_for_api(lang='ru'):
    cases_list = []
    for case_id, case in CASES_DATA.items():
        items = []
        for item in case['items']:
            items.append({
                'name': item.get(f'name_{lang}', item.get('name_ru', '')),
                'icon': item['icon'],
                'chance': item['chance_demo'],
                'chance_demo': item['chance_demo'],
                'chance_real': item['chance_real'],
                'value_stars': item.get('value_stars', 0),
                'value_ton': item.get('value_ton', 0),
            })
        cases_list.append({
            'id': case_id,
            'name': case.get(f'name_{lang}', case.get('name_ru', '')),
            'icon': case['icon'],
            'price_ton': case.get('price_ton'),
            'price_stars': case.get('price_stars'),
            'color': case['color'],
            'items': items
        })
    return cases_list

# =================================================================
# BOT HANDLERS
# =================================================================
def handle_start(chat_id, user, args=None):
    uid = user["id"]
    uname = user.get("username", f"user_{uid}")
    fname = user.get("first_name", "Player")
    
    ref_code = args[0] if args else None
    
    with db_connect() as conn:
        row = conn.execute('SELECT user_id, referral_code FROM users WHERE user_id=?', (uid,)).fetchone()
        
        if not row:
            my_ref = generate_ref_code(uid)
            referred_by = None
            
            if ref_code:
                ref_row = conn.execute('SELECT user_id FROM users WHERE referral_code=?', (ref_code,)).fetchone()
                if ref_row and ref_row[0] != uid:
                    referred_by = ref_row[0]
                    conn.execute('UPDATE users SET referral_count = referral_count + 1 WHERE user_id = ?', (referred_by,))
                    conn.execute('INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)', (referred_by, uid))
                    ref_count = conn.execute('SELECT referral_count FROM users WHERE user_id = ?', (referred_by,)).fetchone()
                    if ref_count and ref_count[0] >= 3:
                        conn.execute('UPDATE users SET free_case_available = 1 WHERE user_id = ?', (referred_by,))
            
            conn.execute('INSERT INTO users (user_id, username, first_name, referral_code, referred_by, balance_stars, balance_ton) VALUES (?, ?, ?, ?, ?, 0, 0)', 
                        (uid, uname, fname, my_ref, referred_by))
    
    keyboard = {"inline_keyboard": [
        [{"text": "🎁 ОТКРЫТЬ ПРИЛОЖЕНИЕ", "web_app": {"url": WEBAPP_URL}}],
        [{"text": "💰 ПОПОЛНИТЬ TON", "callback_data": "dep_ton"}],
        [{"text": "⭐ ПОПОЛНИТЬ STARS", "callback_data": "dep_stars"}],
        [{"text": "👥 РЕФЕРАЛЬНАЯ СИСТЕМА", "callback_data": "ref_info"}],
        [{"text": "💼 ПРОФИЛЬ", "callback_data": "profile"}]
    ]}
    
    tg_send(chat_id, "🎁 <b>GIFT CASES — КЕЙСЫ ПОДАРКОВ</b>\n\n📦 Обычный • ⭐ Звёздный\n💎 TON • 🐵 NFT\n🎁 Бесплатный (за 3 реферала)\n\n💰 Пополняйте через TON или Telegram Stars!\n🆕 Новые пользователи: баланс 0\n\n<b>👇 НАЖМИ НА КНОПКУ!</b>", keyboard)

def handle_dep_ton(cb, chat_id, msg_id, uid):
    tg_answer(cb["id"])
    pid = generate_payment_id(uid)
    with db_connect() as conn:
        conn.execute('UPDATE users SET pending_payment_id=?, pending_payment_time=CURRENT_TIMESTAMP WHERE user_id=?', (pid, uid))
    
    keyboard = {"inline_keyboard": [
        [{"text": "✅ ПРОВЕРИТЬ ОПЛАТУ", "callback_data": f"check_{pid}"}],
        [{"text": "🔄 НОВЫЙ КОД", "callback_data": "dep_ton"}],
        [{"text": "🏠 МЕНЮ", "callback_data": "menu"}]
    ]}
    
    tg_edit(chat_id, msg_id, f"💎 <b>ПОПОЛНЕНИЕ TON</b>\n\n📤 Кошелёк:\n<code>{TON_WALLET}</code>\n\n📝 Код:\n<code>{pid}</code>\n\n⚠️ Мин: <b>1 TON</b>\n⚠️ Укажите код в комментарии!", keyboard)

def handle_dep_stars(cb, chat_id, msg_id, uid):
    tg_answer(cb["id"])
    
    keyboard = {
        "inline_keyboard": [
            [{"text": "⭐ 50 Stars", "callback_data": f"stars_invoice_50"}],
            [{"text": "⭐ 100 Stars", "callback_data": f"stars_invoice_100"}],
            [{"text": "⭐ 250 Stars", "callback_data": f"stars_invoice_250"}],
            [{"text": "⭐ 500 Stars", "callback_data": f"stars_invoice_500"}],
            [{"text": "💎 ПОПОЛНИТЬ TON", "callback_data": "dep_ton"}],
            [{"text": "🏠 МЕНЮ", "callback_data": "menu"}]
        ]
    }
    
    tg_edit(chat_id, msg_id,
        "⭐ <b>ПОПОЛНЕНИЕ STARS</b>\n\n"
        "Выберите сумму для пополнения:\n\n"
        "💰 <b>Реальная оплата звёздами!</b>\n"
        "• Вам будет выставлен счёт\n"
        "• Звёзды спишутся с вашего баланса Telegram\n"
        "• Баланс пополнится автоматически\n\n"
        "👇 Выберите сумму ниже:",
        keyboard
    )

def handle_stars_invoice(cb, chat_id, msg_id, uid, amount):
    tg_answer(cb["id"], f"🔄 Создаю счёт на {amount} Stars...")
    
    charge_id = f"stars_{uid}_{int(time.time())}"
    with db_connect() as conn:
        conn.execute('INSERT INTO stars_payments (user_id, stars_amount, charge_id, status) VALUES (?,?,?,?)', (uid, amount, charge_id, 'pending'))
        conn.execute('UPDATE users SET pending_stars_amount=?, pending_stars_charge_id=? WHERE user_id=?', (amount, charge_id, uid))
    
    success, result = create_stars_invoice(uid, amount)
    
    if success:
        tg_edit(chat_id, msg_id,
            f"⭐ <b>СЧЁТ НА {amount} STARS</b>\n\n"
            f"📱 Счёт отправлен в чат!\n"
            f"💳 <b>Нажмите на него для оплаты!</b>\n\n"
            f"✅ Звёзды реально спишутся с вашего баланса\n"
            f"✅ После оплаты баланс пополнится автоматически\n\n"
            f"⚠️ Если счёт не видно — проверьте чат с ботом",
            {"inline_keyboard": [
                [{"text": "🔄 ПРОВЕРИТЬ ОПЛАТУ", "callback_data": f"check_stars_{charge_id}"}],
                [{"text": "💎 ПОПОЛНИТЬ TON", "callback_data": "dep_ton"}],
                [{"text": "🏠 МЕНЮ", "callback_data": "menu"}]
            ]}
        )
    else:
        error_msg = result.get('description', 'Неизвестная ошибка') if isinstance(result, dict) else str(result)
        with db_connect() as conn:
            conn.execute('DELETE FROM stars_payments WHERE charge_id=?', (charge_id,))
            conn.execute('UPDATE users SET pending_stars_amount=NULL, pending_stars_charge_id=NULL WHERE user_id=?', (uid,))
        
        tg_edit(chat_id, msg_id,
            f"❌ <b>ОШИБКА СОЗДАНИЯ СЧЁТА</b>\n\nTelegram: {error_msg}\n\nПопробуйте позже или пополните через TON.",
            {"inline_keyboard": [
                [{"text": "💎 ПОПОЛНИТЬ TON", "callback_data": "dep_ton"}],
                [{"text": "🔄 ПОПРОБОВАТЬ СНОВА", "callback_data": "dep_stars"}],
                [{"text": "🏠 МЕНЮ", "callback_data": "menu"}]
            ]}
        )

def handle_check_stars(cb, chat_id, msg_id, uid, charge_id):
    tg_answer(cb["id"], "🔍 Проверяю...")
    
    with db_connect() as conn:
        row = conn.execute('SELECT status, stars_amount FROM stars_payments WHERE charge_id=? AND user_id=?', (charge_id, uid)).fetchone()
    
    if row and row[0] == 'completed':
        tg_edit(chat_id, msg_id, f"✅ <b>ПЛАТЕЖ ПОДТВЕРЖДЁН!</b>\n\n⭐ +{row[1]} Stars зачислено!\n\n🎁 Открывайте кейсы!", {"inline_keyboard": [[{"text": "🎁 ОТКРЫТЬ ПРИЛОЖЕНИЕ", "web_app": {"url": WEBAPP_URL}}]]})
    elif row and row[0] == 'pending':
        tg_edit(chat_id, msg_id, f"⏳ <b>ПЛАТЕЖ ОЖИДАЕТСЯ</b>\n\nСчёт на {row[1]} Stars отправлен.\nОплатите его в чате с ботом.", {"inline_keyboard": [[{"text": "🔄 ПРОВЕРИТЬ СНОВА", "callback_data": f"check_stars_{charge_id}"}], [{"text": "🏠 МЕНЮ", "callback_data": "menu"}]]})
    else:
        tg_edit(chat_id, msg_id, "❌ <b>ПЛАТЕЖ НЕ НАЙДЕН</b>\n\nСоздайте новый счёт.", {"inline_keyboard": [[{"text": "⭐ НОВЫЙ СЧЁТ", "callback_data": "dep_stars"}], [{"text": "💎 ПОПОЛНИТЬ TON", "callback_data": "dep_ton"}]]})

def handle_check_payment(cb, chat_id, msg_id, uid, pid):
    tg_answer(cb["id"], "🔍 Проверяю блокчейн...")
    result = verify_ton_transaction(TON_WALLET, pid)
    
    if result:
        amt = result['amount']
        with db_connect() as conn:
            conn.execute('UPDATE users SET balance_ton=balance_ton+?, total_deposited_ton=total_deposited_ton+?, pending_payment_id=NULL WHERE user_id=?', (amt, amt, uid))
        tg_edit(chat_id, msg_id, f"✅ <b>ЗАЧИСЛЕНО!</b>\n\n💰 +{amt:.4f} TON\n\n🎁 Открывайте кейсы!", {"inline_keyboard": [[{"text": "🎁 ОТКРЫТЬ ПРИЛОЖЕНИЕ", "web_app": {"url": WEBAPP_URL}}]]})
    else:
        tg_edit(chat_id, msg_id, "❌ <b>ПЛАТЕЖ НЕ НАЙДЕН</b>\n\n• Проверьте код\n• Мин: 1 TON", {"inline_keyboard": [[{"text": "🔄 ПРОВЕРИТЬ СНОВА", "callback_data": f"check_{pid}"}], [{"text": "💎 НОВЫЙ КОД", "callback_data": "dep_ton"}]]})

def handle_profile(cb, chat_id, msg_id, uid, fname):
    tg_answer(cb["id"])
    with db_connect() as conn:
        row = conn.execute('SELECT balance_ton, balance_stars, total_deposited_ton, total_deposited_stars, referral_count FROM users WHERE user_id=?', (uid,)).fetchone()
    if row:
        ton, stars, dep_ton, dep_stars, ref = row
        tg_edit(chat_id, msg_id, f"💼 <b>{fname}</b>\n\n💎 TON: <b>{ton:.4f}</b>\n⭐ Stars: <b>{stars}</b>\n📥 TON: <b>{dep_ton:.2f}</b>\n📥 Stars: <b>{dep_stars}</b>\n👥 Рефералов: <b>{ref}/3</b>", {"inline_keyboard": [[{"text": "🎁 ОТКРЫТЬ ПРИЛОЖЕНИЕ", "web_app": {"url": WEBAPP_URL}}], [{"text": "💰 ПОПОЛНИТЬ TON", "callback_data": "dep_ton"}], [{"text": "⭐ ПОПОЛНИТЬ STARS", "callback_data": "dep_stars"}], [{"text": "🏠 МЕНЮ", "callback_data": "menu"}]]})

def handle_ref_info(cb, chat_id, msg_id, uid):
    tg_answer(cb["id"])
    with db_connect() as conn:
        row = conn.execute('SELECT referral_code, referral_count FROM users WHERE user_id=?', (uid,)).fetchone()
    if row:
        ref_code, ref_count = row
        ref_link = f"https://t.me/{BOT_USERNAME}?start={ref_code}"
        need = max(0, 3 - ref_count)
        tg_edit(chat_id, msg_id, f"👥 <b>РЕФЕРАЛЬНАЯ СИСТЕМА</b>\n\nПригласите 3 друзей — получите <b>БЕСПЛАТНЫЙ КЕЙС</b>!\n\n🔗 Ваша ссылка:\n<code>{ref_link}</code>\n\n📊 Приглашено: <b>{ref_count}/3</b>\n{'✅ Бесплатный кейс доступен!' if ref_count >= 3 else '❌ Пригласите ещё ' + str(need)}", {"inline_keyboard": [[{"text": "📤 ПОДЕЛИТЬСЯ", "switch_inline_query": ref_code}], [{"text": "🎁 ОТКРЫТЬ ПРИЛОЖЕНИЕ", "web_app": {"url": WEBAPP_URL}}]]})

# =================================================================
# FLASK APP
# =================================================================
flask_app = Flask(__name__)

@flask_app.route('/')
def webapp():
    return render_template_string(HTML_TEMPLATE)

@flask_app.route('/api/user/<int:uid>')
def api_user(uid):
    try:
        with db_connect() as conn:
            row = conn.execute('SELECT balance_ton, balance_stars, gift_items, withdrawn_items, referral_count, free_case_available, language, total_deposited_ton, total_deposited_stars FROM users WHERE user_id=?', (uid,)).fetchone()
        
        if row:
            return jsonify({
                'balance_ton': row[0], 'balance_stars': row[1],
                'gift_items': json.loads(row[2]) if row[2] else [],
                'withdrawn_items': json.loads(row[3]) if row[3] else [],
                'referral_count': row[4], 'free_case_available': row[5] or 0,
                'free_case_timer': 0,
                'language': row[6], 'deposited_ton': row[7], 'deposited_stars': row[8]
            })
        else:
            ref_code = generate_ref_code(uid)
            conn.execute('INSERT INTO users (user_id, username, first_name, referral_code, balance_stars, balance_ton) VALUES (?, ?, ?, ?, 0, 0)', 
                        (uid, f"user_{uid}", "Player", ref_code))
            conn.commit()
            
            return jsonify({
                'balance_ton': 0, 'balance_stars': 0,
                'gift_items': [], 'withdrawn_items': [],
                'referral_count': 0, 'free_case_available': 0,
                'free_case_timer': 0,
                'language': 'ru', 'deposited_ton': 0, 'deposited_stars': 0
            })
    except Exception as e:
        logger.error(f"User load error: {e}")
    
    return jsonify({
        'balance_ton': 0, 'balance_stars': 0,
        'gift_items': [], 'withdrawn_items': [],
        'referral_count': 0, 'free_case_available': 0,
        'free_case_timer': 0,
        'language': 'ru', 'deposited_ton': 0, 'deposited_stars': 0
    })

@flask_app.route('/api/cases')
def api_cases():
    lang = request.args.get('lang', 'ru')
    return jsonify(get_cases_for_api(lang))

@flask_app.route('/api/live_drops')
def api_live_drops():
    with db_connect() as conn:
        rows = conn.execute('SELECT username, item_name, item_icon, case_name, value_stars, value_ton, created_at FROM live_drops ORDER BY created_at DESC LIMIT 20').fetchall()
    
    drops = []
    for row in rows:
        drops.append({
            'username': row[0],
            'item_name': row[1],
            'item_icon': row[2],
            'case_name': row[3],
            'value_stars': row[4],
            'value_ton': row[5],
            'time': row[6]
        })
    
    return jsonify(drops)

@flask_app.route('/api/open_case', methods=['POST'])
def api_open_case():
    data = request.json
    uid = data.get('user_id')
    case_id = data.get('case_id')
    currency = data.get('currency', 'STARS')
    is_demo = data.get('demo_mode', False)
    
    if case_id not in CASES_DATA: return jsonify({'error': 'Кейс не найден!'}), 404
    case = CASES_DATA[case_id]
    
    with db_connect() as conn:
        row = conn.execute('SELECT balance_ton, balance_stars, free_case_available, gift_items, language, username FROM users WHERE user_id=?', (uid,)).fetchone()
        if not row: return jsonify({'error': 'Пользователь не найден!'}), 404
        ton_bal, stars_bal, free_avail, gifts_json, user_lang, username = row
        gifts = json.loads(gifts_json) if gifts_json else []
        
        if case_id == 'free':
            if free_avail <= 0: return jsonify({'error': 'Нужно пригласить 3 друзей!'}), 400
            conn.execute('UPDATE users SET free_case_available=0, referral_count=0 WHERE user_id=?', (uid,))
        elif not is_demo:
            if case.get('price_ton') and not case.get('price_stars'):
                price = case['price_ton']
                if ton_bal < price: return jsonify({'error': 'Недостаточно TON!'}), 400
                conn.execute('UPDATE users SET balance_ton=balance_ton-? WHERE user_id=?', (price, uid))
            elif case.get('price_stars') and not case.get('price_ton'):
                price = case['price_stars']
                if stars_bal < price: return jsonify({'error': 'Недостаточно Stars!'}), 400
                conn.execute('UPDATE users SET balance_stars=balance_stars-? WHERE user_id=?', (price, uid))
            elif case.get('price_ton') and case.get('price_stars'):
                price = case['price_ton'] if currency == 'TON' else case['price_stars']
                if currency == 'TON' and ton_bal < price: return jsonify({'error': 'Недостаточно TON!'}), 400
                if currency == 'STARS' and stars_bal < price: return jsonify({'error': 'Недостаточно Stars!'}), 400
                conn.execute(f'UPDATE users SET {"balance_ton" if currency=="TON" else "balance_stars"}={"balance_ton" if currency=="TON" else "balance_stars"}-? WHERE user_id=?', (price, uid))
        
        pool = []
        for item in case['items']:
            chance = item['chance_demo'] if (is_demo or case_id == 'free') else item['chance_real']
            pool.extend([item] * int(chance * 10))
        
        winner = random.choice(pool) if pool else case['items'][-1]
        winner_name = winner.get(f'name_{user_lang}', winner.get('name_ru', ''))
        
        if not is_demo:
            gifts.append({'name': winner_name, 'icon': winner['icon'], 'value_stars': winner.get('value_stars', 0), 'value_ton': winner.get('value_ton', 0), 'timestamp': datetime.now().isoformat()})
            conn.execute('UPDATE users SET gift_items=? WHERE user_id=?', (json.dumps(gifts), uid))
            
            conn.execute('INSERT INTO live_drops (user_id, username, item_name, item_icon, case_name, value_stars, value_ton) VALUES (?, ?, ?, ?, ?, ?, ?)',
                        (uid, username or f"user_{uid}", winner_name, winner['icon'], case.get(f'name_{user_lang}', case.get('name_ru', '')), winner.get('value_stars', 0), winner.get('value_ton', 0)))
        
        new_ton = conn.execute('SELECT balance_ton FROM users WHERE user_id=?', (uid,)).fetchone()[0]
        new_stars = conn.execute('SELECT balance_stars FROM users WHERE user_id=?', (uid,)).fetchone()[0]
    
    return jsonify({
        'winner': {'name': winner_name, 'icon': winner['icon'], 'value_stars': winner.get('value_stars', 0), 'value_ton': winner.get('value_ton', 0)}, 
        'balance_ton': new_ton, 'balance_stars': new_stars, 
        'is_demo': is_demo,
        'free_case_available': 0 if case_id == 'free' else free_avail,
        'free_case_timer': 0
    })

@flask_app.route('/api/sell_item', methods=['POST'])
def api_sell_item():
    data = request.json; uid = data.get('user_id'); idx = data.get('item_index')
    with db_connect() as conn:
        row = conn.execute('SELECT gift_items, balance_ton, balance_stars FROM users WHERE user_id=?', (uid,)).fetchone()
        if not row: return jsonify({'error': 'Не найдено!'}), 404
        gifts = json.loads(row[0]) if row[0] else []
        if idx < 0 or idx >= len(gifts): return jsonify({'error': 'Предмет не найден!'}), 404
        item = gifts.pop(idx)
        vs = int(item.get('value_stars', 0) * 0.98); vt = round(item.get('value_ton', 0) * 0.98, 2)
        conn.execute('UPDATE users SET gift_items=?, balance_stars=balance_stars+?, balance_ton=balance_ton+? WHERE user_id=?', (json.dumps(gifts), vs, vt, uid))
    return jsonify({'success': True, 'received_stars': vs, 'received_ton': vt, 'balance_ton': row[1] + vt, 'balance_stars': row[2] + vs})

@flask_app.route('/api/withdraw_item', methods=['POST'])
def api_withdraw_item():
    data = request.json; uid = data.get('user_id'); idx = data.get('item_index'); wallet = data.get('wallet', '')
    with db_connect() as conn:
        row = conn.execute('SELECT gift_items, withdrawn_items FROM users WHERE user_id=?', (uid,)).fetchone()
        if not row: return jsonify({'error': 'Не найдено!'}), 404
        gifts = json.loads(row[0]) if row[0] else []; withdrawn = json.loads(row[1]) if row[1] else []
        if idx < 0 or idx >= len(gifts): return jsonify({'error': 'Предмет не найден!'}), 404
        item = gifts.pop(idx); item['withdrawn_at'] = datetime.now().isoformat(); item['wallet'] = wallet; item['status'] = 'completed'
        withdrawn.append(item)
        conn.execute('UPDATE users SET gift_items=?, withdrawn_items=? WHERE user_id=?', (json.dumps(gifts), json.dumps(withdrawn), uid))
    return jsonify({'success': True, 'message': f'✅ {item["name"]} выведен на {wallet[:10]}...', 'item': item})

@flask_app.route('/api/language', methods=['POST'])
def api_language():
    data = request.json; uid = data.get('user_id'); lang = data.get('language', 'ru')
    with db_connect() as conn: conn.execute('UPDATE users SET language=? WHERE user_id=?', (lang, uid))
    return jsonify({'success': True})

@flask_app.route('/api/create_stars_invoice', methods=['POST'])
def api_create_stars_invoice():
    data = request.json
    uid = data.get('user_id')
    amount = data.get('amount', 50)
    
    charge_id = f"stars_{uid}_{int(time.time())}"
    with db_connect() as conn:
        conn.execute('INSERT INTO stars_payments (user_id, stars_amount, charge_id, status) VALUES (?,?,?,?)', (uid, amount, charge_id, 'pending'))
    
    success, result = create_stars_invoice(uid, amount)
    
    if success:
        return jsonify({'success': True, 'charge_id': charge_id, 'message': f'Счёт на {amount} Stars отправлен!'})
    else:
        error_msg = result.get('description', 'Unknown error') if isinstance(result, dict) else str(result)
        with db_connect() as conn:
            conn.execute('DELETE FROM stars_payments WHERE charge_id=?', (charge_id,))
        return jsonify({'success': False, 'error': error_msg})

@flask_app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = request.get_json()
        
        if "message" in update:
            msg = update["message"]
            
            if "successful_payment" in msg:
                payment = msg["successful_payment"]
                uid = msg["from"]["id"]
                payload = payment.get("invoice_payload", "")
                charge_id = payment.get("telegram_payment_charge_id", "")
                stars_amount = payment["total_amount"]
                
                if payload.startswith("stars_deposit_"):
                    with db_connect() as conn:
                        conn.execute('UPDATE users SET balance_stars=balance_stars+?, total_deposited_stars=total_deposited_stars+? WHERE user_id=?', (stars_amount, stars_amount, uid))
                        conn.execute('INSERT INTO transactions (user_id, type, amount, currency, tx_hash) VALUES (?,?,?,?,?)', (uid, 'deposit_stars', stars_amount, 'STARS', charge_id))
                        conn.execute('UPDATE stars_payments SET status=? WHERE user_id=? AND status=?', ('completed', uid, 'pending'))
                    
                    tg_send(msg["chat"]["id"], f"✅ <b>ПЛАТЕЖ ПОДТВЕРЖДЁН!</b>\n\n⭐ +{stars_amount} Stars зачислено!\n\n🎁 Открывайте кейсы!")
                    tg_send(ADMIN_ID, f"⭐ <b>ЗВЁЗДЫ ПОЛУЧЕНЫ!</b>\n\n👤 ID: <code>{uid}</code>\n⭐ Сумма: {stars_amount} Stars\n🔗 ID: <code>{charge_id}</code>")
                    
                    return "ok", 200
            
            chat_id = msg["chat"]["id"]
            user = msg["from"]
            uid = user["id"]
            
            if "text" in msg:
                text = msg["text"]
                if text.startswith("/start"):
                    args = text.replace("/start", "").strip().split()
                    handle_start(chat_id, user, args if args else None)
                elif text.startswith("/withdraw"):
                    try:
                        parts = text.split(); amt = float(parts[1]); wallet = parts[2] if len(parts) > 2 else None
                        if not wallet: tg_send(chat_id, "❌ /withdraw СУММА КОШЕЛЕК")
                        elif amt < 1: tg_send(chat_id, "❌ Мин: 1 TON")
                        else:
                            with db_connect() as conn:
                                row = conn.execute('SELECT balance_ton FROM users WHERE user_id=?', (uid,)).fetchone()
                                if not row or row[0] < amt: tg_send(chat_id, "❌ Недостаточно!")
                                else:
                                    conn.execute('UPDATE users SET balance_ton=balance_ton-? WHERE user_id=?', (amt, uid))
                                    conn.execute('INSERT INTO withdrawal_requests (user_id, item_name, amount, currency, wallet, status) VALUES (?,?,?,?,?,?)', (uid, 'TON Вывод', amt, 'TON', wallet, 'completed'))
                                    tg_send(chat_id, f"✅ Заявка на <b>{amt} TON</b> создана!")
                    except: tg_send(chat_id, "❌ /withdraw СУММА КОШЕЛЕК")
        
        elif "callback_query" in update:
            cb = update["callback_query"]
            chat_id = cb["message"]["chat"]["id"]
            msg_id = cb["message"]["message_id"]
            uid = cb["from"]["id"]
            fname = cb["from"].get("first_name", "Player")
            data = cb.get("data", "")
            
            if data == "dep_ton": handle_dep_ton(cb, chat_id, msg_id, uid)
            elif data == "dep_stars": handle_dep_stars(cb, chat_id, msg_id, uid)
            elif data.startswith("stars_invoice_"):
                amount = int(data.replace("stars_invoice_", ""))
                handle_stars_invoice(cb, chat_id, msg_id, uid, amount)
            elif data.startswith("check_stars_"):
                charge_id = data.replace("check_stars_", "")
                handle_check_stars(cb, chat_id, msg_id, uid, charge_id)
            elif data == "profile": handle_profile(cb, chat_id, msg_id, uid, fname)
            elif data == "ref_info": handle_ref_info(cb, chat_id, msg_id, uid)
            elif data == "menu": tg_edit(chat_id, msg_id, "🎁 <b>GIFT CASES</b>", {"inline_keyboard": [[{"text": "🎁 ОТКРЫТЬ ПРИЛОЖЕНИЕ", "web_app": {"url": WEBAPP_URL}}]]}); tg_answer(cb["id"])
            elif data.startswith("check_"): handle_check_payment(cb, chat_id, msg_id, uid, data.replace("check_", ""))
            else: tg_answer(cb["id"])
        
        return "ok", 200
    except Exception as e:
        logger.error(f"Webhook: {e}")
        return "error", 500

@flask_app.route('/health')
def health(): return jsonify({"status": "ok"})

# =================================================================
# HTML ШАБЛОН (ФИНАЛЬНАЯ ВЕРСИЯ С АВАТАРКАМИ)
# =================================================================
HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="theme-color" content="#0a0a1a">
    <title>GIFT CASES</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
        :root{--bg:#0a0a1a;--card:#141428;--gold:#ffd700;--accent:#7c3aed;--text:#fff;--sub:#888;--border:rgba(255,255,255,0.06)}
        *{margin:0;padding:0;box-sizing:border-box}
        body{background:var(--bg);color:var(--text);font-family:'Inter',sans-serif;min-height:100vh;overflow-x:hidden;-webkit-tap-highlight-color:transparent;user-select:none}
        .app{max-width:440px;margin:0 auto;min-height:100vh;position:relative;padding-bottom:90px}
        .page{display:none;padding:12px;animation:fadeIn 0.3s ease}.page.active{display:block}
        @keyframes fadeIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
        .topbar{display:flex;align-items:center;justify-content:space-between;padding:10px 16px;background:var(--card);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:50}
        .topbar-title{font-weight:700;font-size:16px}
        .back-btn{width:36px;height:36px;border-radius:50%;background:rgba(255,255,255,0.05);border:none;color:#fff;font-size:18px;cursor:pointer;display:flex;align-items:center;justify-content:center}
        .avatar-sm{width:36px;height:36px;border-radius:50%;background:linear-gradient(135deg,var(--accent),#a855f7);display:flex;align-items:center;justify-content:center;font-weight:700;font-size:16px;cursor:pointer;background-size:cover;background-position:center;flex-shrink:0}
        .bal-row{display:flex;gap:8px;padding:8px 12px;overflow-x:auto}
        .bal-chip{flex-shrink:0;padding:6px 12px;border-radius:20px;background:var(--card);font-size:12px;font-weight:600;white-space:nowrap;border:1px solid var(--border)}
        .bal-chip.ton{color:var(--gold)}.bal-chip.stars{color:#60a5fa}
        .deposit-row{display:flex;gap:8px;padding:0 12px 8px}
        .deposit-btn-top{flex:1;padding:10px;border-radius:14px;font-size:12px;font-weight:600;cursor:pointer;border:none;transition:all 0.3s;text-align:center}
        .deposit-btn-top.ton-btn{background:rgba(255,215,0,0.15);color:var(--gold);border:1px solid rgba(255,215,0,0.3)}
        .deposit-btn-top.stars-btn{background:rgba(96,165,250,0.15);color:#60a5fa;border:1px solid rgba(96,165,250,0.3)}
        .deposit-btn-top:active{transform:scale(0.95)}
        
        .live-drops-section{padding:0 12px 8px}
        .live-drops-title{font-weight:700;font-size:12px;color:var(--sub);text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;display:flex;align-items:center;gap:6px}
        .live-dots{width:8px;height:8px;border-radius:50%;background:#10B981;animation:pulse 2s infinite}
        @keyframes pulse{0%,100%{opacity:1}50%{opacity:0.3}}
        .live-drops-scroll{display:flex;gap:6px;overflow-x:auto;padding-bottom:4px}
        .live-drop-item{flex-shrink:0;padding:8px 10px;background:var(--card);border-radius:10px;border:1px solid var(--border);font-size:11px;white-space:nowrap;display:flex;align-items:center;gap:6px}
        .live-drop-icon{font-size:18px}
        .live-drop-name{font-weight:600;color:var(--gold)}
        .live-drop-case{font-size:9px;color:var(--sub)}
        
        .cases-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:12px}
        .case-card{padding:20px 14px;border-radius:20px;text-align:center;cursor:pointer;transition:all 0.3s;border:2px solid var(--border);position:relative;overflow:hidden;background:var(--card)}
        .case-card:active{transform:scale(0.95)}.case-card.featured{grid-column:1/-1;padding:24px}
        .case-card.free-case{border-color:#10B981;background:rgba(16,185,129,0.05)}
        .case-card.free-case.locked{opacity:0.5;pointer-events:none;border-color:#333}
        .case-icon{font-size:48px;margin-bottom:8px;position:relative;z-index:1}.case-card.featured .case-icon{font-size:60px}
        .case-name{font-weight:700;font-size:14px;margin-bottom:4px;position:relative;z-index:1}.case-card.featured .case-name{font-size:17px}
        .case-price{font-size:12px;font-weight:600;position:relative;z-index:1}
        .demo-toggle-inner{display:flex;align-items:center;justify-content:center;gap:10px;padding:10px 12px;margin:0 12px 12px;background:var(--card);border-radius:14px;border:1px solid var(--border)}
        .demo-label-inner{font-size:13px;font-weight:600;color:var(--sub)}
        .demo-switch-inner{position:relative;width:52px;height:28px;cursor:pointer}
        .demo-switch-track-inner{position:absolute;top:0;left:0;width:100%;height:100%;border-radius:14px;background:#333;transition:all 0.3s}
        .demo-switch-inner.active .demo-switch-track-inner{background:#10B981}
        .demo-switch-thumb-inner{position:absolute;top:3px;left:3px;width:22px;height:22px;border-radius:50%;background:#fff;transition:all 0.3s;box-shadow:0 1px 3px rgba(0,0,0,0.3)}
        .demo-switch-inner.active .demo-switch-thumb-inner{left:27px}
        .case-detail-header{text-align:center;padding:20px}.case-detail-icon{font-size:72px;margin-bottom:8px}.case-detail-name{font-weight:800;font-size:22px}.case-detail-price{font-size:15px;color:var(--gold);margin-top:4px}
        .items-preview{padding:0 12px 12px}.items-preview-title{font-weight:600;font-size:13px;color:var(--sub);margin-bottom:10px;text-transform:uppercase;letter-spacing:1px}
        .items-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
        .item-mini{display:flex;align-items:center;gap:10px;padding:10px 12px;background:var(--card);border-radius:12px;border:1px solid var(--border);font-size:12px}
        .item-mini-icon{font-size:36px;width:44px;text-align:center}.item-mini-name{font-weight:600;font-size:11px}.item-mini-chance{font-size:10px;color:var(--gold)}
        .spin-btn{display:block;width:calc(100% - 24px);margin:0 12px 12px;padding:16px;border-radius:16px;font-weight:700;font-size:16px;border:none;cursor:pointer;text-transform:uppercase;letter-spacing:1px;transition:all 0.3s}
        .spin-btn:active{transform:scale(0.97)}.spin-btn.active{background:linear-gradient(135deg,var(--accent),#a855f7);color:#fff;box-shadow:0 0 30px rgba(124,58,237,0.4)}.spin-btn.disabled{background:#333;color:#666;cursor:not-allowed}
        .spin-btn.demo-btn{background:linear-gradient(135deg,#10B981,#34d399);color:#fff;box-shadow:0 0 20px rgba(16,185,129,0.3)}
        .spin-btn.free-btn{background:linear-gradient(135deg,#10B981,#059669);color:#fff;box-shadow:0 0 20px rgba(16,185,129,0.3)}
        .spin-anim{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.95);z-index:200;flex-direction:column;align-items:center;justify-content:center}.spin-anim.active{display:flex}
        .roulette-window{width:92%;max-width:380px;height:110px;background:var(--card);border-radius:24px;overflow:hidden;position:relative;border:2px solid var(--border);margin-bottom:20px;box-shadow:0 20px 40px rgba(0,0,0,0.5)}
        .roulette-window::before,.roulette-window::after{content:'';position:absolute;left:0;width:100%;height:35px;z-index:2;pointer-events:none}
        .roulette-window::before{top:0;background:linear-gradient(to bottom,var(--card),transparent)}.roulette-window::after{bottom:0;background:linear-gradient(to top,var(--card),transparent)}
        .pointer-area{position:absolute;left:50%;top:0;width:4px;height:100%;z-index:3;transform:translateX(-50%)}
        .pointer-line{position:absolute;left:50%;top:0;width:3px;height:100%;background:var(--gold);transform:translateX(-50%);box-shadow:0 0 15px rgba(255,215,0,0.6),0 0 30px rgba(255,215,0,0.3)}
        .pointer-arrow-top{position:absolute;left:50%;top:8px;transform:translateX(-50%);color:var(--gold);font-size:16px;z-index:4;filter:drop-shadow(0 0 6px rgba(255,215,0,0.8))}
        .pointer-arrow-bottom{position:absolute;left:50%;bottom:8px;transform:translateX(-50%) rotate(180deg);color:var(--gold);font-size:16px;z-index:4;filter:drop-shadow(0 0 6px rgba(255,215,0,0.8))}
        .roulette-track{display:flex;position:absolute;left:50%;top:15px;transform:translateX(0);transition:transform 6s cubic-bezier(0.05,0.95,0.1,1)}
        .roulette-item{width:80px;height:80px;display:flex;align-items:center;justify-content:center;font-size:44px;flex-shrink:0;opacity:0.45;transition:all 0.3s;border-radius:16px;margin:0 4px}
        .roulette-item.highlight{opacity:1;transform:scale(1.2);background:rgba(255,215,0,0.12);border:2px solid var(--gold);box-shadow:0 0 30px rgba(255,215,0,0.5),0 0 60px rgba(255,215,0,0.2);z-index:5}
        .spin-text{font-size:18px;color:var(--sub);font-weight:600;transition:all 0.3s}.spin-text.win{color:var(--gold);font-size:22px;font-weight:800}
        .result-toast{position:fixed;top:16px;left:50%;transform:translateX(-50%);padding:14px 20px;background:var(--card);border-radius:14px;z-index:300;text-align:center;font-weight:600;font-size:13px;border:1px solid var(--gold);animation:slideDown 0.4s ease;cursor:pointer;box-shadow:0 10px 30px rgba(0,0,0,0.5);display:flex;align-items:center;gap:10px}
        @keyframes slideDown{from{transform:translate(-50%,-100%);opacity:0}to{transform:translate(-50%,0);opacity:1}}
        .profile-header{text-align:center;padding:20px}
        .profile-avatar{width:64px;height:64px;border-radius:50%;background:linear-gradient(135deg,var(--accent),#a855f7);display:flex;align-items:center;justify-content:center;font-size:28px;font-weight:700;margin:0 auto 8px;background-size:cover;background-position:center}
        .tab-row{display:flex;gap:2px;padding:4px;background:var(--card);border-radius:12px;margin:0 12px 12px;overflow-x:auto}
        .tab-btn{flex:1;min-width:fit-content;padding:10px 8px;text-align:center;border-radius:10px;cursor:pointer;font-weight:600;font-size:11px;color:var(--sub);border:none;background:transparent;transition:all 0.3s;white-space:nowrap}.tab-btn.active{background:var(--accent);color:#fff}
        .tab-content{display:none;padding:12px}.tab-content.active{display:block}
        .gift-item-card{display:flex;align-items:center;gap:12px;padding:12px;background:var(--card);border-radius:12px;margin-bottom:8px;border:1px solid var(--border)}
        .gift-item-icon{font-size:44px;width:54px;text-align:center}.gift-item-info{flex:1}.gift-item-name{font-weight:600;font-size:14px}.gift-item-value{font-size:11px;color:var(--gold)}.gift-item-status{font-size:10px;color:#10B981;margin-top:2px}
        .gift-item-actions{display:flex;gap:6px}.btn-sm{padding:8px 12px;border-radius:8px;font-size:11px;font-weight:600;cursor:pointer;border:none;transition:all 0.3s}.btn-sm:active{transform:scale(0.95)}.btn-sell{background:#ef4444;color:#fff}.btn-withdraw{background:#3b82f6;color:#fff}
        .faq-item{padding:12px;background:var(--card);border-radius:12px;margin-bottom:8px;border:1px solid var(--border)}.faq-q{font-weight:600;margin-bottom:4px}.faq-a{font-size:13px;color:var(--sub)}
        .bottom-nav{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);display:flex;gap:4px;padding:6px;background:var(--card);border-radius:20px;z-index:100;border:1px solid var(--border);box-shadow:0 10px 30px rgba(0,0,0,0.3)}
        .nav-btn{width:52px;height:52px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:20px;cursor:pointer;transition:all 0.3s;border:none;background:transparent;flex-direction:column;gap:1px}.nav-btn.active{background:var(--accent);box-shadow:0 0 15px rgba(124,58,237,0.4)}.nav-label{font-size:8px;font-weight:600;color:var(--sub)}.nav-btn.active .nav-label{color:#fff}
        .payment-modal{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.9);z-index:400;align-items:center;justify-content:center}.payment-modal.active{display:flex}
        .payment-card{width:90%;max-width:380px;padding:24px;background:var(--card);border-radius:20px;border:1px solid var(--border);text-align:center}
        .payment-close{float:right;background:none;border:none;color:#fff;font-size:20px;cursor:pointer}
        .payment-code{font-size:18px;font-weight:700;background:rgba(255,215,0,0.1);padding:10px;border-radius:10px;margin:12px 0;word-break:break-all;color:var(--gold)}
        .payment-wallet{font-size:12px;color:var(--sub);word-break:break-all;margin-bottom:12px}
        .payment-btn{width:100%;padding:14px;border-radius:12px;font-weight:700;cursor:pointer;border:none;margin-top:8px;font-size:14px}
        .payment-btn.check{background:var(--accent);color:#fff}.payment-btn.cancel{background:#333;color:#fff}.payment-btn.bot{background:#3b82f6;color:#fff}
        .stars-amount-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px}
        .stars-amount-btn{padding:12px;border-radius:12px;background:var(--card);border:1px solid var(--border);color:#fff;font-weight:600;cursor:pointer;transition:all 0.3s;text-align:center;font-size:14px}
        .stars-amount-btn:hover{border-color:#60a5fa}.stars-amount-btn:active{transform:scale(0.95)}
        .lang-btn{padding:14px;margin-bottom:8px;color:#fff;font-size:15px;border:none;border-radius:12px;cursor:pointer;font-weight:600;width:100%;transition:all 0.2s;background:var(--accent)}.lang-btn:active{transform:scale(0.96);opacity:0.8}.lang-btn.en{background:#3b82f6}
    </style>
</head>
<body>
<div class="app">
    <div class="topbar" id="topbarMain"><div class="topbar-title" id="mainTitle">🎁 Кейсы</div><div class="avatar-sm" id="avatarSm">S</div></div>
    <div class="topbar" id="topbarCase" style="display:none"><button class="back-btn" onclick="goBack()">←</button><div class="topbar-title" id="caseTopTitle">Кейс</div><div style="width:36px"></div></div>
    <div class="bal-row"><div class="bal-chip ton" id="tonChip">💎 0.00 TON</div><div class="bal-chip stars" id="starsChip">⭐ 0 Stars</div></div>
    <div class="deposit-row" id="depositRow">
        <button class="deposit-btn-top ton-btn" onclick="openDeposit('TON')" id="btnDepTon">💎 Пополнить TON</button>
        <button class="deposit-btn-top stars-btn" onclick="openDeposit('STARS')" id="btnDepStars">⭐ Пополнить Stars</button>
    </div>

    <div class="live-drops-section">
        <div class="live-drops-title"><div class="live-dots"></div> <span id="liveTitle">LIVE Дропы</span></div>
        <div class="live-drops-scroll" id="liveDropsScroll">
            <div class="live-drop-item"><span style="color:var(--sub)">Загрузка...</span></div>
        </div>
    </div>

    <div class="page active" id="page-cases"><div class="cases-grid" id="casesGrid"></div></div>

    <div class="page" id="page-case-detail">
        <div class="case-detail-header"><div class="case-detail-icon" id="detailIcon">📦</div><div class="case-detail-name" id="detailName">Обычный кейс</div><div class="case-detail-price" id="detailPrice">50 Stars</div></div>
        <div class="demo-toggle-inner" id="demoToggleRow"><span class="demo-label-inner" id="demoLabel">Демо-режим</span><div class="demo-switch-inner" id="demoSwitchInner" onclick="toggleDemoInner()"><div class="demo-switch-track-inner"></div><div class="demo-switch-thumb-inner"></div></div></div>
        <div class="items-preview"><div class="items-preview-title" id="itemsTitle">Возможные призы</div><div class="items-grid" id="detailItems"></div></div>
        <button class="spin-btn active" id="detailSpinBtn" onclick="startSpin()">🎰 НАЧАТЬ КРУТИТЬ</button>
    </div>

    <div class="page" id="page-wins"><div id="winsList"></div></div>
    <div class="page" id="page-faq">
        <div class="faq-item"><div class="faq-q" id="faqQ1">❓ Как пополнить Stars?</div><div class="faq-a" id="faqA1">Нажмите кнопку «Пополнить Stars», выберите сумму и оплатите счёт в чате с ботом.</div></div>
        <div class="faq-item"><div class="faq-q" id="faqQ2">❓ Как получить бесплатный кейс?</div><div class="faq-a" id="faqA2">Пригласите 3 друзей — получите бесплатный кейс! После открытия счётчик сбрасывается.</div></div>
    </div>
    <div class="page" id="page-lang">
        <div style="text-align:center;padding:40px 20px"><div style="font-size:48px;margin-bottom:16px">🌐</div><div style="font-weight:700;font-size:18px;margin-bottom:20px" id="langTitle">Выберите язык</div>
            <button class="lang-btn" onclick="setLang('ru')">🇷🇺 Русский</button><button class="lang-btn en" onclick="setLang('en')">🇬🇧 English</button></div>
    </div>
    <div class="page" id="page-profile">
        <div class="profile-header"><div class="profile-avatar" id="profileAvatar">S</div><div style="font-weight:700;font-size:16px;margin-top:4px" id="profileName">Player</div></div>
        <div class="tab-row">
            <button class="tab-btn active" onclick="profileTab('info')" id="tabInfo">📋 Инфо</button><button class="tab-btn" onclick="profileTab('wins')" id="tabWins">🏆 Выигрыши</button><button class="tab-btn" onclick="profileTab('faq')" id="tabFaq">❓ FAQ</button><button class="tab-btn" onclick="profileTab('lang')" id="tabLang">🌐 Язык</button>
        </div>
        <div class="tab-content active" id="ptab-info">
            <div style="text-align:center;padding:10px">
                <div style="margin:12px 0;font-size:15px">💎 TON: <b id="pTon" style="color:var(--gold)">0.00</b></div>
                <div style="margin:12px 0;font-size:15px">⭐ Stars: <b id="pStars" style="color:#60a5fa">0</b></div>
                <div style="margin:12px 0;font-size:14px;color:var(--sub)" id="depTonLabel">📥 Пополнено TON: <b id="pDepTon">0</b></div>
                <div style="margin:12px 0;font-size:14px;color:var(--sub)" id="depStarsLabel">📥 Пополнено Stars: <b id="pDepStars">0</b></div>
                <div style="margin:12px 0;font-size:14px;color:var(--sub)" id="giftsLabel">🎁 Подарков: <b id="pGifts">0</b></div>
                <div style="margin:12px 0;font-size:14px;color:var(--sub)">👥 Рефералов: <b id="pRef">0/3</b></div>
            </div>
        </div>
        <div class="tab-content" id="ptab-wins"><div id="profileWinsList"></div></div>
        <div class="tab-content" id="ptab-faq"><div class="faq-item"><div class="faq-q">❓ Как продать?</div><div class="faq-a" id="faqSell">В «Выигрыши» нажмите «Продать».</div></div></div>
        <div class="tab-content" id="ptab-lang"><button class="lang-btn" onclick="setLang('ru')">🇷🇺 Русский</button><button class="lang-btn en" onclick="setLang('en')">🇬🇧 English</button></div>
    </div>
</div>

<div class="spin-anim" id="spinAnim"><div class="roulette-window" id="rouletteWindow"><div class="pointer-area"><div class="pointer-arrow-top">▼</div><div class="pointer-line"></div><div class="pointer-arrow-bottom">▼</div></div><div class="roulette-track" id="rouletteTrack"></div></div><div class="spin-text" id="spinText">Крутим...</div></div>
<div class="result-toast" id="resultToast" style="display:none"><div id="toastIcon" style="font-size:32px">🎁</div><div><div id="toastName" style="font-weight:700;font-size:14px">Подарок</div></div></div>
<div class="payment-modal" id="paymentModal"><div class="payment-card"><button class="payment-close" onclick="closePayment()">✕</button><div style="font-size:40px;margin-bottom:8px" id="payIcon">💎</div><div style="font-weight:700;font-size:18px;margin-bottom:12px" id="payTitle">Пополнение</div><div id="payContent"></div><button class="payment-btn cancel" onclick="closePayment()">Закрыть</button></div></div>

<div class="bottom-nav">
    <button class="nav-btn active" id="navCases" onclick="navigate('cases')"><span>🎁</span><span class="nav-label" id="navLabelCases">Кейсы</span></button>
    <button class="nav-btn" id="navWins" onclick="navigate('wins')"><span>🏆</span><span class="nav-label" id="navLabelWins">Выигрыши</span></button>
    <button class="nav-btn" id="navFaq" onclick="navigate('faq')"><span>❓</span><span class="nav-label">FAQ</span></button>
    <button class="nav-btn" id="navLang" onclick="navigate('lang')"><span>🌐</span><span class="nav-label" id="navLabelLang">Язык</span></button>
    <button class="nav-btn" id="navProfile" onclick="navigate('profile')"><span>👤</span><span class="nav-label" id="navLabelProfile">Профиль</span></button>
</div>

<script>
const tg=window.Telegram.WebApp;tg.expand();tg.ready();
const user=tg.initDataUnsafe?.user||{};
const uname=user.first_name||'Player';
const uid=user.id||123456789;

// Переменные состояния
let ton=0,stars=0,gifts=[],withdrawn=[],depTon=0,depStars=0,currentCase=null,isSpinning=false,demoModeInner=false,lang='ru',refCount=0,freeAvail=0;

// Аватарки
const avatarSm=document.getElementById('avatarSm');
const profileAvatar=document.getElementById('profileAvatar');
document.getElementById('profileName').textContent=uname;

if(user.photo_url){
    avatarSm.style.backgroundImage=`url(${user.photo_url})`;
    avatarSm.textContent='';
    profileAvatar.style.backgroundImage=`url(${user.photo_url})`;
    profileAvatar.textContent='';
}else{
    avatarSm.textContent=uname[0].toUpperCase();
    profileAvatar.textContent=uname[0].toUpperCase();
}

// Клик по аватарке -> профиль
avatarSm.addEventListener('click',()=>navigate('profile'));

// Переводы
const TR={ru:{mainTitle:'🎁 Кейсы',depositTon:'💎 Пополнить TON',depositStars:'⭐ Пополнить Stars',demoLabel:'Демо-режим',itemsTitle:'Возможные призы',spin:'🎰 НАЧАТЬ КРУТИТЬ',spinDemo:'🆓 КРУТИТЬ ДЕМО',spinFree:'🎁 БЕСПЛАТНО',topUp:'💰 ПОПОЛНИТЕ БАЛАНС',noWins:'Нет выигрышей',sell:'💰 Продать',withdraw:'📤 Вывести',withdrawn:'✅ Выведено',history:'📤 История выводов',depTonL:'📥 Пополнено TON:',depStarsL:'📥 Пополнено Stars:',giftsL:'🎁 Подарков:',wins:'Выигрыши',profile:'Профиль',lang:'Язык',info:'📋 Инфо',faq:'❓ FAQ',chooseLang:'Выберите язык',spinning:'Крутим...',demSpinning:'Демо-режим...',liveTitle:'LIVE Дропы',freeLocked:'🔒 Пригласите 3 друзей',close:'Закрыть',cases:'Кейсы',starsProcessing:'Создаём счёт...',starsSuccess:'✅ Счёт отправлен!',starsError:'❌ Ошибка',payTitleTon:'Пополнение TON',payTitleStars:'Пополнение Stars',sendTon:'Отправьте TON с кодом:',toWallet:'На кошелёк:',minTon:'⚠️ Мин: 1 TON | Без кода не зачислится!',starsInvoiceDesc:'Выберите сумму. Счёт придёт в чат с ботом. Звёзды спишутся реально!'},en:{mainTitle:'🎁 Cases',depositTon:'💎 Deposit TON',depositStars:'⭐ Deposit Stars',demoLabel:'Demo Mode',itemsTitle:'Possible Prizes',spin:'🎰 START SPIN',spinDemo:'🆓 SPIN DEMO',spinFree:'🎁 FREE',topUp:'💰 TOP UP',noWins:'No wins',sell:'💰 Sell',withdraw:'📤 Withdraw',withdrawn:'✅ Withdrawn',history:'📤 History',depTonL:'📥 Deposited TON:',depStarsL:'📥 Deposited Stars:',giftsL:'🎁 Gifts:',wins:'Wins',profile:'Profile',lang:'Language',info:'📋 Info',faq:'❓ FAQ',chooseLang:'Choose Language',spinning:'Spinning...',demSpinning:'Demo Mode...',liveTitle:'LIVE Drops',freeLocked:'🔒 Invite 3 friends',close:'Close',cases:'Cases',starsProcessing:'Creating invoice...',starsSuccess:'✅ Invoice sent!',starsError:'❌ Error',payTitleTon:'Deposit TON',payTitleStars:'Deposit Stars',sendTon:'Send TON with code:',toWallet:'To wallet:',minTon:'⚠️ Min: 1 TON | No code = no credit!',starsInvoiceDesc:'Choose amount. Invoice will arrive in bot chat. Stars will be charged!'}};
function t(key){return TR[lang]?.[key]||TR['ru'][key]||key}

async function loadUser(){try{const r=await fetch('/api/user/'+uid);const d=await r.json();ton=d.balance_ton||0;stars=d.balance_stars||0;gifts=d.gift_items||[];withdrawn=d.withdrawn_items||[];depTon=d.deposited_ton||0;depStars=d.deposited_stars||0;lang=d.language||'ru';refCount=d.referral_count||0;freeAvail=d.free_case_available||0;updateUI()}catch(e){updateUI()}}

function updateUI(){
    document.getElementById('tonChip').textContent='💎 '+ton.toFixed(2)+' TON';
    document.getElementById('starsChip').textContent='⭐ '+stars+' Stars';
    document.getElementById('pTon').textContent=ton.toFixed(2);document.getElementById('pStars').textContent=stars;
    document.getElementById('pDepTon').textContent=depTon.toFixed(2)+' TON';document.getElementById('pDepStars').textContent=depStars+' Stars';
    document.getElementById('pGifts').textContent=gifts.length;document.getElementById('pRef').textContent=refCount+'/3';
    document.getElementById('depositRow').style.display=demoModeInner?'none':'flex';
    applyAllTranslations();renderWins();loadCases();loadLiveDrops();
}

function applyAllTranslations(){
    document.getElementById('mainTitle').textContent=t('mainTitle');
    document.getElementById('btnDepTon').textContent=t('depositTon');document.getElementById('btnDepStars').textContent=t('depositStars');
    document.getElementById('demoLabel').textContent=t('demoLabel');document.getElementById('itemsTitle').textContent=t('itemsTitle');
    document.getElementById('langTitle').textContent=t('chooseLang');
    document.getElementById('liveTitle').textContent=t('liveTitle');
    document.getElementById('tabInfo').textContent=t('info');document.getElementById('tabWins').textContent=t('wins');
    document.getElementById('tabFaq').textContent=t('faq');document.getElementById('tabLang').textContent=t('lang');
    document.getElementById('navLabelCases').textContent=t('cases');document.getElementById('navLabelWins').textContent=t('wins');
    document.getElementById('navLabelLang').textContent=t('lang');document.getElementById('navLabelProfile').textContent=t('profile');
}

async function setLang(l){lang=l;try{await fetch('/api/language',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:uid,language:l})})}catch(e){}updateUI()}

function toggleDemoInner(){demoModeInner=!demoModeInner;const sw=document.getElementById('demoSwitchInner');demoModeInner?sw.classList.add('active'):sw.classList.remove('active');updateUI();if(currentCase)updateCaseDetailButtons()}
function updateCaseDetailButtons(){if(!currentCase)return;const isFree=currentCase.id==='free';const can=isFree||demoModeInner||checkBalance();const btn=document.getElementById('detailSpinBtn');btn.className='spin-btn '+(can?'active':'disabled')+(demoModeInner?' demo-btn':(isFree?' free-btn':''));btn.textContent=isFree?t('spinFree'):(demoModeInner?t('spinDemo'):(can?t('spin'):t('topUp')));document.getElementById('detailPrice').textContent=isFree?'🎁 Бесплатно':(demoModeInner?'🆓 '+t('demoLabel'):(currentCase.price_ton?currentCase.price_ton+' TON':(currentCase.price_stars?currentCase.price_stars+' Stars':'Бесплатно')))
    document.getElementById('demoToggleRow').style.display=isFree?'none':'flex';
}

async function loadLiveDrops(){try{const r=await fetch('/api/live_drops');const drops=await r.json();const scroll=document.getElementById('liveDropsScroll');if(drops.length===0){scroll.innerHTML='<div class="live-drop-item"><span style="color:var(--sub)">Пока нет дропов</span></div>'}else{scroll.innerHTML=drops.map(d=>`<div class="live-drop-item"><span class="live-drop-icon">${d.item_icon}</span><span class="live-drop-name">${d.item_name}</span><span class="live-drop-case">из ${d.case_name}</span></div>`).join('')}}catch(e){}}

async function loadCases(){try{const r=await fetch('/api/cases?lang='+lang);const cases=await r.json();document.getElementById('casesGrid').innerHTML=cases.map(c=>{const isFree=c.id==='free';let price=c.price_ton?c.price_ton+' TON':(c.price_stars?c.price_stars+' Stars':'Бесплатно');let cardClass='';if(isFree){if(freeAvail>0){price='🎁 Доступен!';cardClass=' free-case'}else if(refCount<3){price=t('freeLocked');cardClass=' free-case locked'}else{price='🎁 Доступен!';cardClass=' free-case'}}const feat=c.id==='ton'?' featured':'';return `<div class="case-card${feat}${cardClass}" style="border-color:${c.color}" onclick="openCaseDetail('${c.id}')"><div class="case-icon">${c.icon}</div><div class="case-name">${c.name}</div><div class="case-price" style="color:${c.color}">${price}</div></div>`}).join('')}catch(e){}}

function openCaseDetail(caseId){
    fetch('/api/cases?lang='+lang).then(r=>r.json()).then(cases=>{
        currentCase=cases.find(c=>c.id===caseId);if(!currentCase)return;
        document.getElementById('detailIcon').textContent=currentCase.icon;
        document.getElementById('detailName').textContent=currentCase.name;
        document.getElementById('caseTopTitle').textContent=currentCase.name;
        document.getElementById('detailItems').innerHTML=currentCase.items.map(item=>`<div class="item-mini"><div class="item-mini-icon">${item.icon}</div><div><div class="item-mini-name">${item.name}</div><div class="item-mini-chance">${item.chance}%</div></div></div>`).join('');
        demoModeInner=false;document.getElementById('demoSwitchInner').classList.remove('active');
        updateUI();updateCaseDetailButtons();
        showPage('case-detail');document.getElementById('topbarMain').style.display='none';document.getElementById('topbarCase').style.display='flex';
    });
}

function openDeposit(type){
    const content=document.getElementById('payContent');
    document.getElementById('payIcon').textContent=type==='TON'?'💎':'⭐';
    document.getElementById('payTitle').textContent=type==='TON'?t('payTitleTon'):t('payTitleStars');
    if(type==='TON'){
        const code=Math.random().toString(36).substring(2,18).toUpperCase();
        content.innerHTML=`<div style="font-size:13px;color:var(--sub);margin-bottom:8px">${t('sendTon')}</div><div class="payment-code">${code}</div><div style="font-size:13px;color:var(--sub);margin-bottom:4px">${t('toWallet')}</div><div class="payment-wallet">UQDRRRGutl_ccP25XcwbOK-RN2UXuvE1_GFoerlaIDvmwO7I</div><div style="font-size:11px;color:var(--accent);margin-bottom:12px">${t('minTon')}</div>`;
    } else {
        content.innerHTML=`<div style="font-size:13px;color:var(--sub);margin-bottom:12px">${t('starsInvoiceDesc')}</div>
            <div class="stars-amount-grid">
                <button class="stars-amount-btn" onclick="createStarsInvoice(50)">⭐ 50 Stars</button>
                <button class="stars-amount-btn" onclick="createStarsInvoice(100)">⭐ 100 Stars</button>
                <button class="stars-amount-btn" onclick="createStarsInvoice(250)">⭐ 250 Stars</button>
                <button class="stars-amount-btn" onclick="createStarsInvoice(500)">⭐ 500 Stars</button>
            </div>
            <div id="starsStatus" style="font-size:12px;color:var(--accent);margin-top:8px"></div>`;
    }
    document.getElementById('paymentModal').classList.add('active');
}

async function createStarsInvoice(amount){
    const statusEl=document.getElementById('starsStatus');
    statusEl.textContent=t('starsProcessing');
    try{
        const r=await fetch('/api/create_stars_invoice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:uid,amount:amount})});
        const d=await r.json();
        if(d.success){statusEl.textContent=t('starsSuccess');statusEl.style.color='#10B981';setTimeout(()=>{tg.openTelegramLink('https://t.me/nft_takes_gifts_bot');closePayment()},1500)}
        else{statusEl.textContent=t('starsError')+': '+d.error;statusEl.style.color='#ef4444'}
    }catch(e){statusEl.textContent=t('starsError');statusEl.style.color='#ef4444'}
}

function closePayment(){document.getElementById('paymentModal').classList.remove('active')}
function checkBalance(){if(!currentCase)return false;if(currentCase.id==='free')return freeAvail>0;if(currentCase.price_ton&&ton>=currentCase.price_ton)return true;if(currentCase.price_stars&&stars>=currentCase.price_stars)return true;return false}

async function startSpin(){
    if(!currentCase||isSpinning)return;
    const isFree=currentCase.id==='free';
    if(!isFree&&!demoModeInner&&!checkBalance()){alert(t('topUp'));return}
    if(isFree&&freeAvail<=0){alert('Бесплатный кейс недоступен! Пригласите 3 друзей.');return}
    
    const currency=currentCase.price_ton?'TON':'STARS';
    const r=await fetch('/api/open_case',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:uid,case_id:currentCase.id,currency,demo_mode:demoModeInner})});
    const d=await r.json();if(d.error){alert(d.error);return}
    ton=d.balance_ton;stars=d.balance_stars;
    if(isFree){freeAvail=d.free_case_available;refCount=0}
    const winner=d.winner;
    const trackItems=[];for(let i=0;i<40;i++)trackItems.push(...currentCase.items);
    const wis=[];trackItems.forEach((item,i)=>{if(item.icon===winner.icon&&item.name===winner.name)wis.push(i)});
    const rs=Math.floor(trackItems.length*0.55),re=Math.floor(trackItems.length*0.75);
    const valid=wis.filter(i=>i>=rs&&i<=re);const ci=valid.length>0?valid[Math.floor(Math.random()*valid.length)]:wis[Math.floor(wis.length/2)];
    const track=document.getElementById('rouletteTrack');track.innerHTML=trackItems.map((item,i)=>`<div class="roulette-item" id="ri${i}">${item.icon}</div>`).join('');
    const IW=88,ww=document.getElementById('rouletteWindow').offsetWidth,tp=-(ci*IW)+(ww/2)-(IW/2);
    track.style.transition='none';track.style.transform='translateX(0)';
    document.getElementById('spinAnim').classList.add('active');
    document.getElementById('spinText').textContent=isFree?'Бесплатный кейс...':(demoModeInner?t('demSpinning'):t('spinning'));
    document.getElementById('spinText').classList.remove('win');isSpinning=true;
    requestAnimationFrame(()=>{requestAnimationFrame(()=>{track.style.transition='transform 6s cubic-bezier(0.05,0.95,0.1,1)';track.style.transform=`translateX(${tp}px)`})});
    setTimeout(()=>{document.querySelectorAll('.roulette-item').forEach(el=>el.classList.remove('highlight'));const wel=document.getElementById('ri'+ci);if(wel)wel.classList.add('highlight');document.getElementById('spinText').textContent=(isFree?'[БЕСПЛАТНО] ':(demoModeInner?'[DEMO] ':''))+'🎉 '+winner.name+'!';document.getElementById('spinText').classList.add('win')},5500);
    setTimeout(()=>{document.getElementById('spinAnim').classList.remove('active');isSpinning=false;if(!isFree&&!demoModeInner){gifts.push({name:winner.name,icon:winner.icon,value_stars:winner.value_stars||0,value_ton:winner.value_ton||0})}document.getElementById('toastIcon').textContent=winner.icon;document.getElementById('toastName').textContent=(isFree?'[БЕСПЛАТНО] ':(demoModeInner?'[DEMO] ':''))+winner.name;document.getElementById('resultToast').style.display='flex';setTimeout(()=>document.getElementById('resultToast').style.display='none',3000);updateUI();goBack()},6300);
}

function goBack(){showPage('cases');document.getElementById('topbarMain').style.display='flex';document.getElementById('topbarCase').style.display='none';currentCase=null;demoModeInner=false;document.getElementById('demoSwitchInner').classList.remove('active');updateUI()}
function renderWins(){const active=gifts.map((g,i)=>`<div class="gift-item-card"><div class="gift-item-icon">${g.icon}</div><div class="gift-item-info"><div class="gift-item-name">${g.name}</div><div class="gift-item-value">${g.value_stars?g.value_stars+' Stars':''} ${g.value_ton?g.value_ton+' TON':''}</div></div><div class="gift-item-actions"><button class="btn-sm btn-sell" onclick="sellItem(${i})">${t('sell')}</button><button class="btn-sm btn-withdraw" onclick="withdrawItem(${i})">${t('withdraw')}</button></div></div>`).join('');const done=withdrawn.map(g=>`<div class="gift-item-card"><div class="gift-item-icon">${g.icon}</div><div class="gift-item-info"><div class="gift-item-name">${g.name}</div><div class="gift-item-status">${t('withdrawn')} • ${(g.wallet||'').slice(0,8)}...</div></div></div>`).join('');const html=(active||'')+(done?('<div style="font-weight:600;font-size:13px;color:var(--sub);margin:12px 0 8px">'+t('history')+'</div>'+done):'')||('<div style="text-align:center;padding:20px;color:#888">'+t('noWins')+'</div>');document.getElementById('winsList').innerHTML=html;document.getElementById('profileWinsList').innerHTML=html}
async function sellItem(i){const r=await fetch('/api/sell_item',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:uid,item_index:i})});const d=await r.json();if(d.success){ton=d.balance_ton;stars=d.balance_stars;gifts=gifts.filter((_,idx)=>idx!==i);updateUI()}}
async function withdrawItem(i){const w=prompt('TON wallet:');if(!w)return;const r=await fetch('/api/withdraw_item',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:uid,item_index:i,wallet:w})});const d=await r.json();if(d.success){gifts=gifts.filter((_,idx)=>idx!==i);withdrawn.push(d.item);updateUI();alert(d.message)}}
function showPage(p){document.querySelectorAll('.page').forEach(pg=>pg.classList.remove('active'));const el=document.getElementById('page-'+p);if(el)el.classList.add('active')}
function navigate(p){if(isSpinning)return;showPage(p);document.getElementById('topbarMain').style.display='flex';document.getElementById('topbarCase').style.display='none';currentCase=null;demoModeInner=false;document.getElementById('demoSwitchInner').classList.remove('active');updateUI();document.querySelectorAll('.nav-btn').forEach(b=>b.classList.remove('active'));const navMap={cases:'navCases',wins:'navWins',faq:'navFaq',lang:'navLang',profile:'navProfile'};const an=document.getElementById(navMap[p]);if(an)an.classList.add('active');document.getElementById('mainTitle').textContent=t(p==='cases'?'mainTitle':p==='wins'?'wins':p==='faq'?'faq':p==='lang'?'chooseLang':'profile')}
function profileTab(t){document.querySelectorAll('#page-profile .tab-btn').forEach(b=>b.classList.remove('active'));document.querySelectorAll('#page-profile .tab-content').forEach(c=>c.classList.remove('active'));event.target.classList.add('active');const el=document.getElementById('ptab-'+t);if(el)el.classList.add('active')}

setInterval(loadLiveDrops,5000);
loadUser();
</script>
</body>
</html>'''

# =================================================================
# ЗАПУСК
# =================================================================
def keep_alive():
    while True:
        time.sleep(540)
        try: requests.get(f"https://{RENDER_URL}/health", timeout=5)
        except: pass

if __name__ == '__main__':
    init_db()
    try:
        requests.get(f"{TELEGRAM_API}/setWebhook", params={"url": f"https://{RENDER_URL}/webhook", "drop_pending_updates": True})
        requests.post(f"{TELEGRAM_API}/setChatMenuButton", json={"menu_button": json.dumps({"type":"web_app","text":"🎁 КЕЙСЫ","web_app":{"url":WEBAPP_URL}})})
        logger.info("✅ Webhook set!")
    except Exception as e: logger.error(f"Setup: {e}")
    
    threading.Thread(target=keep_alive, daemon=True).start()
    port = int(os.environ.get('PORT', 8080))
    flask_app.run(host='0.0.0.0', port=port)
