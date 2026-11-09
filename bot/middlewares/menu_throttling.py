"""
Protects the main menu (reply keyboard) buttons from repeated taps.

Main menu buttons are plain text messages, so the callback ThrottlingMiddleware never
sees them and Telegram can't show a loading state on them. Without this, tapping
"📝 Exam Mode" 100 times sends 100 backend requests and shows the exam list 100 times.

Per user:
- the first menu tap shows "⏳ Processing..." and runs;
- any menu tap while it is still running is ignored;
- the same menu button tapped again within COOLDOWN_SECONDS after it finished is ignored.
Messages that are not main menu buttons (answers, AI questions, photos) pass straight through.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable, Dict, Tuple

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot.keyboards.reply import MAIN_MENU_TEXTS

logger = logging.getLogger(__name__)

COOLDOWN_SECONDS = 2.0
# A tap that never finished (crash, very slow backend) stops blocking the user after this.
STALE_BUSY_SECONDS = 30.0
PROCESSING_TEXT = "⏳ Processing..."


class MenuThrottlingMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self.busy_since: Dict[int, float] = {}  # user_id -> when the running menu tap started
        self.last_done: Dict[int, Tuple[str, float]] = {}  # user_id -> (menu text, when it finished)
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not event.from_user or event.text not in MAIN_MENU_TEXTS:
            return await handler(event, data)

        user_id = event.from_user.id
        now = time.monotonic()

        # Checked and set with no await in between, so taps arriving at the same time can't both pass.
        started = self.busy_since.get(user_id)
        if started is not None and now - started < STALE_BUSY_SECONDS:
            return  # another menu tap of this user is still running
        last = self.last_done.get(user_id)
        if last and last[0] == event.text and now - last[1] < COOLDOWN_SECONDS:
            return  # same button tapped again right after its reply
        self.busy_since[user_id] = now

        processing_msg = None
        try:
            try:
                processing_msg = await event.answer(PROCESSING_TEXT)
            except Exception:
                logger.debug("Could not send the processing message", exc_info=True)
            return await handler(event, data)
        finally:
            self.busy_since.pop(user_id, None)
            self.last_done[user_id] = (event.text, time.monotonic())
            if len(self.last_done) > 1000:
                cutoff = time.monotonic() - COOLDOWN_SECONDS
                self.last_done = {k: v for k, v in self.last_done.items() if v[1] > cutoff}
            if processing_msg is not None:
                try:
                    await processing_msg.delete()
                except Exception:
                    pass
