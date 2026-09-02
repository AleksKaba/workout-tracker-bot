import asyncio
import os
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

from states import WorkoutStates
import db

load_dotenv()

router = Router()


def action_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Ещё подход", callback_data="more_set")],
        [InlineKeyboardButton(text="Новое упражнение", callback_data="new_exercise")],
        [InlineKeyboardButton(text="Закончить тренировку", callback_data="finish")]
    ])


@router.message(Command("start"))
async def start_workout(message: Message, state: FSMContext):
    await state.clear()
    user_id = db.get_or_create_user(message.from_user.id, message.from_user.full_name)
    workout_id = db.create_workout(user_id)
    await state.update_data(workout_id=workout_id, set_number=1)
    await state.set_state(WorkoutStates.waiting_exercise)
    await message.answer("Тренировка начата. Какое упражнение?")


@router.message(WorkoutStates.waiting_exercise)
async def handle_exercise(message: Message, state: FSMContext):
    exercise_id = db.get_or_create_exercise(message.text.strip())
    await state.update_data(exercise_id=exercise_id, exercise_name=message.text.strip())
    await state.set_state(WorkoutStates.waiting_weight_reps)
    await message.answer("Вес и повторения через пробел (например: 80 8)")


@router.message(WorkoutStates.waiting_weight_reps)
async def handle_weight_reps(message: Message, state: FSMContext):
    parts = message.text.strip().split()
    if len(parts) != 2:
        await message.answer("Не понял. Введите вес и повторения через пробел, например: 80 8")
        return
    weight_str, reps_str = parts
    try:
        weight = float(weight_str.replace(",", "."))
        reps = int(reps_str)
    except ValueError:
        await message.answer("Вес — число, повторения — целое число. Попробуйте ещё раз.")
        return
    await state.update_data(weight_kg=weight, reps=reps)
    await state.set_state(WorkoutStates.waiting_feeling)
    await message.answer("Как самочувствие (1-10)?")


@router.message(WorkoutStates.waiting_feeling)
async def handle_feeling(message: Message, state: FSMContext):
    try:
        feeling = int(message.text.strip())
        if not (1 <= feeling <= 10):
            raise ValueError
    except ValueError:
        await message.answer("Введите число от 1 до 10.")
        return

    data = await state.get_data()
    db.insert_set(
        workout_id=data["workout_id"],
        exercise_id=data["exercise_id"],
        set_number=data["set_number"],
        weight_kg=data["weight_kg"],
        reps=data["reps"],
        rpe=feeling
    )
    await state.set_state(WorkoutStates.waiting_next_action)
    await message.answer(
        f"Подход записан: {data['exercise_name']} {data['weight_kg']}кг x {data['reps']}",
        reply_markup=action_keyboard()
    )


@router.callback_query(F.data == "more_set", WorkoutStates.waiting_next_action)
async def more_set(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.update_data(set_number=data["set_number"] + 1)
    await state.set_state(WorkoutStates.waiting_weight_reps)
    await callback.message.answer("Вес и повторения через пробел (например: 80 8)")
    await callback.answer()


@router.callback_query(F.data == "new_exercise", WorkoutStates.waiting_next_action)
async def new_exercise(callback: CallbackQuery, state: FSMContext):
    await state.update_data(set_number=1)
    await state.set_state(WorkoutStates.waiting_exercise)
    await callback.message.answer("Какое упражнение?")
    await callback.answer()


@router.callback_query(F.data == "finish", WorkoutStates.waiting_next_action)
async def finish(callback: CallbackQuery, state: FSMContext):
    await state.set_state(WorkoutStates.waiting_notes)
    await callback.message.answer("Есть заметки к тренировке? Если нет, напишите «нет»")
    await callback.answer()


@router.message(WorkoutStates.waiting_notes)
async def handle_notes(message: Message, state: FSMContext):
    data = await state.get_data()
    notes = None if message.text.strip().lower() == "нет" else message.text.strip()
    db.save_workout_notes(data["workout_id"], notes)
    await state.clear()
    await message.answer("Тренировка сохранена. Отличная работа!")


async def main():
    bot = Bot(token=os.getenv("BOT_TOKEN"))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())