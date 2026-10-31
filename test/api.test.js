"use strict";

const { spawnSync } = require("child_process");
const assert = require("node:assert/strict");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { test, before, after } = require("node:test");
const { DatabaseSync } = require("node:sqlite");
const { createApp } = require("../server/app");
const { validateSelect } = require("../server/sql-guard");

const REPO = path.resolve(__dirname, "..");
const TOKEN = "test-token-fixture";
const WORK = fs.mkdtempSync(path.join(os.tmpdir(), "health-api-test-"));
const DATA_DIR = path.join(WORK, "data");
const DB_PATH = path.join(DATA_DIR, "training.db");

function buildFixtureDb() {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  const schema = fs.readFileSync(path.join(REPO, "schema", "schema.sql"), "utf8");
  const seed = fs.readFileSync(path.join(REPO, "test", "fixtures", "seed.sql"), "utf8");
  const db = new DatabaseSync(DB_PATH);
  db.exec(schema);
  db.exec(seed);
  db.close();
}

function listen(app) {
  return new Promise((resolve) => {
    const server = app.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      resolve({ server, base: `http://127.0.0.1:${port}` });
    });
  });
}

async function request(base, pathname, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.token) headers.Authorization = `Bearer ${options.token}`;
  const res = await fetch(`${base}${pathname}`, {
    method: options.method || "GET",
    headers,
    body: options.body,
  });
  const text = await res.text();
  let json;
  try {
    json = JSON.parse(text);
  } catch {
    json = null;
  }
  return { status: res.status, headers: res.headers, text, json };
}

function pythonConfigPaths() {
  const script = `
import os, sys
sys.path.insert(0, ${JSON.stringify(REPO)})
from parse.config import DATA_DIR, EXPORT_DIR, DB_PATH
print(DATA_DIR)
print(EXPORT_DIR)
print(DB_PATH)
`;
  const env = {
    ...process.env,
    HEALTH_DATA_DIR: "/tmp/custom-data",
    HEALTH_EXPORT_DIR: "/tmp/custom-export",
  };
  const result = spawnSync("python3", ["-c", script], { encoding: "utf8", env });
  assert.equal(result.status, 0, result.stderr);
  const [data, exp, db] = result.stdout.trim().split("\n");
  return { data, exp, db };
}

let server;
let base;

before(async () => {
  buildFixtureDb();
  const app = createApp({
    apiToken: TOKEN,
    dataDir: DATA_DIR,
    repoRoot: REPO,
    python: "python3",
  });
  ({ server, base } = await listen(app));
});

after(async () => {
  await new Promise((resolve) => server.close(resolve));
  fs.rmSync(WORK, { recursive: true, force: true });
});

test("GET / serves the dashboard", async () => {
  const res = await request(base, "/");
  assert.equal(res.status, 200);
  assert.match(res.text, /Training Dashboard/);
});

test("GET /health is public", async () => {
  const res = await request(base, "/health");
  assert.equal(res.status, 200);
  assert.equal(res.json.ok, true);
});

test("API rejects missing and wrong tokens", async () => {
  const missing = await request(base, "/api/health");
  assert.equal(missing.status, 401);
  const wrong = await request(base, "/api/health", { token: "nope" });
  assert.equal(wrong.status, 401);
});

test("GET /api/health describes the fixture DB", async () => {
  const res = await request(base, "/api/health", { token: TOKEN });
  assert.equal(res.status, 200);
  assert.equal(res.json.ok, true);
  assert.equal(res.json.db.exists, true);
  assert.match(res.json.db.path, /training\.db$/);
});

test("GET /api/schema lists tables and views", async () => {
  const res = await request(base, "/api/schema", { token: TOKEN });
  assert.equal(res.status, 200);
  const names = res.json.objects.map((o) => o.name);
  assert.ok(names.includes("workouts"));
  assert.ok(names.includes("daily_metrics"));
  assert.ok(names.includes("v_workout_context"));
  assert.ok(names.includes("v_weekly_training"));
  const workouts = res.json.objects.find((o) => o.name === "workouts");
  assert.ok(workouts.columns.some((c) => c.name === "distance_m"));
});

test("GET /api/runs returns running workouts with pace and HR", async () => {
  const res = await request(base, "/api/runs?since=2026-01-01&limit=10", { token: TOKEN });
  assert.equal(res.status, 200);
  assert.equal(res.json.count, 2);
  const first = res.json.runs[0];
  assert.equal(first.id, "run002");
  assert.equal(first.miles, 5);
  assert.equal(first.avg_hr, 151);
  const fiveK = res.json.runs.find((r) => r.id === "run001");
  assert.equal(fiveK.elev_gain_m, 42.5);
  assert.ok(fiveK.pace_min_per_mile > 6);
});

