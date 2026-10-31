"use strict";

const FORBIDDEN =
  /\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|REPLACE|PRAGMA|VACUUM|REINDEX|GRANT|REVOKE|COPY|LOAD_EXTENSION|TRUNCATE)\b/i;

function validateSelect(sql) {
  if (typeof sql !== "string") {
    return { ok: false, error: "sql must be a string" };
  }
  let text = sql.trim();
  if (!text) {
    return { ok: false, error: "sql is empty" };
  }
  if (text.includes(";")) {
    if (text.endsWith(";")) {
      text = text.slice(0, -1).trim();
    }
    if (text.includes(";")) {
      return { ok: false, error: "multiple statements are not allowed" };
    }
  }
  if (text.includes("--") || text.includes("/*") || text.includes("*/")) {
    return { ok: false, error: "comments are not allowed" };
  }
  if (!/^(SELECT|WITH)\b/i.test(text)) {
    return { ok: false, error: "only a single SELECT (or WITH … SELECT) is allowed" };
  }
  if (/\bINTO\b/i.test(text)) {
    return { ok: false, error: "SELECT INTO is not allowed" };
  }
  if (FORBIDDEN.test(text)) {
    return { ok: false, error: "query contains a forbidden keyword" };
  }
  return { ok: true, sql: text };
}

module.exports = { validateSelect };
