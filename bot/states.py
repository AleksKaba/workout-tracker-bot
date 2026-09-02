from aiogram.fsm.state import State, StatesGroup

class WorkoutStates(StatesGroup):
    waiting_exercise = State()
    waiting_weight_reps = State()
    waiting_feeling = State()
    waiting_next_action = State()
    waiting_notes = State()