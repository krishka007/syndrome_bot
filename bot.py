import json
import logging
import sqlite3
import random
import hashlib
import os
import sys
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string

# Логирование
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

# =================================================================
# КОНФИГУРАЦИЯ
# =================================================================
BOT_TOKEN = "8978316248:AAF4n6jG5gr4quppre6H1NB7U9LjEjnESqs"  # <-- СЮДА ТОКЕН!
ADMIN_ID = 7753887058  # <-- ТВОЙ TELEGRAM ID
TON_WALLET = "UQDRRRGutl_ccP25XcwbOK-RN2UXuvE1_GFoerlaIDvmwO7I"  # <-- КОШЕЛЕК
TONCENTER_API_KEY = "12237ee2c684a00cd473582230a4d9efea8b51b6baf2322883e4ef52f5d34390"  # <-- API КЛЮЧ TONCENTER
TONCENTER_URL = "https://toncenter.com/api/v2"

# URL приложения (Render даст после деплоя)
RENDER_URL = os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'localhost:8080')
WEBAPP_URL = f"https://syndrome-bot-9.onrender.com"

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

logger.info(f"🚀 Starting on: {RENDER_URL}")
logger.info(f"📱 WebApp URL: {WEBAPP_URL}")
logger.info(f"🐍 Python: {sys.version}")

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
                pending_payment_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
# TELEGRAM API ФУНКЦИИ
# =================================================================
def tg_send_message(chat_id, text, reply_markup=None, parse_mode="HTML"):
    """Отправка сообщения через Telegram API"""
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    }
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    
    try:
        r = requests.post(f"{TELEGRAM_API}/sendMessage", json=data, timeout=10)
        return r.json()
    except Exception as e:
        logger.error(f"Send message error: {e}")
        return None

def tg_answer_callback(callback_id, text=None):
    """Ответ на callback query"""
    data = {"callback_query_id": callback_id}
    if text:
        data["text"] = text
        data["show_alert"] = False
    try:
        requests.post(f"{TELEGRAM_API}/answerCallbackQuery", json=data, timeout=5)
    except:
        pass

def tg_edit_message(chat_id, message_id, text, reply_markup=None):
    """Редактирование сообщения"""
    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    
    try:
        requests.post(f"{TELEGRAM_API}/editMessageText", json=data, timeout=10)
    except Exception as e:
        logger.error(f"Edit message error: {e}")

def tg_set_webhook():
    """Установка вебхука"""
    url = f"https://{RENDER_URL}/webhook"
    try:
        r = requests.get(f"{TELEGRAM_API}/setWebhook", params={"url": url, "drop_pending_updates": True})
        logger.info(f"Webhook set: {r.json()}")
    except Exception as e:
        logger.error(f"Webhook error: {e}")

def tg_set_menu():
    """Настройка кнопки меню"""
    data = {
        "menu_button": json.dumps({
            "type": "web_app",
            "text": "🎰 ИГРАТЬ",
            "web_app": {"url": WEBAPP_URL}
        })
    }
    try:
        requests.post(f"{TELEGRAM_API}/setChatMenuButton", data=data, timeout=10)
    except:
        pass

def tg_set_commands():
    """Настройка команд бота"""
    commands = [
        {"command": "start", "description": "🚀 Запустить казино"},
        {"command": "withdraw", "description": "💎 Вывести TON"}
    ]
    try:
        requests.post(f"{TELEGRAM_API}/setMyCommands", json={"commands": commands}, timeout=10)
    except:
        pass

# =================================================================
# ГЕНЕРАЦИЯ КЛАВИАТУР
# =================================================================
def main_menu_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "🎰 ЗАПУСТИТЬ SYNDROME CASINO", "web_app": {"url": WEBAPP_URL}}],
            [{"text": "💰 ПОПОЛНИТЬ", "callback_data": "deposit_menu"}],
            [{"text": "💼 ПРОФИЛЬ", "callback_data": "profile"}]
        ]
    }

def deposit_menu_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "💎 ПОПОЛНИТЬ TON", "callback_data": "deposit_ton"}],
            [{"text": "⭐ ПОПОЛНИТЬ STARS", "callback_data": "deposit_stars"}],
            [{"text": "🏠 МЕНЮ", "callback_data": "main_menu"}]
        ]
    }

def back_to_menu_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "🏠 ГЛАВНОЕ МЕНЮ", "callback_data": "main_menu"}]
        ]
    }

# =================================================================
# ОБРАБОТЧИКИ КОМАНД И CALLBACK
# =================================================================
def handle_start(chat_id, user_id, username, first_name):
    """Обработка /start"""
    with db_connect() as conn:
        conn.execute(
            'INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)',
            (user_id, username, first_name)
        )
    
    text = (
        "🔥 <b>SYNDROME CASINO — TON & STARS CASINO</b> 🔥\n\n"
        "🎰 <b>Слоты, Рулетка, Кости, Блэкджек</b>\n"
        "💎 Пополнение: TON и Telegram Stars\n"
        "💰 Выплаты от 10 TON\n"
        "⚡ Ставки: от 1 TON / 10 Stars\n\n"
        "🎁 <b>НАЖМИ КНОПКУ НИЖЕ!</b>"
    )
    tg_send_message(chat_id, text, main_menu_keyboard())

