"""Bounded JSONL projection and an optional, disposable local text cache."""
import gzip
import codecs
import hashlib
import json
import os
from pathlib import Path
import re


class TranscriptError(Exception):
    pass


class Incomplete(Exception):
    pass


CHUNK = 64 * 1024
MAX_STRING = 16 * 1024 * 1024
MAX_HISTORY = 64 * 1024 * 1024
SPECIAL = re.compile(rb'["\\\x00-\x1f]')
NUMBER = re.compile(rb'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z')
ROOT = {'type', 'timestamp', 'payload'}
PAYLOAD = {'id', 'session_id', 'type', 'role', 'message', 'cwd', 'history_base',
           'content', 'internal_chat_message_metadata_passthrough'}


def selected(path):
    if not path:
        return True
    if path[0] not in ROOT:
        return False
    if len(path) == 1:
        return True
    if path[0] != 'payload' or path[1] not in PAYLOAD:
        return False
    if len(path) == 2:
        return True
    if path[1] == 'content':
        return len(path) == 3 or len(path) == 4 and path[3] in ('type', 'text')
    if path[1] == 'history_base':
        return len(path) == 3 and path[2] in ('thread_id', 'end_byte_offset')
    if path[1] == 'internal_chat_message_metadata_passthrough':
        return path[2] in ('turn_id', 'content_item_kinds') and len(path) <= 4
    return False


class Reader:
    def __init__(self, stream, limit, digest=None):
        self.stream, self.limit = stream, limit
        self.base = stream.tell()
        self.buffer = b''
        self.pos = self.hashed = 0
        self.hash = digest or hashlib.sha256()
        self.line_ended = False
        self.projected = 0
        self.budget = MAX_HISTORY

    def charge(self, amount):
        self.projected += amount
        if self.projected > self.budget:
            raise TranscriptError('Selected transcript structure exceeds the 64 MiB cache budget.')

    @property
    def offset(self):
        return self.base + self.pos

    def digest(self):
        self.hash.update(self.buffer[self.hashed:self.pos])
        self.hashed = self.pos
        return self.hash.copy()

    def peek(self):
        if self.pos == len(self.buffer):
            self.digest()
            self.base += self.pos
            self.buffer = self.stream.read(min(CHUNK, max(0, self.limit - self.base)))
            self.pos = self.hashed = 0
            if not self.buffer:
                raise Incomplete()
        return self.buffer[self.pos]

    def take(self):
        value = self.peek()
        self.pos += 1
        if value == 10:
            self.line_ended = True
        return value

    def space(self):
        while self.peek() in (32, 9, 13):
            self.pos += 1

    def string(self, keep, key=False):
        if self.take() != 34:
            raise TranscriptError('Malformed source transcript; expected a JSON string.')
        parts = []
        length = 0
        decoder = None if keep else codecs.getincrementaldecoder('utf-8')('strict')
        while True:
            self.peek()
            match = SPECIAL.search(self.buffer, self.pos)
            end = match.start() if match else len(self.buffer)
            if keep:
                piece = self.buffer[self.pos:end]
                parts.append(piece)
                length += len(piece)
                if not key:
                    self.charge(len(piece))
                if length > MAX_STRING:
                    raise TranscriptError('A selected transcript string exceeds the 16 MiB budget.')
            else:
                try:
                    decoder.decode(self.buffer[self.pos:end])
                except UnicodeDecodeError as exc:
                    raise TranscriptError('Malformed UTF-8 in source transcript.') from exc
            self.pos = end
            if not match:
                continue
            char = self.take()
            if char == 34:
                if not keep:
                    try:
                        decoder.decode(b'',final=True)
                    except UnicodeDecodeError as exc:
                        raise TranscriptError('Malformed UTF-8 in source transcript.') from exc
                    return None
                try:
                    return json.loads(b'"' + b''.join(parts) + b'"')
                except (ValueError, UnicodeDecodeError) as exc:
                    raise TranscriptError('Malformed source transcript string.') from exc
            if char != 92:
                raise TranscriptError('Unescaped control character in source transcript.')
            escape = self.take()
            raw = bytes((92, escape))
            if escape == 117:
                digits = bytes(self.take() for _ in range(4))
                if not all(value in b'0123456789abcdefABCDEF' for value in digits):
                    raise TranscriptError('Malformed Unicode escape in source transcript.')
                raw += digits
            elif escape not in b'"\\/bfnrt':
                raise TranscriptError('Malformed escape in source transcript.')
            if keep:
                parts.append(raw)
                length += len(raw)
                if not key:
                    self.charge(len(raw))
            else:
                try:
                    decoder.decode(raw)
                except UnicodeDecodeError as exc:
                    raise TranscriptError('Malformed UTF-8 in source transcript.') from exc

    def value(self, path=(), depth=0, keep=True):
        if depth > 64:
            raise TranscriptError('Source transcript JSON is nested too deeply.')
        self.space()
        keep = keep and selected(path)
        if keep:
            self.charge(128)
        char = self.peek()
        if char == 34:
            return self.string(keep)
        if char == 123:
            self.pos += 1
            result = {} if keep else None
            self.space()
            if self.peek() == 125:
                self.pos += 1
                return result
            while True:
                key = self.string(True,key=True)
                if len(key) > 4096:
                    raise TranscriptError('Source transcript key is too long.')
                self.space()
                if self.take() != 58:
                    raise TranscriptError('Malformed source transcript object.')
                use = keep and selected(path + (key,))
                value = self.value(path + (key,), depth + 1, use)
                if use:
                    result[key] = value
                self.space()
                separator = self.take()
                if separator == 125:
                    return result
                if separator != 44:
                    raise TranscriptError('Malformed source transcript object separator.')
                self.space()
        if char == 91:
            self.pos += 1
            result = [] if keep else None
            self.space()
            if self.peek() == 93:
                self.pos += 1
                return result
            index = 0
            while True:
                value = self.value(path + (index,), depth + 1, keep)
                if keep:
                    result.append(value)
                self.space()
                separator = self.take()
                if separator == 93:
                    return result
                if separator != 44:
                    raise TranscriptError('Malformed source transcript array separator.')
                index += 1
        if char in (116, 102, 110):
            word, value = {116:(b'true', True), 102:(b'false', False), 110:(b'null', None)}[char]
            if bytes(self.take() for _ in word) != word:
                raise TranscriptError('Malformed source transcript literal.')
            return value if keep else None
        digits = bytearray()
        while True:
            try:
                char = self.peek()
            except Incomplete:
                break
            if char not in b'-+0123456789.eE':
                break
            digits.append(self.take())
            if len(digits) > 128:
                raise TranscriptError('Source transcript number is too long.')
        if not NUMBER.fullmatch(digits):
            raise TranscriptError('Malformed source transcript value.')
        return json.loads(digits) if keep else None


