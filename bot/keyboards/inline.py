from typing import List, Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def question_choices_keyboard(
    question_id: str, options: List[str], qtoken: str
) -> InlineKeyboardMarkup:
    """
    Generates an inline keyboard for multiple-choice question options.
    Each option is on its own row. Buttons show only the letter label (A, B, C, D)
    since the full text is rendered in the question message itself.
    """
    # Each answer on its own row for maximum clarity and readability
    keyboard_rows = []
    for i, _ in enumerate(options):
        choice_letter = chr(65 + i)
        callback_data = f"ans_{choice_letter}_{qtoken}"
        keyboard_rows.append([
            InlineKeyboardButton(text=f"  {choice_letter}  ", callback_data=callback_data)
        ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard_rows)


def session_action_keyboard(
    session_id: str,
    has_next_question: bool,
    is_practice_mode: bool,
    qtoken: Optional[str] = None,
) -> InlineKeyboardMarkup:
    """
    Generates an inline keyboard for session actions like "Explain with AI",
    "Next Question", and "End Session".
    """
    buttons = []

    if is_practice_mode and qtoken:
        # Callback data format: "expai_{qtoken}"
        buttons.append(
            InlineKeyboardButton(
                text="🧠 Explain with AI", callback_data=f"expai_{qtoken}"
            )
        )

    if has_next_question:
        # Callback data format: "next_{session_id}"
        buttons.append(
            InlineKeyboardButton(
                text="➡️ Next Question", callback_data=f"next_{session_id}"
            )
        )
    else:
        # Callback data format: "end_{session_id}"
        buttons.append(
            InlineKeyboardButton(
                text="✅ End Session", callback_data=f"end_{session_id}"
            )
        )

    # Arrange buttons in a single column for simplicity
    keyboard_rows = [[button] for button in buttons]

    return InlineKeyboardMarkup(inline_keyboard=keyboard_rows)


def department_selection_keyboard(departments: List[dict]) -> InlineKeyboardMarkup:
    """
    Generates an inline keyboard for selecting a department during onboarding.
    Each button's callback data will include the department ID.
    """
    buttons = []
    for dept in departments:
        # Callback data format: "select_dept_{dept_id}"
        callback_data = f"select_dept_{dept['id']}"
        buttons.append(
            InlineKeyboardButton(text=dept["name"].title(), callback_data=callback_data)
        )

    # Arrange buttons in a single column
    keyboard_rows = [[button] for button in buttons]

    return InlineKeyboardMarkup(inline_keyboard=keyboard_rows)


def exam_selection_keyboard(exams: List[dict]) -> InlineKeyboardMarkup:
    """
    Generates an inline keyboard for selecting an exam for the chosen department.
    Each button's callback data will include the exam year and semester.
    Sorted by year in increasing order.
    """
    # Sort exams by year (ascending)
    # If years are equal, sort by semester (ascending)
    exams_sorted = sorted(exams, key=lambda x: (x["year"], x["semester"]))

    buttons = []
    for exam in exams_sorted:
        exam_id = exam["id"]
        year = exam["year"]
        semester = exam["semester"]
        # Callback data format: "ex_{id}_{year}_{semester}" (Max 64 chars)
        callback_data = f"ex_{exam_id}_{year}_{semester}"
        text = f"{year} - {semester.title()}"
        buttons.append(
            InlineKeyboardButton(text=text, callback_data=callback_data)
        )

    # Arrange buttons in a single column so long names like "Hamle Afternoon" don't wrap
    keyboard_rows = [[button] for button in buttons]

    return InlineKeyboardMarkup(inline_keyboard=keyboard_rows)


def course_selection_keyboard(courses: List[dict]) -> InlineKeyboardMarkup:
    """
    Generates an inline keyboard for selecting a course for practice mode.
    Each button's callback data will include the course ID.
    Sorted alphabetically by name.
    """
    # Sort courses by name (ascending)
    courses_sorted = sorted(courses, key=lambda x: x["name"])

    buttons = []
    for course in courses_sorted:
        # Callback data format: "select_course_{course_id}"
        callback_data = f"select_course_{course['id']}"
        buttons.append(
            InlineKeyboardButton(text=course["name"].title(), callback_data=callback_data)
        )

    # Arrange buttons in a single column
    keyboard_rows = [[button] for button in buttons]

    return InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
