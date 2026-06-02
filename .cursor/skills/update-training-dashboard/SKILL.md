---
name: update-training-dashboard
description: >-
  Regenerates the static GitHub Pages training dashboard from training.db.
  Runs SQL queries and writes index.html at the repo root. Use when the user
  asks to update, refresh, or rebuild the dashboard, GitHub Pages site, or
  index.html after importing health data or changing dashboard charts.
---

# Update Training Dashboard

Static dashboard for GitHub Pages. Data lives in `../data/training.db` (outside the repo); the published page is `index.html` at the repo root with embedded JSON.

## When to run

- After `python run.py` (new Apple Health import)
- When dashboard charts or tables look stale
- After changing `dashboard/queries.py` or `dashboard/template.html`

## Regenerate

From the `health_data/` repo directory:

```bash
python dashboard/build_dashboard.py
```

Options:

- `--days 365` — daily chart window (default 365)
- `--output index.html` — output path (default: repo root)

## Verify

1. Command prints `Wrote index.html (... bytes)` with exit code 0
2. Open `index.html` locally in a browser (file:// or simple HTTP server)
3. Confirm header shows current date range and five tabs load charts

## Architecture

| File | Role |
|------|------|
| `dashboard/queries.py` | SQL → JSON payload sections |
| `dashboard/template.html` | HTML/CSS/JS shell; `__DASHBOARD_DATA__` placeholder |
| `dashboard/build_dashboard.py` | Queries DB, embeds JSON, writes `index.html` |
| `index.html` | Generated static page — commit for GitHub Pages |

## Adding a new chart

1. Add query fields in `dashboard/queries.py`
2. Add chart/table markup + render logic in `dashboard/template.html`
3. Run `python dashboard/build_dashboard.py`
4. Commit both source changes and regenerated `index.html`

## GitHub Pages

Enable Pages on the repo with source **Deploy from branch** → branch `main` (or default) → folder `/ (root)`. The site serves `index.html` at the repo root.

## Do not

- Commit `training.db` or raw Apple export data
- Hand-edit embedded JSON in `index.html` — regenerate via the build script
