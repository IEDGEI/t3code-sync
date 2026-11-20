# Contributing

This preview supports Windows and one T3 database schema. Linux and macOS contributions are welcome, but support must be backed by platform-specific tests and real T3 validation.

Run all tests and the package builder before opening a change:

```powershell
python -m unittest discover -s . -p "test_*.py" -v
python build_package.py
```

Use synthetic messages and a schema-only fixture. Never commit config files, transcripts, SQLite databases, local logs, backups, credentials or personal paths. An issue report should contain only the environment and a redacted error reason.

Do not broaden a supported schema fingerprint merely to make a newer T3 build pass. Validate the relevant event, projection, index and checkpoint behavior on a copy of the database, test rollback and duplicate prevention, and verify the result through T3 itself.

Keep Codex sources read-only. Any future support for chats continued inside T3 needs explicit reconciliation and divergence tests. The current implementation intentionally skips those chats.

Platform ports must detect both desktop and background servers and must not terminate unrelated processes. Document which app packaging and service configurations were actually tested.