def keep_record(record):
    if not isinstance(record, dict):
        raise TranscriptError('A source transcript record is not an object.')
    payload = record.get('payload') or {}
    if not isinstance(payload, dict):
        return False
    kind = record.get('type')
    if kind == 'event_msg' and payload.get('type') in ('thread_rolled_back', 'thread_rollback'):
        raise TranscriptError('Codex history contains a rollback; manual reconciliation is required.')
    return (kind == 'session_meta' or kind == 'event_msg' and payload.get('type') in
            ('user_message', 'task_started', 'task_complete', 'turn_aborted') or
            kind == 'response_item' and payload.get('type') == 'message' and
            payload.get('role') in ('user', 'assistant'))


def fingerprint(stream, length):
    stream.seek(0)
    digest = hashlib.sha256()
    remaining = length
    while remaining:
        block = stream.read(min(1024 * 1024, remaining))
        if not block:
            raise TranscriptError('Source transcript was truncated while reading.')
        digest.update(block)
        remaining -= len(block)
    return digest


def file_id(stat):
    return [stat.st_dev, stat.st_ino]


def verify_guard(path, guard):
    try:
        with Path(path).open('rb') as stream:
            if file_id(os.fstat(stream.fileno())) != guard['fileId']:
                return False
            return fingerprint(stream, guard['offset']).hexdigest() == guard['sha256']
    except (OSError, TranscriptError):
        return False


