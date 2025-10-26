import logging
import sqlite3
import os
import random
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен бота
BOT_TOKEN = "8338962499:AAF0KswedJ_LjBBexenXuymbozyS7xxiZmQ"
ADMIN_ID = 5818997833  # ← ЗАМЕНИ НА СВОЙ ID

# Глобальное соединение с базой данных
DB_CONNECTION = None


def get_db_connection():
    """Получаем соединение с базой данных"""
    global DB_CONNECTION
    if DB_CONNECTION is None:
        DB_CONNECTION = sqlite3.connect('game.db', check_same_thread=False, timeout=30)
        DB_CONNECTION.execute("PRAGMA journal_mode=WAL")
    return DB_CONNECTION


def init_db():
    """Инициализация базы данных"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Таблица игроков
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS players
                   (
                       user_id INTEGER PRIMARY KEY,
                       username TEXT,
                       nickname TEXT,
                       balance INTEGER DEFAULT 5000,
                       last_income_collection TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                   )
                   ''')

    # === БЕЗОПАСНОЕ ДОБАВЛЕНИЕ ПОЛЕЙ ===
    cursor.execute("PRAGMA table_info(players)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'last_box_open' not in columns:
        cursor.execute('ALTER TABLE players ADD COLUMN last_box_open TIMESTAMP')
    if 'referrer_id' not in columns:
        cursor.execute('ALTER TABLE players ADD COLUMN referrer_id INTEGER')

    # Таблица бизнесов
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS businesses
                   (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       name TEXT,
                       price INTEGER,
                       income INTEGER,
                       description TEXT
                   )
                   ''')

    # Таблица купленных бизнесов
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS player_businesses
                   (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       user_id INTEGER,
                       business_id INTEGER,
                       purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                       FOREIGN KEY (user_id) REFERENCES players (user_id),
                       FOREIGN KEY (business_id) REFERENCES businesses (id),
                       UNIQUE (user_id, business_id)
                   )
                   ''')

    # Таблица яиц
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS eggs
                   (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       name TEXT,
                       price INTEGER,
                       image_file_id TEXT,
                       description TEXT,
                       limit_count INTEGER,
                       current_count INTEGER DEFAULT 0,
                       base_price INTEGER,
                       last_restock TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                   )
                   ''')

    # Таблица купленных яиц
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS player_eggs
                   (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       user_id INTEGER,
                       egg_id INTEGER,
                       purchased_price INTEGER,
                       purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                       FOREIGN KEY (user_id) REFERENCES players (user_id),
                       FOREIGN KEY (egg_id) REFERENCES eggs (id)
                   )
                   ''')

    # Таблица друзей
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS friends
                   (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       user_id INTEGER,
                       friend_id INTEGER,
                       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                       UNIQUE (user_id, friend_id)
                   )
                   ''')

    # Таблица трейдов
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS trades
                   (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       from_user_id INTEGER,
                       to_user_id INTEGER,
                       item_type TEXT,
                       item_id INTEGER,
                       price INTEGER,
                       status TEXT DEFAULT 'pending',
                       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                   )
                   ''')

    # Таблица боксов
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS boxes
                   (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       name TEXT,
                       price INTEGER,
                       rewards TEXT
                   )
                   ''')

    # Таблица кредитов
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS loans
                   (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       user_id INTEGER,
                       amount INTEGER,
                       interest_rate INTEGER,
                       remaining_amount INTEGER,
                       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                       FOREIGN KEY (user_id) REFERENCES players (user_id)
                   )
                   ''')

    # Таблица кодов
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS promo_codes
                   (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       code TEXT UNIQUE,
                       reward_type TEXT,
                       reward_value INTEGER,
                       reward_item TEXT,
                       uses_left INTEGER,
                       expires_at TIMESTAMP,
                       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                   )
                   ''')

    # Таблица использованных кодов
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS used_codes
                   (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       user_id INTEGER,
                       code_id INTEGER,
                       used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                       FOREIGN KEY (user_id) REFERENCES players (user_id),
                       FOREIGN KEY (code_id) REFERENCES promo_codes (id),
                       UNIQUE (user_id, code_id)
                   )
                   ''')

    # Проверяем, нужно ли заполнить начальные данные
    cursor.execute('SELECT COUNT(*) FROM businesses')
    if cursor.fetchone()[0] == 0:
        businesses_data = [
            ("🏪 Ларёк с шаурмой", 5000, 1000, "Небольшой ларёк в проходном месте"),
            ("⛽ АЗС 42-й бензин", 25000, 5000, "Эксклюзивный бензин премиум-класса"),
            ("🏢 Офисный центр", 100000, 20000, "Айтишники работают 24/7"),
            ("🎮 Игровая студия", 500000, 100000, "Разрабатываем хайповые игры"),
            ("💻 IT Корпорация", 2000000, 400000, "Поглощаем стартапы за YAICи")
        ]
        cursor.executemany('INSERT INTO businesses (name, price, income, description) VALUES (?, ?, ?, ?)',
                           businesses_data)

    cursor.execute('SELECT COUNT(*) FROM eggs')
    if cursor.fetchone()[0] == 0:
        eggs_data = [
            ("🥚 Обычное яйцо", 2000, "", "Базовое яйцо с хорошим потенциалом роста. Отличный старт для коллекционера!",
             20, 0, 2000),
            ("🥚 Золотое яйцо", 8000, "", "Редкое золотое яйцо, блестит на солнце. Ценный актив для инвесторов!", 10, 0,
             8000),
            ("💎 Алмазное яйцо", 32000, "",
             "Эпическое алмазное яйцо исключительной редкости. Мечта каждого коллекционера!", 5, 0, 32000),
            ("🔥 Мемное яйцо", 100000, "", "Легендарное мемное яйцо с вирусным потенциалом! Ультра-редкий экземпляр!", 3,
             0, 100000)
        ]
        cursor.executemany(
            'INSERT INTO eggs (name, price, image_file_id, description, limit_count, current_count, base_price) VALUES (?, ?, ?, ?, ?, ?, ?)',
            eggs_data)
    else:
        cursor.execute('UPDATE eggs SET name = ?, description = ? WHERE name = ?',
                       ("🔥 Мемное яйцо", "Легендарное мемное яйцо с вирусным потенциалом! Ультра-редкий экземпляр!",
                        "Огненное яйцо"))

    # Заполняем боксы с пониженной везучестью
    cursor.execute('SELECT COUNT(*) FROM boxes')
    if cursor.fetchone()[0] == 0:
        boxes_data = [
            ("📦 Обычный бокс", 1000, "500-2000 YAIC|0-1 Обычных яиц|0-1 Золотых яиц"),
            ("🎁 Премиум бокс", 5000, "2000-8000 YAIC|1-2 Обычных яиц|0-1 Золотых яиц|0-1 Алмазных яиц"),
            ("📫 Легендарный бокс", 20000, "8000-20000 YAIC|0-1 Золотых яиц|0-1 Алмазных яиц|0-1 Мемных яиц")
        ]
        cursor.executemany('INSERT INTO boxes (name, price, rewards) VALUES (?, ?, ?)', boxes_data)

    conn.commit()
    print("База данных инициализирована")


# Функции для работы с базой данных
def get_player(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM players WHERE user_id = ?', (user_id,))
    return cursor.fetchone()


def create_player(user_id, username, nickname, referrer_id=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT OR IGNORE INTO players (user_id, username, nickname, balance, referrer_id) VALUES (?, ?, ?, 5000, ?)',
        (user_id, username, nickname, referrer_id))
    conn.commit()


def update_balance(user_id, amount):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE players SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()


def get_businesses():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM businesses')
    return cursor.fetchall()


def get_eggs():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM eggs')
    return cursor.fetchall()


def get_player_businesses(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
                   SELECT b.id, b.name, b.income, pb.purchased_at
                   FROM player_businesses pb
                            JOIN businesses b ON pb.business_id = b.id
                   WHERE pb.user_id = ?
                   ''', (user_id,))
    return cursor.fetchall()


def get_player_eggs(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
                   SELECT e.id, e.name, e.price, e.image_file_id, COUNT(pe.id), pe.purchased_price
                   FROM player_eggs pe
                            JOIN eggs e ON pe.egg_id = e.id
                   WHERE pe.user_id = ?
                   GROUP BY e.id
                   ''', (user_id,))
    return cursor.fetchall()


def get_top_players():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
                   SELECT p.nickname,
                          p.balance,
                          (SELECT SUM(b.income)
                           FROM player_businesses pb
                                    JOIN businesses b ON pb.business_id = b.id
                           WHERE pb.user_id = p.user_id) as income
                   FROM players p
                   ORDER BY p.balance DESC LIMIT 10
                   ''')
    return cursor.fetchall()


def update_egg_prices(egg_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT price FROM eggs WHERE id = ?', (egg_id,))
    current_price = cursor.fetchone()[0]
    new_price = int(current_price * 1.08)
    cursor.execute('UPDATE eggs SET price = ? WHERE id = ?', (new_price, egg_id))
    conn.commit()
    return new_price


def restock_eggs():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT last_restock FROM eggs LIMIT 1')
        result = cursor.fetchone()
        if result and result[0]:
            last_restock = datetime.fromisoformat(result[0])
            if datetime.now() - last_restock > timedelta(days=7):
                cursor.execute('UPDATE eggs SET current_count = 0, price = base_price, last_restock = ?',
                               (datetime.now(),))
                conn.commit()
                return True
    except Exception as e:
        print(f"Ошибка при проверке пополнения: {e}")
    return False


# Система друзей
def add_friend(user_id, friend_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT COUNT(*) FROM players WHERE user_id = ?', (friend_id,))
        if cursor.fetchone()[0] == 0:
            return False, "Пользователь с таким ID не найден"

        if user_id == friend_id:
            return False, "Нельзя добавить себя в друзья"

        cursor.execute('SELECT COUNT(*) FROM friends WHERE user_id = ? AND friend_id = ?', (user_id, friend_id))
        if cursor.fetchone()[0] > 0:
            return False, "Этот пользователь уже у вас в друзьях"

        cursor.execute('INSERT OR IGNORE INTO friends (user_id, friend_id) VALUES (?, ?)', (user_id, friend_id))
        cursor.execute('INSERT OR IGNORE INTO friends (user_id, friend_id) VALUES (?, ?)', (friend_id, user_id))
        conn.commit()
        return True, "Друг успешно добавлен!"
    except Exception as e:
        return False, f"Ошибка при добавлении друга: {e}"


def get_friends(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
                   SELECT p.user_id, p.nickname
                   FROM friends f
                            JOIN players p ON f.friend_id = p.user_id
                   WHERE f.user_id = ?
                   ''', (user_id,))
    return cursor.fetchall()


def remove_friend(user_id, friend_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM friends WHERE user_id = ? AND friend_id = ?', (user_id, friend_id))
    cursor.execute('DELETE FROM friends WHERE user_id = ? AND friend_id = ?', (friend_id, user_id))
    conn.commit()


# Система трейдов
def create_trade(from_user_id, to_user_id, item_type, item_id, price):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if item_type == 'egg':
            cursor.execute('SELECT COUNT(*) FROM player_eggs WHERE user_id = ? AND egg_id = ?', (from_user_id, item_id))
        elif item_type == 'business':
            cursor.execute('SELECT COUNT(*) FROM player_businesses WHERE user_id = ? AND business_id = ?',
                           (from_user_id, item_id))

        if cursor.fetchone()[0] == 0:
            return False

        cursor.execute(
            'INSERT INTO trades (from_user_id, to_user_id, item_type, item_id, price) VALUES (?, ?, ?, ?, ?)',
            (from_user_id, to_user_id, item_type, item_id, price))
        trade_id = cursor.lastrowid

        conn.commit()
        return trade_id
    except Exception as e:
        print(f"Ошибка создания трейда: {e}")
        return False


def get_pending_trades(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
                   SELECT t.id,
                          t.from_user_id,
                          t.to_user_id,
                          t.item_type,
                          t.item_id,
                          t.price,
                          p.nickname,
                          CASE
                              WHEN t.item_type = 'egg' THEN e.name
                              WHEN t.item_type = 'business' THEN b.name
                              END as item_name
                   FROM trades t
                            JOIN players p ON t.from_user_id = p.user_id
                            LEFT JOIN eggs e ON t.item_type = 'egg' AND t.item_id = e.id
                            LEFT JOIN businesses b ON t.item_type = 'business' AND t.item_id = b.id
                   WHERE t.to_user_id = ?
                     AND t.status = 'pending'
                   ''', (user_id,))
    return cursor.fetchall()


def accept_trade(trade_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT * FROM trades WHERE id = ?', (trade_id,))
        trade = cursor.fetchone()
        if not trade:
            return False

        trade_id, from_user_id, to_user_id, item_type, item_id, price, status, created_at = trade

        cursor.execute('SELECT balance FROM players WHERE user_id = ?', (to_user_id,))
        to_user_balance = cursor.fetchone()[0]

        if to_user_balance < price:
            return False

        if item_type == 'egg':
            cursor.execute('SELECT id FROM player_eggs WHERE user_id = ? AND egg_id = ? LIMIT 1',
                           (from_user_id, item_id))
            item_to_transfer = cursor.fetchone()
            if not item_to_transfer:
                return False

            cursor.execute('DELETE FROM player_eggs WHERE id = ?', (item_to_transfer[0],))
            cursor.execute('INSERT INTO player_eggs (user_id, egg_id, purchased_price) VALUES (?, ?, ?)',
                           (to_user_id, item_id, price))

        elif item_type == 'business':
            cursor.execute('SELECT id FROM player_businesses WHERE user_id = ? AND business_id = ?',
                           (from_user_id, item_id))
            item_to_transfer = cursor.fetchone()
            if not item_to_transfer:
                return False

            cursor.execute('DELETE FROM player_businesses WHERE id = ?', (item_to_transfer[0],))
            cursor.execute('INSERT INTO player_businesses (user_id, business_id) VALUES (?, ?)', (to_user_id, item_id))

        cursor.execute('UPDATE players SET balance = balance - ? WHERE user_id = ?', (price, to_user_id))
        cursor.execute('UPDATE players SET balance = balance + ? WHERE user_id = ?', (price, from_user_id))
        cursor.execute('UPDATE trades SET status = "accepted" WHERE id = ?', (trade_id,))

        conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка при принятии трейда: {e}")
        conn.rollback()
        return False


def reject_trade(trade_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE trades SET status = "rejected" WHERE id = ?', (trade_id,))
    conn.commit()


# Система боксов - С ПОНИЖЕННОЙ ВЕЗУЧЕСТЬЮ
def get_boxes():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM boxes')
    return cursor.fetchall()


def open_box(user_id, box_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT * FROM boxes WHERE id = ?', (box_id,))
        box = cursor.fetchone()
        if not box:
            return None

        box_id, name, price, rewards_str = box

        cursor.execute('SELECT balance FROM players WHERE user_id = ?', (user_id,))
        player = cursor.fetchone()
        if not player:
            return None

        balance = player[0]

        if balance < price:
            return None

        # Списываем стоимость бокса
        cursor.execute('UPDATE players SET balance = balance - ? WHERE user_id = ?', (price, user_id))

        # Генерируем награды с пониженной везучестью
        rewards = []
        rewards_config = rewards_str.split('|')

        for reward in rewards_config:
            if 'YAIC' in reward:
                # Награда в YAIC
                yaic_range = reward.split()[0]
                min_yaic, max_yaic = map(int, yaic_range.split('-'))
                yaic_reward = random.randint(min_yaic, max_yaic)
                cursor.execute('UPDATE players SET balance = balance + ? WHERE user_id = ?', (yaic_reward, user_id))
                rewards.append(f"{yaic_reward} YAIC")

            elif 'яйц' in reward.lower():
                # Награда в яйцах с пониженной вероятностью
                egg_range = reward.split()[0]
                min_eggs, max_eggs = map(int, egg_range.split('-'))

                # Определяем тип яйца
                if 'Обычных' in reward:
                    egg_type = "🥚 Обычное яйцо"
                    egg_chance = 60  # 60% шанс
                elif 'Золотых' in reward:
                    egg_type = "🥚 Золотое яйцо"
                    egg_chance = 30  # 30% шанс
                elif 'Алмазных' in reward:
                    egg_type = "💎 Алмазное яйцо"
                    egg_chance = 15  # 15% шанс
                elif 'Мемных' in reward:  # ← ИСПРАВЛЕНО: 'в' на 'in'
                    egg_type = "🔥 Мемное яйцо"
                    egg_chance = 5  # 5% шанс
                else:
                    continue

                # Проверяем шанс выпадения
                if random.randint(1, 100) <= egg_chance:
                    cursor.execute('SELECT id FROM eggs WHERE name LIKE ?', (f'%{egg_type}%',))
                    egg_result = cursor.fetchone()
                    if egg_result:
                        egg_id = egg_result[0]
                        num_eggs = random.randint(min_eggs, max_eggs)

                        # Проверяем лимит яиц
                        cursor.execute('SELECT current_count, limit_count FROM eggs WHERE id = ?', (egg_id,))
                        egg_info = cursor.fetchone()
                        if egg_info:
                            current_count, limit_count = egg_info
                            if current_count + num_eggs <= limit_count:
                                for _ in range(num_eggs):
                                    cursor.execute(
                                        'INSERT INTO player_eggs (user_id, egg_id, purchased_price) VALUES (?, ?, 0)',
                                        (user_id, egg_id))
                                # Обновляем счетчик купленных яиц
                                cursor.execute('UPDATE eggs SET current_count = current_count + ? WHERE id = ?',
                                               (num_eggs, egg_id))
                                rewards.append(f"{num_eggs} {egg_type}")

        conn.commit()
        return rewards if rewards else ["Ничего не выпало"]

    except Exception as e:
        print(f"Ошибка открытия бокса: {e}")
        conn.rollback()
        return None


# Функция сбора дохода - ИСПРАВЛЕННАЯ (проверка наличия бизнесов)
def collect_income(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Проверяем есть ли у игрока бизнесы
        cursor.execute('SELECT COUNT(*) FROM player_businesses WHERE user_id = ?', (user_id,))
        business_count = cursor.fetchone()[0]

        if business_count == 0:
            return 0, "no_businesses"

        cursor.execute('SELECT last_income_collection FROM players WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        if not result or not result[0]:
            return 0, "ready"

        last_collection = datetime.fromisoformat(result[0])
        time_passed = datetime.now() - last_collection
        minutes_passed = time_passed.total_seconds() / 60

        # Проверяем, прошло ли 30 минут
        if minutes_passed < 30:
            minutes_remaining = 30 - int(minutes_passed)
            return 0, f"wait_{minutes_remaining}"

        cursor.execute('''
                       SELECT SUM(b.income)
                       FROM player_businesses pb
                                JOIN businesses b ON pb.business_id = b.id
                       WHERE pb.user_id = ?
                       ''', (user_id,))

        total_income = cursor.fetchone()[0] or 0

        if total_income > 0:
            cursor.execute('UPDATE players SET balance = balance + ?, last_income_collection = ? WHERE user_id = ?',
                           (total_income, datetime.now(), user_id))
            conn.commit()

        return total_income, "ready"

    except Exception as e:
        print(f"Ошибка сбора дохода: {e}")
        return 0, "error"


# Функция продажи бизнеса
def sell_business(user_id, business_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            'SELECT b.price FROM player_businesses pb JOIN businesses b ON pb.business_id = b.id WHERE pb.user_id = ? AND pb.business_id = ?',
            (user_id, business_id))
        result = cursor.fetchone()
        if not result:
            return False

        sell_price = int(result[0] * 0.7)  # 70% от исходной цены

        cursor.execute('DELETE FROM player_businesses WHERE user_id = ? AND business_id = ?', (user_id, business_id))
        cursor.execute('UPDATE players SET balance = balance + ? WHERE user_id = ?', (sell_price, user_id))

        conn.commit()
        return sell_price

    except Exception as e:
        print(f"Ошибка продажи бизнеса: {e}")
        return False


# Функция продажи яйца
def sell_egg(user_id, egg_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT id FROM player_eggs WHERE user_id = ? AND egg_id = ? LIMIT 1', (user_id, egg_id))
        result = cursor.fetchone()
        if not result:
            return False

        cursor.execute('SELECT price FROM eggs WHERE id = ?', (egg_id,))
        current_price = cursor.fetchone()[0]
        sell_price = int(current_price * 0.8)  # 80% от текущей цены

        cursor.execute('DELETE FROM player_eggs WHERE id = ?', (result[0],))
        cursor.execute('UPDATE players SET balance = balance + ? WHERE user_id = ?', (sell_price, user_id))

        conn.commit()
        return sell_price

    except Exception as e:
        print(f"Ошибка продажи яйца: {e}")
        return False


# СИСТЕМА КРЕДИТОВ
def take_loan(user_id, amount):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Проверяем есть ли уже активный кредит
        cursor.execute('SELECT COUNT(*) FROM loans WHERE user_id = ? AND remaining_amount > 0', (user_id,))
        if cursor.fetchone()[0] > 0:
            return False, "У вас уже есть активный кредит!"

        # Максимальный кредит - 50,000 YAIC
        if amount > 50000:
            return False, "Максимальная сумма кредита: 50,000 YAIC"

        if amount < 1000:
            return False, "Минимальная сумма кредита: 1,000 YAIC"

        # Процентная ставка 20%
        interest_rate = 20
        total_to_repay = amount + (amount * interest_rate // 100)

        # Выдаем кредит
        cursor.execute('UPDATE players SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
        cursor.execute('INSERT INTO loans (user_id, amount, interest_rate, remaining_amount) VALUES (?, ?, ?, ?)',
                       (user_id, amount, interest_rate, total_to_repay))

        conn.commit()
        return True, f"💰 Кредит выдан!\n\n💵 Получено: {amount} YAIC\n📊 К возврату: {total_to_repay} YAIC\n📈 Процент: {interest_rate}%"

    except Exception as e:
        print(f"Ошибка выдачи кредита: {e}")
        return False, "❌ Ошибка при выдаче кредита"


def repay_loan(user_id, amount):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Получаем информацию о кредите
        cursor.execute('SELECT id, remaining_amount FROM loans WHERE user_id = ? AND remaining_amount > 0', (user_id,))
        loan = cursor.fetchone()

        if not loan:
            return False, "❌ У вас нет активных кредитов"

        loan_id, remaining_amount = loan

        # Проверяем баланс
        cursor.execute('SELECT balance FROM players WHERE user_id = ?', (user_id,))
        balance = cursor.fetchone()[0]

        if balance < amount:
            return False, f"❌ Недостаточно средств! Нужно: {amount} YAIC"

        if amount > remaining_amount:
            amount = remaining_amount

        # Списание средств и обновление кредита
        cursor.execute('UPDATE players SET balance = balance - ? WHERE user_id = ?', (amount, user_id))
        cursor.execute('UPDATE loans SET remaining_amount = remaining_amount - ? WHERE id = ?', (amount, loan_id))

        conn.commit()

        new_remaining = remaining_amount - amount
        if new_remaining <= 0:
            return True, f"✅ Кредит полностью погашен!"
        else:
            return True, f"💵 Внесено: {amount} YAIC\n📊 Осталось выплатить: {new_remaining} YAIC"

    except Exception as e:
        print(f"Ошибка погашения кредита: {e}")
        return False, "❌ Ошибка при погашении кредита"


def get_loan_info(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        'SELECT amount, interest_rate, remaining_amount FROM loans WHERE user_id = ? AND remaining_amount > 0',
        (user_id,))
    loan = cursor.fetchone()

    if loan:
        amount, interest_rate, remaining = loan
        return {
            'has_loan': True,
            'amount': amount,
            'interest_rate': interest_rate,
            'remaining': remaining
        }
    else:
        return {'has_loan': False}


# === СИСТЕМА КОДОВ ===
def create_promo_code(code, reward_type, reward_value, reward_item, uses_left, expires_days=7):
    conn = get_db_connection()
    cursor = conn.cursor()

    expires_at = datetime.now() + timedelta(days=expires_days)

    try:
        cursor.execute('''
            INSERT INTO promo_codes (code, reward_type, reward_value, reward_item, uses_left, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (code, reward_type, reward_value, reward_item, uses_left, expires_at))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def use_promo_code(user_id, code):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Проверяем существование кода
        cursor.execute('''
            SELECT id, reward_type, reward_value, reward_item, uses_left, expires_at 
            FROM promo_codes 
            WHERE code = ? AND uses_left > 0 AND expires_at > ?
        ''', (code, datetime.now()))

        promo = cursor.fetchone()
        if not promo:
            return False, "❌ Код не найден, истек или уже использован!"

        code_id, reward_type, reward_value, reward_item, uses_left, expires_at = promo

        # Проверяем, использовал ли уже пользователь этот код
        cursor.execute('SELECT 1 FROM used_codes WHERE user_id = ? AND code_id = ?', (user_id, code_id))
        if cursor.fetchone():
            return False, "❌ Вы уже использовали этот код!"

        # Выдаем награду
        if reward_type == 'yaic':
            update_balance(user_id, reward_value)
            reward_text = f"💵 {reward_value} YAIC"
        elif reward_type == 'egg':
            # Находим ID яйца по имени
            cursor.execute('SELECT id FROM eggs WHERE name = ?', (reward_item,))
            egg_result = cursor.fetchone()
            if egg_result:
                egg_id = egg_result[0]
                cursor.execute('INSERT INTO player_eggs (user_id, egg_id, purchased_price) VALUES (?, ?, 0)',
                               (user_id, egg_id))
                reward_text = f"🥚 {reward_item}"
            else:
                return False, "❌ Ошибка: указанное яйцо не найдено"
        elif reward_type == 'business':
            # Находим ID бизнеса по имени
            cursor.execute('SELECT id FROM businesses WHERE name = ?', (reward_item,))
            business_result = cursor.fetchone()
            if business_result:
                business_id = business_result[0]
                cursor.execute('INSERT INTO player_businesses (user_id, business_id) VALUES (?, ?)',
                               (user_id, business_id))
                reward_text = f"🏢 {reward_item}"
            else:
                return False, "❌ Ошибка: указанный бизнес не найден"
        else:
            return False, "❌ Неизвестный тип награды"

        # Уменьшаем количество использований и отмечаем использование
        cursor.execute('UPDATE promo_codes SET uses_left = uses_left - 1 WHERE id = ?', (code_id,))
        cursor.execute('INSERT INTO used_codes (user_id, code_id) VALUES (?, ?)', (user_id, code_id))

        conn.commit()
        return True, f"🎉 Поздравляем! Вы получили: {reward_text}"

    except Exception as e:
        print(f"Ошибка использования кода: {e}")
        return False, "❌ Ошибка при использовании кода"


def get_active_codes():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT code, reward_type, reward_value, reward_item, uses_left, expires_at
        FROM promo_codes 
        WHERE uses_left > 0 AND expires_at > ?
    ''', (datetime.now(),))
    return cursor.fetchall()


# === РЕФЕРАЛКА ===
def process_referral(new_user_id, referrer_id):
    if referrer_id and referrer_id != new_user_id:
        cursor = get_db_connection().cursor()
        cursor.execute('SELECT 1 FROM players WHERE user_id = ?', (referrer_id,))
        if cursor.fetchone():
            update_balance(new_user_id, 5000)
            update_balance(referrer_id, 5000)
            return True
    return False


# === КУЛДАУН БОКСОВ ===
def can_open_box(user_id):
    player = get_player(user_id)
    if not player or not player[6]:  # last_box_open
        return True, None

    last_open = datetime.fromisoformat(player[6])
    time_passed = datetime.now() - last_open
    seconds_passed = time_passed.total_seconds()

    if seconds_passed < 120:  # 2 минуты = 120 секунд
        seconds_remaining = 120 - int(seconds_passed)
        return False, seconds_remaining

    return True, None


def set_box_cooldown(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE players SET last_box_open = ? WHERE user_id = ?', (datetime.now(), user_id))
    conn.commit()


# === АДМИН-КОМАНДЫ ===
async def admin_give_yaic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Только для админа!")
        return
    try:
        uid, amount = int(context.args[0]), int(context.args[1])
        update_balance(uid, amount)
        await update.message.reply_text(f"✅ Выдано {amount} YAIC игроку {uid}")
    except:
        await update.message.reply_text("❌ Использование: /give_yaic <id> <сумма>")


async def admin_create_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Только для админа!")
        return

    try:
        # /create_code код тип значение предмет использование
        code = context.args[0]
        reward_type = context.args[1]  # yaic, egg, business
        reward_value = int(context.args[2]) if reward_type == 'yaic' else 0
        reward_item = context.args[3] if reward_type in ['egg', 'business'] else ''
        uses_left = int(context.args[4])

        if create_promo_code(code, reward_type, reward_value, reward_item, uses_left):
            await update.message.reply_text(
                f"✅ Промокод создан!\nКод: {code}\nНаграда: {reward_type} {reward_value} {reward_item}\nИспользований: {uses_left}")
        else:
            await update.message.reply_text("❌ Ошибка: код уже существует!")

    except Exception as e:
        await update.message.reply_text(
            f"❌ Использование: /create_code <код> <yaic/egg/business> <значение> <предмет> <использования>\nПример: /create_code TEST123 yaic 5000 '' 100")


async def fix_nicknames(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Только для админа!")
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    # Находим игроков с None ником
    cursor.execute('SELECT user_id, username FROM players WHERE nickname IS NULL OR nickname = "None"')
    players = cursor.fetchall()

    fixed_count = 0
    for user_id, username in players:
        if username and username != "Неизвестно":
            new_nickname = f"@{username}"
        else:
            new_nickname = f"Игрок_{user_id}"

        cursor.execute('UPDATE players SET nickname = ? WHERE user_id = ?', (new_nickname, user_id))
        fixed_count += 1

    conn.commit()
    await update.message.reply_text(f"✅ Исправлено ников: {fixed_count}")


# Команда для загрузки картинок
async def upload_images(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Эта команда только для администратора!")
        return

    try:
        egg_files = ['egg1.png', 'egg2.png', 'egg3.png', 'egg4.png']
        file_ids = []

        for egg_file in egg_files:
            if os.path.exists(egg_file):
                with open(egg_file, 'rb') as photo:
                    message = await context.bot.send_photo(
                        chat_id=user_id,
                        photo=photo,
                        caption=f"Картинка для {egg_file}"
                    )
                    file_id = message.photo[-1].file_id
                    file_ids.append(file_id)
                    print(f"{egg_file}: {file_id}")
            else:
                print(f"Файл {egg_file} не найден")
                file_ids.append("")

        conn = get_db_connection()
        cursor = conn.cursor()

        eggs = get_eggs()
        for i, egg in enumerate(eggs):
            if i < len(file_ids) and file_ids[i]:
                cursor.execute('UPDATE eggs SET image_file_id = ? WHERE id = ?', (file_ids[i], egg[0]))

        conn.commit()

        await update.message.reply_text("✅ Картинки успешно загружены и сохранены!")

    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при загрузке картинок: {e}")


# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "Неизвестно"
    referrer_id = None
    if context.args and context.args[0].isdigit():
        referrer_id = int(context.args[0])

    try:
        if restock_eggs():
            await update.message.reply_text("🔄 Еженедельное пополнение! Все яйца снова в продаже по базовым ценам!")
    except Exception as e:
        print(f"Ошибка при проверке пополнения: {e}")

    player = get_player(user_id)

    if player and player[2]:
        await show_dashboard(update, context)
    else:
        keyboard = [[InlineKeyboardButton("🎮 Начать игру", callback_data="start_game")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "🎉 Добро пожаловать в игру 'Яйца Бизнес'! \n\n"
            "💼 Строй бизнес, 🥚 покупай редкие яйца и становись самым богатым игроком!",
            reply_markup=reply_markup
        )
        if not player:
            create_player(user_id, username, None, referrer_id)
            if process_referral(user_id, referrer_id):
                await update.message.reply_text("👥 Рефералка: +5000 YAIC тебе и другу!")


# === ПОКУПКА ЯЙЦА — 1 НА ТИП ===
async def buy_egg(query, context: ContextTypes.DEFAULT_TYPE, egg_id):
    user_id = query.from_user.id
    player = get_player(user_id)

    eggs = get_eggs()
    egg = None
    for e in eggs:
        if e[0] == egg_id:
            egg = e
            break

    if not egg:
        await context.bot.send_message(chat_id=user_id, text="❌ Яйцо не найдено!")
        return

    id, name, price, image_file_id, description, limit_count, current_count, base_price, last_restock = egg

    if current_count >= limit_count:
        await context.bot.send_message(chat_id=user_id, text="❌ Это яйцо уже раскуплено!")
        return

    # ПРОВЕРКА: УЖЕ ЕСТЬ?
    cursor = get_db_connection().cursor()
    cursor.execute('SELECT 1 FROM player_eggs WHERE user_id = ? AND egg_id = ?', (user_id, egg_id))
    if cursor.fetchone():
        await context.bot.send_message(chat_id=user_id, text="❌ У тебя уже есть это яйцо!")
        return

    if player[3] < price:
        await context.bot.send_message(chat_id=user_id, text="❌ Недостаточно YAIC!")
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('BEGIN TRANSACTION')
        cursor.execute('UPDATE players SET balance = balance - ? WHERE user_id = ?', (price, user_id))
        cursor.execute('UPDATE eggs SET current_count = current_count + 1 WHERE id = ?', (egg_id,))
        cursor.execute('INSERT INTO player_eggs (user_id, egg_id, purchased_price) VALUES (?, ?, ?)',
                       (user_id, egg_id, price))
        new_price = int(price * 1.08)
        cursor.execute('UPDATE eggs SET price = ? WHERE id = ?', (new_price, egg_id))
        conn.commit()

        await context.bot.send_message(
            chat_id=user_id,
            text=f"🎉 <b>Поздравляем с покупкой!</b>\n\n<b>Вы купили:</b> {name}\n<b>Номер яйца:</b> #{current_count + 1} из {limit_count}\n<b>Цена покупки:</b> {price} YAIC\n<b>Следующее будет стоить:</b> {new_price} YAIC (+8%)",
            parse_mode='HTML'
        )

        await show_egg_market(query, context)

    except Exception as e:
        conn.rollback()
        await context.bot.send_message(chat_id=user_id, text="❌ Ошибка при покупке яйца")


# === ОТКРЫТИЕ БОКСА — КУЛДАУН 2 МИН ===
async def open_box_handler(query, context: ContextTypes.DEFAULT_TYPE, box_id):
    user_id = query.from_user.id

    can_open, remaining = can_open_box(user_id)
    if not can_open:
        minutes = remaining // 60
        seconds = remaining % 60

        # Создаем красивое сообщение о кулдауне
        cooldown_message = (
            f"⏰ <b>Кулдаун!</b>\n\n"
            f"Вы недавно открывали бокс. Подождите еще:\n"
            f"<b>{minutes:02d}:{seconds:02d}</b>\n\n"
            f"💡 <i>Боксы можно открывать раз в 2 минуты</i>"
        )

        # Отправляем сообщение вместо alert
        await context.bot.send_message(
            chat_id=user_id,
            text=cooldown_message,
            parse_mode='HTML'
        )
        return

    # Получаем информацию о боксе для красивого сообщения
    boxes = get_boxes()
    box_name = ""
    box_price = 0
    for box in boxes:
        if box[0] == box_id:
            box_name = box[1]
            box_price = box[2]
            break

    # Проверяем баланс перед открытием
    player = get_player(user_id)
    if player[3] < box_price:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"❌ <b>Недостаточно средств!</b>\n\n"
                 f"Для открытия {box_name} нужно {box_price} YAIC\n"
                 f"Ваш баланс: {player[3]} YAIC",
            parse_mode='HTML'
        )
        return

    # Показываем анимацию открытия
    opening_message = await context.bot.send_message(
        chat_id=user_id,
        text=f"🎁 <b>Открываем {box_name}...</b>\n\n"
             f"⏳ Подождите немного...",
        parse_mode='HTML'
    )

    # Имитируем задержку для драматизма
    await asyncio.sleep(2)

    rewards = open_box(user_id, box_id)

    # Удаляем сообщение об открытии
    try:
        await context.bot.delete_message(chat_id=user_id, message_id=opening_message.message_id)
    except:
        pass

    if rewards is None:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ <b>Не удалось открыть бокс!</b>\n\n"
                 "Возможные причины:\n"
                 "• Недостаточно YAIC\n"
                 "• Достигнут лимит яиц\n"
                 "• Ошибка системы",
            parse_mode='HTML'
        )
    else:
        if rewards == ["Ничего не выпало"]:
            rewards_text = (
                "😔 <b>К сожалению, ничего не выпало...</b>\n\n"
                "💫 Попробуйте еще раз - удача обязательно улыбнется!"
            )
        else:
            rewards_text = "🎉 <b>Поздравляем! Вы получили:</b>\n\n" + "\n".join([f"🎁 {reward}" for reward in rewards])

        # Добавляем информацию о следующем открытии
        rewards_text += f"\n\n⏰ <i>Следующий бокс можно открыть через 2 минуты</i>"

        await context.bot.send_message(
            chat_id=user_id,
            text=rewards_text,
            parse_mode='HTML'
        )

    set_box_cooldown(user_id)


# Обработчик кнопок
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id

    try:
        await context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
    except:
        pass

    if data == "start_game":
        await ask_nickname(query, context)
    elif data == "dashboard":
        await show_dashboard(query, context)
    elif data == "buy_business":
        await show_businesses(query, context)
    elif data == "egg_market":
        await show_egg_market(query, context)
    elif data == "inventory":
        await show_inventory_menu(query, context)
    elif data == "inventory_eggs":
        await show_egg_inventory(query, context)
    elif data == "inventory_businesses":
        await show_business_inventory(query, context)
    elif data == "instructions":
        await show_instructions(query, context)
    elif data == "top_players":
        await show_top_players(query, context)
    elif data == "friends":
        await show_friends_menu(query, context)
    elif data == "trades":
        await show_trades_menu(query, context)
    elif data == "boxes":
        await show_boxes_menu(query, context)
    elif data == "loans":
        await show_loans_menu(query, context)
    elif data == "promo_codes":
        await show_promo_codes_menu(query, context)
    elif data == "enter_promo_code":
        await ask_promo_code(query, context)
    elif data == "add_friend":
        await add_friend_handler(query, context)
    elif data.startswith("remove_friend_"):
        friend_id = int(data.split("_")[2])
        await remove_friend_handler(query, context, friend_id)
    elif data.startswith("business_"):
        business_id = int(data.split("_")[1])
        await buy_business(query, context, business_id)
    elif data.startswith("egg_detail_"):
        egg_id = int(data.split("_")[2])
        await show_egg_details(query, context, egg_id)
    elif data.startswith("buy_egg_"):
        egg_id = int(data.split("_")[2])
        await buy_egg(query, context, egg_id)
    elif data.startswith("collect_income"):
        await collect_income_handler(query, context)
    elif data.startswith("sell_business_"):
        business_id = int(data.split("_")[2])
        await sell_business_handler(query, context, business_id)
    elif data.startswith("sell_egg_"):
        egg_id = int(data.split("_")[2])
        await sell_egg_handler(query, context, egg_id)
    elif data.startswith("trade_business_"):
        business_id = int(data.split("_")[2])
        await create_business_trade_handler(query, context, business_id)
    elif data.startswith("trade_egg_"):
        egg_id = int(data.split("_")[2])
        await create_egg_trade_handler(query, context, egg_id)
    elif data.startswith("select_friend_"):
        friend_id = int(data.split("_")[2])
        await select_friend_handler(query, context, friend_id)
    elif data.startswith("accept_trade_"):
        trade_id = int(data.split("_")[2])
        await accept_trade_handler(query, context, trade_id)
    elif data.startswith("reject_trade_"):
        trade_id = int(data.split("_")[2])
        await reject_trade_handler(query, context, trade_id)
    elif data.startswith("open_box_"):
        box_id = int(data.split("_")[2])
        await open_box_handler(query, context, box_id)
    elif data.startswith("take_loan_"):
        amount = int(data.split("_")[2])
        await take_loan_handler(query, context, amount)
    elif data.startswith("repay_loan_"):
        amount = int(data.split("_")[2])
        await repay_loan_handler(query, context, amount)
    elif data == "custom_loan":
        await ask_loan_amount(query, context)
    elif data == "back_to_market":
        await show_egg_market(query, context)
    elif data == "back_to_inventory":
        await show_inventory_menu(query, context)
    elif data == "back_to_friends":
        await show_friends_menu(query, context)
    elif data == "back_to_trades":
        await show_trades_menu(query, context)
    elif data == "back_to_boxes":
        await show_boxes_menu(query, context)
    elif data == "back_to_loans":
        await show_loans_menu(query, context)
    elif data == "back_to_promo":
        await show_promo_codes_menu(query, context)
    elif data == "sold_out":
        await context.bot.send_message(chat_id=user_id, text="❌ Это яйцо уже раскуплено!")


# Запрос ника
async def ask_nickname(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['awaiting_nickname'] = True
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text="👤 Введи свой игровой ник (2-20 символов):"
    )


# Запрос суммы кредита
async def ask_loan_amount(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['awaiting_loan_amount'] = True
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text="💵 Введите сумму кредита (от 1,000 до 50,000 YAIC):"
    )


# Запрос промокода
async def ask_promo_code(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['awaiting_promo_code'] = True
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text="🎫 Введите промокод:"
    )


# Обработчик текстовых сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "Неизвестно"

    if context.user_data.get('awaiting_nickname'):
        nickname = update.message.text.strip()

        if len(nickname) < 2 or len(nickname) > 20:
            await update.message.reply_text("❌ Ник должен быть от 2 до 20 символов. Попробуй еще раз:")
            return

        create_player(user_id, username, nickname)
        context.user_data['awaiting_nickname'] = False

        await update.message.reply_text(f"✅ Отлично, {nickname}! Держи стартовые 5000 YAIC!")
        await show_dashboard(update, context)

    elif context.user_data.get('awaiting_friend_id'):
        try:
            friend_id = int(update.message.text.strip())
            success, message = add_friend(user_id, friend_id)
            await update.message.reply_text(message)
        except ValueError:
            await update.message.reply_text("❌ Введи корректный ID пользователя (только цифры)")
        context.user_data['awaiting_friend_id'] = False
        await show_friends_menu(update, context)

    elif context.user_data.get('awaiting_trade_price'):
        try:
            price = int(update.message.text.strip())
            item_type = context.user_data['trade_item_type']
            item_id = context.user_data['trade_item_id']
            friend_id = context.user_data['trade_friend_id']

            trade_id = create_trade(user_id, friend_id, item_type, item_id, price)
            if trade_id:
                await update.message.reply_text(f"✅ Трейд создан! Ожидайте ответа от друга.")
            else:
                await update.message.reply_text("❌ Ошибка при создании трейда.")
        except ValueError:
            await update.message.reply_text("❌ Введи корректную цену (только цифры)")

        context.user_data['awaiting_trade_price'] = False
        context.user_data['trade_item_type'] = None
        context.user_data['trade_item_id'] = None
        context.user_data['trade_friend_id'] = None

    elif context.user_data.get('awaiting_loan_amount'):
        try:
            amount = int(update.message.text.strip())
            success, message = take_loan(user_id, amount)
            await update.message.reply_text(message)
        except ValueError:
            await update.message.reply_text("❌ Введи корректную сумму (только цифры)")
        context.user_data['awaiting_loan_amount'] = False
        await show_loans_menu(update, context)

    elif context.user_data.get('awaiting_promo_code'):
        code = update.message.text.strip().upper()
        success, message = use_promo_code(user_id, code)
        await update.message.reply_text(message)
        context.user_data['awaiting_promo_code'] = False
        await show_promo_codes_menu(update, context)


# Личный кабинет
async def show_dashboard(update, context: ContextTypes.DEFAULT_TYPE):
    if hasattr(update, 'effective_user'):
        user_id = update.effective_user.id
    else:
        user_id = update.from_user.id

    player = get_player(user_id)

    if not player:
        await start(update, context)
        return

    nickname, balance = player[2], player[3]

    # Исправляем отображение None ника
    if nickname is None:
        display_nickname = "Без ника"
    else:
        display_nickname = nickname

    player_businesses = get_player_businesses(user_id)
    total_income_per_30min = sum(income for _, _, income, _ in player_businesses)

    # Проверяем кредит
    loan_info = get_loan_info(user_id)
    loan_text = ""
    if loan_info['has_loan']:
        loan_text = f"📊 Кредит: {loan_info['remaining']} YAIC\n"

    text = f"""
