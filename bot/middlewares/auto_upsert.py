import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Dict, Optional, Set

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject, User

from bot.keyboards.reply import MENU_VERSION, MenuState, current_menu_state, main_menu_keyboard, menu_attached
from bot.states.session_states import is_busy
from bot.services.api_client import api_client

# How often a known user's profile is re-synced with the backend.
REFRESH_INTERVAL_SECONDS = 60


def profile_from_response(user_response: Dict[str, Any]) -> Dict[str, Any]:
    """Maps a backend upsert/me response to the FSM keys the bot relies on."""
    return {
        "user_id": user_response.get("user_id"),
        "department_id": user_response.get("department_id"),
        "department_name": user_response.get("department_name"),
        "is_pro": user_response.get("is_pro", False),
        "is_full_access": user_response.get("is_full_access", False),
        "invite_code": user_response.get("invite_code"),
        "invite_count": user_response.get("invite_count", 0),
        "secondary_department_id": user_response.get("secondary_department_id"),
        "secondary_department_name": user_response.get("secondary_department_name"),
        "secondary_department_unlocked": user_response.get("secondary_department_unlocked", False),
        "has_dual_access": user_response.get("has_dual_access", False),
        "active_department_id": user_response.get("active_department_id") or user_response.get("department_id"),
        "active_department_name": user_response.get("active_department_name") or user_response.get("department_name"),
    }


# Sent when a plan change makes the menu the user is looking at stale.
_PLAN_CHANGE_MESSAGES = {
    "dual_on": "🎓 Your Dual Degree is active. Tap 🔄 Switch Department to move between your departments.",
    "dual_off": "Your second department is locked again, so you are back in your main department.",
    "pro_on": "⭐️ Your PRO plan is active. Your menu has been updated.",
    "pro_off": "Your PRO plan has ended. You can upgrade again from the menu.",
    "pro_and_dual_off": (
        "Your PRO plan has ended, so your second department is locked too. "
        "You can upgrade again from the menu."
    ),
}


def _plan_change(before: MenuState, after: MenuState) -> Optional[str]:
    if before == after:
        return None
    if before.is_pro and not after.is_pro:
        return _PLAN_CHANGE_MESSAGES["pro_and_dual_off" if before.has_dual_access else "pro_off"]
    if after.has_dual_access != before.has_dual_access:
        return _PLAN_CHANGE_MESSAGES["dual_on" if after.has_dual_access else "dual_off"]
    return _PLAN_CHANGE_MESSAGES["pro_on" if after.is_pro else "pro_off"]


class AutoUpsertMiddleware(BaseMiddleware):
    """
    Keeps the backend user record (name, username, referral) in sync.

    Unknown users (no department_id in state) are upserted before the handler
    runs, because handlers need the result. Known users are re-synced in the
    background so the handler never waits on the backend; the refreshed profile
    is applied to FSM state on the user's next update (never concurrently with
    a handler, which could clobber its state writes).
    """

    def __init__(self) -> None:
        self._pending_profiles: Dict[int, Dict[str, Any]] = {}
        self._background_tasks: Set[asyncio.Task] = set()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user: Optional[User] = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        state = data.get("state")
        user_state = await state.get_data() if state else {}

        # Apply a profile fetched in the background during a previous update.
        updates: Dict[str, Any] = self._pending_profiles.pop(user.id, None) or {}
        payload = self._build_payload(user, event)

        if user_state.get("department_id") or updates.get("department_id"):
            if time.time() - user_state.get("_last_upsert", 0) >= REFRESH_INTERVAL_SECONDS:
                updates["_last_upsert"] = time.time()
                task = asyncio.create_task(self._refresh_in_background(user.id, payload))
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
        else:
            # New or not-yet-synced user: the handler needs the backend profile now.
            user_response = await api_client.post(
                path="/api/users/upsert",
                telegram_id=user.id,
                payload=payload,
                timeout=10,
            )
            if user_response:
                updates.update(profile_from_response(user_response), _last_upsert=time.time())
            else:
                logging.warning("Failed to upsert user %s to backend.", user.id)

        if updates and state:
            await state.update_data(**updates)

        known_before = "is_pro" in user_state
        before = MenuState.from_profile(user_state)
        after = MenuState.from_profile({**user_state, **updates})
        current_menu_state.set(after)
        menu_attached.set(False)

        result = await handler(event, data)

        if not state or not data.get("bot"):
            return result
        # Read again: the handler may have changed the state or the plan details.
        user_state = await state.get_data()
        if is_busy(await state.get_state()):
            # Never interrupt an exam, AI chat, payment upload or onboarding;
            # a stale menu is fixed on a later, idle update.
            if known_before and before != after:
                await state.update_data(menu_version=0)
            return result

        # PRO or dual access was granted/revoked since the last update, or a deploy
        # changed the menu buttons: the keyboard Telegram shows is stale.
        change_text = _plan_change(before, after) if known_before else None
        outdated = user_state.get("menu_version") != MENU_VERSION and bool(user_state.get("department_id"))
        if not change_text and outdated and menu_attached.get():
            # This update's reply already carried the current menu.
            await state.update_data(menu_version=MENU_VERSION)
        elif change_text or outdated:
            text = change_text or "✨ TeleExam AI has been updated. Your menu now shows the latest options."
            try:
                await data["bot"].send_message(user.id, text, reply_markup=main_menu_keyboard(after))
                await state.update_data(menu_version=MENU_VERSION)
            except Exception:
                logging.warning("Failed to send updated menu to user %s.", user.id)
        return result

    async def _refresh_in_background(self, telegram_id: int, payload: Dict[str, Any]) -> None:
        user_response = await api_client.post(
            path="/api/users/upsert",
            telegram_id=telegram_id,
            payload=payload,
            timeout=10,
        )
        if user_response:
            self._pending_profiles[telegram_id] = profile_from_response(user_response)

    @staticmethod
    def _build_payload(user: User, event: TelegramObject) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "telegram_id": user.id,
            "telegram_username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }
        # Referral code from a /start ref_XXXX deep link (only applied to new users by the backend).
        if isinstance(event, Message) and event.text and event.text.startswith("/start"):
            start_payload = event.text.split(" ", 1)
            if len(start_payload) > 1 and start_payload[1].startswith("ref_"):
                payload["ref_code"] = start_payload[1].split("ref_", 1)[1]
        return payload
