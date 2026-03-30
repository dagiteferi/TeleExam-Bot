from typing import Any, Dict, Optional

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from pydantic import BaseModel

from bot.keyboards.reply import main_menu_keyboard
from bot.services.api_client import api_client
from bot.states.session_states import AIInteraction

router = Router()


# Pydantic models for backend responses
class ExplanationResponse(BaseModel):
    explanation: str


class StudyPlanResponse(BaseModel):
    study_plan_markdown: str


class AIChatResponse(BaseModel):
    response: str


@router.callback_query(F.data.startswith("explain_ai_"))
async def explain_ai_callback(callback: CallbackQuery) -> None:
    """
    Handles requests to explain a question using AI.
    """
    if not callback.message or not callback.from_user:
        await callback.answer("Error processing request.")
        return

    await callback.answer("Generating explanation...", show_alert=False)

    # Parse callback data: "explain_ai_{session_id}_{qtoken}"
    parts = callback.data.split("_", 3)
    if len(parts) != 4:
        await callback.message.answer(
            "Invalid explanation request. Please try again.",
            reply_markup=main_menu_keyboard(),
        )
        return

    _, _, session_id, qtoken = parts

    explanation_data = await api_client.post(
        path="/api/ai/explain",
        telegram_id=callback.from_user.id,
        payload={"session_id": session_id, "qtoken": qtoken},
        response_model=ExplanationResponse,
    )

    if not explanation_data:
        await callback.message.answer(
            "Failed to get explanation. The AI tutor might be busy, please try again later.",
            reply_markup=main_menu_keyboard(),
        )
        return

    await callback.message.answer(
        f"🧠 AI Explanation:\n\n{explanation_data.explanation}",
        reply_markup=main_menu_keyboard(),
    )


@router.message(F.text == "📊 My Study Plan")
async def my_study_plan_handler(message: Message, state: FSMContext) -> None:
    """
    Handles requests to view the user's study plan.
    """
    if not message.from_user:
        return

    # Check for department_id
    user_data = await state.get_data()
    department_id = user_data.get("department_id")
    if not department_id:
        await message.answer(
            "Please use /start to select your department before generating a study plan.",
            reply_markup=main_menu_keyboard(),
        )
        return

    await message.answer("Generating your personalized study plan...")

    study_plan_data = await api_client.post(
        path="/api/ai/study-plan",
        telegram_id=message.from_user.id,
        payload={},
        response_model=StudyPlanResponse,
    )

    if not study_plan_data:
        # As per SRS, handle 402 gracefully. For now, a generic message.
        await message.answer(
            "Failed to retrieve study plan. This might be because you haven't completed "
            "any mock exams yet, or the service is temporarily unavailable. "
            "Please try again later.",
            reply_markup=main_menu_keyboard(),
        )
        return

    await message.answer(
        f"📚 Your Study Plan:\n\n{study_plan_data.study_plan_markdown}",
        parse_mode="Markdown",  # Assuming backend returns Markdown
        reply_markup=main_menu_keyboard(),
    )


@router.message(F.text == "🧠 AI Tutor")
async def ai_tutor_start_handler(message: Message, state: FSMContext) -> None:
    """
    Initiates the AI Tutor chat session.
    """
    if not message.from_user:
        return

    # Check for department_id
    user_data = await state.get_data()
    department_id = user_data.get("department_id")
    if not department_id:
        await message.answer(
            "Please use /start to select your department before using the AI Tutor.",
            reply_markup=main_menu_keyboard(),
        )
        return

    await state.set_state(AIInteraction.chatting)
    await message.answer(
        "Hello! I'm your AI Tutor. Ask me anything about your studies. "
        "Type /end_chat to finish our conversation."
    )


@router.message(AIInteraction.chatting, F.text == "/end_chat")
async def ai_tutor_end_handler(message: Message, state: FSMContext) -> None:
    """
    Ends the AI Tutor chat session.
    """
    if not message.from_user:
        return

    await state.clear()
    await message.answer(
        "AI Tutor chat ended. How else can I help you?",
        reply_markup=main_menu_keyboard(),
    )


@router.message(AIInteraction.chatting)
async def ai_tutor_chat_handler(message: Message) -> None:
    """
    Handles ongoing chat with the AI Tutor.
    """
    if not message.from_user or not message.text:
        return

    await message.answer("Thinking...")  # Acknowledge user input

    ai_response = await api_client.post(
        path="/api/ai/chat",  # Assuming a /api/ai/chat endpoint for dynamic chat
        telegram_id=message.from_user.id,
        payload={"message": message.text},
        response_model=AIChatResponse,
    )

    if not ai_response:
        await message.answer(
            "My AI brain is a bit fuzzy right now. Please try asking again later.",
            reply_markup=main_menu_keyboard(),
        )
        return

    await message.answer(ai_response.response)
