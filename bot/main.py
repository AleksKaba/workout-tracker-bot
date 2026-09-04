import asyncio
import os
import random
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from dotenv import load_dotenv

from states import WorkoutStates, DeleteStates, EditStates
import db

load_dotenv()

router = Router()

STICKER_IDS = [
    "CAACAgIAAxkBAAIBRWqaclgHzj6lXSLV7iZgiCy0JEi_AAI_WQACxj84SfO3jPslJV86PQQ",
    "CAACAgIAAxkBAAIBQ2qackEuSMLOLr8HD6iwMxcqdIIMAALdeAAClqSJSlinhFLFs08kPQQ",
    "CAACAgIAAxkBAAIBQWqachoFGX2-GP34EKxPWmdh_IuJAAIlhwACrJ-RSDQMY-8Sdt-1PQQ",
    "CAACAgEAAxkBAAIBEWqaaTzKA7dN4cdXIUAiph9ADO-fAAL7AAPFiJwE5Su2-pBEE3M9BA",
]


def more_sets_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Ещё подход", callback_data="more_set_yes")],
        [InlineKeyboardButton(text="Закончил упражнение", callback_data="more_set_done")]
    ])


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


def format_workout_list(workouts):
    lines = []
    for i, w in enumerate(workouts, start=1):
        date_str = w["started_at"].strftime("%d.%m.%Y %H:%M")
        exercises_str = ", ".join(w["exercises"]) if w["exercises"] else "без упражнений"
        lines.append(f"{i}. {date_str} — {exercises_str}")
    return "\n".join(lines)


def format_exercises_for_edit(exercises):
    lines = []
    for i, ex in enumerate(exercises, start=1):
        lines.append(f"{i}. {ex['name']} — {ex['set_count']} подход(ов)")
    return "\n".join(lines)


def format_sets_for_edit(exercise, sets):
    lines = [f"{exercise['name']}:"]
    for s in sets:
        lines.append(f"{s['set_number']}) {s['weight_kg']}x{s['reps']}")
    lines.append("")
    lines.append("Отправьте номер подхода, чтобы изменить его вес/повторения.")
    lines.append("Напишите «удалить N», чтобы удалить подход N.")
    lines.append("Напишите «добавить», чтобы добавить новый подход.")
    lines.append("Напишите «отмена», чтобы выйти.")
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


@router.message(Command("delete"))
async def delete_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = db.get_or_create_user(message.from_user.id, message.from_user.full_name)
    workouts = db.get_recent_workouts(user_id, limit=10)
    if not workouts:
        await message.answer("Пока нет сохранённых тренировок.")
        return
    await state.update_data(workouts=workouts)
    await state.set_state(DeleteStates.waiting_workout_choice)
    await message.answer(
        format_workout_list(workouts) + "\n\nОтправьте номер тренировки для удаления, или «отмена»."
    )


@router.message(DeleteStates.waiting_workout_choice)
async def delete_choose(message: Message, state: FSMContext):
    text = message.text.strip().lower()
    if text == "отмена":
        await state.clear()
        await message.answer("Отменено.")
        return
    if not text.isdigit():
        await message.answer("Отправьте номер тренировки из списка, или «отмена».")
        return

    data = await state.get_data()
    workouts = data["workouts"]
    index = int(text)
    if index < 1 or index > len(workouts):
        await message.answer("Такого номера нет в списке.")
        return

    workout = workouts[index - 1]
    await state.update_data(target_workout_id=workout["workout_id"])
    date_str = workout["started_at"].strftime("%d.%m.%Y %H:%M")
    await message.answer(
        f"Точно удалить тренировку от {date_str}? Все подходы будут удалены навсегда.",
        reply_markup=yes_no_keyboard("delete_confirm_yes", "delete_confirm_no")
    )


@router.callback_query(F.data == "delete_confirm_yes")
async def delete_confirm_yes(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    workout_id = data.get("target_workout_id")
    if workout_id:
        db.delete_workout(workout_id)
        await callback.message.answer("Тренировка удалена.")
    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "delete_confirm_no")
