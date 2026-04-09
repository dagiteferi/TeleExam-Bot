from aiogram.fsm.state import State, StatesGroup


class Onboarding(StatesGroup):
    """
    States for the user onboarding process.
    """

    selecting_department = State()


class ExamSession(StatesGroup):
    """
    States for managing an active exam, practice, or quiz session.
    """

    selecting_exam = State()
    selecting_course = State()
    active = State()  # Session is in progress, question has been sent
    waiting_for_answer = State()  # Bot is waiting for the user's answer
    reviewing = State()  # User is reviewing an answer in practice mode


class AIInteraction(StatesGroup):
    """
    States for managing AI tutor interactions.
    """

    chatting = State()  # User is actively chatting with the AI tutor
