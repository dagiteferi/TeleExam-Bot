from aiogram.fsm.state import State, StatesGroup


class Onboarding(StatesGroup):
    """
    States for the user onboarding process.
    """

    selecting_department = State()
    confirming_department = State()  # Department tapped; waiting for the user to confirm


class DualDegree(StatesGroup):
    """States for choosing and unlocking a second department."""

    selecting_department = State()
    confirming_department = State()


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


class Payment(StatesGroup):
    """
    States for handling payment receipt upload.
    """

    uploading_screenshot = State()



# States in which the user is in the middle of something (an exam, an AI chat, a
# payment upload, onboarding...). Announcements and menu refreshes wait until the
# user leaves them, so nothing interrupts what they are doing.
BUSY_STATES = frozenset({
    Onboarding.selecting_department.state,
    Onboarding.confirming_department.state,
    DualDegree.selecting_department.state,
    DualDegree.confirming_department.state,
    ExamSession.selecting_exam.state,
    ExamSession.selecting_course.state,
    ExamSession.active.state,
    ExamSession.waiting_for_answer.state,
    ExamSession.reviewing.state,
    AIInteraction.chatting.state,
    Payment.uploading_screenshot.state,
})


def is_busy(state_name: str | None) -> bool:
    return state_name in BUSY_STATES
