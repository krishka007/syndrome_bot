import asyncio
import logging
import sqlite3
import random
import hashlib
import os
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, MenuButtonWebApp, BotCommand,
    Message, CallbackQuery, LabeledPrice, PreCheckoutQuery
)
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode, ContentType
from aiogram.client.default import DefaultBotProperties

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
WEBAPP_URL = f"https://syndrome-bot-4.onrender.com"

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
            total_withdrawn_ton REAL DEFAULT 0,
            total_withdrawn_stars INTEGER DEFAULT 0,
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
            status TEXT DEFAULT 'pending',
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
    return conn

# =================================================================
# ФУНКЦИИ TON
# =================================================================
def generate_payment_id(user_id):
    timestamp = int(datetime.now().timestamp())
    raw = f"SYN{user_id}X{timestamp}X{random.randint(1000,9999)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16].upper()

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
                        'from': source,
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
    username = message.from_user.username or "user_" + str(user_id)
    first_name = message.from_user.first_name or "Player"
    
    conn = init_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR IGNORE INTO victims (user_id, username, first_name, last_activity) 
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    ''', (user_id, username, first_name))
    conn.commit()
    conn.close()
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(
        text="🎰 ЗАПУСТИТЬ SYNDROME CASINO",
        web_app=WebAppInfo(url=WEBAPP_URL)
    ))
    keyboard.add(InlineKeyboardButton(text="💰 ПОПОЛНИТЬ", callback_data="deposit_menu"))
    keyboard.add(InlineKeyboardButton(text="💼 ПРОФИЛЬ", callback_data="profile"))
    keyboard.adjust(1)
    
    await message.answer(
        "🔥 *SYNDROME CASINO — TON & STARS CASINO* 🔥\n\n"
        "🎰 *Слоты, Рулетка, Кости, Блэкджек*\n"
        "💎 *Пополнение через TON и Telegram Stars*\n"
        "💰 *Мгновенные выплаты от 10 TON*\n"
        "⚡ *Минимальная ставка: 1 TON / 10 Stars*\n\n"
        "🎁 *НАЖМИ НА КНОПКУ НИЖЕ!*\n\n"
        "📊 *ТОП ВЫИГРЫШИ СЕГОДНЯ:*\n"
        "• @crypto_whale — 340 TON\n"
        "• @ton_master — 150 TON\n"
        "• @lucky_gambler — 89 TON",
        reply_markup=keyboard.as_markup()
    )

@dp.callback_query(F.data == "deposit_menu")
async def deposit_menu(callback: CallbackQuery):
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="💎 ПОПОЛНИТЬ TON", callback_data="deposit_ton"))
    keyboard.add(InlineKeyboardButton(text="⭐ ПОПОЛНИТЬ STARS", callback_data="deposit_stars"))
    keyboard.add(InlineKeyboardButton(text="🏠 МЕНЮ", callback_data="main_menu"))
    keyboard.adjust(1)
    
    await callback.message.edit_text(
        "💰 *ПОПОЛНЕНИЕ БАЛАНСА*\n\n"
        "💎 *TON* — криптовалюта TON\n"
        "⭐ *Stars* — Звезды Telegram\n\n"
        "Минимум: 1 TON или 10 Stars",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

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
    
    await callback.message.edit_text(
        "💎 *ПОПОЛНЕНИЕ TON*\n\n"
        f"📤 Отправьте TON на кошелёк:\n\n"
        f"`{TON_WALLET}`\n\n"
        f"📝 *КОД В КОММЕНТАРИИ:*\n"
        f"`{payment_id}`\n\n"
        f"⚠️ Минимум: *1 TON*\n"
        f"Без кода платёж НЕ зачислится!\n\n"
        f"После отправки нажмите проверку.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ ПРОВЕРИТЬ ОПЛАТУ", callback_data=f"checkpay_{payment_id}")],
            [InlineKeyboardButton(text="🔄 НОВЫЙ КОД", callback_data="deposit_ton")],
            [InlineKeyboardButton(text="🏠 МЕНЮ", callback_data="main_menu")]
        ])
    )
    await callback.answer()

@dp.callback_query(F.data == "deposit_stars")
async def deposit_stars(callback: CallbackQuery):
    await callback.message.answer_invoice(
        title="SYNDROME CASINO - Stars",
        description="Пополнение баланса казино через Telegram Stars\n1 звезда = 0.1 TON эквивалент",
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

@dp.pre_checkout_query()
async def pre_checkout(pre_checkout: PreCheckoutQuery):
    await pre_checkout.answer(ok=True)

@dp.message(F.content_type == ContentType.SUCCESSFUL_PAYMENT)
async def successful_payment(message: Message):
    user_id = message.from_user.id
    payment = message.successful_payment
    
    if payment.invoice_payload == "stars_deposit":
        stars_amount = payment.total_amount
        ton_equivalent = stars_amount * 0.1
        
        conn = init_db()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE victims 
            SET balance_stars = balance_stars + ?, 
                balance_ton = balance_ton + ?,
                total_deposited_stars = total_deposited_stars + ?
            WHERE user_id = ?
        ''', (stars_amount, ton_equivalent, stars_amount, user_id))
        cursor.execute('''
            INSERT INTO transactions (user_id, type, amount, currency, tx_hash, status)
            VALUES (?, 'stars_deposit', ?, 'STARS', ?, 'completed')
        ''', (user_id, stars_amount, payment.telegram_payment_charge_id))
        conn.commit()
        conn.close()
        
        await message.answer(
            f"✅ *ПОПОЛНЕНИЕ ЗВЕЗДАМИ!*\n\n"
            f"⭐ Зачислено: *{stars_amount} Stars*\n"
            f"💎 Эквивалент: *{ton_equivalent:.2f} TON*\n\n"
            f"🎰 Играйте в казино!"
        )
        
        await bot.send_message(
            ADMIN_ID,
            f"⭐ *НОВЫЙ ПЛАТЕЖ ЗВЕЗДАМИ!*\n"
            f"👤 @{message.from_user.username or 'Unknown'}\n"
            f"⭐ Сумма: *{stars_amount} Stars*"
        )

