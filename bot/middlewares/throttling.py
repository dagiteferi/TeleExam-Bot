from typing import Any, Awaitable, Callable, Dict
import time

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

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

        # Show initial feedback ("Processing...") and change the button to loading
        try:
            # 1. Update the button text to a loading emoji in the inline keyboard
            if event.message and event.message.reply_markup:
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
                    from aiogram.types import InlineKeyboardMarkup
                    await event.message.edit_reply_markup(
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=new_keyboard)
                    )
            
            # 2. Answer the callback as fallback for Telegram UI status bar
            await event.answer("Processing...")
        except:
            # Silently ignore errors in UI feedback
            pass

        return await handler(event, data)
