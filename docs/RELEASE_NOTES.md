# Windows preview

Version 1.0.3 clarifies automatic shortcut creation and how to launch auto-sync. The installer creates **T3 Code (Auto Sync)** on the desktop, reports its path, and connects matching existing desktop/app-folder shortcuts by default. Original shortcuts are backed up; custom arguments are preserved.

Shortcut backups now use unique filenames, preserving separate originals even when icons in different folders share a name and timestamp.

Fully exit T3, then open the dedicated shortcut to refresh imported chats. If T3 is already running, the update is deferred. Start menu/taskbar entries are not changed. To upgrade or repair an existing launcher, extract the current ZIP and run `Install.cmd` again.

Refresh imported Codex chats before launching T3 Code. This is an independent community tool for Windows, tested against T3 Code 0.1.9 / migration 81 and a pinned schema fingerprint.

## Install

1. Install Python 3.9+ and Node.js 22.13+ with modern SQLite/FTS5 if they are not already available.
2. Download and extract `T3-Codex-AutoSync-Windows.zip`.
3. Run `Install.cmd`. It automatically creates the **T3 Code (Auto Sync)** desktop shortcut.
4. Fully close T3, then open that shortcut.

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
