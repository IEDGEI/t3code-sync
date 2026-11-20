# t3code-sync

Import missing Codex chats and refresh existing history in matching T3 projects before launch.

[한국어 안내](README.ko.md) · [Windows download](https://github.com/IEDGEI/t3code-sync/releases/tag/v1.1.0-windows-preview) · [Recovery](docs/RECOVERY.md) · [Roadmap](docs/github.md)

**Windows preview.** Tested with T3 Code **0.1.9**, database migration **81** and a specific schema fingerprint. Other schemas are rejected before writing. Linux and macOS are not supported yet. This is an independent community tool, unaffiliated with T3 Tools or OpenAI.

## The problem

T3's imported copy can remain at its earlier state after you continue a chat in Codex. A chat moved to another Codex project can also retain its original folder in its transcript. This tool uses Codex's current project membership to import missing chats into existing T3 projects, correct eligible imported chats' project links, and append settled user/assistant messages before T3 starts.

It operates locally. No model calls, API keys, cloud uploads or AI tokens are used by the sync operation.

## Install on Windows

Requirements:

- Windows desktop session.
- T3 Code 0.1.9 with a compatible migration-81 database, and the target projects already added in T3.
- Local Codex history at `CODEX_HOME` or `%USERPROFILE%\.codex`.
- Python 3.9+ with `pythonw.exe`, and Node.js 22.13+ with modern SQLite/FTS5. Local validation used Python 3.9 and Node.js 24.15.

1. Download **T3-Codex-AutoSync-Windows.zip** from the [Windows preview release](https://github.com/IEDGEI/t3code-sync/releases/tag/v1.1.0-windows-preview).
2. Extract the archive, then run **Install.cmd**. Review the source before running it. Windows may display a warning because these scripts are unsigned.
3. The installer finds the local executables, checks the database schema, and **automatically creates a desktop shortcut named T3 Code (Auto Sync)**. You do not need to create it yourself. It does not download dependencies or modify the T3 database.
4. Fully close T3, then launch **T3 Code (Auto Sync)** from the desktop.

By default, existing desktop or app-folder shortcuts that directly target the detected T3 executable without extra arguments are also connected to auto-sync; their originals are backed up. Shortcuts with extra arguments are preserved. `-SkipExistingShortcuts` leaves existing icons alone while still creating the dedicated shortcut.

### Which shortcut should I use?

Use **T3 Code (Auto Sync)** for the clearest result. Automatic updates run **before T3 starts**: fully exit T3, including any background server, then open this shortcut. If T3 is already running, the shortcut opens the existing app and defers the update until a later launch.

| Launch route | Runs auto-sync? |
| --- | --- |
| T3 Code (Auto Sync) desktop shortcut | Yes, when T3 is fully stopped |
| Existing icon connected by the installer | Yes, under the same condition |
| Original T3 executable, unchanged Start menu or taskbar entry | No |

The installer does not change Start menu or taskbar entries. When in doubt, use the dedicated desktop shortcut.

### Upgrade or repair an existing installation

Download and extract the current ZIP, then run `Install.cmd` again. This installs the current launcher and recreates the dedicated shortcut. **Downloading a ZIP or updating the GitHub checkout alone does not update an installed launcher.**

If a conversation still looks old, first fully close T3 and reopen it from **T3 Code (Auto Sync)**. Then inspect `%USERPROFILE%\.t3\codex-autosync\last-sync.json` (or the corresponding custom data folder): `messages` shows additions, `deferred_t3_running` means T3 was still running, and `skipped` entries explain unavailable or divergent source history. Missing chats are imported automatically only when their current Codex project matches one existing active T3 project. Add entirely new projects in T3 first.

For custom paths, run from the extracted directory:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Preview
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 -T3Exe "D:\Apps\T3 Code (Beta).exe"
```

Optional installer arguments: `-PythonExe`, `-NodeExe`, `-T3Home`, `-CodexHome`, `-InstallDir`, `-ShortcutDir`, `-SkipExistingShortcuts` and `-Preview`. `T3CODE_HOME` and `CODEX_HOME` take precedence over their default user directories.

## How it works

1. Check whether the T3 app or its recorded server is running.
2. Read Codex's current project index and stream the JSONL transcripts read-only, discarding image data and tool output.
3. Import missing user chats into matching existing projects, correct eligible project links, and align existing history. Defer unfinished turns and refuse changed or divergent history.
4. Prepare canonical T3 events and matching projections in a transaction using Node's SQLite runtime.
5. Create and integrity-check a pre-update SQLite backup. Recheck the source and running-app guard before committing.
6. Commit thread/provider initialization, project links, message/timeline projections, search updates and checkpoint together, then launch T3.

The tool does not patch T3's installed application files. It **does write T3's internal local database**, which is why this release is a preview with a strict schema gate. If an error occurs, the transaction is rolled back where possible, a status report is written, and the launcher still opens T3. Inspect `last-sync.json` to confirm whether sync succeeded.

## Scope and limitations

| Supported in this preview | Deferred or unsupported |
| --- | --- |
| Missing Codex chats in existing active T3 projects | Creating new T3 projects |
| Current Codex project membership and imported-history moves | Moving chats with native T3 runs or branch/worktree settings |
| Settled or interrupted turns | Currently active turns |
| New visible user/assistant text | Images, attachments and tool activity |
| Unchanged imported baseline | Conversations continued inside T3 or edited/divergent histories |
| Plain local JSONL transcripts | Missing/compressed source transcripts |
| Up to 500 new messages per launch | Cross-device or bidirectional sync |

The tool does not restore earlier history omitted by T3's original import. After reaching the batch limit, further messages can be added on a later launch. Some generated setup context is filtered from new additions. Existing records are preserved.

An initial import keeps the first visible message and the most recent history, up to **200 messages**, with a notice when earlier messages were omitted. The source transcript stays intact. Subsequent launches append newly settled messages. Archived/subagent/Guardian sources, deleted T3 chats, ambiguous project matches and chats already owned by another native T3 thread are not auto-imported.

### Large transcripts and incremental parsing

There is no 512 MiB raw-file cap. The reader consumes fixed-size chunks and projects only the fields needed for text/history alignment. Selected strings are limited to 16 MiB and selected history/structure to a 64 MiB budget; exceeding a budget skips the chat with a reason instead of silently truncating its text.

After a first scan, a compressed private cache stores selected records and a byte cursor. Later launches parse only newly completed JSONL records. SHA-256 verification still **reads the cached prefix** to detect rewrites; parsing and verification are separate costs. Truncation, replacement, changed prefixes and corrupt caches trigger a full rescan. Unfinished final lines are revisited on the next launch. `--preview` can read existing caches but does not create or change them.

## Status, backups and removal

Defaults:

- Program: `%USERPROFILE%\.t3\tools\codex-autosync`
- Status and backups: `%USERPROFILE%\.t3\codex-autosync`
- Latest status: `last-sync.json`
- Execution log: `sync.log` — counts, chat identifiers, titles and error/path details; no message bodies are intentionally logged.
- Database backups: `backups\statev2-before-sync-*.sqlite`
- Previous shortcuts: `shortcut-backups\`
- Disposable text cache: `source-cache\` — contains private conversation text, not a copy of the full transcript.

Backups and caches contain private conversation data. Do not upload them. The cache can be removed while the launcher is stopped; the next launch rebuilds it from Codex. See [recovery and uninstall instructions](docs/RECOVERY.md). Removing the launcher does not remove imported messages or your Codex/T3 history.

## Development

No third-party Python or npm packages are required.

Source code lives in `src/`, Windows installation and packaging scripts in `scripts/`, synthetic tests in `tests/`, and supporting documentation in `docs/`. To install from a source checkout, run `scripts\Install.cmd`. The release ZIP keeps `Install.cmd` at the top for convenience.

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
python -m compileall -q src scripts tests
node --check src/writer.cjs
node --check scripts/check-runtime.cjs
python scripts/build_package.py
```

The database tests use a schema-only T3 fixture and synthetic messages. Installer tests create isolated temporary directories and never launch the dummy T3 executable. The Windows CI workflow runs the tests and builds the public-file-only archive.

The generated `config.json` is local and ignored by Git. After installation:

```powershell
python "$env:USERPROFILE\.t3\tools\codex-autosync\autosync.py" --preview
python "$env:USERPROFILE\.t3\tools\codex-autosync\autosync.py" --apply
```

`--preview` is read-only; `--apply` only writes when T3 is closed. `--launch` syncs and starts T3. Use `--config PATH` for a custom generated config.

## Compatibility reports

When reporting a problem, include OS, T3 version, Node/Python versions and the short error reason. Review logs and remove titles, identifiers and personal paths before sharing. Do not attach conversation databases, transcripts, credentials or backup files. See [CONTRIBUTING.md](docs/CONTRIBUTING.md).

## License and provenance

MIT. The schema fixture and T3-specific event/projection compatibility work reference T3 Code's MIT-licensed implementation. Upstream copyright and license text are retained in [THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md) and [licenses/T3-CODE-MIT.txt](licenses/T3-CODE-MIT.txt).
