import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    return psycopg2.connect(os.getenv("DATABASE_URL"))


def get_or_create_user(telegram_id, telegram_name):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("select user_id from dim_user where telegram_id = %s", (telegram_id,))
    row = cursor.fetchone()
    if row:
        user_id = row[0]
    else:
        cursor.execute(
            "insert into dim_user (telegram_id, name) values (%s, %s) returning user_id",
            (telegram_id, telegram_name)
        )
        user_id = cursor.fetchone()[0]
        conn.commit()
    conn.close()
    return user_id


def get_or_create_exercise(name):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("select exercise_id from dim_exercise where name = %s", (name,))
    row = cursor.fetchone()
    if row:
        exercise_id = row[0]
    else:
        cursor.execute(
            "insert into dim_exercise (name) values (%s) returning exercise_id",
            (name,)
        )
        exercise_id = cursor.fetchone()[0]
        conn.commit()
    conn.close()
    return exercise_id


def create_workout(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "insert into dim_workout (user_id, started_at) values (%s, now()) returning workout_id",
        (user_id,)
    )
    workout_id = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    return workout_id


def insert_set(workout_id, exercise_id, set_number, weight_kg, reps):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """insert into fact_workout_set
           (workout_id, exercise_id, set_number, weight_kg, reps)
           values (%s, %s, %s, %s, %s)""",
        (workout_id, exercise_id, set_number, weight_kg, reps)
    )
    conn.commit()
    conn.close()


def save_workout_notes(workout_id, notes):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "update dim_workout set notes = %s where workout_id = %s",
        (notes, workout_id)
    )
    conn.commit()
    conn.close()


def get_workout_history(user_id, limit=10):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """select workout_id, started_at, notes
           from dim_workout
           where user_id = %s
           order by started_at desc
           limit %s""",
        (user_id, limit)
    )
    workouts = cursor.fetchall()

    history = []
    for workout_id, started_at, notes in workouts:
        cursor.execute(
            """select e.name, s.set_number, s.weight_kg, s.reps
               from fact_workout_set s
               join dim_exercise e on s.exercise_id = e.exercise_id
               where s.workout_id = %s
               order by e.name, s.set_number""",
            (workout_id,)
        )
        rows = cursor.fetchall()
        exercises = {}
        for name, set_number, weight, reps in rows:
            exercises.setdefault(name, []).append((set_number, weight, reps))
        history.append({
            "started_at": started_at,
            "notes": notes,
            "exercises": exercises
        })
    conn.close()
    return history


def get_recent_workouts(user_id, limit=10):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """select workout_id, started_at
           from dim_workout
           where user_id = %s
           order by started_at desc
           limit %s""",
        (user_id, limit)
    )
    workouts = cursor.fetchall()

    result = []
    for workout_id, started_at in workouts:
        cursor.execute(
            """select distinct e.name
               from fact_workout_set s
               join dim_exercise e on s.exercise_id = e.exercise_id
               where s.workout_id = %s
               order by e.name""",
            (workout_id,)
        )
        names = [row[0] for row in cursor.fetchall()]
        result.append({
            "workout_id": workout_id,
            "started_at": started_at,
            "exercises": names
        })
    conn.close()
    return result


def delete_workout(workout_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("delete from fact_workout_set where workout_id = %s", (workout_id,))
    cursor.execute("delete from dim_workout where workout_id = %s", (workout_id,))
    conn.commit()
    conn.close()


def get_workout_exercises(workout_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """select e.exercise_id, e.name, count(*) as set_count
           from fact_workout_set s
           join dim_exercise e on s.exercise_id = e.exercise_id
           where s.workout_id = %s
           group by e.exercise_id, e.name
           order by e.name""",
        (workout_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [{"exercise_id": r[0], "name": r[1], "set_count": r[2]} for r in rows]


def get_exercise_sets(workout_id, exercise_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """select set_id, set_number, weight_kg, reps
           from fact_workout_set
           where workout_id = %s and exercise_id = %s
           order by set_number""",
        (workout_id, exercise_id)
    )
    rows = cursor.fetchall()
    conn.close()
    return [{"set_id": r[0], "set_number": r[1], "weight_kg": r[2], "reps": r[3]} for r in rows]


def update_set(set_id, weight_kg, reps):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "update fact_workout_set set weight_kg = %s, reps = %s where set_id = %s",
        (weight_kg, reps, set_id)
    )
    conn.commit()
    conn.close()


def delete_set(set_id, workout_id, exercise_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("delete from fact_workout_set where set_id = %s", (set_id,))
    cursor.execute(
        """select set_id from fact_workout_set
           where workout_id = %s and exercise_id = %s
           order by set_number""",
        (workout_id, exercise_id)
    )
    remaining = cursor.fetchall()
    for i, (remaining_set_id,) in enumerate(remaining, start=1):
        cursor.execute(
            "update fact_workout_set set set_number = %s where set_id = %s",
            (i, remaining_set_id)
        )
    conn.commit()
    conn.close()


def get_next_set_number(workout_id, exercise_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "select coalesce(max(set_number), 0) + 1 from fact_workout_set where workout_id = %s and exercise_id = %s",
        (workout_id, exercise_id)
    )
    result = cursor.fetchone()[0]
    conn.close()
    return result