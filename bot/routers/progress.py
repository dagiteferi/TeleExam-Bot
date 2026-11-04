import re
from typing import Optional
from datetime import date, datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from pydantic import BaseModel

from bot.keyboards.inline import pro_plan_keyboard
from bot.keyboards.reply import MAIN_MENU_TEXTS, main_menu_keyboard
from bot.routers.ai_tutor import ExplanationResponse
from bot.routers.sessions import send_question
from bot.utils.watermark import embed_watermark
from bot.states.session_states import ExamSession, ResultsHistory
from bot.services.api_client import api_client
from bot.utils.text import MAX_MESSAGE_LENGTH, answer_long, esc

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
    attempted: int = 0
    error_rate_percent: float = 0.0


class TopExamScore(BaseModel):
    title: str
    top_score_percent: float
    total_questions: int


class ActiveSessionInfo(BaseModel):
    mode: str
    title: str
    current_question_index: int
    total_questions: int
    answered_count: int = 0


class RecentSession(BaseModel):
    mode: str
    title: str
    score_percent: float
    question_count: int
    answered_count: int = 0
    submitted_at: datetime


class ProgressResponse(BaseModel):
    department_name: Optional[str] = None
    total_exams_taken: int
    total_practice_sessions: int
    overall_accuracy_percent: float
    total_questions_answered: int
    total_correct: int
    total_wrong: int
    course_breakdown: list[CourseProgress]
    weak_topics: list[WeakTopic]
    recent_exam_scores: list[float]
    top_exam_scores: list[TopExamScore] = []
    active_session_info: Optional[ActiveSessionInfo] = None
    recent_sessions: list[RecentSession] = []
    has_pro: bool = False
    mistakes_to_review: int = 0


class MistakesSummary(BaseModel):
    has_pro: bool
    count: int
    trial_tries_left: Optional[int] = None  # free trial only
    trial_ai_left: Optional[int] = None


class SessionStartResponse(BaseModel):
    session_id: str


class MistakeItem(BaseModel):
    question_id: str
    prompt: str
    your_answer: str
    course_name: Optional[str] = None
    answered_at: datetime


class MistakeCourseCount(BaseModel):
    course_name: str
    count: int


class MistakeListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    has_next: bool
    by_course: list[MistakeCourseCount] = []
    items: list[MistakeItem] = []
    is_trial: bool = False
    locked_count: int = 0
    trial_tries_left: Optional[int] = None
    trial_ai_left: Optional[int] = None


class HistoryItem(BaseModel):
    session_id: str
    mode: str
    title: str
    score_percent: float
    correct_count: int
    wrong_count: int
    question_count: int
    duration_seconds: int = 0
    submitted_at: datetime


class HistoryResponse(BaseModel):
    department_name: Optional[str] = None
    mode: str
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    page: int
    page_size: int
    total: int
    has_next: bool
    items: list[HistoryItem]
    is_trial: bool = False  # free preview: newest few results only
    locked_count: int = 0


# Students are in Ethiopia (UTC+3, no daylight saving); show their local time.
LOCAL_TZ = timezone(timedelta(hours=3))
HISTORY_PAGE_SIZE = 10
REVIEW_MISTAKES_LIMIT = 20  # must match the backend's limit per review session
HISTORY_MODES = {"all": "All", "exam": "📝 Exams", "practice": "🎯 Practice"}
# Quick day filters. A custom range is encoded as "YYYYMMDD-YYYYMMDD".
RANGE_PRESETS = {
    "today": "Today",
    "7d": "Last 7 days",
    "month": "This month",
    "30d": "Last 30 days",
    "all": "All time",
}
_CUSTOM_RANGE_RE = re.compile(r"(\d{8})-(\d{8})")
# Accepts DD/MM/YYYY (also with - or .) and YYYY-MM-DD
_TYPED_DATE_RE = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})|(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})")


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
        return "(Improving)"
    elif diff < -3:
        return "(Declining)"
    else:
        return "(Steady)"


