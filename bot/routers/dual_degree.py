from typing import Optional

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import settings
from bot.keyboards.inline import (
    department_selection_keyboard,
    dual_department_confirmation_keyboard,
    dual_pay_keyboard,
)
from bot.keyboards.reply import MAIN_MENU_TEXTS, MenuState, current_menu_state, main_menu_keyboard
from bot.middlewares.auto_upsert import profile_from_response
from bot.routers.onboarding import DEPARTMENTS_CACHE_TTL
from bot.routers.payment import _send_payment_info
from bot.services.api_client import api_client
from bot.states.session_states import DualDegree
from bot.utils.text import esc

router = Router()


def _dual_prompt(primary_name: Optional[str]) -> str:
    return (
        "🎓 <b>Dual Degree</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Main department: <b>{esc((primary_name or 'Unknown').title())}</b>\n\n"
        "Select your <b>second department</b> below. "
        f"After you confirm, pay <b>{settings.DUAL_DEPT_PRICE_BIRR} Birr</b> "
        "to unlock all of its exams and practice courses."
    )


def _confirmation_text(primary_name: Optional[str], dept_name: Optional[str]) -> str:
    return (
        "<b>Please confirm your second department:</b>\n\n"
        f"🎓 <b>Main:</b> {esc((primary_name or 'Unknown').title())}\n"
        f"🎓 <b>Second:</b> {esc((dept_name or 'Unknown').title())}\n\n"
        f"💰 Unlock price: <b>{settings.DUAL_DEPT_PRICE_BIRR} Birr</b>\n"
        "⚠️ Once the payment is approved, your second department <b>cannot be changed</b>."
    )


async def _fresh_profile(telegram_id: int, state: FSMContext) -> Optional[dict]:
    """Reads the profile from the backend so PRO/unlock status is never stale here."""
    profile = await api_client.get(path="/api/users/me", telegram_id=telegram_id)
    if profile:
        await state.update_data(**profile_from_response(profile))
        current_menu_state.set(MenuState.from_profile(profile))
    return profile


async def _department_list(telegram_id: int) -> list:
    return await api_client.get(
        path="/api/questions/discovery/departments",
        telegram_id=telegram_id,
        cache_ttl=DEPARTMENTS_CACHE_TTL,
    ) or []


@router.message(F.text == "🎓 Dual Degree")
async def dual_degree_menu(message: Message, state: FSMContext) -> None:
    """Entry point: explains the dual plan, or shows the right next step for this user."""
    if not message.from_user:
        return

    profile = await _fresh_profile(message.from_user.id, state)
    if not profile:
        await message.answer("Couldn't load your profile. Please try again in a moment.")
        return

    if not profile.get("department_id"):
        await message.answer("Please use /start to choose your main department first.")
        return

    if not profile.get("is_pro") and not profile.get("is_full_access"):
        await message.answer(
            "🎓 <b>Dual Degree</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Studying two departments? You can unlock a second one.\n\n"
            f"1️⃣ Upgrade to PRO for your main department — <b>{settings.PRO_PRICE_BIRR} Birr</b>\n"
            f"2️⃣ Add your second department — <b>{settings.DUAL_DEPT_PRICE_BIRR} Birr</b>\n\n"
            "Start by upgrading to PRO:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"💎 Upgrade to PRO — {settings.PRO_PRICE_BIRR} Birr",
                    callback_data="buy_pro",
                )],
            ]),
        )
        return

    secondary_name = (profile.get("secondary_department_name") or "").title()
    if profile.get("has_dual_access"):
        await _send_switch_screen(message, profile)
        return

    if profile.get("secondary_department_id"):
        await message.answer(
            f"🎓 Your second department is <b>{esc(secondary_name)}</b>, but it is still locked.\n\n"
            f"Pay <b>{settings.DUAL_DEPT_PRICE_BIRR} Birr</b> to unlock it. "
            "If you already sent a receipt, please wait for the admin to approve it.",
            parse_mode="HTML",
            reply_markup=dual_pay_keyboard(),
        )
        return

    await _show_department_list(message, state, profile, edit=False)


async def _show_department_list(target: Message, state: FSMContext, profile: dict, *, edit: bool) -> None:
    departments = await _department_list(target.chat.id)
    choices = [d for d in departments if str(d["id"]) != str(profile.get("department_id"))]
    if not choices:
        text = "There are no other departments available right now. Please try again later."
        await (target.edit_text(text) if edit else target.answer(text))
        return

    await state.set_state(DualDegree.selecting_department)
    keyboard = department_selection_keyboard(choices, callback_prefix="select_dual_dept_")
    text = _dual_prompt(profile.get("department_name"))
    if edit:
        await target.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=keyboard)


