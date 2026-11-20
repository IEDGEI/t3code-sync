# Windows preview

Refresh imported Codex chats before launching T3 Code. This is an independent community tool for Windows, tested against T3 Code 0.1.9 / migration 81 and a pinned schema fingerprint.

## Install

1. Install Python 3.9+ and Node.js 22.13+ with modern SQLite/FTS5 if they are not already available.
2. Download and extract `T3-Codex-AutoSync-Windows.zip`.
3. Run `Install.cmd`, fully close T3, and use the **T3 Code (Auto Sync)** desktop shortcut.

The installer checks local compatibility before installing. It does not download dependencies or write conversation databases. The runtime performs local sync without model calls or token usage.

## Preview limits

- Existing imported Codex chats only; no new-project or initial-chat import.
- New settled user/assistant text only; no attachments or tool activity.
- T3 must be fully stopped before syncing.
- Chats continued inside T3, divergent history, and missing/compressed source transcripts are skipped.
- Other T3 database schemas are rejected. Do not disable this guard.
- Linux and macOS are not supported in this release.

The tool writes T3's local database and creates verified backups. Read the recovery instructions before use. A sync error is recorded in `last-sync.json`; T3 can still open afterward.

Checksums for the archive are attached in `SHA256SUMS.txt`. Upstream MIT notices are included in the ZIP.
