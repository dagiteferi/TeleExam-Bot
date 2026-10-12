import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BACKEND_URL = "https://teleexam-ai.hf.space"
TELEGRAM_SECRET = os.getenv("BACKEND_SECRET")

HEADERS = {
    "X-Telegram-Secret": TELEGRAM_SECRET
}