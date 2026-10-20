import asyncio
import logging
import secrets
import time

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNotFound, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey

from bot.config import settings
from bot.keyboards.reply import MENU_VERSION, MenuState, main_menu_keyboard
from bot.middlewares.auto_upsert import profile_from_response
from bot.services.api_client import api_client
from bot.states.session_states import AIInteraction, is_busy
from bot.utils.text import esc


def user_state(bot: Bot, dp: Dispatcher, telegram_id: int) -> FSMContext:
    """The FSM state of a user's private chat with the bot, outside of an update."""
    return FSMContext(
        storage=dp.storage,
        key=StorageKey(bot_id=bot.id, chat_id=telegram_id, user_id=telegram_id),
    )


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
    state = user_state(bot, dp, telegram_id)
    await state.update_data(**profile_from_response(profile))
    if await state.get_state() == AIInteraction.chatting.state:
        # Refresh the menu once they leave the chat.
        await state.update_data(menu_version=0)
        return None
    await state.update_data(menu_version=MENU_VERSION)
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


# ── Announcements ────────────────────────────────────────────────────────────

ANNOUNCEMENT_POLL_SECONDS = 20
ANNOUNCEMENT_BATCH = 30
# Telegram allows about 30 messages per second; stay well below it.
SEND_INTERVAL_SECONDS = 0.05
# Someone who left an exam half-done this long ago is not really busy any more.
BUSY_TIMEOUT_SECONDS = 30 * 60


async def _is_busy_now(state: FSMContext) -> bool:
    if not is_busy(await state.get_state()):
        return False
    last_active = (await state.get_data()).get("_last_upsert", 0)
    return time.time() - last_active < BUSY_TIMEOUT_SECONDS


async def _deliver_batch(bot: Bot, dp: Dispatcher) -> int:
    """Sends one batch of pending announcements; returns how many were sent."""
    pending = await api_client.get(
        path=f"/api/announcements/pending?limit={ANNOUNCEMENT_BATCH}",
        telegram_id=bot.id,
        timeout=30,
    )
    if not pending:
        return 0

    sent, deferred, failed = [], [], []
    for item in pending:
        delivery_id = item["delivery_id"]
        telegram_id = int(item["telegram_id"])
        state = user_state(bot, dp, telegram_id)
        if await _is_busy_now(state):
            # In an exam, AI chat, payment upload...: deliver once they are idle.
            deferred.append(delivery_id)
            continue

        reply_markup = None
        if item.get("has_department"):
            reply_markup = main_menu_keyboard(MenuState.from_profile(item))
        try:
            await bot.send_message(
                telegram_id,
                f"📢 <b>Announcement</b>\n\n{esc(item['text'])}",
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
            sent.append(delivery_id)
            if reply_markup:
                await state.update_data(menu_version=MENU_VERSION)
        except (TelegramForbiddenError, TelegramNotFound, TelegramBadRequest) as e:
            # Blocked the bot, deleted their account or chat not found: retrying won't help.
            failed.append({"delivery_id": delivery_id, "error": str(e)[:500]})
        except TelegramRetryAfter as e:
            deferred.append(delivery_id)
            await asyncio.sleep(e.retry_after)
        except Exception as e:
            logging.warning(f"Announcement to {telegram_id} failed, will retry: {e}")
            deferred.append(delivery_id)
        await asyncio.sleep(SEND_INTERVAL_SECONDS)

    await api_client.post(
        path="/api/announcements/deliveries/report",
        telegram_id=bot.id,
        payload={"sent": sent, "deferred": deferred, "failed": failed},
        timeout=30,
    )
    return len(sent)


async def run_announcement_sender(bot: Bot, dp: Dispatcher) -> None:
    """Background loop that delivers admin announcements, never interrupting busy users."""
    while True:
        try:
            sent = await _deliver_batch(bot, dp)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Announcement sender error")
            sent = 0
        # Keep going straight away while a large announcement is still being sent.
        await asyncio.sleep(1 if sent >= ANNOUNCEMENT_BATCH // 2 else ANNOUNCEMENT_POLL_SECONDS)
