"use strict";

const fs = require("fs");
const { DatabaseSync } = require("node:sqlite");
const { dbFile } = require("./config");

function openReadonly(dir) {
  const file = dbFile(dir);
  if (!fs.existsSync(file)) {
    const err = new Error(`database not found at ${file}`);
    err.code = "DB_MISSING";
    throw err;
  }
  return new DatabaseSync(file, { readOnly: true });
}

function withDb(dir, fn) {
  const db = openReadonly(dir);
  try {
    return fn(db);
  } finally {
    db.close();
  }
}

function quoteIdent(name) {
  if (typeof name !== "string" || !/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) {
    throw new Error("invalid identifier");
  }
  return `"${name}"`;
}

function getSchema(dir) {
  return withDb(dir, (db) => {
    const objects = db
      .prepare(
        `
        SELECT name, type FROM sqlite_master
        WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'
        ORDER BY type, name
        `,
      )
      .all();
    return objects.map((obj) => {
      const columns = db.prepare(`PRAGMA table_info(${quoteIdent(obj.name)})`).all();
      return {
        name: obj.name,
        type: obj.type,
        columns: columns.map((col) => ({
          name: col.name,
          type: col.type,
          notnull: Boolean(col.notnull),
          pk: Boolean(col.pk),
        })),
      };
    });
  });
}

module.exports = { openReadonly, withDb, getSchema, quoteIdent };
