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
HISTORY_MODES = {"all": "All", "exam": "Exams", "practice": "Practice"}
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

# Colour bands used everywhere on the dashboard so a glance tells the story.
GOOD_PERCENT = 75
FAIR_PERCENT = 50
MAX_COURSES_SHOWN = 15
MIN_ANSWERS_FOR_INSIGHT = 5  # ignore courses with too few answers when picking strongest/weakest


def _rating(percent: float) -> str:
    if percent >= GOOD_PERCENT:
        return "Strong"
    if percent >= FAIR_PERCENT:
        return "Fair"
    return "Weak"


def _level_label(percent: float) -> str:
    if percent >= 85:
        return "Excellent"
    if percent >= GOOD_PERCENT:
        return "Good"
    if percent >= FAIR_PERCENT:
        return "Fair"
    return "Needs improvement"


def _bar(percent: float, width: int = 10) -> str:
    """Text progress bar, e.g. ▰▰▰▰▰▰▱▱▱▱."""
    filled = max(0, min(width, round(percent / 100 * width)))
    return "▰" * filled + "▱" * (width - filled)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _title(text: str) -> str:
    return f"<b>{text}</b>"


def _section_header(data: ProgressResponse) -> str:
    pct = data.overall_accuracy_percent
    lines = [_title("MY PROGRESS")]
    if data.department_name:
        lines.append(f"<i>{esc(data.department_name.title())}</i>")
    lines += [
        "",
        f"<b>Overall accuracy: {pct:.0f}%</b> ({_level_label(pct)})",
        _bar(pct),
        f"Correct: <b>{data.total_correct}</b>  |  Wrong: <b>{data.total_wrong}</b>  |  "
        f"Answered: <b>{data.total_questions_answered}</b>",
        f"Exams: <b>{data.total_exams_taken}</b>  |  Practice sessions: <b>{data.total_practice_sessions}</b>",
    ]
    return "\n".join(lines)


def _section_focus(data: ProgressResponse) -> Optional[str]:
    """The few things worth acting on, pulled out of the numbers below."""
    tips = []
    rated = [c for c in data.course_breakdown if c.total_answered >= MIN_ANSWERS_FOR_INSIGHT] \
        or data.course_breakdown
    if len(rated) >= 2:
        best = max(rated, key=lambda c: c.accuracy_percent)
        worst = min(rated, key=lambda c: c.accuracy_percent)
        if worst.accuracy_percent < best.accuracy_percent:
            tips.append(f"Weakest course: <b>{esc(worst.course_name)}</b> ({worst.accuracy_percent:.0f}%)")
            tips.append(f"Strongest course: <b>{esc(best.course_name)}</b> ({best.accuracy_percent:.0f}%)")
    if data.weak_topics:
        t = data.weak_topics[0]
        detail = f"{t.error_count} of {t.attempted} wrong" if t.attempted else _plural(t.error_count, "mistake")
        tips.append(f"Hardest topic: <b>{esc(t.topic_name)}</b> ({detail})")
    if data.mistakes_to_review:
        tips.append(f"Mistakes to review: <b>{data.mistakes_to_review}</b>")
    if not tips:
        return None
    return _title("KEY INSIGHTS") + "\n<blockquote>" + "\n".join(tips) + "</blockquote>"


def _section_active(data: ProgressResponse) -> Optional[str]:
    info = data.active_session_info
    if not info:
        return None
    mode = "Exam" if info.mode == "exam" else "Practice"
    lines = [
        f"{mode}: <b>{esc(info.title)}</b>",
        f"Stopped at question <b>{info.current_question_index}</b> of {info.total_questions} "
        f"({info.answered_count} answered)",
    ]
    return _title("UNFINISHED SESSION") + "\n<blockquote>" + "\n".join(lines) + "</blockquote>"


