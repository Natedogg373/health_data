"""Running-shoe roster, mileage, and lifespan estimates for the dashboard.

Shoe identity lives in `shoes.json` so a future pair can be added and an old
pair retired without rewriting SQL. Mileage is always recomputed from the
workouts table — never hardcoded into the page.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import sqlite3

METERS_PER_MILE = 1609.344
RUNNING_TYPE = "HKWorkoutActivityTypeRunning"
DEFAULT_SHOES_PATH = Path(__file__).resolve().parent / "shoes.json"

REQUIRED_REAL_PAIR_FIELDS = ("id", "brand", "model", "start_date")


class ShoeConfigError(ValueError):
    """Raised when shoes.json is missing fields or has invalid dates."""


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ShoeConfigError(f"Invalid date {value!r}") from exc


def load_shoes_config(path: Path | None = None) -> dict:
    """Load and validate the shoe roster JSON."""
    config_path = Path(path) if path is not None else DEFAULT_SHOES_PATH
    if not config_path.exists():
        raise ShoeConfigError(f"Shoe config not found: {config_path}")
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ShoeConfigError(f"Shoe config is not valid JSON: {config_path}") from exc
    return normalize_shoes_config(raw)


def normalize_shoes_config(raw: dict | None) -> dict:
    if not isinstance(raw, dict):
        raise ShoeConfigError("Shoe config must be a JSON object")

    lifespan_in = raw.get("lifespan") or {}
    if not isinstance(lifespan_in, dict):
        raise ShoeConfigError("lifespan must be an object")
    try:
        typical = float(lifespan_in.get("typical_miles", 400))
        check_wear = float(lifespan_in.get("check_wear_miles", 300))
        upper = float(lifespan_in.get("upper_miles", 500))
    except (TypeError, ValueError) as exc:
        raise ShoeConfigError("lifespan miles must be numbers") from exc
    if not (0 < check_wear <= typical <= upper):
        raise ShoeConfigError(
            "Expected 0 < check_wear_miles <= typical_miles <= upper_miles"
        )

    pairs_in = raw.get("pairs") or raw.get("shoes") or []
    if not isinstance(pairs_in, list):
        raise ShoeConfigError("pairs must be a list")

    pairs = []
    seen_ids: set[str] = set()
    for item in pairs_in:
        if not isinstance(item, dict):
            raise ShoeConfigError("Each pair must be an object")
        is_placeholder = bool(item.get("placeholder"))
        pair_id = str(item.get("id") or "")
        if not pair_id:
            raise ShoeConfigError("Shoe pair missing fields: id")
        if pair_id in seen_ids:
            raise ShoeConfigError(f"Duplicate shoe id: {pair_id}")
        seen_ids.add(pair_id)
        if is_placeholder:
            start = _parse_date(item.get("start_date") or item.get("purchased"))
            retired = _parse_date(item.get("retired_date"))
            purchased = _parse_date(item.get("purchased")) or start
            brand = str(item.get("brand") or "")
            model = str(item.get("model") or "")
            display_name = str(
                item.get("display_name") or "Current pair — details pending"
            )
            active = bool(item.get("active", True))
        else:
            missing = [field for field in REQUIRED_REAL_PAIR_FIELDS if not item.get(field)]
            if missing:
                raise ShoeConfigError(f"Shoe pair missing fields: {', '.join(missing)}")
            start = _parse_date(item.get("start_date") or item.get("purchased"))
            if start is None:
                raise ShoeConfigError(f"Shoe {pair_id} needs a start_date")
            retired = _parse_date(item.get("retired_date"))
            purchased = _parse_date(item.get("purchased")) or start
            if retired is not None and retired < start:
                raise ShoeConfigError(f"Shoe {pair_id} retired_date is before start_date")
            brand = str(item["brand"])
            model = str(item["model"])
            display_name = str(item.get("display_name") or f"{brand} {model}")
            marked_retired = bool(item.get("retired")) or retired is not None
            active = False if marked_retired else bool(item.get("active", True))
        pairs.append(
            {
                "id": pair_id,
                "active": active,
                "placeholder": is_placeholder,
                "retired": (not is_placeholder)
                and (bool(item.get("retired")) or retired is not None or not active),
                "brand": brand or None,
                "model": model or None,
                "display_name": display_name,
                "color": item.get("color"),
                "gender": item.get("gender"),
                "size": item.get("size"),
                "width": item.get("width"),
                "sku": item.get("sku"),
                "purchased": purchased.isoformat() if purchased else None,
                "start_date": start.isoformat() if start else None,
                "retired_date": retired.isoformat() if retired else None,
                "retailer": item.get("retailer"),
                "order_number": item.get("order_number"),
                "price_usd": item.get("price_usd"),
                "photo": None if is_placeholder else item.get("photo"),
                "photo_alt": item.get("photo_alt")
                or (
                    f"{brand} {model} {item.get('color') or ''}".strip()
                    if not is_placeholder
                    else "No product photo yet"
                ),
                "pending_detail": item.get("pending_detail"),
            }
        )

    # Never silently promote a previous pair to current. Explicit active
    # non-placeholder pairs win; otherwise a placeholder may stand in.
    real_active = [
        p
        for p in pairs
        if p["active"] and not p["placeholder"] and not p["retired"]
    ]
    placeholder_active = [p for p in pairs if p["placeholder"] and p["active"]]
    active_id = None
    if real_active:
        active_id = max(real_active, key=lambda p: p["start_date"] or "")["id"]
    elif placeholder_active:
        active_id = placeholder_active[0]["id"]
    for pair in pairs:
        pair["active"] = pair["id"] == active_id if active_id else False

    return {
        "lifespan": {
            "typical_miles": typical,
            "check_wear_miles": check_wear,
            "upper_miles": upper,
            "source_url": lifespan_in.get(
                "source_url",
                "https://www.asics.com/us/en-us/blog/how-do-running-shoes-wear-over-time/",
            ),
            "source_note": lifespan_in.get(
                "source_note",
                "ASICS generally recommends replacing running shoes every 300–500 miles.",
            ),
        },
        "footnote": raw.get("footnote")
        or (
            "Only running miles count. Walking, golf, cycling, and other activities "
            "are not added — we cannot assume those were done in these shoes."
        ),
        "active_id": active_id,
        "pairs": pairs,
    }


def classify_shoe_status(
    miles: float,
    check_wear_miles: float = 300,
    typical_miles: float = 400,
    upper_miles: float = 500,
) -> tuple[str, str, str]:
    """Return (code, label, detail) for estimated remaining life.

    300 = check for wear, 400 = typical daily-trainer target, 500 = upper end
    of ASICS' 300–500 mile guidance. Past 400 is a replace / inspect status,
    not "still fine."
    """
    miles = float(miles)
    if miles >= upper_miles:
        over = miles - typical_miles
        return (
            "past_lifespan",
            "Replace this pair",
            (
                f"{miles:.1f} mi is at or past the {upper_miles:.0f}-mile upper estimate "
                f"({over:.1f} mi past the typical {typical_miles:.0f}-mile mark). "
                "Replace these shoes and inspect for outsole/midsole wear."
            ),
        )
    if miles >= typical_miles:
        over = miles - typical_miles
        remaining_upper = upper_miles - miles
        return (
            "replace",
            "Replace / inspect for wear",
            (
                f"{miles:.1f} mi is {over:.1f} past the typical {typical_miles:.0f}-mile "
                f"mark, with about {remaining_upper:.1f} mi left to the {upper_miles:.0f}-mile "
                "upper estimate. Plan a replacement and check the outsole and midsole — "
                "this pair is in/near the upper end of the 300–500 range, not still fresh."
            ),
        )
    if miles >= check_wear_miles:
        remaining = typical_miles - miles
        return (
            "check_wear",
            "Check for wear",
            (
                f"{miles:.1f} mi is into the 300–500 mile range. About {remaining:.1f} mi "
                f"remain to the typical {typical_miles:.0f}-mile target — inspect the outsole "
                "and midsole before they go much further."
            ),
        )
    remaining = typical_miles - miles
    return (
        "fresh",
        "Plenty of life left",
        (
            f"{miles:.1f} mi of an estimated {typical_miles:.0f}-mile typical lifespan "
            f"({remaining:.1f} mi remaining). Check for wear around {check_wear_miles:.0f} mi."
        ),
    )


def lifespan_stats(
    miles: float,
    check_wear_miles: float = 300,
    typical_miles: float = 400,
    upper_miles: float = 500,
) -> dict:
    miles_r = round(float(miles), 1)
    status, label, detail = classify_shoe_status(
        miles_r, check_wear_miles, typical_miles, upper_miles
    )
    return {
        "miles": miles_r,
        "typical_miles": typical_miles,
        "check_wear_miles": check_wear_miles,
        "upper_miles": upper_miles,
        "remaining_to_typical": round(max(0.0, typical_miles - miles_r), 1),
        "miles_past_typical": round(max(0.0, miles_r - typical_miles), 1),
        "remaining_to_upper": round(max(0.0, upper_miles - miles_r), 1),
        "miles_past_upper": round(max(0.0, miles_r - upper_miles), 1),
        "pct_of_typical": round(100.0 * miles_r / typical_miles, 1) if typical_miles else 0.0,
        "pct_of_upper": round(min(100.0, 100.0 * miles_r / upper_miles), 1) if upper_miles else 0.0,
        "status": status,
        "status_label": label,
        "status_detail": detail,
    }


def query_running_mileage(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str | None = None,
) -> dict:
    """Sum running miles in [start_date, end_date] (inclusive).

    Only HKWorkoutActivityTypeRunning with distance_m > 0. Walking / golf /
    cycling and zero-distance jogs are excluded.
    """
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS run_count,
            ROUND(COALESCE(SUM(distance_m), 0) / 1609.344, 1) AS miles,
            MIN(local_date) AS first_run,
            MAX(local_date) AS last_run
        FROM workouts
        WHERE activity_type = ?
          AND distance_m IS NOT NULL
          AND distance_m > 0
          AND local_date >= ?
          AND (? IS NULL OR local_date <= ?)
        """,
        (RUNNING_TYPE, start_date, end_date, end_date),
    ).fetchone()
    data = dict(row) if row else {}
    return {
        "run_count": int(data.get("run_count") or 0),
        "miles": float(data.get("miles") or 0),
        "first_run": data.get("first_run"),
        "last_run": data.get("last_run"),
    }


