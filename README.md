# Apple Health → Training Database

Parse an Apple Health export into a SQLite database focused on running performance and recovery metrics.

## Layout

```
Health_Data/
├── apple_health_export/     # Apple Health ZIP contents (not in git)
├── data/                    # SQLite DB + summaries (not in git)
│   ├── training.db
│   └── summaries/
└── health_data/             # This repo — scripts only
    ├── run.py
    ├── parse/
    └── schema/
```

## Requirements

- Python 3.11+
- No third-party dependencies (stdlib only)

## Usage

1. Export your data from the Health app: **Profile → Export All Health Data**
2. Unzip into `../apple_health_export/` (sibling of this repo)
3. Run the importer from this directory:

```bash
python run.py
```

Options:

- `--fresh` — drop and recreate tables before import
- `--skip-routes` — skip GPX parsing (faster)
- `--weeks 4` — weeks of history in the JSON summary

## What gets imported

| Data | Source |
|------|--------|
| Workouts + statistics | `export.xml` |
| VO2 max, resting HR, HRV, weight | `export.xml` |
| Sleep segments | `export.xml` |
| Daily steps & active energy | aggregated from `export.xml` |
| Activity ring summaries | `export.xml` |
| GPS routes | `workout-routes/*.gpx` |

## Querying

Open `../data/training.db` with any SQLite client. Useful views:

- `v_workout_context` — workouts joined with daily recovery metrics
- `v_weekly_training` — weekly run volume

Training summaries for coaching review are written to `../data/summaries/`.

## Deploy (static dashboard)

`index.html` at the repo root is the published dashboard. Coolify (Railpack/Nixpacks) should treat this as a Node app:

- **Install:** `npm install`
- **Start command:** `npm start`
- **Port:** `3000` (or set `PORT`; the start script uses `${PORT:-3000}`)

Run the same locally:

```bash
npm install
npm start
```

Then open http://localhost:3000. The page is prebuilt; `npm run build` is a no-op.
