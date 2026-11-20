# Changelog

## 1.0.1 — Windows preview

- Update existing imported Codex conversations before launching T3 Code.
- Keep Codex sources read-only and append newly settled visible text only.
- Guard against running T3 instances, source changes and unsupported database schemas.
- Back up and integrity-check the database before committing events and matching projections atomically.
- Provide a Windows installer with runtime/app discovery, custom data paths and shortcut backups.
- Include a read-only preview command, a public-file-only ZIP builder and synthetic regression tests.
- Publish English/Korean documentation, recovery instructions and upstream MIT notices.

Compatibility: T3 Code 0.1.9, migration 81, pinned schema fingerprint. Windows only. Linux validation is planned on a laptop; macOS support is planned. Neither platform is currently supported.