🏠 <b>Личный кабинет</b>

👤 Игрок: {display_nickname}
💵 Баланс: {balance} YAIC
{loan_text}📈 Пассивный доход: {total_income_per_30min} YAIC/30мин
🏢 Бизнесов: {len(player_businesses)}
🥚 Яиц: {len(get_player_eggs(user_id))}
👥 Друзей: {len(get_friends(user_id))}

🎯 Выберите действие:
    """

    keyboard = [
        [InlineKeyboardButton("🏢 Купить бизнес", callback_data="buy_business")],
        [InlineKeyboardButton("🥚 Рынок яиц", callback_data="egg_market")],
        [InlineKeyboardButton("🎒 Инвентарь", callback_data="inventory")],
        [InlineKeyboardButton("👥 Друзья", callback_data="friends")],
        [InlineKeyboardButton("🔄 Трейды", callback_data="trades")],
        [InlineKeyboardButton("📦 Боксы", callback_data="boxes")],
        [InlineKeyboardButton("💰 Кредиты", callback_data="loans")],
        [InlineKeyboardButton("🎫 Промокоды", callback_data="promo_codes")],
        [InlineKeyboardButton("🏆 Топ игроков", callback_data="top_players")],
        [InlineKeyboardButton("📖 Инструкция", callback_data="instructions")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    if hasattr(update, 'message'):
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup, parse_mode='HTML')


# Топ игроков
async def show_top_players(query, context: ContextTypes.DEFAULT_TYPE):
    top_players = get_top_players()

    text = "🏆 <b>Топ 10 игроков</b>\n\n"

    if not top_players:
        text += "😔 Пока нет игроков в рейтинге"
    else:
        for i, (nickname, balance, income) in enumerate(top_players, 1):
            # Исправляем отображение None
            if nickname is None:
                display_name = "Без ника"
            else:
                display_name = nickname

            income = income or 0
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            text += f"{medal} {display_name}\n"
            text += f"   💵 {balance} YAIC | 📈 {income} YAIC/30мин\n\n"

    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="dashboard")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(chat_id=query.from_user.id, text=text, reply_markup=reply_markup, parse_mode='HTML')


# Магазин бизнесов
async def show_businesses(query, context: ContextTypes.DEFAULT_TYPE):
    businesses = get_businesses()
    user_id = query.from_user.id
    player = get_player(user_id)
    balance = player[3] if player else 0

    text = f"🏢 <b>Магазин бизнесов</b>\n\n💵 Ваш баланс: {balance} YAIC\n\n"
    keyboard = []

    for business in businesses:
        id, name, price, income, description = business
        can_afford = "✅" if balance >= price else "❌"
        text += f"{can_afford} {name}\n"
        text += f"   💰 Цена: {price} YAIC\n"
        text += f"   📈 Доход: {income} YAIC/30мин\n"
        text += f"   📝 {description}\n\n"

        keyboard.append([InlineKeyboardButton(f"{name} - {price}YAIC", callback_data=f"business_{id}")])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="dashboard")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(chat_id=query.from_user.id, text=text, reply_markup=reply_markup, parse_mode='HTML')


async def buy_business(query, context: ContextTypes.DEFAULT_TYPE, business_id):
    user_id = query.from_user.id
    player = get_player(user_id)

    businesses = get_businesses()
    business = None
    for b in businesses:
        if b[0] == business_id:
            business = b
            break

    if not business:
        await context.bot.send_message(chat_id=user_id, text="❌ Бизнес не найден!")
        return

    id, name, price, income, description = business

    # Проверяем есть ли уже этот бизнес
    player_businesses = get_player_businesses(user_id)
    for pb_id, pb_name, pb_income, _ in player_businesses:
        if pb_id == business_id:
            await context.bot.send_message(chat_id=user_id, text="❌ У вас уже есть этот бизнес!")
            return

    if player[3] < price:
        await context.bot.send_message(chat_id=user_id, text="❌ Недостаточно YAIC!")
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('UPDATE players SET balance = balance - ? WHERE user_id = ?', (price, user_id))
        cursor.execute('INSERT INTO player_businesses (user_id, business_id) VALUES (?, ?)', (user_id, business_id))
        conn.commit()

        await context.bot.send_message(chat_id=user_id, text=f"✅ Вы купили {name}!\n📈 +{income} YAIC/30мин")
        await show_dashboard(query, context)
    except Exception as e:
        await context.bot.send_message(chat_id=user_id, text="❌ Ошибка при покупке бизнеса")


# Рынок яиц
async def show_egg_market(query, context: ContextTypes.DEFAULT_TYPE):
    eggs = get_eggs()
    user_id = query.from_user.id
    player = get_player(user_id)
    balance = player[3] if player else 0

    text = f"🥚 <b>Рынок яиц</b>\n\n💵 Ваш баланс: {balance} YAIC\n\n"
    keyboard = []

    for egg in eggs:
        id, name, price, image_file_id, description, limit_count, current_count, base_price, last_restock = egg
        available = limit_count - current_count
        status = "✅ Доступно" if available > 0 else "❌ Раскуплено"

        price_increase = ((price - base_price) / base_price) * 100
        price_info = f" (+{price_increase:.1f}%)" if price > base_price else ""

        text += f"{status} {name}\n"
        text += f"   💰 Цена: {price} YAIC{price_info}\n"
        text += f"   📊 Доступно: {available}/{limit_count}\n\n"

        if available > 0:
            keyboard.append([InlineKeyboardButton(f"{name} - {price}YAIC", callback_data=f"egg_detail_{id}")])
        else:
            keyboard.append([InlineKeyboardButton(f"{name} - Раскуплено", callback_data="sold_out")])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="dashboard")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(chat_id=query.from_user.id, text=text, reply_markup=reply_markup, parse_mode='HTML')


async def show_egg_details(query, context: ContextTypes.DEFAULT_TYPE, egg_id):
    eggs = get_eggs()
    egg = None
    for e in eggs:
        if e[0] == egg_id:
            egg = e
            break

    if not egg:
        await context.bot.send_message(chat_id=query.from_user.id, text="❌ Яйцо не найдено!")
        return

    id, name, price, image_file_id, description, limit_count, current_count, base_price, last_restock = egg
    available = limit_count - current_count

    if image_file_id:
        await context.bot.send_photo(
            chat_id=query.from_user.id,
            photo=image_file_id,
            caption=f"<b>{name}</b>\n\n💰 <b>Цена:</b> {price} YAIC\n📊 <b>Доступно:</b> {available}/{limit_count}\n📝 <b>Описание:</b> {description}",
            parse_mode='HTML'
        )
    else:
        text = f"<b>{name}</b>\n\n💰 <b>Цена:</b> {price} YAIC\n📊 <b>Доступно:</b> {available}/{limit_count}\n📝 <b>Описание:</b> {description}"
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text=text,
            parse_mode='HTML'
        )

    if available > 0:
        keyboard = [
            [InlineKeyboardButton("🛒 Купить", callback_data=f"buy_egg_{id}")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_market")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text="Хочешь добавить это яйцо в свою коллекцию?",
            reply_markup=reply_markup
        )
    else:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_market")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text="❌ Это яйцо уже раскуплено! Жди пополнения на следующей неделе.",
            reply_markup=reply_markup
        )


# ИНВЕНТАРЬ С КНОПКОЙ СБОРА ДОХОДА
async def show_inventory_menu(query, context: ContextTypes.DEFAULT_TYPE):
    user_id = query.from_user.id

    text = "🎒 <b>Ваш инвентарь</b>\n\nВыберите раздел для просмотра:"

    keyboard = [
        [InlineKeyboardButton("🥚 Мои яйца", callback_data="inventory_eggs")],
        [InlineKeyboardButton("🏢 Мои бизнесы", callback_data="inventory_businesses")],
        [InlineKeyboardButton("💰 Собрать доход", callback_data="collect_income")],
        [InlineKeyboardButton("🔙 Назад", callback_data="dashboard")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(chat_id=query.from_user.id, text=text, reply_markup=reply_markup, parse_mode='HTML')


async def collect_income_handler(query, context: ContextTypes.DEFAULT_TYPE):
    user_id = query.from_user.id
    income, status = collect_income(user_id)

    if status == "ready" and income > 0:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"💰 <b>Вы собрали доход: {income} YAIC!</b>\n⏰ Следующий сбор через 30 минут.",
            parse_mode='HTML'
        )
    elif status == "no_businesses":
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ <b>У вас нет бизнесов для сбора дохода!</b>\n\n🏢 Приобретите бизнесы в магазине.",
            parse_mode='HTML'
        )
    elif status.startswith("wait_"):
        minutes_remaining = status.split("_")[1]
        await context.bot.send_message(
            chat_id=user_id,
            text=f"⏰ <b>До следующего сбора дохода осталось: {minutes_remaining} минут</b>\n\n📈 Доход накапливается каждые 30 минут.",
            parse_mode='HTML'
        )
    else:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Нет дохода для сбора."
        )

    await show_inventory_menu(query, context)


async def show_business_inventory(query, context: ContextTypes.DEFAULT_TYPE):
    user_id = query.from_user.id
    businesses = get_player_businesses(user_id)

    if not businesses:
        text = "❌ <b>У вас пока нет бизнесов</b>\n\n🏢 Начните с покупки первого бизнеса в магазине!"
    else:
        text = "🏢 <b>Ваши бизнесы</b>\n\n"
        total_income = 0

        for business_id, name, income, purchased_at in businesses:
            total_income += income
            text += f"{name}\n"
            text += f"   📈 Доход: {income} YAIC/30мин\n"
            text += f"   💰 Продажа: {int(income * 10 * 0.7)} YAIC\n\n"

        text += f"📊 <b>Суммарный доход:</b> {total_income} YAIC/30мин\n\n"
        text += "🎯 Выберите действие:"

    keyboard = []
    if businesses:
        for business_id, name, income, _ in businesses:
            keyboard.append([InlineKeyboardButton(f"💰 Продать {name}", callback_data=f"sell_business_{business_id}")])
            keyboard.append([InlineKeyboardButton(f"🔄 Обменять {name}", callback_data=f"trade_business_{business_id}")])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_inventory")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(chat_id=query.from_user.id, text=text, reply_markup=reply_markup, parse_mode='HTML')


async def show_egg_inventory(query, context: ContextTypes.DEFAULT_TYPE):
    user_id = query.from_user.id
    eggs = get_player_eggs(user_id)

    if not eggs:
        text = "❌ <b>У вас пока нет яиц</b>\n\n🥚 Приобретите свои первые яйца на рынке!"
    else:
        text = "🥚 <b>Ваша коллекция яиц</b>\n\n"
        total_value = 0
        total_profit = 0

        for egg_id, name, current_price, image_file_id, count, purchased_price in eggs:
            purchased_price = purchased_price or current_price
            egg_value = current_price * count
            profit = (current_price - purchased_price) * count
            total_value += egg_value
            total_profit += profit

            profit_percent = ((current_price - purchased_price) / purchased_price) * 100 if purchased_price > 0 else 0

            text += f"<b>{name}</b>\n"
            text += f"   💰 Текущая цена: {current_price} YAIC\n"
            text += f"   📈 Прибыль: {profit} YAIC ({profit_percent:+.1f}%)\n"
            text += f"   📊 Количество: {count}\n\n"

        text += f"<b>💎 Общая стоимость:</b> {total_value} YAIC\n"
        text += f"<b>📈 Общая прибыль:</b> {total_profit} YAIC\n\n"
        text += "🎯 Выберите действие:"

    keyboard = []
    if eggs:
        for egg_id, name, current_price, _, count, _ in eggs:
            if count > 0:
                keyboard.append([InlineKeyboardButton(f"💰 Продать {name}", callback_data=f"sell_egg_{egg_id}")])
                keyboard.append([InlineKeyboardButton(f"🔄 Обменять {name}", callback_data=f"trade_egg_{egg_id}")])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_inventory")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=query.from_user.id,
        text=text,
        parse_mode='HTML',
        reply_markup=reply_markup
    )


# Обработчики продажи
async def sell_business_handler(query, context: ContextTypes.DEFAULT_TYPE, business_id):
    user_id = query.from_user.id
    sell_price = sell_business(user_id, business_id)

    if sell_price:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ <b>Бизнес продан за {sell_price} YAIC!</b>",
            parse_mode='HTML'
        )
    else:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Ошибка при продаже бизнеса"
        )

    await show_business_inventory(query, context)


async def sell_egg_handler(query, context: ContextTypes.DEFAULT_TYPE, egg_id):
    user_id = query.from_user.id
    sell_price = sell_egg(user_id, egg_id)

    if sell_price:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ <b>Яйцо продано за {sell_price} YAIC!</b>",
            parse_mode='HTML'
        )
    else:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Ошибка при продаже яйца"
        )

    await show_egg_inventory(query, context)


# СИСТЕМА ДРУЗЕЙ
async def show_friends_menu(query, context: ContextTypes.DEFAULT_TYPE):
    user_id = query.from_user.id
    friends = get_friends(user_id)

    text = "👥 <b>Система друзей</b>\n\n"

    if not friends:
        text += "😔 У вас пока нет друзей.\n\n👤 Добавьте друзей по их ID пользователя!"
    else:
        text += "✅ <b>Ваши друзья:</b>\n"
        for friend_id, nickname in friends:
            # Исправляем отображение None
            display_nickname = nickname if nickname else "Без ника"
            text += f"{display_nickname} (ID: {friend_id})\n"

    text += "\n🎯 Выберите действие:"

    keyboard = [
        [InlineKeyboardButton("➕ Добавить друга", callback_data="add_friend")],
    ]

    if friends:
        for friend_id, nickname in friends:
            display_nickname = nickname if nickname else "Без ника"
            keyboard.append(
                [InlineKeyboardButton(f"❌ Удалить {display_nickname}", callback_data=f"remove_friend_{friend_id}")])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="dashboard")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(chat_id=query.from_user.id, text=text, reply_markup=reply_markup, parse_mode='HTML')


async def add_friend_handler(query, context: ContextTypes.DEFAULT_TYPE):
    user_id = query.from_user.id
    context.user_data['awaiting_friend_id'] = True

    text = """👥 <b>Добавление друга</b>