def _format_progress(data: ProgressResponse) -> str:
    divider = "━" * 30

    lines = ["<b>📊 Your Progress Dashboard</b>"]
    if data.department_name:
        lines.append(f"📚 Department: <b>{esc(data.department_name.title())}</b>")
    lines.append(divider)

    # In-Progress / Stopped Session Status
    if data.active_session_info:
        info = data.active_session_info
        mode_label = "📝 Exam Mode" if info.mode == "exam" else "🎯 Practice Mode"
        lines += [
            "⏸ <b>Current / Paused Session</b>",
            f"Mode: <b>{mode_label}</b>",
            f"Content: <b>{esc(info.title)}</b>",
            f"Stopped at: <b>Question {info.current_question_index} of {info.total_questions}</b>",
            divider,
        ]

    # Overall header
    lines += [
        "<b>Overall Statistics</b>",
        f"Exams taken:        <b>{data.total_exams_taken}</b>",
        f"Practice sessions:  <b>{data.total_practice_sessions}</b>",
        f"Correct answers:    <b>{data.total_correct}</b>",
        f"Incorrect answers:  <b>{data.total_wrong}</b>",
        "",
        "<b>Overall Accuracy</b>",
        f"    {_accuracy_bar(data.overall_accuracy_percent)}",
    ]

    # Top Exam Results
    if data.top_exam_scores:
        lines += ["", divider, "🏆 <b>Top Exam Results</b>"]
        for top in data.top_exam_scores:
            lines.append(f"• <b>{esc(top.title)}</b> — <b>{top.top_score_percent:.1f}%</b> ({top.total_questions} Qs)")

    # Score trend
    if data.recent_exam_scores:
        trend = _trend_arrow(data.recent_exam_scores)
        recent_str = " → ".join(f"{s:.0f}%" for s in data.recent_exam_scores)
        lines += [
            "",
            divider,
            f"<b>Recent Exam Scores</b> {trend}",
            f"    {recent_str}",
        ]

    # Per-course breakdown
    if data.course_breakdown:
        lines += ["", divider, "<b>Per-Course Accuracy</b>"]
        for c in data.course_breakdown:
            lines.append(f"• <b>{esc(c.course_name)}</b>")
            lines.append(f"    {_accuracy_bar(c.accuracy_percent, 8)}  ({c.correct}/{c.total_answered} correct)")

    # Weak topics
    if data.weak_topics:
        lines += ["", divider, "⚠️ <b>Topics Requiring Attention</b>"]
        for t in data.weak_topics:
            if t.attempted:
                lines.append(
                    f"• {esc(t.topic_name)} — <b>{t.error_count} of {t.attempted}</b> wrong "
                    f"({t.error_rate_percent:.0f}%)"
                )
            else:  # older backend without the rate fields
                lines.append(f"• {esc(t.topic_name)} — <b>{t.error_count}</b> mistakes")
        lines.append("<i>Based on your last answers in each topic — it updates as you improve.</i>")

    # Recent History
    if data.recent_sessions:
        lines += ["", divider, "🗓 <b>Recent History</b>"]
        for sess in data.recent_sessions:
            date_str = sess.submitted_at.strftime("%b %d, %Y")
            mode_icon = "📝" if sess.mode == "exam" else "🎯"
            # e.g. "Sep 17, 2026 - 📝 Midterm Exam"
            lines.append(f"• {mode_icon} <b>{esc(sess.title)}</b> ({date_str})")
            lines.append(f"    Score: <b>{sess.score_percent:.1f}%</b>")

    lines += ["", divider, "<i>Consistent practice leads to consistent improvement.</i>"]
    return "\n".join(lines)


def _format_duration(seconds: int) -> str:
    if seconds <= 0:
        return ""
    minutes = seconds // 60
    if minutes < 1:
        return f"{seconds}s"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60}h {minutes % 60:02d}m"


def _local_today() -> date:
    return datetime.now(LOCAL_TZ).date()


