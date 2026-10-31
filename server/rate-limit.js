"use strict";

function rateLimit({ windowMs, max, error = "rate_limited" }) {
  const hits = new Map();
  return function rateLimitMiddleware(req, res, next) {
    const key = req.ip || req.socket?.remoteAddress || "unknown";
    const now = Date.now();
    const recent = (hits.get(key) || []).filter((t) => now - t < windowMs);
    if (recent.length >= max) {
      res.set("Retry-After", String(Math.ceil(windowMs / 1000)));
      return res.status(429).json({ error, message: "Too many requests" });
    }
    recent.push(now);
    hits.set(key, recent);
    return next();
  };
}

module.exports = { rateLimit };
