from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Token(Base):
    __tablename__ = "tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    athlete_id: Mapped[int] = mapped_column(Integer, nullable=False)
    athlete_name: Mapped[str] = mapped_column(String(200), default="")
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[int] = mapped_column(Integer, nullable=False)


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    athlete_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(300), default="")
    sport_type: Mapped[str] = mapped_column(String(50), default="Run")
    start_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    distance_m: Mapped[float] = mapped_column(Float, default=0.0)
    moving_time_s: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_time_s: Mapped[int] = mapped_column(Integer, default=0)
    avg_heartrate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_heartrate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_speed: Mapped[float] = mapped_column(Float, default=0.0)
    avg_cadence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_elevation: Mapped[float] = mapped_column(Float, default=0.0)
    gear_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Analysis results
    zone1_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    zone2_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    zone3_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    zone4_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    zone5_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pace_cv: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    flags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    analyzed: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_streams: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    coach_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # v2: Effort score and plan matching
    effort_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    matched_workout_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # v3: Zone time in seconds for Relative Effort breakdown
    zone1_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    zone2_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    zone3_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    zone4_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    zone5_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class Shoe(Base):
    __tablename__ = "shoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strava_gear_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    total_distance_m: Mapped[float] = mapped_column(Float, default=0.0)
    warn_distance_m: Mapped[float] = mapped_column(Float, default=700_000.0)
    retire_distance_m: Mapped[float] = mapped_column(Float, default=800_000.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class TrainingPlanWeek(Base):
    __tablename__ = "training_plan_weeks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    long_run_km: Mapped[float] = mapped_column(Float, default=0.0)
    interval_description: Mapped[str] = mapped_column(String(300), default="")
    easy_runs_km: Mapped[float] = mapped_column(Float, default=0.0)
    total_target_km: Mapped[float] = mapped_column(Float, default=0.0)
    phase: Mapped[str] = mapped_column(String(20), default="build")
    completed_km: Mapped[float] = mapped_column(Float, default=0.0)
    completed_runs: Mapped[int] = mapped_column(Integer, default=0)


class PlannedWorkout(Base):
    __tablename__ = "planned_workouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    week_id: Mapped[int] = mapped_column(Integer, nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=monday
    workout_date: Mapped[date] = mapped_column(Date, nullable=False)
    workout_type: Mapped[str] = mapped_column(String(20), nullable=False)  # long_run/interval/easy/rest
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    target_distance_km: Mapped[float] = mapped_column(Float, default=0.0)
    target_pace_range: Mapped[str] = mapped_column(String(30), default="")
    target_hr_zone: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    matched_activity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
