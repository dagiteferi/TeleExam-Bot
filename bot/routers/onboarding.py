import difflib
import re
from typing import List, Optional

from aiogram import F, Router
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from bot.keyboards.inline import department_confirmation_keyboard, department_selection_keyboard
from bot.keyboards.reply import main_menu_keyboard
from bot.middlewares.auto_upsert import profile_from_response
from bot.services.api_client import api_client
from bot.states.session_states import Onboarding
from bot.utils.text import esc

router = Router()

# Departments rarely change; cache them so /start doesn't wait on the backend.
DEPARTMENTS_CACHE_TTL = 300


def _normalize(text: str) -> str:
    """Lowercases, drops punctuation/emoji and collapses repeated letters ("Heyyy!!" -> "hey")."""
    text = re.sub(r"[^\w\s]", " ", text.lower())
    text = re.sub(r"(.)\1+", r"\1", text)
    return " ".join(text.split())


# Greetings (in any spelling: "heyy", "hiii", "Hello!", "ሰላም") just re-show the
# department list without a warning. Stored normalized so they match _normalize().
GREETINGS = {
    _normalize(word)
    for word in (
        "start", "hi", "hey", "hello", "hai", "hy", "yo", "sup", "menu", "begin",
        "good morning", "good afternoon", "good evening", "selam", "salam",
        "tadias", "ሰላም", "ታዲያስ", "ሃይ", "ሀይ",
    )
}


def _is_greeting(normalized: str) -> bool:
    if not normalized:  # only emoji / punctuation, e.g. "👋"
        return True
    words = normalized.split()
    return normalized in GREETINGS or (words[0] in GREETINGS and len(words) <= 3)


def _matching_departments(normalized: str, departments: List[dict]) -> List[dict]:
    """Departments whose name looks like what the user typed (e.g. "comp science")."""
    if len(normalized) < 3:
        return []
    matches = []
    for dept in departments:
        name = _normalize(dept["name"])
        if (
            normalized in name
            # Short names like "IT" must match a whole word, not part of "submit".
            or (name in normalized if len(name) >= 4 else name in normalized.split())
            or difflib.SequenceMatcher(None, normalized, name).ratio() >= 0.75
        ):
            matches.append(dept)
    return matches[:3]


def _is_start_command(text: str) -> bool:
    """True for /start, /start ref_XXX and /start@BotName — those go to cmd_start."""
    return re.match(r"^/start(@\w+)?(\s|$)", text) is not None


def _department_prompt(full_name: str) -> str:
    return (
        f"Hello, {esc(full_name)}.\n\n"
        "Welcome to TeleExam AI. To customize your study experience, "
        "please select your department below:"
    )


# Any message during department selection except /start (which has its own handler).
@router.message(
    Onboarding.selecting_department,
    lambda message: not _is_start_command(message.text or ""),
)
async def handle_text_during_department_selection(message: Message, state: FSMContext) -> None:
    """
    Responds to typing during department selection:
    greetings re-show the list, a typed department name gets a "did you mean" button,
    and commands (e.g. /computer_science) or anything else get a warning before the list.
    Only tapping a department button can select a department.
    """
    if not message.from_user:
        return

    # Get departments for re-display
    departments = await api_client.get(
        path="/api/questions/discovery/departments",
        telegram_id=message.from_user.id,
        cache_ttl=DEPARTMENTS_CACHE_TTL,
    )

    if departments:
        text = message.text or message.caption or ""
        normalized = _normalize(text)

        if text.startswith("/"):
            await message.answer(
                "⚠️ <b>Commands can't be used to choose a department.</b>\n\n"
                f"\"{esc(text[:40])}\" is not valid here. "
                "Please tap your department from the buttons below.",
                parse_mode="HTML"
            )
        elif text and not _is_greeting(normalized):
            matches = _matching_departments(normalized, departments)
            if matches:
                await message.answer(
                    "Did you mean this department? Tap it below to continue.\n\n"
                    "Not yours? Send /start to see all departments.",
                    reply_markup=department_selection_keyboard(matches),
                )
                return
            await message.answer(
                "⚠️ <b>Please tap your department from the buttons below.</b>\n\n"
                f"I couldn't match \"{esc(text[:40])}\" to a department.",
                parse_mode="HTML"
            )
        elif not text:  # sticker, photo, voice...
            await message.answer(
                "⚠️ <b>Please tap your department from the buttons below.</b>",
                parse_mode="HTML"
            )
        await message.answer(
            _department_prompt(message.from_user.full_name),
            reply_markup=department_selection_keyboard(departments),
        )


