import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.storage.redis import RedisStorage, DefaultKeyBuilder
from aiogram.types import ErrorEvent, ReplyKeyboardRemove

from bot.config import settings
from bot.middlewares.auto_upsert import AutoUpsertMiddleware
from bot.middlewares.throttling import ThrottlingMiddleware
from bot.routers.ai_tutor import router as ai_tutor_router, chat_exit_router
from bot.routers.onboarding import router as onboarding_router
from bot.routers.progress import router as progress_router
from bot.routers.sessions import router as sessions_router
from bot.routers.referral import router as referral_router
from bot.routers.payment import router as payment_router
from bot.routers.dual_degree import router as dual_degree_router
from bot.keyboards.reply import main_menu_keyboard
from bot.services.api_client import api_client, UserBannedError
from bot.utils.text import esc



import platform
import sys
import aiogram
import aiohttp
from pprint import pprint

logging.basicConfig(level=logging.INFO)


ERROR_TEXT = "⚠️ Something went wrong. Please try again, or use the menu below."


def _banned_text(exc: UserBannedError) -> str:
    text = "🚫 <b>Your account has been restricted by an administrator.</b>"
    if exc.reason:
        text += f"\n\nReason: <i>{esc(exc.reason)}</i>"
    if exc.banned_until:
        try:
            until = datetime.fromisoformat(exc.banned_until).strftime("%b %d, %Y %H:%M UTC")
        except ValueError:
            until = exc.banned_until
        text += f"\nAccess returns: <b>{esc(until)}</b>"
    return text + "\n\nContact support if you believe this was a mistake."


async def on_error(event: ErrorEvent) -> bool:
    """Last-resort handler: log the error and make sure the student always gets a reply."""
    exc = event.exception
    if isinstance(exc, TelegramBadRequest) and "message is not modified" in str(exc):
        return True

    if isinstance(exc, UserBannedError):
        reply_text = _banned_text(exc)
        reply_markup = ReplyKeyboardRemove()
    else:
        logging.getLogger("bot.errors").error(
            "Unhandled error while processing update %s", event.update.update_id, exc_info=exc
        )
        reply_text = ERROR_TEXT
        reply_markup = main_menu_keyboard()

    try:
        callback = event.update.callback_query
        message = event.update.message
        if callback:
            try:
                await callback.answer()
            except TelegramBadRequest:
                pass  # already answered or too old
            if callback.message:
                # Put back the original buttons (the throttle middleware set one to "Processing...")
                try:
                    await callback.message.edit_reply_markup(reply_markup=callback.message.reply_markup)
                except TelegramBadRequest:
                    pass
                await callback.message.answer(reply_text, reply_markup=reply_markup)
        elif message:
            await message.answer(reply_text, reply_markup=reply_markup)
    except Exception:
        logging.getLogger("bot.errors").exception("Failed to notify user about an error")
    return True


async def get_bot_and_dispatcher() -> tuple[Bot, Dispatcher]:
    """
    Initializes and returns the Bot and Dispatcher instances.
    """

    bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML", protect_content=True))


    # FSM storage: Redis keeps students' sessions across restarts and lets several
    # bot instances share state. MemoryStorage is only allowed for local development.
    is_dev = settings.ENVIRONMENT.lower() in ("dev", "development", "local")
    if settings.REDIS_URL:
        raw_url = settings.REDIS_URL.strip()
    elif is_dev:
        raw_url = None
    else:
        raise RuntimeError(
            f"REDIS_URL is required when ENVIRONMENT={settings.ENVIRONMENT!r}. "
            "Without it every restart wipes all students' sessions."
        )

    if raw_url is None:
        from aiogram.fsm.storage.memory import MemoryStorage
        logging.warning(
            "Using in-memory FSM storage (ENVIRONMENT=%s, no REDIS_URL). All user state is lost on restart. "
            "Do NOT use this in production: set ENVIRONMENT=production and REDIS_URL.",
            settings.ENVIRONMENT,
        )
        storage = MemoryStorage()
    else:
        # Ensure raw_url has a scheme
        if not raw_url.startswith(("redis://", "rediss://", "unix://")):
            raw_url = f"redis://{raw_url}"

        logging.info("Connecting to Redis for FSM storage...")
        storage = RedisStorage.from_url(
            raw_url,
            key_builder=DefaultKeyBuilder(with_bot_id=True, with_destiny=True),
        )
        try:
            await storage.redis.ping()
        except Exception as e:
            raise RuntimeError(f"Cannot connect to Redis for FSM storage: {e}") from e
        logging.info("Redis FSM storage connected.")

    dp = Dispatcher(storage=storage)

   
    # One shared instance so profiles refreshed in the background on a message
    # are applied on the next callback too (and vice versa).
    auto_upsert = AutoUpsertMiddleware()
    dp.message.middleware(auto_upsert)
    dp.callback_query.middleware(ThrottlingMiddleware())
    dp.callback_query.middleware(auto_upsert)

  
    dp.include_router(chat_exit_router)  # must stay first
    dp.include_router(onboarding_router)
    dp.include_router(sessions_router)
    dp.include_router(ai_tutor_router)
    dp.include_router(progress_router)
    dp.include_router(payment_router)
    dp.include_router(dual_degree_router)
    dp.include_router(referral_router)


    dp.errors.register(on_error)
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

    async def start_notify_server(bot: Bot, dp: Dispatcher) -> None:
        """Serves /internal/notify locally too, so the local backend relays admin
        messages (with the refreshed menu) through this bot, exactly as in production."""
        from aiohttp import web
        from bot.notify import make_notify_handler

        app = web.Application()
        app.router.add_post("/internal/notify", make_notify_handler(bot, dp))
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", settings.PORT).start()
        print(f"Notify relay listening on http://127.0.0.1:{settings.PORT}/internal/notify")

    async def start_polling():
        print_startup_details()
        bot, dp = await get_bot_and_dispatcher()
        await start_notify_server(bot, dp)
        print("Bot started in polling mode!")
        await dp.start_polling(bot)

    try:
        asyncio.run(start_polling())
    except KeyboardInterrupt:
        print("Bot stopped by user.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
