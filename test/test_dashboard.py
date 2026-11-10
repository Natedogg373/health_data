#!/usr/bin/env python3
"""Unit tests for training-progress dashboard queries."""

from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from dashboard.queries import (  # noqa: E402
    _cardio_from_runs,
    assign_zone,
    classify_week_status,
    fetch_dashboard_data,
    goal_score,
    is_easy,
    is_quality,
    qualifies_easy_aerobic,
)
from dashboard.shoes import (  # noqa: E402
    ShoeConfigError,
    classify_shoe_status,
    lifespan_stats,
    load_shoes_config,
    normalize_shoes_config,
    query_shoe_mileage,
)
from dashboard.training_config import (  # noqa: E402
    CARDIO_MAX_HR_CEILING,
    CARDIO_MIN_SAMPLES,
    EASY_HR_CEILING,
    GOAL_PACE_MAX,
    QUALITY_AVG_HR_MIN,
)
from parse.db import init_schema  # noqa: E402

AS_OF = date(2026, 11, 6)  # Friday
METERS = 1609.344
FORBIDDEN_CARDIO_SCORE_KEYS = (
    "median_sec_per_mi_per_bpm",
    "sec_per_mi_per_bpm",
    "efficiency",
    "effort_index",
    "economy",
    "score",
    "pace_gap_vs_930",
)


def assert_no_combined_cardio_score(test: unittest.TestCase, payload: dict) -> None:
    for key in FORBIDDEN_CARDIO_SCORE_KEYS:
        test.assertNotIn(key, payload)


def _workout(
    conn: sqlite3.Connection,
    wid: str,
    day: date,
    miles: float,
    activity: str = "HKWorkoutActivityTypeRunning",
    duration_sec: float | None = None,
) -> None:
    distance_m = miles * METERS if miles else miles
    start = f"{day.isoformat()}T12:00:00+00:00"
    end = f"{day.isoformat()}T13:00:00+00:00"
    conn.execute(
        """
        INSERT INTO workouts (
            id, activity_type, start_at, end_at, start_date_local, local_date,
            duration_sec, distance_m, energy_kcal, source_id, device, route_file, creation_date
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'Watch', NULL, ?)
        """,
        (
            wid,
            activity,
            start,
            end,
            f"{day.isoformat()} 07:00:00 -0500",
            day.isoformat(),
            duration_sec if duration_sec is not None else 3600,
            distance_m,
            100,
            start,
        ),
    )


def _run(
    conn: sqlite3.Connection,
    wid: str,
    day: date,
    miles: float,
    pace: float,
    avg_hr: float | None,
    max_hr: float | None = None,
) -> None:
    distance_m = miles * METERS
    duration_sec = pace * miles * 60
    start = f"{day.isoformat()}T12:00:00+00:00"
    end = f"{day.isoformat()}T13:00:00+00:00"
    conn.execute(
        """
        INSERT INTO workouts (
            id, activity_type, start_at, end_at, start_date_local, local_date,
            duration_sec, distance_m, energy_kcal, source_id, device, route_file, creation_date
        ) VALUES (?, 'HKWorkoutActivityTypeRunning', ?, ?, ?, ?, ?, ?, ?, 1, 'Watch', NULL, ?)
        """,
        (wid, start, end, f"{day.isoformat()} 07:00:00 -0500", day.isoformat(),
         duration_sec, distance_m, miles * 110, start),
    )
    if avg_hr is not None:
        conn.execute(
            """
            INSERT INTO workout_statistics (
                workout_id, stat_type, avg_value, max_value, unit
            ) VALUES (?, 'HKQuantityTypeIdentifierHeartRate', ?, ?, 'count/min')
            """,
            (wid, avg_hr, max_hr or avg_hr + 12),
        )


