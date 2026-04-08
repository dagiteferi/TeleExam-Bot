from typing import Any, Dict, List, Literal, Optional

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from pydantic import BaseModel

from bot.keyboards.inline import (
    course_selection_keyboard,
    exam_selection_keyboard,
    question_choices_keyboard,
    session_action_keyboard,
)
from bot.keyboards.reply import main_menu_keyboard
from bot.services.api_client import api_client
from bot.states.session_states import ExamSession
from bot.utils.watermark import embed_watermark

router = Router()


# Pydantic models for backend responses
class SessionStartResponse(BaseModel):
    session_id: str


class QuestionPayload(BaseModel):
    question_id: str
    index: int
    total: int
    prompt: Optional[str] = None
    options: List[str]
    qtoken: str
    year: Optional[int] = None
    semester: Optional[str] = None


class GetQuestionResponse(BaseModel):
    session_id: str
    question: QuestionPayload


class AnswerResponse(BaseModel):
    is_correct: Optional[bool] = None
    correct_choice: Optional[str] = None
    explanation: Optional[str] = None


class SessionSubmitResponse(BaseModel):
    score: int
    total_questions: int
    message: str
    score_percent: float # Added for extra info


CHOICE_LABELS = ["A", "B", "C", "D", "E", "F"]


def _format_question_message(question: QuestionPayload, mode: str) -> str:
    """Formats question text with number, choices, and mode badge."""
    q_num = question.index + 1
    q_total = question.total
    mode_icon = "📚" if mode == "exam" else "📝"

    # Header line: progress and mode
    header = f"{mode_icon}  <b>Question {q_num} of {q_total}</b>"
    divider = "━" * 30

    # Question text (bold)
    question_text = f"<b>{question.prompt or 'No question text provided.'}</b>"

    # Each option on its own line
    options_lines = []
    for i, option_text in enumerate(question.options):
        label = CHOICE_LABELS[i] if i < len(CHOICE_LABELS) else str(i + 1)
        options_lines.append(f"<b>{label})</b>  {option_text}")

    options_block = "\n\n".join(options_lines)

    # Historical Context (if available)
    context_footer = ""
    if question.year and question.semester:
        context_footer = f"📅 <i>Source: {question.year} - {question.semester.title()}</i>\n"

    clarity_link = ""
    if mode == "practice":
        # Note: Using absolute Telegram deep link to trigger /start with payload
        # This acts as a text link that can be clicked
        clarity_link = f" or 🧠 <a href='https://t.me/TeleExamAI_bot?start=expai_{question.qtoken}'>Ask AI Clarity</a>"

    return (
        f"{header}\n"
        f"{divider}\n"
        f"{context_footer}"
        f"{divider}\n\n"
        f"{question_text}\n\n"
        f"{divider}\n\n"
        f"{options_block}\n\n"
        f"{divider}\n"
        f"<i>👆 Tap your answer below{clarity_link}</i>"
    )


async def send_question(
    message: Message, state: FSMContext, session_id: str, telegram_id: int
) -> None:
    """Helper to fetch and send the next question to the user."""
    question_wrapped = await api_client.get(
        path=f"/api/sessions/{session_id}/question",
        telegram_id=telegram_id,
        response_model=GetQuestionResponse,
    )

    if not question_wrapped:
        await message.answer(
            "Failed to fetch question. Please try again later.",
            reply_markup=main_menu_keyboard(),
        )
        await state.clear()
        return
    # Handle dictionary (error) response or model instance
    if isinstance(question_wrapped, dict):
        # Extract error message if present
        detail = question_wrapped.get("detail", question_wrapped.get("error", {}))
        msg = detail.get("message") if isinstance(detail, dict) else str(detail)
        await message.answer(f"⚠️  {msg or 'Unexpected error fetching question.'}")
        await state.clear()
        return

    question = question_wrapped.question
    user_data = await state.get_data()
    mode = user_data.get("mode", "exam")

    has_next = (question.index + 1 < question.total)

    await state.update_data(
        question_id=question.question_id,
        qtoken=question.qtoken,
        has_next=has_next,
        is_practice=(mode == "practice"),
        question_options=question.options,
    )
    await state.set_state(ExamSession.waiting_for_answer)

    keyboard = question_choices_keyboard(
        question.question_id, question.options, question.qtoken
    )
    import time
    question_text = _format_question_message(question, mode)
    # Embed invisible watermark with user's telegram_id for scraper tracing
    watermarked_text = embed_watermark(question_text, telegram_id)

    # Record the timestamp when question was sent (for bot speed detection)
    await state.update_data(question_sent_at=time.time())

    await message.answer(
        watermarked_text,
        reply_markup=keyboard,
        parse_mode="HTML",
        protect_content=True,
    )