def annotate_pair(pair: dict, mileage: dict, lifespan: dict) -> dict:
    out = dict(pair)
    if pair.get("placeholder") or not pair.get("start_date"):
        out.update(
            {
                "miles": None,
                "typical_miles": lifespan["typical_miles"],
                "check_wear_miles": lifespan["check_wear_miles"],
                "upper_miles": lifespan["upper_miles"],
                "remaining_to_typical": None,
                "miles_past_typical": None,
                "remaining_to_upper": None,
                "miles_past_upper": None,
                "pct_of_typical": None,
                "pct_of_upper": None,
                "status": "pending",
                "status_label": "Details pending",
                "status_detail": pair.get("pending_detail")
                or (
                    "Current pair purchase details have not been added yet. "
                    "This is not a previous pair."
                ),
                "run_count": 0,
                "first_run": None,
                "last_run": None,
            }
        )
        return out

    stats = lifespan_stats(
        mileage.get("miles") or 0,
        check_wear_miles=lifespan["check_wear_miles"],
        typical_miles=lifespan["typical_miles"],
        upper_miles=lifespan["upper_miles"],
    )
    out.update(stats)
    out["run_count"] = int(mileage.get("run_count") or 0)
    out["first_run"] = mileage.get("first_run")
    out["last_run"] = mileage.get("last_run")
    if pair.get("retired") or not pair.get("active"):
        unknown_end = pair.get("retired_date") is None
        extra = "Previous pair — not the current shoes."
        if unknown_end:
            extra += (
                " Replacement date is unknown, so running miles after this pair "
                "was replaced may be included in this total."
            )
        out["status"] = "previous"
        out["status_label"] = "Previous pair"
        out["status_detail"] = extra
    return out


def build_shoes_payload(
    conn: sqlite3.Connection,
    config: dict | None = None,
    path: Path | None = None,
) -> dict:
    """Query mileage for every configured pair and return the dashboard section."""
    roster = load_shoes_config(path) if config is None else normalize_shoes_config(config)
    lifespan = roster["lifespan"]
    pairs = []
    for pair in roster["pairs"]:
        if pair.get("placeholder") or not pair.get("start_date"):
            mileage = {"miles": None, "run_count": 0, "first_run": None, "last_run": None}
        else:
            mileage = query_running_mileage(
                conn, pair["start_date"], pair.get("retired_date")
            )
        pairs.append(annotate_pair(pair, mileage, lifespan))
    active = next((p for p in pairs if p.get("active")), None)
    return {
        "lifespan": lifespan,
        "footnote": roster.get("footnote"),
        "activity_filter": RUNNING_TYPE,
        "active": active,
        "pairs": pairs,
    }