def _course_row(c: CourseProgress) -> str:
    return (
        f"<b>{esc(c.course_name)}</b>: {c.accuracy_percent:.0f}% ({_rating(c.accuracy_percent)})\n"
        f"{_bar(c.accuracy_percent)}  <i>{c.correct} of {c.total_answered} correct</i>"
    )


def _section_courses(data: ProgressResponse) -> Optional[str]:
    if not data.course_breakdown:
        return None
    # Weakest first: that is where the next study hour pays off most
    courses = sorted(data.course_breakdown, key=lambda c: (c.accuracy_percent, -c.total_answered))
    shown, hidden = courses[:MAX_COURSES_SHOWN], len(courses) - MAX_COURSES_SHOWN
    first, rest = shown[:5], shown[5:]
    lines = [_title("ACCURACY BY COURSE") + " <i>(weakest first)</i>", "\n\n".join(_course_row(c) for c in first)]
    if rest:
        more = "\n\n".join(_course_row(c) for c in rest)
        if hidden > 0:
            more += f"\n\n<i>{_plural(hidden, 'more course')} not shown</i>"
        lines.append(f"<blockquote expandable>{more}</blockquote>")
    lines.append(
        f"<i>Strong: {GOOD_PERCENT}% and above  |  Fair: {FAIR_PERCENT}–{GOOD_PERCENT - 1}%  |  "
        f"Weak: below {FAIR_PERCENT}%</i>"
    )
    return "\n".join(lines)


def _section_weak_topics(data: ProgressResponse) -> Optional[str]:
    if not data.weak_topics:
        return None
    lines = [_title("TOPICS TO WORK ON")]
    for i, t in enumerate(data.weak_topics, start=1):
        if t.attempted:
            lines.append(
                f"{i}. {esc(t.topic_name)}: <b>{t.error_count} of {t.attempted}</b> wrong "
                f"({t.error_rate_percent:.0f}%)"
            )
        else:  # older backend without the rate fields
            lines.append(f"{i}. {esc(t.topic_name)}: <b>{_plural(t.error_count, 'mistake')}</b>")
    lines.append("<i>Based on your latest answers in each topic. It updates as you improve.</i>")
    return "\n".join(lines)


def _section_exams(data: ProgressResponse) -> Optional[str]:
    parts = []
    scores = data.recent_exam_scores
    if len(scores) == 1:
        parts.append(_title("EXAM SCORES") + f"\nLatest: <b>{scores[0]:.0f}%</b>")
    elif scores:
        diff = scores[-1] - scores[-2]
        if diff > 3:
            trend = f"up {diff:.0f} points, improving"
        elif diff < -3:
            trend = f"down {-diff:.0f} points, dropping"
        else:
            trend = "steady"
        parts.append(
            _title("EXAM SCORES")
            + "\nRecent: " + " → ".join(f"{s:.0f}%" for s in scores)
            + f"\nLatest: <b>{scores[-1]:.0f}%</b> ({trend})"
        )
    if data.top_exam_scores:
        rows = [
            f"{i}. {esc(t.title)}: <b>{t.top_score_percent:.0f}%</b> <i>({t.total_questions} questions)</i>"
            for i, t in enumerate(data.top_exam_scores, start=1)
        ]
        parts.append(_title("BEST EXAM RESULTS") + "\n" + "\n".join(rows))
    return "\n\n".join(parts) or None


def _section_recent(data: ProgressResponse) -> Optional[str]:
    if not data.recent_sessions:
        return None
    rows = []
    for s in data.recent_sessions:
        mode = "Exam" if s.mode == "exam" else "Practice"
        when = s.submitted_at.astimezone(LOCAL_TZ).strftime("%b %d")
        rows.append(f"{when}  |  {mode}: {esc(s.title)}  |  <b>{s.score_percent:.0f}%</b>")
    return _title("RECENT ACTIVITY") + "\n<blockquote expandable>" + "\n".join(rows) + "</blockquote>"


