from typing import Any, Awaitable, Callable, Dict, Optional
import asyncio
import time

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, TelegramObject

# Buttons whose handlers don't edit the tapped message, so they get no loading state.
NO_LOADING_PREFIXES = ("locked_ex_", "locked_course_", "buy_pro", "upload_payment_screenshot")


class ThrottlingMiddleware(BaseMiddleware):
    """
    Middleware to prevent duplicate clicks and show a loading state.
    """
    def __init__(self, throttle_time: float = 1.5):
        self.throttle_time = throttle_time
        self.last_clicks: Dict[str, float] = {}
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, CallbackQuery):
            return await handler(event, data)

        user_id = event.from_user.id
        # Create a unique key for this specific button click
        # We include callback_data to allow clicking DIFFERENT buttons
        click_key = f"{user_id}:{event.data}"
        
        current_time = time.time()
        
        if click_key in self.last_clicks:
            if current_time - self.last_clicks[click_key] < self.throttle_time:
                # Silently ignore duplicate clicks to protect backend
                return
        
        self.last_clicks[click_key] = current_time
        
        # Optional: Clean up old entries periodically or use a limited size dict
        if len(self.last_clicks) > 1000:
            self.last_clicks = {k: v for k, v in self.last_clicks.items() if current_time - v < 10}

        # Show initial feedback ("Processing...") and change the button to loading.
        # Both are Telegram API calls that don't depend on each other, so they run
        # together instead of one after the other (saves a round trip on every tap).
        feedback = [self._answer(event)]
        loading_markup = self._loading_markup(event)
        if loading_markup is not None:
            feedback.append(self._show_loading(event, loading_markup))
        await asyncio.gather(*feedback)

        return await handler(event, data)

    @staticmethod
    def _loading_markup(event: CallbackQuery) -> Optional[InlineKeyboardMarkup]:
        """The tapped message's keyboard with the tapped button turned into a loading label."""
        try:
            # Skipped for locked buttons (their handler only sends an info message,
            # so the loading text would never be replaced) and when several buttons
            # share this callback data (we can't tell which one was tapped).
            if (
                event.message
                and event.message.reply_markup
                and not (event.data or "").startswith(NO_LOADING_PREFIXES)
                and sum(
                    button.callback_data == event.data
                    for row in event.message.reply_markup.inline_keyboard
                    for button in row
                ) == 1
            ):
                keyboard = event.message.reply_markup.inline_keyboard
                new_keyboard = []
                found = False
                for row in keyboard:
                    new_row = []
                    for button in row:
                        if button.callback_data == event.data:
                            # It's the button the user just clicked! Change text to loading.
                            loading_text = "⏳ Processing..."
                            new_row.append(button.model_copy(update={"text": loading_text}))
                            found = True
                        else:
                            new_row.append(button)
                    new_keyboard.append(new_row)
                
                if found:
                    return InlineKeyboardMarkup(inline_keyboard=new_keyboard)
        except Exception:
            pass
        return None

    @staticmethod
    async def _show_loading(event: CallbackQuery, markup: InlineKeyboardMarkup) -> None:
        try:
            await event.message.edit_reply_markup(reply_markup=markup)
        except Exception:
            # Silently ignore errors in UI feedback
            pass

    @staticmethod
    async def _answer(event: CallbackQuery) -> None:
        # Answer the callback as fallback for Telegram UI status bar
        try:
            await event.answer("Processing...")
        except Exception:
            # Silently ignore errors in UI feedback
            pass
