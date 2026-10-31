"use strict";

const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const express = require("express");
const multer = require("multer");
const { requireApiToken } = require("./auth");
const { dbFile } = require("./config");
const { getSchema, withDb } = require("./db");
const { ImportManager } = require("./import-job");
const { rateLimit } = require("./rate-limit");
const { validateSelect } = require("./sql-guard");

const INDEX_HTML = path.resolve(__dirname, "..", "index.html");
const MAX_UPLOAD_BYTES = 500 * 1024 * 1024;
const QUERY_ROW_LIMIT = 200;

function parseLimit(value, fallback = 50, max = 500) {
  const n = Number.parseInt(value, 10);
  if (!Number.isFinite(n) || n < 1) return fallback;
  return Math.min(n, max);
}

function parseSince(value) {
  if (!value) return null;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const err = new Error("since must be YYYY-MM-DD");
    err.code = "BAD_REQUEST";
    throw err;
  }
  return value;
}

function pythonVersion(python) {
  const result = spawnSync(python, ["--version"], { encoding: "utf8" });
  const text = `${result.stdout || ""} ${result.stderr || ""}`.trim();
  return result.status === 0 ? text : null;
}

function sendError(res, err) {
  if (err.code === "DB_MISSING") {
    return res.status(503).json({ error: "db_unavailable", message: err.message });
  }
  if (err.code === "BAD_REQUEST") {
    return res.status(400).json({ error: "bad_request", message: err.message });
  }
  console.error(err);
  return res.status(500).json({ error: "internal_error", message: err.message });
}

