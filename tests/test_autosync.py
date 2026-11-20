import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
import contextlib
import io
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import autosync as a


def msg(role, text, at, **extra):
    return dict(role=role, text=text, createdAt=at, **extra)


def record(role, text, at, **extra):
    return {"type": "response_item", "timestamp": at,
            "payload": dict(type="message", role=role, content=[{"type": "input_text", "text": text}], **extra)}


def terminal(at="2026-11-20T08:10:00.000Z"):
    return {"type": "event_msg", "timestamp": at, "payload": {"type": "task_complete"}}


class ParserTests(unittest.TestCase):
    def test_unfinished_turn_is_deferred(self):
        records = [record("user", "first", "2026-11-20T08:00:00.000Z"),
                   record("assistant", "done", "2026-11-20T08:01:00.000Z"), terminal(),
                   record("user", "still running", "2026-11-20T08:12:00.000Z")]
        self.assertEqual([m["text"] for m in a.parse_messages(records)], ["first", "done"])

    def test_no_terminal_is_not_imported(self):
        with self.assertRaises(a.SyncError):
            a.parse_messages([record("user", "active", "2026-11-20T08:00:00.000Z")])

    def test_canonical_turn_removes_setup_and_duplicate_user_records(self):
        at = "2026-11-20T08:00:00.000Z"
        meta = {"turn_id": "turn1"}
        records = [{"type": "event_msg", "timestamp": at, "payload": {"type": "user_message", "message": "hi"}},
                   record("user", "injected setup", at, internal_chat_message_metadata_passthrough=meta),
                   record("user", "hi", at, internal_chat_message_metadata_passthrough=meta),
                   record("assistant", "hello", "2026-11-20T08:01:00.000Z"), terminal()]
        self.assertEqual([m["text"] for m in a.parse_messages(records)], ["hi", "hello"])

    def test_response_then_canonical_is_deduplicated(self):
        at = "2026-11-20T08:00:00.000Z"
        records = [record("user", "hi", at), {"type": "event_msg", "timestamp": at,
                   "payload": {"type": "user_message", "message": "hi"}}, terminal()]
        self.assertEqual(len(a.parse_messages(records)), 1)

    def test_harness_messages_can_align_but_are_not_appended(self):
        at = "2026-11-20T08:00:00.000Z"
        records = [record("user", "baseline", at),
                   record("user", "system envelope", "2026-11-20T08:01:00.000Z",
                          internal_chat_message_metadata_passthrough={"content_item_kinds": ["agents_md.instructions"]}),
                   record("user", "actual question", "2026-11-20T08:02:00.000Z",
                          internal_chat_message_metadata_passthrough={"content_item_kinds": ["user.text"]}), terminal()]
        source = a.parse_messages(records)
        self.assertEqual([m["text"] for m in a.appended_messages([source[0]], source)], ["actual question"])

    def test_200_message_import_cap_aligns_as_subsequence(self):
        source = [msg("assistant", str(i), str(i)) for i in range(300)]
        baseline = [source[0]] + source[2:201]
        self.assertEqual(a.appended_messages(baseline, source), source[201:])

    def test_changed_history_is_refused(self):
        with self.assertRaises(a.SyncError):
            a.appended_messages([msg("user", "edited", "1")], [msg("user", "original", "1")])

    def test_repeated_text_requires_same_timestamp(self):
        source = [msg("user", "yes", "1"), msg("user", "yes", "2"), msg("assistant", "ok", "3")]
        self.assertEqual(a.appended_messages([source[1]], source), [source[2]])
        with self.assertRaises(a.SyncError):
            a.appended_messages([msg("user", "yes", "4")], source)

    def test_no_baseline_is_refused(self):
        with self.assertRaises(a.SyncError):
            a.appended_messages([], [msg("user", "hello", "1")])

    def test_same_timestamp_repeated_messages_have_unique_events(self):
        at = "2026-11-20T08:00:00.000Z"
        source = a.parse_messages([record("assistant", "same", at), record("assistant", "same", at), terminal()])
        self.assertNotEqual(a.event_pair("thread", source[0], 1)[0]["id"],
                            a.event_pair("thread", source[1], 2)[0]["id"])