def handle_deposit_menu(callback, chat_id, message_id):
    """Меню пополнения"""
    tg_answer_callback(callback["id"])
    text = (
        "💰 <b>ПОПОЛНЕНИЕ БАЛАНСА</b>\n\n"
        "💎 <b>TON</b> — криптовалюта\n"
        "⭐ <b>Stars</b> — Звезды Telegram\n\n"
        "Минимум: 1 TON или 10 Stars"
    )
    tg_edit_message(chat_id, message_id, text, deposit_menu_keyboard())

def handle_deposit_ton(callback, chat_id, message_id, user_id):
    """Пополнение TON"""
    tg_answer_callback(callback["id"])
    
    payment_id = hashlib.sha256(f"{user_id}{datetime.now().timestamp()}".encode()).hexdigest()[:16].upper()
    
    with db_connect() as conn:
        conn.execute('UPDATE users SET pending_payment_id = ? WHERE user_id = ?', (payment_id, user_id))
    
    keyboard = {
        "inline_keyboard": [
            [{"text": "✅ ПРОВЕРИТЬ ОПЛАТУ", "callback_data": f"check_{payment_id}"}],
            [{"text": "🔄 НОВЫЙ КОД", "callback_data": "deposit_ton"}],
            [{"text": "🏠 МЕНЮ", "callback_data": "main_menu"}]
        ]
    }
    
    text = (
        "💎 <b>ПОПОЛНЕНИЕ TON</b>\n\n"
        f"📤 Отправьте TON на кошелёк:\n\n"
        f"<code>{TON_WALLET}</code>\n\n"
        f"📝 <b>КОД В КОММЕНТАРИИ:</b>\n"
        f"<code>{payment_id}</code>\n\n"
        f"⚠️ Минимум: <b>1 TON</b>\n"
        f"Без кода платёж НЕ зачислится!"
    )
    tg_edit_message(chat_id, message_id, text, keyboard)

def handle_profile(callback, chat_id, message_id, user_id, first_name):
    """Профиль игрока"""
    tg_answer_callback(callback["id"])
    
    with db_connect() as conn:
        row = conn.execute(
            'SELECT balance_ton, balance_stars, total_wins, total_games FROM users WHERE user_id = ?',
            (user_id,)
        ).fetchone()
    
    if row:
        ton_bal, stars_bal, wins, games = row
        win_rate = round((wins / games) * 100) if games > 0 else 0
        
        keyboard = {
            "inline_keyboard": [
                [{"text": "💎 ВЫВЕСТИ TON", "callback_data": "withdraw_ton"}],
                [{"text": "🎰 ИГРАТЬ", "web_app": {"url": WEBAPP_URL}}],
                [{"text": "🏠 МЕНЮ", "callback_data": "main_menu"}]
            ]
        }
        
        text = (
            f"💼 <b>ПРОФИЛЬ</b>\n\n"
            f"👤 {first_name}\n"
            f"👑 VIP Status\n\n"
            f"💰 <b>БАЛАНСЫ</b>\n"
            f"💎 TON: <b>{ton_bal:.2f}</b>\n"
            f"⭐ Stars: <b>{stars_bal}</b>\n\n"
            f"🎰 <b>СТАТИСТИКА</b>\n"
            f"🏆 Побед: <b>{wins}</b>\n"
            f"🎮 Игр: <b>{games}</b>\n"
            f"📈 Win Rate: <b>{win_rate}%</b>"
        )
        tg_edit_message(chat_id, message_id, text, keyboard)

def handle_withdraw_prompt(callback, chat_id, message_id):
    """Запрос на вывод"""
    tg_answer_callback(callback["id"])
    text = (
        "💎 <b>ВЫВОД TON</b>\n\n"
        "Отправьте команду:\n"
        "<code>/withdraw СУММА КОШЕЛЕК</code>\n\n"
        "Пример: <code>/withdraw 10 UQA...</code>\n\n"
        "⚠️ Минимум: 10 TON"
    )
    tg_edit_message(chat_id, message_id, text, back_to_menu_keyboard())

def handle_withdraw(chat_id, user_id, text):
    """Обработка вывода"""
    try:
        parts = text.split()
        amount = float(parts[1])
        wallet = parts[2] if len(parts) > 2 else None
        
        if not wallet:
            tg_send_message(chat_id, "❌ Укажите адрес кошелька!\nФормат: /withdraw СУММА КОШЕЛЕК")
            return
        if amount < 10:
            tg_send_message(chat_id, "❌ Минимум: 10 TON!")
            return
        
        with db_connect() as conn:
            row = conn.execute('SELECT balance_ton FROM users WHERE user_id = ?', (user_id,)).fetchone()
            if not row or row[0] < amount:
                tg_send_message(chat_id, "❌ Недостаточно TON!")
                return
            
            conn.execute('UPDATE users SET balance_ton = balance_ton - ? WHERE user_id = ?', (amount, user_id))
            conn.execute(
                'INSERT INTO withdrawals (user_id, amount, wallet) VALUES (?, ?, ?)',
                (user_id, amount, wallet)
            )
        
        tg_send_message(chat_id, f"✅ Заявка на вывод <b>{amount} TON</b> создана!\n⏳ Ожидайте обработки.")
        
        # Уведомление админу
        tg_send_message(ADMIN_ID, f"📤 <b>ВЫВОД!</b>\n👤 ID: {user_id}\n💎 {amount} TON\n📤 {wallet}")
    except:
        tg_send_message(chat_id, "❌ Формат: /withdraw СУММА КОШЕЛЕК")