@router.message(F.text == "📚 Take Exam")
@router.message(F.text == "📝 Practice Questions")
async def start_session_handler(message: Message, state: FSMContext) -> None:
    """
    Handles starting a new exam or practice session based on user's menu choice.
    """
    if not message.from_user:
        return

    mode: Literal["exam", "practice"]
    if message.text == "📚 Take Exam":
        mode = "exam"
    elif message.text == "📝 Practice Questions":
        mode = "practice"
    else:
        await message.answer("Invalid session type. Please choose from the menu.")
        return

    # Fetch stored department_id from FSM state
    user_data = await state.get_data()
    department_id = user_data.get("department_id")

    if not department_id:
        await message.answer(
            "It looks like you haven't selected a department yet. "
            "Please use /start to choose your field of study first.",
            reply_markup=main_menu_keyboard(),
        )
        return

    if mode == "exam":
        # Fetch available exams for the department
        exams = await api_client.get(
            path=f"/api/questions/discovery/department/{department_id}/exams",
            telegram_id=message.from_user.id,
        )

        if not exams:
            await message.answer(
                "Currently, there are no mock exams available for your department.",
                reply_markup=main_menu_keyboard(),
            )
            return

        await state.set_state(ExamSession.selecting_exam)
        await message.answer(
            "Select an exam to start:",
            reply_markup=exam_selection_keyboard(exams),
        )
    else:
        # Fetch available courses for the department (Discovery)
        courses = await api_client.get(
            path=f"/api/questions/discovery/courses?department_id={department_id}",
            telegram_id=message.from_user.id,
        )

        if not courses:
            await message.answer(
                "Currently, there are no courses available for practice.",
                reply_markup=main_menu_keyboard(),
            )
            return

        await state.set_state(ExamSession.selecting_course)
        await message.answer(
            "Select a course to practice:",
            reply_markup=course_selection_keyboard(courses),
        )


