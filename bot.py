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
# КОНФИГУРАЦИЯ (ВСЁ ЗАМЕНЕНО)
# =================================================================
BOT_TOKEN = "8978316248:AAF4n6jG5gr4quppre6H1NB7U9LjEjnESqs"
ADMIN_ID = 7753887058
TON_WALLET = "UQDRRRGutl_ccP25XcwbOK-RN2UXuvE1_GFoerlaIDvmwO7I"
TONCENTER_API_KEY = "12237ee2c684a00cd473582230a4d9efea8b51b6baf2322883e4ef52f5d34390"
TONCENTER_URL = "https://toncenter.com/api/v2"

RENDER_URL = os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'syndrome-bot-9.onrender.com')
WEBAPP_URL = "https://syndrome-bot-12.onrender.com"
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
BOT_USERNAME = "nft_takes_gifts_bot"

logger.info(f"🚀 Starting bot @{BOT_USERNAME}")
logger.info(f"📱 WebApp: {WEBAPP_URL}")
logger.info(f"👑 Admin: {ADMIN_ID}")

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
                pending_payment_id TEXT,
                pending_amount REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                type TEXT,
                amount REAL,
                currency TEXT,
                tx_hash TEXT,
                status TEXT DEFAULT 'completed',
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
    logger.info("✅ Database ready")

# =================================================================
# TON ПРОВЕРКА ПЛАТЕЖЕЙ
# =================================================================
def verify_ton_transaction(wallet_address, comment, expected_amount=None, hours=24):
    """Проверка транзакции через TON Center API"""
    try:
        params = {
            'address': wallet_address,
            'limit': 50,
            'api_key': TONCENTER_API_KEY
        }
        r = requests.get(f"{TONCENTER_URL}/getTransactions", params=params, timeout=10)
        if r.status_code != 200:
            return None
        
        data = r.json()
        if not data.get('ok'):
            return None
        
        cutoff = datetime.now() - timedelta(hours=hours)
        
        for tx in data.get('result', []):
            in_msg = tx.get('in_msg', {})
            if not in_msg:
                continue
            
            source = in_msg.get('source', '')
            if source == wallet_address:
                continue
            
            value = int(in_msg.get('value', 0)) / 1_000_000_000
            msg = in_msg.get('message', '')
            
            if comment.upper() in msg.upper():
                tx_time = datetime.fromtimestamp(tx.get('utime', 0))
                if tx_time > cutoff:
                    if expected_amount and value < expected_amount:
                        continue
                    return {
                        'hash': tx.get('hash', ''),
                        'amount': value,
                        'from': source,
                        'time': tx_time.isoformat()
                    }
        return None
    except Exception as e:
        logger.error(f"TON check error: {e}")
        return None

# =================================================================
# TELEGRAM API
# =================================================================
def tg_request(method, data=None):
    try:
        r = requests.post(f"{TELEGRAM_API}/{method}", json=data or {}, timeout=10)
        return r.json()
    except:
        return None

