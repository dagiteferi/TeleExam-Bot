from typing import List, Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def question_choices_keyboard(
    question_id: str, options: List[str], qtoken: str
) -> InlineKeyboardMarkup:
    """
    Generates an inline keyboard for multiple-choice question options.
    Each button's callback data will include the question ID, chosen option, and qtoken.
    """
    buttons = []
    for i, option_text in enumerate(options):
        # Assuming options are A, B, C, D for choices
        choice_letter = chr(65 + i)
        # Callback data format: "answer_{question_id}_{choice_letter}_{qtoken}"
        callback_data = f"answer_{question_id}_{choice_letter}_{qtoken}"
        buttons.append(
            InlineKeyboardButton(text=f"{choice_letter}. {option_text}", callback_data=callback_data)
        )

    # Arrange buttons in two columns for better display
    keyboard_rows = []
    for i in range(0, len(buttons), 2):
        keyboard_rows.append(buttons[i : i + 2])

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
        # Callback data format: "explain_ai_{session_id}_{qtoken}"
        buttons.append(
            InlineKeyboardButton(
                text="🧠 Explain with AI", callback_data=f"explain_ai_{session_id}_{qtoken}"
            )
        )

    if has_next_question:
        # Callback data format: "next_question_{session_id}"
        buttons.append(
            InlineKeyboardButton(
                text="➡️ Next Question", callback_data=f"next_question_{session_id}"
            )
        )
    else:
        # Callback data format: "end_session_{session_id}"
        buttons.append(
            InlineKeyboardButton(
                text="✅ End Session", callback_data=f"end_session_{session_id}"
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
