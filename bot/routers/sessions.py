from typing import Any, Dict, List, Literal, Optional

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from pydantic import BaseModel

from bot.keyboards.inline import question_choices_keyboard, session_action_keyboard
from bot.keyboards.reply import main_menu_keyboard
from bot.services.api_client import api_client
from bot.states.session_states import ExamSession

router = Router()


# Pydantic models for backend responses
class SessionStartResponse(BaseModel):
    session_id: str


class QuestionResponse(BaseModel):
    question_id: str
    text: str
    options: List[str]
    qtoken: str
    has_next: bool
    is_practice: bool = False


class AnswerResponse(BaseModel):
    is_correct: bool
    correct_answer: str
    explanation: Optional[str] = None


class SessionSubmitResponse(BaseModel):
    score: int
    total_questions: int
    message: str


async def _send_question(
    message: Message, state: FSMContext, session_id: str, telegram_id: int
) -> None:
    """Helper to fetch and send the next question to the user."""
    question_data = await api_client.get(
        path=f"/api/sessions/{session_id}/question",
        telegram_id=telegram_id,
        response_model=QuestionResponse,
    )

    if not question_data:
        await message.answer(
            "Failed to fetch question. Please try again later.",
            reply_markup=main_menu_keyboard(),
        )
        await state.clear()
        return

    await state.update_data(
        question_id=question_data.question_id,
        qtoken=question_data.qtoken,
        has_next=question_data.has_next,
        is_practice=question_data.is_practice,
    )
    await state.set_state(ExamSession.waiting_for_answer)

    keyboard = question_choices_keyboard(
        question_data.question_id, question_data.options, question_data.qtoken
    )
    await message.answer(question_data.text, reply_markup=keyboard)


@router.message(F.text == "📚 Take Mock Exam")
@router.message(F.text == "📝 Practice Questions")
async def start_session_handler(message: Message, state: FSMContext) -> None:
    """
    Handles starting a new exam or practice session based on user's menu choice.
    """
    if not message.from_user:
        return

    mode: Literal["exam", "practice"]
    if message.text == "📚 Take Mock Exam":
        mode = "exam"
    elif message.text == "📝 Practice Questions":
        mode = "practice"
    else:
        await message.answer("Invalid session type. Please choose from the menu.")
        return

    await message.answer(f"Starting a new {mode} session...")

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

    session_start_data = await api_client.post(
        path="/api/sessions/start",
        telegram_id=message.from_user.id,
        payload={"mode": mode, "department_id": department_id},
        response_model=SessionStartResponse,
    )

    if not session_start_data:
        await message.answer(
            "Failed to start session. Please try again later.",
            reply_markup=main_menu_keyboard(),
        )
        return

    await state.update_data(session_id=session_start_data.session_id, mode=mode)
    await state.set_state(ExamSession.active)

    await _send_question(message, state, session_start_data.session_id, message.from_user.id)


@router.callback_query(F.data.startswith("answer_"), ExamSession.waiting_for_answer)
async def process_answer_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Processes user's answer to a question, validates qtoken, and displays feedback.
    """
    if not callback.message or not callback.from_user:
        await callback.answer("Error processing your answer.")
        return

    await callback.answer()  # Remove loading spinner instantly

    # Parse callback data: "answer_{question_id}_{choice}_{qtoken}"
    parts = callback.data.split("_", 3)
    if len(parts) != 4:
        await callback.message.answer(
            "Invalid answer format. Please try again.", reply_markup=main_menu_keyboard()
        )
        await state.clear()
        return

    _, question_id, choice, qtoken = parts
    user_data = await state.get_data()
    session_id = user_data.get("session_id")
    is_practice = user_data.get("is_practice", False)
    stored_qtoken = user_data.get("qtoken")

    if not session_id or stored_qtoken != qtoken:
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

    response_text = ""
    if is_practice:
        if answer_data.is_correct:
            response_text = "✅ Correct!"
        else:
            response_text = f"❌ Incorrect. The correct answer was: {answer_data.correct_answer}"
        if answer_data.explanation:
            response_text += f"\n\nExplanation: {answer_data.explanation}"
    else:
        response_text = "Answer submitted."

    # Update the original message with the result and action buttons
    await callback.message.edit_text(
        f"{callback.message.text}\n\n{response_text}",
        reply_markup=session_action_keyboard(
            session_id=session_id,
            has_next_question=user_data.get("has_next", False),
            is_practice_mode=is_practice,
            qtoken=qtoken if is_practice else None,  # Pass qtoken for 'Explain with AI' in practice mode
        ),
    )
    await state.set_state(ExamSession.active)  # Back to active state after answer processed


@router.callback_query(F.data.startswith("next_question_"), ExamSession.active)
async def next_question_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Handles request for the next question in a session.
    """
    if not callback.message or not callback.from_user:
        await callback.answer("Error processing request.")
        return

    await callback.answer()

    # Parse callback data: "next_question_{session_id}"
    _, session_id = callback.data.split("_", 1)
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

    await _send_question(callback.message, state, session_id, callback.from_user.id)


@router.callback_query(F.data.startswith("end_session_"), ExamSession.active)
async def end_session_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Handles ending a session and displaying the final score.
    """
    if not callback.message or not callback.from_user:
        await callback.answer("Error processing request.")
        return

    await callback.answer()

    # Parse callback data: "end_session_{session_id}"
    _, session_id = callback.data.split("_", 1)
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

    await callback.message.edit_text(
        f"Session ended!\n\n"
        f"Score: {submit_data.score}/{submit_data.total_questions}\n"
        f"{submit_data.message}\n\n"
        "Returning to main menu.",
        reply_markup=main_menu_keyboard(),
    )
    await state.clear()  # Clear FSM state after session ends
