import asyncio
import os
import random
import re
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from dotenv import load_dotenv

from states import WorkoutStates, DeleteStates, EditStates, TemplateStates
import db

load_dotenv()

router = Router()

background_tasks = set()
active_timers = {}

CATEGORIES = ["Ноги", "Плечи", "Грудь", "Спина", "Бицепс", "Трицепс"]

CATEGORY_EXERCISES = {
    "Ноги": ["Присед", "Выпады", "Жим ногами", "Сгибание ног", "Разгибание ног", "Икры"],
    "Плечи": ["Жим гантелей стоя", "Махи в стороны", "Махи в наклоне", "Жим Арнольда"],
    "Грудь": ["Жим лёжа", "Жим гантелей лёжа", "Разводка гантелей", "Отжимания"],
    "Спина": ["Тяга штанги", "Тяга блока", "Подтягивания", "Гиперэкстензия"],
    "Бицепс": ["Подъём на бицепс", "Молотки", "Концентрированный подъём"],
    "Трицепс": ["Французский жим", "Разгибание на блоке", "Отжимания на брусьях"],
}

SET_INPUT_RE = re.compile(
    r'^(\d+(?:[.,]\d+)?)\s*(?:кг)?\.?\s*[/\s]+\s*(\d+)\s*(.*)$',
    re.IGNORECASE
)


def parse_set_input(text):
    match = SET_INPUT_RE.match(text.strip())
    if not match:
        return None
    weight_str, reps_str, comment = match.groups()
    weight = float(weight_str.replace(",", "."))
    reps = int(reps_str)
    comment = comment.strip() or None
    return weight, reps, comment


STICKER_IDS = [
    "CAACAgIAAxkBAAIBRWqaclgHzj6lXSLV7iZgiCy0JEi_AAI_WQACxj84SfO3jPslJV86PQQ",
    "CAACAgIAAxkBAAIBQ2qackEuSMLOLr8HD6iwMxcqdIIMAALdeAAClqSJSlinhFLFs08kPQQ",
    "CAACAgIAAxkBAAIBQWqachoFGX2-GP34EKxPWmdh_IuJAAIlhwACrJ-RSDQMY-8Sdt-1PQQ",
    "CAACAgEAAxkBAAIBEWqaaTzKA7dN4cdXIUAiph9ADO-fAAL7AAPFiJwE5Su2-pBEE3M9BA",
]


def more_sets_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Закончил упражнение", callback_data="more_set_done")],
        [
            InlineKeyboardButton(text="⏱ 120 сек", callback_data="timer_120"),
            InlineKeyboardButton(text="⏱ 180 сек", callback_data="timer_180"),
            InlineKeyboardButton(text="⏱ 300 сек", callback_data="timer_300"),
        ]
    ])


def timer_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⏱ 120 сек", callback_data="timer_120"),
            InlineKeyboardButton(text="⏱ 180 сек", callback_data="timer_180"),
            InlineKeyboardButton(text="⏱ 300 сек", callback_data="timer_300"),
        ]
    ])


async def run_rest_timer(bot: Bot, chat_id: int, seconds: int):
    try:
        await asyncio.sleep(seconds)
        await bot.send_message(chat_id, "⏰ Отдых окончен! Время следующего подхода 💪")
    except asyncio.CancelledError:
        pass


def schedule_rest_timer(bot: Bot, chat_id: int, seconds: int):
    old_task = active_timers.get(chat_id)
    if old_task and not old_task.done():
        old_task.cancel()

    task = asyncio.create_task(run_rest_timer(bot, chat_id, seconds))
    active_timers[chat_id] = task
    background_tasks.add(task)

    def _cleanup(finished_task, chat_id=chat_id):
        background_tasks.discard(finished_task)
        if active_timers.get(chat_id) is finished_task:
            active_timers.pop(chat_id, None)

    task.add_done_callback(_cleanup)


