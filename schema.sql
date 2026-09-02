create table dim_user (
    user_id      serial primary key,
    telegram_id  bigint unique,
    name         text not null
);

create table dim_exercise (
    exercise_id   serial primary key,
    name          text not null unique,
    muscle_group  text
);

create table dim_workout (
    workout_id  serial primary key,
    user_id     int references dim_user(user_id),
    started_at  timestamp not null,
    notes       text
);

create table fact_workout_set (
    set_id       serial primary key,
    workout_id   int references dim_workout(workout_id),
    exercise_id  int references dim_exercise(exercise_id),
    set_number   int not null,
    weight_kg    numeric(6,2),
    reps         int not null,
    rpe          int check (rpe between 1 and 10)
);