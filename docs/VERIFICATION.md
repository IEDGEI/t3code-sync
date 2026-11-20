# Windows preview verification

Release target: `v1.1.0-windows-preview`.

## Local checks

- 30 synthetic sync tests passed, including deterministic SQLite handle closure and rollback.
- 11 project/import tests passed: current membership, initial thread/provider/runtime mapping, duplicate prevention, project moves, source/index changes, ambiguity, archived/subagent filtering and deleted/native-owned chat guards.
- 8 streaming/cache tests passed: large ignored strings with bounded allocations, Unicode chunk boundaries, incremental parsing, rewrite detection, partial tails, corrupted caches, invalid UTF-8 and selected-container budgets.
- 4 Windows installer tests passed under Windows PowerShell 5.1.
- 1 distribution test passed: the ZIP contains exactly the public allowlist, includes both MIT notices, normalizes CMD line endings, excludes local config/database files, and has valid internal/external checksums.
- Python compilation and JavaScript/PowerShell syntax checks passed.
- Public source was scanned for the originating user's private paths, email address, credential patterns and private-key headers; no matches were found.

The installer tests use a schema-only database and synthetic Codex records. They cover preview without mutation, Unicode/space-containing paths, app discovery, installation/reinstallation from the extracted release ZIP, automatic dedicated shortcut creation, existing desktop/app-folder shortcut redirection and backups (including same-named icons with identical backup timestamps), preservation of custom arguments and unrelated shortcuts, and rejection of unsupported T3 versions before installation.

## Actual T3 validation

The Windows sync core was exercised against T3 Code 0.1.9, migration 81. It was first checked on an isolated copy, then through the installed T3 CLI after applying an update with a verified backup. The latest message matched, database integrity returned `ok`, and the next sync plan contained zero additions.

The 1.1.0 path was checked with a local transcript larger than 2 GiB and an isolated T3 database. Selected records were under 1 MiB; compressed caches for the tested projects occupied about 0.5 MiB. Initial import produced a third chat in its current project, and a subsequent plan contained zero additions/events. This is one measured local workload, not a general storage or performance guarantee.

After backup and installation, the real T3 0.1.9 server's official `thread list` returned all three chats in the target project and `thread show` decoded the imported chat as idle/settled with 200 messages plus an omission notice. Live database and backup integrity checks returned `ok`. A later read parsed only the newly appended portion while verifying the large cached prefix. No new provider/model turn was started during validation.

This documents a limited tested environment, not compatibility with every Windows/T3 installation. Linux and macOS have not been validated and are not supported by this preview. The GitHub workflow provides additional synthetic Windows test coverage; a green run does not substitute for actual T3 compatibility validation.