def build_plan_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_schema(conn, fresh=True)
    conn.execute(
        """
        INSERT INTO user_profile (id, date_of_birth, biological_sex, export_date)
        VALUES (1, '1990-05-01', 'HKBiologicalSexMale', '2026-11-06 12:00:00 -0500')
        """
    )
    conn.execute("INSERT INTO sources (id, name, version) VALUES (1, 'Apple Watch', '11.0')")

    # W40 (Sep 28–Oct 4): on-track easy volume
    _run(conn, "w40a", date(2026, 9, 28), 4.0, 10.4, 140)
    _run(conn, "w40b", date(2026, 9, 30), 4.0, 10.3, 138)
    _run(conn, "w40c", date(2026, 10, 2), 5.0, 9.4, 159, 174)  # Friday quality
    _run(conn, "w40d", date(2026, 10, 3), 4.0, 10.5, 141)
    # W41: similar
    _run(conn, "w41a", date(2026, 10, 5), 5.05, 10.15, 144)  # best easy ~5 mi, still ~0:45 off 9:30
    _run(conn, "w41b", date(2026, 10, 7), 3.5, 10.2, 139)
    _run(conn, "w41c", date(2026, 10, 9), 4.5, 9.15, 158, 172)
    _run(conn, "w41d", date(2026, 10, 10), 4.0, 10.4, 142)
    # W42: light
    _run(conn, "w42a", date(2026, 10, 12), 3.0, 10.6, 140)
    _run(conn, "w42b", date(2026, 10, 14), 4.0, 10.5, 143)
    # W43: GAP — no runs
    # W44: too hard (several quality / high HR)
    _run(conn, "w44a", date(2026, 10, 26), 4.0, 9.1, 162, 178)
    _run(conn, "w44b", date(2026, 10, 28), 4.0, 9.0, 165, 180)
    _run(conn, "w44c", date(2026, 10, 30), 5.0, 8.9, 168, 182)
    _run(conn, "w44d", date(2026, 10, 31), 4.0, 9.2, 160, 176)
    # W45 (Nov 2–8, as_of Friday): on-track-ish, one quality
    _run(conn, "w45a", date(2026, 11, 2), 4.0, 10.4, 141)
    _run(conn, "w45b", date(2026, 11, 4), 3.5, 10.3, 139)
    _run(conn, "w45c", date(2026, 11, 5), 3.0, 10.5, 142)
    _run(conn, "w45d", date(2026, 11, 6), 5.0, 9.08, 159, 174)

    for i in range(0, 45):
        day = date(2026, 9, 28) + timedelta(days=i)
        if day > AS_OF:
            break
        conn.execute(
            """
            INSERT INTO daily_metrics (local_date, resting_hr, hrv_sdnn, vo2_max, sleep_total_min, steps)
            VALUES (?, 48, 70, 47.8, 450, 9000)
            """,
            (day.isoformat(),),
        )
    conn.commit()
    return conn


