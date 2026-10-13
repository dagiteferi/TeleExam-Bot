import asyncio
import logging
import argparse
import secrets

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from bot.config import settings
from bot.main import get_bot_and_dispatcher
from bot.services.api_client import api_client

# Configure logging
logging.basicConfig(level=logging.INFO)


async def on_startup_webhook(dispatcher: Dispatcher, bot: Bot) -> None:
    """
    Sets up the webhook URL for the Telegram bot on startup.
    """
    base_url = str(settings.BOT_PUBLIC_URL).rstrip("/")
    path = settings.WEBHOOK_PATH.lstrip("/")
    webhook_url = f"{base_url}/{path}"
    logging.info(f"Setting webhook to: {webhook_url}")
    await bot.set_webhook(webhook_url, secret_token=settings.WEBHOOK_SECRET)
    logging.info("Webhook set successfully.")


async def on_shutdown_webhook(dispatcher: Dispatcher, bot: Bot) -> None:
    """
    Closes the aiohttp.ClientSession and logs bot shutdown on exit.
    """
    logging.info("Shutting down bot and closing API client session...")
    await api_client.close_session()  # Close the custom API client session
    await bot.session.close()  # Close aiogram's internal aiohttp session
    logging.info("Bot shutdown complete.")


def make_notify_handler(bot: Bot):
    """
    POST /internal/notify — lets the backend send a message to a user through this bot.
    The backend's host (Hugging Face) can't reach api.telegram.org, so it relays via us.
    """
    async def notify_handler(request: web.Request) -> web.Response:
        if not secrets.compare_digest(request.headers.get("X-Telegram-Secret", ""), settings.BACKEND_SECRET):
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        try:
            data = await request.json()
            telegram_id = int(data["telegram_id"])
            text = str(data["text"])
        except Exception:
            return web.json_response({"ok": False, "error": "invalid payload"}, status=400)
        try:
            await bot.send_message(telegram_id, text, parse_mode="HTML")
        except Exception as e:
            logging.warning(f"Relay notify failed for telegram_id={telegram_id}: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=502)
        return web.json_response({"ok": True})

    return notify_handler


async def start_webhook_server() -> None:
    """
    Initializes the bot and starts the aiohttp web server for webhooks.
    """
    # Initialize bot and dispatcher from bot.main
    bot, dp = await get_bot_and_dispatcher()

    # Register startup and shutdown hooks for webhook specific actions
    dp.startup.register(on_startup_webhook)
    dp.shutdown.register(on_shutdown_webhook)

    # Create aiohttp web application
    app = web.Application()

    # Create a request handler for aiogram
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=settings.WEBHOOK_SECRET,
    )

    # Register webhook handler on specified path
    webhook_requests_handler.register(app, path=settings.WEBHOOK_PATH)

    # Backend → bot relay for admin notifications (payment approved/rejected, etc.)
    app.router.add_post("/internal/notify", make_notify_handler(bot))

    # Setup aiogram application (this registers the dispatcher's handlers with aiohttp)
    setup_application(app, dp, bot=bot)

    # Start aiohttp web server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.HOST, settings.PORT)
    logging.info(f"Starting webhook server on {settings.HOST}:{settings.PORT}")
    await site.start()

    # Keep the server running indefinitely
    # This prevents the main asyncio loop from exiting
    while True:
        await asyncio.sleep(3600)  # Sleep for an hour, or until interrupted


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TeleExam AI Telegram Bot")
    parser.add_argument(
        "--polling",
        action="store_true",
        help="Run the bot in polling mode for local development",
    )
    args = parser.parse_args()

    if args.polling:
        async def start_polling():
            bot, dp = await get_bot_and_dispatcher()
            logging.info("Dropping webhook and starting bot in polling mode...")
            await bot.delete_webhook(drop_pending_updates=True)
            await dp.start_polling(bot)

        try:
            asyncio.run(start_polling())
        except KeyboardInterrupt:
            logging.info("Bot stopped by user.")
        except Exception as e:
            logging.exception("An error occurred while running the bot in polling mode.")
    else:
        try:
            asyncio.run(start_webhook_server())
        except KeyboardInterrupt:
            logging.info("Webhook server stopped by user.")
        except Exception as e:
            logging.exception("An error occurred while running the webhook server.")
