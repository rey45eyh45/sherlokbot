import sqlite3
from datetime import datetime
from config import DATABASE_FILE

def get_connection():
    """Database ulanishini olish"""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """Database jadvallarini yaratish"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Foydalanuvchilar jadvali
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            username TEXT,
            phone_number TEXT,
            language_code TEXT,
            is_bot INTEGER DEFAULT 0,
            is_premium INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    # Foydalanuvchi ma'lumotlari tarixi
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            field_name TEXT,
            old_value TEXT,
            new_value TEXT,
            changed_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')
    
    # Majburiy obuna kanallari
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT UNIQUE,
            channel_username TEXT,
            channel_title TEXT,
            invite_link TEXT,
            is_active INTEGER DEFAULT 1,
            is_request_channel INTEGER DEFAULT 0,
            is_bot INTEGER DEFAULT 0,
            added_at TEXT,
            added_by INTEGER
        )
    ''')
    
    # So'rov yuborgan foydalanuvchilar (join request)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS join_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            channel_id TEXT,
            requested_at TEXT,
            UNIQUE(user_id, channel_id)
        )
    ''')
    
    # Foydalanuvchi guruhlari (bot qaysi guruhlarda ko'rgan)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            group_id INTEGER,
            group_title TEXT,
            group_username TEXT,
            first_seen TEXT,
            last_seen TEXT,
            UNIQUE(user_id, group_id)
        )
    ''')
    
    # Referal tizimi
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER UNIQUE,
            joined_at TEXT,
            FOREIGN KEY (referrer_id) REFERENCES users(user_id),
            FOREIGN KEY (referred_id) REFERENCES users(user_id)
        )
    ''')
    
    # Bot sozlamalari
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    # User sessions (Pyrogram uchun)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_sessions (
            user_id INTEGER PRIMARY KEY,
            api_id TEXT,
            api_hash TEXT,
            phone_number TEXT,
            session_string TEXT,
            is_active INTEGER DEFAULT 0,
            online_enabled INTEGER DEFAULT 0,
            clock_enabled INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    
    # Bot ishga tushirilgan foydalanuvchilar
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bot_started (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            bot_username TEXT,
            started_at TEXT,
            UNIQUE(user_id, bot_username)
        )
    ''')
    
    # Foydalanuvchi balansi
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS balances (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0,
            total_earned INTEGER DEFAULT 0,
            total_withdrawn INTEGER DEFAULT 0,
            updated_at TEXT
        )
    ''')
    
    # Pul yechish so'rovlari
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            card_number TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            processed_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')
    
    conn.commit()
    conn.close()

# ============ Sozlamalar ============

def get_setting(key, default=None):
    """Sozlamani olish"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
    result = cursor.fetchone()
    conn.close()
    return result['value'] if result else default

def set_setting(key, value):
    """Sozlamani saqlash"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)
    ''', (key, str(value)))
    conn.commit()
    conn.close()

def is_auto_backup_enabled():
    """Avto-zaxira yoqilganmi"""
    return get_setting('auto_backup', 'false') == 'true'

def toggle_auto_backup():
    """Avto-zaxirani yoqish/o'chirish"""
    current = is_auto_backup_enabled()
    set_setting('auto_backup', 'false' if current else 'true')
    return not current

# ============ Referal tizimi ============

def add_referral(referrer_id, referred_id):
    """Referal qo'shish"""
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        cursor.execute('''
            INSERT INTO referrals (referrer_id, referred_id, joined_at)
            VALUES (?, ?, ?)
        ''', (referrer_id, referred_id, now))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False

