import logging
from typing import Any, Dict

from aiogram import Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware, NextRequestMiddlewareType
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from aiogram.methods import TelegramMethod
from aiogram.methods.base import Response, TelegramType

# Own storage slot: state.clear() (end of exam, errors, reset) only wipes the
# "default" destiny, so the admin's recording permission survives it.
RECORDING_DESTINY = "recording"


def _recording_key(bot_id: int, telegram_id: int) -> StorageKey:
    return StorageKey(bot_id=bot_id, chat_id=telegram_id, user_id=telegram_id, destiny=RECORDING_DESTINY)


async def save_recording_flag(storage: BaseStorage, bot_id: int, telegram_id: int, profile: Dict[str, Any]) -> None:
    """Stores can_record from a backend profile (upsert or /me response)."""
    if "can_record" in profile:
        await storage.set_data(_recording_key(bot_id, telegram_id), {"can_record": bool(profile["can_record"])})
        if profile["can_record"]:
            logging.info("Recording flag saved for %s", telegram_id)


class ProtectContentMiddleware(BaseRequestMiddleware):
    """
    Every message is sent with protect_content (no forwarding, saving or, on Android,
    screenshots/recording). Users an admin allowed to record (can_record, e.g. the
    marketing team) get unprotected messages.
    """

    def __init__(self, storage: BaseStorage) -> None:
        self._storage = storage

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        chat_id = getattr(method, "chat_id", None)
        if hasattr(method, "protect_content") and isinstance(chat_id, int) and chat_id > 0:
            if (await self._storage.get_data(_recording_key(bot.id, chat_id))).get("can_record"):
                method.protect_content = False
                logging.info("Recording allowed: sending %s to %s unprotected", type(method).__name__, chat_id)
        return await make_request(bot, method)