def _progress_messages(data: ProgressResponse) -> list[str]:
    """
    The dashboard as message texts. Sections are packed whole into each message, so a
    long dashboard never splits inside a <blockquote> (which would break the HTML).
    """
    sections = [
        _section_header(data),
        _section_focus(data),
        _section_active(data),
        _section_courses(data),
        _section_weak_topics(data),
        _section_exams(data),
        _section_recent(data),
    ]
    messages, current = [], ""
    for section in filter(None, sections):
        candidate = f"{current}\n\n{section}" if current else section
        if current and len(candidate) > MAX_MESSAGE_LENGTH:
            messages.append(current)
            current = section
        else:
            current = candidate
    if current:
        messages.append(current)
    return messages


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
    lines = ["<b>RESULTS HISTORY</b>"]
    if data.department_name:
        lines.append(f"<i>{esc(data.department_name.title())}</i>")
    period = _format_period(data.date_from, data.date_to)
    preset = RANGE_PRESETS.get(range_token)
    if period:
        label = f"{preset} ({period})" if preset else period
    else:
        label = "All time"
    lines += [
        "",
        f"Showing: <b>{HISTORY_MODES.get(data.mode, 'All')}</b>",
        f"Period: <b>{label}</b>",
        f"Results found: <b>{data.total}</b>",
    ]

    if not data.items:
        lines += ["", "No results in this period. Try a wider date range."
                  if period else "No completed sessions yet."]
        return "\n".join(lines)

    current_month = None
    for item in data.items:
        local = item.submitted_at.astimezone(LOCAL_TZ)
        month = local.strftime("%B %Y").upper()
        if month != current_month:
            current_month = month
            lines += ["", f"<b>{month}</b>"]

        mode = "Exam" if item.mode == "exam" else "Practice"
        details = [local.strftime("%b %d, %H:%M"), mode]
        duration = _format_duration(item.duration_seconds)
        if duration:
            details.append(duration)
        skipped = item.question_count - item.correct_count - item.wrong_count
        if item.mode != "practice" and skipped > 0:
            details.append(f"{skipped} skipped")

        lines += [
            "",
            f"<b>{esc(item.title)}</b>",
            f"Score: <b>{item.score_percent:.0f}%</b> ({_rating(item.score_percent)})  |  "
            f"{item.correct_count} of {item.question_count} correct",
            f"<i>{'  |  '.join(details)}</i>",
        ]

    if data.is_trial:
        lines += ["", f"<blockquote><b>Free preview</b>\nShowing your {_plural(len(data.items), 'most recent result')}."]
        if data.locked_count:
            lines[-1] += (
                f"\n{_plural(data.locked_count, 'more result')} in this view. "
                "Upgrade to PRO to see your full history."
            )
        lines[-1] += "</blockquote>"
        return "\n".join(lines)

    pages = max(1, -(-data.total // data.page_size))
    lines += ["", f"<i>Page {data.page + 1} of {pages}</i>"]
    return "\n".join(lines)


def _history_toast(data: HistoryResponse, range_token: str) -> str:
    """Short pop-up confirming the filter just applied, e.g. 'Last 7 days, Exams: 5 results'."""
    period = RANGE_PRESETS.get(range_token) or _format_period(data.date_from, data.date_to) or "All time"
    mode = HISTORY_MODES.get(data.mode, "All")
    toast = f"{period}, {mode}: {_plural(data.total, 'result')}"
    if data.page > 0:
        toast += f" (page {data.page + 1})"
    return toast[:200]  # Telegram limit for callback answers


async def _delete_quietly(message: Message) -> None:
    """Deletes an old bot message; ignores messages Telegram no longer lets us delete (>48h)."""
    try:
        await message.delete()
    except TelegramBadRequest:
        pass


def _history_keyboard(data: HistoryResponse, range_token: str) -> InlineKeyboardMarkup:
    """
    Buttons: type filter, day filter, custom dates and paging.
    Callback format: hist:<mode>:<page>:<range>, where range is a preset or YYYYMMDD-YYYYMMDD.
    """
    def mark(selected: bool, text: str) -> str:
        return f"✓ {text}" if selected else text

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
            InlineKeyboardButton(text=mark(is_custom, "Custom dates"), callback_data=f"histc:{data.mode}"),
        ],
    ]

    nav_row = []
    if data.page > 0:
        nav_row.append(InlineKeyboardButton(
            text="‹ Newer", callback_data=f"hist:{data.mode}:{data.page - 1}:{range_token}"))
    if data.has_next:
        nav_row.append(InlineKeyboardButton(
            text="Older ›", callback_data=f"hist:{data.mode}:{data.page + 1}:{range_token}"))
    if nav_row:
        rows.append(nav_row)
    if data.is_trial and data.locked_count:
        rows += pro_plan_keyboard().inline_keyboard  # free preview: upgrade instead of more pages
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _progress_links(data: ProgressResponse) -> tuple[str, InlineKeyboardMarkup]:
    """The PRO links shown under the dashboard: Review My Mistakes and Full Results History."""
    n = data.mistakes_to_review
    lines = [
        _title("NEXT STEPS"),
        "<b>Review My Mistakes</b>: " + (f"{_plural(n, 'question')} to fix" if n else "retry the questions you got wrong"),
        "<b>Results History</b>: every result, filtered by day or date range",
    ]
    if data.has_pro:
        mistakes_text = f"Review My Mistakes ({n})" if n else "Review My Mistakes"
        history_text = "Full Results History"
    else:
        lines.append(
            "\n<blockquote><b>Free trial</b>\n"
            "Mistakes: view 3, retry 3, 1 AI explanation\n"
            "History: your 3 most recent results\n"
            "<i>Upgrade to PRO for full access.</i></blockquote>"
        )
        mistakes_text = "Review My Mistakes (Free trial)"
        history_text = "Results History (Free preview)"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=mistakes_text, callback_data="mistakes:open")],
        [InlineKeyboardButton(text=history_text, callback_data="hist:all:0:all")],
    ])
    return "\n".join(lines), keyboard


