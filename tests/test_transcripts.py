import gzip
import json
from pathlib import Path
import sys
import tempfile
import tracemalloc
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import transcripts as t
import autosync as a


def line(kind, payload):
    return (json.dumps({'type':kind,'timestamp':'2026-11-20T08:00:00.000Z','payload':payload},
                       ensure_ascii=False)+'\n').encode('utf-8')


class StreamingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root/'history.jsonl'
        self.cache = self.root/'cache'

    def tearDown(self):
        self.temp.cleanup()

    def seed(self):
        self.path.write_bytes(line('session_meta',{'id':'session'})+
            line('response_item',{'type':'message','role':'user','content':[{'type':'input_text','text':'hello'}]})+
            line('event_msg',{'type':'task_complete'}))

    def test_large_ignored_strings_use_bounded_memory(self):
        with self.path.open('wb') as output:
            output.write(line('session_meta',{'id':'session'}))
            output.write(b'{"type":"response_item","payload":{"type":"function_call_output","output":"')
            block = b'x'*(1024*1024)
            for _ in range(40):
                output.write(block)
            output.write(b'"}}\n')
            output.write(line('event_msg',{'type':'task_complete'}))
        tracemalloc.start()
        try:
            records,guard,stats = t.scan(self.path,cache_dir=self.cache,writable=True)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertEqual(len(records),2)
        self.assertGreater(stats['parsedBytes'],40*1024*1024)
        self.assertLess(peak,4*1024*1024)
        self.assertTrue(t.verify_guard(self.path,guard))
        self.assertLess(sum(p.stat().st_size for p in self.cache.iterdir()),4096)

    def test_unicode_and_escapes_across_tiny_chunks(self):
        text = '한글 😀 \\ " \n end'
        self.path.write_bytes(line('session_meta',{'id':'session'})+
            line('response_item',{'type':'message','role':'assistant',
                'content':[{'type':'output_text','text':text},{'type':'image','image_url':'ignored'}]})+
            line('event_msg',{'type':'task_complete'}))
        with patch.object(t,'CHUNK',7):
            records,_,_ = t.scan(self.path)
        self.assertEqual(a.parse_messages(records)[0]['text'],text.strip())
        self.assertNotIn('image_url',records[1]['payload']['content'][1])

    def test_cache_parses_only_append_and_rejects_changed_prefix(self):
        self.seed()
        old_size = self.path.stat().st_size
        _,guard,_ = t.scan(self.path,cache_dir=self.cache,writable=True)
        extra = line('event_msg',{'type':'user_message','message':'new question'})+line('event_msg',{'type':'task_complete'})
        with self.path.open('ab') as output:
            output.write(extra)
        records,_,stats = t.scan(self.path,cache_dir=self.cache,writable=True)
        self.assertTrue(stats['cacheHit'])
        self.assertEqual(stats['parsedBytes'],len(extra))
        self.assertEqual(stats['verifiedPrefixBytes'],old_size)
        self.assertTrue(t.verify_guard(self.path,guard))  # Appending does not invalidate settled history.
        self.path.write_bytes(self.path.read_bytes().replace(b'hello',b'other'))
        records,_,stats = t.scan(self.path,cache_dir=self.cache,writable=True)
        self.assertFalse(stats['cacheHit'])
        self.assertFalse(t.verify_guard(self.path,guard))
        self.assertEqual(a.parse_messages(records)[0]['text'],'other')

    def test_partial_tail_is_revisited_and_completed_malformed_record_is_rejected(self):
        self.seed()
        old_size = self.path.stat().st_size
        with self.path.open('ab') as output:
            output.write(b'{broken')
        _,guard,_ = t.scan(self.path,cache_dir=self.cache,writable=True)
        self.assertEqual(guard['offset'],old_size)
        with self.path.open('ab') as output:
            output.write(b'\n')
        with self.assertRaises(t.TranscriptError):
            t.scan(self.path,cache_dir=self.cache,writable=True)

    def test_cache_corruption_rebuilds_and_preview_creates_no_files(self):
        self.seed()
        t.scan(self.path,cache_dir=self.cache)
        self.assertFalse(self.cache.exists())
        original,_,_ = t.scan(self.path,cache_dir=self.cache,writable=True)
        cache = next(self.cache.glob('*.gz'))
        with gzip.open(cache,'rt',encoding='utf-8') as source:
            data=json.load(source)
        data['records'][1]['payload']['content'][0]['text']='corrupt'
        with gzip.open(cache,'wt',encoding='utf-8') as output:
            json.dump(data,output)
        records,_,stats=t.scan(self.path,cache_dir=self.cache,writable=True)
        self.assertFalse(stats['cacheHit'])
        self.assertEqual(records,original)
        cache.write_bytes(b'broken gzip')
        self.assertEqual(t.scan(self.path,cache_dir=self.cache)[0],original)

    def test_inherited_boundary_requires_a_complete_record(self):
        self.seed()
        with self.assertRaises(t.TranscriptError):
            t.scan(self.path,byte_limit=self.path.stat().st_size-1)

    def test_invalid_utf8_is_rejected_even_in_ignored_data(self):
        self.path.write_bytes(b'{"type":"response_item","payload":{"output":"bad\xff"}}\n')
        with self.assertRaises(t.TranscriptError):
            t.scan(self.path)

    def test_selected_container_budget_is_enforced_during_parsing(self):
        self.path.write_bytes(line('response_item',{'type':'message','role':'user',
            'content':[{'type':'input_text','text':'small'} for _ in range(100)]}))
        with patch.object(t,'MAX_HISTORY',2048),self.assertRaises(t.TranscriptError):
            t.scan(self.path)


if __name__=='__main__':
    unittest.main()