@router.callback_query(F.data.startswith("select_dual_dept_"))
async def process_dual_selection(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    await callback.answer()

    dept_id = callback.data.removeprefix("select_dual_dept_")
    departments = await _department_list(callback.from_user.id)
    dept_name = next((d["name"] for d in departments if str(d["id"]) == dept_id), None)
    user_data = await state.get_data()

    await state.update_data(pending_dual_department_id=dept_id, pending_dual_department_name=dept_name)
    await state.set_state(DualDegree.confirming_department)
    await callback.message.edit_text(
        _confirmation_text(user_data.get("department_name"), dept_name),
        parse_mode="HTML",
        reply_markup=dual_department_confirmation_keyboard(dept_id),
    )


@router.callback_query(F.data == "change_dual_dept")
async def process_dual_change(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return

    profile = await _fresh_profile(callback.from_user.id, state)
    if profile and profile.get("secondary_department_unlocked"):
        await callback.answer("Your second department is already unlocked and cannot be changed.", show_alert=True)
        await state.set_state(None)
        return
    await callback.answer()
    if not profile:
        await callback.message.edit_text("Couldn't load your profile. Please try again in a moment.")
        return

    await state.update_data(pending_dual_department_id=None, pending_dual_department_name=None)
    await _show_department_list(callback.message, state, profile, edit=True)


@router.callback_query(F.data.startswith("confirm_dual_dept_"))
async def process_dual_confirmation(callback: CallbackQuery, state: FSMContext) -> None:
    """Saves the second department, then shows the payment instructions for the dual fee."""
    if not callback.from_user or not callback.message:
        return
    await callback.answer()

    dept_id = callback.data.removeprefix("confirm_dual_dept_")
    user_data = await state.get_data()

    res = await api_client.post(
        path="/api/users/dual-department",
        telegram_id=callback.from_user.id,
        payload={"department_id": dept_id},
    )
    if not res or str(res.get("secondary_department_id")) != dept_id:
        await callback.message.edit_text(
            "⚠️ <b>Couldn't save your second department.</b>\n\n"
            "Make sure your PRO plan is active, then tap 🎓 Dual Degree to try again.",
            parse_mode="HTML",
        )
        await state.set_state(None)
        return

    await state.update_data(
        **profile_from_response(res),
        pending_dual_department_id=None,
        pending_dual_department_name=None,
    )
    await state.set_state(None)

    dept_name = esc((res.get("secondary_department_name") or "").title())
    if res.get("has_dual_access"):
        current_menu_state.set(MenuState.from_profile(res))
        await callback.message.edit_text(
            f"✅ Second department set and unlocked: <b>{dept_name}</b>",
            parse_mode="HTML",
        )
        await _send_switch_screen(callback.message, res)
        return

    await callback.message.edit_text(
        f"✅ Second department set: <b>{dept_name}</b>\n\n"
        "Complete the payment below to unlock it.",
        parse_mode="HTML",
    )
    await state.update_data(payment_kind="dual_department")
    await _send_payment_info(callback.message, callback.from_user.id, kind="dual_department")


# ── Switching between the two departments (dual access only) ─────────────────

def _switch_keyboard(profile: dict) -> InlineKeyboardMarkup:
    active_id = str(profile.get("active_department_id") or profile.get("department_id"))
    rows = []
    for dept_id, name in (
        (profile.get("department_id"), profile.get("department_name")),
        (profile.get("secondary_department_id"), profile.get("secondary_department_name")),
    ):
        if not dept_id:
            continue
        label = (name or "Department").title()
        if str(dept_id) == active_id:
            rows.append([InlineKeyboardButton(text=f"✅ {label} (studying now)", callback_data="switch_dept_current")])
        else:
            rows.append([InlineKeyboardButton(text=f"🔄 Switch to {label}", callback_data=f"switch_dept_{dept_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_switch_screen(target: Message, profile: dict) -> None:
    active_name = (profile.get("active_department_name") or profile.get("department_name") or "").title()
    await target.answer(
        "🔄 <b>Switch Department</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"You are studying: <b>{esc(active_name)}</b>\n\n"
        "Exams, practice, progress and AI study plans follow the department you choose.",
        parse_mode="HTML",
        reply_markup=_switch_keyboard(profile),
    )


@router.message(F.text == "🔄 Switch Department")
async def switch_department_menu(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    profile = await _fresh_profile(message.from_user.id, state)
    if not profile:
        await message.answer("Couldn't load your profile. Please try again in a moment.")
        return
    if not profile.get("has_dual_access"):
        # Dual access ended (or never started): show the Dual Degree steps instead.
        await dual_degree_menu(message, state)
        return
    await _send_switch_screen(message, profile)


@router.callback_query(F.data == "switch_dept_current")
async def switch_to_current_department(callback: CallbackQuery) -> None:
    await callback.answer("You are already studying this department.")


@router.callback_query(F.data.startswith("switch_dept_"))
async def process_department_switch(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    await callback.answer()

    dept_id = callback.data.removeprefix("switch_dept_")
    res = await api_client.post(
        path="/api/users/active-department",
        telegram_id=callback.from_user.id,
        payload={"department_id": dept_id},
    )
    if not res:
        await callback.message.edit_text(
            "⚠️ Couldn't switch department. Your Dual Degree may not be active — tap 🎓 Dual Degree to check."
        )
        return

    await state.update_data(**profile_from_response(res))
    menu = MenuState.from_profile(res)
    current_menu_state.set(menu)
    active_name = esc((res.get("active_department_name") or "").title())
    await callback.message.edit_text(f"✅ You are now studying <b>{active_name}</b>.", parse_mode="HTML")
    await callback.message.answer(
        f"📝 Exam Mode, 🎯 Practice Mode, 📊 My Progress and 📅 Study Plan now use <b>{active_name}</b>.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(menu),
    )


@router.message(DualDegree.selecting_department)
@router.message(DualDegree.confirming_department)
async def handle_text_during_dual_selection(message: Message, state: FSMContext) -> None:
    """Typing is not accepted while choosing; menu buttons and commands leave the flow."""
    if not message.from_user:
        return
    text = (message.text or "").strip()
    if text.startswith("/") or text in MAIN_MENU_TEXTS:
        await state.set_state(None)
        from bot.routers.sessions import _route_nav_command
        await _route_nav_command(message, state)
        return
    await message.answer(
        "⚠️ <b>Please use the buttons above to choose your second department.</b>\n\n"
        "Tap 🎓 Dual Degree to start again.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
