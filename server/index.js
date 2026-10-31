"use strict";

const { createApp } = require("./app");
const { apiToken, dataDir, listenPort, pythonBin, REPO_ROOT } = require("./config");

const token = apiToken();
if (!token) {
  console.warn("API_TOKEN is not set: /api/* will return 503 until it is configured.");
}

const dir = dataDir();
const port = listenPort();
const app = createApp({
  apiToken: token,
  dataDir: dir,
  repoRoot: REPO_ROOT,
  python: pythonBin(),
});

app.listen(port, "0.0.0.0", () => {
  console.log(`Listening on 0.0.0.0:${port}`);
  console.log(`Dashboard: /`);
  console.log(`DB: ${dir}/training.db`);
});
