import logging
import secrets

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey

from bot.config import settings
from bot.keyboards.reply import MenuState, main_menu_keyboard
from bot.middlewares.auto_upsert import profile_from_response
from bot.services.api_client import api_client
from bot.states.session_states import AIInteraction


async def _refreshed_menu(bot: Bot, dp: Dispatcher, telegram_id: int):
    """
    Reloads the user's profile after an admin plan change (PRO, dual degree, full
    access), saves it to their bot state and returns the matching main menu.
    Returns None when the menu should not be replaced (profile unavailable, or the
    user is chatting with the AI Tutor and has the "End Chat" keyboard open).
    """
    profile = await api_client.get(path="/api/users/me", telegram_id=telegram_id, timeout=20)
    if not profile:
        return None
    state = FSMContext(
        storage=dp.storage,
        key=StorageKey(bot_id=bot.id, chat_id=telegram_id, user_id=telegram_id),
    )
    await state.update_data(**profile_from_response(profile))
    if await state.get_state() == AIInteraction.chatting.state:
        return None
    return main_menu_keyboard(MenuState.from_profile(profile))


def make_notify_handler(bot: Bot, dp: Dispatcher):
    """
    POST /internal/notify — lets the backend send a message to a user through this bot.
    The backend's host (Hugging Face) can't reach api.telegram.org, so it relays via us.
    With "refresh_menu": true the message also carries the user's updated main menu.
    """
    async def notify_handler(request: web.Request) -> web.Response:
        if not secrets.compare_digest(request.headers.get("X-Telegram-Secret", ""), settings.BACKEND_SECRET):
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        try:
            data = await request.json()
            telegram_id = int(data["telegram_id"])
            text = str(data["text"])
            refresh_menu = bool(data.get("refresh_menu"))
        except Exception:
            return web.json_response({"ok": False, "error": "invalid payload"}, status=400)

        reply_markup = None
        if refresh_menu:
            try:
                reply_markup = await _refreshed_menu(bot, dp, telegram_id)
            except Exception as e:
                # The message itself matters more than the menu; send it anyway.
                logging.warning(f"Menu refresh failed for telegram_id={telegram_id}: {e}")

        try:
            await bot.send_message(telegram_id, text, parse_mode="HTML", reply_markup=reply_markup)
        except Exception as e:
            logging.warning(f"Relay notify failed for telegram_id={telegram_id}: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=502)
        return web.json_response({"ok": True})

    return notify_handler
