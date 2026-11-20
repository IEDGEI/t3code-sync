// SQLite >=3.43 is required for T3's contentless FTS5 search index.
// Python plans the changes; this worker writes canonical events and the matching
// T3 0.1.9 projections atomically. It waits for a parent safety/backup handshake.
'use strict';
const crypto = require('node:crypto');
const readline = require('node:readline');
const { DatabaseSync } = require('node:sqlite');
let db;
let transaction = false;
const send = value => process.stdout.write(JSON.stringify(value) + '\n');
const rows = sql => db.prepare(sql).all().map(row => Object.values(row));
function digestSchema(tables) {
  return crypto.createHash('sha256').update(JSON.stringify(tables.map(name => {
    const row = db.prepare("SELECT sql FROM sqlite_master WHERE type='table' AND name=?").get(name);
    if (!row) throw Error('Required T3 table is missing.');
    return [name, row.sql];
  }))).digest('hex');
}
function snapshotToken() {
  const digest = crypto.createHash('sha256');
  for (const query of [
    'SELECT COALESCE(MAX(sequence),0),COUNT(*) FROM orchestration_events',
    'SELECT * FROM orchestration_v2_projection_metadata ORDER BY projection_name',
    'SELECT thread_id,payload_json FROM orchestration_v2_projection_threads ORDER BY thread_id',
    'SELECT message_id,payload_json FROM orchestration_v2_projection_messages ORDER BY message_id',
  ]) for (const row of rows(query)) digest.update(JSON.stringify(row) + '\n');
  return digest.digest('hex');
}
function project(event) {
  const p = event.payload;
  if ((p.threadId || p.id) !== event.threadId && event.type === 'thread.metadata-updated')
    throw Error('Thread identity mismatch.');
  if (event.type !== 'thread.metadata-updated' && p.threadId !== event.threadId)
    throw Error('Message thread identity mismatch.');
  if (event.type === 'message.updated') {
    if (!['user','assistant'].includes(p.role) || p.streaming || p.runId !== null || p.nodeId !== null)
      throw Error('Unsupported message shape.');
    db.prepare(`INSERT INTO orchestration_v2_projection_messages
      (message_id,thread_id,run_id,node_id,role,streaming,created_at,updated_at,payload_json,search_text)
      VALUES (?,?,NULL,NULL,?,0,?,?,?,?)`).run(
      p.id, p.threadId, p.role, p.createdAt, p.updatedAt, JSON.stringify(p), p.text);
  } else if (event.type === 'turn-item.updated') {
    if (!['user_message','assistant_message'].includes(p.type) || p.runId !== null || p.nodeId !== null)
      throw Error('Unsupported timeline item shape.');
    db.prepare(`INSERT INTO orchestration_v2_projection_turn_items
      (turn_item_id,thread_id,run_id,node_id,provider_thread_id,provider_turn_id,parent_item_id,
       ordinal,type,status,updated_at,payload_json)
      VALUES (?,?,NULL,NULL,NULL,NULL,NULL,? ,?,'completed',?,?)`).run(
      p.id,p.threadId,p.ordinal,p.type,p.updatedAt,JSON.stringify(p));
    db.prepare(`INSERT INTO orchestration_v2_turn_item_positions(thread_id,turn_item_id,ordinal)
      VALUES (?,?,?)`).run(p.threadId,p.id,p.ordinal);
  } else if (event.type === 'thread.metadata-updated') {
    const result = db.prepare(`UPDATE orchestration_v2_projection_threads
      SET updated_at=?,payload_json=? WHERE thread_id=? AND deleted_at IS NULL`).run(
      p.updatedAt,JSON.stringify(p),event.threadId);
    if (result.changes !== 1) throw Error('Imported T3 thread is missing.');
  } else throw Error('Unsupported auto-sync event type.');
}
function prepare(input) {
  db = new DatabaseSync(process.argv[2]);
  db.exec('PRAGMA busy_timeout=5000; BEGIN IMMEDIATE');
  transaction = true;
  const migration = db.prepare('SELECT MAX(migration_id) version FROM effect_sql_migrations').get().version;
  if (migration !== input.migration || digestSchema(input.tables) !== input.schema)
    throw Error('Unsupported T3 database schema.');
  if (snapshotToken() !== input.plan.snapshot) throw Error('T3 database changed during preparation.');
  const checkpoint = db.prepare(`SELECT last_sequence FROM orchestration_v2_projection_metadata
    WHERE projection_name='thread-projections'`).get()?.last_sequence;
  const pending = db.prepare(`SELECT COUNT(*) n FROM orchestration_events WHERE sequence>?
    AND application_event_version=2 AND aggregate_kind='thread'`).get(checkpoint).n;
  if (pending) throw Error('T3 has unapplied events; refusing to advance its checkpoint.');
  if (db.prepare('PRAGMA quick_check').get().quick_check !== 'ok') throw Error('Database integrity check failed.');
  let sequence = checkpoint;
  let written = 0;
  for (const event of input.plan.events) {
    if (!event.id.startsWith('codex-autosync:v1:')) throw Error('Unexpected event identity.');
    if (db.prepare('SELECT 1 FROM orchestration_events WHERE event_id=?').get(event.id)) continue;
    const version = db.prepare(`SELECT COALESCE(MAX(stream_version)+1,0) v FROM orchestration_events
      WHERE aggregate_kind='thread' AND stream_id=?`).get(event.threadId).v;
    const result = db.prepare(`INSERT INTO orchestration_events
      (event_id,aggregate_kind,stream_id,stream_version,event_type,occurred_at,
       command_id,causation_event_id,correlation_id,actor_kind,payload_json,metadata_json,application_event_version)
      VALUES (?,'thread',?,?,?,?,NULL,NULL,NULL,'server',?,'{}',2)`).run(
      event.id,event.threadId,version,event.type,event.occurredAt,JSON.stringify(event.payload));
    project(event);
    sequence = Number(result.lastInsertRowid);
    written++;
  }
  if (written) db.prepare(`UPDATE orchestration_v2_projection_metadata SET last_sequence=?,updated_at=?
    WHERE projection_name='thread-projections'`).run(sequence,new Date().toISOString());
  if (db.prepare('PRAGMA quick_check').get().quick_check !== 'ok') throw Error('Post-write integrity check failed.');
  send({ready:true,events:written});
}
(async () => {
  const input = readline.createInterface({input:process.stdin,crlfDelay:Infinity});
  let prepared = false;
  try {
    for await (const line of input) {
      const command = JSON.parse(line);
      if (!prepared) { prepare(command); prepared = true; continue; }
      if (command.commit !== true) throw Error('Parent cancelled the update.');
      db.exec('COMMIT'); transaction = false;
      send({committed:true});
      break;
    }
  } catch (error) {
    send({error:error.message});
    process.exitCode = 1;
  } finally {
    if (transaction) { try { db.exec('ROLLBACK'); } catch {} }
    if (db) db.close();
    input.close();
  }
})().catch(error => { send({error:error.message}); process.exitCode = 1; });
