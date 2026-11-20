# Windows preview verification

Release target: `v1.0.3-windows-preview`.

## Local checks

- 30 synthetic sync tests passed, including deterministic SQLite handle closure and rollback.
- 4 Windows installer tests passed under Windows PowerShell 5.1.
- 1 distribution test passed: the ZIP contains exactly the public allowlist, includes both MIT notices, normalizes CMD line endings, excludes local config/database files, and has valid internal/external checksums.
- Python compilation and JavaScript/PowerShell syntax checks passed.
- Public source was scanned for the originating user's private paths, email address, credential patterns and private-key headers; no matches were found.

The installer tests use a schema-only database and synthetic Codex records. They cover preview without mutation, Unicode/space-containing paths, app discovery, installation/reinstallation from the extracted release ZIP, automatic dedicated shortcut creation, existing desktop/app-folder shortcut redirection and backups (including same-named icons with identical backup timestamps), preservation of custom arguments and unrelated shortcuts, and rejection of unsupported T3 versions before installation.

## Actual T3 validation

The Windows sync core was exercised against T3 Code 0.1.9, migration 81. It was first checked on an isolated copy, then through the installed T3 CLI after applying an update with a verified backup. The latest message matched, database integrity returned `ok`, and the next sync plan contained zero additions.

This documents a limited tested environment, not compatibility with every Windows/T3 installation. Linux and macOS have not been validated and are not supported by this preview. The GitHub workflow provides additional synthetic Windows test coverage; a green run does not substitute for actual T3 compatibility validation.