function createApp(options = {}) {
  const token = options.apiToken !== undefined ? options.apiToken : process.env.API_TOKEN || null;
  const dataDir = options.dataDir || process.env.HEALTH_DATA_DIR || "/data";
  const repoRoot = options.repoRoot || path.resolve(__dirname, "..");
  const python = options.python || process.env.PYTHON || "python3";
  const imports =
    options.imports ||
    new ImportManager({
      repoRoot,
      dataDir,
      python,
      dashboardOutput: options.dashboardOutput,
    });

  const uploadDir = options.uploadDir || path.join(require("os").tmpdir(), "health-uploads");
  fs.mkdirSync(uploadDir, { recursive: true });
  const upload = multer({
    dest: uploadDir,
    limits: { fileSize: MAX_UPLOAD_BYTES, files: 1 },
  });

  const app = express();
  app.disable("x-powered-by");
  app.use(express.json({ limit: "1mb" }));
  app.use((req, res, next) => {
    res.set("Access-Control-Allow-Origin", "*");
    res.set("Access-Control-Allow-Headers", "Authorization, Content-Type");
    res.set("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    if (req.method === "OPTIONS") return res.status(204).end();
    return next();
  });

  app.get("/", (_req, res) => {
    if (!fs.existsSync(INDEX_HTML)) {
      return res.status(404).type("text").send("index.html not found");
    }
    return res.sendFile(INDEX_HTML);
  });

  app.get("/health", (_req, res) => {
    res.json({ ok: true });
  });

  const api = express.Router();
  api.use(rateLimit({ windowMs: 60_000, max: 120 }));
  api.use(requireApiToken(token && String(token).trim() ? String(token) : null));

  api.get("/health", (_req, res) => {
    const file = dbFile(dataDir);
    const exists = fs.existsSync(file);
    res.json({
      ok: true,
      db: { path: file, exists },
      python: pythonVersion(python),
      import: imports.getJob(),
    });
  });

  api.get("/schema", (_req, res) => {
    try {
      res.json({ objects: getSchema(dataDir) });
    } catch (err) {
      sendError(res, err);
    }
  });

  api.get("/runs", (req, res) => {
    try {
      const since = parseSince(req.query.since);
      const limit = parseLimit(req.query.limit, 50, 200);
      const rows = withDb(dataDir, (db) =>
        db
          .prepare(
            `
            SELECT
              w.id,
              w.local_date,
              w.start_at,
              w.end_at,
              w.duration_sec,
              w.distance_m,
              ROUND(w.distance_m / 1609.344, 2) AS miles,
              ROUND(w.duration_sec / NULLIF(w.distance_m / 1609.344, 0) / 60.0, 2) AS pace_min_per_mile,
              w.energy_kcal,
              hr.avg_value AS avg_hr,
              hr.max_value AS max_hr,
              hr.min_value AS min_hr,
              r.elev_gain_m,
              w.route_file
            FROM workouts w
            LEFT JOIN workout_statistics hr
              ON hr.workout_id = w.id
             AND hr.stat_type = 'HKQuantityTypeIdentifierHeartRate'
            LEFT JOIN routes r ON r.workout_id = w.id
            WHERE w.activity_type = 'HKWorkoutActivityTypeRunning'
              AND w.distance_m IS NOT NULL AND w.distance_m > 0
              AND (? IS NULL OR w.local_date >= ?)
            ORDER BY w.start_at DESC
            LIMIT ?
            `,
          )
          .all(since, since, limit),
      );
      res.json({ count: rows.length, runs: rows });
    } catch (err) {
      sendError(res, err);
    }
  });

  api.get("/weekly", (_req, res) => {
    try {
      const weeks = withDb(dataDir, (db) =>
        db
          .prepare(
            `
            SELECT week, workout_count, run_count, run_distance_m, run_duration_sec,
                   ROUND(run_distance_m / 1609.344, 2) AS run_miles
            FROM v_weekly_training
            ORDER BY week
            `,
          )
          .all(),
      );
      res.json({ count: weeks.length, weeks });
    } catch (err) {
      sendError(res, err);
    }
  });

  api.get("/daily", (req, res) => {
    try {
      const since = parseSince(req.query.since);
      const limit = parseLimit(req.query.limit, 90, 730);
      const rows = withDb(dataDir, (db) =>
        db
          .prepare(
            `
            SELECT
              dm.local_date,
              dm.resting_hr,
              dm.hrv_sdnn,
              dm.vo2_max,
              dm.body_mass_kg,
              dm.sleep_total_min,
              dm.sleep_deep_min,
              dm.sleep_rem_min,
              dm.sleep_core_min,
              dm.sleep_awake_min,
              dm.steps,
              dm.active_energy_kcal,
              dm.workout_count,
              dm.run_count,
              dm.run_distance_m,
              a.exercise_min,
              a.stand_hours
            FROM daily_metrics dm
            LEFT JOIN activity_summaries a ON a.local_date = dm.local_date
            WHERE ? IS NULL OR dm.local_date >= ?
            ORDER BY dm.local_date DESC
            LIMIT ?
            `,
          )
          .all(since, since, limit),
      );
      res.json({ count: rows.length, days: rows });
    } catch (err) {
      sendError(res, err);
    }
  });

  api.get("/workouts/:id", (req, res) => {
    try {
      const id = req.params.id;
      if (!/^[A-Za-z0-9_-]{1,64}$/.test(id)) {
        return res.status(400).json({ error: "bad_request", message: "invalid workout id" });
      }
      const payload = withDb(dataDir, (db) => {
        const workout = db.prepare(`SELECT * FROM v_workout_context WHERE id = ?`).get(id);
        if (!workout) return null;
        const statistics = db
          .prepare(
            `
            SELECT stat_type, start_at, end_at, sum_value, avg_value, min_value, max_value, unit
            FROM workout_statistics WHERE workout_id = ? ORDER BY stat_type
            `,
          )
          .all(id);
        const metadata = db
          .prepare(`SELECT key, value FROM workout_metadata WHERE workout_id = ? ORDER BY key`)
          .all(id);
        const route = db
          .prepare(
            `
            SELECT id, gpx_filename, point_count, distance_m, elev_gain_m,
                   duration_sec, avg_speed_mps, max_speed_mps
            FROM routes WHERE workout_id = ?
            `,
          )
          .get(id);
        return { workout, statistics, metadata, route: route || null };
      });
      if (!payload) return res.status(404).json({ error: "not_found" });
      return res.json(payload);
    } catch (err) {
      return sendError(res, err);
    }
  });

  api.post("/query", rateLimit({ windowMs: 60_000, max: 30, error: "query_rate_limited" }), (req, res) => {
    try {
      const checked = validateSelect(req.body?.sql);
      if (!checked.ok) {
        return res.status(400).json({ error: "invalid_sql", message: checked.error });
      }
      const limit = parseLimit(req.body?.limit, QUERY_ROW_LIMIT, QUERY_ROW_LIMIT);
      const rows = withDb(dataDir, (db) => {
        const wrapped = `SELECT * FROM (${checked.sql}) AS _q LIMIT ?`;
        return db.prepare(wrapped).all(limit);
      });
      return res.json({ count: rows.length, limit, rows });
    } catch (err) {
      if (err.code === "DB_MISSING") return sendError(res, err);
      return res.status(400).json({ error: "query_failed", message: err.message });
    }
  });

  const importLimit = rateLimit({ windowMs: 60 * 60_000, max: 8, error: "import_rate_limited" });

  api.get("/import", (_req, res) => {
    res.json(imports.getJob());
  });

  api.get("/import/:id", (req, res) => {
    const job = imports.getJob(req.params.id);
    if (!job) return res.status(404).json({ error: "not_found" });
    return res.json(job);
  });

  api.post("/import", importLimit, (req, res) => {
    upload.single("file")(req, res, (err) => {
      if (err) {
        const status = err.code === "LIMIT_FILE_SIZE" ? 413 : 400;
        return res.status(status).json({
          error: "upload_failed",
          message: err.message || "Upload failed",
        });
      }
      if (!req.file) {
        return res.status(400).json({ error: "bad_request", message: "multipart field 'file' is required" });
      }
      const skipRoutes =
        req.body?.skip_routes === "1" ||
        req.body?.skip_routes === "true" ||
        req.query.skip_routes === "1";
      try {
        const job = imports.start({ zipPath: req.file.path, skipRoutes });
        return res.status(202).json(job);
      } catch (startErr) {
        fs.rmSync(req.file.path, { force: true });
        if (startErr.code === "BUSY") {
          return res.status(409).json({ error: "import_busy", message: startErr.message });
        }
        return sendError(res, startErr);
      }
    });
  });

  app.use("/api", api);

  app.use((err, _req, res, _next) => {
    if (err instanceof multer.MulterError) {
      const status = err.code === "LIMIT_FILE_SIZE" ? 413 : 400;
      return res.status(status).json({ error: "upload_failed", message: err.message });
    }
    return sendError(res, err);
  });

  return app;
}

module.exports = { createApp, MAX_UPLOAD_BYTES, QUERY_ROW_LIMIT };
