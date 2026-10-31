"use strict";

const crypto = require("crypto");

function timingSafeEqualString(a, b) {
  const left = Buffer.from(String(a), "utf8");
  const right = Buffer.from(String(b), "utf8");
  const size = Math.max(left.length, right.length, 1);
  const padLeft = Buffer.alloc(size);
  const padRight = Buffer.alloc(size);
  left.copy(padLeft);
  right.copy(padRight);
  return crypto.timingSafeEqual(padLeft, padRight) && left.length === right.length;
}

function requireApiToken(token) {
  return function authMiddleware(req, res, next) {
    if (!token) {
      return res.status(503).json({
        error: "api_unavailable",
        message: "API_TOKEN is not set on the server",
      });
    }
    const header = req.get("authorization") || "";
    const match = header.match(/^Bearer\s+(\S+)$/i);
    const provided = match ? match[1] : "";
    if (!timingSafeEqualString(provided, token)) {
      return res.status(401).json({ error: "unauthorized" });
    }
    return next();
  };
}

module.exports = { timingSafeEqualString, requireApiToken };
