from aiogram.fsm.state import State, StatesGroup

class WorkoutStates(StatesGroup):
    waiting_exercise_list = State()
    waiting_exercise_number = State()
    waiting_weight_reps = State()
    waiting_more_sets = State()
    waiting_notes = State()


class DeleteStates(StatesGroup):
    waiting_workout_choice = State()


class EditStates(StatesGroup):
    waiting_workout_choice = State()
    waiting_exercise_choice = State()
    waiting_set_action = State()
    waiting_new_weight_reps = State()