# Any message while the confirmation screen is open, except /start (which restarts selection).
@router.message(
    Onboarding.confirming_department,
    lambda message: not _is_start_command(message.text or ""),
)
async def handle_text_during_department_confirmation(message: Message, state: FSMContext) -> None:
    """Typing is not accepted on the confirmation screen; re-sends the confirm/change buttons."""
    if not message.from_user:
        return
    user_data = await state.get_data()
    dept_id = user_data.get("pending_department_id")
    if not dept_id:
        # Lost the pending choice; start the selection over.
        await state.set_state(None)
        await message.answer("Please send /start to choose your department.")
        return
    await message.answer(
        "⚠️ <b>Please use the buttons to confirm or change your department.</b>\n\n"
        + _confirmation_text(message.from_user, user_data.get("pending_department_name")),
        parse_mode="HTML",
        reply_markup=department_confirmation_keyboard(dept_id),
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, command: CommandObject) -> None:
    """
    Handles the /start command, checking for deep link payloads or existing departments.
    """
    if not message.from_user:
        return

    # Check for deep link payloads (e.g., /start expai_... or /start ref_...)
    payload = command.args
    if payload:
        if payload.startswith("expai_"):
            qtoken = payload.split("_", 1)[1]
            from bot.routers.ai_tutor import handle_ai_explanation
            await handle_ai_explanation(message, state, qtoken, message.from_user.id)
            return
        elif payload.startswith("ref_"):
            ref_code = payload.split("_", 1)[1]
            await state.update_data(temp_ref_code=ref_code)

    # AutoUpsertMiddleware normally has the user's department in state already.
    user_data = await state.get_data()
    department_id = user_data.get("department_id")

    if not department_id:
        # State can be empty after a restart or a slow backend. Never show the
        # department list to an existing user: ask the backend before onboarding.
        profile = await api_client.post(
            path="/api/users/upsert",
            telegram_id=message.from_user.id,
            payload={
                "telegram_id": message.from_user.id,
                "first_name": message.from_user.first_name,
                "last_name": message.from_user.last_name,
                "telegram_username": message.from_user.username,
            },
            timeout=30,
        )
        if not profile:
            await message.answer(
                "⏳ We couldn't reach the server right now. Please send /start again in a moment."
            )
            return
        await state.update_data(**profile_from_response(profile))
        department_id = profile.get("department_id")

    if department_id:
        # Already has department, skip straight to menu
        await message.answer(
            f"Welcome back, {esc(message.from_user.full_name)}.\n\n"
            "Ready to continue studying?",
            reply_markup=main_menu_keyboard(),
        )
        return

    # Fetch available departments from the backend
    departments = await api_client.get(
        path="/api/questions/discovery/departments",
        telegram_id=message.from_user.id,
        cache_ttl=DEPARTMENTS_CACHE_TTL,
    )

    if not departments:
        await message.answer(
            "Welcome to TeleExam AI.\n\n"
            "Currently, there are no departments available. Please try again later.",
            reply_markup=main_menu_keyboard(),
        )
        return

    await state.set_state(Onboarding.selecting_department)
    await message.answer(
        _department_prompt(message.from_user.full_name),
        reply_markup=department_selection_keyboard(departments),
    )


def _confirmation_text(user: User, dept_name: Optional[str]) -> str:
    username = f"@{esc(user.username)}" if user.username else "Not set"
    return (
        "<b>Please confirm your details:</b>\n\n"
        f"👤 <b>Name:</b> {esc(user.full_name)}\n"
        f"🔗 <b>Username:</b> {username}\n"
        f"🎓 <b>Department:</b> {esc((dept_name or 'Unknown').title())}\n\n"
        "⚠️ Your department <b>cannot be changed</b> after you confirm."
    )


async def _existing_department(callback: CallbackQuery, state: FSMContext) -> Optional[str]:
    """Returns the user's saved department, checking the backend if state doesn't know it."""
    user_data = await state.get_data()
    existing_dept_id = user_data.get("department_id")
    if not existing_dept_id:
        user_profile = await api_client.get(
            path="/api/users/me",
            telegram_id=callback.from_user.id,
        )
        if user_profile and user_profile.get("department_id"):
            existing_dept_id = user_profile.get("department_id")
            await state.update_data(
                department_id=existing_dept_id,
                department_name=user_profile.get("department_name"),
            )
    return existing_dept_id


