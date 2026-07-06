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
WEBAPP_URL = "https://syndrome-bot-9.onrender.com"
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
                total_deposited_ton REAL DEFAULT 0,
                total_deposited_stars INTEGER DEFAULT 0,
                referral_code TEXT UNIQUE,
                referred_by INTEGER,
                referral_count INTEGER DEFAULT 0,
                free_case_available INTEGER DEFAULT 0,
                gift_items TEXT DEFAULT '[]',
                withdrawn_items TEXT DEFAULT '[]',
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
# TELEGRAM API
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

def generate_ref_code(user_id):
    return hashlib.md5(f"ref{user_id}{time.time()}".encode()).hexdigest()[:8].upper()

# =================================================================
# ДАННЫЕ КЕЙСОВ
# =================================================================
ALL_CASES = {
    "regular": {
        "id": "regular", "name": "Обычный кейс", "icon": "📦",
        "price_ton": 1, "price_stars": 15, "color": "#9CA3AF",
        "items": [
            {"name": "❤️ Сердечко", "icon": "❤️", "chance": 30, "value_stars": 15, "value_ton": 0.5},
            {"name": "🧸 Мишка", "icon": "🧸", "chance": 25, "value_stars": 15, "value_ton": 0.5},
            {"name": "🌹 Роза", "icon": "🌹", "chance": 20, "value_stars": 25, "value_ton": 0.8},
            {"name": "🎂 Тортик", "icon": "🎂", "chance": 10, "value_stars": 50, "value_ton": 1.5},
            {"name": "💍 Кольцо", "icon": "💍", "chance": 7, "value_stars": 100, "value_ton": 3.0},
            {"name": "💎 Кристалл", "icon": "💎", "chance": 5, "value_stars": 150, "value_ton": 5.0},
            {"name": "💩 Ничего", "icon": "💩", "chance": 3, "value_stars": 0, "value_ton": 0},
        ]
    },
    "stars": {
        "id": "stars", "name": "Звёздный кейс", "icon": "⭐",
        "price_stars": 100, "color": "#FBBF24",
        "items": [
            {"name": "15 Звёзд", "icon": "⭐", "chance": 45, "value_stars": 15},
            {"name": "30 Звёзд", "icon": "🌟", "chance": 30, "value_stars": 30},
            {"name": "50 Звёзд", "icon": "💫", "chance": 25, "value_stars": 50},
            {"name": "75 Звёзд", "icon": "✨", "chance": 20, "value_stars": 75},
            {"name": "150 Звёзд", "icon": "💎", "chance": 5, "value_stars": 150},
            {"name": "350 Звёзд", "icon": "👑", "chance": 2, "value_stars": 350},
        ]
    },
    "ton": {
        "id": "ton", "name": "TON кейс", "icon": "💎",
        "price_ton": 10, "color": "#0088CC",
        "items": [
            {"name": "1 TON", "icon": "💎", "chance": 45, "value_ton": 1},
            {"name": "3 TON", "icon": "💎", "chance": 35, "value_ton": 3},
            {"name": "5 TON", "icon": "💎", "chance": 20, "value_ton": 5},
            {"name": "8 TON", "icon": "💎", "chance": 10, "value_ton": 8},
            {"name": "15 TON", "icon": "💎", "chance": 5, "value_ton": 15},
            {"name": "30 TON", "icon": "💎", "chance": 2, "value_ton": 30},
        ]
    },
    "nft": {
        "id": "nft", "name": "NFT кейс", "icon": "🐵",
        "price_ton": 50, "price_stars": 350, "color": "#F472B6",
        "items": [
            {"name": "🐵 NFT Обезьяна", "icon": "🐵", "chance": 8, "value_stars": 1500, "value_ton": 50},
            {"name": "🐍 NFT Змейка", "icon": "🐍", "chance": 35, "value_stars": 250, "value_ton": 8},
            {"name": "🎄 NFT Новый Год", "icon": "🎄", "chance": 45, "value_stars": 150, "value_ton": 5},
            {"name": "🎃 NFT Хэллоуин", "icon": "🎃", "chance": 12, "value_stars": 400, "value_ton": 15},
        ]
    },
    "free": {
        "id": "free", "name": "Бесплатный кейс", "icon": "🎁",
        "color": "#10B981",
        "items": [
            {"name": "🧸 Мишка", "icon": "🧸", "chance": 20, "value_stars": 15, "value_ton": 0.5},
            {"name": "❤️ Сердечко", "icon": "❤️", "chance": 20, "value_stars": 15, "value_ton": 0.5},
            {"name": "🌹 Роза", "icon": "🌹", "chance": 15, "value_stars": 25, "value_ton": 0.8},
            {"name": "🎂 Тортик", "icon": "🎂", "chance": 10, "value_stars": 50, "value_ton": 1.5},
            {"name": "💍 Кольцо", "icon": "💍", "chance": 5, "value_stars": 100, "value_ton": 3.0},
            {"name": "💩 Ничего", "icon": "💩", "chance": 30, "value_stars": 0, "value_ton": 0},
        ]
    }
}