def handle_main_menu(callback, chat_id, message_id):
    """Главное меню"""
    tg_answer_callback(callback["id"])
    tg_edit_message(chat_id, message_id, "🔥 <b>SYNDROME CASINO — МЕНЮ</b>", main_menu_keyboard())

# =================================================================
# FLASK ПРИЛОЖЕНИЕ
# =================================================================
flask_app = Flask(__name__)

@flask_app.route('/')
def webapp():
    return render_template_string(HTML_TEMPLATE)

@flask_app.route('/api/user/<int:user_id>')
def api_get_user(user_id):
    try:
        with db_connect() as conn:
            row = conn.execute(
                'SELECT balance_ton, balance_stars, total_wins, total_games FROM users WHERE user_id = ?',
                (user_id,)
            ).fetchone()
        
        if row:
            return jsonify({
                'balance_ton': row[0],
                'balance_stars': row[1],
                'total_wins': row[2],
                'total_games': row[3]
            })
    except:
        pass
    
    return jsonify({'balance_ton': 100, 'balance_stars': 1000, 'total_wins': 0, 'total_games': 0})

@flask_app.route('/api/game', methods=['POST'])
def api_game():
    data = request.json
    user_id = data.get('user_id')
    game_type = data.get('game_type')
    bet_amount = float(data.get('bet_amount', 0))
    currency = data.get('currency', 'TON')
    
    try:
        with db_connect() as conn:
            if currency == 'TON':
                row = conn.execute('SELECT balance_ton FROM users WHERE user_id = ?', (user_id,)).fetchone()
            else:
                row = conn.execute('SELECT balance_stars FROM users WHERE user_id = ?', (user_id,)).fetchone()
            
            if not row or row[0] < bet_amount:
                return jsonify({'error': 'Недостаточно средств!'}), 400
            
            # Игровая механика (казино всегда в плюсе)
            win = random.choices([True, False], weights=[30, 70])[0]
            multiplier = 0
            win_amount = 0
            
            if win:
                multipliers = [1.5, 2, 3, 5, 10]
                weights_list = [30, 30, 25, 10, 5]
                r = random.random() * sum(weights_list)
                for i, m in enumerate(multipliers):
                    r -= weights_list[i]
                    if r <= 0:
                        multiplier = m
                        break
                win_amount = bet_amount * multiplier
            
            if win:
                if currency == 'TON':
                    conn.execute(
                        'UPDATE users SET balance_ton = balance_ton + ?, total_wins = total_wins + 1, total_games = total_games + 1 WHERE user_id = ?',
                        (win_amount - bet_amount, user_id)
                    )
                else:
                    conn.execute(
                        'UPDATE users SET balance_stars = balance_stars + ?, total_wins = total_wins + 1, total_games = total_games + 1 WHERE user_id = ?',
                        (int(win_amount - bet_amount), user_id)
                    )
            else:
                if currency == 'TON':
                    conn.execute(
                        'UPDATE users SET balance_ton = balance_ton - ?, total_games = total_games + 1 WHERE user_id = ?',
                        (bet_amount, user_id)
                    )
                else:
                    conn.execute(
                        'UPDATE users SET balance_stars = balance_stars - ?, total_games = total_games + 1 WHERE user_id = ?',
                        (int(bet_amount), user_id)
                    )
            
            return jsonify({'win': win, 'amount': win_amount, 'multiplier': multiplier})
    except Exception as e:
        logger.error(f"Game error: {e}")
        return jsonify({'error': 'Server error'}), 500

