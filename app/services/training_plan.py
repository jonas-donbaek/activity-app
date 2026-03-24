from datetime import date, timedelta
from typing import List, Tuple

from app.models import PlannedWorkout, TrainingPlanWeek


def generate_training_plan(
    start_date: date = date(2026, 3, 16),  # Monday after today (March 15)
    race_date: date = date(2026, 6, 14),
) -> list[TrainingPlanWeek]:
    """Generate a progressive half marathon training plan.

    Structure:
    - Weeks 1-4: Base building
    - Weeks 5-9: Build phase (increase distance + intensity)
    - Weeks 10-11: Peak phase
    - Weeks 12-13: Taper phase
    """
    total_days = (race_date - start_date).days
    total_weeks = total_days // 7
    if total_weeks < 4:
        total_weeks = max(total_weeks, 2)

    weeks: list[TrainingPlanWeek] = []

    for week_num in range(1, total_weeks + 1):
        week_start = start_date + timedelta(weeks=week_num - 1)
        week_end = week_start + timedelta(days=6)
        phase, long_run, interval, easy, total = _week_prescription(week_num, total_weeks)

        weeks.append(
            TrainingPlanWeek(
                week_number=week_num,
                start_date=week_start,
                end_date=week_end,
                phase=phase,
                long_run_km=long_run,
                interval_description=interval,
                easy_runs_km=easy,
                total_target_km=total,
            )
        )

    return weeks


def _week_prescription(
    week: int, total_weeks: int
) -> tuple[str, float, str, float, float]:
    """Return (phase, long_run_km, interval_desc, easy_runs_km, total_target_km)."""

    # Determine phase
    taper_start = total_weeks - 1  # Last 2 weeks are taper
    peak_start = taper_start - 2   # 2 weeks of peak before taper
    build_start = 5                 # Weeks 5+ are build

    if week >= taper_start:
        return _taper_week(week, total_weeks)
    elif week >= peak_start:
        return _peak_week(week)
    elif week >= build_start:
        return _build_week(week)
    else:
        return _base_week(week)


def _base_week(week: int) -> tuple[str, float, str, float, float]:
    """Base building phase: gentle progression."""
    long_runs = {1: 8, 2: 9, 3: 10, 4: 11}
    long_run = long_runs.get(week, 10)

    intervals = {
        1: "4x400m hurtigt med 90s joggepause",
        2: "5x400m hurtigt med 90s joggepause",
        3: "3x1000m i tempo-pace med 2min pause",
        4: "4x1000m i tempo-pace med 2min pause",
    }
    interval = intervals.get(week, "4x400m med 90s pause")

    easy = round(long_run * 0.8, 1)  # 2 easy runs totaling ~80% of long run
    total = round(long_run + easy + 5, 1)  # +5 for interval session

    return ("base", long_run, interval, easy, total)


def _build_week(week: int) -> tuple[str, float, str, float, float]:
    """Build phase: increase long run and intensity."""
    long_runs = {5: 12, 6: 13, 7: 14, 8: 15, 9: 16}
    long_run = long_runs.get(week, 14)

    intervals = {
        5: "5x800m i Zone 4 med 2min joggepause",
        6: "3x1600m i Zone 4 med 3min pause",
        7: "6x800m i Zone 4 med 90s pause",
        8: "4x1600m i Zone 4 med 2min pause",
        9: "2x3000m i tempo (Zone 3-4) med 3min pause",
    }
    interval = intervals.get(week, "5x800m i Zone 4")

    easy = round(long_run * 0.7, 1)
    total = round(long_run + easy + 7, 1)  # +7 for harder interval

    return ("build", long_run, interval, easy, total)


def _peak_week(week: int) -> tuple[str, float, str, float, float]:
    """Peak phase: highest volume, maintain intensity."""
    long_run = 18.0

    intervals = {
        10: "5x1000m i Zone 4 med 2min pause",
        11: "3x2000m i tempo-pace med 3min pause",
    }
    # Use week number modulo for flexibility
    interval = intervals.get(week, "5x1000m i Zone 4 med 2min pause")

    easy = 12.0
    total = round(long_run + easy + 8, 1)

    return ("peak", long_run, interval, easy, total)


def _taper_week(
    week: int, total_weeks: int
) -> tuple[str, float, str, float, float]:
    """Taper phase: reduce volume, maintain some intensity."""
    weeks_to_race = total_weeks - week + 1

    if weeks_to_race == 2:
        # 2 weeks out: 30% reduction
        return (
            "taper",
            12.0,
            "3x800m i Zone 4 med 2min pause - hold tempoet, sænk mængden",
            8.0,
            25.0,
        )
    else:
        # Race week: minimal volume
        return (
            "taper",
            5.0,
            "4x200m strides - hold benene friske 🏁",
            4.0,
            12.0,
        )


# --- Daily Workout Generation ---

# Pace targets based on Jonas' data (avg HR 159 at ~6:00/km pace)
# Zone 2 pace estimated ~6:45-7:15/km, Interval ~4:30-5:00/km
PACE_TARGETS = {
    "easy": ("6:45", "7:15"),
    "long_run": ("6:30", "7:00"),
    "interval": ("4:30", "5:00"),
    "tempo": ("5:15", "5:45"),
    "recovery": ("7:30", "8:00"),
}