# =================================================================
# BOT HANDLERS
# =================================================================
def handle_start(chat_id, user, args=None):
    uid = user["id"]
    uname = user.get("username", f"user_{uid}")
    fname = user.get("first_name", "Player")
    
    ref_code = args[0] if args else None
    
    with db_connect() as conn:
        row = conn.execute('SELECT user_id FROM users WHERE user_id=?', (uid,)).fetchone()
        
        if not row:
            my_ref = generate_ref_code(uid)
            referred_by = None
            
            if ref_code:
                ref_row = conn.execute('SELECT user_id FROM users WHERE referral_code=?', (ref_code,)).fetchone()
                if ref_row and ref_row[0] != uid:
                    referred_by = ref_row[0]
                    conn.execute('UPDATE users SET referral_count=referral_count+1 WHERE user_id=?', (referred_by,))
                    ref_count = conn.execute('SELECT referral_count FROM users WHERE user_id=?', (referred_by,)).fetchone()
                    if ref_count and ref_count[0] >= 3:
                        conn.execute('UPDATE users SET free_case_available=1 WHERE user_id=?', (referred_by,))
            
            conn.execute('''
                INSERT INTO users (user_id, username, first_name, referral_code, referred_by, balance_stars, balance_ton)
                VALUES (?, ?, ?, ?, ?, 50, 1.0)
            ''', (uid, uname, fname, my_ref, referred_by))
    
    keyboard = {"inline_keyboard": [
        [{"text": "🎁 ОТКРЫТЬ ПРИЛОЖЕНИЕ", "web_app": {"url": WEBAPP_URL}}],
        [{"text": "👥 РЕФЕРАЛЬНАЯ СИСТЕМА", "callback_data": "ref_info"}]
    ]}
    
    tg_send(chat_id, 
        "🎁 <b>GIFT CASES — КЕЙСЫ ПОДАРКОВ</b>\n\n"
        "📦 Обычный • ⭐ Звёздный\n"
        "💎 TON • 🐵 NFT\n"
        "🎁 Бесплатный (за 3 реферала)\n\n"
        "<b>👇 НАЖМИ НА КНОПКУ!</b>",
        keyboard
    )