def cancel_active_timer(chat_id: int):
    task = active_timers.get(chat_id)
    if task and not task.done():
        task.cancel()


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
    for i, s in enumerate(exercise["sets"], start=1):
        weight, reps, comment = s
        line = f"{i}) {weight}кг/{reps}"
        if comment:
            line += f" — {comment}"
        lines.append(line)
    return "\n".join(lines)


def format_exercise_progress(exercise):
    lines = [f"{exercise['number']}. {exercise['name']}:"]
    for i, s in enumerate(exercise["sets"], start=1):
        weight, reps, comment = s
        line = f"{i}) {weight}кг/{reps}"
        if comment:
            line += f" — {comment}"
        lines.append(line)
    next_i = len(exercise["sets"]) + 1
    lines.append(f"{next_i}) Подход - напишите вес и количество повторений, пример: 80кг/5")
    return "\n".join(lines)


def format_full_summary(exercises):
    lines = []
    n = 1
    for ex in exercises:
        if not ex["sets"]:
            continue
        set_parts = []
        for i, s in enumerate(ex["sets"], start=1):
            weight, reps, comment = s
            part = f"{i}) {weight}кг/{reps}"
            if comment:
                part += f" ({comment})"
            set_parts.append(part)
        lines.append(f"{n}. {ex['name']} {len(ex['sets'])} подход(ов): {' '.join(set_parts)}")
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
        line = f"{s['set_number']}) {s['weight_kg']}кг/{s['reps']}"
        if s.get("comment"):
            line += f" — {s['comment']}"
        lines.append(line)
    lines.append("")
    lines.append("Отправьте номер подхода, чтобы изменить его вес/повторения.")
    lines.append("Напишите «удалить N», чтобы удалить подход N.")
    lines.append("Напишите «добавить», чтобы добавить новый подход.")
    lines.append("Напишите «отмена», чтобы выйти.")
    return "\n".join(lines)