def _resolve_range(token: str) -> tuple[Optional[date], Optional[date]]:
    """Turns a range token (preset or custom) into (first day, last day); (None, None) = all time."""
    today = _local_today()
    if token == "today":
        return today, today
    if token == "7d":
        return today - timedelta(days=6), today
    if token == "30d":
        return today - timedelta(days=29), today
    if token == "month":
        return today.replace(day=1), today
    match = _CUSTOM_RANGE_RE.fullmatch(token)
    if match:
        try:
            return (
                datetime.strptime(match.group(1), "%Y%m%d").date(),
                datetime.strptime(match.group(2), "%Y%m%d").date(),
            )
        except ValueError:
            pass
    return None, None


def _custom_token(first: date, last: date) -> str:
    return f"{first:%Y%m%d}-{last:%Y%m%d}"


def _format_period(first: Optional[date], last: Optional[date]) -> str:
    if not first or not last:
        return ""
    if first == last:
        return first.strftime("%b %d, %Y")
    if first.year == last.year:
        return f"{first:%b %d} – {last:%b %d, %Y}"
    return f"{first:%b %d, %Y} – {last:%b %d, %Y}"


def _parse_typed_range(text: str) -> tuple[date, date]:
    """
    Reads one or two dates typed by the user, e.g. "01/10/2026 - 04/11/2026" or "04/11/2026".
    Raises ValueError with a user-friendly message when the input is not usable.
    """
    days = []
    for m in _TYPED_DATE_RE.finditer(text):
        if m.group(1):
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            day, month, year = int(m.group(4)), int(m.group(5)), int(m.group(6))
        try:
            days.append(date(year, month, day))
        except ValueError:
            raise ValueError(f"{m.group(0)} is not a real date.")

    if not days or len(days) > 2:
        raise ValueError("Please send one date, or two dates for a range.")
    first, last = min(days), max(days)
    today = _local_today()
    if first > today:
        raise ValueError("That date is in the future.")
    return first, min(last, today)


