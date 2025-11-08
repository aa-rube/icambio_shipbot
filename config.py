import os
from dotenv import load_dotenv

load_dotenv()

# Odoo
ODOO_URL = os.getenv("ODOO_URL", "http://localhost:8069/jsonrpc")
ODOO_DB = os.getenv("ODOO_DB", "")  # Имя базы данных Odoo
ODOO_LOGIN = os.getenv("ODOO_LOGIN", "")
ODOO_API_KEY = os.getenv("ODOO_API_KEY", "")

# Telegram Bot
BOT_TOKEN = os.getenv("BOT_TOKEN", "PUT_YOUR_TELEGRAM_BOT_TOKEN_HERE")

# Mongo
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "icambio")

# Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Local API (FastAPI) host/port
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "5055"))

# TTLs (in seconds)
SHIFT_TTL = int(os.getenv("SHIFT_TTL", str(12 * 60 * 60)))        # 12 hours
LOC_TTL   = int(os.getenv("LOC_TTL",   str(12 * 60 * 60)))        # 12 hours
PHOTO_WAIT_TTL = int(os.getenv("PHOTO_WAIT_TTL", str(10 * 60)))   # 10 minutes
ORDER_LOCK_TTL = int(os.getenv("ORDER_LOCK_TTL", str(30)))        # 30 seconds
LIVE_LOCATION_DURATION = int(os.getenv("LIVE_LOCATION_DURATION", str(8 * 60 * 60)))  # 8 hours
LOCATION_REQUEST_INTERVAL = int(os.getenv("LOCATION_REQUEST_INTERVAL", str(20)))  # 20 seconds

# Manager
MANAGER_CHAT_ID = int(os.getenv("MANAGER_CHAT_ID", "0"))

# Webhook
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
