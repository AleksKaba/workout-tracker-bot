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