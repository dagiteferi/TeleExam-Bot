from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """
    Generates the main menu ReplyKeyboardMarkup for persistent navigation.
    """
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📚 Take Exam"),
                KeyboardButton(text="📝 Practice Questions"),
            ],
            [
                KeyboardButton(text="🧠 AI Tutor"),
                KeyboardButton(text="📊 My Study Plan"),
            ],
            [
                KeyboardButton(text="📈 My Progress"),
                KeyboardButton(text="🔗 Refer & Earn"),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
        one_time_keyboard=False,
    )
    return keyboard


def chat_menu_keyboard() -> ReplyKeyboardMarkup:
    """
    Generates a simple reply keyboard to end the AI chat session.
    """
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔚 End Chat")]],
        resize_keyboard=True,
    )