@router.callback_query(F.data.startswith("select_course_"), ExamSession.selecting_course)
async def process_course_selection(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Handles selection of a specific course and starts a practice session.
    """
    if not callback.from_user or not callback.message:
        return

    # Always answer callback queries promptly to prevent Telegram timeout
    await callback.answer()

    # Extract course ID from callback data
    course_id = callback.data.split("_", 2)[2]
    user_data = await state.get_data()
    department_id = user_data.get("department_id")

    await callback.message.edit_text("Initializing practice session...")

    # Start the session using the course_id. 
    # Note: Backend might require topic_id; we'll trial using course_id as topic_id if needed.
    res = await api_client.post(
        path="/api/sessions/start",
        telegram_id=callback.from_user.id,
        payload={
            "mode": "practice", 
            "department_id": department_id, 
            "course_id": course_id,
        },
        response_model=SessionStartResponse,
    )

    if not res:
        await callback.message.answer(
            "Failed to start practice session. Please try again later.",
            reply_markup=main_menu_keyboard(),
        )
        return

    # Handle active session conflict (409)
    if isinstance(res, dict) and res.get("detail", {}).get("error", {}).get("code") == "active_session_exists":
        session_id = res["detail"]["error"]["session_id"]
        await callback.message.answer("You have an active session. Resuming...")
    else:
        # Successful new session
        session_id = res.session_id

    await state.update_data(session_id=session_id, mode="practice")
    await state.set_state(ExamSession.active)
    await send_question(callback.message, state, session_id, callback.from_user.id)


@router.callback_query(F.data.startswith("ex_"), ExamSession.selecting_exam)
async def process_exam_selection(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Handles selection of a specific exam and starts the session.
    """
    if not callback.from_user or not callback.message:
        return

    # Always answer callback queries promptly to prevent Telegram timeout
    await callback.answer()

    # Parse callback data: "ex_{id}_{year}_{semester}"
    parts = callback.data.split("_", 3)
    if len(parts) != 4:
        return

    _, exam_id, year, semester = parts
    user_data = await state.get_data()
    department_id = user_data.get("department_id")

    await callback.message.edit_text(f"Starting {year} {semester.title()} exam...")

    res = await api_client.post(
        path="/api/sessions/start",
        telegram_id=callback.from_user.id,
        payload={
            "mode": "exam",
            "department_id": department_id,
            "past_exam_id": exam_id,
        },
        response_model=SessionStartResponse,
    )

    if not res:
        await callback.message.answer(
            "Failed to start exam session. Please try again later.",
            reply_markup=main_menu_keyboard(),
        )
        return

    # Handle active session conflict (409)
    if isinstance(res, dict) and res.get("detail", {}).get("error", {}).get("code") == "active_session_exists":
        session_id = res["detail"]["error"]["session_id"]
        await callback.message.answer("You have an active session. Resuming...")
    else:
        # Successful new session
        session_id = res.session_id

    await state.update_data(session_id=session_id, mode="exam")
    await state.set_state(ExamSession.active)
    await send_question(callback.message, state, session_id, callback.from_user.id)


@router.callback_query(F.data.startswith("ans_"), ExamSession.waiting_for_answer)
async def process_answer_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Processes user's answer to a question, validates qtoken, and displays feedback.
    """
    if not callback.message or not callback.from_user:
        await callback.answer("Error processing your answer.")
        return

    await callback.answer()  # Remove loading spinner instantly

    # Parse callback data: "ans_{choice}_{qtoken}"
    parts = callback.data.split("_", 2)
    if len(parts) != 3:
        await callback.message.answer(
            "Invalid answer format. Please try again.", reply_markup=main_menu_keyboard()
        )
        await state.clear()
        return

    _, choice, qtoken = parts
    user_data = await state.get_data()
    session_id = user_data.get("session_id")
    question_id = user_data.get("question_id") # Get from state
    is_practice = user_data.get("is_practice", False)
    stored_qtoken = user_data.get("qtoken")

    if not session_id or not question_id or stored_qtoken != qtoken:
        await callback.message.answer(
            "Session error or invalid question token. Please start a new session.",
            reply_markup=main_menu_keyboard(),
        )
        await state.clear()
        return

    answer_data = await api_client.post(
        path=f"/api/sessions/{session_id}/answer",
        telegram_id=callback.from_user.id,
        payload={"question_id": question_id, "answer": choice, "qtoken": qtoken},
        response_model=AnswerResponse,
    )


    if not answer_data:
        await callback.message.answer(
            "Failed to submit answer. Please try again.",
            reply_markup=main_menu_keyboard(),
        )
        return

    # Get the stored options list to display which one was selected
    question_options = user_data.get("question_options", [])
    choice_index = ord(choice) - 65  # 'A' -> 0, 'B' -> 1, etc.
    selected_text = question_options[choice_index] if choice_index < len(question_options) else choice

    divider = "━" * 30

    if is_practice:
        if answer_data.is_correct:
            result_line = f"✅  <b>Correct!</b>"
            selected_line = f"You chose <b>{choice})</b>  {selected_text}"
            result_block = f"{result_line}\n{selected_line}"
        else:
            correct_letter = answer_data.correct_choice or "?"
            # Find correct option text
            correct_index = ord(correct_letter) - 65 if len(correct_letter) == 1 else -1
            correct_text = question_options[correct_index] if 0 <= correct_index < len(question_options) else correct_letter
            result_line = f"❌  <b>Incorrect</b>"
            selected_line = f"You chose <b>{choice})</b>  <s>{selected_text}</s>"
            correct_line = f"Correct answer: <b>{correct_letter})</b>  {correct_text}"
            result_block = f"{result_line}\n{selected_line}\n{correct_line}"

        if answer_data.explanation:
            explanation_block = f"\n{divider}\n💡  <b>Explanation</b>\n{answer_data.explanation}"
        else:
            explanation_block = ""
    else:
        result_block = f"📌  Answer <b>{choice}</b> submitted."
        explanation_block = ""

    # Reconstruct the full message to keep question context visible
    original_text = callback.message.text or ""
    updated_text = (
        f"{original_text}\n\n"
        f"{divider}\n"
        f"{result_block}"
        f"{explanation_block}"
    )

    await callback.message.edit_text(
        updated_text,
        reply_markup=session_action_keyboard(
            session_id=session_id,
            has_next_question=user_data.get("has_next", False),
            is_practice_mode=is_practice,
            qtoken=qtoken if is_practice else None,
        ),
        parse_mode="HTML",
    )
    await state.set_state(ExamSession.active)


@router.callback_query(F.data.startswith("next_"), ExamSession.active)
async def next_question_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Handles request for the next question in a session.
    """
    if not callback.message or not callback.from_user:
        await callback.answer("Error processing request.")
        return

    await callback.answer()

    # Parse callback data: "next_{session_id}"
    parts = callback.data.split("_", 1)
    if len(parts) != 2:
        return
    session_id = parts[1]
    user_data = await state.get_data()
    current_session_id = user_data.get("session_id")

    if not current_session_id or current_session_id != session_id:
        await callback.message.answer(
            "Session error. Please start a new session.",
            reply_markup=main_menu_keyboard(),
        )
        await state.clear()
        return

    # Call backend to advance to next question
    next_question_status = await api_client.post(
        path=f"/api/sessions/{session_id}/next",
        telegram_id=callback.from_user.id,
        payload={},
    )

    if not next_question_status:
        await callback.message.answer(
            "Failed to get next question. Please try again.",
            reply_markup=main_menu_keyboard(),
        )
        return

    await send_question(callback.message, state, session_id, callback.from_user.id)


@router.callback_query(F.data.startswith("end_"), ExamSession.active)
async def end_session_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Handles ending a session and displaying the final score.
    """
    if not callback.message or not callback.from_user:
        await callback.answer("Error processing request.")
        return

    await callback.answer()

    # Parse callback data: "end_{session_id}"
    parts = callback.data.split("_", 1)
    if len(parts) != 2:
        return
    session_id = parts[1]
    user_data = await state.get_data()
    current_session_id = user_data.get("session_id")

    if not current_session_id or current_session_id != session_id:
        await callback.message.answer(
            "Session error. Please start a new session.",
            reply_markup=main_menu_keyboard(),
        )
        await state.clear()
        return

    # Submit session to backend for final scoring
    submit_data = await api_client.post(
        path=f"/api/sessions/{session_id}/submit",
        telegram_id=callback.from_user.id,
        payload={},
        response_model=SessionSubmitResponse,
    )

    if not submit_data:
        await callback.message.answer(
            "Failed to finalize session. Please try again.",
            reply_markup=main_menu_keyboard(),
        )
        return

    # Check if we got an error dictionary (e.g. 409 Conflict) or a proper model instance
    if isinstance(submit_data, dict):
        # If it's a conflict detail
        if "error" in submit_data or "detail" in submit_data:
            detail = submit_data.get("detail", submit_data.get("error", {}))
            msg = detail.get("message") if isinstance(detail, dict) else str(detail)
            if "already_submitted" in str(detail):
                await callback.answer("Your results have already been saved.", show_alert=True)
                await callback.message.delete()
                await state.clear()
                return
            
            await callback.message.answer(f"Error finalizing session: {msg}")
            return
        
        # Fallback for raw dict access if validation was skipped
        score = submit_data.get("score", 0)
        total = submit_data.get("total_questions", 0)
        pct = submit_data.get("score_percent", 0.0)
        msg_text = submit_data.get("message", "Keep learning!")
    else:
        # Proper model instance access
        score = submit_data.score
        total = submit_data.total_questions
        pct = submit_data.score_percent
        msg_text = submit_data.message

    if pct >= 80:
        grade_emoji = "🏆"
        grade_label = "Excellent!"
    elif pct >= 60:
        grade_emoji = "👍"
        grade_label = "Good job!"
    elif pct >= 40:
        grade_emoji = "📖"
        grade_label = "Keep studying!"
    else:
        grade_emoji = "💪"
        grade_label = "Don't give up!"

    divider = "━" * 30
    result_message = (
        f"🎓  <b>Session Complete!</b>\n"
        f"{divider}\n\n"
        f"{grade_emoji}  <b>{grade_label}</b>\n\n"
        f"📊  Score:  <b>{score} / {total}</b>\n"
        f"📈  Percentage:  <b>{pct:.1f}%</b>\n\n"
        f"{divider}\n"
        f"<i>{submit_data.message}</i>"
    )

    await callback.message.edit_text(
        result_message,
        parse_mode="HTML",
    )
    # Send a new message to show the main menu reply keyboard
    await callback.message.answer(
        "Use the menu below to start another session:",
        reply_markup=main_menu_keyboard(),
    )
    await state.clear()
