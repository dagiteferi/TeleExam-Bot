import asyncio
import logging
import secrets
import time

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNotFound, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import ReplyKeyboardRemove

from bot.config import settings
from bot.keyboards.reply import MENU_VERSION, MenuState, main_menu_keyboard
from bot.middlewares.auto_upsert import profile_from_response
from bot.middlewares.protect_content import save_recording_flag
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
    await save_recording_flag(dp.storage, bot.id, telegram_id, profile)
    if not profile.get("department_id"):
        # Admin reset: forget everything (selected course, exam state...) so
        # /start shows the department choice again.
        await state.clear()
        return ReplyKeyboardRemove()
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

# Regular check; new announcements and users becoming idle also wake the sender at once.
ANNOUNCEMENT_POLL_SECONDS = 10
ANNOUNCEMENT_BATCH = 30
# Telegram allows about 30 messages per second; stay well below it.
SEND_INTERVAL_SECONDS = 0.05
# Someone who left an exam half-done this long ago is not really busy any more.
BUSY_TIMEOUT_SECONDS = 30 * 60


_wake = asyncio.Event()
# Users skipped because they were busy; the middleware wakes the sender when they are idle again.
_waiting_users: set[int] = set()


def wake_announcement_sender() -> None:
    _wake.set()


def wake_if_waiting(telegram_id: int) -> None:
    """Called after each idle update: send this user's waiting announcements right away."""
    if telegram_id in _waiting_users:
        _wake.set()


async def _is_busy_now(state: FSMContext) -> bool:
    if not is_busy(await state.get_state()):
        return False
    last_active = (await state.get_data()).get("_last_upsert", 0)
    return time.time() - last_active < BUSY_TIMEOUT_SECONDS


def announcement_html(text: str) -> str:
    return f"📢 <b>Announcement</b>\n\n{esc(text)}"


# Shown instead when Telegram no longer lets the bot delete an old copy (over 48 hours).
WITHDRAWN_HTML = "📢 <i>This announcement was withdrawn.</i>"


def _permanent(e: Exception) -> bool:
    """Errors where retrying the same edit / delete can never work."""
    return isinstance(e, (TelegramForbiddenError, TelegramNotFound, TelegramBadRequest))


async def _sync_batch(bot: Bot) -> int:
    """
    Applies admin edits and deletes to copies already in users' chats.
    Returns how many tasks were handled.
    """
    tasks = await api_client.get(
        path=f"/api/announcements/sync?limit={ANNOUNCEMENT_BATCH}",
        telegram_id=bot.id,
        timeout=30,
    )
    if not tasks:
        return 0

    edited, deleted, deferred, failed = [], [], [], []
    for task in tasks:
        delivery_id = task["delivery_id"]
        chat_id = int(task["telegram_id"])
        message_id = int(task["message_id"])
        try:
            if task["action"] == "edit":
                try:
                    await bot.edit_message_text(
                        announcement_html(task["text"]), chat_id=chat_id, message_id=message_id, parse_mode="HTML"
                    )
                except TelegramBadRequest as e:
                    if "not modified" not in str(e).lower():
                        raise
                edited.append({"delivery_id": delivery_id, "version": task["version"]})
            else:
                try:
                    await bot.delete_message(chat_id, message_id)
                except TelegramBadRequest as e:
                    if "not found" in str(e).lower():
                        pass  # the user already deleted it
                    else:
                        # Too old to delete (Telegram allows 48 hours): blank it out instead.
                        await bot.edit_message_text(
                            WITHDRAWN_HTML, chat_id=chat_id, message_id=message_id, parse_mode="HTML"
                        )
                deleted.append(delivery_id)
        except TelegramRetryAfter as e:
            deferred.append(delivery_id)
            await asyncio.sleep(e.retry_after)
        except Exception as e:
            if _permanent(e):
                failed.append(
                    {"delivery_id": delivery_id, "action": task["action"], "version": task["version"], "error": str(e)[:500]}
                )
            else:
                logging.warning(f"Announcement {task['action']} for {chat_id} failed, will retry: {e}")
                deferred.append(delivery_id)
        await asyncio.sleep(SEND_INTERVAL_SECONDS)

    await api_client.post(
        path="/api/announcements/sync/report",
        telegram_id=bot.id,
        payload={"edited": edited, "deleted": deleted, "deferred": deferred, "failed": failed},
        timeout=30,
    )
    # Deferred ones don't count, so temporary errors don't keep the loop spinning.
    return len(tasks) - len(deferred)


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
            _waiting_users.add(telegram_id)
            continue
        _waiting_users.discard(telegram_id)

        try:
            # No reply keyboard: Telegram refuses to edit messages that carry one, and the
            # user's current menu stays on screen anyway (a stale one is fixed on their next update).
            message = await bot.send_message(
                telegram_id,
                announcement_html(item["text"]),
                parse_mode="HTML",
            )
            # The message id lets the admin edit or delete this copy later.
            sent.append({"delivery_id": delivery_id, "message_id": message.message_id, "version": item.get("version", 1)})
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
        payload={"sent_messages": sent, "deferred": deferred, "failed": failed},
        timeout=30,
    )
    return len(sent)


async def run_announcement_sender(bot: Bot, dp: Dispatcher) -> None:
    """
    Background loop that delivers admin announcements, never interrupting busy users,
    and applies the admin's edits and deletes to copies already delivered.
    """
    while True:
        try:
            sent = await _deliver_batch(bot, dp)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Announcement sender error")
            sent = 0
        try:
            sent += await _sync_batch(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Announcement edit/delete error")
        # Keep going straight away while a large announcement is still being sent;
        # otherwise wait for the next check or a wake-up (new announcement, idle user).
        if sent >= ANNOUNCEMENT_BATCH // 2:
            await asyncio.sleep(0.5)
            continue
        try:
            await asyncio.wait_for(_wake.wait(), timeout=ANNOUNCEMENT_POLL_SECONDS)
        except asyncio.TimeoutError:
            pass
        _wake.clear()


def make_wake_handler():
    """POST /internal/announcements/wake — the backend asks for an immediate send."""
    async def wake_handler(request: web.Request) -> web.Response:
        if not secrets.compare_digest(request.headers.get("X-Telegram-Secret", ""), settings.BACKEND_SECRET):
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        wake_announcement_sender()
        return web.json_response({"ok": True})

    return wake_handler