def generate_daily_workouts(week: TrainingPlanWeek) -> List[PlannedWorkout]:
    """Generate daily workout plan for a given training week.

    Schedule:
    - Monday: Rest
    - Tuesday: Easy Run
    - Wednesday: Rest
    - Thursday: Interval/Tempo
    - Friday: Rest
    - Saturday: Long Run
    - Sunday: Easy Run (optional, based on phase)
    """
    workouts = []
    ws = week.start_date  # Monday

    # Monday - Rest
    workouts.append(PlannedWorkout(
        week_id=week.id or 0,
        day_of_week=0,
        workout_date=ws,
        workout_type="rest",
        title="Hviledag",
        description="Restituering. Stræk ud, foam roll, eller gå en tur.",
        target_distance_km=0,
        target_pace_range="",
        target_hr_zone=None,
    ))

    # Tuesday - Easy Run
    easy_km = round(week.easy_runs_km * 0.5, 1) if week.easy_runs_km else 5.0
    workouts.append(PlannedWorkout(
        week_id=week.id or 0,
        day_of_week=1,
        workout_date=ws + timedelta(days=1),
        workout_type="easy",
        title="Easy Run",
        description=f"{easy_km} km i Zone 2. Hold pulsen UNDER 141 bpm.\n"
                    f"Pace-mål: {PACE_TARGETS['easy'][0]}-{PACE_TARGETS['easy'][1]}/km.\n"
                    f"Tænk: 'Kan jeg føre en samtale?' - hvis ja, er tempoet rigtigt.",
        target_distance_km=easy_km,
        target_pace_range=f"{PACE_TARGETS['easy'][0]}-{PACE_TARGETS['easy'][1]}",
        target_hr_zone=2,
    ))

    # Wednesday - Rest
    workouts.append(PlannedWorkout(
        week_id=week.id or 0,
        day_of_week=2,
        workout_date=ws + timedelta(days=2),
        workout_type="rest",
        title="Hviledag",
        description="Restituering. Styrketræning for benene er fint.",
        target_distance_km=0,
        target_pace_range="",
        target_hr_zone=None,
    ))

    # Thursday - Interval/Tempo
    workouts.append(PlannedWorkout(
        week_id=week.id or 0,
        day_of_week=3,
        workout_date=ws + timedelta(days=3),
        workout_type="interval",
        title="Interval",
        description=f"{week.interval_description}\n"
                    f"Opvarmning: 10 min rolig jogging (Zone 1-2).\n"
                    f"Interval-pace: {PACE_TARGETS['interval'][0]}-{PACE_TARGETS['interval'][1]}/km.\n"
                    f"Nedvarmning: 10 min rolig jogging.",
        target_distance_km=7.0,
        target_pace_range=f"{PACE_TARGETS['interval'][0]}-{PACE_TARGETS['interval'][1]}",
        target_hr_zone=4,
    ))

    # Friday - Rest
    workouts.append(PlannedWorkout(
        week_id=week.id or 0,
        day_of_week=4,
        workout_date=ws + timedelta(days=4),
        workout_type="rest",
        title="Hviledag",
        description="Hvil før weekendens long run. Let gåtur er OK.",
        target_distance_km=0,
        target_pace_range="",
        target_hr_zone=None,
    ))

    # Saturday - Long Run
    workouts.append(PlannedWorkout(
        week_id=week.id or 0,
        day_of_week=5,
        workout_date=ws + timedelta(days=5),
        workout_type="long_run",
        title="Long Run",
        description=f"{week.long_run_km} km i STRENGT Zone 2.\n"
                    f"Pace-mål: {PACE_TARGETS['long_run'][0]}-{PACE_TARGETS['long_run'][1]}/km.\n"
                    f"Hold pulsen under 141 bpm HELE vejen.\n"
                    f"Start langsomt - det er bedre at slutte stærkt end at gå død.",
        target_distance_km=week.long_run_km,
        target_pace_range=f"{PACE_TARGETS['long_run'][0]}-{PACE_TARGETS['long_run'][1]}",
        target_hr_zone=2,
    ))

    # Sunday - Easy Run or Rest (depending on phase)
    if week.phase in ("build", "peak"):
        easy_km_sun = round(week.easy_runs_km * 0.5, 1) if week.easy_runs_km else 4.0
        workouts.append(PlannedWorkout(
            week_id=week.id or 0,
            day_of_week=6,
            workout_date=ws + timedelta(days=6),
            workout_type="easy",
            title="Recovery Run",
            description=f"{easy_km_sun} km recovery i Zone 1-2.\n"
                        f"Pace-mål: {PACE_TARGETS['recovery'][0]}-{PACE_TARGETS['recovery'][1]}/km.\n"
                        f"Meget langsomt - dette er aktiv restitution.",
            target_distance_km=easy_km_sun,
            target_pace_range=f"{PACE_TARGETS['recovery'][0]}-{PACE_TARGETS['recovery'][1]}",
            target_hr_zone=1,
        ))
    else:
        workouts.append(PlannedWorkout(
            week_id=week.id or 0,
            day_of_week=6,
            workout_date=ws + timedelta(days=6),
            workout_type="rest",
            title="Hviledag",
            description="God restitution efter gårsdagens long run.",
            target_distance_km=0,
            target_pace_range="",
            target_hr_zone=None,
        ))

    return workouts