def _format_history(data: HistoryResponse, range_token: str = "all") -> str:
    """Results history grouped by month, newest first."""
    divider = "━" * 30
    lines = [f"<b>📜 Results History — {HISTORY_MODES.get(data.mode, 'All')}</b>"]
    if data.department_name:
        lines.append(f"📚 Department: <b>{esc(data.department_name.title())}</b>")
    period = _format_period(data.date_from, data.date_to)
    preset = RANGE_PRESETS.get(range_token)
    if period:
        label = f"{preset} ({period})" if preset else period
        lines.append(f"📅 Period: <b>{label}</b>")
    else:
        lines.append("📅 Period: <b>All time</b>")
    lines.append(divider)

    if not data.items:
        lines.append(
            "No results in this period. Try a wider range."
            if period else "No finished sessions here yet."
        )
        return "\n".join(lines)

    current_month = None
    for item in data.items:
        local = item.submitted_at.astimezone(LOCAL_TZ)
        month = local.strftime("%B %Y")
        if month != current_month:
            current_month = month
            lines += ["", f"🗓 <b>{month}</b>"]

        icon = "📝" if item.mode == "exam" else "🎯"
        details = [local.strftime("%b %d, %H:%M")]
        duration = _format_duration(item.duration_seconds)
        if duration:
            details.append(f"⏱ {duration}")
        skipped = item.question_count - item.correct_count - item.wrong_count
        if item.mode != "practice" and skipped > 0:
            details.append(f"{skipped} skipped")

        lines.append(f"{icon} <b>{esc(item.title)}</b>")
        lines.append(
            f"    Score: <b>{item.score_percent:.1f}%</b> "
            f"({item.correct_count}/{item.question_count})"
        )
        lines.append(f"    <i>{' · '.join(details)}</i>")

    if data.is_trial:
        lines += ["", divider, f"🎁 <i>Free preview: your {len(data.items)} newest result"
                               f"{'s' if len(data.items) != 1 else ''} here.</i>"]
        if data.locked_count:
            lines.append(
                f"🔒 <b>{data.locked_count} more result{'s' if data.locked_count != 1 else ''}</b> "
                "in this view — upgrade to 💎 PRO to see your full history."
            )
        return "\n".join(lines)

    pages = max(1, -(-data.total // data.page_size))
    lines += ["", divider, f"Page <b>{data.page + 1}</b> of <b>{pages}</b> · {data.total} results in total"]
    return "\n".join(lines)


def _history_keyboard(data: HistoryResponse, range_token: str) -> InlineKeyboardMarkup:
    """
    Buttons: type filter, day filter, custom dates and paging.
    Callback format: hist:<mode>:<page>:<range>, where range is a preset or YYYYMMDD-YYYYMMDD.
    """
    def mark(selected: bool, text: str) -> str:
        return f"✅ {text}" if selected else text

    def range_btn(token: str, text: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=mark(token == range_token, text),
            callback_data=f"hist:{data.mode}:0:{token}",
        )

    is_custom = range_token not in RANGE_PRESETS
    rows = [
        [
            InlineKeyboardButton(text=mark(mode == data.mode, label), callback_data=f"hist:{mode}:0:{range_token}")
            for mode, label in HISTORY_MODES.items()
        ],
        [range_btn("today", "Today"), range_btn("7d", "7 days"), range_btn("month", "This month")],
        [
            range_btn("30d", "30 days"),
            range_btn("all", "All time"),
            InlineKeyboardButton(text=mark(is_custom, "📆 Custom"), callback_data=f"histc:{data.mode}"),
        ],
    ]

    nav_row = []
    if data.page > 0:
        nav_row.append(InlineKeyboardButton(
            text="⬅️ Newer", callback_data=f"hist:{data.mode}:{data.page - 1}:{range_token}"))
    if data.has_next:
        nav_row.append(InlineKeyboardButton(
            text="Older ➡️", callback_data=f"hist:{data.mode}:{data.page + 1}:{range_token}"))
    if nav_row:
        rows.append(nav_row)
    if data.is_trial and data.locked_count:
        rows += pro_plan_keyboard().inline_keyboard  # free preview: upgrade instead of more pages
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _progress_links(data: ProgressResponse) -> tuple[str, InlineKeyboardMarkup]:
    """The PRO links shown under the dashboard: Review My Mistakes and Full Results History."""
    n = data.mistakes_to_review
    mistakes_line = (
        f"🔁 <b>Review My Mistakes</b> — practise the <b>{n}</b> question{'s' if n != 1 else ''} you got wrong"
        if n else "🔁 <b>Review My Mistakes</b> — practise the questions you got wrong"
    )
    lines = [
        "<b>📌 Go further</b>",
        mistakes_line,
        "📜 <b>Full Results History</b> — every result, filter by day or date range",
    ]
    if data.has_pro:
        mistakes_text = f"🔁 Review My Mistakes ({n})" if n else "🔁 Review My Mistakes"
        history_text = "📜 Full Results History"
    else:
        lines.append(
            "\n🎁 <b>Free trial</b>\n"
            "<i>• Review My Mistakes: see 3 mistakes, retry 3 questions, 1 AI explanation\n"
            "• Results History: your 3 newest results in every view and day filter\n"
            "💎 PRO unlocks everything.</i>"
        )
        mistakes_text = "🎁 Review My Mistakes · Free trial"
        history_text = "🎁 Results History · Free preview"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=mistakes_text, callback_data="mistakes:open")],
        [InlineKeyboardButton(text=history_text, callback_data="hist:all:0:all")],
    ])
    return "\n".join(lines), keyboard


async def _send_pro_upsell(message: Message, feature: str, headline: Optional[str] = None) -> None:
    await message.answer(
        f"🔒 <b>{esc(headline or f'{feature} is a PRO feature.')}</b>\n\n"
        "Upgrade to PRO to unlock:\n"
        "• 🔁 Review My Mistakes — practise only the questions you got wrong\n"
        "• 📜 Full Results History — with day and date-range filters\n"
        "• 🤖 Unlimited AI Tutor and personalized study plans",
        parse_mode="HTML",
        reply_markup=pro_plan_keyboard(),
    )


async def _get_mistakes_summary(telegram_id: int) -> Optional[MistakesSummary]:
    return await api_client.get(
        path="/api/progress/mistakes", telegram_id=telegram_id, response_model=MistakesSummary
    )