async def _send_pro_upsell(message: Message, feature: str, headline: Optional[str] = None) -> None:
    await message.answer(
        f"<b>{esc(headline or f'{feature} is a PRO feature.')}</b>\n\n"
        "PRO includes:\n"
        "<blockquote>Review My Mistakes: practise only the questions you got wrong\n"
        "Full Results History: with day and date-range filters\n"
        "Unlimited AI Tutor and personalised study plans</blockquote>",
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
        "<i>Loading your progress...</i>", parse_mode="HTML"
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
            "<b>MY PROGRESS</b>\n\n"
            "No activity yet. Your dashboard fills in after your first session.\n\n"
            "<blockquote><b>Practice Mode</b>: learn with instant feedback\n"
            "<b>Exam Mode</b>: test yourself under real exam conditions</blockquote>\n"
            "Complete one to see your accuracy, strongest and weakest courses, "
            "and the topics to focus on.",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        return

    for text in _progress_messages(progress_data):
        await answer_long(message, text, parse_mode="HTML", reply_markup=main_menu_keyboard())
    # Clear links to the PRO features: Review My Mistakes and Full Results History
    links_text, links_keyboard = _progress_links(progress_data)
    await message.answer(links_text, parse_mode="HTML", reply_markup=links_keyboard)


NO_MISTAKES_TEXT = (
    "<b>No mistakes to review.</b>\n\n"
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
    review_question_id: Optional[str] = None, is_trial: bool = False, trial_tries_left: int = 0,
) -> None:
    """
    Starts a Review My Mistakes practice session and sends the first question.
    With review_question_id it starts at that question and continues (Next) through the other mistakes.
    """
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
            "it has left your mistakes list — open My Progress and tap Review My Mistakes to see the rest.",
            reply_markup=main_menu_keyboard(),
        )
        return

    if isinstance(res, dict) and res.get("detail", {}).get("error", {}).get("code") == "active_session_exists":
        session_id = res["detail"]["error"]["session_id"]
        await message.answer("You have an unfinished review. Resuming...")
    else:
        session_id = res.session_id
        await message.answer(intro, parse_mode="HTML")

    # The answer handler shows the PRO message when the free tries run out in this session.
    # Tied to the session id so it can't leak into a later normal practice/exam session.
    await state.update_data(
        session_id=session_id, mode="practice",
        review_session=session_id,  # last question shows "✅ Finish review"
        review_trial_session=session_id if is_trial else None,
        review_trial_left=trial_tries_left if is_trial else None,
    )
    await state.set_state(ExamSession.active)
    await send_question(message, state, session_id, telegram_id)


