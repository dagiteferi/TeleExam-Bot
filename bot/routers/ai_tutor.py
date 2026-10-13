import asyncio
from typing import Optional

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from pydantic import BaseModel

from bot.keyboards.reply import MAIN_MENU_TEXTS, main_menu_keyboard, chat_menu_keyboard
from bot.services.api_client import api_client
from bot.states.session_states import AIInteraction, ExamSession
from bot.utils.text import answer_long, esc

router = Router()

FREE_DAILY_AI_QUESTIONS = 5  # Matches the backend's free daily chat allowance
MAX_QUESTION_LENGTH = 1000
GENERAL_CHAT_QUESTION_ID = "00000000-0000-0000-0000-000000000000"

# Included first in the dispatcher so it runs before every other router.
chat_exit_router = Router()


def _leaves_chat(text: str | None) -> bool:
    """Menu buttons and commands (except /end_chat) end the AI chat instead of going to the AI."""
    if not text:
        return False
    text = text.strip()
    if text in MAIN_MENU_TEXTS:
        return True
    return text.startswith("/") and not text.startswith("/end_chat")


@chat_exit_router.message(AIInteraction.chatting, F.text.func(_leaves_chat))
async def leave_chat_on_navigation(message: Message, state: FSMContext) -> None:
    """End the chat, then let the normal handler for this button/command run."""
    await state.set_state(None)
    raise SkipHandler()


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
        f"<b>Your Personalized Study Plan</b>",
        divider,
        f"<b>Performance Summary</b>",
        f"{esc(plan.summary)}",
        f"\nExams completed: <b>{plan.total_exams_done}</b>",
        f"Average score: <b>{plan.overall_score_percent:.1f}%</b>",
        "",
        divider,
        "<b>Focus Areas</b>",
    ]

    # Weak topics
    for wt in plan.weak_topics:
        priority_label = f"({esc(wt.focus)} Priority)"
        lines.append(f"• <b>{esc(wt.topic)}</b> — {wt.errors} errors {priority_label}")

    lines += ["", divider, "<b>7-Day Study Plan</b>"]

    # Daily plan
    for d in plan.daily_plan:
        lines.append(f"<b>Day {d.day}:</b> {esc(d.topic)} → {esc(d.action)}")

    lines += ["", divider, "<i>Adhere to this plan daily for optimal results.</i>"]
    return "\n".join(lines)


# ─── Explain with AI (button in practice mode) ───────────────────────────────