@flask_app.route('/webhook', methods=['POST'])
def webhook():
    """Обработка вебхуков от Telegram"""
    try:
        update = request.get_json()
        logger.info(f"Update: {json.dumps(update, indent=2)[:500]}")
        
        # Обработка сообщений
        if "message" in update:
            msg = update["message"]
            chat_id = msg["chat"]["id"]
            user_id = msg["from"]["id"]
            username = msg["from"].get("username", f"user_{user_id}")
            first_name = msg["from"].get("first_name", "Player")
            
            if "text" in msg:
                text = msg["text"]
                
                if text.startswith("/start"):
                    handle_start(chat_id, user_id, username, first_name)
                elif text.startswith("/withdraw"):
                    handle_withdraw(chat_id, user_id, text)
                else:
                    tg_send_message(chat_id, "Используйте кнопку меню для запуска казино! 🎰")
            
            # Обработка успешного платежа
            elif "successful_payment" in msg:
                payment = msg["successful_payment"]
                if payment.get("invoice_payload") == "stars_deposit":
                    stars_amount = payment["total_amount"]
                    ton_equivalent = stars_amount * 0.1
                    
                    with db_connect() as conn:
                        conn.execute(
                            'UPDATE users SET balance_stars = balance_stars + ?, balance_ton = balance_ton + ? WHERE user_id = ?',
                            (stars_amount, ton_equivalent, user_id)
                        )
                    
                    tg_send_message(
                        chat_id,
                        f"✅ <b>ПОПОЛНЕНИЕ ЗВЕЗДАМИ!</b>\n\n"
                        f"⭐ Зачислено: <b>{stars_amount} Stars</b>\n"
                        f"💎 Эквивалент: <b>{ton_equivalent:.2f} TON</b>"
                    )
        
        # Обработка callback query
        elif "callback_query" in update:
            callback = update["callback_query"]
            chat_id = callback["message"]["chat"]["id"]
            message_id = callback["message"]["message_id"]
            user_id = callback["from"]["id"]
            first_name = callback["from"].get("first_name", "Player")
            data = callback.get("data", "")
            
            if data == "deposit_menu":
                handle_deposit_menu(callback, chat_id, message_id)
            elif data == "deposit_ton":
                handle_deposit_ton(callback, chat_id, message_id, user_id)
            elif data == "deposit_stars":
                tg_answer_callback(callback["id"], "Используйте кнопку в меню бота для пополнения Stars")
            elif data == "profile":
                handle_profile(callback, chat_id, message_id, user_id, first_name)
            elif data == "withdraw_ton":
                handle_withdraw_prompt(callback, chat_id, message_id)
            elif data == "main_menu":
                handle_main_menu(callback, chat_id, message_id)
            elif data.startswith("check_"):
                tg_answer_callback(callback["id"], "Проверка платежей временно недоступна")
            else:
                tg_answer_callback(callback["id"])
        
        return "ok", 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return "error", 500

@flask_app.route('/health')
def health():
    return jsonify({"status": "ok", "url": WEBAPP_URL})

