"use strict";

const { spawn } = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");

const STATUS_FILE = "import-status.json";
const ACTIVE = new Set(["queued", "running"]);

function runCommand(bin, args, options) {
  return new Promise((resolve, reject) => {
    const child = spawn(bin, args, {
      cwd: options.cwd,
      env: options.env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
      options.onLog?.(chunk.toString());
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
      options.onLog?.(chunk.toString());
    });
    child.on("error", reject);
    child.on("close", (code) => {
      resolve({ code, stdout, stderr });
    });
  });
}

function findExportXml(root) {
  const stack = [root];
  while (stack.length) {
    const dir = stack.pop();
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const ent of entries) {
      if (ent.name === "__MACOSX" || ent.name.startsWith(".")) continue;
      const full = path.join(dir, ent.name);
      if (ent.isFile() && ent.name === "export.xml") return full;
      if (ent.isDirectory()) stack.push(full);
    }
  }
  return null;
}

class ImportManager {
  constructor({ repoRoot, dataDir, python, dashboardOutput }) {
    this.repoRoot = repoRoot;
    this.dataDir = dataDir;
    this.python = python;
    this.dashboardOutput = dashboardOutput;
    this.current = this._loadLast();
  }

  getJob(id) {
    if (id) {
      if (this.current && this.current.id === id) return this.current;
      return null;
    }
    return this.current || { status: "idle" };
  }

  isBusy() {
    return Boolean(this.current && ACTIVE.has(this.current.status));
  }

  start({ zipPath, skipRoutes = false }) {
    if (this.isBusy()) {
      const err = new Error("An import is already running");
      err.code = "BUSY";
      throw err;
    }
    const job = {
      id: crypto.randomUUID(),
      status: "queued",
      stage: "queued",
      skip_routes: Boolean(skipRoutes),
      started_at: new Date().toISOString(),
      finished_at: null,
      message: "Import queued",
      log_tail: [],
    };
    this.current = job;
    this._persist(job);
    setImmediate(() => {
      this._run(job, zipPath).catch((err) => {
        job.status = "failed";
        job.message = err.message || String(err);
        job.finished_at = new Date().toISOString();
        this._persist(job);
      });
    });
    return publicJob(job);
  }

  async _run(job, zipPath) {
    const workDir = fs.mkdtempSync(path.join(os.tmpdir(), "health-import-"));
    const onLog = (text) => {
      for (const line of text.split(/\r?\n/)) {
        if (line.trim()) job.log_tail.push(line.slice(0, 500));
      }
      if (job.log_tail.length > 80) {
        job.log_tail = job.log_tail.slice(-80);
      }
    };

    try {
      job.status = "running";
      job.stage = "unzip";
      job.message = "Extracting export zip";
      this._persist(job);

      const unzip = await runCommand(this.python, ["-m", "zipfile", "-e", zipPath, workDir], {
        cwd: this.repoRoot,
        env: process.env,
        onLog,
      });
      if (unzip.code !== 0) {
        throw new Error(unzip.stderr.trim() || "Failed to unzip export");
      }

      const exportXml = findExportXml(workDir);
      if (!exportXml) {
        throw new Error("export.xml not found in zip");
      }
      const exportDir = path.dirname(exportXml);

      job.stage = "import";
      job.message = "Running Python importer";
      this._persist(job);

      const importArgs = ["run.py", "--fresh"];
      if (job.skip_routes) importArgs.push("--skip-routes");
      const importer = await runCommand(this.python, importArgs, {
        cwd: this.repoRoot,
        env: {
          ...process.env,
          HEALTH_EXPORT_DIR: exportDir,
          HEALTH_DATA_DIR: this.dataDir,
        },
        onLog,
      });
      if (importer.code !== 0) {
        throw new Error(importer.stderr.trim() || importer.stdout.trim() || "Importer failed");
      }

      job.stage = "dashboard";
      job.message = "Regenerating dashboard";
      this._persist(job);

      const dashboardArgs = ["dashboard/build_dashboard.py"];
      if (this.dashboardOutput) {
        dashboardArgs.push("--output", this.dashboardOutput);
      }
      const dashboard = await runCommand(this.python, dashboardArgs, {
        cwd: this.repoRoot,
        env: {
          ...process.env,
          HEALTH_DATA_DIR: this.dataDir,
        },
        onLog,
      });
      if (dashboard.code !== 0) {
        throw new Error(dashboard.stderr.trim() || dashboard.stdout.trim() || "Dashboard rebuild failed");
      }

      job.status = "succeeded";
      job.stage = "done";
      job.message = "Import complete";
      job.finished_at = new Date().toISOString();
      this._persist(job);
    } catch (err) {
      job.status = "failed";
      job.stage = job.stage || "failed";
      job.message = err.message || String(err);
      job.finished_at = new Date().toISOString();
      this._persist(job);
    } finally {
      fs.rmSync(workDir, { recursive: true, force: true });
      if (zipPath) {
        fs.rmSync(zipPath, { force: true });
      }
    }
  }

  _statusPath() {
    return path.join(this.dataDir, STATUS_FILE);
  }

  _loadLast() {
    try {
      const raw = fs.readFileSync(this._statusPath(), "utf8");
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object") {
        if (ACTIVE.has(parsed.status)) {
          parsed.status = "failed";
          parsed.message = "Import interrupted by process restart";
          parsed.finished_at = parsed.finished_at || new Date().toISOString();
        }
        return parsed;
      }
    } catch {
      // no prior status
    }
    return null;
  }

  _persist(job) {
    try {
      fs.mkdirSync(this.dataDir, { recursive: true });
      fs.writeFileSync(this._statusPath(), JSON.stringify(publicJob(job), null, 2));
    } catch {
      // volume may be missing in some local tests
    }
  }
}

function publicJob(job) {
  return {
    id: job.id,
    status: job.status,
    stage: job.stage,
    skip_routes: job.skip_routes,
    started_at: job.started_at,
    finished_at: job.finished_at,
    message: job.message,
    log_tail: (job.log_tail || []).slice(-40),
  };
}

module.exports = { ImportManager, findExportXml, publicJob };