class ZoneHelpersTest(unittest.TestCase):
    def test_assign_zone_bands(self):
        self.assertEqual(assign_zone(125), "Z1")
        self.assertEqual(assign_zone(140), "Z2")
        self.assertEqual(assign_zone(145), "Z2")
        self.assertEqual(assign_zone(148), "Z3")
        self.assertEqual(assign_zone(170), "Z4")
        self.assertEqual(assign_zone(180), "Z5")
        self.assertEqual(assign_zone(110), "Z1")
        self.assertEqual(assign_zone(200), "Z5")
        self.assertIsNone(assign_zone(None))

    def test_easy_vs_quality(self):
        self.assertTrue(is_easy(EASY_HR_CEILING))
        self.assertFalse(is_easy(EASY_HR_CEILING + 1))
        self.assertTrue(is_quality(QUALITY_AVG_HR_MIN))
        self.assertFalse(is_quality(QUALITY_AVG_HR_MIN - 1))

    def test_qualifying_easy_aerobic_filters(self):
        self.assertTrue(qualifies_easy_aerobic(4.0, 40, 141, 152, 10.2))
        self.assertFalse(qualifies_easy_aerobic(1.5, 16, 140, 148, 10.5))  # short
        self.assertFalse(qualifies_easy_aerobic(5.0, 45, 159, 174, 9.05))  # 4x4-ish
        self.assertFalse(qualifies_easy_aerobic(4.75, 40, 141, 179, 8.5))  # avg easy, max not
        self.assertFalse(qualifies_easy_aerobic(4.0, 40, None, 150, 10.2))  # no HR
        self.assertTrue(qualifies_easy_aerobic(4.0, 40, 141, None, 10.2))  # missing max still counts
        self.assertFalse(qualifies_easy_aerobic(4.0, 40, 141, CARDIO_MAX_HR_CEILING + 1, 10.2))

    def test_inverted_pace_over_hr_ratio_is_not_shipped(self):
        """sec/mi ÷ bpm at the same pace falls when HR rises — that is not 'better'."""
        inverted = lambda pace, hr: pace * 60.0 / hr
        self.assertLess(inverted(10.0, 145), inverted(10.0, 140))

    def test_same_pace_lower_hr_never_looks_worse(self):
        low = _cardio_from_runs([{"pace_min_per_mile": 10.0, "avg_hr": 138, "max_hr": 150}] * 3)
        high = _cardio_from_runs([{"pace_min_per_mile": 10.0, "avg_hr": 144, "max_hr": 150}] * 3)
        self.assertEqual(low["median_pace"], high["median_pace"])
        self.assertLess(low["median_hr"], high["median_hr"])
        assert_no_combined_cardio_score(self, low)
        assert_no_combined_cardio_score(self, high)

    def test_same_hr_faster_pace_never_looks_worse(self):
        fast = _cardio_from_runs([{"pace_min_per_mile": 9.25, "avg_hr": 140, "max_hr": 150}] * 3)
        slow = _cardio_from_runs([{"pace_min_per_mile": 10.50, "avg_hr": 140, "max_hr": 150}] * 3)
        self.assertLess(fast["median_pace"], slow["median_pace"])
        self.assertEqual(fast["median_hr"], slow["median_hr"])
        assert_no_combined_cardio_score(self, fast)
        assert_no_combined_cardio_score(self, slow)

    def test_goal_score_prefers_easy_five_at_goal_pace(self):
        hit = goal_score(5.0, 9.25, 144)
        miss_hr = goal_score(5.0, 9.25, 160)
        miss_pace = goal_score(5.0, 11.0, 140)
        self.assertGreater(hit, miss_hr)
        self.assertGreater(hit, miss_pace)
        self.assertGreater(hit, 85)
        self.assertIsNone(goal_score(5.0, 9.25, None))

    def test_status_codes(self):
        code, label, _ = classify_week_status(16.5, 0.72, 1, 5)
        self.assertEqual(code, "on_track")
        code, _, _ = classify_week_status(8.0, 0.9, 0, 7)
        self.assertEqual(code, "light")
        code, _, _ = classify_week_status(17.0, 0.3, 3, 7)
        self.assertEqual(code, "too_hard")
        code, _, _ = classify_week_status(0, None, 0, 5)
        self.assertEqual(code, "gap")


class DashboardPayloadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = build_plan_db()
        cls.data = fetch_dashboard_data(cls.conn, days=365, today=AS_OF)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_progress_this_week(self):
        p = self.data["overview"]["progress"]
        self.assertEqual(p["label"], "This week")
        self.assertEqual(p["week"], "2026-W45")
        self.assertAlmostEqual(p["miles"], 15.5, places=1)
        self.assertEqual(p["quality_count"], 1)
        self.assertGreater(p["easy_share"], 0.6)
        self.assertEqual(p["status"], "on_track")
        self.assertIsNotNone(p["last_quality"])
        self.assertEqual(p["last_quality"]["local_date"], "2026-11-06")

    def test_gap_week_in_consistency(self):
        weeks = {w["week"]: w for w in self.data["volume"]["weekly"]}
        self.assertIn("2026-W43", weeks)
        self.assertTrue(weeks["2026-W43"]["is_gap"])
        self.assertIn("2026-W43", self.data["volume"]["gap_weeks"])

    def test_too_hard_week_zone_mix(self):
        zw = {w["week"]: w for w in self.data["running"]["zone_weekly"]}
        hard = zw["2026-W44"]
        self.assertGreater(hard["zones"]["Z3"] + hard["zones"]["Z4"], hard["zones"]["Z2"])
        self.assertGreaterEqual(hard["quality_count"], 3)

    def test_goal_candidate_includes_easy_five(self):
        dates = [c["local_date"] for c in self.data["overview"]["goal"]["candidates"]]
        self.assertIn("2026-10-05", dates)
        best = self.data["overview"]["goal"]["best_easy_near_5"]
        self.assertEqual(best["local_date"], "2026-10-05")
        self.assertLessEqual(best["avg_hr"], EASY_HR_CEILING)
        self.assertAlmostEqual(best["pace_min_per_mile"], 10.15, places=2)
        self.assertGreater(self.data["overview"]["goal"]["pace_gap_min"], 0)

    def test_scatter_and_cardio_form(self):
        scatter = self.data["running"]["scatter"]
        self.assertTrue(any(p["zone"] == "Z2" for p in scatter))
        self.assertTrue(any(p["quality"] for p in scatter))
        cardio = self.data["running"]["cardio"]
        self.assertEqual(cardio["window"]["status"], "ok")
        self.assertGreaterEqual(cardio["window"]["n"], CARDIO_MIN_SAMPLES)
        self.assertIsNotNone(cardio["window"]["median_pace"])
        self.assertIsNotNone(cardio["window"]["median_hr"])
        assert_no_combined_cardio_score(self, cardio["window"])
        self.assertTrue(any(w["median_pace"] for w in cardio["weekly"]))
        self.assertTrue(all("median_sec_per_mi_per_bpm" not in w for w in cardio["weekly"]))
        # Interval / high-HR day must not be a cardio sample.
        recent = {r["local_date"]: r for r in self.data["running"]["recent_runs"]}
        self.assertFalse(recent["2026-11-06"]["cardio_sample"])
        self.assertTrue(recent["2026-11-02"]["cardio_sample"])
        easy = self.data["running"]["easy_trend"]
        self.assertTrue(all(130 <= r["avg_hr"] <= 148 for r in easy))
        self.assertNotIn("vo2", cardio["formula"].lower())
        self.assertIn("apple vo", cardio["limitations"].lower().replace("₂", "2"))
        self.assertIn("not a speed/hr index", cardio["limitations"].lower())
        self.assertIn("missing max hr still counts", cardio["limitations"].lower())
        self.assertIsNone(self.data["overview"]["progress"]["easy_form"].get("vo2"))

    def test_config_embedded(self):
        cfg = self.data["config"]
        self.assertEqual(cfg["easy_hr_ceiling"], 145)
        names = [z["name"] for z in cfg["zones"]]
        self.assertEqual(names, ["Z1", "Z2", "Z3", "Z4", "Z5"])
        self.assertEqual(cfg["goal"]["pace_max"], GOAL_PACE_MAX)
        self.assertEqual(cfg["cardio"]["min_samples"], CARDIO_MIN_SAMPLES)

    def test_shoes_section_present(self):
        shoes = self.data["shoes"]
        active = shoes["active"]
        self.assertEqual(active["id"], "asics-2026-08-01")
        self.assertEqual(active["brand"], "ASICS")
        self.assertFalse(active.get("model"))
        self.assertEqual(active["display_name"], "ASICS (model unknown)")
        self.assertIsNone(active.get("photo"))
        self.assertFalse(active.get("photo_stand_in"))
        self.assertFalse(active.get("color"))
        self.assertFalse(active.get("size"))
        blob = json.dumps(active).lower()
        self.assertNotRegex(blob, r"gel[- ]?(kayano|cumulus|nimbus)")
        self.assertNotIn("kayano", blob)
        self.assertGreater(active["miles"], 0)
        self.assertGreater(active["run_miles"], 0)
        self.assertIn("stack", active)
        previous = next(p for p in shoes["pairs"] if p["id"] == "gel-cumulus-26-black-safety-yellow")
        self.assertTrue(previous["retired"])
        self.assertFalse(previous["active"])
        self.assertIn("HKWorkoutActivityTypeRunning", shoes["activity_filter"])
        self.assertIn("HKWorkoutActivityTypeWalking", shoes["activity_filter"])
        self.assertIn("walking", shoes["footnote"].lower())

    def test_sparse_cardio_has_no_headline(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_schema(conn, fresh=True)
        conn.execute(
            """INSERT INTO user_profile (id, date_of_birth, biological_sex, export_date)
               VALUES (1, '1990-05-01', 'HKBiologicalSexMale', '2026-11-06 12:00:00 -0500')"""
        )
        conn.execute("INSERT INTO sources (id, name, version) VALUES (1, 'Apple Watch', '11.0')")
        _run(conn, "only1", date(2026, 11, 2), 4.0, 10.4, 141, 150)
        _run(conn, "only2", date(2026, 11, 4), 3.5, 10.3, 139, 149)
        conn.commit()
        data = fetch_dashboard_data(conn, days=365, today=AS_OF)
        window = data["running"]["cardio"]["window"]
        self.assertEqual(window["n"], 2)
        self.assertEqual(window["status"], "sparse")
        self.assertIsNone(window["median_pace"])
        self.assertIsNone(window["median_hr"])
        assert_no_combined_cardio_score(self, window)
        conn.close()

    def test_tiny_seed_does_not_crash(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_schema(conn, fresh=True)
        seed = (REPO / "test" / "fixtures" / "seed.sql").read_text(encoding="utf-8")
        conn.executescript(seed)
        data = fetch_dashboard_data(conn, days=365, today=date(2026, 1, 15))
        self.assertGreaterEqual(data["overview"]["run_count"], 2)
        self.assertIn("progress", data["overview"])
        self.assertTrue(data["running"]["recent_runs"])
        self.assertIn("shoes", data)
        self.assertIn("active", data["shoes"])
        conn.close()


def _empty_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_schema(conn, fresh=True)
    conn.execute(
        """INSERT INTO user_profile (id, date_of_birth, biological_sex, export_date)
           VALUES (1, '1990-05-01', 'HKBiologicalSexMale', '2026-11-06 12:00:00 -0500')"""
    )
    conn.execute("INSERT INTO sources (id, name, version) VALUES (1, 'Apple Watch', '11.0')")
    return conn


CUMULUS = {
    "id": "gel-cumulus-26-black-safety-yellow",
    "active": True,
    "brand": "ASICS",
    "model": "Gel-Cumulus 26",
    "color": "Black / Safety Yellow",
    "start_date": "2025-04-16",
    "purchased": "2025-04-16",
}


class ShoeTrackerTest(unittest.TestCase):
    def test_default_config_seeds_aug_2026_asics_not_gel(self):
        cfg = load_shoes_config()
        self.assertEqual(cfg["lifespan"]["typical_miles"], 400)
        self.assertEqual(cfg["lifespan"]["check_wear_miles"], 300)
        self.assertEqual(cfg["lifespan"]["upper_miles"], 500)
        self.assertIn("300", cfg["lifespan"]["source_note"])
        active = next(p for p in cfg["pairs"] if p["active"])
        self.assertEqual(active["id"], "asics-2026-08-01")
        self.assertEqual(active["brand"], "ASICS")
        self.assertFalse(active.get("model"))
        self.assertEqual(active["start_date"], "2026-08-01")
        self.assertEqual(active["display_name"], "ASICS (model unknown)")
        self.assertIsNone(active.get("photo"))
        self.assertFalse(active.get("photo_stand_in"))
        self.assertFalse(active.get("color"))
        self.assertFalse(active.get("size"))
        blob = json.dumps(active).lower()
        self.assertNotRegex(blob, r"gel[- ]?(kayano|cumulus|nimbus)")
        self.assertNotIn("kayano", blob)
        self.assertNotIn("nimbus", blob)
        previous = next(p for p in cfg["pairs"] if p["id"] == "gel-cumulus-26-black-safety-yellow")
        self.assertFalse(previous["active"])
        self.assertTrue(previous["retired"])
        self.assertEqual(previous["retired_date"], "2026-07-31")
        self.assertNotIn("address", json.dumps(cfg).lower())
        self.assertNotIn("credit card", json.dumps(cfg).lower())

    def test_config_rejects_missing_fields_and_bad_dates(self):
        with self.assertRaises(ShoeConfigError):
            normalize_shoes_config({"pairs": [{"id": "x"}]})
        with self.assertRaises(ShoeConfigError):
            normalize_shoes_config(
                {"pairs": [{**CUMULUS, "start_date": "not-a-date"}]}
            )
        with self.assertRaises(ShoeConfigError):
            normalize_shoes_config(
                {
                    "pairs": [
                        {**CUMULUS, "start_date": "2025-04-16", "retired_date": "2025-04-01"}
                    ]
                }
            )
        pending = normalize_shoes_config(
            {"pairs": [{"id": "current-placeholder", "placeholder": True}]}
        )
        self.assertTrue(pending["pairs"][0]["placeholder"])
        self.assertIsNone(pending["pairs"][0]["start_date"])

    def test_does_not_promote_previous_pair_to_active(self):
        cfg = normalize_shoes_config(
            {
                "pairs": [
                    {**CUMULUS, "active": False, "retired": True},
                ]
            }
        )
        self.assertIsNone(cfg["active_id"])
        self.assertFalse(cfg["pairs"][0]["active"])
        self.assertTrue(cfg["pairs"][0]["retired"])

    def test_start_date_filtering(self):
        conn = _empty_conn()
        _workout(conn, "before", date(2025, 4, 15), 10.0)
        _workout(conn, "on_day", date(2025, 4, 16), 3.0)
        _workout(conn, "first", date(2025, 4, 20), 5.0)
        _workout(conn, "later", date(2026, 11, 4), 4.0)
        conn.commit()
        miles = query_shoe_mileage(conn, "2025-04-16")
        self.assertEqual(miles["run_count"], 3)
        self.assertAlmostEqual(miles["run_miles"], 12.0, places=1)
        self.assertEqual(miles["first_run"], "2025-04-16")
        self.assertEqual(miles["last_run"], "2026-11-04")
        conn.close()

    def test_counts_run_and_walk_excludes_golf_cycle_hike(self):
        conn = _empty_conn()
        _workout(conn, "run_ok", date(2025, 5, 1), 8.0)
        _workout(conn, "walk", date(2025, 5, 2), 12.0, "HKWorkoutActivityTypeWalking")
        _workout(conn, "golf", date(2025, 5, 3), 6.0, "HKWorkoutActivityTypeGolf")
        _workout(conn, "ride", date(2025, 5, 4), 20.0, "HKWorkoutActivityTypeCycling")
        _workout(conn, "hike", date(2025, 5, 4), 9.0, "HKWorkoutActivityTypeHiking")
        _workout(conn, "zero", date(2025, 5, 5), 0.0)
        conn.execute(
            """
            INSERT INTO workouts (
                id, activity_type, start_at, end_at, start_date_local, local_date,
                duration_sec, distance_m, energy_kcal, source_id, device, route_file, creation_date
            ) VALUES ('null_dist', 'HKWorkoutActivityTypeRunning', '2025-05-06T12:00:00+00:00',
                      '2025-05-06T13:00:00+00:00', '2025-05-06 07:00:00 -0500', '2025-05-06',
                      3600, NULL, 100, 1, 'Watch', NULL, '2025-05-06T12:00:00+00:00')
            """
        )
        conn.commit()
        miles = query_shoe_mileage(conn, "2025-04-16")
        self.assertEqual(miles["run_count"], 1)
        self.assertEqual(miles["walk_count"], 1)
        self.assertAlmostEqual(miles["run_miles"], 8.0, places=1)
        self.assertAlmostEqual(miles["walk_miles"], 12.0, places=1)
        self.assertAlmostEqual(miles["miles"], 20.0, places=1)
        conn.close()

    def test_walk_before_start_date_is_excluded(self):
        conn = _empty_conn()
        _workout(conn, "early_walk", date(2026, 7, 31), 5.0, "HKWorkoutActivityTypeWalking")
        _workout(conn, "ok_walk", date(2026, 8, 2), 3.0, "HKWorkoutActivityTypeWalking")
        _workout(conn, "ok_run", date(2026, 8, 3), 4.0)
        conn.commit()
        miles = query_shoe_mileage(conn, "2026-08-01")
        self.assertEqual(miles["walk_count"], 1)
        self.assertEqual(miles["run_count"], 1)
        self.assertAlmostEqual(miles["miles"], 7.0, places=1)
        conn.close()

    def test_retired_date_stops_counting(self):
        conn = _empty_conn()
        _workout(conn, "in", date(2025, 6, 1), 10.0)
        _workout(conn, "out", date(2025, 7, 1), 10.0)
        conn.commit()
        miles = query_shoe_mileage(conn, "2025-04-16", "2025-06-15")
        self.assertEqual(miles["run_count"], 1)
        self.assertAlmostEqual(miles["miles"], 10.0, places=1)
        conn.close()

    def test_lifespan_thresholds(self):
        self.assertEqual(classify_shoe_status(0)[0], "fresh")
        self.assertEqual(classify_shoe_status(299.9)[0], "fresh")
        self.assertEqual(classify_shoe_status(300)[0], "check_wear")
        self.assertEqual(classify_shoe_status(399.9)[0], "check_wear")
        self.assertEqual(classify_shoe_status(400)[0], "replace")
        code, label, detail = classify_shoe_status(476.7)
        self.assertEqual(code, "replace")
        self.assertIn("Replace", label)
        self.assertIn("inspect", label.lower() + detail.lower())
        self.assertNotIn("plenty of life", detail.lower())
        self.assertNotIn("still fine", detail.lower())
        self.assertEqual(classify_shoe_status(500)[0], "past_lifespan")
        self.assertEqual(classify_shoe_status(620)[0], "past_lifespan")

    def test_lifespan_remaining_math(self):
        fresh = lifespan_stats(244.5)
        self.assertEqual(fresh["status"], "fresh")
        self.assertAlmostEqual(fresh["remaining_to_typical"], 155.5, places=1)
        self.assertEqual(fresh["miles_past_typical"], 0)
        worn = lifespan_stats(476.7)
        self.assertEqual(worn["status"], "replace")
        self.assertEqual(worn["remaining_to_typical"], 0)
        self.assertAlmostEqual(worn["miles_past_typical"], 76.7, places=1)
        self.assertAlmostEqual(worn["remaining_to_upper"], 23.3, places=1)
        self.assertGreaterEqual(worn["pct_of_typical"], 100)

    def test_payload_uses_injected_config_and_real_miles(self):
        conn = _empty_conn()
        _workout(conn, "old", date(2025, 4, 10), 50.0)
        _workout(conn, "run1", date(2025, 4, 20), 5.0)
        _workout(conn, "run2", date(2026, 11, 4), 4.7)
        _workout(conn, "walk", date(2025, 5, 1), 30.0, "HKWorkoutActivityTypeWalking")
        conn.commit()
        retired = {
            "id": "old-pair",
            "active": False,
            "brand": "ASICS",
            "model": "Gel-Cumulus 25",
            "start_date": "2024-01-01",
            "retired_date": "2025-04-15",
        }
        data = fetch_dashboard_data(
            conn,
            days=365,
            today=date(2026, 11, 6),
            shoes_config={"pairs": [retired, CUMULUS]},
        )
        shoes = data["shoes"]
        self.assertEqual(shoes["active"]["id"], "gel-cumulus-26-black-safety-yellow")
        self.assertAlmostEqual(shoes["active"]["run_miles"], 9.7, places=1)
        self.assertAlmostEqual(shoes["active"]["walk_miles"], 30.0, places=1)
        self.assertAlmostEqual(shoes["active"]["miles"], 39.7, places=1)
        self.assertEqual(shoes["active"]["run_count"], 2)
        self.assertEqual(shoes["active"]["walk_count"], 1)
        self.assertEqual(shoes["active"]["status"], "fresh")
        self.assertAlmostEqual(shoes["active"]["stack"]["run_miles"], 9.7, places=1)
        old = next(p for p in shoes["pairs"] if p["id"] == "old-pair")
        self.assertFalse(old["active"])
        self.assertAlmostEqual(old["miles"], 50.0, places=1)
        self.assertIn("walking", shoes["footnote"].lower())
        conn.close()

    def test_placeholder_skips_mileage(self):
        conn = _empty_conn()
        _workout(conn, "run1", date(2025, 4, 20), 10.0)
        conn.commit()
        data = fetch_dashboard_data(
            conn,
            days=365,
            today=date(2026, 11, 6),
            shoes_config={
                "pairs": [
                    {
                        "id": "current-placeholder",
                        "placeholder": True,
                        "active": True,
                    },
                    {**CUMULUS, "active": False, "retired": True},
                ]
            },
        )
        self.assertEqual(data["shoes"]["active"]["id"], "current-placeholder")
        self.assertEqual(data["shoes"]["active"]["status"], "pending")
        self.assertIsNone(data["shoes"]["active"]["miles"])
        prev = next(p for p in data["shoes"]["pairs"] if p["id"] == CUMULUS["id"])
        self.assertEqual(prev["status"], "previous")
        self.assertFalse(prev["active"])
        self.assertAlmostEqual(prev["miles"], 10.0, places=1)
        conn.close()

    def test_production_sanity_shape_run_and_walk_totals(self):
        """Fixture shaped like the 2026-11-09 production check (not hardcoded in UI)."""
        conn = _empty_conn()
        run_total, walk_total = 99.64, 85.75
        for i in range(29):
            day = date(2026, 8, 3) if i == 0 else date(2026, 11, 4) if i == 28 else date(2026, 8, 10)
            _workout(conn, f"r{i}", day, run_total / 29)
        for i in range(23):
            day = date(2026, 8, 2) if i == 0 else date(2026, 10, 25) if i == 22 else date(2026, 9, 1)
            _workout(conn, f"w{i}", day, walk_total / 23, "HKWorkoutActivityTypeWalking")
        conn.commit()
        miles = query_shoe_mileage(conn, "2026-08-01")
        self.assertEqual(miles["run_count"], 29)
        self.assertEqual(miles["walk_count"], 23)
        self.assertAlmostEqual(miles["run_miles"], 99.64, places=1)
        self.assertAlmostEqual(miles["walk_miles"], 85.75, places=1)
        self.assertAlmostEqual(miles["miles"], 185.39, places=1)
        self.assertEqual(miles["first_run"], "2026-08-03")
        self.assertEqual(miles["last_run"], "2026-11-04")
        self.assertEqual(miles["first_walk"], "2026-08-02")
        self.assertEqual(miles["last_walk"], "2026-10-25")
        conn.close()

    def test_current_pair_has_no_product_photo(self):
        kayano = REPO / "dashboard" / "assets" / "asics-gel-kayano-33-black.jpg"
        self.assertFalse(kayano.exists())
        attr = (REPO / "dashboard" / "assets" / "ATTRIBUTION.md").read_text(encoding="utf-8")
        self.assertNotIn("kayano-33", attr.lower())
        self.assertIn("previous", attr.lower())
        page = (REPO / "index.html").read_text(encoding="utf-8")
        self.assertIn("ASICS (model unknown)", page)
        self.assertIn("No photo until the model is known", page)
        self.assertNotIn("GEL-KAYANO 33", page)
        self.assertNotIn("asics-gel-kayano-33-black.jpg", page)
        self.assertIn("Colorway unconfirmed", page)

    def test_model_field_optional_in_config(self):
        cfg = normalize_shoes_config(
            {
                "pairs": [
                    {
                        "id": "asics-2026-08-01",
                        "brand": "ASICS",
                        "start_date": "2026-08-01",
                        "purchased": "2026-08-01",
                    }
                ]
            }
        )
        self.assertIsNone(cfg["pairs"][0]["model"])
        self.assertEqual(cfg["pairs"][0]["display_name"], "ASICS (model unknown)")


if __name__ == "__main__":
    unittest.main()