@dp.callback_query(F.data.startswith("checkpay_"))
async def check_payment(callback: CallbackQuery):
    payment_id = callback.data.replace("checkpay_", "")
    user_id = callback.from_user.id
    
    await callback.message.edit_text(
        "🔍 *ПРОВЕРКА ТРАНЗАКЦИИ*\n\nСканирую блокчейн TON...",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 ОБНОВИТЬ", callback_data=f"checkpay_{payment_id}")]
        ])
    )
    
    result = verify_ton_transaction(TON_WALLET, payment_id)
    
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
            INSERT INTO transactions (user_id, type, amount, currency, tx_hash, status)
            VALUES (?, 'ton_deposit', ?, 'TON', ?, 'completed')
        ''', (user_id, amount_ton, result['hash']))
        conn.commit()
        conn.close()
        
        await bot.send_message(
            ADMIN_ID,
            f"💰 *ПЛАТЕЖ TON!*\n"
            f"👤 @{callback.from_user.username or 'Unknown'}\n"
            f"💎 Сумма: *{amount_ton:.4f} TON*"
        )
        
        await callback.message.edit_text(
            f"✅ *ПЛАТЕЖ ЗАЧИСЛЕН!*\n\n"
            f"💰 Зачислено: *{amount_ton:.4f} TON*\n\n"
            f"🎰 Играйте в казино!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎰 ИГРАТЬ", web_app=WebAppInfo(url=WEBAPP_URL))],
                [InlineKeyboardButton(text="🏠 МЕНЮ", callback_data="main_menu")]
            ])
        )
    else:
        await callback.message.edit_text(
            "❌ *ПЛАТЕЖ НЕ НАЙДЕН*\n\n"
            "• Проверьте код в комментарии\n"
            "• Транзакция может идти до 5 минут\n"
            "• Минимум: 1 TON",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 ПРОВЕРИТЬ СНОВА", callback_data=f"checkpay_{payment_id}")],
                [InlineKeyboardButton(text="💎 НОВЫЙ ПЛАТЕЖ", callback_data="deposit_ton")],
                [InlineKeyboardButton(text="🏠 МЕНЮ", callback_data="main_menu")]
            ])
        )
    await callback.answer()

@dp.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):
    conn = init_db()
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
        
        await callback.message.edit_text(
            f"💼 *ПРОФИЛЬ*\n\n"
            f"👤 {callback.from_user.first_name}\n"
            f"👑 VIP Status\n\n"
            f"💰 *БАЛАНСЫ*\n"
            f"💎 TON: *{ton_bal:.4f}*\n"
            f"⭐ Stars: *{stars_bal}*\n\n"
            f"📥 *ПОПОЛНЕНИЯ*\n"
            f"💎 TON: *{ton_dep:.2f}*\n"
            f"⭐ Stars: *{stars_dep}*\n\n"
            f"🎰 *СТАТИСТИКА*\n"
            f"🏆 Побед: *{wins}*\n"
            f"🎮 Игр: *{games}*\n"
            f"📈 Win Rate: *{win_rate}%*",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💎 ВЫВЕСТИ TON", callback_data="withdraw_ton")],
                [InlineKeyboardButton(text="🎰 ИГРАТЬ", web_app=WebAppInfo(url=WEBAPP_URL))],
                [InlineKeyboardButton(text="🏠 МЕНЮ", callback_data="main_menu")]
            ])
        )
    await callback.answer()

@dp.callback_query(F.data == "withdraw_ton")
async def withdraw_ton_prompt(callback: CallbackQuery):
    await callback.message.edit_text(
        "💎 *ВЫВОД TON*\n\n"
        "Отправьте сообщение:\n"
        "`/withdraw СУММА КОШЕЛЕК`\n\n"
        "Пример:\n"
        "`/withdraw 10 EQD...`\n\n"
        "⚠️ Минимум: 10 TON",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 МЕНЮ", callback_data="main_menu")]
        ])
    )
    await callback.answer()

@dp.message(Command("withdraw"))
async def withdraw_ton(message: Message):
    user_id = message.from_user.id
    
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
        
        conn = init_db()
        cursor = conn.cursor()
        cursor.execute('SELECT balance_ton FROM victims WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        
        if not result or result[0] < amount:
            await message.reply("❌ Недостаточно TON!")
            conn.close()
            return
        
        cursor.execute('''
            UPDATE victims 
            SET balance_ton = balance_ton - ?, total_withdrawn_ton = total_withdrawn_ton + ?
            WHERE user_id = ?
        ''', (amount, amount, user_id))
        cursor.execute('''
            INSERT INTO withdrawal_requests (user_id, amount, currency, wallet_address, status)
            VALUES (?, ?, 'TON', ?, 'pending')
        ''', (user_id, amount, wallet))
        conn.commit()
        conn.close()
        
        await message.reply(
            f"✅ *ЗАЯВКА НА ВЫВОД!*\n\n"
            f"💎 Сумма: *{amount} TON*\n"
            f"📤 Кошелёк: `{wallet}`\n\n"
            f"⏳ Ожидает обработки (до 24ч)"
        )
        
        await bot.send_message(
            ADMIN_ID,
            f"📤 *ЗАЯВКА НА ВЫВОД!*\n"
            f"👤 @{message.from_user.username or 'Unknown'}\n"
            f"💎 Сумма: *{amount} TON*\n"
            f"📤 Кошелёк: `{wallet}`"
        )
    except Exception as e:
        await message.reply("❌ Формат: /withdraw СУММА КОШЕЛЕК")

@dp.callback_query(F.data == "main_menu")
async def main_menu(callback: CallbackQuery):
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="🎰 ЗАПУСТИТЬ КАЗИНО", web_app=WebAppInfo(url=WEBAPP_URL)))
    keyboard.add(InlineKeyboardButton(text="💰 ПОПОЛНИТЬ", callback_data="deposit_menu"))
    keyboard.add(InlineKeyboardButton(text="💼 ПРОФИЛЬ", callback_data="profile"))
    keyboard.adjust(1)
    
    await callback.message.edit_text("🔥 *SYNDROME CASINO — МЕНЮ*", reply_markup=keyboard.as_markup())
    await callback.answer()

@dp.message(Command("admin"))
async def admin_command(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    conn = init_db()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*), COALESCE(SUM(total_deposited_ton), 0), COALESCE(SUM(total_deposited_stars), 0) FROM victims')
    users, ton, stars = cursor.fetchone()
    cursor.execute("SELECT COUNT(*) FROM withdrawal_requests WHERE status = 'pending'")
    pending = cursor.fetchone()[0]
    conn.close()
    
    await message.answer(
        f"👑 *АДМИН-ПАНЕЛЬ*\n\n"
        f"👥 Пользователей: *{users}*\n"
        f"💎 Депозитов TON: *{ton:.2f}*\n"
        f"⭐ Депозитов Stars: *{stars}*\n"
        f"📤 Ожидают вывода: *{pending}*"
    )

# =================================================================
# FLASK + WEBAPP
# =================================================================
flask_app = Flask(__name__)

@flask_app.route('/')
def webapp():
    return render_template_string(HTML_TEMPLATE)

@flask_app.route('/api/user/<int:user_id>')
def get_user_data(user_id):
    conn = init_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT balance_ton, balance_stars, total_wins, total_games, 
               total_deposited_ton, total_deposited_stars
        FROM victims WHERE user_id = ?
    ''', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return jsonify({
            'balance_ton': result[0],
            'balance_stars': result[1],
            'total_wins': result[2],
            'total_games': result[3],
            'deposited_ton': result[4],
            'deposited_stars': result[5]
        })
    return jsonify({
        'balance_ton': 0, 'balance_stars': 0,
        'total_wins': 0, 'total_games': 0,
        'deposited_ton': 0, 'deposited_stars': 0
    })