async def try_mistake_again(message: Message, state: FSMContext, telegram_id: int, question_id: str) -> None:
    """
    Starts at the chosen wrong question, then continues through the other mistakes with
    ➡️ Next Question. A correct answer removes a question from the list.
    """
    summary = await _check_mistakes_access(message, telegram_id, "try")
    if not summary:
        return
    intro = (
        "<b>TRY AGAIN</b>\n\n"
        "Starting with this question. Tap <b>Next Question</b> to continue with your other mistakes.\n"
        "A question is removed from your list once you answer it correctly."
    )
    if not summary.has_pro:
        left = summary.trial_tries_left
        intro += (
            f"\n\n<i>Free trial: {left} tr{'ies' if left != 1 else 'y'} left. "
            "Each answered question uses one.</i>"
        )
    await _start_review(
        message, state, telegram_id, intro=intro, review_question_id=question_id,
        is_trial=not summary.has_pro, trial_tries_left=summary.trial_tries_left or 0,
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

    trial_note = ""
    if not summary.has_pro:
        trial_note = (
            "\n\n<i>That was your free AI explanation. "
            "Upgrade to PRO for unlimited AI explanations on every mistake.</i>"
        )
    await answer_long(
        message,
        f"<b>AI EXPLANATION</b>\n\n{esc(explanation.explanation)}{trial_note}",
        parse_mode="HTML",
        protect_content=True,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Try this question again", callback_data=f"mtry:{question_id}"),
        ]]),
    )