test("GET /api/weekly and /api/daily", async () => {
  const weekly = await request(base, "/api/weekly", { token: TOKEN });
  assert.equal(weekly.status, 200);
  assert.ok(weekly.json.weeks.length >= 1);
  const totalRuns = weekly.json.weeks.reduce((sum, w) => sum + Number(w.run_count || 0), 0);
  assert.equal(totalRuns, 2);

  const daily = await request(base, "/api/daily?since=2026-01-11", { token: TOKEN });
  assert.equal(daily.status, 200);
  assert.equal(daily.json.count, 2);
  assert.equal(daily.json.days[0].local_date, "2026-01-12");
  assert.equal(daily.json.days[0].resting_hr, 51);
});

test("GET /api/workouts/:id", async () => {
  const res = await request(base, "/api/workouts/run001", { token: TOKEN });
  assert.equal(res.status, 200);
  assert.equal(res.json.workout.activity_type, "HKWorkoutActivityTypeRunning");
  assert.equal(res.json.workout.resting_hr, 52);
  assert.equal(res.json.statistics[0].avg_value, 148);
  assert.equal(res.json.route.elev_gain_m, 42.5);
  const missing = await request(base, "/api/workouts/nope", { token: TOKEN });
  assert.equal(missing.status, 404);
});

test("POST /api/query allows SELECT and rejects writes", async () => {
  const ok = await request(base, "/api/query", {
    token: TOKEN,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sql: "SELECT id, local_date FROM workouts ORDER BY local_date" }),
  });
  assert.equal(ok.status, 200);
  assert.equal(ok.json.count, 3);

  const blocked = await request(base, "/api/query", {
    token: TOKEN,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sql: "DELETE FROM workouts" }),
  });
  assert.equal(blocked.status, 400);
  assert.equal(blocked.json.error, "invalid_sql");

  const multi = validateSelect("SELECT 1; DROP TABLE workouts");
  assert.equal(multi.ok, false);
});

test("API_TOKEN unset returns 503 on /api/*", async () => {
  const app = createApp({ apiToken: "", dataDir: DATA_DIR, repoRoot: REPO });
  const { server: s, base: b } = await listen(app);
  try {
    const res = await request(b, "/api/health", { token: TOKEN });
    assert.equal(res.status, 503);
    assert.equal(res.json.error, "api_unavailable");
    const dash = await request(b, "/");
    assert.equal(dash.status, 200);
  } finally {
    await new Promise((resolve) => s.close(resolve));
  }
});

test("Python config honors HEALTH_* env vars", () => {
  const paths = pythonConfigPaths();
  assert.match(paths.data, /custom-data$/);
  assert.match(paths.exp, /custom-export$/);
  assert.match(paths.db, /training\.db$/);
});

test("POST /api/import ingests a tiny Apple Health zip", async () => {
  const importDir = fs.mkdtempSync(path.join(os.tmpdir(), "health-import-test-"));
  const zipPath = path.join(importDir, "export.zip");
  const xml = path.join(REPO, "test", "fixtures", "minimal-export.xml");
  const staging = path.join(importDir, "apple_health_export");
  fs.mkdirSync(staging);
  fs.copyFileSync(xml, path.join(staging, "export.xml"));
  const zip = spawnSync("python3", ["-m", "zipfile", "-c", zipPath, "apple_health_export"], {
    cwd: importDir,
    encoding: "utf8",
  });
  assert.equal(zip.status, 0, zip.stderr);

  const importData = path.join(importDir, "data");
  fs.mkdirSync(importData);
  const app = createApp({
    apiToken: TOKEN,
    dataDir: importData,
    repoRoot: REPO,
    python: "python3",
    dashboardOutput: path.join(importDir, "index.html"),
  });
  const { server: s, base: b } = await listen(app);
  try {
    const boundary = "----HealthTestBoundary";
    const zipBuf = fs.readFileSync(zipPath);
    const prefix = Buffer.from(
      `--${boundary}\r\nContent-Disposition: form-data; name="skip_routes"\r\n\r\ntrue\r\n` +
        `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="export.zip"\r\n` +
        `Content-Type: application/zip\r\n\r\n`,
    );
    const suffix = Buffer.from(`\r\n--${boundary}--\r\n`);
    const body = Buffer.concat([prefix, zipBuf, suffix]);
    const posted = await request(b, "/api/import", {
      token: TOKEN,
      method: "POST",
      headers: {
        "Content-Type": `multipart/form-data; boundary=${boundary}`,
        "Content-Length": String(body.length),
      },
      body,
    });
    assert.equal(posted.status, 202, JSON.stringify(posted.json));
    assert.equal(posted.json.status, "queued");

    let job;
    for (let i = 0; i < 40; i += 1) {
      const status = await request(b, `/api/import/${posted.json.id}`, { token: TOKEN });
      job = status.json;
      if (job.status === "succeeded" || job.status === "failed") break;
      await new Promise((r) => setTimeout(r, 250));
    }
    assert.equal(job.status, "succeeded", JSON.stringify(job));

    const runs = await request(b, "/api/runs", { token: TOKEN });
    assert.equal(runs.status, 200);
    assert.equal(runs.json.count, 1);
    assert.equal(runs.json.runs[0].avg_hr, 145);
    assert.ok(runs.json.runs[0].miles > 3);
  } finally {
    await new Promise((resolve) => s.close(resolve));
    fs.rmSync(importDir, { recursive: true, force: true });
  }
});
