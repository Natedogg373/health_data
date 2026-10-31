"use strict";

const path = require("path");

const REPO_ROOT = path.resolve(__dirname, "..");

function dataDir() {
  return process.env.HEALTH_DATA_DIR || "/data";
}

function dbFile(dir = dataDir()) {
  return path.join(dir, "training.db");
}

function apiToken() {
  const value = process.env.API_TOKEN;
  return value && value.length > 0 ? value : null;
}

function listenPort() {
  const raw = process.env.PORT;
  const port = raw ? Number.parseInt(raw, 10) : 3000;
  return Number.isFinite(port) && port > 0 ? port : 3000;
}

function pythonBin() {
  return process.env.PYTHON || "python3";
}

module.exports = {
  REPO_ROOT,
  dataDir,
  dbFile,
  apiToken,
  listenPort,
  pythonBin,
};