def scan(path, byte_limit=None, cache_dir=None, writable=False):
    path = Path(path)
    if not path.is_file() or path.suffix != '.jsonl':
        raise TranscriptError('Source transcript is missing or compressed; left unchanged.')
    cache_path = None
    cache = None
    if cache_dir is not None:
        key = hashlib.sha256((str(path.resolve()) + ':' + str(byte_limit)).encode()).hexdigest()
        cache_path = Path(cache_dir) / (key + '.json.gz')
        try:
            with gzip.open(cache_path, 'rb') as source:
                data = source.read(MAX_HISTORY + 1024 * 1024 + 1)
                if len(data) <= MAX_HISTORY + 1024 * 1024:
                    cache = json.loads(data)
        except (OSError, EOFError, ValueError):
            pass  # A cache is disposable; source validation is authoritative.
    with path.open('rb') as stream:
        stat = os.fstat(stream.fileno())
        size = stat.st_size if byte_limit is None else byte_limit
        if size > stat.st_size or size < 0:
            raise TranscriptError('Inherited source boundary is unavailable.')
        records = []
        offset = 0
        digest = hashlib.sha256()
        hit = False
        if isinstance(cache, dict) and cache.get('version') == 1:
            old = cache.get('guard', {})
            if (old.get('fileId') == file_id(stat) and isinstance(old.get('offset'), int)
                    and 0 <= old['offset'] <= size and isinstance(cache.get('records'), list)):
                digest = fingerprint(stream, old['offset'])
                encoded = json.dumps(cache['records'],ensure_ascii=False,separators=(',', ':')).encode('utf-8')
                if (digest.hexdigest() == old.get('sha256') and
                        hashlib.sha256(encoded).hexdigest() == cache.get('recordsSha256')):
                    records = cache['records']
                    offset = old['offset']
                    hit = True
        if not hit:
            digest = hashlib.sha256()
        stream.seek(offset)
        reader = Reader(stream, size, digest)
        retained_bytes = sum(len(json.dumps(record, ensure_ascii=False).encode('utf-8')) for record in records)
        complete = offset
        completed_hash = digest.copy()
        while reader.offset < size:
            reader.line_ended = False
            reader.projected = 0
            reader.budget = MAX_HISTORY - retained_bytes
            try:
                record = reader.value()
                reader.space()
                if reader.take() != 10:
                    raise TranscriptError('Malformed source transcript record separator.')
            except Incomplete:
                if byte_limit is not None:
                    raise TranscriptError('Inherited Codex history ends inside a record.')
                break
            except TranscriptError:
                if reader.line_ended or byte_limit is not None:
                    raise
                # A malformed unfinished last line is still an uncommitted
                # writer tail. Completed malformed records remain errors.
                ended = False
                try:
                    while reader.offset < size:
                        reader.peek()
                        newline = reader.buffer.find(b'\n',reader.pos)
                        if newline >= 0:
                            ended = True
                            break
                        reader.pos = len(reader.buffer)
                except Incomplete:
                    pass
                if ended:
                    raise
                break
            if keep_record(record):
                retained_bytes += len(json.dumps(record, ensure_ascii=False).encode('utf-8'))
                if retained_bytes > MAX_HISTORY:
                    raise TranscriptError('Selected transcript text exceeds the 64 MiB cache budget.')
                records.append(record)
            complete = reader.offset
            completed_hash = reader.digest()
        guard = {'fileId':file_id(stat), 'offset':complete, 'sha256':completed_hash.hexdigest()}
        if file_id(path.stat()) != guard['fileId']:
            raise TranscriptError('Source transcript was replaced while reading.')
    if cache_path is not None and writable:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_suffix('.tmp')
        with gzip.open(temporary, 'wt', encoding='utf-8', compresslevel=3) as target:
            encoded = json.dumps(records,ensure_ascii=False,separators=(',', ':')).encode('utf-8')
            json.dump({'version':1, 'guard':guard, 'records':records,
                       'recordsSha256':hashlib.sha256(encoded).hexdigest()},target,ensure_ascii=False,separators=(',', ':'))
        os.replace(temporary, cache_path)
    return records, guard, {'cacheHit':hit, 'parsedBytes':complete-offset,
                            'verifiedPrefixBytes':offset if hit else 0,
                            'sourceBytes':size, 'selectedBytes':retained_bytes}
