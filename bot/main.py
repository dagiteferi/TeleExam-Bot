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
from bot.routers.referral import router as referral_router
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

    # Check Environment and select storage
    if settings.ENVIRONMENT.lower() in ("dev", "development") and not settings.REDIS_URL:
        from aiogram.fsm.storage.memory import MemoryStorage
        logging.info("Development environment detected and no REDIS_URL provided. Using MemoryStorage.")
        storage = MemoryStorage()
    else:
        # Prioritize Prod REDIS_URL, then DEV_REDIS_URL
        raw_url = settings.REDIS_URL.strip() if settings.REDIS_URL else settings.DEV_REDIS_URL.strip()
        
        # Ensure raw_url has a scheme
        if not raw_url.startswith(("redis://", "rediss://", "unix://")):
            raw_url = f"redis://{raw_url}"

        logging.info(f"Connecting to Redis for FSM storage...")
        storage = RedisStorage.from_url(
            raw_url,
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
    dp.include_router(referral_router)


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
