from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


@dataclass(frozen=True)
class MenuState:
    """The plan details that decide which main menu buttons a user sees."""

    is_pro: bool = False
    has_dual_access: bool = False  # PRO + approved dual payment (or admin full access)

    @classmethod
    def from_profile(cls, profile: dict) -> "MenuState":
        return cls(
            is_pro=bool(profile.get("is_pro")),
            has_dual_access=bool(profile.get("has_dual_access")),
        )


# Menu state of the user whose update is being handled. Set per update by
# AutoUpsertMiddleware so every main menu matches the user's current plan.
current_menu_state: ContextVar[MenuState] = ContextVar("current_menu_state", default=MenuState())

# Texts of the main menu buttons (must match main_menu_keyboard below)
MAIN_MENU_TEXTS = frozenset({
    "📝 Exam Mode",
    "🎯 Practice Mode",
    "🧠 AI Tutor",
    "📅 Study Plan",
    "📊 My Progress",
    "🤝 Invite Friends",
    "📁 Saved Questions",
    "🎓 Dual Degree",
    "🔄 Switch Department",
    "⭐️ Upgrade to PRO",
})


def main_menu_keyboard(menu: Optional[MenuState] = None) -> ReplyKeyboardMarkup:
    """
    Main menu for the user's plan:
    free → "Dual Degree" + "Upgrade to PRO"; PRO → "Dual Degree";
    PRO with approved dual payment → "Switch Department" only.
    """
    if menu is None:
        menu = current_menu_state.get()
    keyboard = [
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
            KeyboardButton(text="🔄 Switch Department" if menu.has_dual_access else "🎓 Dual Degree"),
        ],
    ]
    if not menu.is_pro:
        keyboard.append([KeyboardButton(text="⭐️ Upgrade to PRO")])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
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
