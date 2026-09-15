from aiogram import F, Router
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.inline import department_selection_keyboard
from bot.keyboards.reply import main_menu_keyboard
from bot.services.api_client import api_client
from bot.states.session_states import Onboarding

router = Router()

# Text message handlers to prevent text input during onboarding
@router.message(Onboarding.selecting_department)
async def handle_text_during_department_selection(message: Message, state: FSMContext) -> None:
    """Shows error when user types text instead of selecting department."""
    if not message.from_user:
        return
    
    departments = await api_client.get(
        path="/api/questions/discovery/departments",
        telegram_id=message.from_user.id,
    )
    
    if departments:
        await message.answer(
            "⚠️ <b>Please use the buttons below to select your department.</b>\n\n"
            "Do not type - tap your department name from the list.",
            parse_mode="HTML"
        )
        await message.answer(
            "Select your department:",
            reply_markup=department_selection_keyboard(departments),
        )
    else:
        await message.answer(
            "⚠️ <b>Please use the buttons below to select your department.</b>\n\n"
            "Currently no departments are available.",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )


# Main menu text handler - blocks non-command text
@router.message()
async def handle_text_in_main_menu(message: Message) -> None:
    """Shows error when user types text that matches menu options instead of using buttons."""
    if not message.from_user:
        return
    
    # Skip if it's a command (starts with /)
    if message.text and message.text.startswith("/"):
        return
    
    # Check if text looks like a menu option
    text_lower = message.text.lower() if message.text else ""
    menu_keywords = ["exam", "practice", "ai", "progress", "invite", "saved", "study", "plan"]
    
    if any(keyword in text_lower for keyword in menu_keywords):
        await message.answer(
            "⚠️ <b>Please use the buttons below to select an option.</b>\n\n"
            "Do not type - tap the button for your choice.",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard()
        )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, command: CommandObject) -> None:
    if not message.from_user:
        return

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

    if department_id:
        await message.answer(
            f"Welcome back, {message.from_user.first_name}.\n\n"
            "Ready to continue studying?",
            reply_markup=main_menu_keyboard(),
        )
        return

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

    await state.set_state(Onboarding.selecting_department)
    await message.answer(
        f"Hello, {message.from_user.first_name}.\n\n"
        "Welcome to TeleExam AI. To customize your study experience, "
        "please select your department below:",
        reply_markup=department_selection_keyboard(departments),
    )


@router.callback_query(F.data.startswith("select_dept_"), Onboarding.selecting_department)
async def process_department_selection(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return

    await callback.answer()
    dept_id = callback.data.split("_", 2)[2]

    user_data = await state.get_data()
    ref_code = user_data.get("temp_ref_code")

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
    await state.set_state(None)

    await callback.message.edit_text("Department successfully set.")
    await callback.message.answer(
        "Welcome to TeleExam AI. You can now access Practice Mode and Exam Mode.\n\n"
        "Please use the menu below to navigate.",
        reply_markup=main_menu_keyboard(),
    )
