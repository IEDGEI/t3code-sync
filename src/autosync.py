"""Import and refresh settled Codex chats in matching T3 projects before launch.

Python 3.9+ and Node.js 22.13+; no third-party packages.
Codex storage is always read-only. Events and projections are committed together.
"""
import argparse
import bisect
import contextlib
import ctypes
import datetime as dt
import hashlib
import json
import ntpath
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from typing import Any, Dict, List, Optional
from transcripts import TranscriptError as SyncError, scan as scan_transcript, verify_guard

VERSION = "1.1.0"
SUPPORTED_MIGRATION = 81
SCHEMA_TABLES = (
    "orchestration_events", "orchestration_v2_projection_threads",
    "orchestration_v2_projection_messages", "orchestration_v2_projection_turn_items",
    "orchestration_v2_projection_runs", "orchestration_v2_projection_metadata",
    "orchestration_v2_turn_item_positions",
    "projection_projects", "orchestration_v2_projection_provider_threads", "provider_session_runtime",
)
# Filled from, and verified against, the installed T3 0.1.9 database.
SUPPORTED_SCHEMA = "0adb585032548396648a76542b93c8415ce075fbe9063be34948ffe4f04f5c50"
PREFIX = "codex-autosync:v1:"
MAX_BATCH_MESSAGES = 500
INITIAL_HISTORY_MESSAGES = 200


class ClosingConnection(sqlite3.Connection):
    """Commit/rollback like sqlite3's context manager, then release the handle."""
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def readonly(path: Path) -> sqlite3.Connection:
    # Path.as_uri quotes Korean names, spaces, '#' and '?' safely.
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5,
                         factory=ClosingConnection)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    return db


def schema_digest(db: sqlite3.Connection) -> str:
    definitions = []
    for name in SCHEMA_TABLES:
        row = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
        if row is None:
            raise SyncError("Required T3 table is missing: " + name)
        definitions.append([name, row[0]])
    return hashlib.sha256(json_text(definitions).encode()).hexdigest()


def verify_schema(db: sqlite3.Connection) -> None:
    migration = db.execute("SELECT MAX(migration_id) FROM effect_sql_migrations").fetchone()[0]
    if migration != SUPPORTED_MIGRATION or schema_digest(db) != SUPPORTED_SCHEMA:
        raise SyncError("Unsupported T3 database version; no changes were made.")


