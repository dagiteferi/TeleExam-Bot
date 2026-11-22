import asyncio
import logging

from aiogram import Bot

CHECK_SECONDS = 60


async def ensure_webhook(bot: Bot, url: str, secret: str) -> bool:
    """Takes the webhook back if another deployment changed it. Returns True when it had to."""
    info = await bot.get_webhook_info()
    if info.url == url:
        return False
    logging.error("Webhook was changed to %r by another deployment. Setting it back to %s", info.url, url)
    await bot.set_webhook(url, secret_token=secret)
    return True


async def guard_webhook(bot: Bot, url: str, secret: str) -> None:
    while True:
        await asyncio.sleep(CHECK_SECONDS)
        try:
            await ensure_webhook(bot, url, secret)
        except Exception:
            logging.exception("Webhook check failed; trying again in a minute")
