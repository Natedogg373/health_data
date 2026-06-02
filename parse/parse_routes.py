"""Parse GPX workout routes and link to workouts."""

from __future__ import annotations

import math
import re
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

from parse.config import ROUTES_DIR
from parse.parse_export import parse_apple_datetime

GPX_NS = {"gpx": "http://www.topografix.com/GPX/1/1"}
ROUTE_FILENAME = re.compile(
    r"route_(\d{4}-\d{2}-\d{2})_(\d{1,2})\.(\d{2})(am|pm)\.gpx$",
    re.IGNORECASE,
)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _parse_gpx(path: Path) -> list[dict]:
    tree = ET.parse(path)
    root = tree.getroot()
    points = []
    for trkpt in root.findall(".//gpx:trkpt", GPX_NS):
        lat = float(trkpt.get("lat"))
        lon = float(trkpt.get("lon"))
        ele_el = trkpt.find("gpx:ele", GPX_NS)
        time_el = trkpt.find("gpx:time", GPX_NS)
        elevation = float(ele_el.text) if ele_el is not None and ele_el.text else None
        recorded_at = time_el.text if time_el is not None else None

        speed = course = None
        ext = trkpt.find("gpx:extensions", GPX_NS)
        if ext is not None:
            for child in ext:
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if tag == "speed" and child.text:
                    speed = float(child.text)
                elif tag == "course" and child.text:
                    course = float(child.text)

        points.append(
            {
                "lat": lat,
                "lon": lon,
                "elevation_m": elevation,
                "recorded_at": recorded_at,
                "speed_mps": speed,
                "course_deg": course,
            }
        )
    return points


def _parse_route_filename(filename: str) -> datetime | None:
    """Parse route_2024-09-24_7.07pm.gpx into approximate local datetime."""
    match = ROUTE_FILENAME.match(filename)
    if not match:
        return None
    day, hour, minute, ampm = match.groups()
    h = int(hour) % 12
    if ampm.lower() == "pm":
        h += 12
    return datetime.strptime(f"{day} {h:02d}:{minute}", "%Y-%m-%d %H:%M")


def _find_workout_for_route(conn: sqlite3.Connection, filename: str) -> str | None:
    row = conn.execute(
        "SELECT id FROM workouts WHERE route_file = ?", (filename,)
    ).fetchone()
    if row:
        return row["id"]

    route_dt = _parse_route_filename(filename)
    if route_dt is None:
        return None

    day = route_dt.date().isoformat()
    candidates = conn.execute(
        """
        SELECT id, start_date_local FROM workouts
        WHERE local_date = ?
          AND id NOT IN (SELECT workout_id FROM routes WHERE workout_id IS NOT NULL)
        ORDER BY start_date_local
        """,
        (day,),
    ).fetchall()
    if not candidates:
        return None

    route_minutes = route_dt.hour * 60 + route_dt.minute
    best_id = None
    best_delta_min = 9999
    for cand in candidates:
        if not cand["start_date_local"]:
            continue
        wdt = parse_apple_datetime(cand["start_date_local"])
        w_minutes = wdt.hour * 60 + wdt.minute
        delta = abs(route_minutes - w_minutes)
        if delta < best_delta_min:
            best_delta_min = delta
            best_id = cand["id"]

    if best_id is not None and best_delta_min <= 30:
        conn.execute(
            "UPDATE workouts SET route_file = ? WHERE id = ?",
            (filename, best_id),
        )
        return best_id
    return None


def _route_stats(points: list[dict]) -> dict:
    if not points:
        return {
            "point_count": 0,
            "distance_m": 0.0,
            "elev_gain_m": 0.0,
            "duration_sec": 0.0,
            "avg_speed_mps": None,
            "max_speed_mps": None,
        }

    distance = 0.0
    elev_gain = 0.0
    speeds = []
    for i in range(1, len(points)):
        p0, p1 = points[i - 1], points[i]
        distance += _haversine_m(p0["lat"], p0["lon"], p1["lat"], p1["lon"])
        if p0["elevation_m"] is not None and p1["elevation_m"] is not None:
            gain = p1["elevation_m"] - p0["elevation_m"]
            if gain > 0:
                elev_gain += gain
        if p1["speed_mps"] is not None:
            speeds.append(p1["speed_mps"])

    duration_sec = 0.0
    if points[0]["recorded_at"] and points[-1]["recorded_at"]:
        t0 = datetime.fromisoformat(points[0]["recorded_at"].replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(points[-1]["recorded_at"].replace("Z", "+00:00"))
        duration_sec = (t1 - t0).total_seconds()

    return {
        "point_count": len(points),
        "distance_m": distance,
        "elev_gain_m": elev_gain,
        "duration_sec": duration_sec,
        "avg_speed_mps": sum(speeds) / len(speeds) if speeds else None,
        "max_speed_mps": max(speeds) if speeds else None,
    }


def parse_routes(conn: sqlite3.Connection, routes_dir: Path = ROUTES_DIR) -> int:
    """Parse all GPX files and link to workouts by filename. Returns route count."""
    if not routes_dir.exists():
        return 0

    conn.execute("DELETE FROM route_points")
    conn.execute("DELETE FROM routes")
    conn.commit()

    parsed = 0
    for gpx_path in sorted(routes_dir.glob("*.gpx")):
        filename = gpx_path.name
        points = _parse_gpx(gpx_path)
        stats = _route_stats(points)
        workout_id = _find_workout_for_route(conn, filename)

        cur = conn.execute(
            """
            INSERT INTO routes (
                workout_id, gpx_filename, point_count, distance_m,
                elev_gain_m, duration_sec, avg_speed_mps, max_speed_mps
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                workout_id,
                filename,
                stats["point_count"],
                stats["distance_m"],
                stats["elev_gain_m"],
                stats["duration_sec"],
                stats["avg_speed_mps"],
                stats["max_speed_mps"],
            ),
        )
        route_id = cur.lastrowid

        conn.executemany(
            """
            INSERT INTO route_points (
                route_id, seq, lat, lon, elevation_m,
                recorded_at, speed_mps, course_deg
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    route_id,
                    i,
                    p["lat"],
                    p["lon"],
                    p["elevation_m"],
                    p["recorded_at"],
                    p["speed_mps"],
                    p["course_deg"],
                )
                for i, p in enumerate(points)
            ],
        )
        parsed += 1

        if parsed % 25 == 0:
            conn.commit()

    conn.commit()
    return parsed
