import json
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import autosync as a
import test_autosync


class ProjectImportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_autosync.DatabaseTests()
        self.fixture.setUp()
        self.root,self.db_path = self.fixture.root,self.fixture.db_path
        self.codex=self.root/'codex'
        self.codex.mkdir()
        self.project_root=self.root/'current-project'
        self.other_root=self.root/'other-project'
        with sqlite3.connect(str(self.db_path),factory=a.ClosingConnection) as db:
            for project,root in [('current',self.project_root),('other',self.other_root)]:
                db.execute("INSERT INTO projection_projects(project_id,title,workspace_root,scripts_json,created_at,updated_at) VALUES (?,?,?,'[]','0','0')",(project,project,str(root)))
        with sqlite3.connect(str(self.codex/'state_5.sqlite'),factory=a.ClosingConnection) as db:
            db.execute('CREATE TABLE threads(id TEXT,rollout_path TEXT,cwd TEXT,name TEXT,thread_source TEXT,archived INTEGER,model TEXT)')
        self.add_source('new')

    def tearDown(self):
        self.fixture.tearDown()

    def add_source(self,native,role='user',archived=0,count=2):
        at='2026-11-20T08:00:00.000Z'
        path=self.codex/(native+'.jsonl')
        records=[{'type':'session_meta','payload':{'id':native,'cwd':str(self.other_root)}}]
        for i in range(count):
            records.append(test_autosync.record('user' if i%2==0 else 'assistant','message '+str(i),at))
        records.append(test_autosync.terminal())
        path.write_text(''.join(json.dumps(r)+'\n' for r in records),encoding='utf-8')
        with sqlite3.connect(str(self.codex/'state_5.sqlite'),factory=a.ClosingConnection) as db:
            db.execute('INSERT OR REPLACE INTO threads VALUES (?,?,?,?,?,?,?)',
                       (native,str(path),str(self.project_root),'Current chat',role,archived,'test-model'))
        return path

    def apply(self,plan):
        return a.apply_plan(self.db_path,plan,self.root/'backups',lambda:False)

    def test_current_index_imports_missing_chat_once_with_native_mapping(self):
        plan=a.build_plan(self.db_path,self.codex)
        self.assertEqual(plan['messages'],2)
        self.assertEqual(plan['threads'][0]['action'],'import')
        self.apply(plan)
        with a.readonly(self.db_path) as db:
            row=db.execute("SELECT project_id,payload_json FROM orchestration_v2_projection_threads WHERE thread_id='import:codex:new'").fetchone()
            self.assertEqual(row['project_id'],'current')
            self.assertEqual(json.loads(row['payload_json'])['projectId'],'current')
            provider=db.execute("SELECT payload_json FROM orchestration_v2_projection_provider_threads WHERE thread_id='import:codex:new'").fetchone()
            self.assertEqual(json.loads(provider[0])['nativeThreadRef']['nativeId'],'new')
            runtime=db.execute("SELECT resume_cursor_json,runtime_payload_json FROM provider_session_runtime WHERE thread_id='import:codex:new'").fetchone()
            self.assertEqual(json.loads(runtime[0]),{'threadId':'new'})
            self.assertEqual(json.loads(runtime[1])['cwd'],str(self.project_root))
        self.assertEqual(a.build_plan(self.db_path,self.codex)['events'],[])

    def test_project_move_updates_projection_payload_and_resume_directory(self):
        self.apply(a.build_plan(self.db_path,self.codex))
        with sqlite3.connect(str(self.codex/'state_5.sqlite'),factory=a.ClosingConnection) as db:
            db.execute('UPDATE threads SET cwd=?',(str(self.other_root),))
        plan=a.build_plan(self.db_path,self.codex)
        self.assertEqual(plan['messages'],0)
        self.assertEqual(plan['threads'][0]['action'],'move')
        self.apply(plan)
        with a.readonly(self.db_path) as db:
            self.assertEqual(db.execute("SELECT project_id FROM orchestration_v2_projection_threads WHERE thread_id='import:codex:new'").fetchone()[0],'other')
            self.assertEqual(json.loads(db.execute("SELECT runtime_payload_json FROM provider_session_runtime WHERE thread_id='import:codex:new'").fetchone()[0])['cwd'],str(self.other_root))
        self.assertEqual(a.build_plan(self.db_path,self.codex)['events'],[])

    def test_initial_history_has_first_and_recent_messages_with_notice(self):
        self.add_source('new',count=240)
        plan=a.build_plan(self.db_path,self.codex)
        self.assertEqual(plan['messages'],200)
        messages=[e['payload']['text'] for e in plan['events'] if e['type']=='message.updated']
        self.assertEqual(messages[0],'message 0')
        self.assertEqual(messages[1],'message 41')
        self.assertEqual(messages[-1],'message 239')
        self.assertTrue(any(e['payload'].get('type')=='system_notice' for e in plan['events']))
        self.apply(plan)
        self.assertEqual(a.build_plan(self.db_path,self.codex)['messages'],0)

    def test_guard_refuses_project_membership_changes_after_preview(self):
        plan=a.build_plan(self.db_path,self.codex)
        with sqlite3.connect(str(self.codex/'state_5.sqlite'),factory=a.ClosingConnection) as db:
            db.execute('UPDATE threads SET cwd=?',(str(self.other_root),))
        with self.assertRaises(a.SyncError):
            self.apply(plan)
        self.assertEqual(self.fixture.count(),0)

    def test_guard_refuses_rewritten_prefix_but_allows_new_tail(self):
        plan=a.build_plan(self.db_path,self.codex)
        path=self.codex/'new.jsonl'
        with path.open('a',encoding='utf-8') as output:
            output.write(json.dumps(test_autosync.record('user','next unfinished','2026-11-20T08:12:00.000Z'))+'\n')
        self.apply(plan)
        self.assertEqual(a.build_plan(self.db_path,self.codex)['messages'],0)
        new_plan=a.build_plan(self.db_path,self.codex)
        new_plan['events']=a.event_pair('import:codex:new',test_autosync.msg('assistant','test','2026-11-20T09:00:00.000Z'),3)
        new_plan['sources']=plan['sources']
        path.write_bytes(path.read_bytes().replace(b'message 0',b'changed 0'))
        with self.assertRaises(a.SyncError):
            self.apply(new_plan)

    def test_archived_and_subagent_sources_are_not_imported(self):
        self.add_source('archived',archived=1)
        self.add_source('guardian',role='guardian_review')
        self.add_source('subagent',role='subagent')
        plan=a.build_plan(self.db_path,self.codex)
        self.assertEqual([e['threadId'] for e in plan['events'] if e['type']=='thread.created'],['import:codex:new'])

    def test_deleted_chat_is_not_resurrected(self):
        self.apply(a.build_plan(self.db_path,self.codex))
        with sqlite3.connect(str(self.db_path),factory=a.ClosingConnection) as db:
            db.execute("UPDATE orchestration_v2_projection_threads SET deleted_at='now' WHERE thread_id='import:codex:new'")
        self.assertEqual(a.build_plan(self.db_path,self.codex)['events'],[])

    def test_chats_continued_in_t3_are_not_moved(self):
        self.apply(a.build_plan(self.db_path,self.codex))
        with sqlite3.connect(str(self.codex/'state_5.sqlite'),factory=a.ClosingConnection) as db:
            db.execute('UPDATE threads SET cwd=?',(str(self.other_root),))
        with sqlite3.connect(str(self.db_path),factory=a.ClosingConnection) as db:
            db.execute("INSERT INTO orchestration_v2_projection_runs(run_id,thread_id,ordinal,provider,status,requested_at,payload_json) VALUES ('run','import:codex:new',1,'codex','completed','0','{}')")
        plan=a.build_plan(self.db_path,self.codex)
        self.assertEqual(plan['events'],[])
        self.assertIn('continued inside T3',plan['threads'][0]['reason'])

    def test_existing_native_owner_prevents_duplicate_initial_import(self):
        with sqlite3.connect(str(self.db_path),factory=a.ClosingConnection) as db:
            db.execute("INSERT INTO orchestration_v2_projection_provider_threads(provider_thread_id,thread_id,provider,status,updated_at,payload_json,driver,provider_instance_id) VALUES ('owned','native-chat','codex','idle','0',?,'codex','codex')",
                       (json.dumps({'nativeThreadRef':{'nativeId':'new'}}),))
        plan=a.build_plan(self.db_path,self.codex)
        self.assertEqual(plan['events'],[])
        self.assertIn('already owned',plan['threads'][0]['reason'])

    def test_duplicate_project_roots_are_refused(self):
        with sqlite3.connect(str(self.db_path),factory=a.ClosingConnection) as db:
            db.execute('UPDATE projection_projects SET workspace_root=?',(str(self.project_root),))
        plan=a.build_plan(self.db_path,self.codex)
        self.assertEqual(plan['events'],[])
        self.assertIn('several T3 projects',plan['threads'][0]['reason'])

    def test_path_normalization_handles_windows_device_prefixes(self):
        self.assertEqual(a.normalize_project_path(r'\\?\C:\My Project'),a.normalize_project_path('c:/my project/'))
        self.assertEqual(a.normalize_project_path(r'\\?\UNC\server\share\x'),a.normalize_project_path(r'\\server\share\x'))


if __name__=='__main__':
    unittest.main()
