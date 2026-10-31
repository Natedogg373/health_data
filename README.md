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

Paths default to `../apple_health_export` and `../data`. Override with `HEALTH_EXPORT_DIR` and `HEALTH_DATA_DIR` (the Coolify API import sets these automatically).

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

## Deploy (dashboard + fitness API)

The Node app serves the static dashboard at `/` and a token-protected JSON API at `/api/*`. `training.db` is **not** in git — it lives on a Coolify persistent volume.

`railpack.json` forces provider `node` (Python is detected first because of `requirements.txt`) and installs **Node 22 + Python 3.12** so the importer can run in the same container. `nixpacks.toml` does the same for Nixpacks.

### Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `API_TOKEN` | **Yes** for `/api/*` | unset | Bearer token. If missing, `/api/*` returns 503. |
| `HEALTH_DATA_DIR` | Recommended | `/data` (Node) | Directory that contains `training.db`. |
| `HEALTH_EXPORT_DIR` | Local importer only | `../apple_health_export` | Folder with `export.xml`. The API import sets this per job. |
| `PORT` | No | `3000` | Listen port. Binds `0.0.0.0`. |
| `PYTHON` | No | `python3` | Python binary for import + dashboard rebuild. |

Generate a token:

```bash
openssl rand -hex 32
```

### Coolify (v4, Railpack)

1. Builder: **Railpack**. Start command stays `npm start` (from `railpack.json`). Port **3000**.
2. **Persistent storage:** add a volume and mount it at **`/data`**. That directory must be writable; the app stores `training.db` and `import-status.json` there.
3. **Environment variables** (runtime, not only build):
   - `API_TOKEN` = the token from `openssl rand -hex 32`
   - `HEALTH_DATA_DIR` = `/data`
4. Health check path: `/health` (public, no token).
5. Redeploy after merge. First boot has no database until you upload an export (or copy an existing `training.db` onto the volume).
6. Expose the app on Tailscale Funnel if you want a public HTTPS URL. **`/` is not authenticated** — only `/api/*` requires the bearer token. If the dashboard should stay private, put Coolify basic auth in front or do not Funnel `/`.

Python importer env vars (`HEALTH_EXPORT_DIR`, `HEALTH_DATA_DIR`) are also honored when you run `python run.py` locally.

### Local server

```bash
npm install
HEALTH_DATA_DIR=./data API_TOKEN=dev npm start
```

Open http://localhost:3000. `npm test` runs the API smoke tests against a synthetic fixture DB (no real health data). `npm run build` is a no-op.

### API (all `/api/*` routes)

Send `Authorization: Bearer $API_TOKEN`. Examples assume:

```bash
export HOST="https://your-funnel-host.example"
export API_TOKEN="…"   # same value as Coolify
```

**GET /health** (no token) — process liveness

```bash
curl -sS "$HOST/health"
```

```json
{"ok":true}
```

**GET /api/health** — DB path, Python version, last import

```bash
curl -sS -H "Authorization: Bearer $API_TOKEN" "$HOST/api/health"
```

```json
{
  "ok": true,
  "db": {"path": "/data/training.db", "exists": true},
  "python": "Python 3.12.x",
  "import": {"status": "idle"}
}
```

**GET /api/schema** — tables, views, and columns

```bash
curl -sS -H "Authorization: Bearer $API_TOKEN" "$HOST/api/schema"
```

```json
{
  "objects": [
    {"name": "workouts", "type": "table", "columns": [{"name": "id", "type": "TEXT"}]}
  ]
}
```

**GET /api/runs?since=YYYY-MM-DD&limit=50** — runs with distance, duration, pace, HR, elevation

```bash
curl -sS -H "Authorization: Bearer $API_TOKEN" "$HOST/api/runs?since=2026-01-01&limit=20"
```

```json
{
  "count": 1,
  "runs": [{
    "id": "run001",
    "local_date": "2026-01-10",
    "distance_m": 5000,
    "miles": 3.11,
    "duration_sec": 1920,
    "pace_min_per_mile": 10.3,
    "avg_hr": 148,
    "max_hr": 172,
    "elev_gain_m": 42.5
  }]
}
```

**GET /api/weekly** — `v_weekly_training`

```bash
curl -sS -H "Authorization: Bearer $API_TOKEN" "$HOST/api/weekly"
```

```json
{
  "count": 1,
  "weeks": [{
    "week": "2026-W01",
    "workout_count": 3,
    "run_count": 2,
    "run_distance_m": 13046.7,
    "run_miles": 8.11
  }]
}
```

**GET /api/daily?since=YYYY-MM-DD** — resting HR, HRV, VO2max, sleep, steps

```bash
curl -sS -H "Authorization: Bearer $API_TOKEN" "$HOST/api/daily?since=2026-01-01"
```

```json
{
  "count": 1,
  "days": [{
    "local_date": "2026-01-10",
    "resting_hr": 52,
    "hrv_sdnn": 46,
    "vo2_max": 48.2,
    "sleep_total_min": 430,
    "steps": 9800
  }]
}
```

**GET /api/workouts/:id** — one workout plus stats, metadata, route summary

```bash
curl -sS -H "Authorization: Bearer $API_TOKEN" "$HOST/api/workouts/run001"
```

**POST /api/query** — one read-only `SELECT` (row cap 200). Writes and multiple statements are rejected; the DB is also opened read-only.

```bash
curl -sS -H "Authorization: Bearer $API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"sql":"SELECT local_date, distance_m FROM workouts ORDER BY start_at DESC"}' \
  "$HOST/api/query"
```

**POST /api/import** — upload an Apple Health export ZIP (up to ~500MB). Runs `python run.py --fresh` into `HEALTH_DATA_DIR`, then rebuilds `index.html`. Returns **202** and a job id; poll status (imports take several minutes on a full export).

```bash
# On a Mac, after Health.app → Profile → Export All Health Data
curl -X POST -H "Authorization: Bearer $API_TOKEN" \
  -F "file=@$HOME/Downloads/export.zip" \
  "$HOST/api/import"
```

Optional form field `skip_routes=true` skips GPX parsing (faster).

**GET /api/import** and **GET /api/import/:id** — job status (`queued` → `running` → `succeeded` / `failed`)

```bash
curl -sS -H "Authorization: Bearer $API_TOKEN" "$HOST/api/import"
```

Only one import runs at a time; a second POST returns 409. `/api/*` is rate-limited (stricter on query and import).