def handle_ref_info(cb, chat_id, msg_id, uid):
    tg_answer(cb["id"])
    
    with db_connect() as conn:
        row = conn.execute('SELECT referral_code, referral_count FROM users WHERE user_id=?', (uid,)).fetchone()
    
    if row:
        ref_code, ref_count = row
        ref_link = f"https://t.me/{BOT_USERNAME}?start={ref_code}"
        need = max(0, 3 - ref_count)
        
        tg_edit(chat_id, msg_id,
            f"👥 <b>РЕФЕРАЛЬНАЯ СИСТЕМА</b>\n\n"
            f"Пригласите 3 друзей — получите <b>БЕСПЛАТНЫЙ КЕЙС</b>!\n\n"
            f"🔗 Ваша ссылка:\n<code>{ref_link}</code>\n\n"
            f"📊 Приглашено: <b>{ref_count}/3</b>\n"
            f"{'✅ Бесплатный кейс доступен!' if ref_count >= 3 else '❌ Пригласите ещё ' + str(need)}",
            {"inline_keyboard": [
                [{"text": "📤 ПОДЕЛИТЬСЯ", "switch_inline_query": ref_code}],
                [{"text": "🎁 ОТКРЫТЬ ПРИЛОЖЕНИЕ", "web_app": {"url": WEBAPP_URL}}]
            ]}
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
            row = conn.execute('''
                SELECT balance_ton, balance_stars, gift_items, withdrawn_items, referral_count, 
                       free_case_available, language
                FROM users WHERE user_id=?
            ''', (uid,)).fetchone()
        if row:
            return jsonify({
                'balance_ton': row[0], 'balance_stars': row[1],
                'gift_items': json.loads(row[2]) if row[2] else [],
                'withdrawn_items': json.loads(row[3]) if row[3] else [],
                'referral_count': row[4], 'free_case_available': row[5],
                'language': row[6]
            })
    except: pass
    return jsonify({
        'balance_ton': 100.0, 'balance_stars': 1000, 'gift_items': [], 'withdrawn_items': [],
        'referral_count': 0, 'free_case_available': 0, 'language': 'ru'
    })

@flask_app.route('/api/cases')
def api_cases():
    cases_list = []
    for key, case in ALL_CASES.items():
        cases_list.append({
            'id': key, 'name': case['name'], 'icon': case['icon'],
            'price_ton': case.get('price_ton', 0), 'price_stars': case.get('price_stars', 0),
            'color': case['color'], 'items': case['items']
        })
    return jsonify(cases_list)

@flask_app.route('/api/open_case', methods=['POST'])
def api_open_case():
    data = request.json
    uid = data.get('user_id')
    case_id = data.get('case_id')
    currency = data.get('currency', 'TON')
    
    if case_id not in ALL_CASES:
        return jsonify({'error': 'Кейс не найден!'}), 404
    
    case = ALL_CASES[case_id]
    
    with db_connect() as conn:
        row = conn.execute('SELECT balance_ton, balance_stars, free_case_available, gift_items FROM users WHERE user_id=?', (uid,)).fetchone()
        if not row:
            return jsonify({'error': 'Пользователь не найден!'}), 404
        
        ton_bal, stars_bal, free_avail, gifts_json = row
        gifts = json.loads(gifts_json) if gifts_json else []
        
        if case_id == 'free':
            if free_avail <= 0:
                return jsonify({'error': 'Нужно пригласить 3 друзей!'}), 400
            conn.execute('UPDATE users SET free_case_available=0 WHERE user_id=?', (uid,))
        else:
            price = case.get('price_ton', 0) if currency == 'TON' else case.get('price_stars', 0)
            if currency == 'TON' and ton_bal < price:
                return jsonify({'error': 'Недостаточно TON!'}), 400
            if currency == 'STARS' and stars_bal < price:
                return jsonify({'error': 'Недостаточно Stars!'}), 400
            
            if currency == 'TON':
                conn.execute('UPDATE users SET balance_ton=balance_ton-? WHERE user_id=?', (price, uid))
            else:
                conn.execute('UPDATE users SET balance_stars=balance_stars-? WHERE user_id=?', (price, uid))
        
        # Выбор предмета
        items_pool = []
        for item in case['items']:
            items_pool.extend([item] * int(item['chance'] * 10))
        
        winner = random.choice(items_pool)
        
        gifts.append({
            'name': winner['name'], 'icon': winner['icon'],
            'value_stars': winner.get('value_stars', 0),
            'value_ton': winner.get('value_ton', 0),
            'timestamp': datetime.now().isoformat()
        })
        conn.execute('UPDATE users SET gift_items=? WHERE user_id=?', (json.dumps(gifts), uid))
        
        new_ton = conn.execute('SELECT balance_ton FROM users WHERE user_id=?', (uid,)).fetchone()[0]
        new_stars = conn.execute('SELECT balance_stars FROM users WHERE user_id=?', (uid,)).fetchone()[0]
    
    return jsonify({
        'winner': winner,
        'balance_ton': new_ton,
        'balance_stars': new_stars
    })

@flask_app.route('/api/sell_item', methods=['POST'])
def api_sell_item():
    data = request.json
    uid = data.get('user_id')
    item_index = data.get('item_index')
    
    with db_connect() as conn:
        row = conn.execute('SELECT gift_items, balance_ton, balance_stars FROM users WHERE user_id=?', (uid,)).fetchone()
        if not row: return jsonify({'error': 'Пользователь не найден!'}), 404
        
        gifts = json.loads(row[0]) if row[0] else []
        if item_index < 0 or item_index >= len(gifts):
            return jsonify({'error': 'Предмет не найден!'}), 404
        
        item = gifts.pop(item_index)
        value_stars = int(item.get('value_stars', 0) * 0.98)
        value_ton = round(item.get('value_ton', 0) * 0.98, 2)
        
        conn.execute('UPDATE users SET gift_items=?, balance_stars=balance_stars+?, balance_ton=balance_ton+? WHERE user_id=?',
                    (json.dumps(gifts), value_stars, value_ton, uid))
        
        new_ton = row[1] + value_ton
        new_stars = row[2] + value_stars
    
    return jsonify({
        'success': True, 'sold_item': item,
        'received_stars': value_stars, 'received_ton': value_ton,
        'balance_ton': new_ton, 'balance_stars': new_stars
    })

@flask_app.route('/api/withdraw_item', methods=['POST'])
def api_withdraw_item():
    """ФЕЙКОВЫЙ ВЫВОД — предмет перемещается в историю выведенных, но реально никуда не отправляется"""
    data = request.json
    uid = data.get('user_id')
    item_index = data.get('item_index')
    wallet = data.get('wallet', '')
    
    with db_connect() as conn:
        row = conn.execute('SELECT gift_items, withdrawn_items FROM users WHERE user_id=?', (uid,)).fetchone()
        if not row: return jsonify({'error': 'Пользователь не найден!'}), 404
        
        gifts = json.loads(row[0]) if row[0] else []
        withdrawn = json.loads(row[1]) if row[1] else []
        
        if item_index < 0 or item_index >= len(gifts):
            return jsonify({'error': 'Предмет не найден!'}), 404
        
        item = gifts.pop(item_index)
        item['withdrawn_at'] = datetime.now().isoformat()
        item['wallet'] = wallet
        item['status'] = 'completed'  # Фейковый статус "выведено"
        withdrawn.append(item)
        
        conn.execute('UPDATE users SET gift_items=?, withdrawn_items=? WHERE user_id=?',
                    (json.dumps(gifts), json.dumps(withdrawn), uid))
        
        # Сохраняем заявку в БД (для видимости)
        conn.execute('''
            INSERT INTO withdrawal_requests (user_id, item_name, item_icon, amount, currency, wallet, status)
            VALUES (?, ?, ?, ?, ?, ?, 'completed')
        ''', (uid, item['name'], item['icon'], item.get('value_ton', 0), 'TON', wallet))
    
    return jsonify({
        'success': True,
        'message': f'✅ {item["name"]} успешно выведен на кошелёк {wallet[:10]}...',
        'item': item
    })

@flask_app.route('/api/language', methods=['POST'])
def api_language():
    data = request.json
    uid = data.get('user_id')
    lang = data.get('language', 'ru')
    with db_connect() as conn:
        conn.execute('UPDATE users SET language=? WHERE user_id=?', (lang, uid))
    return jsonify({'success': True})

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
                    args = text.replace("/start", "").strip().split()
                    handle_start(chat_id, user, args if args else None)
                elif text.startswith("/withdraw"):
                    try:
                        parts = text.split()
                        amt = float(parts[1])
                        wallet = parts[2] if len(parts) > 2 else None
                        if not wallet: tg_send(chat_id, "❌ /withdraw СУММА КОШЕЛЕК")
                        elif amt < 10: tg_send(chat_id, "❌ Мин: 10 TON")
                        else:
                            with db_connect() as conn:
                                row = conn.execute('SELECT balance_ton FROM users WHERE user_id=?', (uid,)).fetchone()
                                if not row or row[0] < amt: tg_send(chat_id, "❌ Недостаточно!")
                                else:
                                    conn.execute('UPDATE users SET balance_ton=balance_ton-? WHERE user_id=?', (amt, uid))
                                    conn.execute('INSERT INTO withdrawal_requests (user_id, item_name, amount, currency, wallet, status) VALUES (?,?,?,?,?,?)', (uid, 'TON Вывод', amt, 'TON', wallet, 'completed'))
                                    tg_send(chat_id, f"✅ Заявка на вывод <b>{amt} TON</b> создана!\n⏳ Ожидайте зачисления (до 24ч)")
                    except: tg_send(chat_id, "❌ /withdraw СУММА КОШЕЛЕК")
        elif "callback_query" in update:
            cb = update["callback_query"]
            chat_id = cb["message"]["chat"]["id"]
            msg_id = cb["message"]["message_id"]
            uid = cb["from"]["id"]
            data = cb.get("data", "")
            if data == "ref_info": handle_ref_info(cb, chat_id, msg_id, uid)
            else: tg_answer(cb["id"])
        return "ok", 200
    except Exception as e:
        logger.error(f"Webhook: {e}")
        return "error", 500

@flask_app.route('/health')
def health():
    return jsonify({"status": "ok"})

# =================================================================
# HTML ШАБЛОН
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

        :root {
            --bg: #0a0a1a;
            --card: #141428;
            --gold: #ffd700;
            --accent: #7c3aed;
            --text: #fff;
            --sub: #888;
            --border: rgba(255, 255, 255, 0.06);
        }

        *{margin:0;padding:0;box-sizing:border-box}
        body{background:var(--bg);color:var(--text);font-family:'Inter',sans-serif;min-height:100vh;overflow-x:hidden;-webkit-tap-highlight-color:transparent}

        .app{max-width:440px;margin:0 auto;min-height:100vh;position:relative;padding-bottom:90px}

        .page{display:none;padding:12px;animation:fadeIn 0.3s ease}
        .page.active{display:block}
        @keyframes fadeIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}

        .topbar{display:flex;align-items:center;justify-content:space-between;padding:10px 16px;background:var(--card);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:50}
        .topbar-title{font-weight:700;font-size:16px}
        .back-btn{width:36px;height:36px;border-radius:50%;background:rgba(255,255,255,0.05);border:none;color:#fff;font-size:18px;cursor:pointer;display:flex;align-items:center;justify-content:center}
        .avatar-sm{width:36px;height:36px;border-radius:50%;background:linear-gradient(135deg,var(--accent),#a855f7);display:flex;align-items:center;justify-content:center;font-weight:700;font-size:16px;cursor:pointer}

        .bal-row{display:flex;gap:8px;padding:8px 12px;overflow-x:auto}
        .bal-chip{flex-shrink:0;padding:6px 12px;border-radius:20px;background:var(--card);font-size:12px;font-weight:600;white-space:nowrap;border:1px solid var(--border)}
        .bal-chip.ton{color:var(--gold)}.bal-chip.stars{color:#60a5fa}

        .cases-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:12px}
        .case-card{padding:20px 14px;border-radius:20px;text-align:center;cursor:pointer;transition:all 0.3s;border:2px solid var(--border);position:relative;overflow:hidden;background:var(--card)}
        .case-card:active{transform:scale(0.95)}
        .case-card.featured{grid-column:1/-1;padding:24px}
        .case-icon{font-size:48px;margin-bottom:8px;position:relative;z-index:1}
        .case-card.featured .case-icon{font-size:60px}
        .case-name{font-weight:700;font-size:14px;margin-bottom:4px;position:relative;z-index:1}
        .case-card.featured .case-name{font-size:17px}
        .case-price{font-size:12px;font-weight:600;position:relative;z-index:1}

        .case-detail-header{text-align:center;padding:20px}
        .case-detail-icon{font-size:72px;margin-bottom:8px}
        .case-detail-name{font-weight:800;font-size:22px}
        .case-detail-price{font-size:15px;color:var(--gold);margin-top:4px}

        .items-preview{padding:0 12px 12px}
        .items-preview-title{font-weight:600;font-size:13px;color:var(--sub);margin-bottom:10px;text-transform:uppercase;letter-spacing:1px}
        .items-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
        .item-mini{display:flex;align-items:center;gap:10px;padding:10px 12px;background:var(--card);border-radius:12px;border:1px solid var(--border);font-size:12px}
        .item-mini-icon{font-size:28px;width:36px;text-align:center}
        .item-mini-name{font-weight:600;font-size:11px}
        .item-mini-chance{font-size:10px;color:var(--gold)}

        .spin-btn{display:block;width:calc(100% - 24px);margin:0 12px 12px;padding:16px;border-radius:16px;font-weight:700;font-size:16px;border:none;cursor:pointer;text-transform:uppercase;letter-spacing:1px;transition:all 0.3s}
        .spin-btn:active{transform:scale(0.97)}
        .spin-btn.active{background:linear-gradient(135deg,var(--accent),#a855f7);color:#fff;box-shadow:0 0 30px rgba(124,58,237,0.4)}
        .spin-btn.disabled{background:#333;color:#666;cursor:not-allowed}

        .spin-anim{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.95);z-index:200;flex-direction:column;align-items:center;justify-content:center}
        .spin-anim.active{display:flex}

        .roulette-window{width:92%;max-width:380px;height:110px;background:var(--card);border-radius:24px;overflow:hidden;position:relative;border:2px solid var(--border);margin-bottom:20px;box-shadow:0 20px 40px rgba(0,0,0,0.5)}
        .roulette-window::before,.roulette-window::after{content:'';position:absolute;left:0;width:100%;height:35px;z-index:2;pointer-events:none}
        .roulette-window::before{top:0;background:linear-gradient(to bottom,var(--card),transparent)}
        .roulette-window::after{bottom:0;background:linear-gradient(to top,var(--card),transparent)}
        .pointer-area{position:absolute;left:50%;top:0;width:4px;height:100%;z-index:3;transform:translateX(-50%)}
        .pointer-line{position:absolute;left:50%;top:0;width:3px;height:100%;background:var(--gold);transform:translateX(-50%);box-shadow:0 0 15px rgba(255,215,0,0.6),0 0 30px rgba(255,215,0,0.3)}
        .pointer-arrow-top{position:absolute;left:50%;top:8px;transform:translateX(-50%);color:var(--gold);font-size:16px;z-index:4;filter:drop-shadow(0 0 6px rgba(255,215,0,0.8))}
        .pointer-arrow-bottom{position:absolute;left:50%;bottom:8px;transform:translateX(-50%) rotate(180deg);color:var(--gold);font-size:16px;z-index:4;filter:drop-shadow(0 0 6px rgba(255,215,0,0.8))}

        .roulette-track{display:flex;position:absolute;left:50%;top:15px;transform:translateX(0);transition:transform 6s cubic-bezier(0.05,0.95,0.1,1)}
        .roulette-item{width:80px;height:80px;display:flex;align-items:center;justify-content:center;font-size:44px;flex-shrink:0;opacity:0.45;transition:all 0.3s;border-radius:16px;margin:0 4px}
        .roulette-item.highlight{opacity:1;transform:scale(1.2);background:rgba(255,215,0,0.12);border:2px solid var(--gold);box-shadow:0 0 30px rgba(255,215,0,0.5),0 0 60px rgba(255,215,0,0.2);z-index:5}
        .spin-text{font-size:18px;color:var(--sub);font-weight:600;transition:all 0.3s}
        .spin-text.win{color:var(--gold);font-size:22px;font-weight:800}

        .result-toast{position:fixed;top:16px;left:50%;transform:translateX(-50%);padding:14px 20px;background:var(--card);border-radius:14px;z-index:300;text-align:center;font-weight:600;font-size:13px;border:1px solid var(--gold);animation:slideDown 0.4s ease;cursor:pointer;box-shadow:0 10px 30px rgba(0,0,0,0.5);display:flex;align-items:center;gap:10px}
        @keyframes slideDown{from{transform:translate(-50%,-100%);opacity:0}to{transform:translate(-50%,0);opacity:1}}

        .profile-header{text-align:center;padding:20px}
        .profile-avatar{width:64px;height:64px;border-radius:50%;background:linear-gradient(135deg,var(--accent),#a855f7);display:flex;align-items:center;justify-content:center;font-size:28px;font-weight:700;margin:0 auto 8px}
        .tab-row{display:flex;gap:2px;padding:4px;background:var(--card);border-radius:12px;margin:0 12px 12px;overflow-x:auto}
        .tab-btn{flex:1;min-width:fit-content;padding:10px 8px;text-align:center;border-radius:10px;cursor:pointer;font-weight:600;font-size:11px;color:var(--sub);border:none;background:transparent;transition:all 0.3s;white-space:nowrap}
        .tab-btn.active{background:var(--accent);color:#fff}
        .tab-content{display:none;padding:12px}
        .tab-content.active{display:block}

        .gift-item-card{display:flex;align-items:center;gap:12px;padding:12px;background:var(--card);border-radius:12px;margin-bottom:8px;border:1px solid var(--border)}
        .gift-item-icon{font-size:36px;width:50px;text-align:center}
        .gift-item-info{flex:1}
        .gift-item-name{font-weight:600;font-size:14px}
        .gift-item-value{font-size:11px;color:var(--gold)}
        .gift-item-status{font-size:10px;color:#10B981;margin-top:2px}
        .gift-item-actions{display:flex;gap:6px}
        .btn-sm{padding:8px 12px;border-radius:8px;font-size:11px;font-weight:600;cursor:pointer;border:none;transition:all 0.3s}
        .btn-sm:active{transform:scale(0.95)}
        .btn-sell{background:#ef4444;color:#fff}
        .btn-withdraw{background:#3b82f6;color:#fff}

        .faq-item{padding:12px;background:var(--card);border-radius:12px;margin-bottom:8px;border:1px solid var(--border)}
        .faq-q{font-weight:600;margin-bottom:4px}
        .faq-a{font-size:13px;color:var(--sub)}

        .bottom-nav{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);display:flex;gap:4px;padding:6px;background:var(--card);border-radius:20px;z-index:100;border:1px solid var(--border);box-shadow:0 10px 30px rgba(0,0,0,0.3)}
        .nav-btn{width:52px;height:52px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:20px;cursor:pointer;transition:all 0.3s;border:none;background:transparent;flex-direction:column;gap:1px}
        .nav-btn.active{background:var(--accent);box-shadow:0 0 15px rgba(124,58,237,0.4)}
        .nav-label{font-size:8px;font-weight:600;color:var(--sub)}
        .nav-btn.active .nav-label{color:#fff}
    </style>
</head>
<body>
<div class="app">
    <div class="topbar" id="topbarMain">
        <div class="topbar-title">🎁 Кейсы</div>
        <div class="avatar-sm" id="avatarSm" onclick="navigate('profile')">S</div>
    </div>
    <div class="topbar" id="topbarCase" style="display:none">
        <button class="back-btn" onclick="goBack()">←</button>
        <div class="topbar-title" id="caseTopTitle">Кейс</div>
        <div style="width:36px"></div>
    </div>
    <div class="bal-row">
        <div class="bal-chip ton" id="tonChip">💎 100.00 TON</div>
        <div class="bal-chip stars" id="starsChip">⭐ 1000 Stars</div>
    </div>

    <div class="page active" id="page-cases"><div class="cases-grid" id="casesGrid"></div></div>

    <div class="page" id="page-case-detail">
        <div class="case-detail-header">
            <div class="case-detail-icon" id="detailIcon">📦</div>
            <div class="case-detail-name" id="detailName">Обычный кейс</div>
            <div class="case-detail-price" id="detailPrice">1 TON</div>
        </div>
        <div class="items-preview">
            <div class="items-preview-title">Возможные призы</div>
            <div class="items-grid" id="detailItems"></div>
        </div>
        <button class="spin-btn active" id="detailSpinBtn" onclick="startSpin()">🎰 НАЧАТЬ КРУТИТЬ</button>
    </div>

    <div class="page" id="page-wins"><div id="winsList"></div></div>

    <div class="page" id="page-faq">
        <div class="faq-item"><div class="faq-q">❓ Как открыть кейс?</div><div class="faq-a">Выберите кейс и нажмите "Начать крутить".</div></div>
        <div class="faq-item"><div class="faq-q">❓ Как пополнить баланс?</div><div class="faq-a">Через бота @nft_takes_gifts_bot.</div></div>
        <div class="faq-item"><div class="faq-q">❓ Как вывести подарок?</div><div class="faq-a">В разделе "Выигрыши" нажмите "Вывести" и укажите адрес кошелька. Вывод занимает до 24 часов.</div></div>
    </div>

    <div class="page" id="page-lang">
        <div style="text-align:center;padding:40px 20px">
            <div style="font-size:48px;margin-bottom:16px">🌐</div>
            <button style="width:100%;padding:14px;margin-bottom:8px;background:var(--accent);color:#fff;font-size:15px;border:none;border-radius:12px;cursor:pointer;font-weight:600" onclick="setLang('ru')">🇷🇺 Русский</button>
            <button style="width:100%;padding:14px;background:#3b82f6;color:#fff;font-size:15px;border:none;border-radius:12px;cursor:pointer;font-weight:600" onclick="setLang('en')">🇬🇧 English</button>
        </div>
    </div>

    <div class="page" id="page-profile">
        <div class="profile-header">
            <div class="profile-avatar" id="profileAvatar">S</div>
            <div style="font-weight:700;font-size:16px;margin-top:4px" id="profileName">Player</div>
        </div>
        <div class="tab-row">
            <button class="tab-btn active" onclick="profileTab('info')">📋 Инфо</button>
            <button class="tab-btn" onclick="profileTab('wins')">🏆 Выигрыши</button>
            <button class="tab-btn" onclick="profileTab('faq')">❓ FAQ</button>
            <button class="tab-btn" onclick="profileTab('lang')">🌐 Язык</button>
        </div>
        <div class="tab-content active" id="ptab-info">
            <div style="text-align:center;padding:10px">
                <div style="margin:12px 0;font-size:15px">💎 TON: <b id="pTon" style="color:var(--gold)">100.00</b></div>
                <div style="margin:12px 0;font-size:15px">⭐ Stars: <b id="pStars" style="color:#60a5fa">1000</b></div>
                <div style="margin:12px 0;font-size:14px;color:var(--sub)">🎁 Подарков: <b id="pGifts">0</b></div>
                <div style="margin:12px 0;font-size:14px;color:var(--sub)">📤 Выведено: <b id="pWithdrawn">0</b></div>
            </div>
        </div>
        <div class="tab-content" id="ptab-wins"><div id="profileWinsList"></div></div>
        <div class="tab-content" id="ptab-faq"><div class="faq-item"><div class="faq-q">❓ Как продать?</div><div class="faq-a">В "Выигрыши" нажмите "Продать".</div></div></div>
        <div class="tab-content" id="ptab-lang">
            <button style="width:100%;padding:14px;margin-bottom:8px;background:var(--accent);color:#fff;font-size:15px;border:none;border-radius:12px;cursor:pointer;font-weight:600" onclick="setLang('ru')">🇷🇺 Русский</button>
            <button style="width:100%;padding:14px;background:#3b82f6;color:#fff;font-size:15px;border:none;border-radius:12px;cursor:pointer;font-weight:600" onclick="setLang('en')">🇬🇧 English</button>
        </div>
    </div>
</div>

<div class="spin-anim" id="spinAnim">
    <div class="roulette-window" id="rouletteWindow">
        <div class="pointer-area">
            <div class="pointer-arrow-top">▼</div>
            <div class="pointer-line"></div>
            <div class="pointer-arrow-bottom">▼</div>
        </div>
        <div class="roulette-track" id="rouletteTrack"></div>
    </div>
    <div class="spin-text" id="spinText">Крутим...</div>
</div>

<div class="result-toast" id="resultToast" style="display:none" onclick="navigate('wins')">
    <div id="toastIcon" style="font-size:28px">🎁</div>
    <div><div id="toastName" style="font-weight:700;font-size:14px">Подарок</div></div>
</div>

<div class="bottom-nav">
    <button class="nav-btn active" onclick="navigate('cases')"><span>🎁</span><span class="nav-label">Кейсы</span></button>
    <button class="nav-btn" onclick="navigate('wins')"><span>🏆</span><span class="nav-label">Выигрыши</span></button>
    <button class="nav-btn" onclick="navigate('faq')"><span>❓</span><span class="nav-label">FAQ</span></button>
    <button class="nav-btn" onclick="navigate('lang')"><span>🌐</span><span class="nav-label">Язык</span></button>
    <button class="nav-btn" onclick="navigate('profile')"><span>👤</span><span class="nav-label">Профиль</span></button>
</div>

<script>
const tg=window.Telegram.WebApp;tg.expand();tg.ready();
const user=tg.initDataUnsafe?.user||{};
const uname=user.first_name||'Player';
const uid=user.id||123456789;

let ton=100,stars=1000,gifts=[],withdrawn=[],currentCase=null,isSpinning=false;

document.getElementById('avatarSm').textContent=uname[0].toUpperCase();
document.getElementById('profileAvatar').textContent=uname[0].toUpperCase();
document.getElementById('profileName').textContent=uname;

async function loadUser(){
    try{const r=await fetch('/api/user/'+uid);const d=await r.json();
        ton=d.balance_ton||100;stars=d.balance_stars||1000;gifts=d.gift_items||[];withdrawn=d.withdrawn_items||[];updateUI()}catch(e){updateUI()}
}

function updateUI(){
    document.getElementById('tonChip').textContent='💎 '+ton.toFixed(2)+' TON';
    document.getElementById('starsChip').textContent='⭐ '+stars+' Stars';
    document.getElementById('pTon').textContent=ton.toFixed(2);
    document.getElementById('pStars').textContent=stars;
    document.getElementById('pGifts').textContent=gifts.length;
    document.getElementById('pWithdrawn').textContent=withdrawn.length;
    renderWins();loadCases();
}

async function loadCases(){
    try{const r=await fetch('/api/cases');const cases=await r.json();
        document.getElementById('casesGrid').innerHTML=cases.map(c=>{
            const price=c.price_ton?c.price_ton+' TON':(c.price_stars?c.price_stars+' Stars':'Бесплатно');
            const feat=c.id==='ton'?' featured':'';
            return `<div class="case-card${feat}" style="border-color:${c.color}" onclick="openCaseDetail('${c.id}')">
                <div class="case-icon">${c.icon}</div><div class="case-name">${c.name}</div><div class="case-price" style="color:${c.color}">${price}</div></div>`;
        }).join('')}catch(e){}
}

function openCaseDetail(caseId){
    fetch('/api/cases').then(r=>r.json()).then(cases=>{
        currentCase=cases.find(c=>c.id===caseId);if(!currentCase)return;
        document.getElementById('detailIcon').textContent=currentCase.icon;
        document.getElementById('detailName').textContent=currentCase.name;
        const price=currentCase.price_ton?currentCase.price_ton+' TON':(currentCase.price_stars?currentCase.price_stars+' Stars':'Бесплатно');
        document.getElementById('detailPrice').textContent=price;
        document.getElementById('caseTopTitle').textContent=currentCase.name;
        document.getElementById('detailItems').innerHTML=currentCase.items.map(item=>`
            <div class="item-mini"><div class="item-mini-icon">${item.icon}</div><div><div class="item-mini-name">${item.name}</div><div class="item-mini-chance">${item.chance}%</div></div></div>`).join('');
        const can=checkBalance();const btn=document.getElementById('detailSpinBtn');
        btn.className=can?'spin-btn active':'spin-btn disabled';btn.textContent=can?'🎰 НАЧАТЬ КРУТИТЬ':'💰 ПОПОЛНИТЕ БАЛАНС';
        showPage('case-detail');document.getElementById('topbarMain').style.display='none';document.getElementById('topbarCase').style.display='flex';
    });
}

function checkBalance(){if(!currentCase)return false;if(currentCase.id==='free')return true;if(currentCase.price_ton&&ton>=currentCase.price_ton)return true;if(currentCase.price_stars&&stars>=currentCase.price_stars)return true;return false}

async function startSpin(){
    if(!currentCase||isSpinning)return;if(!checkBalance()){alert('Пополните баланс!');return}
    const currency=currentCase.price_ton?'TON':'STARS';
    const r=await fetch('/api/open_case',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:uid,case_id:currentCase.id,currency})});
    const d=await r.json();if(d.error){alert(d.error);return}
    ton=d.balance_ton;stars=d.balance_stars;const winner=d.winner;

    const trackItems=[];for(let i=0;i<40;i++)trackItems.push(...currentCase.items);
    const winnerIndices=[];trackItems.forEach((item,i)=>{if(item.icon===winner.icon&&item.name===winner.name)winnerIndices.push(i)});
    const rs=Math.floor(trackItems.length*0.55),re=Math.floor(trackItems.length*0.75);
    const valid=winnerIndices.filter(i=>i>=rs&&i<=re);
    const chosenIdx=valid.length>0?valid[Math.floor(Math.random()*valid.length)]:winnerIndices[Math.floor(winnerIndices.length/2)];

    const track=document.getElementById('rouletteTrack');
    track.innerHTML=trackItems.map((item,i)=>`<div class="roulette-item" id="ri${i}">${item.icon}</div>`).join('');
    const IW=88;const ww=document.getElementById('rouletteWindow').offsetWidth;
    const tp=-(chosenIdx*IW)+(ww/2)-(IW/2);

    track.style.transition='none';track.style.transform='translateX(0)';
    document.getElementById('spinAnim').classList.add('active');
    document.getElementById('spinText').textContent='Крутим...';document.getElementById('spinText').classList.remove('win');
    isSpinning=true;

    requestAnimationFrame(()=>{requestAnimationFrame(()=>{track.style.transition='transform 6s cubic-bezier(0.05,0.95,0.1,1)';track.style.transform=`translateX(${tp}px)`})});

    setTimeout(()=>{
        document.querySelectorAll('.roulette-item').forEach(el=>el.classList.remove('highlight'));
        const wel=document.getElementById('ri'+chosenIdx);if(wel)wel.classList.add('highlight');
        document.getElementById('spinText').textContent='🎉 '+winner.name+'!';document.getElementById('spinText').classList.add('win');
    },5500);

    setTimeout(()=>{
        document.getElementById('spinAnim').classList.remove('active');isSpinning=false;
        gifts.push({name:winner.name,icon:winner.icon,value_stars:winner.value_stars||0,value_ton:winner.value_ton||0});
        document.getElementById('toastIcon').textContent=winner.icon;document.getElementById('toastName').textContent=winner.name;
        document.getElementById('resultToast').style.display='flex';setTimeout(()=>document.getElementById('resultToast').style.display='none',3000);
        updateUI();goBack();
    },6300);
}

function goBack(){showPage('cases');document.getElementById('topbarMain').style.display='flex';document.getElementById('topbarCase').style.display='none';currentCase=null}

function renderWins(){
    const active=gifts.map((g,i)=>`<div class="gift-item-card"><div class="gift-item-icon">${g.icon}</div><div class="gift-item-info"><div class="gift-item-name">${g.name}</div><div class="gift-item-value">${g.value_stars?g.value_stars+' Stars':''} ${g.value_ton?g.value_ton+' TON':''}</div></div><div class="gift-item-actions"><button class="btn-sm btn-sell" onclick="sellItem(${i})">💰 Продать</button><button class="btn-sm btn-withdraw" onclick="withdrawItem(${i})">📤 Вывести</button></div></div>`).join('');
    const done=withdrawn.map(g=>`<div class="gift-item-card"><div class="gift-item-icon">${g.icon}</div><div class="gift-item-info"><div class="gift-item-name">${g.name}</div><div class="gift-item-status">✅ Выведено • ${(g.wallet||'').slice(0,8)}...</div></div></div>`).join('');
    const html=(active||'')+(done?('<div style="font-weight:600;font-size:13px;color:var(--sub);margin:12px 0 8px">📤 История выводов</div>'+done):'')||'<div style="text-align:center;padding:20px;color:#888">Нет выигрышей</div>';
    document.getElementById('winsList').innerHTML=html;document.getElementById('profileWinsList').innerHTML=html;
}

async function sellItem(i){
    const r=await fetch('/api/sell_item',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:uid,item_index:i})});
    const d=await r.json();if(d.success){ton=d.balance_ton;stars=d.balance_stars;gifts=gifts.filter((_,idx)=>idx!==i);updateUI()}
}

async function withdrawItem(i){
    const w=prompt('Введите адрес кошелька TON для вывода:');
    if(!w)return;
    const r=await fetch('/api/withdraw_item',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:uid,item_index:i,wallet:w})});
    const d=await r.json();
    if(d.success){gifts=gifts.filter((_,idx)=>idx!==i);withdrawn.push(d.item);updateUI();alert(d.message)}
}

function showPage(p){document.querySelectorAll('.page').forEach(pg=>pg.classList.remove('active'));const el=document.getElementById('page-'+p);if(el)el.classList.add('active')}
function navigate(p){if(isSpinning)return;showPage(p);document.getElementById('topbarMain').style.display='flex';document.getElementById('topbarCase').style.display='none';currentCase=null;document.querySelectorAll('.nav-btn').forEach(b=>b.classList.remove('active'));if(event&&event.target){const btn=event.target.closest('.nav-btn');if(btn)btn.classList.add('active')}}
function profileTab(t){document.querySelectorAll('#page-profile .tab-btn').forEach(b=>b.classList.remove('active'));document.querySelectorAll('#page-profile .tab-content').forEach(c=>c.classList.remove('active'));if(event&&event.target)event.target.classList.add('active');const el=document.getElementById('ptab-'+t);if(el)el.classList.add('active')}
async function setLang(l){await fetch('/api/language',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:uid,language:l})});alert(l==='ru'?'Русский':'English')}

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
