"""Build daily_metrics rollups from parsed health data."""

from __future__ import annotations

import sqlite3

SLEEP_DEEP = {"HKCategoryValueSleepAnalysisAsleepDeep", "AsleepDeep"}
SLEEP_REM = {"HKCategoryValueSleepAnalysisAsleepREM", "AsleepREM"}
SLEEP_CORE = {"HKCategoryValueSleepAnalysisAsleepCore", "AsleepCore", "HKCategoryValueSleepAnalysisAsleepUnspecified", "AsleepUnspecified"}
SLEEP_AWAKE = {"HKCategoryValueSleepAnalysisAwake", "Awake", "HKCategoryValueSleepAnalysisInBed", "InBed"}


def _minutes_between(start_at: str, end_at: str) -> float:
    from datetime import datetime

    fmt_variants = (
        lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")),
        lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M:%S %z"),
    )
    for parser in fmt_variants:
        try:
            start = parser(start_at)
            end = parser(end_at)
            return max(0.0, (end - start).total_seconds() / 60.0)
        except ValueError:
            continue
    return 0.0


def build_daily_metrics(conn: sqlite3.Connection) -> int:
    """Populate daily_metrics from health_samples, sleep, and workouts."""
    dates = conn.execute(
        """
        SELECT DISTINCT local_date FROM (
            SELECT local_date FROM health_samples
            UNION SELECT local_date FROM sleep_sessions
            UNION SELECT local_date FROM workouts
            UNION SELECT local_date FROM daily_metrics
        )
        WHERE local_date IS NOT NULL
        ORDER BY local_date
        """
    ).fetchall()
    for row in dates:
        conn.execute(
            "INSERT OR IGNORE INTO daily_metrics (local_date) VALUES (?)",
            (row["local_date"],),
        )

    # Latest value per day for key metrics
    for record_type, column in (
        ("HKQuantityTypeIdentifierRestingHeartRate", "resting_hr"),
        ("HKQuantityTypeIdentifierHeartRateVariabilitySDNN", "hrv_sdnn"),
        ("HKQuantityTypeIdentifierVO2Max", "vo2_max"),
        ("HKQuantityTypeIdentifierBodyMass", "body_mass_kg"),
    ):
        conn.execute(
            f"""
            UPDATE daily_metrics SET {column} = (
                SELECT hs.value_num FROM health_samples hs
                WHERE hs.record_type = ? AND hs.local_date = daily_metrics.local_date
                ORDER BY hs.start_at DESC LIMIT 1
            )
            WHERE EXISTS (
                SELECT 1 FROM health_samples hs
                WHERE hs.record_type = ? AND hs.local_date = daily_metrics.local_date
            )
            """,
            (record_type, record_type),
        )

    # Sleep aggregation by end date (sleep attributed to wake day)
    sleep_rows = conn.execute(
        "SELECT start_at, end_at, value FROM sleep_sessions"
    ).fetchall()

    sleep_by_day: dict[str, dict[str, float]] = {}
    for row in sleep_rows:
        from datetime import datetime

        try:
            end = datetime.fromisoformat(row["end_at"].replace("Z", "+00:00"))
        except ValueError:
            end = datetime.strptime(row["end_at"], "%Y-%m-%d %H:%M:%S %z")
        day = end.date().isoformat()
        mins = _minutes_between(row["start_at"], row["end_at"])
        bucket = sleep_by_day.setdefault(
            day,
            {"total": 0.0, "deep": 0.0, "rem": 0.0, "core": 0.0, "awake": 0.0},
        )
        val = row["value"] or ""
        if val in SLEEP_DEEP:
            bucket["deep"] += mins
            bucket["total"] += mins
        elif val in SLEEP_REM:
            bucket["rem"] += mins
            bucket["total"] += mins
        elif val in SLEEP_CORE:
            bucket["core"] += mins
            bucket["total"] += mins
        elif val in SLEEP_AWAKE:
            bucket["awake"] += mins
        else:
            bucket["total"] += mins

    for day, data in sleep_by_day.items():
        conn.execute(
            """
            INSERT INTO daily_metrics (
                local_date, sleep_total_min, sleep_deep_min,
                sleep_rem_min, sleep_core_min, sleep_awake_min
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(local_date) DO UPDATE SET
                sleep_total_min = excluded.sleep_total_min,
                sleep_deep_min = excluded.sleep_deep_min,
                sleep_rem_min = excluded.sleep_rem_min,
                sleep_core_min = excluded.sleep_core_min,
                sleep_awake_min = excluded.sleep_awake_min
            """,
            (
                day,
                data["total"],
                data["deep"],
                data["rem"],
                data["core"],
                data["awake"],
            ),
        )

    # Backfill workout distance/energy from statistics when not on the Workout element
    conn.execute(
        """
        UPDATE workouts SET distance_m = (
            SELECT CASE COALESCE(ws.unit, 'mi')
                WHEN 'mi' THEN ws.sum_value * 1609.344
                WHEN 'km' THEN ws.sum_value * 1000.0
                ELSE ws.sum_value
            END
            FROM workout_statistics ws
            WHERE ws.workout_id = workouts.id
              AND ws.stat_type IN (
                'HKQuantityTypeIdentifierDistanceWalkingRunning',
                'HKQuantityTypeIdentifierDistanceCycling'
              )
            LIMIT 1
        )
        WHERE distance_m IS NULL OR distance_m < 100
        """
    )
    conn.execute(
        """
        UPDATE workouts SET energy_kcal = (
            SELECT ws.sum_value FROM workout_statistics ws
            WHERE ws.workout_id = workouts.id
              AND ws.stat_type = 'HKQuantityTypeIdentifierActiveEnergyBurned'
            LIMIT 1
        )
        WHERE energy_kcal IS NULL
        """
    )

    # Workout counts per day
    conn.execute(
        """
        UPDATE daily_metrics SET
            workout_count = (
                SELECT COUNT(*) FROM workouts w
                WHERE w.local_date = daily_metrics.local_date
            ),
            run_count = (
                SELECT COUNT(*) FROM workouts w
                WHERE w.local_date = daily_metrics.local_date
                  AND w.activity_type = 'HKWorkoutActivityTypeRunning'
            ),
            run_distance_m = COALESCE((
                SELECT SUM(w.distance_m) FROM workouts w
                WHERE w.local_date = daily_metrics.local_date
                  AND w.activity_type = 'HKWorkoutActivityTypeRunning'
            ), 0),
            run_duration_sec = COALESCE((
                SELECT SUM(w.duration_sec) FROM workouts w
                WHERE w.local_date = daily_metrics.local_date
                  AND w.activity_type = 'HKWorkoutActivityTypeRunning'
            ), 0)
        """
    )

    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM daily_metrics").fetchone()[0]
