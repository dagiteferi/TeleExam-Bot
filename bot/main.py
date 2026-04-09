import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage, DefaultKeyBuilder

from bot.config import settings
from bot.middlewares.auto_upsert import AutoUpsertMiddleware
from bot.middlewares.throttling import ThrottlingMiddleware
from bot.routers.ai_tutor import router as ai_tutor_router
from bot.routers.onboarding import router as onboarding_router
from bot.routers.progress import router as progress_router
from bot.routers.sessions import router as sessions_router
from bot.services.api_client import api_client


import platform
import sys
import aiogram
import aiohttp
from pprint import pprint

logging.basicConfig(level=logging.INFO)


async def get_bot_and_dispatcher() -> tuple[Bot, Dispatcher]:
    """
    Initializes and returns the Bot and Dispatcher instances.
    """

    bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))

   
    storage = RedisStorage.from_url(
        settings.REDIS_URL,
        key_builder=DefaultKeyBuilder(with_bot_id=True, with_destiny=True),
    )

    dp = Dispatcher(storage=storage)

   
    dp.message.middleware(AutoUpsertMiddleware())
    dp.callback_query.middleware(ThrottlingMiddleware()) #
    dp.callback_query.middleware(AutoUpsertMiddleware())

  
    dp.include_router(onboarding_router)
    dp.include_router(sessions_router)
    dp.include_router(ai_tutor_router)
    dp.include_router(progress_router)

    dp.shutdown.register(api_client.close_session)

    return bot, dp


if __name__ == "__main__":
    
   


    def print_startup_details():
        
        YELLOW = "\033[93m"
        CYAN = "\033[96m"
        RESET = "\033[0m"
        BOLD = "\033[1m"

        print(f"\n{BOLD}{CYAN}========== TeleExam Bot Startup Details =========={RESET}")
        print(f"{YELLOW}Python:{RESET} {platform.python_version()} ({sys.executable})")
        print(f"{YELLOW}Platform:{RESET} {platform.system()} {platform.release()} ({platform.machine()})")
        print(f"{YELLOW}aiogram:{RESET} {aiogram.__version__}")
        print(f"{YELLOW}aiohttp:{RESET} {aiohttp.__version__}")
        print(f"{CYAN}================================================={RESET}\n")

    async def start_polling():
        print_startup_details()
        bot, dp = await get_bot_and_dispatcher()
        print("Bot started in polling mode!")
        await dp.start_polling(bot)

    try:
        asyncio.run(start_polling())
    except KeyboardInterrupt:
        print("Bot stopped by user.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
