# Windows preview

Version 1.1.0 imports missing user chats into existing T3 projects using Codex's current project membership, and corrects eligible imported chats' project links. Old folder paths inside a transcript no longer determine its destination.

Large JSONL transcripts are streamed without the previous 512 MiB raw-file cap. Compressed private text caches store parser cursors; subsequent launches parse appended records while SHA-256 still reads and verifies the cached prefix. Source edits, replacement, truncation and damaged caches trigger a rescan. Preview leaves caches unchanged.

Initial history retains the first visible message and recent history, up to 200 messages, and displays a notice for omitted messages. New settled messages are appended on later launches. Source transcripts remain unchanged.

Fully exit T3, then open the dedicated shortcut to refresh imported chats. If T3 is already running, the update is deferred. Start menu/taskbar entries are not changed. To upgrade or repair an existing launcher, extract the current ZIP and run `Install.cmd` again.

Refresh imported Codex chats before launching T3 Code. This is an independent community tool for Windows, tested against T3 Code 0.1.9 / migration 81 and a pinned schema fingerprint.

## Install

1. Install Python 3.9+ and Node.js 22.13+ with modern SQLite/FTS5 if they are not already available.
2. Download and extract `T3-Codex-AutoSync-Windows.zip`.
3. Run `Install.cmd`. It automatically creates the **T3 Code (Auto Sync)** desktop shortcut.
4. Fully close T3, then open that shortcut.

The installer checks local compatibility before installing. It does not download dependencies or write conversation databases. The runtime performs local sync without model calls or token usage.

## Preview limits

- Missing chats are imported only into matching existing active T3 projects; add new projects in T3 first.
- Archived/subagent sources, deleted T3 chats and ambiguous/native-owned matches are excluded.
- Project moves are paused for native T3 runs or branch/worktree settings.
- New settled user/assistant text only; no attachments or tool activity.
- T3 must be fully stopped before syncing.
- Chats continued inside T3, divergent history, and missing/compressed source transcripts are skipped.
- Other T3 database schemas are rejected. Do not disable this guard.
- Linux and macOS are not supported in this release.

The tool writes T3's local database and creates verified backups. Read the recovery instructions before use. A sync error is recorded in `last-sync.json`; T3 can still open afterward.

The `source-cache` folder contains private conversation text. Keep it private along with database backups. Selected strings are limited to 16 MiB and selected history/structure to a 64 MiB budget; the tool reports unsupported records instead of silently truncating their text.

Checksums for the archive are attached in `SHA256SUMS.txt`. Upstream MIT notices are included in the ZIP.
