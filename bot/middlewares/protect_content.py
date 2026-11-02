from aiogram import Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware, NextRequestMiddlewareType
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from aiogram.methods import TelegramMethod
from aiogram.methods.base import Response, TelegramType


class ProtectContentMiddleware(BaseRequestMiddleware):
    """
    Every message is sent with protect_content (no forwarding, saving or, on Android,
    screenshots/recording). Users an admin allowed to record (can_record, e.g. the
    marketing team) get unprotected messages. The flag comes from the profile the
    bot keeps in each user's FSM state.
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
            key = StorageKey(bot_id=bot.id, chat_id=chat_id, user_id=chat_id)
            if (await self._storage.get_data(key)).get("can_record"):
                method.protect_content = False
        return await make_request(bot, method)
