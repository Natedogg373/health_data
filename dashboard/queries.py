"""Query training.db for dashboard charts and tables."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _one(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> dict | None:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def fetch_dashboard_data(conn: sqlite3.Connection, days: int = 365) -> dict:
    """Return all dashboard payload sections."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    profile = _one(conn, "SELECT date_of_birth, biological_sex, export_date FROM user_profile WHERE id = 1")
    date_range = _one(
        conn,
        """
        SELECT MIN(local_date) AS start_date, MAX(local_date) AS end_date
        FROM daily_metrics
        """,
    )

    run_totals = _one(
        conn,
        """
        SELECT
            COUNT(*) AS run_count,
            ROUND(SUM(distance_m) / 1609.344, 1) AS total_miles,
            ROUND(SUM(duration_sec) / 3600.0, 1) AS total_hours
        FROM workouts
        WHERE activity_type = 'HKWorkoutActivityTypeRunning'
          AND distance_m IS NOT NULL AND distance_m > 0
        """,
    )

    workout_totals = _one(conn, "SELECT COUNT(*) AS workout_count FROM workouts")

    latest_recovery = _one(
        conn,
        """
        SELECT resting_hr, hrv_sdnn, vo2_max, body_mass_kg, local_date
        FROM daily_metrics
        WHERE resting_hr IS NOT NULL OR hrv_sdnn IS NOT NULL OR vo2_max IS NOT NULL
        ORDER BY local_date DESC
        LIMIT 1
        """,
    )

    weekly_runs = _rows(
        conn,
        """
        SELECT week, run_count, ROUND(run_distance_m / 1609.344, 2) AS miles,
               ROUND(run_duration_sec / 3600.0, 2) AS hours
        FROM v_weekly_training
        WHERE run_count > 0
        ORDER BY week
        """,
    )

    recent_runs = _rows(
        conn,
        """
        SELECT
            w.local_date,
            ROUND(w.distance_m / 1609.344, 2) AS miles,
            ROUND(w.duration_sec / 60.0, 1) AS duration_min,
            ROUND(w.duration_sec / NULLIF(w.distance_m / 1609.344, 0) / 60.0, 1) AS pace_min_per_mile,
            ws.avg_value AS avg_hr,
            ws.max_value AS max_hr,
            w.energy_kcal,
            CASE WHEN w.route_file IS NOT NULL THEN 1 ELSE 0 END AS has_route
        FROM workouts w
        LEFT JOIN workout_statistics ws
          ON ws.workout_id = w.id
         AND ws.stat_type = 'HKQuantityTypeIdentifierHeartRate'
        WHERE w.activity_type = 'HKWorkoutActivityTypeRunning'
          AND w.distance_m IS NOT NULL AND w.distance_m > 0
        ORDER BY w.start_at DESC
        LIMIT 30
        """,
    )

    daily_recovery = _rows(
        conn,
        """
        SELECT
            local_date,
            resting_hr,
            hrv_sdnn,
            vo2_max,
            ROUND(sleep_total_min / 60.0, 2) AS sleep_hours,
            ROUND(sleep_deep_min / 60.0, 2) AS sleep_deep_hours,
            ROUND(sleep_rem_min / 60.0, 2) AS sleep_rem_hours,
            body_mass_kg
        FROM daily_metrics
        WHERE local_date >= ?
          AND (resting_hr IS NOT NULL OR hrv_sdnn IS NOT NULL
               OR vo2_max IS NOT NULL OR sleep_total_min IS NOT NULL)
        ORDER BY local_date
        """,
        (cutoff,),
    )

    daily_activity = _rows(
        conn,
        """
        SELECT
            dm.local_date,
            dm.steps,
            dm.active_energy_kcal,
            dm.run_count,
            ROUND(dm.run_distance_m / 1609.344, 2) AS run_miles,
            a.exercise_min,
            a.exercise_goal,
            a.stand_hours,
            a.stand_goal,
            a.active_energy_goal
        FROM daily_metrics dm
        LEFT JOIN activity_summaries a ON a.local_date = dm.local_date
        WHERE dm.local_date >= ?
        ORDER BY dm.local_date
        """,
        (cutoff,),
    )

    workout_types = _rows(
        conn,
        """
        SELECT
            activity_type,
            COUNT(*) AS count,
            ROUND(SUM(distance_m) / 1609.344, 1) AS miles,
            ROUND(SUM(duration_sec) / 3600.0, 1) AS hours
        FROM workouts
        GROUP BY activity_type
        ORDER BY count DESC
        """,
    )

    monthly_runs = _rows(
        conn,
        """
        SELECT
            strftime('%Y-%m', local_date) AS month,
            COUNT(*) AS run_count,
            ROUND(SUM(distance_m) / 1609.344, 1) AS miles
        FROM workouts
        WHERE activity_type = 'HKWorkoutActivityTypeRunning'
          AND distance_m IS NOT NULL
        GROUP BY month
        ORDER BY month
        """,
    )

    return {
        "meta": {
            "generated_at": date.today().isoformat(),
            "chart_days": days,
            "export_date": profile["export_date"] if profile else None,
            "data_start": date_range["start_date"] if date_range else None,
            "data_end": date_range["end_date"] if date_range else None,
        },
        "overview": {
            "run_count": run_totals["run_count"] if run_totals else 0,
            "total_miles": run_totals["total_miles"] if run_totals else 0,
            "total_hours": run_totals["total_hours"] if run_totals else 0,
            "workout_count": workout_totals["workout_count"] if workout_totals else 0,
            "latest_resting_hr": latest_recovery["resting_hr"] if latest_recovery else None,
            "latest_hrv": latest_recovery["hrv_sdnn"] if latest_recovery else None,
            "latest_vo2": latest_recovery["vo2_max"] if latest_recovery else None,
            "latest_recovery_date": latest_recovery["local_date"] if latest_recovery else None,
            "weekly_miles": weekly_runs[-26:],
        },
        "running": {
            "weekly": weekly_runs,
            "monthly": monthly_runs,
            "recent_runs": recent_runs,
        },
        "recovery": {
            "daily": daily_recovery,
        },
        "activity": {
            "daily": daily_activity,
        },
        "workouts": {
            "by_type": workout_types,
        },
    }