async def _reject_if_already_set(callback: CallbackQuery, state: FSMContext) -> bool:
    if await _existing_department(callback, state):
        await callback.answer(
            "Your department is already set and cannot be changed.",
            show_alert=True,
        )
        await state.set_state(None)
        return True
    return False


@router.callback_query(F.data.startswith("select_dept_"))
async def process_department_selection(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Handles a department button tap: shows the user's details and the chosen
    department, and asks them to confirm before anything is saved.
    """
    if not callback.from_user or not callback.message:
        return

    user_data = await state.get_data()
    if user_data.get("department_id"):
        await callback.answer(
            "Your department is already set and cannot be changed.",
            show_alert=True,
        )
        await state.set_state(None)
        return

    await callback.answer()

    dept_id = callback.data.split("_", 2)[2]
    departments = await api_client.get(
        path="/api/questions/discovery/departments",
        telegram_id=callback.from_user.id,
        cache_ttl=DEPARTMENTS_CACHE_TTL,
    ) or []
    dept_name = next((d["name"] for d in departments if str(d["id"]) == dept_id), None)

    await state.update_data(pending_department_id=dept_id, pending_department_name=dept_name)
    await state.set_state(Onboarding.confirming_department)
    await callback.message.edit_text(
        _confirmation_text(callback.from_user, dept_name),
        parse_mode="HTML",
        reply_markup=department_confirmation_keyboard(dept_id),
    )


@router.callback_query(F.data == "change_dept")
async def process_department_change(callback: CallbackQuery, state: FSMContext) -> None:
    """Goes back from the confirmation screen to the full department list."""
    if not callback.from_user or not callback.message:
        return
    if await _reject_if_already_set(callback, state):
        return
    await callback.answer()

    departments = await api_client.get(
        path="/api/questions/discovery/departments",
        telegram_id=callback.from_user.id,
        cache_ttl=DEPARTMENTS_CACHE_TTL,
    )
    if not departments:
        await callback.message.edit_text("Couldn't load departments. Please send /start to try again.")
        return

    await state.update_data(pending_department_id=None, pending_department_name=None)
    await state.set_state(Onboarding.selecting_department)
    await callback.message.edit_text(
        _department_prompt(callback.from_user.full_name),
        reply_markup=department_selection_keyboard(departments),
    )


@router.callback_query(F.data.startswith("confirm_dept_"))
async def process_department_confirmation(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Saves the confirmed department to the backend (it is locked after this)
    and shows the main menu. Prevents changing department if one is already set.
    """
    if not callback.from_user or not callback.message:
        return
    if await _reject_if_already_set(callback, state):
        return

    # Always answer callback queries promptly to prevent Telegram timeout
    await callback.answer()

    dept_id = callback.data.split("_", 2)[2]
    user_data = await state.get_data()
    ref_code = user_data.get("temp_ref_code")

    # Explicitly update backend with the new department_id and any referral code
    upsert_res = await api_client.post(
        path="/api/users/upsert",
        telegram_id=callback.from_user.id,
        payload={
            "telegram_id": callback.from_user.id,
            "department_id": dept_id,
            "ref_code": ref_code,
            "first_name": callback.from_user.first_name,
            "last_name": callback.from_user.last_name,
            "telegram_username": callback.from_user.username,
        },
    )

    if not upsert_res or not upsert_res.get("department_id"):
        # Not saved: restore the confirmation screen (the throttle middleware
        # replaced its buttons with "Processing...") so the user can retry.
        await callback.message.edit_text(
            "⚠️ <b>Couldn't save your department right now. Please tap ✅ Confirm again.</b>\n\n"
            + _confirmation_text(callback.from_user, user_data.get("pending_department_name")),
            parse_mode="HTML",
            reply_markup=department_confirmation_keyboard(dept_id),
        )
        return

    await state.update_data(
        department_id=upsert_res.get("department_id"),
        department_name=upsert_res.get("department_name"),
        pending_department_id=None,
        pending_department_name=None,
    )
    await state.set_state(None)  # Clear onboarding state

    # Update message and show main menu
    await callback.message.edit_text(
        f"✅ Department set: <b>{esc((upsert_res.get('department_name') or user_data.get('pending_department_name') or '').title())}</b>",
        parse_mode="HTML",
    )
    await callback.message.answer(
        "Welcome to TeleExam AI. You can now access Practice Mode and Exam Mode.\n\n"
        "Please use the menu below to navigate.",
        reply_markup=main_menu_keyboard(),
    )
