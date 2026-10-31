"""Path configuration — code lives in the git repo, data lives outside it."""

import os
from pathlib import Path

# Repo root: health_data/ (this directory's parent)
REPO_ROOT = Path(__file__).resolve().parent.parent

# Workspace root: Health_Data/ (parent of repo)
WORKSPACE_ROOT = REPO_ROOT.parent


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    if value:
        return Path(value).expanduser().resolve()
    return default


# Apple Health export folder (outside repo). Override with HEALTH_EXPORT_DIR.
EXPORT_DIR = _env_path("HEALTH_EXPORT_DIR", WORKSPACE_ROOT / "apple_health_export")
EXPORT_XML = EXPORT_DIR / "export.xml"
ROUTES_DIR = EXPORT_DIR / "workout-routes"
ECG_DIR = EXPORT_DIR / "electrocardiograms"

# SQLite database and generated artifacts (outside repo). Override with HEALTH_DATA_DIR.
DATA_DIR = _env_path("HEALTH_DATA_DIR", WORKSPACE_ROOT / "data")
DB_PATH = DATA_DIR / "training.db"
SUMMARIES_DIR = DATA_DIR / "summaries"

# HealthKit record types to store as individual samples (low volume)
SAMPLE_RECORD_TYPES = {
    "HKQuantityTypeIdentifierVO2Max",
    "HKQuantityTypeIdentifierRestingHeartRate",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
    "HKQuantityTypeIdentifierBodyMass",
}

# Category types stored as segments
CATEGORY_RECORD_TYPES = {
    "HKCategoryTypeIdentifierSleepAnalysis",
}

# High-volume types aggregated into daily_metrics during parse (not stored per-sample)
DAILY_AGGREGATE_TYPES = {
    "HKQuantityTypeIdentifierStepCount",
    "HKQuantityTypeIdentifierActiveEnergyBurned",
}