def templates_choice_keyboard(templates):
    rows = [
        [InlineKeyboardButton(text=t["name"], callback_data=f"tpl_{t['template_id']}")]
        for t in templates
    ]
    rows.append([InlineKeyboardButton(text="📋 Выбрать по группам мышц", callback_data="cat_start")])
    rows.append([InlineKeyboardButton(text="🆕 Свой список", callback_data="tpl_new")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def category_keyboard(selected):
    rows = []
    for cat in CATEGORIES:
        mark = "✅ " if cat in selected else ""
        rows.append([InlineKeyboardButton(text=f"{mark}{cat}", callback_data=f"catsel_{cat}")])
    rows.append([InlineKeyboardButton(text="Готово ▶", callback_data="cat_confirm")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def exercise_multiselect_keyboard(names, selected):
    rows = []
    for name in names:
        mark = "✅ " if name in selected else ""
        rows.append([InlineKeyboardButton(text=f"{mark}{name}", callback_data=f"exsel_{name}")])
    rows.append([InlineKeyboardButton(text="Начать тренировку ▶", callback_data="ex_confirm")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def format_template_list(templates):
    lines = [f"{i}. {t['name']}" for i, t in enumerate(templates, start=1)]
    lines.append("")
    lines.append("Отправьте номер шаблона, или «отмена».")
    return "\n".join(lines)


def format_template_view(name, exercises):
    lines = [f"«{name}»:"]
    for i, e in enumerate(exercises, start=1):
        lines.append(f"{i}. {e['name']}")
    lines.append("")
    lines.append("Напишите «удалить N», чтобы удалить упражнение N.")
    lines.append("Напишите «добавить: Название», чтобы добавить упражнение.")
    lines.append("Напишите «переименовать: Новое название», чтобы переименовать шаблон.")
    lines.append("Напишите «удалить шаблон», чтобы удалить его целиком.")
    lines.append("Напишите «отмена», чтобы выйти.")
    return "\n".join(lines)


@router.message(Command("start"))
async def start_workout(message: Message, state: FSMContext):
    await state.clear()
    user_id = db.get_or_create_user(message.from_user.id, message.from_user.full_name)
    workout_id = db.create_workout(user_id)
    await state.update_data(workout_id=workout_id, user_id=user_id)

    templates = db.get_templates(user_id)
    await state.set_state(WorkoutStates.waiting_template_choice)
    await message.answer(
        "Тренировка начата. Выберите вариант:",
        reply_markup=templates_choice_keyboard(templates)
    )


@router.callback_query(F.data == "tpl_new", WorkoutStates.waiting_template_choice)
async def handle_template_new(callback: CallbackQuery, state: FSMContext):
    await state.set_state(WorkoutStates.waiting_exercise_list)
    await callback.message.answer(
        "Перечислите упражнения на сегодня через запятую, например: Присед, Отжимания, Тяга"
    )
    await callback.answer()


@router.callback_query(F.data == "cat_start", WorkoutStates.waiting_template_choice)
async def handle_category_start(callback: CallbackQuery, state: FSMContext):
    await state.update_data(selected_categories=set())
    await state.set_state(WorkoutStates.waiting_category_choice)
    await callback.message.edit_text(
        "Выберите одну или несколько групп мышц:",
        reply_markup=category_keyboard(set())
    )
    await callback.answer()


@router.callback_query(F.data.startswith("catsel_"), WorkoutStates.waiting_category_choice)
async def handle_category_toggle(callback: CallbackQuery, state: FSMContext):
    cat = callback.data[len("catsel_"):]
    data = await state.get_data()
    selected = set(data.get("selected_categories", set()))
    if cat in selected:
        selected.discard(cat)
    else:
        selected.add(cat)
    await state.update_data(selected_categories=selected)
    await callback.message.edit_reply_markup(reply_markup=category_keyboard(selected))
    await callback.answer()


@router.callback_query(F.data == "cat_confirm", WorkoutStates.waiting_category_choice)
async def handle_category_confirm(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_categories", set())
    if not selected:
        await callback.answer("Выберите хотя бы одну группу мышц", show_alert=True)
        return

    names = []
    seen = set()
    for cat in CATEGORIES:
        if cat not in selected:
            continue
        for name in CATEGORY_EXERCISES.get(cat, []):
            if name not in seen:
                seen.add(name)
                names.append(name)

    await state.update_data(catalog_names=names, selected_exercises=set())
    await state.set_state(WorkoutStates.waiting_category_exercise_choice)
    await callback.message.edit_text(
        "Выберите упражнения на сегодня:",
        reply_markup=exercise_multiselect_keyboard(names, set())
    )
    await callback.answer()


@router.callback_query(F.data.startswith("exsel_"), WorkoutStates.waiting_category_exercise_choice)
async def handle_exercise_toggle(callback: CallbackQuery, state: FSMContext):
    name = callback.data[len("exsel_"):]
    data = await state.get_data()
    selected = set(data.get("selected_exercises", set()))
    if name in selected:
        selected.discard(name)
    else:
        selected.add(name)
    await state.update_data(selected_exercises=selected)
    catalog_names = data.get("catalog_names", [])
    await callback.message.edit_reply_markup(
        reply_markup=exercise_multiselect_keyboard(catalog_names, selected)
    )
    await callback.answer()


@router.callback_query(F.data == "ex_confirm", WorkoutStates.waiting_category_exercise_choice)
async def handle_exercise_confirm(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_exercises", set())
    if not selected:
        await callback.answer("Выберите хотя бы одно упражнение", show_alert=True)
        return

    catalog_names = data.get("catalog_names", [])
    chosen_names = [n for n in catalog_names if n in selected]

    exercises = []
    for i, name in enumerate(chosen_names, start=1):
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
    await callback.message.edit_text(format_exercise_list(exercises))
    await callback.answer()


@router.callback_query(F.data.startswith("tpl_"), WorkoutStates.waiting_template_choice)
async def handle_template_choice(callback: CallbackQuery, state: FSMContext):
    template_id = int(callback.data.split("_")[1])
    tpl_exercises = db.get_template_exercises(template_id)

    exercises = []
    for i, e in enumerate(tpl_exercises, start=1):
        exercises.append({
            "number": i,
            "name": e["name"],
            "exercise_id": e["exercise_id"],
            "done": False,
            "sets": []
        })

    await state.update_data(exercises=exercises)
    await state.set_state(WorkoutStates.waiting_exercise_number)
    await callback.message.answer(format_exercise_list(exercises))
    await callback.answer()


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
    await state.set_state(WorkoutStates.waiting_save_template_name)
    await message.answer(
        "Хотите сохранить этот список как шаблон для будущих тренировок?\n"
        "Если да — напишите название (например: День ног). Если нет — напишите «нет»."
    )


@router.message(WorkoutStates.waiting_save_template_name)
async def handle_save_template_name(message: Message, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()
    exercises = data["exercises"]
    user_id = data["user_id"]

    if text.lower() != "нет":
        if db.template_name_exists(user_id, text):
            await message.answer(
                "Шаблон с таким названием уже есть. Введите другое название, или «нет», чтобы не сохранять."
            )
            return
        template_id = db.create_template(user_id, text)
        for i, ex in enumerate(exercises, start=1):
            db.add_template_exercise(template_id, ex["exercise_id"], i)
        await message.answer(f"Шаблон «{text}» сохранён.")

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
    await state.set_state(WorkoutStates.waiting_set_input)
    await message.answer(format_exercise_progress(exercise), reply_markup=more_sets_keyboard())


@router.message(WorkoutStates.waiting_set_input)
async def handle_set_input(message: Message, state: FSMContext):
    text = message.text.strip()

    if text.lower() in ("готово", "закончил", "конец"):
        cancel_active_timer(message.chat.id)
        data = await state.get_data()
        exercises = data["exercises"]
        number = data["current_exercise_number"]
        exercise = next(e for e in exercises if e["number"] == number)
        exercise["done"] = True
        await state.update_data(exercises=exercises)
        await state.set_state(WorkoutStates.waiting_exercise_number)
        await message.answer(format_exercise_summary(exercise))
        await message.answer(format_exercise_list(exercises), reply_markup=timer_keyboard())
        return

    parsed = parse_set_input(text)
    if parsed is None:
        await message.answer(
            "Не понял формат. Пример: 80кг/5 (можно добавить комментарий: 80кг/5 было тяжело), "
            "или напишите «готово», чтобы закончить упражнение."
        )
        return
    weight, reps, comment = parsed

    cancel_active_timer(message.chat.id)

    data = await state.get_data()
    exercises = data["exercises"]
    number = data["current_exercise_number"]
    exercise = next(e for e in exercises if e["number"] == number)

    exercise["sets"].append((weight, reps, comment))
    set_number = len(exercise["sets"])

    db.insert_set(
        workout_id=data["workout_id"],
        exercise_id=exercise["exercise_id"],
        set_number=set_number,
        weight_kg=weight,
        reps=reps,
        comment=comment
    )

    await state.update_data(exercises=exercises)
    await message.answer(format_exercise_progress(exercise), reply_markup=more_sets_keyboard())


@router.callback_query(F.data.startswith("timer_"))
async def handle_timer_button(callback: CallbackQuery):
    seconds = int(callback.data.split("_")[1])
    schedule_rest_timer(callback.bot, callback.message.chat.id, seconds)
    await callback.answer(f"Таймер запущен на {seconds} сек ⏱")


@router.callback_query(F.data == "more_set_done")
async def handle_more_set_done(callback: CallbackQuery, state: FSMContext):
    cancel_active_timer(callback.message.chat.id)
    data = await state.get_data()
    if "exercises" not in data or "current_exercise_number" not in data:
        await callback.answer()
        return
    exercises = data["exercises"]
    number = data["current_exercise_number"]
    exercise = next((e for e in exercises if e["number"] == number), None)
    if exercise is None:
        await callback.answer()
        return
    exercise["done"] = True

    await state.update_data(exercises=exercises)
    await state.set_state(WorkoutStates.waiting_exercise_number)
    await callback.message.answer(format_exercise_summary(exercise))
    await callback.message.answer(format_exercise_list(exercises), reply_markup=timer_keyboard())
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
            parts = []
            for _, weight, reps, comment in sets:
                part = f"{weight}кг/{reps}"
                if comment:
                    part += f" ({comment})"
                parts.append(part)
            sets_str = ", ".join(parts)
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


@router.message(Command("templates"))
async def templates_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = db.get_or_create_user(message.from_user.id, message.from_user.full_name)
    templates = db.get_templates(user_id)
    if not templates:
        await message.answer("У вас нет сохранённых шаблонов.")
        return
    await state.update_data(user_id=user_id, templates=templates)
    await state.set_state(TemplateStates.waiting_choice)
    await message.answer(format_template_list(templates))


@router.message(TemplateStates.waiting_choice)
async def templates_choose(message: Message, state: FSMContext):
    text = message.text.strip().lower()
    if text == "отмена":
        await state.clear()
        await message.answer("Отменено.")
        return
    if not text.isdigit():
        await message.answer("Отправьте номер шаблона из списка, или «отмена».")
        return

    data = await state.get_data()
    templates = data["templates"]
    index = int(text)
    if index < 1 or index > len(templates):
        await message.answer("Такого номера нет в списке.")
        return

    template = templates[index - 1]
    await state.update_data(
        target_template_id=template["template_id"],
        target_template_name=template["name"]
    )
    await state.set_state(TemplateStates.waiting_action)
    exercises = db.get_template_exercises(template["template_id"])
    await message.answer(format_template_view(template["name"], exercises))


@router.message(TemplateStates.waiting_action)
async def templates_action(message: Message, state: FSMContext):
    text = message.text.strip()
    lower = text.lower()
    data = await state.get_data()
    template_id = data["target_template_id"]
    user_id = data["user_id"]

    if lower == "отмена":
        await state.clear()
        await message.answer("Отменено.")
        return

    if lower == "удалить шаблон":
        db.delete_template(template_id)
        await state.clear()
        await message.answer("Шаблон удалён.")
        return

    if lower.startswith("переименовать:"):
        new_name = text.split(":", 1)[1].strip()
        if not new_name:
            await message.answer("Укажите новое название после двоеточия.")
            return
        if db.template_name_exists(user_id, new_name):
            await message.answer("Шаблон с таким названием уже есть. Введите другое.")
            return
        db.rename_template(template_id, new_name)
        await state.update_data(target_template_name=new_name)
        exercises = db.get_template_exercises(template_id)
        await message.answer(format_template_view(new_name, exercises))
        return

    if lower.startswith("добавить:"):
        exercise_name = text.split(":", 1)[1].strip()
        if not exercise_name:
            await message.answer("Укажите название упражнения после двоеточия.")
            return
        exercise_id = db.get_or_create_exercise(exercise_name)
        next_position = db.get_next_template_position(template_id)
        db.add_template_exercise(template_id, exercise_id, next_position)
        exercises = db.get_template_exercises(template_id)
        await message.answer(format_template_view(data["target_template_name"], exercises))
        return

    if lower.startswith("удалить "):
        number_str = lower.replace("удалить ", "").strip()
        if not number_str.isdigit():
            await message.answer("Формат: «удалить 2»")
            return
        db.remove_template_exercise(template_id, int(number_str))
        exercises = db.get_template_exercises(template_id)
        if exercises:
            await message.answer(format_template_view(data["target_template_name"], exercises))
        else:
            await message.answer("Упражнение удалено. В шаблоне больше ничего нет.")
            await state.clear()
        return

    await message.answer(
        "Не понял. Напишите «удалить N», «добавить: Название», "
        "«переименовать: Название», «удалить шаблон» или «отмена»."
    )


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
        BotCommand(command="templates", description="Управление шаблонами тренировок"),
        BotCommand(command="edit", description="Изменить тренировку"),
        BotCommand(command="delete", description="Удалить тренировку"),
    ])

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())