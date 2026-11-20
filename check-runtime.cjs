'use strict';
try {
  const { DatabaseSync } = require('node:sqlite');
  const db = new DatabaseSync(':memory:');
  db.exec("CREATE VIRTUAL TABLE runtime_check USING fts5(text, content='', contentless_delete=1)");
  const result = {node: process.versions.node, sqlite: db.prepare('SELECT sqlite_version() version').get().version};
  db.close();
  process.stdout.write(JSON.stringify(result) + '\n');
} catch (error) {
  process.stderr.write('Node.js 22.13+ with modern SQLite/FTS5 is required: ' + error.message + '\n');
  process.exitCode = 1;
}
