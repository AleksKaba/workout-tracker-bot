import asyncio
import random
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

STICKER_IDS = [
    "CAACAgEAAxkBAAIBEWqaaTzKA7dN4cdXIUAiph9ADO-fAAL7AAPFiJwE5Su2-pBEE3M9BA",
    "CAACAgIAAxkBAAIBQWqachoFGX2-GP34EKxPWmdh_IuJAAIlhwACrJ-RSDQMY-8Sdt-1PQQ",
    "CAACAgIAAxkBAAIBQ2qackEuSMLOLr8HD6iwMxcqdIIMAALdeAAClqSJSlinhFLFs08kPQQ",
    "CAACAgIAAxkBAAIBRWqaclgHzj6lXSLV7iZgiCy0JEi_AAI_WQACxj84SfO3jPslJV86PQQ"
    ]


def more_sets_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Ещё подход", callback_data="more_set_yes")],
        [InlineKeyboardButton(text="Закончил упражнение", callback_data="more_set_done")]
    ])


def format_exercise_list(exercises):
    lines = []
    for ex in exercises:
        mark = "✅" if ex["done"] else "⬜"
        lines.append(f"{ex['number']}. {mark} {ex['name']}")
    lines.append("")
    lines.append("Отправьте номер упражнения, чтобы начать его.")
    lines.append("Когда закончите все упражнения — напишите «готово».")
    return "\n".join(lines)


def format_exercise_summary(exercise):
    lines = [f"{exercise['name']} — {len(exercise['sets'])} подход(ов):"]
    for i, (weight, reps) in enumerate(exercise["sets"], start=1):
        lines.append(f"{i}) {weight}x{reps}")
    return "\n".join(lines)


def format_full_summary(exercises):
    lines = []
    n = 1
    for ex in exercises:
        if not ex["sets"]:
            continue
        set_parts = " ".join(f"{i}) {w}х{r}" for i, (w, r) in enumerate(ex["sets"], start=1))
        lines.append(f"{n}. {ex['name']} {len(ex['sets'])} подход(ов): {set_parts}")
        n += 1
    return "\n".join(lines) if lines else "Подходов не было."


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
            "done": False,
            "sets": []
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
        summary = format_full_summary(exercises)
        await state.set_state(WorkoutStates.waiting_notes)
        await message.answer(summary)
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
    await state.set_state(WorkoutStates.waiting_weight_reps)
    await message.answer(f"«{exercise['name']}». Вес и повторения через пробел (например: 80 8)")


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

    set_number = len(exercise["sets"]) + 1
    exercise["sets"].append((weight, reps))

    db.insert_set(
        workout_id=data["workout_id"],
        exercise_id=exercise["exercise_id"],
        set_number=set_number,
        weight_kg=weight,
        reps=reps
    )

    await state.update_data(exercises=exercises)
    await state.set_state(WorkoutStates.waiting_more_sets)
    await message.answer(
        f"Вы сделали {set_number} подход {weight}x{reps}",
        reply_markup=more_sets_keyboard()
    )


@router.callback_query(F.data == "more_set_yes", WorkoutStates.waiting_more_sets)
async def handle_more_set_yes(callback: CallbackQuery, state: FSMContext):
    await state.set_state(WorkoutStates.waiting_weight_reps)
    await callback.message.answer("Вес и повторения через пробел (например: 80 8)")
    await callback.answer()


@router.callback_query(F.data == "more_set_done", WorkoutStates.waiting_more_sets)
async def handle_more_set_done(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    exercises = data["exercises"]
    number = data["current_exercise_number"]
    exercise = next(e for e in exercises if e["number"] == number)
    exercise["done"] = True

    await state.update_data(exercises=exercises)
    await state.set_state(WorkoutStates.waiting_exercise_number)
    await callback.message.answer(format_exercise_summary(exercise))
    await callback.message.answer(format_exercise_list(exercises))
    await callback.answer()


@router.message(WorkoutStates.waiting_notes)
async def handle_notes(message: Message, state: FSMContext):
    data = await state.get_data()
    notes = None if message.text.strip().lower() == "нет" else message.text.strip()
    db.save_workout_notes(data["workout_id"], notes)
    await state.clear()
        await message.answer("Тренировка сохранена. Молодца! 💪")
    if STICKER_IDS:
        await message.answer_sticker(random.choice(STICKER_IDS))

@router.message(Command("history"))
async def show_history(message: Message):
    user_id = db.get_or_create_user(message.from_user.id, message.from_user.full_name)
    history = db.get_workout_history(user_id, limit=5)

    if not history:
        await message.answer("Пока нет сохранённых тренировок.")
        return

    for workout in history:
        date_str = workout["started_at"].strftime("%d.%m.%Y %H:%M")
        lines = [f"📅 {date_str}"]
        for exercise_name, sets in workout["exercises"].items():
            sets_str = ", ".join(f"{w}x{r}" for _, w, r in sets)
            lines.append(f"— {exercise_name}: {len(sets)} подход(ов) ({sets_str})")
        if workout["notes"]:
            lines.append(f"Заметка: {workout['notes']}")
        await message.answer("\n".join(lines))


@router.message(F.sticker)
async def get_sticker_id(message: Message):
    await message.answer(f"file_id этого стикера:\n{message.sticker.file_id}")


async def main():
    bot = Bot(token=os.getenv("BOT_TOKEN"))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())