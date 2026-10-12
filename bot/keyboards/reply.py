from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

# Texts of the main menu buttons (must match main_menu_keyboard below)
MAIN_MENU_TEXTS = frozenset({
    "📝 Exam Mode",
    "🎯 Practice Mode",
    "🧠 AI Tutor",
    "📅 Study Plan",
    "📊 My Progress",
    "🤝 Invite Friends",
    "📁 Saved Questions",
    "⭐️ Upgrade to PRO",
})


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📝 Exam Mode"),
                KeyboardButton(text="🎯 Practice Mode"),
            ],
            [
                KeyboardButton(text="🧠 AI Tutor"),
                KeyboardButton(text="📅 Study Plan"),
            ],
            [
                KeyboardButton(text="📊 My Progress"),
                KeyboardButton(text="🤝 Invite Friends"),
            ],
            [
                KeyboardButton(text="📁 Saved Questions"),
                KeyboardButton(text="⭐️ Upgrade to PRO"),
            ]
        ],
        resize_keyboard=True,
        is_persistent=True,
        one_time_keyboard=False,
        input_field_placeholder="Choose an option from the menu...",
    )


def chat_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="End Chat")]],
        resize_keyboard=True,
        input_field_placeholder="Type your question here...",
    )