def tg_send(chat_id, text, keyboard=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if keyboard:
        data["reply_markup"] = json.dumps(keyboard)
    return tg_request("sendMessage", data)

def tg_edit(chat_id, msg_id, text, keyboard=None):
    data = {"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": "HTML"}
    if keyboard:
        data["reply_markup"] = json.dumps(keyboard)
    return tg_request("editMessageText", data)

def tg_answer(cb_id, text=""):
    return tg_request("answerCallbackQuery", {"callback_query_id": cb_id, "text": text})

def generate_payment_id(user_id):
    return hashlib.sha256(f"{user_id}{time.time()}{random.randint(0,9999)}".encode()).hexdigest()[:16].upper()

# =================================================================
# КЛАВИАТУРЫ
# =================================================================
def menu_kb():
    return {"inline_keyboard": [
        [{"text": "🎰 ЗАПУСТИТЬ SYNDROME CASINO", "web_app": {"url": WEBAPP_URL}}],
        [{"text": "💎 ПОПОЛНИТЬ TON", "callback_data": "dep_ton"}],
        [{"text": "⭐ ПОПОЛНИТЬ STARS", "callback_data": "dep_stars"}],
        [{"text": "💼 ПРОФИЛЬ", "callback_data": "profile"}]
    ]}

def pay_check_kb(payment_id):
    return {"inline_keyboard": [
        [{"text": "✅ ПРОВЕРИТЬ ОПЛАТУ", "callback_data": f"check_{payment_id}"}],
        [{"text": "🔄 НОВЫЙ КОД", "callback_data": "dep_ton"}],
        [{"text": "🏠 МЕНЮ", "callback_data": "menu"}]
    ]}

def back_kb():
    return {"inline_keyboard": [[{"text": "🏠 ГЛАВНОЕ МЕНЮ", "callback_data": "menu"}]]}

# =================================================================
# ОБРАБОТЧИКИ
# =================================================================
def handle_start(chat_id, user):
    user_id = user["id"]
    username = user.get("username", f"user_{user_id}")
    first_name = user.get("first_name", "Player")
    
    with db_connect() as conn:
        conn.execute(
            'INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)',
            (user_id, username, first_name)
        )
    
    tg_send(chat_id,
        "🔥 <b>SYNDROME CASINO</b> 🔥\n\n"
        "🎰 Слоты, Рулетка, Кости, Блэкджек\n"
        "🎁 Подарки Telegram\n"
        "🖼️ NFT Кейсы (20 TON)\n"
        "💎 TON + ⭐ Stars\n\n"
        "<b>👇 НАЖМИ КНОПКУ НИЖЕ!</b>",
        menu_kb()
    )

def handle_deposit_ton(callback, chat_id, msg_id, user_id):
    tg_answer(callback["id"])
    
    payment_id = generate_payment_id(user_id)
    with db_connect() as conn:
        conn.execute(
            'UPDATE users SET pending_payment_id=?, pending_amount=0 WHERE user_id=?',
            (payment_id, user_id)
        )
    
    tg_edit(chat_id, msg_id,
        f"💎 <b>ПОПОЛНЕНИЕ TON</b>\n\n"
        f"📤 Кошелёк:\n<code>{TON_WALLET}</code>\n\n"
        f"📝 Код:\n<code>{payment_id}</code>\n\n"
        f"⚠️ Мин: <b>1 TON</b>\n"
        f"⚠️ Укажите код в комментарии!",
        pay_check_kb(payment_id)
    )

def handle_check_payment(callback, chat_id, msg_id, user_id, payment_id):
    """РЕАЛЬНАЯ ПРОВЕРКА ПЛАТЕЖА"""
    tg_answer(callback["id"], "🔍 Проверяю блокчейн TON...")
    
    result = verify_ton_transaction(TON_WALLET, payment_id)
    
    if result:
        amount = result['amount']
        with db_connect() as conn:
            conn.execute(
                'UPDATE users SET balance_ton=balance_ton+?, total_deposited_ton=total_deposited_ton+?, pending_payment_id=NULL WHERE user_id=?',
                (amount, amount, user_id)
            )
            conn.execute(
                'INSERT INTO transactions (user_id, type, amount, currency, tx_hash) VALUES (?,?,?,?,?)',
                (user_id, 'deposit_ton', amount, 'TON', result['hash'][:20])
            )
        
        tg_edit(chat_id, msg_id,
            f"✅ <b>ПЛАТЕЖ ЗАЧИСЛЕН!</b>\n\n"
            f"💰 +{amount:.4f} TON\n"
            f"🔗 {result['hash'][:20]}...\n\n"
            f"🎰 Играйте в казино!",
            {"inline_keyboard": [[{"text": "🎰 ИГРАТЬ", "web_app": {"url": WEBAPP_URL}}]]}
        )
        
        # Уведомление админу
        tg_send(ADMIN_ID, f"💰 <b>+{amount:.4f} TON</b> от {user_id}")
    else:
        tg_edit(chat_id, msg_id,
            "❌ <b>ПЛАТЕЖ НЕ НАЙДЕН</b>\n\n"
            "• Проверьте код в комментарии\n"
            "• Транзакция идёт до 5 минут\n"
            "• Минимум: 1 TON",
            pay_check_kb(payment_id)
        )

def handle_profile(callback, chat_id, msg_id, user_id, first_name):
    tg_answer(callback["id"])
    
    with db_connect() as conn:
        row = conn.execute(
            'SELECT balance_ton, balance_stars, total_wins, total_games, total_deposited_ton FROM users WHERE user_id=?',
            (user_id,)
        ).fetchone()
    
    if row:
        ton, stars, wins, games, dep = row
        wr = round((wins/games)*100) if games > 0 else 0
        
        tg_edit(chat_id, msg_id,
            f"💼 <b>ПРОФИЛЬ {first_name}</b>\n\n"
            f"💎 TON: <b>{ton:.4f}</b>\n"
            f"⭐ Stars: <b>{stars}</b>\n"
            f"📥 Пополнено: <b>{dep:.2f} TON</b>\n"
            f"🏆 Побед: <b>{wins}</b> | 🎮 Игр: <b>{games}</b>\n"
            f"📈 Win Rate: <b>{wr}%</b>",
            {"inline_keyboard": [
                [{"text": "💎 ВЫВЕСТИ TON", "callback_data": "wd_ton"}],
                [{"text": "🎰 ИГРАТЬ", "web_app": {"url": WEBAPP_URL}}],
                [{"text": "🏠 МЕНЮ", "callback_data": "menu"}]
            ]}
        )

def handle_withdraw(chat_id, user_id, text):
    try:
        parts = text.split()
        amount = float(parts[1])
        wallet = parts[2] if len(parts) > 2 else None
        
        if not wallet: return tg_send(chat_id, "❌ /withdraw СУММА КОШЕЛЕК")
        if amount < 10: return tg_send(chat_id, "❌ Мин: 10 TON")
        
        with db_connect() as conn:
            row = conn.execute('SELECT balance_ton FROM users WHERE user_id=?', (user_id,)).fetchone()
            if not row or row[0] < amount: return tg_send(chat_id, "❌ Недостаточно!")
            
            conn.execute('UPDATE users SET balance_ton=balance_ton-? WHERE user_id=?', (amount, user_id))
            conn.execute('INSERT INTO withdrawals (user_id, amount, wallet) VALUES (?,?,?)', (user_id, amount, wallet))
        
        tg_send(chat_id, f"✅ Заявка на <b>{amount} TON</b> создана!")
        tg_send(ADMIN_ID, f"📤 ВЫВОД: {amount} TON\n👤 {user_id}\n📤 {wallet}")
    except:
        tg_send(chat_id, "❌ /withdraw СУММА КОШЕЛЕК")

# =================================================================
# ДАННЫЕ ДЛЯ ПОДАРКОВ И NFT
# =================================================================
TELEGRAM_GIFTS = [
    {"name": "🧸 Мишка", "icon": "🧸", "rarity": "common", "chance": 35, "price_ton": 0.5},
    {"name": "❤️ Сердечко", "icon": "❤️", "rarity": "common", "chance": 30, "price_ton": 0.3},
    {"name": "🌹 Роза", "icon": "🌹", "rarity": "common", "chance": 25, "price_ton": 0.4},
    {"name": "💎 Кристалл", "icon": "💎", "rarity": "rare", "chance": 15, "price_ton": 1.5},
    {"name": "👑 Корона", "icon": "👑", "rarity": "rare", "chance": 10, "price_ton": 2.0},
    {"name": "🌟 Звезда", "icon": "🌟", "rarity": "epic", "chance": 5, "price_ton": 5.0},
    {"name": "🐉 Дракон", "icon": "🐉", "rarity": "legendary", "chance": 1, "price_ton": 50.0},
    {"name": "🦄 Единорог", "icon": "🦄", "rarity": "mythic", "chance": 0.5, "price_ton": 200.0},
]

NFT_ITEMS = [
    {"name": "Bored Ape #3847", "image": "🐵", "rarity": "legendary", "chance": 0.5, "floor_price": 500},
    {"name": "CryptoPunk #9281", "image": "👾", "rarity": "legendary", "chance": 0.3, "floor_price": 800},
    {"name": "TON DNS Diamond", "image": "💠", "rarity": "epic", "chance": 3, "floor_price": 100},
    {"name": "TON Punks #442", "image": "🤖", "rarity": "rare", "chance": 8, "floor_price": 50},
    {"name": "Fragment Number", "image": "📞", "rarity": "rare", "chance": 10, "floor_price": 30},
    {"name": "TON Diamonds", "image": "💎", "rarity": "common", "chance": 15, "floor_price": 20},
    {"name": "Telegram Username NFT", "image": "@", "rarity": "common", "chance": 20, "floor_price": 15},
    {"name": "Anonymous Number", "image": "#️⃣", "rarity": "common", "chance": 25, "floor_price": 10},
]

# =================================================================
# FLASK
# =================================================================
flask_app = Flask(__name__)

@flask_app.route('/')
def webapp():
    return render_template_string(HTML_TEMPLATE)

@flask_app.route('/api/user/<int:user_id>')
def api_user(user_id):
    try:
        with db_connect() as conn:
            row = conn.execute(
                'SELECT balance_ton, balance_stars, total_wins, total_games, total_deposited_ton, nft_items, gift_items FROM users WHERE user_id=?',
                (user_id,)
            ).fetchone()
        if row:
            return jsonify({
                'balance_ton': row[0], 'balance_stars': row[1],
                'total_wins': row[2], 'total_games': row[3],
                'deposited_ton': row[4],
                'nft_items': json.loads(row[5]) if row[5] else [],
                'gift_items': json.loads(row[6]) if row[6] else []
            })
    except:
        pass
    return jsonify({'balance_ton': 100, 'balance_stars': 1000, 'total_wins': 0, 'total_games': 0, 'deposited_ton': 0, 'nft_items': [], 'gift_items': []})

@flask_app.route('/api/game', methods=['POST'])
def api_game():
    data = request.json
    user_id = data.get('user_id')
    game_type = data.get('game_type')
    bet = float(data.get('bet_amount', 0))
    currency = data.get('currency', 'TON')
    
    try:
        with db_connect() as conn:
            col = 'balance_ton' if currency == 'TON' else 'balance_stars'
            row = conn.execute(f'SELECT {col} FROM users WHERE user_id=?', (user_id,)).fetchone()
            if not row or row[0] < bet:
                return jsonify({'error': 'Недостаточно средств!'}), 400
            
            win = random.choices([True, False], weights=[30, 70])[0]
            mult, prize = 0, 0
            
            if win:
                mults = [1.5, 2, 3, 5, 10]
                wgts = [30, 30, 25, 10, 5]
                r = random.random() * sum(wgts)
                for i, m in enumerate(mults):
                    r -= wgts[i]
                    if r <= 0: mult = m; break
                prize = bet * mult
            
            if win:
                conn.execute(
                    f'UPDATE users SET {col}={col}+?, total_wins=total_wins+1, total_games=total_games+1 WHERE user_id=?',
                    (prize - bet, user_id)
                )
            else:
                conn.execute(
                    f'UPDATE users SET {col}={col}-?, total_games=total_games+1 WHERE user_id=?',
                    (bet, user_id)
                )
            
            return jsonify({'win': win, 'amount': prize, 'multiplier': mult})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@flask_app.route('/api/gift', methods=['POST'])
def api_gift():
    data = request.json
    user_id = data.get('user_id')
    
    items = []
    for g in TELEGRAM_GIFTS:
        items.extend([g] * int(g['chance'] * 10))
    
    gift = random.choice(items)
    
    with db_connect() as conn:
        row = conn.execute('SELECT gift_items FROM users WHERE user_id=?', (user_id,)).fetchone()
        gifts = json.loads(row[0]) if row and row[0] else []
        gifts.append(gift['name'])
        conn.execute('UPDATE users SET gift_items=? WHERE user_id=?', (json.dumps(gifts), user_id))
    
    return jsonify({'gift': gift})

@flask_app.route('/api/nft', methods=['POST'])
def api_nft():
    data = request.json
    user_id = data.get('user_id')
    
    with db_connect() as conn:
        row = conn.execute('SELECT balance_ton FROM users WHERE user_id=?', (user_id,)).fetchone()
        if not row or row[0] < 20:
            return jsonify({'error': 'Недостаточно TON! Нужно 20 TON'}), 400
        
        items = []
        for n in NFT_ITEMS:
            items.extend([n] * int(n['chance'] * 10))
        
        nft = random.choice(items)
        
        conn.execute('UPDATE users SET balance_ton=balance_ton-20 WHERE user_id=?', (user_id,))
        row2 = conn.execute('SELECT nft_items FROM users WHERE user_id=?', (user_id,)).fetchone()
        nfts = json.loads(row2[0]) if row2 and row2[0] else []
        nfts.append(nft['name'])
        conn.execute('UPDATE users SET nft_items=? WHERE user_id=?', (json.dumps(nfts), user_id))
    
    return jsonify({'nft': nft})

@flask_app.route('/api/gifts/list')
def api_gifts_list():
    return jsonify(TELEGRAM_GIFTS)

@flask_app.route('/api/nft/list')
def api_nft_list():
    return jsonify(NFT_ITEMS)

@flask_app.route('/api/check_payment', methods=['POST'])
def api_check_payment():
    data = request.json
    user_id = data.get('user_id')
    payment_id = data.get('payment_id')
    
    result = verify_ton_transaction(TON_WALLET, payment_id)
    
    if result:
        amount = result['amount']
        with db_connect() as conn:
            conn.execute(
                'UPDATE users SET balance_ton=balance_ton+?, total_deposited_ton=total_deposited_ton+?, pending_payment_id=NULL WHERE user_id=?',
                (amount, amount, user_id)
            )
        return jsonify({'success': True, 'amount': amount, 'hash': result['hash'][:20]})
    
    return jsonify({'success': False, 'message': 'Платеж не найден'})

@flask_app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = request.get_json()
        
        if "message" in update:
            msg = update["message"]
            chat_id = msg["chat"]["id"]
            user = msg["from"]
            user_id = user["id"]
            
            if "text" in msg:
                text = msg["text"]
                if text.startswith("/start"):
                    handle_start(chat_id, user)
                elif text.startswith("/withdraw"):
                    handle_withdraw(chat_id, user_id, text)
            
            elif "successful_payment" in msg:
                payment = msg["successful_payment"]
                if payment.get("invoice_payload") == "stars_deposit":
                    stars = payment["total_amount"]
                    with db_connect() as conn:
                        conn.execute(
                            'UPDATE users SET balance_stars=balance_stars+?, balance_ton=balance_ton+? WHERE user_id=?',
                            (stars, stars * 0.1, user_id)
                        )
                    tg_send(chat_id, f"✅ +{stars} Stars!")
        
        elif "callback_query" in update:
            cb = update["callback_query"]
            chat_id = cb["message"]["chat"]["id"]
            msg_id = cb["message"]["message_id"]
            user_id = cb["from"]["id"]
            first_name = cb["from"].get("first_name", "Player")
            data = cb.get("data", "")
            
            if data == "dep_ton":
                handle_deposit_ton(cb, chat_id, msg_id, user_id)
            elif data == "dep_stars":
                tg_answer(cb["id"], "⭐ Используйте кнопку в приложении")
            elif data == "profile":
                handle_profile(cb, chat_id, msg_id, user_id, first_name)
            elif data == "wd_ton":
                tg_edit(chat_id, msg_id, "Отправьте:\n<code>/withdraw СУММА КОШЕЛЕК</code>", back_kb())
                tg_answer(cb["id"])
            elif data == "menu":
                tg_edit(chat_id, msg_id, "🔥 <b>SYNDROME CASINO</b>", menu_kb())
                tg_answer(cb["id"])
            elif data.startswith("check_"):
                pid = data.replace("check_", "")
                handle_check_payment(cb, chat_id, msg_id, user_id, pid)
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
# HTML ШАБЛОН (НЕОНОВЫЙ ДИЗАЙН + ПОДАРКИ + NFT)
# =================================================================
HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="theme-color" content="#0a0a1a">
    <title>SYNDROME CASINO</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Inter:wght@300;400;600;700;900&display=swap');
        
        :root {
            --bg: #0a0a1a;
            --card: #12122a;
            --neon-pink: #ff2d95;
            --neon-blue: #00d4ff;
            --neon-purple: #b347ea;
            --neon-gold: #ffd700;
            --neon-green: #00ff88;
            --glass: rgba(255,255,255,0.05);
            --border: rgba(255,255,255,0.1);
        }
        
        *{margin:0;padding:0;box-sizing:border-box}
        body{background:var(--bg);color:#fff;font-family:'Inter',sans-serif;min-height:100vh;overflow-x:hidden}
        
        .bg-anim{position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0}
        .orb{position:absolute;border-radius:50%;filter:blur(80px);opacity:0.15;animation:floatOrb 8s infinite}
        .orb:nth-child(1){width:300px;height:300px;background:var(--neon-purple);top:10%;left:-100px;animation-delay:0s}
        .orb:nth-child(2){width:200px;height:200px;background:var(--neon-blue);bottom:20%;right:-50px;animation-delay:3s}
        .orb:nth-child(3){width:250px;height:250px;background:var(--neon-pink);top:50%;left:50%;animation-delay:6s}
        @keyframes floatOrb{0%,100%{transform:translate(0,0) scale(1)}33%{transform:translate(30px,-30px) scale(1.1)}66%{transform:translate(-20px,20px) scale(0.9)}}
        
        .app{position:relative;z-index:1;max-width:480px;margin:0 auto;padding:16px;padding-bottom:100px}
        
        .header{display:flex;align-items:center;gap:12px;margin-bottom:16px;padding:16px;background:var(--card);border:1px solid var(--border);border-radius:20px}
        .avatar{width:48px;height:48px;border-radius:50%;background:linear-gradient(135deg,var(--neon-purple),var(--neon-pink));display:flex;align-items:center;justify-content:center;font-size:22px;font-weight:900;box-shadow:0 0 20px rgba(179,71,234,0.4)}
        .username{font-weight:700;font-size:15px}
        .vip{font-size:11px;color:var(--neon-gold)}
        
        .balance-panel{position:relative;margin-bottom:16px;padding:20px;border-radius:24px;background:linear-gradient(135deg,rgba(179,71,234,0.15),rgba(0,212,255,0.1));border:1px solid rgba(179,71,234,0.3);overflow:hidden}
        .balance-row{display:flex;justify-content:space-around;position:relative;z-index:1}
        .bal-item{text-align:center}
        .bal-amount{font-family:'Orbitron',monospace;font-size:26px;font-weight:900;background:linear-gradient(135deg,var(--neon-gold),#ffaa00);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
        .bal-label{font-size:10px;text-transform:uppercase;color:#888;margin-top:4px;letter-spacing:1px}
        
        .tabs{display:flex;gap:4px;margin-bottom:16px;padding:4px;background:var(--card);border-radius:16px}
        .tab{flex:1;padding:10px;text-align:center;border-radius:12px;cursor:pointer;font-weight:600;font-size:13px;color:#888;border:none;background:transparent;transition:all 0.3s}
        .tab.active{background:linear-gradient(135deg,var(--neon-purple),var(--neon-pink));color:#fff;box-shadow:0 0 20px rgba(255,45,149,0.3)}
        
        .tab-content{display:none}
        .tab-content.active{display:block}
        
        .section-title{font-size:14px;font-weight:700;margin-bottom:12px;display:flex;align-items:center;gap:8px;color:var(--neon-blue)}
        .section-title::after{content:'';flex:1;height:1px;background:var(--border)}
        
        .games-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:16px}
        .game-card{position:relative;padding:16px;background:var(--card);border:1px solid var(--border);border-radius:16px;text-align:center;cursor:pointer;transition:all 0.3s}
        .game-card:hover{transform:translateY(-3px);border-color:var(--neon-purple);box-shadow:0 10px 30px rgba(179,71,234,0.2)}
        .game-card.disabled{opacity:0.4;pointer-events:none}
        .game-icon{font-size:36px;margin-bottom:6px}
        .game-name{font-size:13px;font-weight:700}
        .game-bet{font-size:10px;color:var(--neon-gold);margin-top:2px}
        .hot-badge{position:absolute;top:8px;right:8px;padding:3px 7px;border-radius:6px;font-size:9px;font-weight:700;background:var(--neon-pink);animation:pulse 2s infinite}
        @keyframes pulse{0%,100%{transform:scale(1)}50%{transform:scale(1.1)}}
        
        .gift-section,.nft-section{margin-bottom:16px;padding:16px;background:var(--card);border:1px solid var(--border);border-radius:16px}
        .gift-grid{display:flex;gap:8px;overflow-x:auto;padding:8px 0}
        .gift-item{flex-shrink:0;width:70px;text-align:center;padding:10px;background:var(--glass);border-radius:12px;border:1px solid var(--border)}
        .gift-icon{font-size:30px}
        .gift-chance{font-size:9px;color:var(--neon-gold);margin-top:2px}
        
        .neon-btn{width:100%;padding:14px;border:none;border-radius:14px;font-weight:700;font-size:14px;cursor:pointer;text-transform:uppercase;letter-spacing:1px;transition:all 0.3s;color:#fff}
        .btn-purple{background:linear-gradient(135deg,var(--neon-purple),var(--neon-pink));box-shadow:0 0 25px rgba(255,45,149,0.3)}
        .btn-gold{background:linear-gradient(135deg,var(--neon-gold),#ffaa00);color:#000}
        .btn-blue{background:linear-gradient(135deg,var(--neon-blue),#0099ff)}
        .neon-btn:hover{transform:translateY(-2px)}
        
        .modal{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.9);z-index:1000;align-items:center;justify-content:center;backdrop-filter:blur(10px)}
        .modal.active{display:flex}
        .modal-content{width:90%;max-width:380px;padding:24px;background:var(--card);border:1px solid var(--border);border-radius:24px;text-align:center;position:relative;max-height:80vh;overflow-y:auto}
        .modal-close{position:absolute;top:12px;right:12px;width:32px;height:32px;border-radius:50%;border:none;background:rgba(255,255,255,0.1);color:#fff;font-size:16px;cursor:pointer}
        .modal-title{font-family:'Orbitron',monospace;font-size:20px;font-weight:900;margin-bottom:16px;background:linear-gradient(135deg,var(--neon-gold),var(--neon-pink));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
        
        .slot-reels{display:flex;gap:10px;justify-content:center;margin:20px 0}
        .reel{width:70px;height:70px;display:flex;align-items:center;justify-content:center;font-size:32px;background:var(--glass);border:2px solid var(--border);border-radius:14px}
        .reel.spin{animation:reelAnim 0.1s infinite;border-color:var(--neon-gold)}
        @keyframes reelAnim{0%{transform:translateY(-8px)}50%{transform:translateY(8px)}100%{transform:translateY(-8px)}}
        
        .result-win{color:var(--neon-green);font-weight:700;padding:10px;border-radius:10px;background:rgba(0,255,136,0.1)}
        .result-lose{color:var(--neon-pink);font-weight:700;padding:10px;border-radius:10px;background:rgba(255,45,149,0.1)}
        
        .amount-input{width:100%;padding:14px;background:var(--glass);border:2px solid var(--border);border-radius:14px;color:#fff;font-size:20px;font-weight:700;text-align:center;outline:none;font-family:'Orbitron',monospace}
        .amount-input:focus{border-color:var(--neon-purple)}
        
        .toast{position:fixed;top:20px;left:50%;transform:translateX(-50%);padding:14px 20px;background:var(--card);border:1px solid var(--border);border-radius:14px;z-index:2000;font-weight:600;font-size:13px;text-align:center;max-width:90%;white-space:pre-line;box-shadow:0 10px 30px rgba(0,0,0,0.5)}
        
        .nft-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:12px 0}
        .nft-card{padding:12px;background:var(--glass);border:1px solid var(--border);border-radius:12px;text-align:center}
        .nft-rarity{font-size:9px;text-transform:uppercase;letter-spacing:1px;margin-top:4px}
        .legendary{color:#ff8c00}.epic{color:var(--neon-purple)}.rare{color:var(--neon-blue)}.common{color:#888}
    </style>
</head>
<body>
    <div class="bg-anim"><div class="orb"></div><div class="orb"></div><div class="orb"></div></div>
    
    <div class="app">
        <div class="header">
            <div class="avatar" id="avatar">S</div>
            <div style="flex:1"><div class="username" id="username">Player</div><div class="vip">👑 VIP</div></div>
            <span style="font-size:22px">💎</span>
        </div>
        
        <div class="balance-panel">
            <div class="balance-row">
                <div class="bal-item"><div class="bal-amount" id="tonBal">0.00</div><div class="bal-label">TON</div></div>
                <div class="bal-item"><div class="bal-amount" id="starsBal">0</div><div class="bal-label">STARS</div></div>
            </div>
        </div>
        
        <div class="tabs">
            <button class="tab active" onclick="switchTab('games')">🎰 ИГРЫ</button>
            <button class="tab" onclick="switchTab('gifts')">🎁 ПОДАРКИ</button>
            <button class="tab" onclick="switchTab('nft')">🖼️ NFT</button>
            <button class="tab" onclick="switchTab('profile')">💼 ПРОФИЛЬ</button>
        </div>
        
        <div class="tab-content active" id="tab-games">
            <div class="games-grid">
                <div class="game-card" id="card-slots" onclick="openGame('slots')"><div class="hot-badge">HOT</div><div class="game-icon">🎰</div><div class="game-name">СЛОТЫ</div><div class="game-bet" id="slotsBet">1 TON</div></div>
                <div class="game-card" id="card-roulette" onclick="openGame('roulette')"><div class="game-icon">🎡</div><div class="game-name">РУЛЕТКА</div><div class="game-bet" id="rouletteBet">2 TON</div></div>
                <div class="game-card" id="card-dice" onclick="openGame('dice')"><div class="game-icon">🎲</div><div class="game-name">КОСТИ</div><div class="game-bet" id="diceBet">1.5 TON</div></div>
                <div class="game-card" id="card-blackjack" onclick="openGame('blackjack')"><div class="game-icon">🃏</div><div class="game-name">БЛЭКДЖЕК</div><div class="game-bet" id="blackjackBet">5 TON</div></div>
            </div>
        </div>
        
        <div class="tab-content" id="tab-gifts">
            <div class="gift-section">
                <div class="section-title">🎁 БЕСПЛАТНЫЙ ПОДАРОК</div>
                <p style="font-size:12px;color:#888;margin-bottom:12px">Крутите бесплатно раз в день!</p>
                <button class="neon-btn btn-purple" onclick="openFreeGift()">🎁 ОТКРЫТЬ ПОДАРОК</button>
            </div>
            <div class="gift-section">
                <div class="section-title">📊 ДОСТУПНЫЕ ПОДАРКИ</div>
                <div class="gift-grid" id="giftList"></div>
            </div>
        </div>
        
        <div class="tab-content" id="tab-nft">
            <div class="nft-section">
                <div class="section-title">🖼️ NFT КЕЙС (20 TON)</div>
                <p style="font-size:12px;color:#888;margin-bottom:12px">Открывайте NFT с реальными шансами!</p>
                <button class="neon-btn btn-gold" onclick="openNFTCase()">🔓 ОТКРЫТЬ КЕЙС (20 TON)</button>
            </div>
            <div class="nft-section">
                <div class="section-title">📊 ДОСТУПНЫЕ NFT</div>
                <div class="nft-grid" id="nftList"></div>
            </div>
        </div>
        
        <div class="tab-content" id="tab-profile">
            <div class="gift-section">
                <div class="section-title">💼 МОЙ ПРОФИЛЬ</div>
                <div style="margin:8px 0"><span style="color:#888">💎 TON:</span> <b id="profTon">0</b></div>
                <div style="margin:8px 0"><span style="color:#888">⭐ Stars:</span> <b id="profStars">0</b></div>
                <div style="margin:8px 0"><span style="color:#888">🏆 Побед:</span> <b id="profWins">0</b></div>
                <div style="margin:8px 0"><span style="color:#888">🎮 Игр:</span> <b id="profGames">0</b></div>
                <div style="margin:8px 0"><span style="color:#888">🎁 Подарков:</span> <b id="profGifts">0</b></div>
                <div style="margin:8px 0"><span style="color:#888">🖼️ NFT:</span> <b id="profNFTs">0</b></div>
            </div>
            <button class="neon-btn btn-purple" onclick="handleDeposit()">💰 ПОПОЛНИТЬ</button>
            <button class="neon-btn btn-blue" onclick="handleWithdraw()" style="margin-top:8px">💎 ВЫВЕСТИ</button>
        </div>
    </div>
    
    <div class="modal" id="slotsModal"><div class="modal-content">
        <button class="modal-close" onclick="closeModal()">✕</button>
        <div class="modal-title">🎰 СЛОТЫ</div>
        <div class="slot-reels"><div class="reel" id="r1">🍒</div><div class="reel" id="r2">🍋</div><div class="reel" id="r3">💎</div></div>
        <div id="slotsResult"></div>
        <button class="neon-btn btn-purple" onclick="spinSlots()">🎰 КРУТИТЬ</button>
    </div></div>
    
    <div class="modal" id="giftModal"><div class="modal-content">
        <button class="modal-close" onclick="closeModal()">✕</button>
        <div class="modal-title">🎁 ПОДАРОК</div>
        <div style="font-size:80px;margin:20px 0" id="giftResult">🎁</div>
        <div id="giftText" style="font-weight:700;font-size:18px"></div>
    </div></div>
    
    <div class="modal" id="nftModal"><div class="modal-content">
        <button class="modal-close" onclick="closeModal()">✕</button>
        <div class="modal-title">🖼️ NFT КЕЙС</div>
        <div style="font-size:80px;margin:20px 0" id="nftResult">🖼️</div>
        <div id="nftText" style="font-weight:700;font-size:18px"></div>
    </div></div>
    
    <div class="toast" id="toast" style="display:none"></div>

    <script>
        const tg=window.Telegram.WebApp;tg.expand();tg.ready();
        const user=tg.initDataUnsafe?.user||{};
        const userId=user.id||123456789;
        document.getElementById('username').textContent=user.first_name||'Player';
        document.getElementById('avatar').textContent=(user.first_name||'P')[0].toUpperCase();
        
        let ton=100,stars=1000,wins=0,games=0,gifts=[],nfts=[],spinning=false;
        
        function toast(m){const t=document.getElementById('toast');t.textContent=m;t.style.display='block';setTimeout(()=>t.style.display='none',3000)}
        
        async function load(){
            try{const r=await fetch('/api/user/'+userId);const d=await r.json();
                ton=d.balance_ton||100;stars=d.balance_stars||1000;wins=d.total_wins||0;games=d.total_games||0;
                gifts=d.gift_items||[];nfts=d.nft_items||[];updateUI()}catch(e){updateUI()}
        }
        
        function updateUI(){
            document.getElementById('tonBal').textContent=ton.toFixed(2);
            document.getElementById('starsBal').textContent=stars;
            document.getElementById('profTon').textContent=ton.toFixed(2);
            document.getElementById('profStars').textContent=stars;
            document.getElementById('profWins').textContent=wins;
            document.getElementById('profGames').textContent=games;
            document.getElementById('profGifts').textContent=gifts.length;
            document.getElementById('profNFTs').textContent=nfts.length;
            ['slots','roulette','dice','blackjack'].forEach(g=>{
                const c=document.getElementById('card-'+g);
                const bets={slots:1,roulette:2,dice:1.5,blackjack:5};
                ton<bets[g]?c.classList.add('disabled'):c.classList.remove('disabled')
            })
        }
        
        function switchTab(t){
            document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));
            event.target.classList.add('active');
            document.querySelectorAll('.tab-content').forEach(c=>c.classList.remove('active'));
            document.getElementById('tab-'+t).classList.add('active');
            if(t==='gifts')loadGiftList();
            if(t==='nft')loadNFTList();
        }
        
        function openGame(g){document.getElementById(g+'Modal').classList.add('active')}
        function closeModal(){document.querySelectorAll('.modal').forEach(m=>m.classList.remove('active'));spinning=false}
        
        async function loadGiftList(){
            const r=await fetch('/api/gifts/list');const data=await r.json();
            document.getElementById('giftList').innerHTML=data.map(g=>`<div class="gift-item"><div class="gift-icon">${g.icon}</div><div style="font-size:10px;font-weight:600">${g.name.split(' ')[0]}</div><div class="gift-chance">${g.chance}%</div></div>`).join('')
        }
        
        async function loadNFTList(){
            const r=await fetch('/api/nft/list');const data=await r.json();
            document.getElementById('nftList').innerHTML=data.map(n=>`<div class="nft-card"><div style="font-size:28px">${n.image}</div><div style="font-size:11px;font-weight:600">${n.name}</div><div class="nft-rarity ${n.rarity}">${n.rarity} • ${n.chance}%</div><div style="font-size:10px;color:#888">Floor: ${n.floor_price} TON</div></div>`).join('')
        }
        
        async function openFreeGift(){
            const r=await fetch('/api/gift',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:userId})});
            const d=await r.json();
            document.getElementById('giftResult').textContent=d.gift.icon;
            document.getElementById('giftText').textContent=d.gift.name+' ('+d.gift.rarity+')';
            document.getElementById('giftModal').classList.add('active');
            gifts.push(d.gift.name);updateUI()
        }
        
        async function openNFTCase(){
            if(ton<20){toast('❌ Нужно 20 TON!');return}
            const r=await fetch('/api/nft',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:userId})});
            const d=await r.json();
            if(d.error){toast(d.error);return}
            document.getElementById('nftResult').textContent=d.nft.image;
            document.getElementById('nftText').innerHTML=d.nft.name+'<br><span class="'+d.nft.rarity+'">'+d.nft.rarity.toUpperCase()+'</span><br>Floor: '+d.nft.floor_price+' TON';
            document.getElementById('nftModal').classList.add('active');
            ton-=20;nfts.push(d.nft.name);updateUI()
        }
        
        async function spinSlots(){
            if(spinning||ton<1)return;spinning=true;
            const reels=[document.getElementById('r1'),document.getElementById('r2'),document.getElementById('r3')];
            const sym=["🍒","🍋","🔔","💎","7️⃣"];
            reels.forEach(r=>r.classList.add('spin'));
            for(let i=0;i<15;i++){reels.forEach(r=>r.textContent=sym[Math.floor(Math.random()*5)]);await new Promise(r=>setTimeout(r,80))}
            reels.forEach(r=>r.classList.remove('spin'));
            try{
                const r=await fetch('/api/game',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:userId,game_type:'slots',bet_amount:1,currency:'TON'})});
                const d=await r.json();
                if(d.win){ton+=d.amount-1;wins++;reels.forEach(r=>r.textContent='💎');document.getElementById('slotsResult').innerHTML='<div class="result-win">🎉 +'+d.amount.toFixed(2)+' TON!</div>'}
                else{ton-=1;document.getElementById('slotsResult').innerHTML='<div class="result-lose">😢 -1 TON</div>'}
                games++;updateUI();spinning=false
            }catch(e){spinning=false}
        }
        
        function handleDeposit(){tg.openTelegramLink('https://t.me/nft_takes_gifts_bot')}
        function handleWithdraw(){tg.openTelegramLink('https://t.me/nft_takes_gifts_bot');toast('Отправьте боту:\n/withdraw СУММА КОШЕЛЕК')}
        
        document.querySelectorAll('.modal').forEach(m=>m.addEventListener('click',function(e){if(e.target===this)closeModal()}));
        load();setInterval(load,30000)
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
    
    # Установка вебхука
    try:
        requests.get(f"{TELEGRAM_API}/setWebhook", params={"url": f"https://{RENDER_URL}/webhook", "drop_pending_updates": True})
        requests.post(f"{TELEGRAM_API}/setChatMenuButton", json={"menu_button": json.dumps({"type":"web_app","text":"🎰 ИГРАТЬ","web_app":{"url":WEBAPP_URL}})})
        requests.post(f"{TELEGRAM_API}/setMyCommands", json={"commands":[{"command":"start","description":"🚀 Запустить"},{"command":"withdraw","description":"💎 Вывести"}]})
        logger.info("✅ Webhook set!")
    except Exception as e:
        logger.error(f"Setup error: {e}")
    
    # Авто-пинг
    threading.Thread(target=keep_alive, daemon=True).start()
    
    port = int(os.environ.get('PORT', 8080))
    flask_app.run(host='0.0.0.0', port=port)
