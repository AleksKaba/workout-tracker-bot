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


def yes_no_keyboard(yes_data, no_data, yes_text="Да", no_text="Нет"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=yes_text, callback_data=yes_data)],
        [InlineKeyboardButton(text=no_text, callback_data=no_data)]
    ])


def format_exercise_list(exercises):
    lines = []
    for ex in exercises:
        mark = "✅" if ex["done"] else "⬜"
        lines.append(f"{ex['number']}. {mark} {ex['name']}")
    lines.append("")
    lines.append("Отправьте номер упражнения, чтобы отметить его.")
    lines.append("Когда закончите — напишите «готово».")
    return "\n".join(lines)


@router.message(Command("start"))
async def start_workout(message: Message, state: FSMContext):
    await state.clear()
    user_id = db.get_or_create_user(message.from_user.id, message.from_user.full_name)
    workout_id = db.create_workout(user_id)
    await state.update_data(workout_id=workout_id)
    await state.set_state(WorkoutStates.waiting_exercise_list)
    await message.answer(
        "Тренировка начата. Перечислите упражнения на сегодня через запятую, "
        "например: Присед, Отжимания, Тяга"
    )


@router.message(WorkoutStates.waiting_exercise_list)
async def handle_exercise_list(message: Message, state: FSMContext):
    names = [n.strip() for n in message.text.split(",") if n.strip()]
    if not names:
        await message.answer("Не понял список. Перечислите упражнения через запятую.")
        return

    exercises = []
    for i, name in enumerate(names, start=1):
        exercise_id = db.get_or_create_exercise(name)
        exercises.append({
            "number": i,
            "name": name,
            "exercise_id": exercise_id,
            "done": False
        })

    await state.update_data(exercises=exercises)
    await state.set_state(WorkoutStates.waiting_exercise_number)
    await message.answer(format_exercise_list(exercises))


@router.message(WorkoutStates.waiting_exercise_number)
async def handle_exercise_number(message: Message, state: FSMContext):
    text = message.text.strip().lower()
    data = await state.get_data()
    exercises = data["exercises"]

    if text == "готово":
        await state.set_state(WorkoutStates.waiting_notes)
        await message.answer("Есть заметки к тренировке? Если нет, напишите «нет»")
        return

    if not text.isdigit():
        await message.answer("Отправьте номер упражнения из списка, или напишите «готово».")
        return

    number = int(text)
    exercise = next((e for e in exercises if e["number"] == number), None)
    if exercise is None:
        await message.answer("Такого номера нет в списке. Попробуйте ещё раз.")
        return

    await state.update_data(current_exercise_number=number)
    await state.set_state(WorkoutStates.waiting_confirm_done)
    await message.answer(
        f"«{exercise['name']}» — вы выполнили это упражнение?",
        reply_markup=yes_no_keyboard("done_yes", "done_no")
    )


@router.callback_query(F.data == "done_no", WorkoutStates.waiting_confirm_done)
async def handle_done_no(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.set_state(WorkoutStates.waiting_exercise_number)
    await callback.message.answer(format_exercise_list(data["exercises"]))
    await callback.answer()


@router.callback_query(F.data == "done_yes", WorkoutStates.waiting_confirm_done)
async def handle_done_yes(callback: CallbackQuery, state: FSMContext):
    await state.update_data(current_set_number=1)
    await state.set_state(WorkoutStates.waiting_weight_reps)
    await callback.message.answer("Вес и повторения через пробел (например: 80 8)")
    await callback.answer()


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

    data = await state.get_data()
    exercises = data["exercises"]
    number = data["current_exercise_number"]
    exercise = next(e for e in exercises if e["number"] == number)

    db.insert_set(
        workout_id=data["workout_id"],
        exercise_id=exercise["exercise_id"],
        set_number=data["current_set_number"],
        weight_kg=weight,
        reps=reps
    )

    await state.set_state(WorkoutStates.waiting_more_sets)
    await message.answer(
        f"Подход записан: {exercise['name']} {weight}кг x {reps}. Ещё один подход?",
        reply_markup=yes_no_keyboard("more_set_yes", "more_set_done", yes_text="Да", no_text="Хватит")
    )


@router.callback_query(F.data == "more_set_yes", WorkoutStates.waiting_more_sets)
async def handle_more_set_yes(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.update_data(current_set_number=data["current_set_number"] + 1)
    await state.set_state(WorkoutStates.waiting_weight_reps)
    await callback.message.answer("Вес и повторения через пробел (например: 80 8)")
    await callback.answer()


@router.callback_query(F.data == "more_set_done", WorkoutStates.waiting_more_sets)
async def handle_more_set_done(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    exercises = data["exercises"]
    number = data["current_exercise_number"]
    for e in exercises:
        if e["number"] == number:
            e["done"] = True

    await state.update_data(exercises=exercises)
    await state.set_state(WorkoutStates.waiting_exercise_number)
    await callback.message.answer(format_exercise_list(exercises))
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