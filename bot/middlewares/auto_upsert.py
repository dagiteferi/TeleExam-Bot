from typing import Any, Awaitable, Callable, Dict, Optional

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject, User

from bot.services.api_client import api_client


class AutoUpsertMiddleware(BaseMiddleware):
    """
    Middleware to automatically upsert user information to the backend on every update.

    This ensures that the backend always has the latest user data and that
    a user record exists before any other handlers are processed.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        """
        Processes the incoming Telegram update to upsert user data.
        """
        user: User = data["event_from_user"]
        if not user:
            # If for some reason user is not available, proceed without upsert
            return await handler(event, data)

        telegram_id = user.id
        username = user.username
        first_name = user.first_name
        last_name = user.last_name

        import time
        
        # Throttling Logic: Only upsert user info every 10 minutes to keep bot snappy
        state = data.get("state")
        if state:
            user_state = await state.get_data()
            last_upsert = user_state.get("_last_upsert", 0)
            
            # CRITICAL OPTIMIZATION: If we already have the department_id, skip upsert entirely for high-frequency updates
            if user_state.get("department_id") and time.time() - last_upsert < 3600: # 1 hour
                return await handler(event, data)
            
            if time.time() - last_upsert < 600: # 10 minutes
                return await handler(event, data)

        # Extract referral code from /start deep link if present
        referral_code: Optional[str] = None
        if isinstance(event, Message) and event.text and event.text.startswith("/start"):
            start_payload = event.text.split(" ", 1)
            if len(start_payload) > 1 and start_payload[1].startswith("ref_"):
                referral_code = start_payload[1].split("ref_", 1)[1]

        payload = {
            "telegram_id": telegram_id,
            "telegram_username": username,
            "first_name": first_name,
            "last_name": last_name,
        }
        if referral_code:
            payload["ref_code"] = referral_code

        # Call the backend to upsert user data
        user_response = await api_client.post(
            path="/api/users/upsert",
            telegram_id=user.id,
            payload=payload,
            timeout=10, # Increased timeout but throttled calls
        )

        if user_response:
            # Update FSM state with the latest user information from the backend
            if state:
                await state.update_data(
                    user_id=user_response.get("user_id"),
                    department_id=user_response.get("department_id"),
                    is_pro=user_response.get("is_pro", False),
                    invite_code=user_response.get("invite_code"),
                    invite_count=user_response.get("invite_count", 0),
                    _last_upsert=time.time() # Remember this call
                )
        else:
            print(f"Failed to upsert user {telegram_id} to backend.")

        return await handler(event, data)
