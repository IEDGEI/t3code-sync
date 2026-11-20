# Changelog

## 1.1.0 — Windows preview

- Import missing Codex user chats into existing active T3 projects using current Codex membership, including moved chats whose original transcript names an older folder.
- Correct eligible imported chats' project links and resume directories without creating duplicate native-thread owners.
- Stream large JSONL files with bounded field selection; cache compressed text and parser cursors, parse appended records incrementally, and verify source prefixes with SHA-256.
- Preserve partial tails, rescan changed/replaced/truncated sources and damaged caches, and keep preview read-only.
- Initialize canonical thread/provider events, runtime resume data and matching projections atomically with verified backups.
- Keep initial history to the first message and recent history, up to 200 messages, with an explicit notice for omitted earlier messages.
- Exclude archived/subagent sources, deleted T3 chats and ambiguous/native-owned matches; pause project moves for native T3 activity or branch/worktree settings.

## 1.0.3 — Windows preview

- Explain automatic desktop shortcut creation, which icons run sync, and the requirement to fully close T3 before launching.
- Document reinstalling the current ZIP to upgrade or repair an installed launcher, and checking sync status.
- Show the dedicated shortcut path in installer output and clarify the CMD completion message.
- Cover automatic redirection and backup of existing desktop/app-folder shortcuts while preserving custom arguments and unrelated shortcuts.
- Give shortcut backups unique filenames so same-named icons from different folders cannot overwrite one another within one clock tick.

## 1.0.2 — Windows preview

- Organize runtime code, scripts, tests and supporting documentation into folders.
- Keep a top-level installer in the release ZIP and verify installation from the extracted package.
- Fix CMD handling of parentheses in the success message and preserve installer failure exit codes.
- Remove the personal laptop installation guide from public source and packages.

## 1.0.1 — Windows preview

- Update existing imported Codex conversations before launching T3 Code.
- Keep Codex sources read-only and append newly settled visible text only.
- Guard against running T3 instances, source changes and unsupported database schemas.
- Back up and integrity-check the database before committing events and matching projections atomically.
- Provide a Windows installer with runtime/app discovery, custom data paths and shortcut backups.
- Use Unicode Shell links and explicitly closed SQLite connections across Windows locales and Python versions.
- Include a read-only preview command, a public-file-only ZIP builder and synthetic regression tests.
- Publish English/Korean documentation, recovery instructions and upstream MIT notices.

Compatibility: T3 Code 0.1.9, migration 81, pinned schema fingerprint. Windows only. Linux validation is planned on a laptop; macOS support is planned. Neither platform is currently supported.
