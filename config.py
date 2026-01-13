import os
from dotenv import load_dotenv

# .env faylini yuklash
load_dotenv()

# Bot konfiguratsiyasi
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Admin ID raqamlari (bir nechta admin bo'lishi mumkin)
ADMINS = [int(os.getenv("ADMIN_ID", 0))]

# Telegram API konfiguratsiyasi (my.telegram.org dan olingan)
API_ID = int(os.getenv("API_ID", 32774640))
API_HASH = os.getenv("API_HASH", "9adc3168498b133b918d793d6377ffe1")

# Database fayli
DATABASE_FILE = "bot_database.db"

# User sessions papkasi
SESSIONS_DIR = "sessions"

# Bot haqida
BOT_NAME = "Tahlilchi Bot"
BOT_VERSION = "1.0"