@flask_app.route('/api/game', methods=['POST'])
def process_game():
    data = request.json
    user_id = data.get('user_id')
    game_type = data.get('game_type')
    bet_amount = float(data.get('bet_amount', 0))
    currency = data.get('currency', 'TON')
    
    conn = init_db()
    cursor = conn.cursor()
    
    if currency == 'TON':
        cursor.execute('SELECT balance_ton FROM victims WHERE user_id = ?', (user_id,))
    else:
        cursor.execute('SELECT balance_stars FROM victims WHERE user_id = ?', (user_id,))
    
    result = cursor.fetchone()
    
    if not result or result[0] < bet_amount:
        conn.close()
        return jsonify({'error': 'Insufficient balance', 'message': 'Недостаточно средств!'}), 400
    
    win = random.choices([True, False], weights=[30, 70])[0]
    multiplier = 0
    
    if win:
        multipliers = [1.5, 2, 3, 5, 10]
        weights = [30, 30, 25, 10, 5]
        total_weight = sum(weights)
        r = random.random() * total_weight
        
        for i, m in enumerate(multipliers):
            r -= weights[i]
            if r <= 0:
                multiplier = m
                break
        
        win_amount = bet_amount * multiplier
        
        if currency == 'TON':
            cursor.execute('''
                UPDATE victims 
                SET balance_ton = balance_ton + ?, total_wins = total_wins + 1, total_games = total_games + 1 
                WHERE user_id = ?
            ''', (win_amount - bet_amount, user_id))
        else:
            cursor.execute('''
                UPDATE victims 
                SET balance_stars = balance_stars + ?, total_wins = total_wins + 1, total_games = total_games + 1 
                WHERE user_id = ?
            ''', (int(win_amount - bet_amount), user_id))
    else:
        win_amount = 0
        if currency == 'TON':
            cursor.execute('''
                UPDATE victims 
                SET balance_ton = balance_ton - ?, total_games = total_games + 1 
                WHERE user_id = ?
            ''', (bet_amount, user_id))
        else:
            cursor.execute('''
                UPDATE victims 
                SET balance_stars = balance_stars - ?, total_games = total_games + 1 
                WHERE user_id = ?
            ''', (int(bet_amount), user_id))
    
    cursor.execute('''
        INSERT INTO transactions (user_id, type, amount, currency, status)
        VALUES (?, ?, ?, ?, 'completed')
    ''', (user_id, f"{game_type}_{'win' if win else 'lose'}", win_amount if win else bet_amount, currency))
    
    conn.commit()
    conn.close()
    
    return jsonify({
        'win': win,
        'amount': win_amount,
        'multiplier': multiplier,
        'currency': currency
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
# HTML ШАБЛОН (ПОЛНАЯ ВЕРСИЯ С МОДАЛЬНЫМ ОКНОМ ПОПОЛНЕНИЯ)
# =================================================================
HTML_TEMPLATE = r'''
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="theme-color" content="#0a0a1a">
    <title>SYNDROME CASINO</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
        
        :root {
            --bg-primary: #0a0a1a;
            --bg-secondary: #12122a;
            --border-glass: rgba(255, 255, 255, 0.08);
            --text-primary: #ffffff;
            --text-secondary: #8a8aa8;
            --accent-gold: #ffd700;
            --accent-purple: #7c3aed;
            --accent-blue: #3b82f6;
            --accent-green: #10b981;
            --accent-red: #ff2d55;
            --gradient-gold: linear-gradient(135deg, #ffd700 0%, #ff8c00 100%);
            --gradient-purple: linear-gradient(135deg, #7c3aed 0%, #a855f7 100%);
            --gradient-blue: linear-gradient(135deg, #3b82f6 0%, #60a5fa 100%);
            --gradient-red: linear-gradient(135deg, #ff2d55 0%, #ff6b6b 100%);
            --shadow-glow-gold: 0 0 20px rgba(255, 215, 0, 0.3);
            --shadow-glow-purple: 0 0 20px rgba(124, 58, 237, 0.3);
        }
        
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            background: var(--bg-primary);
            color: var(--text-primary);
            font-family: 'Inter', sans-serif;
            min-height: 100vh;
            overflow-x: hidden;
            -webkit-tap-highlight-color: transparent;
        }
        
        .particles { position: fixed; top: 0; left: 0; width: 100%; height: 100%; z-index: 0; overflow: hidden; pointer-events: none; }
        
        .particle {
            position: absolute; width: 2px; height: 2px;
            background: var(--accent-gold); border-radius: 50%;
            animation: floatUp 8s infinite; opacity: 0;
        }
        
        @keyframes floatUp {
            0% { transform: translateY(100vh) scale(0); opacity: 0; }
            10% { opacity: 0.4; } 90% { opacity: 0.4; }
            100% { transform: translateY(-100vh) scale(1); opacity: 0; }
        }
        
        .app-container { position: relative; z-index: 1; max-width: 480px; margin: 0 auto; padding: 16px 16px 100px; min-height: 100vh; }
        
        .header {
            background: var(--bg-secondary); border: 1px solid var(--border-glass);
            border-radius: 20px; padding: 16px; margin-bottom: 16px;
            display: flex; align-items: center; gap: 12px;
            backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
        }
        
        .avatar { width: 48px; height: 48px; border-radius: 50%; background: var(--gradient-purple); display: flex; align-items: center; justify-content: center; font-size: 24px; font-weight: 700; box-shadow: var(--shadow-glow-purple); flex-shrink: 0; }
        .user-info { flex: 1; }
        .user-name { font-size: 16px; font-weight: 700; }
        .user-status { font-size: 12px; color: var(--accent-gold); font-weight: 500; }
        
        .balance-card {
            background: linear-gradient(135deg, rgba(124, 58, 237, 0.2), rgba(59, 130, 246, 0.2));
            border: 1px solid rgba(124, 58, 237, 0.3); border-radius: 20px;
            padding: 20px; margin-bottom: 20px; position: relative; overflow: hidden;
        }
        
        .balance-card::before {
            content: ''; position: absolute; top: -50%; left: -50%;
            width: 200%; height: 200%;
            background: radial-gradient(circle, rgba(124, 58, 237, 0.15), transparent 70%);
            animation: rotate 10s linear infinite;
        }
        
        @keyframes rotate { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        
        .balance-label { font-size: 12px; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; position: relative; z-index: 1; }
        .balance-row { display: flex; justify-content: space-around; align-items: center; position: relative; z-index: 1; }
        .balance-item { text-align: center; }
        .balance-amount { font-size: 28px; font-weight: 900; background: var(--gradient-gold); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
        .balance-currency { font-size: 11px; color: var(--text-secondary); text-transform: uppercase; margin-top: 4px; }
        .balance-divider { width: 1px; height: 50px; background: rgba(255, 255, 255, 0.15); }
        
        .tabs { display: flex; background: var(--bg-secondary); border-radius: 16px; padding: 4px; margin-bottom: 20px; gap: 4px; }
        .tab { flex: 1; padding: 12px; text-align: center; border-radius: 12px; cursor: pointer; font-weight: 600; font-size: 14px; transition: all 0.3s; color: var(--text-secondary); border: none; background: transparent; font-family: 'Inter', sans-serif; }
        .tab.active { background: var(--gradient-purple); color: white; box-shadow: var(--shadow-glow-purple); }
        
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        
        .currency-select { display: flex; gap: 8px; margin-bottom: 16px; }
        .currency-btn { flex: 1; padding: 12px; border-radius: 12px; border: 1px solid var(--border-glass); background: transparent; color: white; cursor: pointer; font-weight: 600; font-size: 14px; transition: all 0.3s; font-family: 'Inter', sans-serif; }
        .currency-btn.active { background: var(--gradient-gold); color: black; border-color: transparent; font-weight: 700; }
        
        .games-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
        .game-card { background: var(--bg-secondary); border: 1px solid var(--border-glass); border-radius: 20px; padding: 20px; text-align: center; cursor: pointer; transition: all 0.3s; position: relative; }
        .game-card:hover { transform: translateY(-3px); border-color: rgba(255, 215, 0, 0.4); box-shadow: 0 15px 30px rgba(0, 0, 0, 0.3); }
        .game-card.disabled { opacity: 0.4; cursor: not-allowed; pointer-events: none; }
        .game-card.disabled:hover { transform: none; border-color: var(--border-glass); box-shadow: none; }
        .game-icon { font-size: 40px; margin-bottom: 8px; }
        .game-name { font-size: 15px; font-weight: 600; margin-bottom: 4px; }
        .game-bet { font-size: 12px; color: var(--accent-gold); }
        
        .game-badge { position: absolute; top: 10px; right: 10px; background: var(--gradient-red); color: white; padding: 4px 8px; border-radius: 8px; font-size: 10px; font-weight: 700; animation: pulse 2s infinite; }
        @keyframes pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.1); } }
        
        .deposit-card { background: var(--bg-secondary); border: 1px solid var(--border-glass); border-radius: 20px; padding: 24px; margin-bottom: 12px; cursor: pointer; transition: all 0.3s; text-align: center; }
        .deposit-card:hover { border-color: rgba(255, 215, 0, 0.4); transform: translateY(-2px); box-shadow: 0 10px 25px rgba(0, 0, 0, 0.3); }
        .deposit-icon { font-size: 48px; margin-bottom: 12px; }
        .deposit-name { font-size: 18px; font-weight: 700; margin-bottom: 4px; }
        .deposit-desc { font-size: 13px; color: var(--text-secondary); }
        
        .profile-card { background: var(--bg-secondary); border: 1px solid var(--border-glass); border-radius: 20px; padding: 20px; margin-bottom: 12px; }
        .stat-row { display: flex; justify-content: space-between; align-items: center; padding: 14px 0; border-bottom: 1px solid var(--border-glass); }
        .stat-row:last-child { border-bottom: none; }
        .stat-label-profile { color: var(--text-secondary); font-size: 14px; }
        .stat-value-profile { font-weight: 700; font-size: 16px; }
        
        .profile-btn { background: var(--gradient-purple); color: white; border: none; padding: 16px; border-radius: 14px; font-size: 15px; font-weight: 700; cursor: pointer; width: 100%; margin-top: 12px; text-transform: uppercase; letter-spacing: 0.5px; font-family: 'Inter', sans-serif; box-shadow: var(--shadow-glow-purple); transition: all 0.3s; }
        .profile-btn:hover { transform: translateY(-2px); }
        .profile-btn.blue { background: var(--gradient-blue); box-shadow: 0 0 20px rgba(59, 130, 246, 0.3); }
        
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0, 0, 0, 0.95); z-index: 1000; backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); align-items: center; justify-content: center; }
        .modal.active { display: flex; }
        
        .modal-content { background: var(--bg-secondary); border: 1px solid var(--border-glass); border-radius: 24px; padding: 24px; width: 90%; max-width: 400px; text-align: center; position: relative; animation: modalIn 0.3s ease; }
        @keyframes modalIn { from { transform: scale(0.9); opacity: 0; } to { transform: scale(1); opacity: 1; } }
        
        .modal-close { position: absolute; top: 16px; right: 16px; background: rgba(255, 255, 255, 0.1); border: none; color: white; width: 36px; height: 36px; border-radius: 50%; font-size: 18px; cursor: pointer; display: flex; align-items: center; justify-content: center; font-family: 'Inter', sans-serif; transition: all 0.3s; }
        .modal-close:hover { background: rgba(255, 45, 85, 0.3); }
        
        .modal-title { font-size: 24px; font-weight: 800; margin-bottom: 24px; background: var(--gradient-gold); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
        
        .slot-container { display: flex; gap: 12px; justify-content: center; margin: 24px 0; }
        .slot-reel { width: 80px; height: 80px; background: rgba(255, 255, 255, 0.05); border: 2px solid var(--border-glass); border-radius: 16px; display: flex; align-items: center; justify-content: center; font-size: 36px; transition: all 0.1s; }
        .slot-reel.spinning { animation: reelSpin 0.1s linear infinite; border-color: var(--accent-gold); }
        @keyframes reelSpin { 0% { transform: translateY(-10px); } 50% { transform: translateY(10px); } 100% { transform: translateY(-10px); } }
        
        .roulette-wheel { width: 200px; height: 200px; border-radius: 50%; background: conic-gradient(#ff2d55 0deg 36deg, #000 36deg 72deg, #ff2d55 72deg 108deg, #000 108deg 144deg, #ff2d55 144deg 180deg, #000 180deg 216deg, #ff2d55 216deg 252deg, #000 252deg 288deg, #ff2d55 288deg 324deg, #000 324deg 360deg); margin: 24px auto; transition: transform 3s cubic-bezier(0.17, 0.67, 0.12, 0.99); display: flex; align-items: center; justify-content: center; box-shadow: 0 0 30px rgba(255, 45, 85, 0.2); }
        .roulette-center { width: 60px; height: 60px; background: var(--bg-primary); border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 24px; font-weight: 700; color: var(--accent-gold); border: 2px solid var(--border-glass); }
        
        .game-btn { background: var(--gradient-purple); color: white; border: none; padding: 16px; border-radius: 16px; font-size: 16px; font-weight: 700; cursor: pointer; width: 100%; margin-top: 16px; text-transform: uppercase; letter-spacing: 1px; box-shadow: var(--shadow-glow-purple); font-family: 'Inter', sans-serif; transition: all 0.3s; }
        .game-btn:hover { transform: translateY(-2px); }
        
        .result-banner { padding: 16px; border-radius: 16px; margin: 16px 0; font-weight: 700; font-size: 18px; animation: fadeIn 0.5s ease; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(-10px); } to { opacity: 1; transform: translateY(0); } }
        .result-win { background: rgba(16, 185, 129, 0.2); border: 1px solid rgba(16, 185, 129, 0.4); color: #10b981; }
        .result-lose { background: rgba(255, 45, 85, 0.2); border: 1px solid rgba(255, 45, 85, 0.4); color: #ff2d55; }
        
        /* Стили модального окна пополнения */
        .deposit-modal-icon { font-size: 60px; margin-bottom: 16px; }
        .deposit-modal-title { font-size: 20px; font-weight: 700; margin-bottom: 8px; }
        .deposit-modal-subtitle { font-size: 13px; color: var(--text-secondary); margin-bottom: 20px; }
        
        .amount-input { width: 100%; padding: 18px; background: rgba(255, 255, 255, 0.05); border: 2px solid var(--border-glass); border-radius: 16px; color: white; font-size: 24px; font-weight: 700; text-align: center; font-family: 'Inter', sans-serif; transition: all 0.3s; outline: none; }
        .amount-input:focus { border-color: var(--accent-gold); box-shadow: var(--shadow-glow-gold); }
        .amount-input::placeholder { color: rgba(255, 255, 255, 0.2); }
        .amount-currency-label { font-size: 14px; color: var(--accent-gold); font-weight: 600; margin-bottom: 4px; }
        .min-amount-hint { font-size: 11px; color: var(--text-secondary); margin-bottom: 16px; }
        
        .quick-amounts { display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap; }
        .quick-amount-btn { flex: 1; min-width: 55px; padding: 10px; border-radius: 12px; border: 1px solid var(--border-glass); background: rgba(255, 255, 255, 0.05); color: white; cursor: pointer; font-weight: 600; font-size: 13px; transition: all 0.3s; font-family: 'Inter', sans-serif; }
        .quick-amount-btn:hover { border-color: var(--accent-gold); background: rgba(255, 215, 0, 0.1); }
        
        .deposit-submit-btn { background: var(--gradient-gold); color: black; border: none; padding: 16px; border-radius: 16px; font-size: 16px; font-weight: 700; cursor: pointer; width: 100%; text-transform: uppercase; letter-spacing: 1px; font-family: 'Inter', sans-serif; transition: all 0.3s; }
        .deposit-submit-btn:hover { transform: translateY(-2px); box-shadow: var(--shadow-glow-gold); }
        .deposit-submit-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
        
        .error-message { color: var(--accent-red); font-size: 12px; margin-top: 4px; display: none; }
        .error-message.show { display: block; }
        
        .toast { position: fixed; top: 20px; left: 50%; transform: translateX(-50%); background: var(--bg-secondary); border: 1px solid var(--border-glass); border-radius: 16px; padding: 16px 24px; z-index: 2000; animation: slideDown 0.3s ease; text-align: center; font-weight: 600; font-size: 14px; backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px); box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5); max-width: 90%; white-space: pre-line; }
        @keyframes slideDown { from { transform: translate(-50%, -100%); opacity: 0; } to { transform: translate(-50%, 0); opacity: 1; } }
        
        .quick-stats { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-bottom: 16px; }
        .quick-stat { background: var(--bg-secondary); border: 1px solid var(--border-glass); border-radius: 12px; padding: 10px; text-align: center; }
        .quick-stat-value { font-size: 16px; font-weight: 700; color: var(--accent-gold); }
        .quick-stat-label { font-size: 10px; color: var(--text-secondary); text-transform: uppercase; }
    </style>
</head>
<body>
    <div class="particles" id="particles"></div>
    
    <div class="app-container">
        <div class="header">
            <div class="avatar" id="avatar">S</div>
            <div class="user-info">
                <div class="user-name" id="username">Player</div>
                <div class="user-status">👑 VIP Status</div>
            </div>
            <span style="font-size: 24px;">💎</span>
        </div>
        
        <div class="balance-card">
            <div class="balance-label">💰 ВАШ БАЛАНС</div>
            <div class="balance-row">
                <div class="balance-item">
                    <div class="balance-amount" id="tonBalance">0.00</div>
                    <div class="balance-currency">TON</div>
                </div>
                <div class="balance-divider"></div>
                <div class="balance-item">
                    <div class="balance-amount" id="starsBalance">0</div>
                    <div class="balance-currency">STARS</div>
                </div>
            </div>
        </div>
        
        <div class="quick-stats">
            <div class="quick-stat"><div class="quick-stat-value" id="quickWins">0</div><div class="quick-stat-label">🏆 Побед</div></div>
            <div class="quick-stat"><div class="quick-stat-value" id="quickGames">0</div><div class="quick-stat-label">🎮 Игр</div></div>
            <div class="quick-stat"><div class="quick-stat-value" id="quickRate">0%</div><div class="quick-stat-label">📊 Win Rate</div></div>
        </div>
        
        <div class="tabs">
            <button class="tab active" onclick="switchTab('games')">🎰 ИГРЫ</button>
            <button class="tab" onclick="switchTab('deposit')">💰 ПОПОЛНИТЬ</button>
            <button class="tab" onclick="switchTab('profile')">💼 ПРОФИЛЬ</button>
        </div>
        
        <div class="tab-content active" id="tab-games">
            <div class="currency-select">
                <button class="currency-btn active" onclick="selectCurrency('TON', this)">💎 TON</button>
                <button class="currency-btn" onclick="selectCurrency('STARS', this)">⭐ STARS</button>
            </div>
            <div class="games-grid">
                <div class="game-card" id="card-slots" onclick="openGame('slots')">
                    <div class="game-badge">HOT 🔥</div>
                    <div class="game-icon">🎰</div><div class="game-name">СЛОТЫ</div><div class="game-bet" id="slotsBet">1 TON</div>
                </div>
                <div class="game-card" id="card-roulette" onclick="openGame('roulette')">
                    <div class="game-icon">🎡</div><div class="game-name">РУЛЕТКА</div><div class="game-bet" id="rouletteBet">2 TON</div>
                </div>
                <div class="game-card" id="card-dice" onclick="openGame('dice')">
                    <div class="game-icon">🎲</div><div class="game-name">КОСТИ</div><div class="game-bet" id="diceBet">1.5 TON</div>
                </div>
                <div class="game-card" id="card-blackjack" onclick="openGame('blackjack')">
                    <div class="game-icon">🃏</div><div class="game-name">БЛЭКДЖЕК</div><div class="game-bet" id="blackjackBet">5 TON</div>
                </div>
            </div>
        </div>
        
        <div class="tab-content" id="tab-deposit">
            <div class="deposit-card" onclick="openDepositModal('TON')">
                <div class="deposit-icon">💎</div>
                <div class="deposit-name">ПОПОЛНИТЬ TON</div>
                <div class="deposit-desc">Криптовалюта • Минимум 1 TON</div>
                <div class="deposit-desc" style="margin-top:6px;color:var(--accent-gold);font-weight:600;">👆 НАЖМИ ДЛЯ ВВОДА СУММЫ</div>
            </div>
            <div class="deposit-card" onclick="openDepositModal('STARS')">
                <div class="deposit-icon">⭐</div>
                <div class="deposit-name">ПОПОЛНИТЬ STARS</div>
                <div class="deposit-desc">Звезды Telegram • Минимум 10 Stars</div>
                <div class="deposit-desc" style="margin-top:6px;color:var(--accent-gold);font-weight:600;">👆 НАЖМИ ДЛЯ ВВОДА СУММЫ</div>
            </div>
        </div>
        
        <div class="tab-content" id="tab-profile">
            <div class="profile-card">
                <div class="stat-row"><span class="stat-label-profile">💎 TON Баланс</span><span class="stat-value-profile" id="profTonBalance">0.00</span></div>
                <div class="stat-row"><span class="stat-label-profile">⭐ Stars Баланс</span><span class="stat-value-profile" id="profStarsBalance">0</span></div>
                <div class="stat-row"><span class="stat-label-profile">📥 Пополнено TON</span><span class="stat-value-profile" id="profDepositedTon">0.00</span></div>
                <div class="stat-row"><span class="stat-label-profile">📥 Пополнено Stars</span><span class="stat-value-profile" id="profDepositedStars">0</span></div>
                <div class="stat-row"><span class="stat-label-profile">🏆 Побед</span><span class="stat-value-profile" id="profWins">0</span></div>
                <div class="stat-row"><span class="stat-label-profile">🎮 Игр</span><span class="stat-value-profile" id="profGames">0</span></div>
                <div class="stat-row"><span class="stat-label-profile">📈 Win Rate</span><span class="stat-value-profile" id="profWinRate">0%</span></div>
            </div>
            <button class="profile-btn" onclick="handleWithdraw('TON')">💎 ВЫВЕСТИ TON</button>
            <button class="profile-btn blue" onclick="handleWithdraw('STARS')">⭐ ВЫВЕСТИ STARS</button>
        </div>
    </div>
    
    <!-- МОДАЛЬНОЕ ОКНО ПОПОЛНЕНИЯ -->
    <div class="modal" id="depositModal">
        <div class="modal-content">
            <button class="modal-close" onclick="closeDepositModal()">✕</button>
            <div class="deposit-modal-icon" id="depositModalIcon">💎</div>
            <div class="deposit-modal-title" id="depositModalTitle">Пополнение TON</div>
            <div class="deposit-modal-subtitle" id="depositModalSubtitle">Введите сумму пополнения</div>
            <input type="number" class="amount-input" id="depositAmount" placeholder="0" min="0" step="0.1" oninput="validateDepositAmount()">
            <div class="amount-currency-label" id="depositCurrencyLabel">TON</div>
            <div class="min-amount-hint" id="depositMinHint">Минимум: 1 TON</div>
            <div class="error-message" id="depositError">Введите сумму!</div>
            <div class="quick-amounts" id="quickAmounts"></div>
            <button class="deposit-submit-btn" id="depositSubmitBtn" onclick="submitDeposit()" disabled>💰 ПОПОЛНИТЬ</button>
        </div>
    </div>
    
    <!-- МОДАЛЬНЫЕ ОКНА ИГР -->
    <div class="modal" id="slotsModal">
        <div class="modal-content">
            <button class="modal-close" onclick="closeGame()">✕</button>
            <div class="modal-title">🎰 СЛОТЫ</div>
            <div class="slot-container"><div class="slot-reel" id="reel1">🍒</div><div class="slot-reel" id="reel2">🍋</div><div class="slot-reel" id="reel3">💎</div></div>
            <div id="slotsResult"></div>
            <button class="game-btn" onclick="spinSlots()">🎰 КРУТИТЬ (<span id="slotsBetAmount">1</span> <span id="slotsBetCurrency">TON</span>)</button>
        </div>
    </div>
    
    <div class="modal" id="rouletteModal">
        <div class="modal-content">
            <button class="modal-close" onclick="closeGame()">✕</button>
            <div class="modal-title">🎡 РУЛЕТКА</div>
            <div class="roulette-wheel" id="rouletteWheel"><div class="roulette-center">🎡</div></div>
            <div id="rouletteResult"></div>
            <button class="game-btn" onclick="spinRoulette()">🎡 КРУТИТЬ (<span id="rouletteBetAmount">2</span> <span id="rouletteBetCurrency">TON</span>)</button>
        </div>
    </div>
    
    <div class="modal" id="diceModal">
        <div class="modal-content">
            <button class="modal-close" onclick="closeGame()">✕</button>
            <div class="modal-title">🎲 КОСТИ</div>
            <div style="display:flex;gap:40px;justify-content:center;margin:24px 0;font-size:60px;">
                <div id="playerDice">🎲</div><div style="color:var(--text-secondary);">VS</div><div id="botDice">🎲</div>
            </div>
            <div id="diceResult"></div>
            <button class="game-btn" onclick="playDice()">🎲 БРОСИТЬ (<span id="diceBetAmount">1.5</span> <span id="diceBetCurrency">TON</span>)</button>
        </div>
    </div>
    
    <div class="modal" id="blackjackModal">
        <div class="modal-content">
            <button class="modal-close" onclick="closeGame()">✕</button>
            <div class="modal-title">🃏 БЛЭКДЖЕК</div>
            <div style="display:flex;justify-content:space-around;margin:24px 0;">
                <div style="text-align:center;"><div style="font-size:12px;color:var(--text-secondary);margin-bottom:8px;">ВАШИ КАРТЫ</div><div style="font-size:40px;" id="playerCards">🂠 🂠</div><div style="font-size:20px;font-weight:700;margin-top:8px;" id="playerScore">0</div></div>
                <div style="text-align:center;"><div style="font-size:12px;color:var(--text-secondary);margin-bottom:8px;">ДИЛЕР</div><div style="font-size:40px;" id="dealerCards">🂠 🂠</div><div style="font-size:20px;font-weight:700;margin-top:8px;" id="dealerScore">0</div></div>
            </div>
            <div id="blackjackResult"></div>
            <button class="game-btn" onclick="playBlackjack()">🃏 ИГРАТЬ (<span id="blackjackBetAmount">5</span> <span id="blackjackBetCurrency">TON</span>)</button>
        </div>
    </div>
    
    <div class="toast" id="toast" style="display:none;"></div>

    <script>
        const tg = window.Telegram.WebApp;
        tg.expand(); tg.ready();
        document.documentElement.style.backgroundColor = '#0a0a1a';
        
        const user = tg.initDataUnsafe?.user || {};
        const userId = user.id || 123456789;
        const username = user.username || user.first_name || 'Player';
        
        document.getElementById('username').textContent = username;
        document.getElementById('avatar').textContent = username.charAt(0).toUpperCase();
        
        const API_URL = '/api';
        let tonBalance = 100;
        let starsBalance = 1000;
        let depositedTon = 0;
        let depositedStars = 0;
        let totalWins = 0;
        let totalGames = 0;
        let currentCurrency = 'TON';
        let isSpinning = false;
        let depositType = 'TON';
        
        const bets = { TON: { slots: 1, roulette: 2, dice: 1.5, blackjack: 5 }, STARS: { slots: 10, roulette: 20, dice: 15, blackjack: 50 } };
        const slotSymbols = ["🍒", "🍋", "🔔", "💎", "7️⃣", "🍇", "🎯", "🌟"];
        
        // Частицы фона
        function createParticles() {
            const container = document.getElementById('particles');
            for (let i = 0; i < 25; i++) {
                const p = document.createElement('div');
                p.className = 'particle';
                p.style.left = Math.random() * 100 + '%';
                p.style.animationDelay = Math.random() * 8 + 's';
                p.style.animationDuration = (Math.random() * 6 + 6) + 's';
                container.appendChild(p);
            }
        }
        
        function showToast(msg) {
            const toast = document.getElementById('toast');
            toast.textContent = msg; toast.style.display = 'block';
            clearTimeout(toast._timeout);
            toast._timeout = setTimeout(() => { toast.style.display = 'none'; }, 3000);
        }
        
        function getBalance() { return currentCurrency === 'TON' ? tonBalance : starsBalance; }
        function getMinBet(game) { return bets[currentCurrency][game]; }
        
        // Загрузка данных с сервера
        async function loadUserData() {
            try {
                const response = await fetch(`${API_URL}/user/${userId}`);
                const data = await response.json();
                tonBalance = data.balance_ton || 100;
                starsBalance = data.balance_stars || 1000;
                depositedTon = data.deposited_ton || 0;
                depositedStars = data.deposited_stars || 0;
                totalWins = data.total_wins || 0;
                totalGames = data.total_games || 0;
                updateAllUI();
            } catch (error) {
                console.log('Using demo data');
                updateAllUI();
            }
        }
        
        function updateAllUI() {
            document.getElementById('tonBalance').textContent = tonBalance.toFixed(2);
            document.getElementById('starsBalance').textContent = starsBalance;
            document.getElementById('quickWins').textContent = totalWins;
            document.getElementById('quickGames').textContent = totalGames;
            document.getElementById('quickRate').textContent = totalGames > 0 ? Math.round((totalWins / totalGames) * 100) + '%' : '0%';
            document.getElementById('profTonBalance').textContent = tonBalance.toFixed(2);
            document.getElementById('profStarsBalance').textContent = starsBalance;
            document.getElementById('profDepositedTon').textContent = depositedTon.toFixed(2);
            document.getElementById('profDepositedStars').textContent = depositedStars;
            document.getElementById('profWins').textContent = totalWins;
            document.getElementById('profGames').textContent = totalGames;
            document.getElementById('profWinRate').textContent = totalGames > 0 ? Math.round((totalWins / totalGames) * 100) + '%' : '0%';
            
            document.querySelectorAll('.game-bet').forEach(el => {
                const game = el.id.replace('Bet', '');
                el.textContent = bets[currentCurrency][game] + ' ' + currentCurrency;
            });
            
            updateGameCards();
            
            document.getElementById('slotsBetAmount').textContent = getMinBet('slots');
            document.getElementById('slotsBetCurrency').textContent = currentCurrency;
            document.getElementById('rouletteBetAmount').textContent = getMinBet('roulette');
            document.getElementById('rouletteBetCurrency').textContent = currentCurrency;
            document.getElementById('diceBetAmount').textContent = getMinBet('dice');
            document.getElementById('diceBetCurrency').textContent = currentCurrency;
            document.getElementById('blackjackBetAmount').textContent = getMinBet('blackjack');
            document.getElementById('blackjackBetCurrency').textContent = currentCurrency;
        }
        
        function updateGameCards() {
            const balance = getBalance();
            ['slots', 'roulette', 'dice', 'blackjack'].forEach(game => {
                const card = document.getElementById(`card-${game}`);
                const minBet = bets[currentCurrency][game];
                if (balance < minBet) card.classList.add('disabled');
                else card.classList.remove('disabled');
            });
        }
        
        function switchTab(tabName) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            event.target.classList.add('active');
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            document.getElementById(`tab-${tabName}`).classList.add('active');
            if (tabName === 'profile') loadUserData();
        }
        
        function selectCurrency(currency, btn) {
            currentCurrency = currency;
            document.querySelectorAll('.currency-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            updateAllUI();
        }
        
        function openGame(game) {
            const balance = getBalance();
            const minBet = getMinBet(game);
            if (balance < minBet) { showToast(`❌ Недостаточно ${currentCurrency}! Нужно: ${minBet} ${currentCurrency}`); return; }
            document.getElementById(`${game}Result`).innerHTML = '';
            document.getElementById(`${game}Modal`).classList.add('active');
            document.body.style.overflow = 'hidden';
        }
        
        function closeGame() {
            document.querySelectorAll('.modal').forEach(m => { if (m.id !== 'depositModal') m.classList.remove('active'); });
            document.body.style.overflow = 'auto';
            isSpinning = false;
        }
        
        // ====== МОДАЛЬНОЕ ОКНО ПОПОЛНЕНИЯ ======
        function openDepositModal(type) {
            depositType = type;
            document.getElementById('depositModalIcon').textContent = type === 'TON' ? '💎' : '⭐';
            document.getElementById('depositModalTitle').textContent = type === 'TON' ? 'Пополнение TON' : 'Пополнение Stars';
            document.getElementById('depositModalSubtitle').textContent = type === 'TON' ? 'Введите сумму в TON' : 'Введите сумму в Stars';
            document.getElementById('depositCurrencyLabel').textContent = type;
            document.getElementById('depositMinHint').textContent = type === 'TON' ? 'Минимум: 1 TON' : 'Минимум: 10 Stars';
            document.getElementById('depositAmount').value = '';
            document.getElementById('depositAmount').step = type === 'TON' ? '0.1' : '1';
            document.getElementById('depositError').classList.remove('show');
            document.getElementById('depositSubmitBtn').disabled = true;
            
            const quickAmounts = document.getElementById('quickAmounts');
            if (type === 'TON') {
                quickAmounts.innerHTML = `
                    <button class="quick-amount-btn" onclick="setDepositAmount(1)">1 TON</button>
                    <button class="quick-amount-btn" onclick="setDepositAmount(5)">5 TON</button>
                    <button class="quick-amount-btn" onclick="setDepositAmount(10)">10 TON</button>
                    <button class="quick-amount-btn" onclick="setDepositAmount(50)">50 TON</button>
                    <button class="quick-amount-btn" onclick="setDepositAmount(100)">100 TON</button>`;
            } else {
                quickAmounts.innerHTML = `
                    <button class="quick-amount-btn" onclick="setDepositAmount(10)">10 ⭐</button>
                    <button class="quick-amount-btn" onclick="setDepositAmount(50)">50 ⭐</button>
                    <button class="quick-amount-btn" onclick="setDepositAmount(100)">100 ⭐</button>
                    <button class="quick-amount-btn" onclick="setDepositAmount(500)">500 ⭐</button>
                    <button class="quick-amount-btn" onclick="setDepositAmount(1000)">1000 ⭐</button>`;
            }
            
            document.getElementById('depositModal').classList.add('active');
            document.body.style.overflow = 'hidden';
            setTimeout(() => document.getElementById('depositAmount').focus(), 300);
        }
        
        function closeDepositModal() {
            document.getElementById('depositModal').classList.remove('active');
            document.body.style.overflow = 'auto';
        }
        
        function setDepositAmount(amount) {
            document.getElementById('depositAmount').value = amount;
            validateDepositAmount();
        }
        
        function validateDepositAmount() {
            const input = document.getElementById('depositAmount');
            const error = document.getElementById('depositError');
            const submitBtn = document.getElementById('depositSubmitBtn');
            const value = parseFloat(input.value);
            const min = depositType === 'TON' ? 1 : 10;
            
            if (isNaN(value) || value < min) {
                error.textContent = depositType === 'TON' ? 'Минимальная сумма: 1 TON' : 'Минимальная сумма: 10 Stars';
                error.classList.add('show');
                submitBtn.disabled = true;
            } else {
                error.classList.remove('show');
                submitBtn.disabled = false;
            }
        }
        
        function submitDeposit() {
            const value = parseFloat(document.getElementById('depositAmount').value);
            const min = depositType === 'TON' ? 1 : 10;
            if (isNaN(value) || value < min) { showToast('❌ Введите корректную сумму!'); return; }
            
            if (depositType === 'TON') {
                tonBalance += value;
                depositedTon += value;
                // В реальной версии: открываем чат с ботом для оплаты
                tg.openTelegramLink('https://t.me/SyndromeCasinoBot');
                showToast(`✅ Пополнение TON\nСумма: ${value.toFixed(2)} TON\n\nПереходите в бота для оплаты`);
            } else {
                const intValue = Math.floor(value);
                starsBalance += intValue;
                depositedStars += intValue;
                tg.openTelegramLink('https://t.me/SyndromeCasinoBot');
                showToast(`✅ Пополнение Stars\nСумма: ${intValue} Stars\n\nПереходите в бота для оплаты`);
            }
            
            updateAllUI();
            closeDepositModal();
        }
        
        // ====== ИГРОВАЯ МЕХАНИКА ======
        async function makeBet(gameType) {
            const betAmount = getMinBet(gameType);
            const balance = getBalance();
            if (balance < betAmount) return null;
            if (isSpinning) return null;
            isSpinning = true;
            
            try {
                const response = await fetch(`${API_URL}/game`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ user_id: userId, game_type: gameType, bet_amount: betAmount, currency: currentCurrency })
                });
                const result = await response.json();
                
                if (result.error) { showToast(result.message || 'Ошибка!'); isSpinning = false; return null; }
                
                if (result.win) {
                    if (currentCurrency === 'TON') tonBalance += result.amount - betAmount;
                    else starsBalance += result.amount - betAmount;
                    totalWins++;
                } else {
                    if (currentCurrency === 'TON') tonBalance -= betAmount;
                    else starsBalance -= betAmount;
                }
                totalGames++;
                updateAllUI();
                isSpinning = false;
                return result;
            } catch (error) {
                // Демо-режим
                const win = Math.random() < 0.30;
                const multipliers = [1.5, 2, 3, 5, 10];
                const weights = [30, 30, 25, 10, 5];
                let totalW = weights.reduce((a,b) => a+b, 0);
                let r = Math.random() * totalW;
                let multiplier = 1.5;
                for (let i = 0; i < multipliers.length; i++) { r -= weights[i]; if (r <= 0) { multiplier = multipliers[i]; break; } }
                
                const winAmount = win ? betAmount * multiplier : 0;
                if (win) {
                    if (currentCurrency === 'TON') tonBalance += winAmount - betAmount;
                    else starsBalance += Math.floor(winAmount) - betAmount;
                    totalWins++;
                } else {
                    if (currentCurrency === 'TON') tonBalance -= betAmount;
                    else starsBalance -= betAmount;
                }
                totalGames++;
                updateAllUI();
                isSpinning = false;
                return { win, amount: winAmount, multiplier };
            }
        }
        
        async function spinSlots() {
            if (isSpinning) return;
            const reels = [document.getElementById('reel1'), document.getElementById('reel2'), document.getElementById('reel3')];
            reels.forEach(r => r.classList.add('spinning'));
            for (let i = 0; i < 20; i++) {
                reels.forEach(r => { r.textContent = slotSymbols[Math.floor(Math.random() * slotSymbols.length)]; });
                await new Promise(r => setTimeout(r, 80 + i * 5));
            }
            reels.forEach(r => r.classList.remove('spinning'));
            
            const result = await makeBet('slots');
            if (result && result.win) {
                reels.forEach(r => r.textContent = '💎');
                document.getElementById('slotsResult').innerHTML = `<div class="result-banner result-win">🎉 ДЖЕКПОТ!<br>+${result.amount.toFixed(2)} ${currentCurrency} (x${result.multiplier})</div>`;
                showToast(`🎉 +${result.amount.toFixed(2)} ${currentCurrency}!`);
            } else if (result) {
                document.getElementById('slotsResult').innerHTML = `<div class="result-banner result-lose">😢 Проигрыш: -${getMinBet('slots')} ${currentCurrency}</div>`;
            }
        }
        
        async function spinRoulette() {
            if (isSpinning) return;
            const wheel = document.getElementById('rouletteWheel');
            wheel.style.transform = `rotate(${(5 + Math.floor(Math.random() * 5)) * 360 + Math.floor(Math.random() * 360)}deg)`;
            await new Promise(r => setTimeout(r, 3000));
            
            const result = await makeBet('roulette');
            if (result && result.win) {
                document.getElementById('rouletteResult').innerHTML = `<div class="result-banner result-win">🎉 ПОБЕДА! +${result.amount.toFixed(2)} ${currentCurrency}</div>`;
                showToast(`🎉 +${result.amount.toFixed(2)} ${currentCurrency}!`);
            } else if (result) {
                document.getElementById('rouletteResult').innerHTML = `<div class="result-banner result-lose">😢 Мимо! -${getMinBet('roulette')} ${currentCurrency}</div>`;
            }
            setTimeout(() => { wheel.style.transition = 'none'; wheel.style.transform = 'rotate(0deg)'; setTimeout(() => { wheel.style.transition = 'transform 3s cubic-bezier(0.17, 0.67, 0.12, 0.99)'; }, 100); }, 500);
        }
        
        async function playDice() {
            if (isSpinning) return;
            const diceFaces = ['⚀', '⚁', '⚂', '⚃', '⚄', '⚅'];
            const pd = document.getElementById('playerDice'), bd = document.getElementById('botDice');
            for (let i = 0; i < 10; i++) {
                pd.textContent = diceFaces[Math.floor(Math.random() * 6)];
                bd.textContent = diceFaces[Math.floor(Math.random() * 6)];
                await new Promise(r => setTimeout(r, 100));
            }
            const result = await makeBet('dice');
            const pr = Math.floor(Math.random() * 6) + 1, br = Math.floor(Math.random() * 6) + 1;
            pd.textContent = diceFaces[pr - 1]; bd.textContent = diceFaces[br - 1];
            if (result && result.win) {
                document.getElementById('diceResult').innerHTML = `<div class="result-banner result-win">🎉 Вы: ${pr} | Бот: ${br}<br>+${result.amount.toFixed(2)} ${currentCurrency}</div>`;
                showToast(`🎉 +${result.amount.toFixed(2)} ${currentCurrency}!`);
            } else if (result) {
                document.getElementById('diceResult').innerHTML = `<div class="result-banner result-lose">😢 Вы: ${pr} | Бот: ${br}<br>-${getMinBet('dice')} ${currentCurrency}</div>`;
            }
        }
        
        async function playBlackjack() {
            if (isSpinning) return;
            const ps = Math.floor(Math.random() * 8) + 14, ds = Math.floor(Math.random() * 8) + 14;
            document.getElementById('playerScore').textContent = ps;
            document.getElementById('dealerScore').textContent = '?';
            document.getElementById('playerCards').textContent = '🂡 🂨';
            document.getElementById('dealerCards').textContent = '🂠 🂠';
            await new Promise(r => setTimeout(r, 1500));
            document.getElementById('dealerScore').textContent = ds;
            document.getElementById('dealerCards').textContent = '🂡 🂩';
            
            const result = await makeBet('blackjack');
            if (result && result.win) {
                document.getElementById('blackjackResult').innerHTML = `<div class="result-banner result-win">🎉 Вы: ${ps} | Дилер: ${ds}<br>+${result.amount.toFixed(2)} ${currentCurrency}</div>`;
                showToast(`🎉 +${result.amount.toFixed(2)} ${currentCurrency}!`);
            } else if (result) {
                document.getElementById('blackjackResult').innerHTML = `<div class="result-banner result-lose">😢 Вы: ${ps} | Дилер: ${ds}<br>-${getMinBet('blackjack')} ${currentCurrency}</div>`;
            }
        }
        
        function handleWithdraw(type) {
            if (type === 'TON') {
                tg.openTelegramLink('https://t.me/SyndromeCasinoBot');
                showToast('📤 Для вывода TON отправьте боту:\n/withdraw СУММА КОШЕЛЕК\n\nМинимум: 10 TON');
            } else {
                showToast('📤 Вывод Stars доступен от 100 Stars\n\nОбратитесь в поддержку');
            }
        }
        
        // Закрытие модалок по клику вне
        document.querySelectorAll('.modal').forEach(modal => {
            modal.addEventListener('click', function(e) {
                if (e.target === this) {
                    if (this.id === 'depositModal') closeDepositModal();
                    else closeGame();
                }
            });
        });
        
        document.getElementById('depositAmount').addEventListener('keypress', function(e) {
            if (e.key === 'Enter' && !document.getElementById('depositSubmitBtn').disabled) submitDeposit();
        });
        
        // Инициализация
        createParticles();
        loadUserData();
        setInterval(loadUserData, 30000);
        
        console.log('🎰 SYNDROME CASINO ACTIVE');
    </script>
</body>
</html>
'''

# =================================================================
# ЗАПУСК ДЛЯ RENDER
# =================================================================
async def main():
    conn = init_db()
    conn.close()
    print("✅ База готова")
    
    webhook_url = f"https://{RENDER_URL}/webhook"
    await bot.set_webhook(url=webhook_url, drop_pending_updates=True)
    print(f"✅ Webhook: {webhook_url}")
    
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(text="🎰 ИГРАТЬ", web_app=WebAppInfo(url=f"https://{RENDER_URL}"))
    )
    await bot.set_my_commands([
        BotCommand(command="start", description="🚀 Запустить казино"),
        BotCommand(command="withdraw", description="💎 Вывести TON")
    ])
    
    print("🔥 SYNDROME CASINO АКТИВЕН!")
    print(f"🌐 URL: https://{RENDER_URL}")
    print("💰 Готов к приёму платежей!")

if __name__ == '__main__':
    import threading
    asyncio.run(main())
    
    port = int(os.environ.get('PORT', 8080))
    flask_app.run(host='0.0.0.0', port=port)