Чтобы добавить друга, вам нужно знать его ID пользователя.

Попросите друга:
1. Написать боту @userinfobot
2. Скопировать цифры из поля "Id"
3. Отправить эти цифры вам

Затем введите ID друга:"""

    await context.bot.send_message(chat_id=user_id, text=text, parse_mode='HTML')


async def remove_friend_handler(query, context: ContextTypes.DEFAULT_TYPE, friend_id):
    user_id = query.from_user.id
    remove_friend(user_id, friend_id)
    await context.bot.send_message(chat_id=user_id, text="✅ Друг удален из списка!")
    await show_friends_menu(query, context)


# СИСТЕМА ТРЕЙДОВ
async def show_trades_menu(query, context: ContextTypes.DEFAULT_TYPE):
    user_id = query.from_user.id
    pending_trades = get_pending_trades(user_id)

    text = "🔄 <b>Система трейдов</b>\n\n"

    if not pending_trades:
        text += "😔 У вас нет ожидающих трейдов\n\n"
    else:
        text += "⏳ <b>Ожидающие трейды:</b>\n"
        for trade_id, from_user_id, to_user_id, item_type, item_id, price, nickname, item_name in pending_trades:
            # Исправляем отображение None
            display_nickname = nickname if nickname else "Без ника"
            text += f"{display_nickname} предлагает {item_name} за {price} YAIC\n"
        text += "\n"

    text += "🎯 Выберите действие:"

    keyboard = []
    if pending_trades:
        for trade_id, from_user_id, to_user_id, item_type, item_id, price, nickname, item_name in pending_trades:
            display_nickname = nickname if nickname else "Без ника"
            keyboard.append([InlineKeyboardButton(f"✅ Принять {item_name} за {price}YAIC",
                                                  callback_data=f"accept_trade_{trade_id}")])
            keyboard.append(
                [InlineKeyboardButton(f"❌ Отклонить {item_name}", callback_data=f"reject_trade_{trade_id}")])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="dashboard")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(chat_id=query.from_user.id, text=text, reply_markup=reply_markup, parse_mode='HTML')


async def create_business_trade_handler(query, context: ContextTypes.DEFAULT_TYPE, business_id):
    user_id = query.from_user.id
    context.user_data['trade_item_type'] = 'business'
    context.user_data['trade_item_id'] = business_id

    friends = get_friends(user_id)
    if not friends:
        await context.bot.send_message(chat_id=user_id, text="❌ У вас нет друзей для обмена!")
        return

    keyboard = []
    for friend_id, nickname in friends:
        display_nickname = nickname if nickname else "Без ника"
        keyboard.append([InlineKeyboardButton(f"{display_nickname}", callback_data=f"select_friend_{friend_id}")])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="inventory_businesses")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=user_id,
        text="👥 Выберите друга для обмена:",
        reply_markup=reply_markup
    )


async def create_egg_trade_handler(query, context: ContextTypes.DEFAULT_TYPE, egg_id):
    user_id = query.from_user.id
    context.user_data['trade_item_type'] = 'egg'
    context.user_data['trade_item_id'] = egg_id

    friends = get_friends(user_id)
    if not friends:
        await context.bot.send_message(chat_id=user_id, text="❌ У вас нет друзей для обмена!")
        return

    keyboard = []
    for friend_id, nickname in friends:
        display_nickname = nickname if nickname else "Без ника"
        keyboard.append([InlineKeyboardButton(f"{display_nickname}", callback_data=f"select_friend_{friend_id}")])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="inventory_eggs")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=user_id,
        text="👥 Выберите друга для обмена:",
        reply_markup=reply_markup
    )


# ОБРАБОТЧИК ДЛЯ ВЫБОРА ДРУГА
async def select_friend_handler(query, context: ContextTypes.DEFAULT_TYPE, friend_id):
    user_id = query.from_user.id
    context.user_data['trade_friend_id'] = friend_id
    context.user_data['awaiting_trade_price'] = True

    item_type = context.user_data['trade_item_type']
    item_id = context.user_data['trade_item_id']

    # Получаем информацию о предмете
    if item_type == 'business':
        businesses = get_businesses()
        item_name = None
        for business in businesses:
            if business[0] == item_id:
                item_name = business[1]
                break
    else:  # egg
        eggs = get_eggs()
        item_name = None
        for egg in eggs:
            if egg[0] == item_id:
                item_name = egg[1]
                break

    await context.bot.send_message(
        chat_id=user_id,
        text=f"💰 Введите цену в YAIC для {item_name}:\n\n(Минимальная цена: 1 YAIC)"
    )


async def accept_trade_handler(query, context: ContextTypes.DEFAULT_TYPE, trade_id):
    user_id = query.from_user.id

    if accept_trade(trade_id):
        await context.bot.send_message(chat_id=user_id, text="✅ Трейд успешно завершен!")
    else:
        await context.bot.send_message(chat_id=user_id, text="❌ Не удалось завершить трейд. Проверьте баланс.")

    await show_trades_menu(query, context)


async def reject_trade_handler(query, context: ContextTypes.DEFAULT_TYPE, trade_id):
    user_id = query.from_user.id
    reject_trade(trade_id)
    await context.bot.send_message(chat_id=user_id, text="❌ Трейд отклонен!")
    await show_trades_menu(query, context)


# СИСТЕМА БОКСОВ - С ПОНИЖЕННОЙ ВЕЗУЧЕСТЬЮ
async def show_boxes_menu(query, context: ContextTypes.DEFAULT_TYPE):
    boxes = get_boxes()
    user_id = query.from_user.id
    player = get_player(user_id)
    balance = player[3] if player else 0

    text = f"📦 <b>Система боксов</b>\n\n💵 Ваш баланс: {balance} YAIC\n\n"

    for box in boxes:
        box_id, name, price, rewards = box
        text += f"{name}\n"
        text += f"   💰 Цена: {price} YAIC\n"
        text += f"   🎁 Возможные награды: {rewards}\n\n"

    text += "🎯 Выберите бокс для открытия:"

    keyboard = []
    for box in boxes:
        box_id, name, price, _ = box
        keyboard.append([InlineKeyboardButton(f"{name} - {price}YAIC", callback_data=f"open_box_{box_id}")])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="dashboard")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(chat_id=query.from_user.id, text=text, reply_markup=reply_markup, parse_mode='HTML')


# СИСТЕМА КРЕДИТОВ
async def show_loans_menu(query, context: ContextTypes.DEFAULT_TYPE):
    user_id = query.from_user.id
    loan_info = get_loan_info(user_id)
    player = get_player(user_id)
    balance = player[3] if player else 0

    text = f"💰 <b>Система кредитов</b>\n\n💵 Ваш баланс: {balance} YAIC\n\n"

    if loan_info['has_loan']:
        text += f"📊 <b>Текущий кредит:</b>\n"
        text += f"   💰 Сумма: {loan_info['amount']} YAIC\n"
        text += f"   📈 Процент: {loan_info['interest_rate']}%\n"
        text += f"   ⏳ Осталось выплатить: {loan_info['remaining']} YAIC\n\n"
        text += "🎯 Выберите действие:"

        keyboard = [
            [InlineKeyboardButton("💵 Внести 1,000 YAIC", callback_data="repay_loan_1000")],
            [InlineKeyboardButton("💵 Внести 5,000 YAIC", callback_data="repay_loan_5000")],
            [InlineKeyboardButton("💵 Внести 10,000 YAIC", callback_data="repay_loan_10000")],
            [InlineKeyboardButton("💵 Внести всю сумму", callback_data=f"repay_loan_{loan_info['remaining']}")],
            [InlineKeyboardButton("🔙 Назад", callback_data="dashboard")]
        ]
    else:
        text += "💳 Вы можете взять кредит под 20% годовых\n\n"
        text += "📊 Максимальная сумма: 50,000 YAIC\n"
        text += "📊 Минимальная сумма: 1,000 YAIC\n\n"
        text += "🎯 Выберите сумму кредита:"

        keyboard = [
            [InlineKeyboardButton("💵 Взять 5,000 YAIC", callback_data="take_loan_5000")],
            [InlineKeyboardButton("💵 Взять 10,000 YAIC", callback_data="take_loan_10000")],
            [InlineKeyboardButton("💵 Взять 25,000 YAIC", callback_data="take_loan_25000")],
            [InlineKeyboardButton("💵 Взять 50,000 YAIC", callback_data="take_loan_50000")],
            [InlineKeyboardButton("✏️ Ввести свою сумму", callback_data="custom_loan")],
            [InlineKeyboardButton("🔙 Назад", callback_data="dashboard")]
        ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(chat_id=query.from_user.id, text=text, reply_markup=reply_markup, parse_mode='HTML')


async def take_loan_handler(query, context: ContextTypes.DEFAULT_TYPE, amount):
    user_id = query.from_user.id
    success, message = take_loan(user_id, amount)
    await context.bot.send_message(chat_id=user_id, text=message)
    await show_loans_menu(query, context)


async def repay_loan_handler(query, context: ContextTypes.DEFAULT_TYPE, amount):
    user_id = query.from_user.id
    success, message = repay_loan(user_id, amount)
    await context.bot.send_message(chat_id=user_id, text=message)
    await show_loans_menu(query, context)


# СИСТЕМА ПРОМОКОДОВ
async def show_promo_codes_menu(query, context: ContextTypes.DEFAULT_TYPE):
    user_id = query.from_user.id
    active_codes = get_active_codes()

    text = "🎫 <b>Система промокодов</b>\n\n"

    if active_codes:
        text += "✅ <b>Активные коды:</b>\n"
        for code, reward_type, reward_value, reward_item, uses_left, expires_at in active_codes:
            expires_date = datetime.fromisoformat(expires_at).strftime("%d.%m.%Y")
            if reward_type == 'yaic':
                reward_text = f"{reward_value} YAIC"
            else:
                reward_text = reward_item
            text += f"🎁 <b>{code}</b> - {reward_text} (осталось: {uses_left}, до: {expires_date})\n"
        text += "\n"

    text += "🎯 Выберите действие:"

    keyboard = [
        [InlineKeyboardButton("🎫 Ввести промокод", callback_data="enter_promo_code")],
        [InlineKeyboardButton("🔙 Назад", callback_data="dashboard")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(chat_id=query.from_user.id, text=text, reply_markup=reply_markup, parse_mode='HTML')


async def enter_promo_code_handler(query, context: ContextTypes.DEFAULT_TYPE):
    await ask_promo_code(query, context)


# Инструкция
async def show_instructions(query, context: ContextTypes.DEFAULT_TYPE):
    text = """