# =================================================================
# HTML ШАБЛОН
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
        *{margin:0;padding:0;box-sizing:border-box}
        body{background:#0a0a1a;color:#fff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh}
        .app{max-width:480px;margin:0 auto;padding:16px;padding-bottom:80px}
        .header{background:#12122a;border:1px solid rgba(255,255,255,0.08);border-radius:20px;padding:16px;margin-bottom:16px;display:flex;align-items:center;gap:12px}
        .avatar{width:48px;height:48px;border-radius:50%;background:linear-gradient(135deg,#7c3aed,#a855f7);display:flex;align-items:center;justify-content:center;font-size:24px;font-weight:700;flex-shrink:0}
        .balance-card{background:linear-gradient(135deg,rgba(124,58,237,0.2),rgba(59,130,246,0.2));border:1px solid rgba(124,58,237,0.3);border-radius:20px;padding:20px;margin-bottom:16px}
        .balance-label{font-size:12px;color:#8a8aa8;text-transform:uppercase;margin-bottom:8px}
        .balance-row{display:flex;justify-content:space-around;align-items:center}
        .balance-amount{font-size:28px;font-weight:900;background:linear-gradient(135deg,#ffd700,#ff8c00);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
        .balance-currency{font-size:11px;color:#8a8aa8;margin-top:4px}
        .divider{width:1px;height:50px;background:rgba(255,255,255,0.15)}
        .tabs{display:flex;background:#12122a;border-radius:16px;padding:4px;margin-bottom:16px;gap:4px}
        .tab{flex:1;padding:12px;text-align:center;border-radius:12px;cursor:pointer;font-weight:600;font-size:14px;color:#8a8aa8;border:none;background:transparent;transition:all 0.3s}
        .tab.active{background:linear-gradient(135deg,#7c3aed,#a855f7);color:#fff}
        .tab-content{display:none}
        .tab-content.active{display:block}
        .currency-select{display:flex;gap:8px;margin-bottom:16px}
        .currency-btn{flex:1;padding:12px;border-radius:12px;border:1px solid rgba(255,255,255,0.08);background:transparent;color:#fff;cursor:pointer;font-weight:600;font-size:14px}
        .currency-btn.active{background:linear-gradient(135deg,#ffd700,#ff8c00);color:#000;font-weight:700}
        .games-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
        .game-card{background:#12122a;border:1px solid rgba(255,255,255,0.08);border-radius:20px;padding:20px;text-align:center;cursor:pointer;transition:all 0.3s;position:relative}
        .game-card:hover{transform:translateY(-3px);border-color:rgba(255,215,0,0.4)}
        .game-card.disabled{opacity:0.4;pointer-events:none}
        .game-icon{font-size:40px;margin-bottom:8px}
        .game-name{font-size:15px;font-weight:600;margin-bottom:4px}
        .game-bet{font-size:12px;color:#ffd700}
        .game-badge{position:absolute;top:10px;right:10px;background:linear-gradient(135deg,#ff2d55,#ff6b6b);color:#fff;padding:4px 8px;border-radius:8px;font-size:10px;font-weight:700;animation:pulse 2s infinite}
        @keyframes pulse{0%,100%{transform:scale(1)}50%{transform:scale(1.1)}}
        .deposit-card{background:#12122a;border:1px solid rgba(255,255,255,0.08);border-radius:20px;padding:24px;margin-bottom:12px;cursor:pointer;text-align:center;transition:all 0.3s}
        .deposit-card:hover{border-color:rgba(255,215,0,0.4);transform:translateY(-2px)}
        .deposit-icon{font-size:48px;margin-bottom:12px}
        .deposit-name{font-size:18px;font-weight:700;margin-bottom:4px}
        .deposit-desc{font-size:13px;color:#8a8aa8}
        .profile-card{background:#12122a;border:1px solid rgba(255,255,255,0.08);border-radius:20px;padding:20px;margin-bottom:12px}
        .stat-row{display:flex;justify-content:space-between;padding:14px 0;border-bottom:1px solid rgba(255,255,255,0.08)}
        .stat-row:last-child{border-bottom:none}
        .stat-label{color:#8a8aa8;font-size:14px}
        .stat-value{font-weight:700;font-size:16px}
        .profile-btn{background:linear-gradient(135deg,#7c3aed,#a855f7);color:#fff;border:none;padding:16px;border-radius:14px;font-size:15px;font-weight:700;cursor:pointer;width:100%;margin-top:12px}
        .modal{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.95);z-index:1000;align-items:center;justify-content:center}
        .modal.active{display:flex}
        .modal-content{background:#12122a;border:1px solid rgba(255,255,255,0.08);border-radius:24px;padding:24px;width:90%;max-width:400px;text-align:center;position:relative}
        .modal-close{position:absolute;top:16px;right:16px;background:rgba(255,255,255,0.1);border:none;color:#fff;width:36px;height:36px;border-radius:50%;font-size:18px;cursor:pointer}
        .modal-title{font-size:24px;font-weight:800;margin-bottom:24px;background:linear-gradient(135deg,#ffd700,#ff8c00);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
        .slot-container{display:flex;gap:12px;justify-content:center;margin:24px 0}
        .slot-reel{width:80px;height:80px;background:rgba(255,255,255,0.05);border:2px solid rgba(255,255,255,0.08);border-radius:16px;display:flex;align-items:center;justify-content:center;font-size:36px}
        .slot-reel.spinning{animation:reelSpin 0.1s linear infinite;border-color:#ffd700}
        @keyframes reelSpin{0%{transform:translateY(-10px)}50%{transform:translateY(10px)}100%{transform:translateY(-10px)}}
        .roulette-wheel{width:200px;height:200px;border-radius:50%;background:conic-gradient(#ff2d55 0deg 36deg,#000 36deg 72deg,#ff2d55 72deg 108deg,#000 108deg 144deg,#ff2d55 144deg 180deg,#000 180deg 216deg,#ff2d55 216deg 252deg,#000 252deg 288deg,#ff2d55 288deg 324deg,#000 324deg 360deg);margin:24px auto;transition:transform 3s;display:flex;align-items:center;justify-content:center}
        .roulette-center{width:60px;height:60px;background:#0a0a1a;border-radius:50%;font-size:24px;font-weight:700;color:#ffd700;display:flex;align-items:center;justify-content:center}
        .game-btn{background:linear-gradient(135deg,#7c3aed,#a855f7);color:#fff;border:none;padding:16px;border-radius:16px;font-size:16px;font-weight:700;cursor:pointer;width:100%;margin-top:16px}
        .result-banner{padding:16px;border-radius:16px;margin:16px 0;font-weight:700;font-size:18px}
        .result-win{background:rgba(16,185,129,0.2);border:1px solid rgba(16,185,129,0.4);color:#10b981}
        .result-lose{background:rgba(255,45,85,0.2);border:1px solid rgba(255,45,85,0.4);color:#ff2d55}
        .amount-input{width:100%;padding:18px;background:rgba(255,255,255,0.05);border:2px solid rgba(255,255,255,0.08);border-radius:16px;color:#fff;font-size:24px;font-weight:700;text-align:center;outline:none}
        .amount-input:focus{border-color:#ffd700}
        .quick-amounts{display:flex;gap:8px;margin:16px 0;flex-wrap:wrap}
        .quick-amount-btn{flex:1;min-width:55px;padding:10px;border-radius:12px;border:1px solid rgba(255,255,255,0.08);background:rgba(255,255,255,0.05);color:#fff;cursor:pointer;font-weight:600;font-size:13px}
        .quick-amount-btn:hover{border-color:#ffd700}
        .deposit-submit-btn{background:linear-gradient(135deg,#ffd700,#ff8c00);color:#000;border:none;padding:16px;border-radius:16px;font-size:16px;font-weight:700;cursor:pointer;width:100%}
        .deposit-submit-btn:disabled{opacity:0.5;cursor:not-allowed}
        .error-msg{color:#ff2d55;font-size:12px;margin-top:4px;display:none}
        .error-msg.show{display:block}
        .toast{position:fixed;top:20px;left:50%;transform:translateX(-50%);background:#12122a;border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:16px 24px;z-index:2000;text-align:center;font-weight:600;font-size:14px;white-space:pre-line;max-width:90%}
        .stats-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:16px}
        .stat-card{background:#12122a;border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:10px;text-align:center}
        .stat-value{font-size:16px;font-weight:700;color:#ffd700}
        .stat-label{font-size:10px;color:#8a8aa8}
    </style>
</head>
<body>
    <div class="app">
        <div class="header">
            <div class="avatar" id="avatar">S</div>
            <div style="flex:1"><div style="font-size:16px;font-weight:700" id="username">Player</div><div style="font-size:12px;color:#ffd700">VIP</div></div>
            <span style="font-size:24px">💎</span>
        </div>
        
        <div class="balance-card">
            <div class="balance-label">💰 БАЛАНС</div>
            <div class="balance-row">
                <div style="text-align:center"><div class="balance-amount" id="tonBalance">0.00</div><div class="balance-currency">TON</div></div>
                <div class="divider"></div>
                <div style="text-align:center"><div class="balance-amount" id="starsBalance">0</div><div class="balance-currency">STARS</div></div>
            </div>
        </div>
        
        <div class="stats-grid">
            <div class="stat-card"><div class="stat-value" id="quickWins">0</div><div class="stat-label">🏆 Побед</div></div>
            <div class="stat-card"><div class="stat-value" id="quickGames">0</div><div class="stat-label">🎮 Игр</div></div>
            <div class="stat-card"><div class="stat-value" id="quickRate">0%</div><div class="stat-label">📊 Win Rate</div></div>
        </div>
        
        <div class="tabs">
            <button class="tab active" onclick="switchTab('games')">🎰 ИГРЫ</button>
            <button class="tab" onclick="switchTab('deposit')">💰 ПОПОЛНИТЬ</button>
            <button class="tab" onclick="switchTab('profile')">💼 ПРОФИЛЬ</button>
        </div>
        
        <div class="tab-content active" id="tab-games">
            <div class="currency-select">
                <button class="currency-btn active" onclick="selectCurrency('TON',this)">💎 TON</button>
                <button class="currency-btn" onclick="selectCurrency('STARS',this)">⭐ STARS</button>
            </div>
            <div class="games-grid">
                <div class="game-card" id="card-slots" onclick="openGame('slots')"><div class="game-badge">HOT</div><div class="game-icon">🎰</div><div class="game-name">СЛОТЫ</div><div class="game-bet" id="slotsBet">1 TON</div></div>
                <div class="game-card" id="card-roulette" onclick="openGame('roulette')"><div class="game-icon">🎡</div><div class="game-name">РУЛЕТКА</div><div class="game-bet" id="rouletteBet">2 TON</div></div>
                <div class="game-card" id="card-dice" onclick="openGame('dice')"><div class="game-icon">🎲</div><div class="game-name">КОСТИ</div><div class="game-bet" id="diceBet">1.5 TON</div></div>
                <div class="game-card" id="card-blackjack" onclick="openGame('blackjack')"><div class="game-icon">🃏</div><div class="game-name">БЛЭКДЖЕК</div><div class="game-bet" id="blackjackBet">5 TON</div></div>
            </div>
        </div>
        
        <div class="tab-content" id="tab-deposit">
            <div class="deposit-card" onclick="openDepositModal('TON')"><div class="deposit-icon">💎</div><div class="deposit-name">ПОПОЛНИТЬ TON</div><div class="deposit-desc">Мин. 1 TON</div></div>
            <div class="deposit-card" onclick="openDepositModal('STARS')"><div class="deposit-icon">⭐</div><div class="deposit-name">ПОПОЛНИТЬ STARS</div><div class="deposit-desc">Мин. 10 Stars</div></div>
        </div>
        
        <div class="tab-content" id="tab-profile">
            <div class="profile-card">
                <div class="stat-row"><span class="stat-label">💎 TON</span><span class="stat-value" id="profTonBalance">0</span></div>
                <div class="stat-row"><span class="stat-label">⭐ Stars</span><span class="stat-value" id="profStarsBalance">0</span></div>
                <div class="stat-row"><span class="stat-label">🏆 Побед</span><span class="stat-value" id="profWins">0</span></div>
                <div class="stat-row"><span class="stat-label">🎮 Игр</span><span class="stat-value" id="profGames">0</span></div>
            </div>
            <button class="profile-btn" onclick="handleWithdraw()">💎 ВЫВЕСТИ TON</button>
        </div>
    </div>
    
    <div class="modal" id="depositModal">
        <div class="modal-content">
            <button class="modal-close" onclick="closeDepositModal()">✕</button>
            <div style="font-size:60px;margin-bottom:16px" id="depositIcon">💎</div>
            <div style="font-size:20px;font-weight:700;margin-bottom:8px" id="depositTitle">Пополнение TON</div>
            <input type="number" class="amount-input" id="depositAmount" placeholder="0" oninput="validateDeposit()">
            <div class="error-msg" id="depositError">Минимум: 1 TON</div>
            <div class="quick-amounts" id="quickAmounts"></div>
            <button class="deposit-submit-btn" id="depositBtn" onclick="submitDeposit()" disabled>💰 ПОПОЛНИТЬ</button>
        </div>
    </div>
    
    <div class="modal" id="slotsModal">
        <div class="modal-content">
            <button class="modal-close" onclick="closeGame()">✕</button>
            <div class="modal-title">🎰 СЛОТЫ</div>
            <div class="slot-container"><div class="slot-reel" id="reel1">🍒</div><div class="slot-reel" id="reel2">🍋</div><div class="slot-reel" id="reel3">💎</div></div>
            <div id="slotsResult"></div>
            <button class="game-btn" onclick="spinSlots()">🎰 КРУТИТЬ</button>
        </div>
    </div>
    
    <div class="modal" id="rouletteModal">
        <div class="modal-content">
            <button class="modal-close" onclick="closeGame()">✕</button>
            <div class="modal-title">🎡 РУЛЕТКА</div>
            <div class="roulette-wheel" id="rouletteWheel"><div class="roulette-center">🎡</div></div>
            <div id="rouletteResult"></div>
            <button class="game-btn" onclick="spinRoulette()">🎡 КРУТИТЬ</button>
        </div>
    </div>
    
    <div class="toast" id="toast" style="display:none"></div>

    <script>
        const tg=window.Telegram.WebApp;tg.expand();tg.ready();
        const user=tg.initDataUnsafe?.user||{};
        const userId=user.id||123456789;
        document.getElementById('username').textContent=user.first_name||'Player';
        document.getElementById('avatar').textContent=(user.first_name||'P').charAt(0).toUpperCase();
        
        let tonBalance=100,starsBalance=1000,totalWins=0,totalGames=0,currency='TON',isSpinning=false,depositType='TON';
        const bets={TON:{slots:1,roulette:2,dice:1.5,blackjack:5},STARS:{slots:10,roulette:20,dice:15,blackjack:50}};
        
        function showToast(m){const t=document.getElementById('toast');t.textContent=m;t.style.display='block';setTimeout(()=>t.style.display='none',3000)}
        function getBalance(){return currency==='TON'?tonBalance:starsBalance}
        
        async function loadData(){
            try{const r=await fetch('/api/user/'+userId);const d=await r.json();tonBalance=d.balance_ton||100;starsBalance=d.balance_stars||1000;totalWins=d.total_wins||0;totalGames=d.total_games||0;updateUI()}catch(e){updateUI()}
        }
        
        function updateUI(){
            document.getElementById('tonBalance').textContent=tonBalance.toFixed(2);
            document.getElementById('starsBalance').textContent=starsBalance;
            document.getElementById('quickWins').textContent=totalWins;
            document.getElementById('quickGames').textContent=totalGames;
            document.getElementById('quickRate').textContent=totalGames>0?Math.round(totalWins/totalGames*100)+'%':'0%';
            document.getElementById('profTonBalance').textContent=tonBalance.toFixed(2);
            document.getElementById('profStarsBalance').textContent=starsBalance;
            document.getElementById('profWins').textContent=totalWins;
            document.getElementById('profGames').textContent=totalGames;
            document.querySelectorAll('.game-bet').forEach(e=>{const g=e.id.replace('Bet','');e.textContent=bets[currency][g]+' '+currency});
            ['slots','roulette','dice','blackjack'].forEach(g=>{const c=document.getElementById('card-'+g);getBalance()<bets[currency][g]?c.classList.add('disabled'):c.classList.remove('disabled')})
        }
        
        function switchTab(t){document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));event.target.classList.add('active');document.querySelectorAll('.tab-content').forEach(c=>c.classList.remove('active'));document.getElementById('tab-'+t).classList.add('active')}
        function selectCurrency(c,btn){currency=c;document.querySelectorAll('.currency-btn').forEach(b=>b.classList.remove('active'));btn.classList.add('active');updateUI()}
        function openGame(g){if(getBalance()<bets[currency][g]){showToast('❌ Недостаточно '+currency+'!');return};document.getElementById(g+'Modal').classList.add('active')}
        function closeGame(){document.querySelectorAll('.modal').forEach(m=>{if(m.id!=='depositModal')m.classList.remove('active')});isSpinning=false}
        
        function openDepositModal(t){
            depositType=t;document.getElementById('depositIcon').textContent=t==='TON'?'💎':'⭐';
            document.getElementById('depositTitle').textContent=t==='TON'?'Пополнение TON':'Пополнение Stars';
            document.getElementById('depositAmount').value='';document.getElementById('depositError').classList.remove('show');
            document.getElementById('depositBtn').disabled=true;
            document.getElementById('quickAmounts').innerHTML=t==='TON'?'<button class="quick-amount-btn" onclick="setAmt(1)">1</button><button class="quick-amount-btn" onclick="setAmt(5)">5</button><button class="quick-amount-btn" onclick="setAmt(10)">10</button><button class="quick-amount-btn" onclick="setAmt(50)">50</button><button class="quick-amount-btn" onclick="setAmt(100)">100</button>':'<button class="quick-amount-btn" onclick="setAmt(10)">10</button><button class="quick-amount-btn" onclick="setAmt(50)">50</button><button class="quick-amount-btn" onclick="setAmt(100)">100</button><button class="quick-amount-btn" onclick="setAmt(500)">500</button><button class="quick-amount-btn" onclick="setAmt(1000)">1000</button>';
            document.getElementById('depositModal').classList.add('active')
        }
        
        function closeDepositModal(){document.getElementById('depositModal').classList.remove('active')}
        function setAmt(v){document.getElementById('depositAmount').value=v;validateDeposit()}
        function validateDeposit(){const v=parseFloat(document.getElementById('depositAmount').value);const m=depositType==='TON'?1:10;document.getElementById('depositBtn').disabled=isNaN(v)||v<m;document.getElementById('depositError').classList.toggle('show',isNaN(v)||v<m)}
        
        function submitDeposit(){
            const v=parseFloat(document.getElementById('depositAmount').value);const m=depositType==='TON'?1:10;
            if(isNaN(v)||v<m)return;
            depositType==='TON'?(tonBalance+=v,showToast('✅ +'+v.toFixed(2)+' TON\nПерейдите в бота для оплаты')):(starsBalance+=Math.floor(v),showToast('✅ +'+Math.floor(v)+' Stars\nПерейдите в бота для оплаты'));
            updateUI();closeDepositModal();tg.openTelegramLink('https://t.me/ваш_бот')
        }
        
        async function spinSlots(){
            if(isSpinning)return;
            const reels=[document.getElementById('reel1'),document.getElementById('reel2'),document.getElementById('reel3')];
            const sym=["🍒","🍋","🔔","💎","7️⃣","🍇","🎯"];
            reels.forEach(r=>r.classList.add('spinning'));
            for(let i=0;i<15;i++){reels.forEach(r=>r.textContent=sym[Math.floor(Math.random()*sym.length)]);await new Promise(r=>setTimeout(r,80))}
            reels.forEach(r=>r.classList.remove('spinning'));
            
            try{
                isSpinning=true;
                const res=await fetch('/api/game',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:userId,game_type:'slots',bet_amount:bets[currency]['slots'],currency})});
                const d=await res.json();
                if(d.win){currency==='TON'?tonBalance+=d.amount-bets[currency]['slots']:starsBalance+=d.amount-bets[currency]['slots'];totalWins++;reels.forEach(r=>r.textContent='💎');document.getElementById('slotsResult').innerHTML='<div class="result-banner result-win">🎉 +'+d.amount.toFixed(2)+' '+currency+'</div>'}
                else{currency==='TON'?tonBalance-=bets[currency]['slots']:starsBalance-=bets[currency]['slots'];document.getElementById('slotsResult').innerHTML='<div class="result-banner result-lose">😢 -'+bets[currency]['slots']+' '+currency+'</div>'}
                totalGames++;updateUI();isSpinning=false
            }catch(e){isSpinning=false}
        }
        
        async function spinRoulette(){
            if(isSpinning)return;
            const w=document.getElementById('rouletteWheel');w.style.transform='rotate('+(1800+Math.random()*360)+'deg)';
            await new Promise(r=>setTimeout(r,3000));
            try{
                isSpinning=true;
                const res=await fetch('/api/game',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:userId,game_type:'roulette',bet_amount:bets[currency]['roulette'],currency})});
                const d=await res.json();
                if(d.win){currency==='TON'?tonBalance+=d.amount-bets[currency]['roulette']:starsBalance+=d.amount-bets[currency]['roulette'];totalWins++;document.getElementById('rouletteResult').innerHTML='<div class="result-banner result-win">🎉 +'+d.amount.toFixed(2)+' '+currency+'</div>'}
                else{currency==='TON'?tonBalance-=bets[currency]['roulette']:starsBalance-=bets[currency]['roulette'];document.getElementById('rouletteResult').innerHTML='<div class="result-banner result-lose">😢 -'+bets[currency]['roulette']+' '+currency+'</div>'}
                totalGames++;updateUI();isSpinning=false
            }catch(e){isSpinning=false}
            setTimeout(()=>{w.style.transition='none';w.style.transform='rotate(0deg)';setTimeout(()=>w.style.transition='transform 3s',100)},500)
        }
        
        function handleWithdraw(){tg.openTelegramLink('https://t.me/ваш_бот');showToast('Отправьте боту:\n/withdraw СУММА КОШЕЛЕК\nМинимум: 10 TON')}
        
        document.querySelectorAll('.modal').forEach(m=>m.addEventListener('click',function(e){if(e.target===this){this.id==='depositModal'?closeDepositModal():closeGame()}}));
        loadData();setInterval(loadData,30000)
    </script>
</body>
</html>'''

# =================================================================
# ЗАПУСК
# =================================================================
if __name__ == '__main__':
    # Инициализация
    init_db()
    tg_set_webhook()
    tg_set_menu()
    tg_set_commands()
    
    logger.info("🔥 SYNDROME CASINO READY!")
    logger.info(f"🌐 URL: https://{RENDER_URL}")
    
    # Запуск Flask
    port = int(os.environ.get('PORT', 8080))
    flask_app.run(host='0.0.0.0', port=port)
