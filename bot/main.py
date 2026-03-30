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
from bot.routers.sessions import router as sessions_router
from bot.services.api_client import api_client

# Configure logging
logging.basicConfig(level=logging.INFO)


async def get_bot_and_dispatcher() -> tuple[Bot, Dispatcher]:
    """
    Initializes and returns the Bot and Dispatcher instances.
    """
    # Initialize Bot with token and HTML parse mode for rich formatting
    bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))

    # Use RedisStorage to persist sessions across bot restarts
    storage = RedisStorage.from_url(
        settings.REDIS_URL,
        key_builder=DefaultKeyBuilder(with_bot_id=True, with_destiny=True),
    )

    dp = Dispatcher(storage=storage)

    # Register middlewares to process updates before handlers
    dp.message.middleware(AutoUpsertMiddleware())
    dp.callback_query.middleware(ThrottlingMiddleware()) # Visual loading and anti-duplication
    dp.callback_query.middleware(AutoUpsertMiddleware())

    # Include all defined routers into the dispatcher
    dp.include_router(onboarding_router)
    dp.include_router(sessions_router)
    dp.include_router(ai_tutor_router)

    # Register a shutdown handler to close the aiohttp.ClientSession gracefully
    dp.shutdown.register(api_client.close_session)

    return bot, dp


if __name__ == "__main__":
    # This block is for local development/testing using polling
    async def start_polling():
        bot, dp = await get_bot_and_dispatcher()
        print("Bot started in polling mode!")
        await dp.start_polling(bot)

    try:
        asyncio.run(start_polling())
    except KeyboardInterrupt:
        print("Bot stopped by user.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