📖 <b>Инструкция по игре "Яйца Бизнес"</b>

🎮 <b>Как начать:</b>
1. Нажми "🎮 Начать игру"
2. Придумай ник
3. Начни покупать бизнесы

🏢 <b>Бизнесы:</b>
- Можно купить только 1 экземпляр каждого бизнеса
- Приносят пассивный доход каждые 30 минут
- Доход в валюте YAIC
- Можно продать за 70% от цены покупки

🥚 <b>Яйца хайпа:</b>
- 4 типа уникальных яиц с картинками
- Ограниченное количество каждого типа
- После каждой покупки цена растет на 8%
- Каждую неделю тираж пополняется
- Можно продать за 80% от текущей цены

👥 <b>Система друзей:</b>
- Добавляйте друзей по ID
- Обменивайтесь яйцами и бизнесами

🔄 <b>Трейды:</b>
- Предлагайте друзьям обмен
- Устанавливайте свою цену
- Принимайте или отклоняйте предложения

📦 <b>Боксы:</b>
- Открывайте за YAIC
- Случайные награды (YAIC, яйца)
- Разные уровни боксов
- Кулдаун 2 минуты между открытиями

💰 <b>Кредиты:</b>
- Берите кредиты под 20%
- Максимум 50,000 YAIC
- Выплачивайте вовремя

