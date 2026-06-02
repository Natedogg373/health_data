"""Path configuration — code lives in the git repo, data lives outside it."""

from pathlib import Path

# Repo root: health_data/ (this directory's parent)
REPO_ROOT = Path(__file__).resolve().parent.parent

# Workspace root: Health_Data/ (parent of repo)
WORKSPACE_ROOT = REPO_ROOT.parent

# Apple Health export folder (outside repo)
EXPORT_DIR = WORKSPACE_ROOT / "apple_health_export"
EXPORT_XML = EXPORT_DIR / "export.xml"
ROUTES_DIR = EXPORT_DIR / "workout-routes"
ECG_DIR = EXPORT_DIR / "electrocardiograms"

# SQLite database and generated artifacts (outside repo)
DATA_DIR = WORKSPACE_ROOT / "data"
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
