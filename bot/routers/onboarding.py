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
    Handles the /start command, fetching available departments for the user to select.
    The AutoUpsertMiddleware ensures the user is registered in the backend.
    """
    if not message.from_user:
        return

    # Clear any existing state
    await state.clear()

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
    Processes the user's department selection and transitions to the main menu.
    """
    if not callback.from_user or not callback.message:
        return

    # Extract department ID from callback data
    dept_id = callback.data.split("_", 2)[2]
    
    # Save selection in FSM state
    await state.update_data(department_id=dept_id)
    await state.set_state(None) # Clear onboarding state

    await callback.answer("Department selected successfully! ✅")
    
    # Send a confirmation message and show the main menu
    await callback.message.edit_text(
        f"Great! You've selected your department. 🎓\n\n"
        "Now you can take mock exams, practice questions, and use the AI Tutor "
        "tailored to your field of study."
    )
    await callback.message.answer(
        "What would you like to do today?",
        reply_markup=main_menu_keyboard(),
    )
