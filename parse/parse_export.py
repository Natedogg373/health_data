"""Stream-parse Apple Health export.xml into SQLite."""

from __future__ import annotations

import hashlib
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from parse.config import (
    CATEGORY_RECORD_TYPES,
    DAILY_AGGREGATE_TYPES,
    EXPORT_XML,
    SAMPLE_RECORD_TYPES,
)
from parse.db import get_or_create_source, init_schema

# In-memory daily accumulators (cleared per import)
_daily_steps: dict[str, float] = {}
_daily_active_energy: dict[str, float] = {}


def parse_apple_datetime(value: str) -> datetime:
    """Parse Apple Health timestamps like '2023-12-14 17:49:51 -0500'."""
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S %z")


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def local_date(dt: datetime) -> str:
    return dt.date().isoformat()


def workout_id(start: str, end: str, activity: str, source: str) -> str:
    raw = f"{start}|{end}|{activity}|{source}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def duration_to_seconds(value: str | None, unit: str | None) -> float | None:
    if value is None:
        return None
    v = float(value)
    if unit == "min":
        return v * 60.0
    if unit == "hr":
        return v * 3600.0
    if unit == "s":
        return v
    return v


def distance_to_meters(value: str | None, unit: str | None) -> float | None:
    if value is None:
        return None
    v = float(value)
    if unit in ("mi", "mile", "miles"):
        return v * 1609.344
    if unit in ("km", "kilometer", "kilometers"):
        return v * 1000.0
    if unit in ("m", "meter", "meters"):
        return v
    return v


def energy_to_kcal(value: str | None, unit: str | None) -> float | None:
    if value is None:
        return None
    v = float(value)
    if unit in ("Cal", "kcal"):
        return v
    if unit == "kJ":
        return v / 4.184
    return v


def _process_me(conn: sqlite3.Connection, elem: ET.Element) -> None:
    export_date = conn.execute("SELECT export_date FROM user_profile WHERE id = 1").fetchone()
    conn.execute(
        """
        INSERT INTO user_profile (id, date_of_birth, biological_sex, blood_type, export_date)
        VALUES (1, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            date_of_birth = excluded.date_of_birth,
            biological_sex = excluded.biological_sex,
            blood_type = excluded.blood_type,
            export_date = COALESCE(excluded.export_date, user_profile.export_date)
        """,
        (
            elem.get("HKCharacteristicTypeIdentifierDateOfBirth"),
            elem.get("HKCharacteristicTypeIdentifierBiologicalSex"),
            elem.get("HKCharacteristicTypeIdentifierBloodType"),
            export_date["export_date"] if export_date else None,
        ),
    )


def _process_export_date(conn: sqlite3.Connection, elem: ET.Element) -> None:
    conn.execute(
        """
        INSERT INTO user_profile (id, export_date)
        VALUES (1, ?)
        ON CONFLICT(id) DO UPDATE SET export_date = excluded.export_date
        """,
        (elem.get("value"),),
    )