def get_referral_count(user_id):
    """Foydalanuvchi taklif qilgan odamlar soni"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ?', (user_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_referrals(user_id):
    """Foydalanuvchi taklif qilgan odamlar ro'yxati"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT r.referred_id, r.joined_at, u.first_name, u.username
        FROM referrals r
        LEFT JOIN users u ON r.referred_id = u.user_id
        WHERE r.referrer_id = ?
        ORDER BY r.joined_at DESC
    ''', (user_id,))
    referrals = cursor.fetchall()
    conn.close()
    return referrals

def has_referrer(user_id):
    """Foydalanuvchi kimdir tomonidan taklif qilinganmi"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT referrer_id FROM referrals WHERE referred_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

# ============ Foydalanuvchilar bilan ishlash ============

def add_or_update_user(user):
    """Foydalanuvchini qo'shish yoki yangilash"""
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Mavjud foydalanuvchini tekshirish
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user.id,))
    existing = cursor.fetchone()
    
    if existing:
        # O'zgarishlarni tarixga yozish
        changes = []
        if existing['first_name'] != user.first_name:
            changes.append(('first_name', existing['first_name'], user.first_name))
        if existing['last_name'] != (user.last_name or ''):
            changes.append(('last_name', existing['last_name'], user.last_name or ''))
        if existing['username'] != (user.username or ''):
            changes.append(('username', existing['username'], user.username or ''))
        
        for field, old_val, new_val in changes:
            cursor.execute('''
                INSERT INTO user_history (user_id, field_name, old_value, new_value, changed_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (user.id, field, old_val, new_val, now))
        
        # Foydalanuvchini yangilash
        cursor.execute('''
            UPDATE users SET 
                first_name = ?, last_name = ?, username = ?, 
                language_code = ?, is_premium = ?, updated_at = ?
            WHERE user_id = ?
        ''', (user.first_name, user.last_name or '', user.username or '',
              user.language_code or '', 1 if getattr(user, 'is_premium', False) else 0, 
              now, user.id))
    else:
        # Yangi foydalanuvchi qo'shish
        cursor.execute('''
            INSERT INTO users (user_id, first_name, last_name, username, 
                              language_code, is_bot, is_premium, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user.id, user.first_name, user.last_name or '', user.username or '',
              user.language_code or '', 1 if user.is_bot else 0,
              1 if getattr(user, 'is_premium', False) else 0, now, now))
    
    conn.commit()
    conn.close()

def update_user_phone(user_id, phone_number):
    """Foydalanuvchi telefon raqamini yangilash"""
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("SELECT phone_number FROM users WHERE user_id = ?", (user_id,))
    existing = cursor.fetchone()
    
    if existing and existing['phone_number'] != phone_number:
        cursor.execute('''
            INSERT INTO user_history (user_id, field_name, old_value, new_value, changed_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, 'phone_number', existing['phone_number'], phone_number, now))
    
    cursor.execute("UPDATE users SET phone_number = ?, updated_at = ? WHERE user_id = ?",
                   (phone_number, now, user_id))
    conn.commit()
    conn.close()

def get_user(user_id):
    """Foydalanuvchi ma'lumotlarini olish"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return dict(user) if user else None

def get_user_by_username(username):
    """Username bo'yicha foydalanuvchini olish"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,))
    user = cursor.fetchone()
    conn.close()
    return dict(user) if user else None

def get_user_history(user_id):
    """Foydalanuvchi ma'lumotlari tarixini olish"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM user_history WHERE user_id = ? ORDER BY changed_at DESC
    ''', (user_id,))
    history = cursor.fetchall()
    conn.close()
    return [dict(h) for h in history]

def get_all_users():
    """Barcha foydalanuvchilarni olish"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users ORDER BY created_at DESC")
    users = cursor.fetchall()
    conn.close()
    return [dict(u) for u in users]

def get_users_count():
    """Foydalanuvchilar sonini olish"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM users")
    result = cursor.fetchone()
    conn.close()
    return result['count']

# ============ Guruhlar bilan ishlash ============

def add_user_to_group(user_id, group_id, group_title, group_username=None):
    """Foydalanuvchini guruhga qo'shish"""
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute('''
        INSERT INTO user_groups (user_id, group_id, group_title, group_username, first_seen, last_seen)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, group_id) DO UPDATE SET 
            group_title = excluded.group_title,
            group_username = excluded.group_username,
            last_seen = excluded.last_seen
    ''', (user_id, group_id, group_title, group_username or '', now, now))
    
    conn.commit()
    conn.close()

