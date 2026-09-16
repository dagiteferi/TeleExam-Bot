from aiogram import F, Router
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.inline import department_selection_keyboard
from bot.keyboards.reply import main_menu_keyboard
from bot.services.api_client import api_client
from bot.states.session_states import Onboarding

router = Router()


# Text message handler during onboarding - re-display buttons
@router.message(Onboarding.selecting_department)
async def handle_text_during_department_selection(message: Message, state: FSMContext) -> None:
    """Shows error when user types text instead of selecting department, re-displays buttons."""
    if not message.from_user:
        return
    
    # Get departments for re-display
    departments = await api_client.get(
        path="/api/questions/discovery/departments",
        telegram_id=message.from_user.id,
    )
    
    if departments:
        welcome_text = (
            f"Hello, {message.from_user.first_name}.\n\n"
            "⚠️ <b>Please use the buttons below to select your department.</b>\n\n"
            "Do not type - tap your department name from the list.",
            "Please select your department below:"
        )
        
        await message.answer(
            "⚠️ <b>Please use the buttons below to select your department.</b>\n\n"
            "Do not type - tap your department name from the list.",
            parse_mode="HTML"
        )
        await message.answer(
            f"Hello, {message.from_user.first_name}.\n\n"
            "Welcome to TeleExam AI. To customize your study experience, "
            "please select your department below:",
            reply_markup=department_selection_keyboard(departments),
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

    user_data = await state.get_data()
    department_id = user_data.get("department_id")

    # If state is missing department_id, check backend database explicitly
    if not department_id:
        user_profile = await api_client.get(
            path="/api/users/me",
            telegram_id=message.from_user.id,
        )
        if user_profile and user_profile.get("department_id"):
            department_id = user_profile.get("department_id")
            await state.update_data(
                department_id=department_id,
                department_name=user_profile.get("department_name"),
                user_id=user_profile.get("user_id"),
                is_pro=user_profile.get("is_pro", False),
            )

    if department_id:
        # Already has department, skip straight to menu
        await message.answer(
            f"Welcome back, {message.from_user.first_name}.\n\n"
            "Ready to continue studying?",
            reply_markup=main_menu_keyboard(),
        )
        return

    # Fetch available departments from the backend
    departments = await api_client.get(
        path="/api/questions/discovery/departments",
        telegram_id=message.from_user.id,
    )

    if not departments:
        await message.answer(
            "Welcome to TeleExam AI.\n\n"
            "Currently, there are no departments available. Please try again later.",
            reply_markup=main_menu_keyboard(),
        )
        return

    welcome_text = (
        f"Hello, {message.from_user.first_name}.\n\n"
        "Welcome to TeleExam AI. To customize your study experience, "
        "please select your department below:"
    )
    
    await state.set_state(Onboarding.selecting_department)
    await message.answer(
        welcome_text,
        reply_markup=department_selection_keyboard(departments),
    )


@router.callback_query(F.data.startswith("select_dept_"))
async def process_department_selection(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Handles department selection, saves to FSM, and confirms to user.
    Prevents changing department if one is already set.
    """
    if not callback.from_user or not callback.message:
        return

    # Check if department is already configured for this user
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

    if existing_dept_id:
        await callback.answer(
            "Your department is already set and cannot be changed.",
            show_alert=True,
        )
        await state.set_state(None)
        return

    # Always answer callback queries promptly to prevent Telegram timeout
    await callback.answer()

    # Extract department ID from callback data
    dept_id = callback.data.split("_", 2)[2]

    # Save selection in FSM state and persist to backend
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

    actual_dept_id = dept_id
    dept_name = None
    if upsert_res and upsert_res.get("department_id"):
        actual_dept_id = upsert_res.get("department_id")
        dept_name = upsert_res.get("department_name")

    await state.update_data(
        department_id=actual_dept_id,
        department_name=dept_name,
    )
    await state.set_state(None)  # Clear onboarding state

    # Update message and show main menu
    await callback.message.edit_text("Department successfully set.")
    await callback.message.answer(
        "Welcome to TeleExam AI. You can now access Practice Mode and Exam Mode.\n\n"
        "Please use the menu below to navigate.",
        reply_markup=main_menu_keyboard(),
    )