def snapshot_token(db: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for query in (
        "SELECT COALESCE(MAX(sequence),0),COUNT(*) FROM orchestration_events",
        "SELECT * FROM orchestration_v2_projection_metadata ORDER BY projection_name",
        "SELECT thread_id,payload_json FROM orchestration_v2_projection_threads ORDER BY thread_id",
        "SELECT message_id,payload_json FROM orchestration_v2_projection_messages ORDER BY message_id",
        "SELECT project_id,title,workspace_root,deleted_at,archived_at FROM projection_projects ORDER BY project_id",
        "SELECT provider_thread_id,payload_json FROM orchestration_v2_projection_provider_threads ORDER BY provider_thread_id",
        "SELECT thread_id,runtime_payload_json FROM provider_session_runtime ORDER BY thread_id",
    ):
        for row in db.execute(query):
            digest.update(json_text(list(row)).encode())
            digest.update(b"\n")
    return digest.hexdigest()


def _windows_processes():
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("pid", wintypes.DWORD), ("heap", ctypes.c_size_t),
                    ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                    ("parent", wintypes.DWORD), ("priority", wintypes.LONG),
                    ("flags", wintypes.DWORD), ("exe", wintypes.WCHAR * 260)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise SyncError("Cannot inspect running processes; refusing to write.")
    entry = Entry()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        more = kernel.Process32FirstW(handle, ctypes.byref(entry))
        if not more:
            raise SyncError("Process inventory is unavailable; refusing to write.")
        while more:
            yield int(entry.pid), entry.exe
            more = kernel.Process32NextW(handle, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(handle)


def t3_running(home: Path, exe: Path) -> bool:
    if os.name == "nt":
        processes = dict(_windows_processes())
        if not any(name.casefold() == "explorer.exe" for name in processes.values()):
            raise SyncError("Desktop process inventory is restricted; refusing to write.")
        if any(name.casefold() == exe.name.casefold() for name in processes.values()):
            return True
        runtime = home / "userdata" / "server-runtime.json"
        if runtime.exists():
            try:
                pid = json.loads(runtime.read_text(encoding="utf-8"))["pid"]
                # A stale pid reused by an unrelated process is not a T3 server.
                name = processes.get(pid, "").casefold()
                if name in ("node.exe", "bun.exe", "t3.exe", exe.name.casefold()):
                    return True
            except (ValueError, KeyError, TypeError):
                raise SyncError("Cannot verify T3 runtime ownership; refusing to write.")
        return False
    # The installed launcher targets Windows; tests provide an explicit guard.
    raise SyncError("Automatic process detection is supported on Windows only.")


@contextlib.contextmanager
def launch_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    handle.seek(0)
    if not handle.read(1):
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise SyncError("Another auto-sync launcher is already running.") from exc
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        # Closing releases the lock, including on exceptions.
        handle.close()


def content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    return "\n".join(part["text"].strip() for part in content
                     if isinstance(part, dict) and isinstance(part.get("text"), str)
                     and part["text"].strip())


def hidden_user(payload: Dict[str, Any]) -> bool:
    meta = payload.get("internal_chat_message_metadata_passthrough")
    if not isinstance(meta, dict):
        return False
    kinds = meta.get("content_item_kinds")
    if isinstance(kinds, list) and kinds:
        # Preserve actual user text and user responses, excluding harness/AGENTS envelopes.
        return not any(isinstance(kind, str) and kind.startswith("user.") for kind in kinds)
    return False


def source_identity(path: Path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def read_records(path: Path, byte_limit: Optional[int] = None) -> List[Dict[str, Any]]:
    return scan_transcript(path, byte_limit)[0]


def transcript_records(native_id: str, path: Path, paths: Dict[str, Path],
                       visited=None, byte_limit=None, cache_dir=None, writable=False, diagnostics=None):
    visited = set() if visited is None else set(visited)
    if native_id in visited or len(visited) >= 16:
        raise SyncError("Cyclic or excessively deep inherited Codex history.")
    visited.add(native_id)
    records, source_guard, stats = scan_transcript(path, byte_limit, cache_dir, writable)
    if diagnostics is not None:
        diagnostics.append(stats)
    guards = {str(path): source_guard}
    meta = next((r.get("payload", {}) for r in records if r.get("type") == "session_meta"), {})
    if meta.get("id", meta.get("session_id")) != native_id:
        raise SyncError("Source transcript identity differs from the imported chat.")
    base = meta.get("history_base")
    if base:
        parent_id = base.get("thread_id")
        end = base.get("end_byte_offset")
        if parent_id not in paths or not isinstance(end, int) or end < 0:
            raise SyncError("Inherited Codex history is unavailable.")
        inherited, inherited_guards = transcript_records(parent_id, paths[parent_id], paths, visited, end,
                                                        cache_dir, writable, diagnostics)
        guards.update(inherited_guards)
        records = [r for r in inherited if r.get("type") != "session_meta"] + records
    return records, guards


def parse_messages(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Mirror T3's deduplication, retaining all history for alignment, not just 200 items."""
    # Ignore the unfinished tail. Never import the latest still-running user turn.
    terminals = [i for i, r in enumerate(records) if r.get("type") == "event_msg"
                 and r.get("payload", {}).get("type") in ("task_complete", "turn_aborted")]
    if not terminals:
        raise SyncError("No settled Codex turn found; deferred.")
    records = records[:terminals[-1] + 1]
    skip = set()
    canonical = set()
    response_users = []

    def finish_turn():
        matching = {turn for _, turn, text in response_users if text in canonical}
        skip.update(index for index, turn, _ in response_users if turn in matching)
        canonical.clear()
        response_users.clear()

    for index, record in enumerate(records):
        payload = record.get("payload") or {}
        if record.get("type") == "response_item" and payload.get("type") == "message":
            if payload.get("role") == "assistant":
                finish_turn()
            elif payload.get("role") == "user":
                metadata = payload.get("internal_chat_message_metadata_passthrough") or {}
                turn = metadata.get("turn_id") if isinstance(metadata, dict) else None
                text = content_text(payload.get("content"))
                if turn and text:
                    response_users.append((index, turn, text))
        elif record.get("type") == "event_msg" and payload.get("type") == "user_message":
            canonical.add((payload.get("message") or "").strip())
    finish_turn()
    messages = []
    occurrences = {}
    for index, record in enumerate(records):
        payload = record.get("payload") or {}
        canonical_user = record.get("type") == "event_msg" and payload.get("type") == "user_message"
        response = record.get("type") == "response_item" and payload.get("type") == "message"
        if not canonical_user and not response:
            continue
        role = "user" if canonical_user else payload.get("role")
        text = payload.get("message", "") if canonical_user else content_text(payload.get("content"))
        if role not in ("user", "assistant") or not isinstance(text, str) or not text.strip():
            continue
        if canonical_user:
            for previous in reversed(messages):
                if previous["role"] == "assistant":
                    break
                if previous["response_user"] and previous["text"].strip() == text.strip():
                    messages.remove(previous)
                    break
        elif role == "user":
            if index in skip:
                continue
            duplicate = False
            for previous in reversed(messages):
                if previous["role"] == "assistant":
                    break
                if not previous["response_user"] and previous["text"].strip() == text.strip():
                    duplicate = True
                    break
            if duplicate:
                continue
        timestamp = record.get("timestamp")
        if not isinstance(timestamp, str):
            raise SyncError("A source message has no timestamp.")
        try:
            dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise SyncError("Invalid source message timestamp.") from exc
        identity = (payload.get("id"), role, timestamp, text)
        occurrence = occurrences.get(identity, 0)
        occurrences[identity] = occurrence + 1
        messages.append({"role": role, "text": text, "createdAt": timestamp,
                         "sourceId": payload.get("id"), "hidden": role == "user" and hidden_user(payload),
                         "occurrence": occurrence, "response_user": not canonical_user and role == "user"})
    return messages


def message_key(message):
    return message["role"], message["text"].strip()


def appended_messages(existing, source):
    if not existing:
        raise SyncError("Imported chat has no baseline messages; left unchanged.")
    positions = {}
    for index, message in enumerate(source):
        positions.setdefault(message_key(message), []).append(index)
    cursor = -1
    for message in existing:
        choices = positions.get(message_key(message), [])
        start = bisect.bisect_right(choices, cursor)
        candidates = choices[start:]
        # Exact timestamps distinguish repeated short replies; do not guess a branch.
        exact = [i for i in candidates if source[i]["createdAt"] == message["createdAt"]]
        if not exact:
            raise SyncError("Existing T3 history is not an unchanged source subsequence; left unchanged.")
        cursor = exact[0]
    return [message for message in source[cursor + 1:] if not message.get("hidden", False)]


def current_messages(db, thread_id, checkpoint):
    values = {row["message_id"]: json.loads(row["payload_json"]) for row in db.execute(
        "SELECT message_id,payload_json FROM orchestration_v2_projection_messages WHERE thread_id=?", (thread_id,))}
    order = {}
    for row in db.execute('SELECT ordinal,payload_json FROM orchestration_v2_projection_turn_items WHERE thread_id=?',(thread_id,)):
        item = json.loads(row['payload_json'])
        if item.get('messageId'):
            order[item['messageId']] = row['ordinal']
    for row in db.execute("SELECT payload_json FROM orchestration_events WHERE stream_id=? AND sequence>? "
                          "AND event_type='turn-item.updated' ORDER BY sequence",(thread_id,checkpoint)):
        item=json.loads(row[0])
        if item.get('messageId'):
            order[item['messageId']] = item['ordinal']
    for row in db.execute("SELECT payload_json FROM orchestration_events WHERE stream_id=? "
                          "AND application_event_version=2 AND event_type='message.updated' AND sequence>? "
                          "ORDER BY sequence", (thread_id, checkpoint)):
        payload = json.loads(row[0])
        values[payload["id"]] = payload
    return sorted(values.values(), key=lambda value: (value["createdAt"],order.get(value['id'],0),value["id"]))


def event_pair(thread_id, message, ordinal):
    signature = json_text([thread_id, message.get("sourceId"), message.get("occurrence", 0), message["role"],
                           message["createdAt"], message["text"]])
    token = hashlib.sha256(signature.encode()).hexdigest()[:32]
    message_id = PREFIX + "message:" + thread_id + ":" + token
    item_id = PREFIX + "item:" + thread_id + ":" + token
    at = message["createdAt"]
    user = message["role"] == "user"
    payload = {"createdBy": "user" if user else "agent", "creationSource": "server",
               "id": message_id, "threadId": thread_id, "runId": None, "nodeId": None,
               "role": message["role"], "text": message["text"], "attachments": [],
               "streaming": False, "createdAt": at, "updatedAt": at}
    item = {"id": item_id, "threadId": thread_id, "runId": None, "nodeId": None,
            "providerThreadId": None, "providerTurnId": None, "nativeItemRef": None,
            "parentItemId": None, "ordinal": ordinal, "status": "completed", "title": None,
            "startedAt": at, "completedAt": at, "updatedAt": at,
            "type": "user_message" if user else "assistant_message", "messageId": message_id,
            "text": message["text"]}
    if user:
        item.update(createdBy="user", creationSource="server", inputIntent="turn_start", attachments=[])
    else:
        item["streaming"] = False
    return [
        {"id": PREFIX + "event:" + message_id, "threadId": thread_id,
         "type": "message.updated", "occurredAt": at, "payload": payload},
        {"id": PREFIX + "event:" + item_id, "threadId": thread_id,
         "type": "turn-item.updated", "occurredAt": at, "payload": item},
    ]


def normalize_project_path(value):
    value = str(value or '').replace('/', '\\')
    if value.startswith('\\\\?\\UNC\\'):
        value = '\\\\' + value[8:]
    elif value.startswith('\\\\?\\'):
        value = value[4:]
    return ntpath.normpath(value).casefold().rstrip('\\')


def read_sources(codex_home):
    wanted = ('id', 'rollout_path', 'cwd', 'name', 'title', 'archived', 'source',
              'thread_source', 'project_id', 'model')
    with readonly(Path(codex_home) / 'state_5.sqlite') as codex:
        columns = {row['name'] for row in codex.execute('PRAGMA table_info(threads)')}
        names = [name for name in wanted if name in columns]
        sources = {row['id']:dict(row) for row in codex.execute(
            'SELECT ' + ','.join(names) + ' FROM threads ORDER BY id')}
        roots = {}
        if codex.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='project_roots'").fetchone():
            for row in codex.execute('SELECT project_id,path FROM project_roots ORDER BY project_id,position'):
                roots.setdefault(row['project_id'], []).append(row['path'])
    user_sources = {key:value for key,value in sources.items() if user_source(value)}
    signature = hashlib.sha256(json_text([user_sources, roots]).encode()).hexdigest()
    return sources, roots, signature


def user_source(source):
    return (source.get('thread_source') in (None, 'user') and
            not str(source.get('source') or '').lstrip().startswith('{'))


def matching_project(source, projects, roots):
    if not user_source(source) or source.get('archived'):
        return None
    current = normalize_project_path(source.get('cwd'))
    matches = [p for p in projects if normalize_project_path(p['workspace_root']) == current]
    if not matches:
        candidates = {normalize_project_path(value) for value in roots.get(source.get('project_id'), [])}
        matches = [p for p in projects if normalize_project_path(p['workspace_root']) in candidates]
    if len(matches) > 1:
        raise SyncError('Current Codex project matches several T3 projects; left unchanged.')
    return matches[0] if matches else None


def metadata_event(thread):
    token = hashlib.sha256(json_text(thread).encode()).hexdigest()[:24]
    return {'id':PREFIX + 'thread:' + thread['id'] + ':' + token, 'threadId':thread['id'],
            'type':'thread.metadata-updated', 'occurredAt':thread['updatedAt'], 'payload':thread}


def initial_thread_events(source, project, messages, omitted):
    native = source['id']
    thread_id = 'import:codex:' + native
    provider_id = 'provider-thread:provider:codex:provider-instance:codex:native-thread:' + native
    created, updated = messages[0]['createdAt'], messages[-1]['createdAt']
    model = source.get('model')
    if not model and project.get('default_model_selection_json'):
        selection = json.loads(project['default_model_selection_json'])
        if selection.get('instanceId') == 'codex':
            model = selection.get('model')
    title = source.get('name') or source.get('title') or 'Imported Codex chat'
    title = title.strip().split('\n')[0][:150] or 'Imported Codex chat'
    thread = dict(createdBy='system', creationSource='server', id=thread_id,
                  projectId=project['project_id'], title=title, providerInstanceId='codex',
                  modelSelection={'instanceId':'codex', 'model':model or 'gpt-6.1-sol'},
                  runtimeMode='full-access', interactionMode='default', branch=None, worktreePath=None,
                  linkedPullRequest=None, branchPullRequest=None, activeProviderThreadId=provider_id,
                  historyOrigin='v1_import', lineage={'parentThreadId':None,'relationshipToParent':None,
                                                    'rootThreadId':thread_id}, forkedFrom=None,
                  createdAt=created, updatedAt=updated, archivedAt=None, settledOverride='settled',
                  settledAt=updated, unsettledAt=None, snoozedUntil=None, snoozedAt=None,
                  pinnedAt=None, pinOrderKey=None, activeOrderKey=None, lastVisitedAt=None, deletedAt=None)
    provider = dict(id=provider_id, driver='codex', providerInstanceId='codex', providerSessionId=None,
                    appThreadId=thread_id, ownerNodeId=None,
                    nativeThreadRef={'driver':'codex','nativeId':native,'strength':'strong'},
                    nativeConversationHeadRef=None, status='idle', firstRunOrdinal=None, lastRunOrdinal=None,
                    handoffIds=[], forkedFrom=None, pendingBackgroundTasks=[], createdAt=created, updatedAt=updated)
    events = [{'id':PREFIX+'created:'+thread_id, 'threadId':thread_id, 'type':'thread.created',
               'occurredAt':created, 'payload':thread}]
    if omitted:
        notice = dict(id=PREFIX+'history:'+thread_id, threadId=thread_id, runId=None, nodeId=None,
                      providerThreadId=None, providerTurnId=None, nativeItemRef=None, parentItemId=None,
                      ordinal=0, status='completed', title=None, startedAt=created, completedAt=created,
                      updatedAt=created, type='system_notice',
                      message=str(omitted)+' earlier messages were not imported. This chat keeps the first '
                      'message and recent history. The original Codex transcript is unchanged.')
        events.append({'id':PREFIX+'notice:'+thread_id, 'threadId':thread_id, 'type':'turn-item.updated',
                       'occurredAt':created, 'payload':notice})
    for ordinal, message in enumerate(messages, 1):
        events.extend(event_pair(thread_id, message, ordinal))
    events.append({'id':PREFIX+'provider:'+thread_id, 'threadId':thread_id, 'type':'provider-thread.updated',
                   'occurredAt':updated, 'payload':provider})
    return events, title


def build_plan(db_path: Path, codex_home: Path, cache_dir=None, writable_cache=False):
    sources, roots, index_signature = read_sources(codex_home)
    paths = {key:Path(value['rollout_path']) for key,value in sources.items() if value.get('rollout_path')}
    with readonly(db_path) as db:
        db.execute("BEGIN")
        verify_schema(db)
        token = snapshot_token(db)
        checkpoint_row = db.execute("SELECT last_sequence FROM orchestration_v2_projection_metadata "
                                    "WHERE projection_name='thread-projections'").fetchone()
        if checkpoint_row is None:
            raise SyncError("T3 projection checkpoint is unavailable.")
        checkpoint = checkpoint_row[0]
        events = []
        reports = []
        source_guards = {}
        diagnostics = []
        total = 0
        projects = [dict(row) for row in db.execute('SELECT * FROM projection_projects '
                    'WHERE deleted_at IS NULL AND archived_at IS NULL')]
        existing_ids = {row[0] for row in db.execute('SELECT thread_id FROM orchestration_v2_projection_threads')}
        threads = db.execute("SELECT thread_id,title,payload_json FROM orchestration_v2_projection_threads "
                             "WHERE deleted_at IS NULL AND thread_id LIKE 'import:%' ORDER BY thread_id").fetchall()
        for row in threads:
            thread_id = row["thread_id"]
            thread = json.loads(row["payload_json"])
            native_id = thread_id.rsplit(":", 1)[-1]
            report = {"threadId": thread_id, "title": row["title"], "messages": 0}
            try:
                if thread.get("modelSelection", {}).get("instanceId") != "codex" and not thread_id.startswith("import:codex:"):
                    continue
                if thread.get("historyOrigin") != "v1_import":
                    raise SyncError("Chat no longer has an imported-history baseline.")
                if db.execute("SELECT 1 FROM orchestration_v2_projection_runs WHERE thread_id=? LIMIT 1", (thread_id,)).fetchone():
                    raise SyncError("Chat was continued inside T3; automatic reconciliation is paused.")
                # Include pending T3-native run events as well as materialized projections.
                if db.execute("SELECT 1 FROM orchestration_events WHERE stream_id=? AND sequence>? "
                              "AND event_type IN ('run.created','run.updated','thread.deleted') LIMIT 1",
                              (thread_id, checkpoint)).fetchone():
                    raise SyncError("Chat has pending native activity; deferred.")
                if native_id not in paths:
                    raise SyncError("Codex source session is unavailable.")
                project = matching_project(sources[native_id], projects, roots)
                moved = project is not None and thread.get('projectId') != project['project_id']
                if moved and (thread.get('worktreePath') or thread.get('branch')):
                    raise SyncError('Imported chat has T3 branch/worktree settings; project move is paused.')
                records, guards = transcript_records(native_id, paths[native_id], paths,
                    cache_dir=cache_dir, writable=writable_cache, diagnostics=diagnostics)
                source = parse_messages(records)
                existing = current_messages(db, thread_id, checkpoint)
                if any(message.get("runId") is not None or message.get("nodeId") is not None
                       or message.get("streaming") for message in existing):
                    raise SyncError("Chat contains native or streaming activity; left unchanged.")
                additions = appended_messages(existing, source)
                remaining = MAX_BATCH_MESSAGES - total
                if remaining <= 0 and additions:
                    raise SyncError("Batch limit reached; remaining messages will be synced next launch.")
                additions = additions[:remaining]
                max_ordinal = db.execute("SELECT COALESCE(MAX(ordinal),0) FROM orchestration_v2_projection_turn_items "
                                         "WHERE thread_id=?", (thread_id,)).fetchone()[0]
                max_ordinal = max(max_ordinal, db.execute(
                    "SELECT COALESCE(MAX(ordinal),0) FROM orchestration_v2_turn_item_positions WHERE thread_id=?",
                    (thread_id,)).fetchone()[0])
                for pending in db.execute("SELECT payload_json FROM orchestration_events WHERE stream_id=? "
                                          "AND sequence>? AND event_type='turn-item.updated'", (thread_id, checkpoint)):
                    max_ordinal = max(max_ordinal, json.loads(pending[0]).get("ordinal", 0))
                thread_events = []
                for index, message in enumerate(additions, max_ordinal + 1):
                    thread_events.extend(event_pair(thread_id, message, index))
                if additions or moved:
                    thread['id'] = thread_id
                    thread["updatedAt"] = max(thread["updatedAt"], additions[-1]["createdAt"] if additions else
                                             dt.datetime.now(dt.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z'))
                    if moved:
                        thread['projectId'] = project['project_id']
                    thread_events.append(metadata_event(thread))
                    source_guards.update(guards)
                events.extend(thread_events)
                total += len(additions)
                report.update(status="ready" if additions or moved else "up_to_date", messages=len(additions),
                              action='move' if moved else 'update')
            except (SyncError, OSError) as exc:
                report.update(status="skipped", reason=str(exc))
            reports.append(report)
        for native_id, source_info in sources.items():
            thread_id = 'import:codex:' + native_id
            if thread_id in existing_ids or native_id not in paths or not user_source(source_info) or source_info.get('archived'):
                continue
            report = {'threadId':thread_id, 'title':source_info.get('name') or source_info.get('title'),
                      'messages':0, 'action':'import'}
            try:
                project = matching_project(source_info, projects, roots)
                if project is None:
                    continue  # Only existing active T3 projects are eligible.
                owner = db.execute("SELECT thread_id FROM orchestration_v2_projection_provider_threads "
                    "WHERE driver='codex' AND provider_instance_id='codex' "
                    "AND json_extract(payload_json,'$.nativeThreadRef.nativeId')=? LIMIT 1", (native_id,)).fetchone()
                if owner:
                    raise SyncError('This native Codex chat is already owned by a T3 thread; left unchanged.')
                records, guards = transcript_records(native_id, paths[native_id], paths,
                    cache_dir=cache_dir, writable=writable_cache, diagnostics=diagnostics)
                visible = [m for m in parse_messages(records) if not m.get('hidden',False)]
                if not visible:
                    raise SyncError('No settled visible messages are available for the initial import.')
                history = visible if len(visible) <= INITIAL_HISTORY_MESSAGES else [visible[0]] + visible[-(INITIAL_HISTORY_MESSAGES-1):]
                if total + len(history) > MAX_BATCH_MESSAGES:
                    raise SyncError('Batch limit reached; this chat will be imported on a later launch.')
                initial, title = initial_thread_events(source_info, project, history, len(visible)-len(history))
                events.extend(initial)
                source_guards.update(guards)
                total += len(history)
                report.update(title=title, status='ready', messages=len(history), omittedMessages=len(visible)-len(history),
                              projectId=project['project_id'])
            except (SyncError,OSError) as exc:
                report.update(status='skipped',reason=str(exc))
            reports.append(report)
        return {"snapshot": token, "events": events, "sources": source_guards,
                "messages": total, "threads": reports, 'sourceReads':diagnostics,
                'codexHome':str(codex_home), 'codexIndex':index_signature}


def apply_plan(db_path: Path, plan, backup_dir: Path, guard, node_exe=None):
    if guard():
        raise SyncError("T3 is running. Updates are deferred until it is fully closed.")
    if not plan["events"]:
        return None
    node_exe = node_exe or shutil.which("node.exe") or shutil.which("node")
    if not node_exe:
        raise SyncError("Node.js 22.13+ with node:sqlite is required.")
    environment = dict(os.environ, NODE_NO_WARNINGS="1")
    worker = subprocess.Popen(
        [str(node_exe), str(Path(__file__).with_name("writer.cjs")), str(db_path.resolve())],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        encoding="utf-8", env=environment,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        worker.stdin.write(json_text({"migration": SUPPORTED_MIGRATION, "schema": SUPPORTED_SCHEMA,
                                     "tables": SCHEMA_TABLES, "plan": plan}) + "\n")
        worker.stdin.flush()
        prepared = worker.stdout.readline()
        if not prepared:
            raise SyncError("Native SQLite writer could not start: " + worker.stderr.read()[-300:])
        ready = json.loads(prepared)
        if not ready.get("ready"):
            raise SyncError(ready.get("error", "Native SQLite preparation failed."))
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        backup_path = backup_dir / ("statev2-before-sync-" + stamp + ".sqlite")
        with readonly(db_path) as source, sqlite3.connect(str(backup_path), factory=ClosingConnection) as target:
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise SyncError("Backup verification failed; no changes were made.")
        if guard():
            raise SyncError("T3 started during sync; the transaction was rolled back.")
        for path, identity in plan["sources"].items():
            unchanged = verify_guard(path, identity) if isinstance(identity,dict) else source_identity(Path(path)) == tuple(identity)
            if not unchanged:
                raise SyncError("Codex source changed during sync; the transaction was rolled back.")
        if plan.get('codexHome') and read_sources(plan['codexHome'])[2] != plan.get('codexIndex'):
            raise SyncError('Codex project membership changed during sync; the transaction was rolled back.')
        if guard():
            raise SyncError('T3 started while source fingerprints were checked; the transaction was rolled back.')
        worker.stdin.write('{"commit":true}\n')
        worker.stdin.flush()
        stdout, stderr = worker.communicate(timeout=15)
        responses = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        if worker.returncode != 0 or not any(response.get("committed") for response in responses):
            raise SyncError(next((r["error"] for r in responses if "error" in r), stderr[-300:]))
        return str(backup_path)
    except BaseException:
        if worker.poll() is None:
            try:
                worker.communicate('{"commit":false}\n', timeout=10)
            except (subprocess.TimeoutExpired, OSError):
                worker.kill()
                worker.communicate()
        raise
    finally:
        for stream in (worker.stdin, worker.stdout, worker.stderr):
            if stream is not None and not stream.closed:
                stream.close()


def write_report(state_dir: Path, report):
    state_dir.mkdir(parents=True, exist_ok=True)
    report["at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    temporary = state_dir / "last-sync.tmp"
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(str(temporary), str(state_dir / "last-sync.json"))
    # Logs contain counts, identifiers and reasons, never message bodies.
    with (state_dir / "sync.log").open("a", encoding="utf-8") as log:
        log.write(json_text(report) + "\n")


def run(config, apply=False, launch=False):
    home = Path(config["t3_home"])
    exe = Path(config["t3_exe"])
    state_dir = Path(config["state_dir"])
    if not exe.is_file():
        raise SyncError("T3 executable is missing; update config.json after moving T3.")
    with launch_lock(state_dir / "launch.lock"):
        report = {"version": VERSION, "status": "preview", "messages": 0, "threads": []}
        try:
            if t3_running(home, exe):
                report["status"] = "deferred_t3_running"
            else:
                plan = build_plan(home / "userdata" / "statev2.sqlite", Path(config["codex_home"]),
                                  state_dir / 'source-cache', writable_cache=apply)
                report.update(messages=plan["messages"], threads=plan["threads"],sourceReads=plan['sourceReads'])
                if apply:
                    backup = apply_plan(home / "userdata" / "statev2.sqlite", plan,
                                        state_dir / "backups", lambda: t3_running(home, exe), config.get("node_exe"))
                    report.update(status="synced" if backup else "up_to_date", backup=backup)
            write_report(state_dir, report)
        except Exception as exc:
            report.update(status="error", error=str(exc))
            write_report(state_dir, report)
        if launch:
            environment = dict(os.environ, T3CODE_HOME=str(home))
            subprocess.Popen([str(exe)], cwd=str(exe.parent), close_fds=True, env=environment)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    parser.add_argument("--apply", action="store_true", help="Append events, only when T3 is stopped")
    parser.add_argument("--launch", action="store_true", help="Sync, then launch T3 (or open its existing window)")
    parser.add_argument("--preview", action="store_true", help="Read-only plan, including when T3 is running")
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8-sig"))
        if args.preview:
            plan = build_plan(Path(config["t3_home"]) / "userdata" / "statev2.sqlite", Path(config["codex_home"]),
                              Path(config['state_dir']) / 'source-cache' if config.get('state_dir') else None)
            report = {key: plan[key] for key in ("messages", "threads", 'sourceReads')}
            report["status"] = "preview"
        else:
            report = run(config, apply=args.apply or args.launch, launch=args.launch)
        if sys.stdout is not None:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if report.get("status") == "error" else 0
    except Exception as exc:
        if sys.stderr is not None:
            print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
