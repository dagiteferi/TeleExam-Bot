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

        # Extract referral code from /start deep link if present
        referral_code: Optional[str] = None
        if isinstance(event, Message) and event.text and event.text.startswith("/start"):
            start_payload = event.text.split(" ", 1)
            if len(start_payload) > 1 and start_payload[1].startswith("ref_"):
                referral_code = start_payload[1].split("ref_", 1)[1]

        payload = {
            "telegram_id": telegram_id,
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
        }
        if referral_code:
            payload["invite_code"] = referral_code

        # Call the backend to upsert user data
        # The middleware should not block the main flow if upsert fails,
        # but log the error.
        upsert_success = await api_client.post(
            path="/api/users/upsert",
            telegram_id=telegram_id,
            payload=payload,
        )

        if not upsert_success:
            print(f"Failed to upsert user {telegram_id} to backend.")
            # In a production scenario, more robust error handling might be needed,
            # e.g., notifying an admin or retrying. For now, we proceed.

        return await handler(event, data)
