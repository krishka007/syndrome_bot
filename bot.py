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
WEBAPP_URL = "https://syndrome-bot-13.onrender.com"
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
                balance_ton REAL DEFAULT 100.0,
                balance_stars INTEGER DEFAULT 1000,
                total_wins INTEGER DEFAULT 0,
                total_games INTEGER DEFAULT 0,
                total_deposited_ton REAL DEFAULT 0,
                nft_items TEXT DEFAULT '[]',
                gift_items TEXT DEFAULT '[]',
                last_free_case TIMESTAMP,
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
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                wallet TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
    logger.info("DB ready")

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
# TELEGRAM API HELPERS
# =================================================================
def tg_request(method, data=None):
    try:
        r = requests.post(f"{TELEGRAM_API}/{method}", json=data or {}, timeout=10)
        return r.json()
    except: return None

def tg_send(chat_id, text, keyboard=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if keyboard: data["reply_markup"] = json.dumps(keyboard)
    return tg_request("sendMessage", data)

def tg_edit(chat_id, msg_id, text, keyboard=None):
    data = {"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": "HTML"}
    if keyboard: data["reply_markup"] = json.dumps(keyboard)
    return tg_request("editMessageText", data)

def tg_answer(cb_id, text=""):
    return tg_request("answerCallbackQuery", {"callback_query_id": cb_id, "text": text})

def generate_payment_id(user_id):
    return hashlib.sha256(f"{user_id}{time.time()}{random.randint(0,9999)}".encode()).hexdigest()[:16].upper()

# =================================================================
# GIFT CASE DATA (Telegram Gift Style)
# =================================================================
GIFT_CASES = {
    "common": {
        "name": "Обычный кейс",
        "icon": "📦",
        "price_ton": 1,
        "price_stars": 10,
        "color": "#9CA3AF",
        "items": [
            {"name": "❤️ Сердечко", "icon": "❤️", "rarity": "common", "chance": 30, "value": 0.5},
            {"name": "🌹 Роза", "icon": "🌹", "rarity": "common", "chance": 25, "value": 0.8},
            {"name": "🎈 Шарик", "icon": "🎈", "rarity": "common", "chance": 20, "value": 0.3},
            {"name": "🍀 Клевер", "icon": "🍀", "rarity": "common", "chance": 15, "value": 0.6},
            {"name": "💍 Кольцо", "icon": "💍", "rarity": "rare", "chance": 7, "value": 3.0},
            {"name": "💎 Кристалл", "icon": "💎", "rarity": "rare", "chance": 3, "value": 5.0},
        ]
    },
    "rare": {
        "name": "Редкий кейс",
        "icon": "🎁",
        "price_ton": 5,
        "price_stars": 50,
        "color": "#60A5FA",
        "items": [
            {"name": "💎 Кристалл", "icon": "💎", "rarity": "rare", "chance": 30, "value": 5.0},
            {"name": "👑 Корона", "icon": "👑", "rarity": "rare", "chance": 25, "value": 8.0},
            {"name": "💍 Кольцо", "icon": "💍", "rarity": "rare", "chance": 20, "value": 6.0},
            {"name": "🌟 Звезда", "icon": "🌟", "rarity": "epic", "chance": 15, "value": 20.0},
            {"name": "🔮 Шар", "icon": "🔮", "rarity": "epic", "chance": 8, "value": 30.0},
            {"name": "🐉 Дракон", "icon": "🐉", "rarity": "legendary", "chance": 2, "value": 100.0},
        ]
    },
    "epic": {
        "name": "Эпический кейс",
        "icon": "✨",
        "price_ton": 15,
        "price_stars": 150,
        "color": "#A78BFA",
        "items": [
            {"name": "🌟 Звезда", "icon": "🌟", "rarity": "epic", "chance": 30, "value": 20.0},
            {"name": "🔮 Шар", "icon": "🔮", "rarity": "epic", "chance": 25, "value": 30.0},
            {"name": "🐉 Дракон", "icon": "🐉", "rarity": "legendary", "chance": 20, "value": 100.0},
            {"name": "🦄 Единорог", "icon": "🦄", "rarity": "legendary", "chance": 15, "value": 150.0},
            {"name": "🏆 Кубок", "icon": "🏆", "rarity": "mythic", "chance": 7, "value": 500.0},
            {"name": "👼 Ангел", "icon": "👼", "rarity": "mythic", "chance": 3, "value": 1000.0},
        ]
    },
    "legendary": {
        "name": "Легендарный кейс",
        "icon": "👑",
        "price_ton": 50,
        "price_stars": 500,
        "color": "#FBBF24",
        "items": [
            {"name": "🐉 Дракон", "icon": "🐉", "rarity": "legendary", "chance": 30, "value": 100.0},
            {"name": "🦄 Единорог", "icon": "🦄", "rarity": "legendary", "chance": 25, "value": 150.0},
            {"name": "🏆 Кубок", "icon": "🏆", "rarity": "mythic", "chance": 20, "value": 500.0},
            {"name": "👼 Ангел", "icon": "👼", "rarity": "mythic", "chance": 15, "value": 1000.0},
            {"name": "🌌 Галактика", "icon": "🌌", "rarity": "mythic", "chance": 7, "value": 5000.0},
            {"name": "⚡ Молния", "icon": "⚡", "rarity": "mythic", "chance": 3, "value": 10000.0},
        ]
    }
}

# =================================================================
# BOT HANDLERS
# =================================================================
def handle_start(chat_id, user):
    uid = user["id"]
    uname = user.get("username", f"user_{uid}")
    fname = user.get("first_name", "Player")
    with db_connect() as conn:
        conn.execute('INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?,?,?)', (uid, uname, fname))
    
    keyboard = {"inline_keyboard": [
        [{"text": "🎁 ОТКРЫВАТЬ КЕЙСЫ", "web_app": {"url": WEBAPP_URL}}],
        [{"text": "💎 ПОПОЛНИТЬ TON", "callback_data": "dep_ton"}],
        [{"text": "💼 ПРОФИЛЬ", "callback_data": "profile"}]
    ]}
    
    tg_send(chat_id, 
        "🎁 <b>GIFT CASES — КЕЙСЫ ПОДАРКОВ</b> 🎁\n\n"
        "📦 Обычный • 🎁 Редкий\n"
        "✨ Эпический • 👑 Легендарный\n\n"
        "💎 Цены от 1 TON / 10 Stars\n"
        "🎉 Шанс выбить МИФИЧЕСКИЙ подарок!\n\n"
        "<b>👇 НАЖМИ НА КНОПКУ!</b>",
        keyboard
    )

def handle_dep_ton(cb, chat_id, msg_id, uid):
    tg_answer(cb["id"])
    pid = generate_payment_id(uid)
    with db_connect() as conn:
        conn.execute('UPDATE users SET pending_payment_id=? WHERE user_id=?', (pid, uid))
    
    keyboard = {"inline_keyboard": [
        [{"text": "✅ ПРОВЕРИТЬ", "callback_data": f"check_{pid}"}],
        [{"text": "🔄 НОВЫЙ КОД", "callback_data": "dep_ton"}],
        [{"text": "🏠 МЕНЮ", "callback_data": "menu"}]
    ]}
    
    tg_edit(chat_id, msg_id,
        f"💎 <b>ПОПОЛНЕНИЕ TON</b>\n\n"
        f"📤 Кошелёк:\n<code>{TON_WALLET}</code>\n\n"
        f"📝 Код:\n<code>{pid}</code>\n\n"
        f"⚠️ Мин: <b>1 TON</b>\n"
        f"⚠️ Укажите код в комментарии!",
        keyboard
    )

def handle_check(cb, chat_id, msg_id, uid, pid):
    tg_answer(cb["id"], "🔍 Проверяю блокчейн...")
    result = verify_ton_transaction(TON_WALLET, pid)
    
    if result:
        amt = result['amount']
        with db_connect() as conn:
            conn.execute('UPDATE users SET balance_ton=balance_ton+?, total_deposited_ton=total_deposited_ton+?, pending_payment_id=NULL WHERE user_id=?', (amt, amt, uid))
        
        keyboard = {"inline_keyboard": [[{"text": "🎁 ОТКРЫВАТЬ КЕЙСЫ", "web_app": {"url": WEBAPP_URL}}]]}
        tg_edit(chat_id, msg_id, f"✅ <b>ЗАЧИСЛЕНО!</b>\n\n💰 +{amt:.4f} TON\n\n🎁 Открывайте кейсы!", keyboard)
        tg_send(ADMIN_ID, f"💰 +{amt:.4f} TON от {uid}")
    else:
        keyboard = {"inline_keyboard": [
            [{"text": "🔄 ПРОВЕРИТЬ СНОВА", "callback_data": f"check_{pid}"}],
            [{"text": "💎 НОВЫЙ КОД", "callback_data": "dep_ton"}]
        ]}
        tg_edit(chat_id, msg_id, "❌ <b>ПЛАТЕЖ НЕ НАЙДЕН</b>\n\n• Проверьте код\n• Транзакция идёт до 5 мин", keyboard)

def handle_profile(cb, chat_id, msg_id, uid, fname):
    tg_answer(cb["id"])
    with db_connect() as conn:
        row = conn.execute('SELECT balance_ton, balance_stars, total_wins, total_games FROM users WHERE user_id=?', (uid,)).fetchone()
    if row:
        ton, stars, wins, games = row
        wr = round((wins/games)*100) if games > 0 else 0
        keyboard = {"inline_keyboard": [
            [{"text": "🎁 ОТКРЫВАТЬ КЕЙСЫ", "web_app": {"url": WEBAPP_URL}}],
            [{"text": "💎 ВЫВЕСТИ", "callback_data": "wd_ton"}],
            [{"text": "🏠 МЕНЮ", "callback_data": "menu"}]
        ]}
        tg_edit(chat_id, msg_id,
            f"💼 <b>{fname}</b>\n\n"
            f"💎 TON: <b>{ton:.4f}</b>\n"
            f"⭐ Stars: <b>{stars}</b>\n"
            f"🏆 Побед: <b>{wins}</b> | 🎮 Игр: <b>{games}</b>\n"
            f"📈 Win Rate: <b>{wr}%</b>",
            keyboard
        )

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
            row = conn.execute('SELECT balance_ton, balance_stars, total_wins, total_games, gift_items, nft_items FROM users WHERE user_id=?', (uid,)).fetchone()
        if row:
            return jsonify({
                'balance_ton': row[0], 'balance_stars': row[1],
                'total_wins': row[2], 'total_games': row[3],
                'gift_items': json.loads(row[4]) if row[4] else [],
                'nft_items': json.loads(row[5]) if row[5] else []
            })
    except: pass
    return jsonify({'balance_ton': 100, 'balance_stars': 1000, 'total_wins': 0, 'total_games': 0, 'gift_items': [], 'nft_items': []})

@flask_app.route('/api/cases')
def api_cases():
    """Возвращает все кейсы"""
    cases_list = []
    for key, case in GIFT_CASES.items():
        cases_list.append({
            'id': key,
            'name': case['name'],
            'icon': case['icon'],
            'price_ton': case['price_ton'],
            'price_stars': case['price_stars'],
            'color': case['color'],
            'items': case['items']
        })
    return jsonify(cases_list)

@flask_app.route('/api/open_case', methods=['POST'])
def api_open_case():
    """Открытие кейса"""
    data = request.json
    uid = data.get('user_id')
    case_id = data.get('case_id')
    currency = data.get('currency', 'TON')
    
    if case_id not in GIFT_CASES:
        return jsonify({'error': 'Кейс не найден!'}), 404
    
    case = GIFT_CASES[case_id]
    price = case['price_ton'] if currency == 'TON' else case['price_stars']
    
    with db_connect() as conn:
        col = 'balance_ton' if currency == 'TON' else 'balance_stars'
        row = conn.execute(f'SELECT {col} FROM users WHERE user_id=?', (uid,)).fetchone()
        
        if not row or row[0] < price:
            return jsonify({'error': f'Недостаточно {currency}!'}), 400
        
        # Выбор предмета по шансам
        items_pool = []
        for item in case['items']:
            items_pool.extend([item] * int(item['chance'] * 10))
        
        winner = random.choice(items_pool)
        
        # Списываем цену
        conn.execute(f'UPDATE users SET {col}={col}-?, total_games=total_games+1 WHERE user_id=?', (price, uid))
        
        # Добавляем подарок
        row2 = conn.execute('SELECT gift_items FROM users WHERE user_id=?', (uid,)).fetchone()
        gifts = json.loads(row2[0]) if row2 and row2[0] else []
        gifts.append({'name': winner['name'], 'icon': winner['icon'], 'rarity': winner['rarity'], 'value': winner['value']})
        conn.execute('UPDATE users SET gift_items=?, total_wins=total_wins+1 WHERE user_id=?', (json.dumps(gifts), uid))
    
    return jsonify({'winner': winner, 'case_name': case['name']})

@flask_app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = request.get_json()
        
        if "message" in update:
            msg = update["message"]
            chat_id = msg["chat"]["id"]
            user = msg["from"]
            uid = user["id"]
            
            if "text" in msg:
                text = msg["text"]
                if text.startswith("/start"):
                    handle_start(chat_id, user)
                elif text.startswith("/withdraw"):
                    try:
                        parts = text.split()
                        amt = float(parts[1])
                        wallet = parts[2] if len(parts) > 2 else None
                        if not wallet:
                            tg_send(chat_id, "❌ /withdraw СУММА КОШЕЛЕК")
                        elif amt < 10:
                            tg_send(chat_id, "❌ Мин: 10 TON")
                        else:
                            with db_connect() as conn:
                                row = conn.execute('SELECT balance_ton FROM users WHERE user_id=?', (uid,)).fetchone()
                                if not row or row[0] < amt:
                                    tg_send(chat_id, "❌ Недостаточно!")
                                else:
                                    conn.execute('UPDATE users SET balance_ton=balance_ton-? WHERE user_id=?', (amt, uid))
                                    conn.execute('INSERT INTO withdrawals (user_id, amount, wallet) VALUES (?,?,?)', (uid, amt, wallet))
                                    tg_send(chat_id, f"✅ Заявка на <b>{amt} TON</b> создана!")
                                    tg_send(ADMIN_ID, f"📤 ВЫВОД: {amt} TON\n👤 {uid}\n📤 {wallet}")
                    except:
                        tg_send(chat_id, "❌ /withdraw СУММА КОШЕЛЕК")
        
        elif "callback_query" in update:
            cb = update["callback_query"]
            chat_id = cb["message"]["chat"]["id"]
            msg_id = cb["message"]["message_id"]
            uid = cb["from"]["id"]
            fname = cb["from"].get("first_name", "Player")
            data = cb.get("data", "")
            
            if data == "dep_ton":
                handle_dep_ton(cb, chat_id, msg_id, uid)
            elif data == "profile":
                handle_profile(cb, chat_id, msg_id, uid, fname)
            elif data == "menu":
                tg_edit(chat_id, msg_id, "🎁 <b>GIFT CASES</b>", {"inline_keyboard": [[{"text": "🎁 ОТКРЫВАТЬ КЕЙСЫ", "web_app": {"url": WEBAPP_URL}}]]})
                tg_answer(cb["id"])
            elif data == "wd_ton":
                tg_edit(chat_id, msg_id, "💎 Отправьте:\n<code>/withdraw СУММА КОШЕЛЕК</code>")
                tg_answer(cb["id"])
            elif data.startswith("check_"):
                handle_check(cb, chat_id, msg_id, uid, data.replace("check_", ""))
            else:
                tg_answer(cb["id"])
        
        return "ok", 200
    except Exception as e:
        logger.error(f"Webhook: {e}")
        return "error", 500

@flask_app.route('/health')
def health():
    return jsonify({"status": "ok"})

# =================================================================
# HTML — КЕЙСЫ В СТИЛЕ TELEGRAM GIFTS
# =================================================================
HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="theme-color" content="#0f0f1a">
    <title>GIFT CASES</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
        
        :root {
            --bg: #0f0f1a;
            --card: #1a1a2e;
            --gold: #ffd700;
            --accent: #7c3aed;
            --text: #fff;
            --sub: #9ca3af;
        }
        
        *{margin:0;padding:0;box-sizing:border-box}
        body{background:var(--bg);color:var(--text);font-family:'Inter',sans-serif;min-height:100vh;overflow-x:hidden}
        
        .app{max-width:440px;margin:0 auto;padding:12px;padding-bottom:40px}
        
        /* Баланс */
        .bal{display:flex;align-items:center;gap:8px;padding:12px 16px;background:var(--card);border-radius:16px;margin-bottom:12px}
        .bal-icon{font-size:20px}
        .bal-text{font-weight:700;font-size:15px}
        .bal-ton{background:linear-gradient(135deg,var(--gold),#ffaa00);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
        .bal-stars{color:#60a5fa;margin-left:12px}
        
        /* Кейсы */
        .cases-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:16px}
        
        .case-card{position:relative;padding:20px 14px;border-radius:20px;text-align:center;cursor:pointer;transition:all 0.3s;overflow:hidden;border:2px solid transparent}
        .case-card:hover{transform:translateY(-4px)}
        .case-card:active{transform:scale(0.97)}
        
        .case-card.common{border-color:#9CA3AF;background:linear-gradient(180deg,rgba(156,163,175,0.15),rgba(156,163,175,0.05))}
        .case-card.rare{border-color:#60A5FA;background:linear-gradient(180deg,rgba(96,165,250,0.15),rgba(96,165,250,0.05))}
        .case-card.epic{border-color:#A78BFA;background:linear-gradient(180deg,rgba(167,139,250,0.15),rgba(167,139,250,0.05))}
        .case-card.legendary{border-color:#FBBF24;background:linear-gradient(180deg,rgba(251,191,36,0.15),rgba(251,191,36,0.05))}
        
        .case-glow{position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none}
        .case-card.epic .case-glow{background:radial-gradient(circle at 50% 0%,rgba(167,139,250,0.3),transparent 60%)}
        .case-card.legendary .case-glow{background:radial-gradient(circle at 50% 0%,rgba(251,191,36,0.3),transparent 60%)}
        
        .case-icon{font-size:48px;margin-bottom:8px;position:relative;z-index:1}
        .case-name{font-weight:700;font-size:14px;margin-bottom:4px;position:relative;z-index:1}
        .case-price{font-size:12px;color:var(--gold);font-weight:600;position:relative;z-index:1}
        .case-count{font-size:10px;color:var(--sub);margin-top:2px;position:relative;z-index:1}
        
        /* Модалка открытия */
        .modal{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.9);z-index:100;align-items:center;justify-content:center;backdrop-filter:blur(10px)}
        .modal.active{display:flex}
        
        .modal-card{width:90%;max-width:360px;padding:30px;background:var(--card);border-radius:24px;text-align:center;position:relative;animation:popIn 0.4s ease}
        @keyframes popIn{0%{transform:scale(0.8);opacity:0}100%{transform:scale(1);opacity:1}}
        
        .modal-close{position:absolute;top:12px;right:12px;width:32px;height:32px;border-radius:50%;background:rgba(255,255,255,0.1);border:none;color:#fff;font-size:16px;cursor:pointer}
        
        .win-icon{font-size:80px;animation:winBounce 0.6s ease}
        @keyframes winBounce{0%{transform:scale(0)}50%{transform:scale(1.2)}100%{transform:scale(1)}}
        
        .win-name{font-size:22px;font-weight:800;margin:12px 0 4px}
        .win-rarity{font-size:13px;font-weight:700;text-transform:uppercase;margin-bottom:6px}
        .win-value{font-size:14px;color:var(--gold);font-weight:600;margin-bottom:20px}
        
        .collect-btn{display:inline-block;padding:14px 32px;border-radius:14px;background:linear-gradient(135deg,var(--accent),#a855f7);color:#fff;font-weight:700;cursor:pointer;border:none;font-size:15px;transition:all 0.3s}
        .collect-btn:hover{transform:translateY(-2px)}
        
        /* Анимация открытия кейса */
        .opening-anim{position:fixed;top:0;left:0;width:100%;height:100%;z-index:200;display:none;align-items:center;justify-content:center;background:rgba(0,0,0,0.95)}
        .opening-anim.active{display:flex}
        
        .opening-content{text-align:center}
        .opening-icon{font-size:100px;animation:shake 0.6s ease infinite}
        @keyframes shake{0%,100%{transform:rotate(0)}25%{transform:rotate(-10deg)}75%{transform:rotate(10deg)}}
        
        .opening-text{font-size:16px;font-weight:600;margin-top:20px;color:var(--sub)}
        
        .rarity-common{color:#9ca3af}
        .rarity-rare{color:#60a5fa}
        .rarity-epic{color:#a78bfa}
        .rarity-legendary{color:#fbbf24}
        .rarity-mythic{color:#f472b6}
        
        /* Коллекция */
        .section-title{font-size:15px;font-weight:700;margin-bottom:10px;color:var(--sub);text-transform:uppercase;letter-spacing:1px}
        .collection-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:16px}
        
        .collection-item{padding:10px;background:var(--card);border-radius:12px;text-align:center;border:1px solid rgba(255,255,255,0.05)}
        .collection-icon{font-size:28px}
        .collection-name{font-size:10px;font-weight:600;margin-top:4px}
        
        .toast{position:fixed;top:16px;left:50%;transform:translateX(-50%);padding:12px 20px;background:var(--card);border-radius:14px;z-index:300;font-weight:600;font-size:13px;text-align:center;border:1px solid rgba(255,255,255,0.1)}
        
        .currency-toggle{display:flex;gap:6px;margin-bottom:12px}
        .curr-btn{flex:1;padding:8px;border-radius:10px;border:1px solid rgba(255,255,255,0.1);background:transparent;color:var(--sub);font-weight:600;font-size:12px;cursor:pointer;transition:all 0.3s}
        .curr-btn.active{background:var(--accent);color:#fff;border-color:transparent}
    </style>
</head>
<body>
<div class="app">
    <!-- Баланс -->
    <div class="bal">
        <span class="bal-icon">💰</span>
        <span class="bal-text bal-ton" id="tonDisplay">100.00 TON</span>
        <span class="bal-text bal-stars" id="starsDisplay">⭐ 1000</span>
    </div>
    
    <!-- Выбор валюты -->
    <div class="currency-toggle">
        <button class="curr-btn active" onclick="setCurrency('TON', this)">💎 TON</button>
        <button class="curr-btn" onclick="setCurrency('STARS', this)">⭐ STARS</button>
    </div>
    
    <!-- Кейсы -->
    <div class="section-title">🎁 ДОСТУПНЫЕ КЕЙСЫ</div>
    <div class="cases-grid" id="casesGrid"></div>
    
    <!-- Коллекция -->
    <div class="section-title">📦 МОЯ КОЛЛЕКЦИЯ</div>
    <div class="collection-grid" id="collectionGrid">
        <div style="text-align:center;padding:20px;color:var(--sub);grid-column:1/-1">Открывайте кейсы чтобы собирать коллекцию!</div>
    </div>
    
    <!-- Кнопки -->
    <button style="width:100%;padding:14px;margin-top:8px;border-radius:14px;background:linear-gradient(135deg,#ffd700,#ffaa00);color:#000;font-weight:700;border:none;cursor:pointer;font-size:14px" onclick="tg.openTelegramLink('https://t.me/nft_takes_gifts_bot')">💰 ПОПОЛНИТЬ</button>
</div>

<!-- Анимация открытия -->
<div class="opening-anim" id="openingAnim">
    <div class="opening-content">
        <div class="opening-icon" id="openingIcon">📦</div>
        <div class="opening-text">Открываем кейс...</div>
    </div>
</div>

<!-- Модалка результата -->
<div class="modal" id="resultModal">
    <div class="modal-card">
        <button class="modal-close" onclick="closeResult()">✕</button>
        <div class="win-icon" id="resultIcon">🎁</div>
        <div class="win-name" id="resultName">Подарок</div>
        <div class="win-rarity" id="resultRarity">COMMON</div>
        <div class="win-value" id="resultValue">0.5 TON</div>
        <button class="collect-btn" onclick="closeResult()">🎉 ЗАБРАТЬ!</button>
    </div>
</div>

<div class="toast" id="toast" style="display:none"></div>

<script>
const tg=window.Telegram.WebApp;tg.expand();tg.ready();
const user=tg.initDataUnsafe?.user||{};
const uid=user.id||123456;

let ton=100,stars=1000,gifts=[],currency='TON';

function toast(m){const t=document.getElementById('toast');t.textContent=m;t.style.display='block';setTimeout(()=>t.style.display='none',2500)}

async function load(){
    try{const r=await fetch('/api/user/'+uid);const d=await r.json();
        ton=d.balance_ton||100;stars=d.balance_stars||1000;gifts=d.gift_items||[];
        updateUI()}catch(e){updateUI()}
}

function updateUI(){
    document.getElementById('tonDisplay').textContent=ton.toFixed(2)+' TON';
    document.getElementById('starsDisplay').textContent='⭐ '+stars;
    
    // Коллекция
    const grid=document.getElementById('collectionGrid');
    if(gifts.length>0){
        grid.innerHTML=gifts.map(g=>`
            <div class="collection-item">
                <div class="collection-icon">${g.icon||'🎁'}</div>
                <div class="collection-name">${g.name||'Подарок'}</div>
                <div style="font-size:9px;color:var(--sub);margin-top:2px">${g.rarity||'common'}</div>
            </div>`).join('');
    }else{
        grid.innerHTML='<div style="text-align:center;padding:20px;color:var(--sub);grid-column:1/-1">Открывайте кейсы чтобы собирать коллекцию!</div>';
    }
    
    buildCases();
}

function setCurrency(c,btn){
    currency=c;
    document.querySelectorAll('.curr-btn').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    buildCases();
}

function buildCases(){
    fetch('/api/cases').then(r=>r.json()).then(cases=>{
        document.getElementById('casesGrid').innerHTML=cases.map(c=>{
            const price=currency==='TON'?c.price_ton:c.price_stars;
            const balance=currency==='TON'?ton:stars;
            const canOpen=balance>=price;
            
            return `<div class="case-card ${c.id}" onclick="openCase('${c.id}')" style="${canOpen?'':'opacity:0.5;pointer-events:none'}">
                <div class="case-glow"></div>
                <div class="case-icon">${c.icon}</div>
                <div class="case-name">${c.name}</div>
                <div class="case-price">${price} ${currency}</div>
                <div class="case-count">${c.items.length} предметов</div>
            </div>`;
        }).join('');
    });
}

async function openCase(caseId){
    const price=currency==='TON'?{common:1,rare:5,epic:15,legendary:50}[caseId]:{common:10,rare:50,epic:150,legendary:500}[caseId];
    const balance=currency==='TON'?ton:stars;
    
    if(balance<price){toast('❌ Недостаточно '+currency+'!');return}
    
    // Анимация открытия
    const anim=document.getElementById('openingAnim');
    const icon=document.getElementById('openingIcon');
    anim.classList.add('active');
    
    const icons=['📦','🎁','✨','👑','💎','🌟'];
    for(let i=0;i<15;i++){
        icon.textContent=icons[Math.floor(Math.random()*icons.length)];
        await new Promise(r=>setTimeout(r,100));
    }
    
    // Запрос к серверу
    const r=await fetch('/api/open_case',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({user_id:uid,case_id:caseId,currency:currency})
    });
    
    const d=await r.json();
    
    if(d.error){
        anim.classList.remove('active');
        toast('❌ '+d.error);
        return;
    }
    
    // Списываем баланс
    if(currency==='TON')ton-=price;
    else stars-=price;
    
    // Добавляем подарок
    gifts.push({name:d.winner.name,icon:d.winner.icon,rarity:d.winner.rarity,value:d.winner.value});
    
    // Показываем результат
    setTimeout(()=>{
        anim.classList.remove('active');
        
        document.getElementById('resultIcon').textContent=d.winner.icon;
        document.getElementById('resultName').textContent=d.winner.name;
        document.getElementById('resultRarity').innerHTML=`<span class="rarity-${d.winner.rarity}">${d.winner.rarity.toUpperCase()}</span>`;
        document.getElementById('resultValue').textContent='💰 '+d.winner.value+' TON';
        document.getElementById('resultModal').classList.add('active');
        
        updateUI();
    },1800);
}

function closeResult(){
    document.getElementById('resultModal').classList.remove('active');
}

// Инициализация
load();
setInterval(load,30000);
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
        logger.info("Webhook set!")
    except Exception as e:
        logger.error(f"Setup: {e}")
    
    threading.Thread(target=keep_alive, daemon=True).start()
    port = int(os.environ.get('PORT', 8080))
    flask_app.run(host='0.0.0.0', port=port)