async def _load_history(
    telegram_id: int, mode: str, page: int, range_token: str
) -> tuple[Optional[HistoryResponse], str]:
    """Fetches one history page; returns (response, range token actually used)."""
    first, last = _resolve_range(range_token)
    if not first:
        range_token = "all"
    path = f"/api/progress/history?mode={mode}&page={page}&page_size={HISTORY_PAGE_SIZE}"
    if first and last:
        path += f"&date_from={first.isoformat()}&date_to={last.isoformat()}"
    history = await api_client.get(path=path, telegram_id=telegram_id, response_model=HistoryResponse)
    return history, range_token



# ─── Handler ─────────────────────────────────────────────────────────────────

@router.message(F.text == "📊 My Progress")
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
            "<b>No activity recorded yet.</b>\n\n"
            "Complete a session in Practice Mode or Exam Mode to view your statistics here.",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        return

    await answer_long(
        message,
        _format_progress(progress_data),
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
    # Clear links to the PRO features: Review My Mistakes and Full Results History
    links_text, links_keyboard = _progress_links(progress_data)
    await message.answer(links_text, parse_mode="HTML", reply_markup=links_keyboard)


NO_MISTAKES_TEXT = (
    "🎉 <b>No mistakes to review!</b>\n\n"
    "Every question you got wrong has since been answered correctly. "
    "Keep practising — new mistakes will show up here."
)
MISTAKES_PAGE_SIZE = 5
# Deep-link payloads used by the links inside the mistakes list (/start <payload>)
TRY_AGAIN_PREFIX = "mt_"   # mt_<question_id>
EXPLAIN_PREFIX = "me_"     # me_<question_id>_<your answer letter>


async def _check_mistakes_access(message: Message, telegram_id: int, action: str) -> Optional[MistakesSummary]:
    """
    action: "try" (retry one question), "ai" (AI explanation) or "all" (practice all mistakes).
    PRO can do everything; free users get a small trial for "try" and "ai".
    Tells the user why when not allowed (PRO message) and returns None.
    """
    summary = await _get_mistakes_summary(telegram_id)
    if not summary:
        await message.answer("⏳ Could not load your mistakes right now. Please try again later.")
        return None
    if summary.count == 0:
        await message.answer(NO_MISTAKES_TEXT, parse_mode="HTML")
        return None
    if summary.has_pro:
        return summary

    if action == "all":
        await _send_pro_upsell(message, "Practice all mistakes")
        return None
    if action == "try" and not summary.trial_tries_left:
        await _send_pro_upsell(
            message, "Review My Mistakes",
            headline="You've used your 3 free tries. Upgrade to PRO to retry all your mistakes.",
        )
        return None
    if action == "ai" and not summary.trial_ai_left:
        await _send_pro_upsell(
            message, "Review My Mistakes",
            headline="You've used your free AI explanation. Upgrade to PRO for unlimited AI explanations.",
        )
        return None
    return summary


async def _start_review(
    message: Message, state: FSMContext, telegram_id: int, intro: str,
    review_question_id: Optional[str] = None, is_trial: bool = False,
) -> None:
    """Starts a Review My Mistakes practice session (all mistakes, or one question) and sends question 1."""
    payload = {"mode": "practice", "review_mistakes": True}
    if review_question_id:
        payload["review_question_id"] = review_question_id
    res = await api_client.post(
        path="/api/sessions/start",
        telegram_id=telegram_id,
        payload=payload,
        response_model=SessionStartResponse,
    )
    if not res:
        if is_trial:
            # Free trial only covers the newest few mistakes (or the tries ran out meanwhile)
            await _send_pro_upsell(
                message, "Review My Mistakes",
                headline="The free trial covers your 3 newest mistakes. Upgrade to PRO to practise all of them.",
            )
            return
        await message.answer(
            "Couldn't start the review. If you already answered this question correctly, "
            "it has left your mistakes list — tap 🔁 Review My Mistakes in 📊 My Progress to see the rest.",
            reply_markup=main_menu_keyboard(),
        )
        return

    if isinstance(res, dict) and res.get("detail", {}).get("error", {}).get("code") == "active_session_exists":
        session_id = res["detail"]["error"]["session_id"]
        await message.answer("You have an unfinished review. Resuming...")
    else:
        session_id = res.session_id
        await message.answer(intro, parse_mode="HTML")

    await state.update_data(session_id=session_id, mode="practice")
    await state.set_state(ExamSession.active)
    await send_question(message, state, session_id, telegram_id)


async def try_mistake_again(message: Message, state: FSMContext, telegram_id: int, question_id: str) -> None:
    """Retries one wrong question as a one-question practice; a correct answer removes it from the list."""
    summary = await _check_mistakes_access(message, telegram_id, "try")
    if not summary:
        return
    intro = "🔁 <b>Try again</b>\n\nAnswer correctly and this question leaves your mistakes list."
    if not summary.has_pro:
        left = summary.trial_tries_left - 1  # this try uses one
        intro += f"\n\n🎁 <i>Free trial: {left} tr{'ies' if left != 1 else 'y'} left after this one.</i>"
    await _start_review(
        message, state, telegram_id, intro=intro, review_question_id=question_id, is_trial=not summary.has_pro,
    )


async def explain_mistake(message: Message, telegram_id: int, question_id: str, your_answer: str) -> None:
    """AI explanation of a wrong question, including why the student's answer was wrong."""
    summary = await _check_mistakes_access(message, telegram_id, "ai")
    if not summary:
        return

    thinking = await message.answer("<i>AI Tutor is analyzing your answer...</i>", parse_mode="HTML")
    explanation = await api_client.post(
        path="/api/ai/explain",
        telegram_id=telegram_id,
        # "mistakes": free users use their Review My Mistakes trial explanation
        payload={"question_id": question_id, "user_answer": your_answer, "source": "mistakes"},
        response_model=ExplanationResponse,
        timeout=60,
    )
    try:
        await thinking.delete()
    except Exception:
        pass

    if not explanation or not explanation.success:
        msg = explanation.explanation if explanation and explanation.explanation else \
            "⏳ The AI tutor is currently busy. Please try again in a moment."
        # The backend's "free explanation used" message comes with the upgrade button
        await message.answer(esc(msg), reply_markup=pro_plan_keyboard() if "PRO" in msg else None)
        return

    divider = "━" * 30
    trial_note = ""
    if not summary.has_pro:
        trial_note = (
            f"\n\n{divider}\n🎁 <i>That was your free AI explanation. "
            "Upgrade to 💎 PRO for unlimited AI explanations on every mistake.</i>"
        )
    await answer_long(
        message,
        f"🧠 <b>AI Explanation</b>\n{divider}\n\n{esc(explanation.explanation)}{trial_note}",
        parse_mode="HTML",
        protect_content=True,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔁 Try this question again", callback_data=f"mtry:{question_id}"),
        ]]),
    )


