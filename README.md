# t3code-sync

Refresh imported Codex chats before launching T3 Code.

[한국어 안내](README.ko.md) · [Windows download](https://github.com/IEDGEI/t3code-sync/releases/tag/v1.0.1-windows-preview) · [Recovery](docs/RECOVERY.md) · [Roadmap](github.md)

**Windows preview.** Tested with T3 Code **0.1.9**, database migration **81** and a specific schema fingerprint. Other schemas are rejected before writing. Linux and macOS are not supported yet. This is an independent community tool, unaffiliated with T3 Tools or OpenAI.

## The problem

You import a Codex conversation into T3, then continue it in the Codex desktop app. T3's imported copy can remain at its earlier state. This tool compares the local source history with the existing imported chat and appends newly settled user and assistant messages before T3 starts.

It operates locally. No model calls, API keys, cloud uploads or AI tokens are used by the sync operation.

## Install on Windows

Requirements:

- Windows desktop session.
- T3 Code 0.1.9 with a compatible migration-81 database, and the desired Codex chats already imported into T3.
- Local Codex history at `CODEX_HOME` or `%USERPROFILE%\.codex`.
- Python 3.9+ with `pythonw.exe`, and Node.js 22.13+ with modern SQLite/FTS5. Local validation used Python 3.9 and Node.js 24.15.

1. Download **T3-Codex-AutoSync-Windows.zip** from the [Windows preview release](https://github.com/IEDGEI/t3code-sync/releases/tag/v1.0.1-windows-preview).
2. Extract the archive, then run **Install.cmd**. Review the source before running it. Windows may display a warning because these scripts are unsigned.
3. The installer finds the local executables and checks the database schema. It does not download dependencies or modify the T3 database.
4. Fully close T3, then launch **T3 Code (Auto Sync)** from the desktop.

Existing desktop or app-folder shortcuts that directly target T3 without extra arguments may also be updated; their originals are backed up. Running the T3 executable directly bypasses sync.

If T3 is already running, the shortcut opens the existing app without changing its database. Close it completely and use the shortcut again to sync. Background T3 servers must also be stopped.

For custom paths, run from the extracted directory:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Preview
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -T3Exe "D:\Apps\T3 Code (Beta).exe"
```

Optional installer arguments: `-PythonExe`, `-NodeExe`, `-T3Home`, `-CodexHome`, `-InstallDir`, `-ShortcutDir`, `-SkipExistingShortcuts` and `-Preview`. `T3CODE_HOME` and `CODEX_HOME` take precedence over their default user directories.

## How it works

1. Check whether the T3 app or its recorded server is running.
2. Open Codex's index and JSONL transcripts read-only.
3. Align the existing imported messages with the source. Defer unfinished turns and refuse changed or divergent history.
4. Prepare canonical T3 events and matching projections in a transaction using Node's SQLite runtime.
5. Create and integrity-check a pre-update SQLite backup. Recheck the source and running-app guard before committing.
6. Commit the events, message/timeline projections, positions, search updates and checkpoint together, then launch T3.

The tool does not patch T3's installed application files. It **does write T3's internal local database**, which is why this release is a preview with a strict schema gate. If an error occurs, the transaction is rolled back where possible, a status report is written, and the launcher still opens T3. Inspect `last-sync.json` to confirm whether sync succeeded.

## Scope and limitations

| Supported in this preview | Deferred or unsupported |
| --- | --- |
| Existing imported Codex chats | Initial import of new projects/chats |
| Settled or interrupted turns | Currently active turns |
| New visible user/assistant text | Images, attachments and tool activity |
| Unchanged imported baseline | Conversations continued inside T3 or edited/divergent histories |
| Plain local JSONL transcripts | Missing/compressed source transcripts |
| Up to 500 new messages per launch | Cross-device or bidirectional sync |

The tool does not restore earlier history omitted by T3's original import. After reaching the batch limit, further messages can be added on a later launch. Some generated setup context is filtered from new additions. Existing records are preserved.

## Status, backups and removal

Defaults:

- Program: `%USERPROFILE%\.t3\tools\codex-autosync`
- Status and backups: `%USERPROFILE%\.t3\codex-autosync`
- Latest status: `last-sync.json`
- Execution log: `sync.log` — counts, chat identifiers, titles and error/path details; no message bodies are intentionally logged.
- Database backups: `backups\statev2-before-sync-*.sqlite`
- Previous shortcuts: `shortcut-backups\`

Backups contain your T3 conversation database and should remain private. See [recovery and uninstall instructions](docs/RECOVERY.md). Removing the launcher does not remove imported messages or your Codex/T3 history.

## Development

No third-party Python or npm packages are required.

```powershell
python -m unittest discover -s . -p "test_*.py" -v
python -m py_compile autosync.py build_package.py
node --check writer.cjs
node --check check-runtime.cjs
python build_package.py
```

The database tests use a schema-only T3 fixture and synthetic messages. Installer tests create isolated temporary directories and never launch the dummy T3 executable. The Windows CI workflow runs the tests and builds the public-file-only archive.

The generated `config.json` is local and ignored by Git. After installation:

```powershell
python "$env:USERPROFILE\.t3\tools\codex-autosync\autosync.py" --preview
python "$env:USERPROFILE\.t3\tools\codex-autosync\autosync.py" --apply
```

`--preview` is read-only; `--apply` only writes when T3 is closed. `--launch` syncs and starts T3. Use `--config PATH` for a custom generated config.

## Compatibility reports

When reporting a problem, include OS, T3 version, Node/Python versions and the short error reason. Review logs and remove titles, identifiers and personal paths before sharing. Do not attach conversation databases, transcripts, credentials or backup files. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License and provenance

MIT. The schema fixture and T3-specific event/projection compatibility work reference T3 Code's MIT-licensed implementation. Upstream copyright and license text are retained in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [licenses/T3-CODE-MIT.txt](licenses/T3-CODE-MIT.txt).