async def delete_confirm_no(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Отменено.")
    await callback.answer()


@router.message(Command("edit"))
async def edit_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = db.get_or_create_user(message.from_user.id, message.from_user.full_name)
    workouts = db.get_recent_workouts(user_id, limit=10)
    if not workouts:
        await message.answer("Пока нет сохранённых тренировок.")
        return
    await state.update_data(workouts=workouts)
    await state.set_state(EditStates.waiting_workout_choice)
    await message.answer(
        format_workout_list(workouts) + "\n\nОтправьте номер тренировки для редактирования, или «отмена»."
    )


@router.message(EditStates.waiting_workout_choice)
async def edit_choose_workout(message: Message, state: FSMContext):
    text = message.text.strip().lower()
    if text == "отмена":
        await state.clear()
        await message.answer("Отменено.")
        return
    if not text.isdigit():
        await message.answer("Отправьте номер тренировки из списка, или «отмена».")
        return

    data = await state.get_data()
    workouts = data["workouts"]
    index = int(text)
    if index < 1 or index > len(workouts):
        await message.answer("Такого номера нет в списке.")
        return

    workout = workouts[index - 1]
    exercises = db.get_workout_exercises(workout["workout_id"])
    if not exercises:
        await message.answer("В этой тренировке нет записанных подходов.")
        await state.clear()
        return

    await state.update_data(target_workout_id=workout["workout_id"], exercises=exercises)
    await state.set_state(EditStates.waiting_exercise_choice)
    await message.answer(
        format_exercises_for_edit(exercises) + "\n\nОтправьте номер упражнения, или «отмена»."
    )


@router.message(EditStates.waiting_exercise_choice)
async def edit_choose_exercise(message: Message, state: FSMContext):
    text = message.text.strip().lower()
    if text == "отмена":
        await state.clear()
        await message.answer("Отменено.")
        return
    if not text.isdigit():
        await message.answer("Отправьте номер упражнения из списка, или «отмена».")
        return

    data = await state.get_data()
    exercises = data["exercises"]
    index = int(text)
    if index < 1 or index > len(exercises):
        await message.answer("Такого номера нет в списке.")
        return

    exercise = exercises[index - 1]
    workout_id = data["target_workout_id"]
    sets = db.get_exercise_sets(workout_id, exercise["exercise_id"])
    await state.update_data(target_exercise=exercise, sets=sets)
    await state.set_state(EditStates.waiting_set_action)
    await message.answer(format_sets_for_edit(exercise, sets))


@router.message(EditStates.waiting_set_action)
async def edit_set_action(message: Message, state: FSMContext):
    text = message.text.strip().lower()
    data = await state.get_data()

    if text == "отмена":
        await state.clear()
        await message.answer("Отменено.")
        return

    if text == "добавить":
        await state.update_data(edit_action="add")
        await state.set_state(EditStates.waiting_new_weight_reps)
        await message.answer("Вес и повторения нового подхода через пробел (например: 80 8)")
        return

    if text.startswith("удалить "):
        number_str = text.replace("удалить ", "").strip()
        if not number_str.isdigit():
            await message.answer("Формат: «удалить 2»")
            return
        set_number = int(number_str)
        sets = data["sets"]
        target = next((s for s in sets if s["set_number"] == set_number), None)
        if target is None:
            await message.answer("Такого подхода нет.")
            return
        exercise = data["target_exercise"]
        workout_id = data["target_workout_id"]
        db.delete_set(target["set_id"], workout_id, exercise["exercise_id"])
        new_sets = db.get_exercise_sets(workout_id, exercise["exercise_id"])
        await state.update_data(sets=new_sets)
        if new_sets:
            await message.answer("Подход удалён.\n\n" + format_sets_for_edit(exercise, new_sets))
        else:
            await message.answer("Подход удалён. Больше подходов у этого упражнения нет.")
            await state.clear()
        return

    if text.isdigit():
        set_number = int(text)
        sets = data["sets"]
        target = next((s for s in sets if s["set_number"] == set_number), None)
        if target is None:
            await message.answer("Такого подхода нет.")
            return
        await state.update_data(edit_action="edit", target_set_id=target["set_id"])
        await state.set_state(EditStates.waiting_new_weight_reps)
        await message.answer(f"Новый вес и повторения для подхода {set_number} (например: 82 6)")
        return

    await message.answer("Не понял. Отправьте номер подхода, «удалить N», «добавить» или «отмена».")


@router.message(EditStates.waiting_new_weight_reps)
async def edit_new_weight_reps(message: Message, state: FSMContext):
    parts = message.text.strip().split()
    if len(parts) != 2:
        await message.answer("Не понял. Введите вес и повторения через пробел, например: 82 6")
        return
    weight_str, reps_str = parts
    try:
        weight = float(weight_str.replace(",", "."))
        reps = int(reps_str)
    except ValueError:
        await message.answer("Вес — число, повторения — целое число. Попробуйте ещё раз.")
        return

    data = await state.get_data()
    exercise = data["target_exercise"]
    workout_id = data["target_workout_id"]

    if data.get("edit_action") == "add":
        set_number = db.get_next_set_number(workout_id, exercise["exercise_id"])
        db.insert_set(workout_id, exercise["exercise_id"], set_number, weight, reps)
        await message.answer("Подход добавлен.")
    else:
        db.update_set(data["target_set_id"], weight, reps)
        await message.answer("Подход обновлён.")

    new_sets = db.get_exercise_sets(workout_id, exercise["exercise_id"])
    await state.update_data(sets=new_sets)
    await state.set_state(EditStates.waiting_set_action)
    await message.answer(format_sets_for_edit(exercise, new_sets))


@router.message(F.sticker)
async def get_sticker_id(message: Message):
    await message.answer(f"file_id этого стикера:\n{message.sticker.file_id}")


async def main():
    bot = Bot(token=os.getenv("BOT_TOKEN"))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await bot.set_my_commands([
        BotCommand(command="start", description="Начать новую тренировку"),
        BotCommand(command="history", description="Посмотреть историю тренировок"),
        BotCommand(command="edit", description="Изменить тренировку"),
        BotCommand(command="delete", description="Удалить тренировку"),
    ])

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())