def get_user_groups(user_id):
    """Foydalanuvchi guruhlarini olish"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_groups WHERE user_id = ?", (user_id,))
    groups = cursor.fetchall()
    conn.close()
    return [dict(g) for g in groups]

# ============ Kanallar bilan ishlash ============

def add_channel(channel_id, channel_username, channel_title, added_by, is_request=False, invite_link=None, is_bot=False):
    """Kanal qo'shish"""
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        cursor.execute('''
            INSERT INTO channels (channel_id, channel_username, channel_title, invite_link, is_active, is_request_channel, is_bot, added_at, added_by)
            VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)
        ''', (str(channel_id), channel_username or '', channel_title or '', invite_link or '', 1 if is_request else 0, 1 if is_bot else 0, now, added_by))
        conn.commit()
        result = True
    except sqlite3.IntegrityError:
        result = False
    
    conn.close()
    return result

def remove_channel(channel_id):
    """Kanalni o'chirish"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM channels WHERE channel_id = ?", (str(channel_id),))
    # So'rovlarni ham o'chirish
    cursor.execute("DELETE FROM join_requests WHERE channel_id = ?", (str(channel_id),))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

def get_active_channels():
    """Faol kanallarni olish"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM channels WHERE is_active = 1")
    channels = cursor.fetchall()
    conn.close()
    return [dict(c) for c in channels]

def get_request_channels():
    """So'rovli kanallarni olish"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM channels WHERE is_active = 1 AND is_request_channel = 1")
    channels = cursor.fetchall()
    conn.close()
    return [dict(c) for c in channels]

def toggle_channel(channel_id):
    """Kanal holatini o'zgartirish"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE channels SET is_active = NOT is_active WHERE channel_id = ?", (str(channel_id),))
    conn.commit()
    conn.close()

# ============ Join Request bilan ishlash ============

def add_join_request(user_id, channel_id):
    """Foydalanuvchi so'rovini saqlash"""
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        cursor.execute('''
            INSERT INTO join_requests (user_id, channel_id, requested_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, channel_id) DO UPDATE SET requested_at = ?
        ''', (user_id, str(channel_id), now, now))
        conn.commit()
        result = True
    except:
        result = False
    
    conn.close()
    return result

def has_join_request(user_id, channel_id):
    """Foydalanuvchi so'rov yuborganmi tekshirish"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM join_requests WHERE user_id = ? AND channel_id = ?
    ''', (user_id, str(channel_id)))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def remove_join_request(user_id, channel_id):
    """So'rovni o'chirish"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        DELETE FROM join_requests WHERE user_id = ? AND channel_id = ?
    ''', (user_id, str(channel_id)))
    conn.commit()
    conn.close()

# ============ User Sessions ============

def save_user_session(user_id, api_id, api_hash, phone_number, session_string):
    """Foydalanuvchi sessiyasini saqlash"""
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    cursor.execute('''
        INSERT OR REPLACE INTO user_sessions 
        (user_id, api_id, api_hash, phone_number, session_string, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 1, COALESCE((SELECT created_at FROM user_sessions WHERE user_id = ?), ?), ?)
    ''', (user_id, api_id, api_hash, phone_number, session_string, user_id, now, now))
    
    conn.commit()
    conn.close()

def get_user_session(user_id):
    """Foydalanuvchi sessiyasini olish"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM user_sessions WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return dict(result) if result else None

def update_session_settings(user_id, online_enabled=None, clock_enabled=None):
    """Session sozlamalarini yangilash"""
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    if online_enabled is not None:
        cursor.execute('UPDATE user_sessions SET online_enabled = ?, updated_at = ? WHERE user_id = ?',
                      (1 if online_enabled else 0, now, user_id))
    
    if clock_enabled is not None:
        cursor.execute('UPDATE user_sessions SET clock_enabled = ?, updated_at = ? WHERE user_id = ?',
                      (1 if clock_enabled else 0, now, user_id))
    
    conn.commit()
    conn.close()

def delete_user_session(user_id):
    """Foydalanuvchi sessiyasini o'chirish"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM user_sessions WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def get_active_online_sessions():
    """Online yoqilgan barcha sessiyalarni olish"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM user_sessions WHERE is_active = 1 AND online_enabled = 1')
    results = cursor.fetchall()
    conn.close()
    return [dict(r) for r in results]

def get_active_clock_sessions():
    """Soat yoqilgan barcha sessiyalarni olish"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM user_sessions WHERE is_active = 1 AND clock_enabled = 1')
    results = cursor.fetchall()
    conn.close()
    return [dict(r) for r in results]

# ============ Bot Started ============

def add_bot_started(user_id, bot_username):
    """Foydalanuvchi botni ishga tushirganini saqlash"""
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    try:
        cursor.execute('''
            INSERT OR IGNORE INTO bot_started (user_id, bot_username, started_at)
            VALUES (?, ?, ?)
        ''', (user_id, bot_username.lower(), now))
        conn.commit()
        result = True
    except:
        result = False
    
    conn.close()
    return result

def has_bot_started(user_id, bot_username):
    """Foydalanuvchi botni ishga tushirganini tekshirish"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM bot_started WHERE user_id = ? AND bot_username = ?
    ''', (user_id, bot_username.lower()))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def remove_bot_started(user_id, bot_username):
    """Bot started yozuvini o'chirish"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        DELETE FROM bot_started WHERE user_id = ? AND bot_username = ?
    ''', (user_id, bot_username.lower()))
    conn.commit()
    conn.close()

# ============ Balans tizimi ============

def get_user_balance(user_id):
    """Foydalanuvchi balansini olish"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM balances WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return dict(result)
    return {'user_id': user_id, 'balance': 0, 'total_earned': 0, 'total_withdrawn': 0}

