import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BACKEND_URL = "https://teleexam-ai.hf.space"
TELEGRAM_SECRET = os.getenv("This_is_production_secret_2026")  # Add this to your .env

HEADERS = {
    "X-Telegram-Secret": TELEGRAM_SECRET
}