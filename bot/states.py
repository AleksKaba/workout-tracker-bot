from aiogram.fsm.state import State, StatesGroup

class WorkoutStates(StatesGroup):
    waiting_exercise_list = State()
    waiting_exercise_number = State()
    waiting_weight_reps = State()
    waiting_more_sets = State()
    waiting_notes = State()