🎫 <b>Промокоды:</b>
- Следите за каналом с анонсами
- Вводите коды для получения наград
- Коды ограничены по времени и количеству использований

⏰ <b>Сбор дохода:</b>
- Доход накапливается каждые 30 минут
- Собирайте в инвентаре
- Если 30 минут не прошло - покажет таймер

🚀 <b>Удачи в построении бизнес-империи!</b>
    """

    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="dashboard")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(chat_id=query.from_user.id, text=text, reply_markup=reply_markup, parse_mode='HTML')


# Основная функция
def main():
    init_db()

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("give_yaic", admin_give_yaic))
    application.add_handler(CommandHandler("create_code", admin_create_code))
    application.add_handler(CommandHandler("fix_nicks", fix_nicknames))
    application.add_handler(CommandHandler("upload_images", upload_images))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🎮 Бот 'Яйца Бизнес' запущен!")
    print("💵 Валюта: YAIC")
    print("🏢 Бизнесы: можно купить только 1 экземпляр")
    print("🥚 4 типа яиц: Обычное, Золотое, Алмазное, Мемное")
    print("📦 Боксы с пониженной везучестью и кулдауном 2 минуты")
    print("⏰ Таймер сбора дохода: 30 минут")
    print("💰 Система кредитов под 20%")
    print("🔄 Система трейдов")
    print("🎫 Система промокодов")
    print("👥 Реферальная система")
    print("🔧 Команда для исправления ников: /fix_nicks")

    print("🚀 Бот запускается...")
    application.run_polling()


if __name__ == '__main__':
    main()