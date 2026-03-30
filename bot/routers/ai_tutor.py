import asyncio
from typing import Optional

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from pydantic import BaseModel

from bot.keyboards.reply import main_menu_keyboard
from bot.services.api_client import api_client
from bot.states.session_states import AIInteraction

router = Router()


# ─── Pydantic models matching backend schemas ────────────────────────────────

class ExplanationResponse(BaseModel):
    success: bool = True
    explanation: str
    key_points: list[str] = []
    weak_topic_suggestion: Optional[str] = None


class AIChatResponse(BaseModel):
    success: bool = True
    ai_response: str  # Note: backend returns 'ai_response', not 'response'


class StudyTopic(BaseModel):
    topic: str
    errors: int
    focus: str


class StudyDay(BaseModel):
    day: int
    topic: str
    action: str


class StudyPlanDetails(BaseModel):
    summary: str
    total_exams_done: int
    overall_score_percent: float
    weak_topics: list[StudyTopic] = []
    daily_plan: list[StudyDay] = []


class StudyPlanResponse(BaseModel):
    success: bool = True
    study_plan: Optional[StudyPlanDetails] = None
    message: Optional[str] = None


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _format_study_plan(plan: StudyPlanDetails) -> str:
    """Formats a study plan into a beautiful, readable Telegram message."""
    divider = "━" * 30

    # Header
    lines = [
        f"📚 <b>Your Personalized Study Plan</b>",
        divider,
        f"📊 <b>Performance Summary</b>",
        f"{plan.summary}",
        f"\n🏆 Exams completed: <b>{plan.total_exams_done}</b>",
        f"📈 Average score: <b>{plan.overall_score_percent:.1f}%</b>",
        "",
        divider,
        "⚠️ <b>Your Weak Topics</b>",
    ]

    # Weak topics
    for wt in plan.weak_topics:
        icon = "🔴" if wt.focus == "High Priority" else "🟡" if wt.focus == "Medium" else "🟢"
        lines.append(f"{icon}  <b>{wt.topic}</b>  —  {wt.errors} errors  ({wt.focus})")

    lines += ["", divider, "📅 <b>7-Day Study Plan</b>"]

    # Daily plan
    for d in plan.daily_plan:
        lines.append(f"<b>Day {d.day}:</b>  {d.topic}  →  {d.action}")

    lines += ["", divider, "<i>💡 Stick to this plan daily for best results!</i>"]
    return "\n".join(lines)


# ─── Explain with AI (button in practice mode) ───────────────────────────────

