from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.inline import department_selection_keyboard
from bot.keyboards.reply import main_menu_keyboard
from bot.services.api_client import api_client
from bot.states.session_states import Onboarding

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    """
    Handles the /start command, fetching available departments if none selected.
    """
    if not message.from_user:
        return

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
    await state.update_data(department_id=dept_id)
    
    # Explicitly update backend with the new department_id
    await api_client.post(
        path="/api/users/upsert",
        telegram_id=callback.from_user.id,
        payload={
            "telegram_id": callback.from_user.id,
            "department_id": dept_id,
        },
    )
    
    await state.set_state(None)  # Clear onboarding state

    # Update message and show main menu
    await callback.message.edit_text("Department selected successfully! ✅")
    await callback.message.answer(
        "Welcome to TeleExam AI! You can now start practicing or take mock exams. "
        "Use the menu below to navigate.",
        reply_markup=main_menu_keyboard(),
    )
