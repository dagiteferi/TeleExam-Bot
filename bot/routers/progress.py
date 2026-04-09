from typing import Optional

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from pydantic import BaseModel

from bot.keyboards.reply import main_menu_keyboard
from bot.services.api_client import api_client

router = Router()


# ─── Pydantic models matching backend schemas ────────────────────────────────

class CourseProgress(BaseModel):
    course_name: str
    total_answered: int
    correct: int
    wrong: int
    accuracy_percent: float


class WeakTopic(BaseModel):
    topic_name: str
    error_count: int


class ProgressResponse(BaseModel):
    total_exams_taken: int
    total_practice_sessions: int
    overall_accuracy_percent: float
    total_questions_answered: int
    total_correct: int
    total_wrong: int
    course_breakdown: list[CourseProgress]
    weak_topics: list[WeakTopic]
    recent_exam_scores: list[float]


# ─── Formatting helpers ───────────────────────────────────────────────────────

def _accuracy_bar(percent: float, width: int = 10) -> str:
    """Render a simple ASCII progress bar for accuracy."""
    filled = round(percent / 100 * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {percent:.1f}%"


def _trend_arrow(scores: list[float]) -> str:
    """Show a simple trend indicator based on last 2 scores."""
    if len(scores) < 2:
        return ""
    diff = scores[-1] - scores[-2]
    if diff > 3:
        return "📈 Improving"
    elif diff < -3:
        return "📉 Declining"
    else:
        return "➡️ Steady"


def _format_progress(data: ProgressResponse) -> str:
    divider = "━" * 30

    # Overall header
    lines = [
        "📈  <b>Your Progress Dashboard</b>",
        divider,
        "",
        "🗂  <b>Overall Stats</b>",
        f"📝  Exams taken:        <b>{data.total_exams_taken}</b>",
        f"🏋️  Practice sessions:  <b>{data.total_practice_sessions}</b>",
        f"❓  Questions answered: <b>{data.total_questions_answered}</b>",
        f"✅  Correct:            <b>{data.total_correct}</b>",
        f"❌  Wrong:              <b>{data.total_wrong}</b>",
        "",
        f"🎯  <b>Overall Accuracy</b>",
        f"    {_accuracy_bar(data.overall_accuracy_percent)}",
    ]

    # Score trend
    if data.recent_exam_scores:
        trend = _trend_arrow(data.recent_exam_scores)
        recent_str = "  →  ".join(f"{s:.0f}%" for s in data.recent_exam_scores)
        lines += [
            "",
            divider,
            "📊  <b>Recent Exam Scores</b>  " + (f"({trend})" if trend else ""),
            f"    {recent_str}",
        ]

    # Per-course breakdown
    if data.course_breakdown:
        lines += ["", divider, "📚  <b>Per-Course Accuracy</b>"]
        for c in data.course_breakdown:
            icon = "🟢" if c.accuracy_percent >= 70 else "🟡" if c.accuracy_percent >= 50 else "🔴"
            lines.append(f"{icon}  <b>{c.course_name}</b>")
            lines.append(f"    {_accuracy_bar(c.accuracy_percent, 8)}  ({c.correct}/{c.total_answered} correct)")

    # Weak topics
    if data.weak_topics:
        lines += ["", divider, "⚠️  <b>Topics Needing Attention</b>"]
        for t in data.weak_topics:
            lines.append(f"🔴  {t.topic_name}  —  <b>{t.error_count}</b> mistakes")

    lines += ["", divider, "<i>💡 Keep practicing to improve your scores!</i>"]
    return "\n".join(lines)


# ─── Handler ─────────────────────────────────────────────────────────────────

@router.message(F.text == "📈 My Progress")
async def my_progress_handler(message: Message, state: FSMContext) -> None:
    """
    Displays the user's private progress dashboard.
    Each user only sees their own data — the backend enforces this
    by scoping all queries to the authenticated telegram_id.
    """
    if not message.from_user:
        return

    loading_msg = await message.answer(
        "📊 <i>Loading your progress...</i>", parse_mode="HTML"
    )

    progress_data = await api_client.get(
        path="/api/progress/me",
        telegram_id=message.from_user.id,
        response_model=ProgressResponse,
    )

    try:
        await loading_msg.delete()
    except Exception:
        pass

    if not progress_data:
        await message.answer(
            "⏳ Could not load your progress right now. Please try again later.",
            reply_markup=main_menu_keyboard(),
        )
        return

    if progress_data.total_questions_answered == 0:
        await message.answer(
            "📭  <b>No activity yet!</b>\n\n"
            "Start practicing or take an exam to see your progress here.",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        return

    await message.answer(
        _format_progress(progress_data),
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