def add_balance(user_id, amount):
    """Foydalanuvchi balansiga pul qo'shish"""
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    # Avval mavjud balansni tekshirish
    cursor.execute('SELECT balance, total_earned FROM balances WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    
    if result:
        new_balance = result['balance'] + amount
        new_total = result['total_earned'] + amount
        cursor.execute('''
            UPDATE balances SET balance = ?, total_earned = ?, updated_at = ?
            WHERE user_id = ?
        ''', (new_balance, new_total, now, user_id))
    else:
        cursor.execute('''
            INSERT INTO balances (user_id, balance, total_earned, total_withdrawn, updated_at)
            VALUES (?, ?, ?, 0, ?)
        ''', (user_id, amount, amount, now))
    
    conn.commit()
    conn.close()

def subtract_balance(user_id, amount):
    """Foydalanuvchi balansidan pul ayirish"""
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    cursor.execute('SELECT balance, total_withdrawn FROM balances WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    
    if result and result['balance'] >= amount:
        new_balance = result['balance'] - amount
        new_withdrawn = result['total_withdrawn'] + amount
        cursor.execute('''
            UPDATE balances SET balance = ?, total_withdrawn = ?, updated_at = ?
            WHERE user_id = ?
        ''', (new_balance, new_withdrawn, now, user_id))
        conn.commit()
        conn.close()
        return True
    
    conn.close()
    return False

def create_withdrawal(user_id, amount, card_number):
    """Pul yechish so'rovi yaratish"""
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    cursor.execute('''
        INSERT INTO withdrawals (user_id, amount, card_number, status, created_at)
        VALUES (?, ?, ?, 'pending', ?)
    ''', (user_id, amount, card_number, now))
    conn.commit()
    withdrawal_id = cursor.lastrowid
    conn.close()
    return withdrawal_id

def get_pending_withdrawals():
    """Kutilayotgan pul yechish so'rovlarini olish"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT w.*, u.first_name, u.username 
        FROM withdrawals w 
        JOIN users u ON w.user_id = u.user_id 
        WHERE w.status = 'pending'
        ORDER BY w.created_at ASC
    ''')
    result = cursor.fetchall()
    conn.close()
    return [dict(row) for row in result]

def process_withdrawal(withdrawal_id, status):
    """Pul yechish so'rovini tasdiqlash/rad etish"""
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    cursor.execute('''
        UPDATE withdrawals SET status = ?, processed_at = ?
        WHERE id = ?
    ''', (status, now, withdrawal_id))
    conn.commit()
    conn.close()

def get_withdrawal_by_id(withdrawal_id):
    """ID bo'yicha pul yechish so'rovini olish"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM withdrawals WHERE id = ?', (withdrawal_id,))
    result = cursor.fetchone()
    conn.close()
    return dict(result) if result else None

# Database ni ishga tushirish
if __name__ == "__main__":
    init_database()
    print("Database muvaffaqiyatli yaratildi!")
