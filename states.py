from aiogram.fsm.state import State, StatesGroup

class ExamStates(StatesGroup):
    waiting_for_mode = State()
    in_exam = State()           # User is currently taking an exam
    waiting_for_answer = State()
    after_answer = State()      # Show feedback + "Next" or "Explain"