@router.callback_query(F.data.startswith("expai_"))
async def explain_ai_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Handles 'Explain with AI' button press after answering a practice question.
    """
    if not callback.message or not callback.from_user:
        return
    await callback.answer("Generating AI explanation...", show_alert=False)
    qtoken = callback.data.split("_", 1)[1]
    await handle_ai_explanation(callback.message, state, qtoken, callback.from_user.id)


async def handle_ai_explanation(message: Message, state: FSMContext, qtoken: str, user_id: int) -> None:
    """Core logic to fetch and display AI explanation, reused by callback and deep link."""
    # Get question context from FSM state
    user_data = await state.get_data()
    question_id = user_data.get("question_id")

    if not question_id:
        await message.answer(
            "❌ Cannot explain — question context lost. Please start a new session.",
            reply_markup=main_menu_keyboard(),
        )
        return

    # Show a "thinking" message first for UX
    thinking_msg = await message.answer("<i>AI Tutor is analyzing...</i>", parse_mode="HTML")

    explanation_data = await api_client.post(
        path="/api/ai/explain",
        telegram_id=user_id,
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
        # If the backend sent a specific explanation (like a Paywall/Pro message), display it
        error_msg = explanation_data.explanation if explanation_data and explanation_data.explanation else "⏳ The AI tutor is currently busy. Please try again in a moment."
        await message.answer(
            esc(error_msg),
            reply_markup=main_menu_keyboard(),
        )
        return

    divider = "━" * 30
    explanation_msg = (
        f"<b>AI Explanation</b>\n"
        f"{divider}\n\n"
        f"{esc(explanation_data.explanation)}"
    )
    if explanation_data.weak_topic_suggestion:
        explanation_msg += f"\n\n{divider}\n<i>Note: {esc(explanation_data.weak_topic_suggestion)}</i>"

    # Keyboard for follow-up
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Ask Follow-up", callback_data="ai_followup")]
    ])

    await answer_long(
        message,
        explanation_msg,
        parse_mode="HTML",
        protect_content=True,
        reply_markup=keyboard
    )


@router.callback_query(F.data == "ai_followup")
async def ai_followup_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Invoked when user taps 'Ask Follow-up' on an AI explanation."""
    await callback.answer()
    
    # Save the current state so we can return to it later
    current_state = await state.get_state()
    await state.update_data(pre_chat_state=current_state, chat_context="question")
    
    await state.set_state(AIInteraction.chatting)
    await callback.message.answer(
        "<b>Follow-up Mode</b>\n"
        "Ask me for any clarification about this question.\n\n"
        "<i>To exit, use the button below or type /end_chat.</i>",
        parse_mode="HTML",
        reply_markup=chat_menu_keyboard()
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

    current_state = await state.get_state()
    await state.update_data(pre_chat_state=current_state, chat_context="general")
    await state.set_state(AIInteraction.chatting)

    department_name = user_data.get("department_name")
    for_department = f" for <b>{esc(department_name.title())}</b>" if department_name else ""
    await message.answer(
        "🧠 <b>AI Tutor</b>\n\n"
        f"Ask me anything about your studies{for_department} and I'll explain it simply.\n\n"
        "💡 <b>Try asking:</b>\n"
        "• <i>Explain [a topic from your course] in simple words</i>\n"
        "• <i>What is the difference between [X] and [Y]?</i>\n"
        "• <i>How should I prepare for my exit exam?</i>\n\n"
        "📌 <b>Tips</b>\n"
        "• Ask one clear question per message.\n"
        "• Stuck on a practice question? Tap <b>🧠 Ask AI Tutor</b> under it — "
        "I'll explain that exact question.\n"
        f"• Free plan: {FREE_DAILY_AI_QUESTIONS} questions per day. PRO: unlimited.\n\n"
        "<i>Type your question below. Tap End Chat when you're done.</i>",
        parse_mode="HTML",
        reply_markup=chat_menu_keyboard()
    )


@router.message(AIInteraction.chatting, F.text == "End Chat")
@router.message(AIInteraction.chatting, Command("end_chat"))
async def ai_tutor_end_handler(message: Message, state: FSMContext) -> None:
    """Ends the AI Tutor chat session."""
    if not message.from_user:
        return
    # If user was in a session, return them to active session state
    user_data = await state.get_data()
    session_id = user_data.get("session_id")
    
    if session_id:
        from bot.routers.sessions import send_question
        
        # Restore pre-chat state (e.g. waiting_for_answer or active)
        pre_chat_state = user_data.get("pre_chat_state")
        if pre_chat_state:
            await state.set_state(pre_chat_state)
        else:
            await state.set_state(ExamSession.active)
            
        await message.answer("✅ Follow-up ended. Resuming your session...")
        await send_question(message, state, session_id, message.from_user.id)
    else:
        await state.set_state(None)
        await message.answer(
            "AI Tutor session ended. Continuing your studies.",
            reply_markup=main_menu_keyboard(),
        )


@router.message(AIInteraction.chatting, ~F.text.func(_leaves_chat))
async def ai_tutor_chat_handler(message: Message, state: FSMContext) -> None:
    """Handles ongoing chat with the AI Tutor."""
    if not message.from_user or not message.text:
        return

    if len(message.text) > MAX_QUESTION_LENGTH:
        await message.answer(
            f"✂️ That's a bit long. Please keep your question under {MAX_QUESTION_LENGTH} characters."
        )
        return

    # Follow-ups are about the current practice question; the menu AI Tutor is a
    # general study chat, sent with the all-zero id the backend treats as "no question".
    user_data = await state.get_data()
    question_id = GENERAL_CHAT_QUESTION_ID
    if user_data.get("chat_context") != "general":
        question_id = user_data.get("question_id") or GENERAL_CHAT_QUESTION_ID

    thinking_msg = await message.answer("<i>Analyzing...</i>", parse_mode="HTML")

    ai_response = await api_client.post(
        path="/api/ai/chat",
        telegram_id=message.from_user.id,
        payload={
            "message": message.text,
            "question_id": question_id,
        },
        response_model=AIChatResponse,
        timeout=60,
    )

    try:
        await thinking_msg.delete()
    except Exception:
        pass

    if not ai_response or not ai_response.success:
        error_msg = ai_response.ai_response if ai_response and ai_response.ai_response else "⏳ My AI brain is a bit busy right now. Please try again in a moment."
        await message.answer(esc(error_msg))
        return

    divider = "━" * 20
    await answer_long(
        message,
        f"{esc(ai_response.ai_response)}\n\n"
        f"{divider}\n"
        f"<i>Tap End Chat or type /end_chat to exit</i>",
        parse_mode="HTML",
        protect_content=True,
    )


# ─── Study Plan ──────────────────────────────────────────────────────────────

@router.message(F.text == "📅 Study Plan")
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
        "<i>Analyzing exam history and generating personalized study plan...</i>",
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
        
        from bot.keyboards.inline import pro_plan_keyboard
        if "Upgrade to PRO" in prereq_msg:
            reply_markup = pro_plan_keyboard()
        else:
            reply_markup = main_menu_keyboard()
        
        await message.answer(
            f"ℹ️ {esc(prereq_msg)}",
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
        return


    formatted = _format_study_plan(study_plan_data.study_plan)
    await answer_long(
        message,
        formatted,
        parse_mode="HTML",
        protect_content=True,
        reply_markup=main_menu_keyboard(),
    )