def _format_mistakes_list(data: MistakeListResponse, bot_username: str) -> str:
    """Summary + numbered wrong questions, each with Try again / Explain links."""
    lines = [
        "<b>REVIEW MY MISTAKES</b>",
        "",
        f"Questions to fix: <b>{data.total}</b>",
    ]
    if data.by_course:
        shown = data.by_course[:5]
        rows = [f"{esc(c.course_name)}: <b>{c.count}</b>" for c in shown]
        hidden = len(data.by_course) - len(shown)
        if hidden > 0:
            rows.append(f"<i>{_plural(hidden, 'more course')}</i>")
        lines.append("<blockquote><b>By course</b>\n" + "\n".join(rows) + "</blockquote>")
    lines.append("<i>A question is removed from this list once you answer it correctly.</i>")
    if data.is_trial:
        tries, ai = data.trial_tries_left or 0, data.trial_ai_left or 0
        lines.append(
            f"\n<b>Free trial:</b> {tries} tr{'ies' if tries != 1 else 'y'} and "
            f"{_plural(ai, 'AI explanation')} left"
        )

    base = f"https://t.me/{bot_username}?start="
    start_no = data.page * data.page_size
    for i, item in enumerate(data.items, start=start_no + 1):
        when = item.answered_at.astimezone(LOCAL_TZ).strftime("%b %d")
        meta = f"{esc(item.course_name)}  |  {when}" if item.course_name else when
        try_link = f'{base}{TRY_AGAIN_PREFIX}{item.question_id}'
        ai_link = f'{base}{EXPLAIN_PREFIX}{item.question_id}_{item.your_answer}'
        lines += [
            "",
            f"<b>{i}.</b> {esc(item.prompt)}",
            f"<i>{meta}  |  Your answer: {esc(item.your_answer)}</i>",
            f'<a href="{try_link}">Try again</a>  |  <a href="{ai_link}">Explain with AI</a>',
        ]

    if data.is_trial:
        lines.append("")
        if data.locked_count:
            lines.append(
                f"<blockquote>{_plural(data.locked_count, 'more mistake')} not shown. "
                "Upgrade to PRO to see and practise all of them.</blockquote>"
            )
        else:
            lines.append("<i>PRO includes unlimited tries and AI explanations on every mistake.</i>")
        return "\n".join(lines)

    pages = max(1, -(-data.total // data.page_size))
    lines += ["", f"<i>Page {data.page + 1} of {pages}</i>"]
    return "\n".join(lines)


def _mistakes_list_keyboard(data: MistakeListResponse) -> InlineKeyboardMarkup:
    if data.is_trial:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Practise all mistakes (PRO)", callback_data="mistakes:start")],
            *pro_plan_keyboard().inline_keyboard,
        ])
    rows = []
    nav = []
    if data.page > 0:
        nav.append(InlineKeyboardButton(text="‹ Newer", callback_data=f"mistakes:page:{data.page - 1}"))
    if data.has_next:
        nav.append(InlineKeyboardButton(text="Older ›", callback_data=f"mistakes:page:{data.page + 1}"))
    if nav:
        rows.append(nav)
    practice_n = min(data.total, REVIEW_MISTAKES_LIMIT)
    rows.append([InlineKeyboardButton(
        text=f"Practise all mistakes ({practice_n})", callback_data="mistakes:start")])
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
            f"<b>REVIEW MY MISTAKES</b>\n\n"
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

    # Make the update obvious: a toast naming the filter, the new result as a fresh
    # message at the bottom, and the old one deleted (Telegram shows a delete animation).
    toast = _history_toast(history, range_token)
    await callback.answer(toast)
    await callback.message.answer(
        _format_history(history, range_token),
        parse_mode="HTML",
        reply_markup=_history_keyboard(history, range_token),
    )
    await _delete_quietly(callback.message)


@router.callback_query(F.data.startswith("histc:"))
async def results_history_custom_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Asks the user to type the days they want to see."""
    mode = callback.data.split(":", 1)[1]
    await state.set_state(ResultsHistory.entering_dates)
    today = _local_today()
    prompt = await callback.message.answer(
        "<b>CUSTOM DATES</b>\n\n"
        "Type a date range (day/month/year):\n"
        f"<code>01/{today:%m/%Y} - {today:%d/%m/%Y}</code>\n\n"
        "Or one date to see a single day:\n"
        f"<code>{today:%d/%m/%Y}</code>\n\n"
        "<i>Send /cancel to go back.</i>",
        parse_mode="HTML",
    )
    # Remembered so both are removed once the new result is shown
    await state.update_data(
        history_mode=mode if mode in HISTORY_MODES else "all",
        history_old_msg_ids=[callback.message.message_id, prompt.message_id],
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
            f"<b>Invalid date.</b> {esc(str(e))}\n\n"
            "Example: <code>01/10/2026 - 04/11/2026</code>\n"
            "Tap <b>Custom dates</b> to try again.",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        return

    data = await state.get_data()
    mode = data.get("history_mode", "all")
    old_msg_ids = data.get("history_old_msg_ids") or []
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
    # Remove the old history message and the "Choose your dates" prompt (delete animation)
    for msg_id in old_msg_ids:
        try:
            await message.bot.delete_message(message.chat.id, msg_id)
        except TelegramBadRequest:
            pass
