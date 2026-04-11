from aiogram import F, Router
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.inline import department_selection_keyboard
from bot.keyboards.reply import main_menu_keyboard
from bot.services.api_client import api_client
from bot.states.session_states import Onboarding

router = Router()


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
            # We'll use this ref_code during the first upsert (department selection)


    user_data = await state.get_data()
    department_id = user_data.get("department_id")

    if department_id:
        # Already has department, skip straight to menu
        await message.answer(
            f"Welcome back, {message.from_user.first_name}! 👋\n\n"
            "Ready to study today?",
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
            "Welcome to TeleExam AI Bot! 👋\n\n"
            "Currently, there are no departments available. Please try again later.",
            reply_markup=main_menu_keyboard(),
        )
        return

    welcome_text = (
        f"Hello, {message.from_user.first_name}! 👋\n\n"
        "Welcome to TeleExam AI Bot! To provide you with the best study experience, "
        "please select your department from the list below:"
    )
    
    await state.set_state(Onboarding.selecting_department)
    await message.answer(
        welcome_text,
        reply_markup=department_selection_keyboard(departments),
    )


@router.callback_query(F.data.startswith("select_dept_"), Onboarding.selecting_department)
async def process_department_selection(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Handles department selection, saves to FSM, and confirms to user.
    """
    if not callback.from_user or not callback.message:
        return

    # Always answer callback queries promptly to prevent Telegram timeout
    await callback.answer()

    # Extract department ID from callback data
    dept_id = callback.data.split("_", 2)[2]

    # Save selection in FSM state and persist to backend
    # Extract temp_ref_code if it exists
    user_data = await state.get_data()
    ref_code = user_data.get("temp_ref_code")

    # Explicitly update backend with the new department_id and any referral code
    await api_client.post(
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

    await state.update_data(department_id=dept_id)
    await state.set_state(None)  # Clear onboarding state

    # Update message and show main menu
    await callback.message.edit_text("Department selected successfully! ✅")
    await callback.message.answer(
        "Welcome to TeleExam AI! You can now start practicing or take mock exams. "
        "Use the menu below to navigate.",
        reply_markup=main_menu_keyboard(),
    )