class FileTests(unittest.TestCase):
    def test_readonly_context_closes_the_handle_without_gc(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'context.sqlite'
            with sqlite3.connect(str(path), factory=a.ClosingConnection) as writable:
                writable.execute('CREATE TABLE example(value TEXT)')
            with a.readonly(path) as reader:
                self.assertEqual(reader.execute('SELECT count(*) FROM example').fetchone()[0], 0)
            with self.assertRaises(sqlite3.ProgrammingError):
                reader.execute('SELECT 1')
            path.unlink()  # Windows must allow this while reader is still referenced.

    def test_closing_context_preserves_transaction_rollback(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'context.sqlite'
            with sqlite3.connect(str(path), factory=a.ClosingConnection) as writable:
                writable.execute('CREATE TABLE example(value TEXT)')
            with self.assertRaises(RuntimeError):
                with sqlite3.connect(str(path), factory=a.ClosingConnection) as writable:
                    writable.execute("INSERT INTO example VALUES ('rolled back')")
                    raise RuntimeError('cancel')
            with a.readonly(path) as reader:
                self.assertEqual(reader.execute('SELECT count(*) FROM example').fetchone()[0], 0)

    def test_partial_last_line_is_not_imported(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "a.jsonl"
            path.write_bytes((json.dumps(terminal()) + "\n{partial").encode())
            self.assertEqual(len(a.read_records(path)), 1)

    def test_malformed_completed_record_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "a.jsonl"
            path.write_bytes(b'{bad}\n')
            with self.assertRaises(a.SyncError):
                a.read_records(path)

    def test_inherited_transcript_and_cycle(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp) / "parent.jsonl"
            child = Path(temp) / "child.jsonl"
            content = [dict(type="session_meta", payload={"id": "parent"}), record("user", "base", "2026-11-20T08:00:00.000Z"), terminal()]
            parent.write_text("".join(json.dumps(r) + "\n" for r in content), encoding="utf-8")
            child.write_text(json.dumps(dict(type="session_meta", payload={"id": "child", "history_base":
                             {"thread_id": "parent", "end_byte_offset": parent.stat().st_size}})) + "\n", encoding="utf-8")
            records, guards = a.transcript_records("child", child, {"parent": parent, "child": child})
            self.assertEqual(a.parse_messages(records)[0]["text"], "base")
            self.assertEqual(len(guards), 2)
            with self.assertRaises(a.SyncError):
                a.transcript_records("child", child, {}, visited={"child"})

    def test_readonly_does_not_create_missing_database(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / "missing.sqlite"
            with self.assertRaises(sqlite3.OperationalError):
                a.readonly(missing)
            self.assertFalse(missing.exists())


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / "state.sqlite"
        subprocess.run(['node','--disable-warning=ExperimentalWarning','-e',
            "new(require('node:sqlite').DatabaseSync)(process.argv[1]).exec(require('node:fs').readFileSync(process.argv[2],'utf8'))",
            str(self.db_path),str(Path(__file__).with_name('schema_fixture.sql'))],check=True,capture_output=True)
        db = sqlite3.connect(str(self.db_path), factory=a.ClosingConnection)
        db.execute("INSERT INTO orchestration_v2_projection_metadata VALUES ('thread-projections',2,0,'2026-11-20T00:00:00.000Z')")
        db.execute("INSERT INTO orchestration_v2_projection_threads(thread_id,project_id,title,default_provider,"
                   "runtime_mode,interaction_mode,created_at,updated_at,payload_json) "
                   "VALUES ('thread','project','Test','codex','full-access','default','0','0','{}')")
        db.commit()
        db.close()
        with a.readonly(self.db_path) as db:
            token = a.snapshot_token(db)
            fixture_schema = a.schema_digest(db)
        self.schema_patch = patch.object(a, 'SUPPORTED_SCHEMA', fixture_schema)
        self.schema_patch.start()
        self.message = msg("assistant", "new", "2026-11-20T08:00:00.000Z")
        self.plan = dict(snapshot=token, events=a.event_pair("thread", self.message, 1), sources={})

    def tearDown(self):
        self.schema_patch.stop()
        self.temp.cleanup()

    def count(self):
        with sqlite3.connect(str(self.db_path), factory=a.ClosingConnection) as db:
            return db.execute("SELECT COUNT(*) FROM orchestration_events").fetchone()[0]

    def test_apply_creates_backup_and_matching_events_and_projections(self):
        backup = a.apply_plan(self.db_path, self.plan, self.root / "backups", lambda: False)
        self.assertEqual(self.count(), 2)
        with sqlite3.connect(backup, factory=a.ClosingConnection) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM orchestration_events").fetchone()[0], 0)
        with sqlite3.connect(str(self.db_path), factory=a.ClosingConnection) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM orchestration_v2_projection_messages").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM orchestration_v2_projection_turn_items").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT last_sequence FROM orchestration_v2_projection_metadata WHERE projection_name='thread-projections'").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT stream_version FROM orchestration_events ORDER BY sequence").fetchall(), [(0,), (1,)])

    def test_running_t3_refuses_writes(self):
        with self.assertRaises(a.SyncError):
            a.apply_plan(self.db_path, self.plan, self.root / "backups", lambda: True)
        self.assertEqual(self.count(), 0)

    def test_t3_starting_mid_transaction_rolls_back(self):
        states = iter([False, True])
        with self.assertRaises(a.SyncError):
            a.apply_plan(self.db_path, self.plan, self.root / "backups", lambda: next(states))
        self.assertEqual(self.count(), 0)

    def test_changed_database_refuses_writes(self):
        self.plan["snapshot"] = "wrong"
        with self.assertRaises(a.SyncError):
            a.apply_plan(self.db_path, self.plan, self.root / "backups", lambda: False)
        self.assertEqual(self.count(), 0)

    def test_unknown_t3_migration_refuses_writes(self):
        with sqlite3.connect(str(self.db_path), factory=a.ClosingConnection) as db:
            db.execute("UPDATE effect_sql_migrations SET migration_id=82")
        with self.assertRaises(a.SyncError):
            a.apply_plan(self.db_path, self.plan, self.root / 'backups', lambda: False)
        self.assertEqual(self.count(), 0)

    def test_changed_source_refuses_writes(self):
        source = self.root / "source.jsonl"
        source.write_text("changed", encoding="utf-8")
        self.plan["sources"] = {str(source): (0, 0)}
        with self.assertRaises(a.SyncError):
            a.apply_plan(self.db_path, self.plan, self.root / "backups", lambda: False)
        self.assertEqual(self.count(), 0)

    def test_pending_events_prevent_duplicates_before_t3_replay(self):
        a.apply_plan(self.db_path, self.plan, self.root / "backups", lambda: False)
        with a.readonly(self.db_path) as db:
            existing = a.current_messages(db, "thread", 0)
            self.assertEqual(a.appended_messages(existing, [self.message]), [])

    def test_duplicate_events_are_not_written_twice(self):
        a.apply_plan(self.db_path, self.plan, self.root / "backups", lambda: False)
        with a.readonly(self.db_path) as db:
            self.plan["snapshot"] = a.snapshot_token(db)
        a.apply_plan(self.db_path, self.plan, self.root / "backups", lambda: False)
        self.assertEqual(self.count(), 2)

    def prepare_source(self):
        codex = self.root / 'codex'
        codex.mkdir()
        transcript = codex / 'source.jsonl'
        at = '2026-11-20T08:00:00.000Z'
        records = [dict(type='session_meta', payload={'id':'source'}),
                   record('user','baseline',at), terminal(),
                   record('user','new question','2026-11-20T08:11:00.000Z'),
                   record('user','internal setup','2026-11-20T08:11:01.000Z',
                          internal_chat_message_metadata_passthrough={'content_item_kinds':['agents_md.instructions']}),
                   record('assistant','new answer','2026-11-20T08:12:00.000Z'),
                   terminal('2026-11-20T08:13:00.000Z')]
        transcript.write_text(''.join(json.dumps(r)+'\n' for r in records),encoding='utf-8')
        with sqlite3.connect(str(codex/'state_5.sqlite'), factory=a.ClosingConnection) as db:
            db.execute('CREATE TABLE threads(id TEXT,rollout_path TEXT)')
            db.execute('INSERT INTO threads VALUES (?,?)',('source',str(transcript)))
        thread={'id':'import:codex:source','historyOrigin':'v1_import','modelSelection':{'instanceId':'codex'},'updatedAt':at}
        baseline=dict(id='baseline',threadId=thread['id'],runId=None,nodeId=None,
                      role='user',text='baseline',createdAt=at,updatedAt=at,streaming=False)
        with sqlite3.connect(str(self.db_path), factory=a.ClosingConnection) as db:
            db.execute('UPDATE orchestration_v2_projection_threads SET thread_id=?,payload_json=?',
                       (thread['id'],json.dumps(thread)))
        subprocess.run(['node','--disable-warning=ExperimentalWarning','-e',
            "const d=new(require('node:sqlite').DatabaseSync)(process.argv[1]);const p=JSON.parse(process.argv[2]);"
            "d.prepare('INSERT INTO orchestration_v2_projection_messages(message_id,thread_id,role,streaming,created_at,updated_at,payload_json) VALUES (?,?,?,0,?,?,?)').run(p.id,p.threadId,p.role,p.createdAt,p.updatedAt,JSON.stringify(p));d.close()",
            str(self.db_path),json.dumps(baseline)],check=True,capture_output=True)
        return codex

    def test_planner_finds_only_new_visible_messages(self):
        codex=self.prepare_source()
        plan=a.build_plan(self.db_path,codex)
        self.assertEqual(plan['messages'],2)
        self.assertEqual([event['payload']['text'] for event in plan['events'] if event['type']=='message.updated'],
                         ['new question','new answer'])
        a.apply_plan(self.db_path,plan,self.root/'backups',lambda:False)
        self.assertEqual(a.build_plan(self.db_path,codex)['messages'],0)

    def test_planner_pauses_chats_continued_inside_t3(self):
        codex=self.prepare_source()
        with sqlite3.connect(str(self.db_path), factory=a.ClosingConnection) as db:
            db.execute("INSERT INTO orchestration_v2_projection_runs(run_id,thread_id,ordinal,provider,status,requested_at,payload_json) VALUES ('run','import:codex:source',1,'codex','completed','0','{}')")
        plan=a.build_plan(self.db_path,codex)
        self.assertEqual(plan['messages'],0)
        self.assertIn('continued inside T3',plan['threads'][0]['reason'])

    def test_cli_preview_is_read_only(self):
        codex=self.prepare_source()
        home=self.root/'t3'
        (home/'userdata').mkdir(parents=True)
        copied=home/'userdata'/'statev2.sqlite'
        with a.readonly(self.db_path) as source, sqlite3.connect(str(copied), factory=a.ClosingConnection) as target:
            source.backup(target)
        config=self.root/'config.json'
        config.write_text(json.dumps(dict(t3_home=str(home),codex_home=str(codex))),encoding='utf-8')
        with patch('sys.argv',['autosync.py','--preview','--config',str(config)]), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(a.main(),0)
        self.assertEqual(json.loads(output.getvalue())['messages'],2)
        with a.readonly(copied) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM orchestration_events').fetchone()[0],0)

    def test_cli_reports_invalid_config(self):
        with patch('sys.argv',['autosync.py','--config',str(self.root/'missing.json')]), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(a.main(),1)

    def test_run_records_error_without_starting_t3(self):
        home=self.root/'t3'
        (home/'userdata').mkdir(parents=True)
        config=dict(t3_home=str(home),codex_home=str(self.root),t3_exe=str(Path(a.__file__)),state_dir=str(self.root/'state'))
        with patch.object(a,'t3_running',return_value=False):
            result=a.run(config)
        self.assertEqual(result['status'],'error')
        self.assertTrue((self.root/'state'/'last-sync.json').is_file())

    def test_launcher_commits_before_app_start_and_next_run_is_noop(self):
        codex=self.prepare_source()
        home=self.root/'t3'
        (home/'userdata').mkdir(parents=True)
        copied=home/'userdata'/'statev2.sqlite'
        with a.readonly(self.db_path) as source, sqlite3.connect(str(copied), factory=a.ClosingConnection) as target:
            source.backup(target)
        fake_exe=Path(a.__file__).resolve()
        config=dict(t3_home=str(home),codex_home=str(codex),t3_exe=str(fake_exe),state_dir=str(self.root/'state'))
        original_popen=subprocess.Popen
        app_starts=[]
        def start_process(args,**kwargs):
            if args==[str(fake_exe)]:
                self.assertEqual(kwargs['env']['T3CODE_HOME'],str(home))
                with a.readonly(copied) as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM orchestration_v2_projection_messages').fetchone()[0],3)
                app_starts.append(args)
                return object()
            return original_popen(args,**kwargs)
        with patch.object(a,'t3_running',return_value=False),patch.object(a.subprocess,'Popen',side_effect=start_process):
            result=a.run(config,apply=True,launch=True)
            self.assertEqual(result['status'],'synced')
            self.assertEqual(len(app_starts),1)
            self.assertEqual(a.run(config,apply=True)['status'],'up_to_date')
            config_path=self.root/'launcher-config.json'
            config_path.write_text(json.dumps(config),encoding='utf-8')
            with patch('sys.argv',['autosync.py','--apply','--config',str(config_path)]),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(a.main(),0)


if __name__ == "__main__":
    unittest.main()