@router.callback_query(F.data.startswith("expai_"))
async def explain_ai_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Handles 'Explain with AI' button press after answering a practice question.
    Parses callback data: 'expai_{qtoken}'
    Uses question_id stored in FSM state and the answered choice.
    """
    if not callback.message or not callback.from_user:
        await callback.answer("Error processing request.")
        return

    await callback.answer("Generating AI explanation...", show_alert=False)

    # Get question context from FSM state
    user_data = await state.get_data()
    question_id = user_data.get("question_id")

    if not question_id:
        await callback.message.answer(
            "❌ Cannot explain — question context lost. Please start a new session.",
            reply_markup=main_menu_keyboard(),
        )
        return

    # Show a "thinking" message first for UX
    thinking_msg = await callback.message.answer("🧠 <i>AI Tutor is thinking...</i>", parse_mode="HTML")

    explanation_data = await api_client.post(
        path="/api/ai/explain",
        telegram_id=callback.from_user.id,
        payload={
            "question_id": question_id,
            "user_answer": None,  # Backend will use context from the session
        },
        response_model=ExplanationResponse,
        timeout=60,  # AI calls can take longer
    )

    # Delete the "thinking" message
    try:
        await thinking_msg.delete()
    except Exception:
        pass

    if not explanation_data or not explanation_data.success:
        await callback.message.answer(
            "⏳ The AI tutor is currently busy. Please try again in a moment.",
            reply_markup=main_menu_keyboard(),
        )
        return

    divider = "━" * 30
    explanation_msg = (
        f"🧠 <b>AI Explanation</b>\n"
        f"{divider}\n\n"
        f"{explanation_data.explanation}"
    )
    if explanation_data.weak_topic_suggestion:
        explanation_msg += f"\n\n{divider}\n💡 <i>{explanation_data.weak_topic_suggestion}</i>"

    await callback.message.answer(
        explanation_msg,
        parse_mode="HTML",
        protect_content=True,
    )


# ─── AI Chat Tutor ───────────────────────────────────────────────────────────

@router.message(F.text == "🧠 AI Tutor")
async def ai_tutor_start_handler(message: Message, state: FSMContext) -> None:
    """Initiates the AI Tutor chat session."""
    if not message.from_user:
        return

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
        "👋 <b>Hello! I'm your AI Tutor.</b>\n\n"
        "Ask me <b>any question</b> about your studies and I'll help you understand it.\n\n"
        "<i>Type /end_chat to finish our conversation.</i>",
        parse_mode="HTML",
    )


@router.message(AIInteraction.chatting, F.text == "/end_chat")
async def ai_tutor_end_handler(message: Message, state: FSMContext) -> None:
    """Ends the AI Tutor chat session."""
    if not message.from_user:
        return
    await state.set_state(None)  # Return to previous state, not clear all
    await message.answer(
        "✅ AI Tutor chat ended.\n\nGood luck with your studies! 🎓",
        reply_markup=main_menu_keyboard(),
    )


@router.message(AIInteraction.chatting)
async def ai_tutor_chat_handler(message: Message, state: FSMContext) -> None:
    """Handles ongoing chat with the AI Tutor."""
    if not message.from_user or not message.text:
        return

    # Get question_id from state if user is in context of a question
    user_data = await state.get_data()
    question_id = user_data.get("question_id", "00000000-0000-0000-0000-000000000000")

    thinking_msg = await message.answer("🧠 <i>Thinking...</i>", parse_mode="HTML")

    ai_response = await api_client.post(
        path="/api/ai/chat",
        telegram_id=message.from_user.id,
        payload={
            "message": message.text,
            "question_id": question_id,  # Backend requires this field
        },
        response_model=AIChatResponse,
        timeout=60,
    )

    try:
        await thinking_msg.delete()
    except Exception:
        pass

    if not ai_response or not ai_response.success:
        await message.answer(
            "⏳ My AI brain is a bit busy right now. Please try again in a moment."
        )
        return

    await message.answer(
        f"🤖 {ai_response.ai_response}",  # Note: 'ai_response' field, not 'response'
        parse_mode="HTML",
        protect_content=True,
    )


# ─── Study Plan ──────────────────────────────────────────────────────────────

@router.message(F.text == "📊 My Study Plan")
async def my_study_plan_handler(message: Message, state: FSMContext) -> None:
    """Handles study plan generation."""
    if not message.from_user:
        return

    user_data = await state.get_data()
    department_id = user_data.get("department_id")
    if not department_id:
        await message.answer(
            "Please use /start to select your department first.",
            reply_markup=main_menu_keyboard(),
        )
        return

    thinking_msg = await message.answer(
        "📊 <i>Analyzing your exam history and generating a personalized study plan...</i>",
        parse_mode="HTML",
    )

    study_plan_data = await api_client.post(
        path="/api/ai/study-plan",
        telegram_id=message.from_user.id,
        payload={},  # Backend StudyPlanRequest is empty
        response_model=StudyPlanResponse,
        timeout=90,
    )

    try:
        await thinking_msg.delete()
    except Exception:
        pass

    if not study_plan_data:
        await message.answer(
            "⏳ Study plan service is temporarily unavailable. Please try again later.",
            reply_markup=main_menu_keyboard(),
        )
        return

    if not study_plan_data.success or not study_plan_data.study_plan:
        # Backend returns a user-friendly prereq message
        prereq_msg = study_plan_data.message or (
            "You need to complete at least one full year's past exam before "
            "I can generate your personalized study plan.\n\n"
            "📚 Go to <b>Take Exam</b> → select any year → finish all questions."
        )
        await message.answer(
            f"ℹ️ {prereq_msg}",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        return

    formatted = _format_study_plan(study_plan_data.study_plan)
    await message.answer(
        formatted,
        parse_mode="HTML",
        protect_content=True,
        reply_markup=main_menu_keyboard(),
    )