def _format_mistakes_list(data: MistakeListResponse, bot_username: str) -> str:
    """Summary + numbered wrong questions, each with Try again / Ask AI links."""
    divider = "━" * 30
    lines = ["🔁 <b>Review My Mistakes</b>", divider, "📊 <b>Summary</b>"]
    lines.append(f"You have <b>{data.total}</b> question{'s' if data.total != 1 else ''} to fix.")
    if data.by_course:
        shown = data.by_course[:5]
        for c in shown:
            lines.append(f"• {esc(c.course_name)} — <b>{c.count}</b>")
        hidden = len(data.by_course) - len(shown)
        if hidden > 0:
            lines.append(f"• <i>+{hidden} more course{'s' if hidden != 1 else ''}</i>")
    lines.append("<i>Answer a question correctly and it leaves this list.</i>")
    if data.is_trial:
        tries, ai = data.trial_tries_left or 0, data.trial_ai_left or 0
        lines.append(
            f"\n🎁 <b>Free trial:</b> {tries} tr{'ies' if tries != 1 else 'y'} · "
            f"{ai} AI explanation{'s' if ai != 1 else ''} left"
        )
    lines.append(divider)

    base = f"https://t.me/{bot_username}?start="
    start_no = data.page * data.page_size
    for i, item in enumerate(data.items, start=start_no + 1):
        when = item.answered_at.astimezone(LOCAL_TZ).strftime("%b %d")
        course = f"{esc(item.course_name)} · " if item.course_name else ""
        try_link = f'{base}{TRY_AGAIN_PREFIX}{item.question_id}'
        ai_link = f'{base}{EXPLAIN_PREFIX}{item.question_id}_{item.your_answer}'
        lines += [
            "",
            f"<b>{i}.</b> {esc(item.prompt)}",
            f"    <i>{course}{when}</i>",
            f'    <a href="{try_link}">🔁 Try again</a>   ·   <a href="{ai_link}">🧠 Ask AI</a>',
        ]

    if data.is_trial:
        lines += ["", divider]
        if data.locked_count:
            lines.append(
                f"🔒 <b>{data.locked_count} more mistake{'s' if data.locked_count != 1 else ''}</b> "
                "— upgrade to 💎 PRO to see and practise all of them."
            )
        else:
            lines.append("💎 <i>PRO: unlimited tries and AI explanations on every mistake.</i>")
        return "\n".join(lines)

    pages = max(1, -(-data.total // data.page_size))
    lines += ["", divider, f"Page <b>{data.page + 1}</b> of <b>{pages}</b>"]
    return "\n".join(lines)


def _mistakes_list_keyboard(data: MistakeListResponse) -> InlineKeyboardMarkup:
    if data.is_trial:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔒 Practice all mistakes · PRO", callback_data="mistakes:start")],
            *pro_plan_keyboard().inline_keyboard,
        ])
    rows = []
    nav = []
    if data.page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Newer", callback_data=f"mistakes:page:{data.page - 1}"))
    if data.has_next:
        nav.append(InlineKeyboardButton(text="Older ➡️", callback_data=f"mistakes:page:{data.page + 1}"))
    if nav:
        rows.append(nav)
    practice_n = min(data.total, REVIEW_MISTAKES_LIMIT)
    rows.append([InlineKeyboardButton(
        text=f"▶️ Practice all mistakes ({practice_n})", callback_data="mistakes:start")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "mistakes:open")
@router.callback_query(F.data.startswith("mistakes:page:"))
async def mistakes_list_callback(callback: CallbackQuery) -> None:
    """The list of wrong questions with a summary; Newer/Older edit the same message."""
    if not callback.from_user or not callback.message:
        return
    is_open = callback.data == "mistakes:open"
    try:
        page = 0 if is_open else max(0, int(callback.data.rsplit(":", 1)[1]))
    except ValueError:
        await callback.answer()
        return

    data = await api_client.get(
        path=f"/api/progress/mistakes/list?page={page}&page_size={MISTAKES_PAGE_SIZE}",
        telegram_id=callback.from_user.id,
        response_model=MistakeListResponse,
    )
    await callback.answer()
    if not data:
        await callback.message.answer("⏳ Could not load your mistakes right now. Please try again later.")
        return
    if data.total == 0:
        await callback.message.answer(NO_MISTAKES_TEXT, parse_mode="HTML")
        return

    bot_username = (await callback.bot.me()).username
    text = embed_watermark(_format_mistakes_list(data, bot_username), callback.from_user.id)
    keyboard = _mistakes_list_keyboard(data)
    if not is_open and len(text) <= MAX_MESSAGE_LENGTH:
        try:
            await callback.message.edit_text(
                text, parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True)
            return
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                return
    await answer_long(
        callback.message, text, parse_mode="HTML", reply_markup=keyboard,
        protect_content=True, disable_web_page_preview=True,
    )


@router.callback_query(F.data.startswith("mtry:"))
async def mistake_try_again_callback(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    await callback.answer()
    await try_mistake_again(callback.message, state, callback.from_user.id, callback.data.split(":", 1)[1])


@router.callback_query(F.data == "mistakes:start")
async def review_mistakes_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Starts a practice session made of the student's open mistakes (PRO only)."""
    if not callback.from_user or not callback.message:
        return
    await callback.answer()
    summary = await _check_mistakes_access(callback.message, callback.from_user.id, "all")
    if not summary:
        return
    to_review = min(summary.count, REVIEW_MISTAKES_LIMIT)
    await _start_review(
        callback.message, state, callback.from_user.id,
        intro=(
            f"🔁 <b>Review My Mistakes</b>\n\n"
            f"{to_review} question{'s' if to_review != 1 else ''} you got wrong before. "
            "Answer one correctly and it leaves your mistakes list."
        ),
    )


async def handle_mistake_deep_link(message: Message, state: FSMContext, payload: str) -> bool:
    """Handles the Try again / Ask AI links in the mistakes list. True if the payload was ours."""
    if payload.startswith(TRY_AGAIN_PREFIX):
        await try_mistake_again(message, state, message.from_user.id, payload[len(TRY_AGAIN_PREFIX):])
        return True
    if payload.startswith(EXPLAIN_PREFIX):
        question_id, _, your_answer = payload[len(EXPLAIN_PREFIX):].rpartition("_")
        if question_id and your_answer in ("A", "B", "C", "D"):
            await explain_mistake(message, message.from_user.id, question_id, your_answer)
            return True
    return False


@router.callback_query(F.data.startswith("hist:"))
async def results_history_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Shows one page of the results history; filter/day/page buttons edit it in place."""
    parts = callback.data.split(":")
    try:
        mode, page = parts[1], max(0, int(parts[2]))
    except (IndexError, ValueError):
        await callback.answer()
        return
    range_token = parts[3] if len(parts) > 3 else "all"  # older buttons had no range
    if mode not in HISTORY_MODES:
        mode = "all"

    # Any button press cancels a pending "type your dates" prompt
    if await state.get_state() == ResultsHistory.entering_dates.state:
        await state.clear()

    history, range_token = await _load_history(callback.from_user.id, mode, page, range_token)
    if not history:
        await callback.answer()
        await callback.message.answer("⏳ Could not load your history right now. Please try again.")
        return

    text = _format_history(history, range_token)
    keyboard = _history_keyboard(history, range_token)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            # e.g. the old message can't be edited any more: send a fresh one
            await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("histc:"))
async def results_history_custom_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Asks the user to type the days they want to see."""
    mode = callback.data.split(":", 1)[1]
    await state.set_state(ResultsHistory.entering_dates)
    await state.update_data(history_mode=mode if mode in HISTORY_MODES else "all")
    today = _local_today()
    await callback.message.answer(
        "📆 <b>Choose your dates</b>\n\n"
        "Type a date range (day/month/year):\n"
        f"<code>01/{today:%m/%Y} - {today:%d/%m/%Y}</code>\n\n"
        "Or one date to see a single day:\n"
        f"<code>{today:%d/%m/%Y}</code>\n\n"
        "<i>Send /cancel to go back.</i>",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(ResultsHistory.entering_dates)
async def results_history_dates_entered(message: Message, state: FSMContext) -> None:
    """Reads the typed date range and shows the history for it."""
    text = (message.text or "").strip()

    # Menu buttons and commands leave date entry and go to their normal handlers
    if text in MAIN_MENU_TEXTS or (text.startswith("/") and text.lower() != "/cancel"):
        await state.clear()
        raise SkipHandler()
    if text.lower() in ("/cancel", "cancel"):
        await state.clear()
        await message.answer("Date filter cancelled.", reply_markup=main_menu_keyboard())
        return

    try:
        first, last = _parse_typed_range(text)
    except ValueError as e:
        # One retry message, then leave the state so other typing isn't treated as dates
        await state.clear()
        await message.answer(
            f"⚠️ {esc(str(e))}\n\n"
            "Example: <code>01/10/2026 - 04/11/2026</code>\n"
            "Tap <b>📆 Custom</b> again to try once more.",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        return

    mode = (await state.get_data()).get("history_mode", "all")
    await state.clear()

    history, range_token = await _load_history(message.from_user.id, mode, 0, _custom_token(first, last))
    if not history:
        await message.answer(
            "⏳ Could not load your history right now. Please try again later.",
            reply_markup=main_menu_keyboard(),
        )
        return
    await message.answer(
        _format_history(history, range_token),
        parse_mode="HTML",
        reply_markup=_history_keyboard(history, range_token),
    )