def _process_workout(conn: sqlite3.Connection, elem: ET.Element) -> None:
    source_name = elem.get("sourceName", "unknown")
    source_version = elem.get("sourceVersion")
    source_id = get_or_create_source(conn, source_name, source_version)

    start_dt = parse_apple_datetime(elem.get("startDate"))
    end_dt = parse_apple_datetime(elem.get("endDate"))
    activity = elem.get("workoutActivityType", "unknown")
    wid = workout_id(
        elem.get("startDate"), elem.get("endDate"), activity, source_name
    )

    route_file = None
    for ref in elem.iter("FileReference"):
        path = ref.get("path", "")
        if path:
            route_file = Path(path).name
            break

    distance_m = distance_to_meters(elem.get("totalDistance"), elem.get("totalDistanceUnit"))
    energy_kcal = energy_to_kcal(elem.get("totalEnergyBurned"), elem.get("totalEnergyBurnedUnit"))

    conn.execute(
        """
        INSERT OR REPLACE INTO workouts (
            id, activity_type, start_at, end_at, start_date_local, local_date,
            duration_sec, distance_m, energy_kcal,
            source_id, device, route_file, creation_date
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            wid,
            activity,
            to_iso(start_dt),
            to_iso(end_dt),
            elem.get("startDate"),
            local_date(start_dt),
            duration_to_seconds(elem.get("duration"), elem.get("durationUnit")),
            distance_m,
            energy_kcal,
            source_id,
            elem.get("device"),
            route_file,
            elem.get("creationDate"),
        ),
    )

    conn.execute("DELETE FROM workout_statistics WHERE workout_id = ?", (wid,))
    conn.execute("DELETE FROM workout_metadata WHERE workout_id = ?", (wid,))

    for child in elem:
        if child.tag == "WorkoutStatistics":
            stat_type = child.get("type")
            if not stat_type:
                continue
            sum_val = float(child.get("sum")) if child.get("sum") else None
            if distance_m is None and stat_type in (
                "HKQuantityTypeIdentifierDistanceWalkingRunning",
                "HKQuantityTypeIdentifierDistanceCycling",
            ):
                distance_m = distance_to_meters(
                    child.get("sum"), child.get("unit") or "mi"
                )
            if energy_kcal is None and stat_type == "HKQuantityTypeIdentifierActiveEnergyBurned":
                energy_kcal = energy_to_kcal(child.get("sum"), child.get("unit"))
            conn.execute(
                """
                INSERT INTO workout_statistics (
                    workout_id, stat_type, start_at, end_at,
                    sum_value, avg_value, min_value, max_value, unit
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    wid,
                    stat_type,
                    child.get("startDate"),
                    child.get("endDate"),
                    sum_val,
                    float(child.get("average")) if child.get("average") else None,
                    float(child.get("minimum")) if child.get("minimum") else None,
                    float(child.get("maximum")) if child.get("maximum") else None,
                    child.get("unit"),
                ),
            )
        elif child.tag == "MetadataEntry":
            key = child.get("key")
            if not key:
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO workout_metadata (workout_id, key, value)
                VALUES (?, ?, ?)
                """,
                (wid, key, child.get("value")),
            )


def _process_record(conn: sqlite3.Connection, elem: ET.Element) -> None:
    record_type = elem.get("type")
    if not record_type:
        return

    start_dt = parse_apple_datetime(elem.get("startDate"))
    end_dt = parse_apple_datetime(elem.get("endDate"))
    day = local_date(start_dt)
    source_id = get_or_create_source(
        conn, elem.get("sourceName", "unknown"), elem.get("sourceVersion")
    )

    if record_type in SAMPLE_RECORD_TYPES:
        value = elem.get("value")
        conn.execute(
            """
            INSERT INTO health_samples (
                record_type, start_at, end_at, local_date,
                value_num, value_text, unit, source_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_type,
                to_iso(start_dt),
                to_iso(end_dt),
                day,
                float(value) if value is not None else None,
                value,
                elem.get("unit"),
                source_id,
            ),
        )
    elif record_type in CATEGORY_RECORD_TYPES:
        conn.execute(
            """
            INSERT INTO sleep_sessions (start_at, end_at, local_date, value, source_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                to_iso(start_dt),
                to_iso(end_dt),
                day,
                elem.get("value", "unknown"),
                source_id,
            ),
        )
    elif record_type in DAILY_AGGREGATE_TYPES:
        value = float(elem.get("value", 0))
        if record_type == "HKQuantityTypeIdentifierStepCount":
            _daily_steps[day] = _daily_steps.get(day, 0.0) + value
        elif record_type == "HKQuantityTypeIdentifierActiveEnergyBurned":
            _daily_active_energy[day] = _daily_active_energy.get(day, 0.0) + value


def _process_workout_route(conn: sqlite3.Connection, elem: ET.Element) -> None:
    """Link a standalone WorkoutRoute element to the closest workout by start time."""
    route_file = None
    for ref in elem.iter("FileReference"):
        path = ref.get("path", "")
        if path:
            route_file = Path(path).name
            break
    if not route_file:
        return

    route_start = elem.get("startDate")
    if not route_start:
        return

    route_dt = parse_apple_datetime(route_start)
    day = local_date(route_dt)
    route_minutes = route_dt.hour * 60 + route_dt.minute

    candidates = conn.execute(
        """
        SELECT id, start_date_local FROM workouts
        WHERE local_date = ? AND (route_file IS NULL OR route_file = ?)
        """,
        (day, route_file),
    ).fetchall()

    best_id = None
    best_delta = 9999
    for cand in candidates:
        if not cand["start_date_local"]:
            continue
        wdt = parse_apple_datetime(cand["start_date_local"])
        w_minutes = wdt.hour * 60 + wdt.minute
        delta = abs(route_minutes - w_minutes)
        if delta < best_delta:
            best_delta = delta
            best_id = cand["id"]

    if best_id is not None and best_delta <= 15:
        conn.execute(
            "UPDATE workouts SET route_file = ? WHERE id = ?",
            (route_file, best_id),
        )


def _process_activity_summary(conn: sqlite3.Connection, elem: ET.Element) -> None:
    date_parts = elem.get("dateComponents", "")
    # dateComponents format: "2024-01-15 06:00:00 -0500" or similar
    try:
        day = parse_apple_datetime(date_parts).date().isoformat()
    except ValueError:
        day = date_parts[:10] if len(date_parts) >= 10 else date_parts

    conn.execute(
        """
        INSERT INTO activity_summaries (
            date_components, local_date,
            active_energy_kcal, active_energy_goal,
            exercise_min, exercise_goal,
            stand_hours, stand_goal
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(local_date) DO UPDATE SET
            date_components = excluded.date_components,
            active_energy_kcal = excluded.active_energy_kcal,
            active_energy_goal = excluded.active_energy_goal,
            exercise_min = excluded.exercise_min,
            exercise_goal = excluded.exercise_goal,
            stand_hours = excluded.stand_hours,
            stand_goal = excluded.stand_goal
        """,
        (
            date_parts,
            day,
            float(elem.get("activeEnergyBurned")) if elem.get("activeEnergyBurned") else None,
            float(elem.get("activeEnergyBurnedGoal")) if elem.get("activeEnergyBurnedGoal") else None,
            float(elem.get("appleExerciseTime")) if elem.get("appleExerciseTime") else None,
            float(elem.get("appleExerciseTimeGoal")) if elem.get("appleExerciseTimeGoal") else None,
            float(elem.get("appleStandHours")) if elem.get("appleStandHours") else None,
            float(elem.get("appleStandHoursGoal")) if elem.get("appleStandHoursGoal") else None,
        ),
    )


def _flush_daily_aggregates(conn: sqlite3.Connection) -> None:
    all_days = set(_daily_steps) | set(_daily_active_energy)
    for day in all_days:
        conn.execute(
            """
            INSERT INTO daily_metrics (local_date, steps, active_energy_kcal)
            VALUES (?, ?, ?)
            ON CONFLICT(local_date) DO UPDATE SET
                steps = COALESCE(excluded.steps, daily_metrics.steps),
                active_energy_kcal = COALESCE(excluded.active_energy_kcal, daily_metrics.active_energy_kcal)
            """,
            (
                day,
                _daily_steps.get(day),
                _daily_active_energy.get(day),
            ),
        )


def parse_export(
    conn: sqlite3.Connection,
    export_path: Path = EXPORT_XML,
    batch_size: int = 5000,
) -> dict[str, int]:
    """Stream-parse export.xml. Returns counts."""
    global _daily_steps, _daily_active_energy
    _daily_steps = {}
    _daily_active_energy = {}

    counts = {"records": 0, "workouts": 0, "activity_summaries": 0}
    pending = 0

    context = ET.iterparse(str(export_path), events=("end",))
    for _event, elem in context:
        tag = elem.tag
        if tag == "Me":
            _process_me(conn, elem)
            elem.clear()
        elif tag == "ExportDate":
            _process_export_date(conn, elem)
            elem.clear()
        elif tag == "Workout":
            _process_workout(conn, elem)
            counts["workouts"] += 1
            elem.clear()
        elif tag == "Record":
            _process_record(conn, elem)
            counts["records"] += 1
            elem.clear()
        elif tag == "WorkoutRoute":
            _process_workout_route(conn, elem)
            elem.clear()
        elif tag == "ActivitySummary":
            _process_activity_summary(conn, elem)
            counts["activity_summaries"] += 1
            elem.clear()
        # Do not clear WorkoutStatistics/MetadataEntry here — clearing
        # removes their attributes before the parent Workout is processed.

        pending += 1
        if pending >= batch_size:
            conn.commit()
            pending = 0

    _flush_daily_aggregates(conn)
    conn.commit()
    return counts


def run_parse(conn: sqlite3.Connection, fresh: bool = False) -> dict[str, int]:
    init_schema(conn, fresh=fresh)
    if fresh:
        conn.executescript(
            """
            DELETE FROM workout_statistics;
            DELETE FROM workout_metadata;
            DELETE FROM workouts;
            DELETE FROM health_samples;
            DELETE FROM sleep_sessions;
            DELETE FROM activity_summaries;
            DELETE FROM daily_metrics;
            DELETE FROM routes;
            DELETE FROM route_points;
            DELETE FROM user_profile;
            """
        )
        conn.commit()

    if not EXPORT_XML.exists():
        raise FileNotFoundError(f"Export not found: {EXPORT_XML}")

    return parse_export(conn)
