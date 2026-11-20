# Recovery and removing auto-sync

## Restore a pre-sync database

1. Fully exit the T3 desktop app and stop any T3 background server or service using the same data directory. Do not replace a live SQLite database.
2. Make a separate recovery copy of the entire T3 `userdata` directory, including any `statev2.sqlite-wal` and `statev2.sqlite-shm` files. Keep it private.
3. Select a `statev2-before-sync-*.sqlite` backup from the auto-sync `backups` directory. Restoring it returns the entire T3 database to that time, including other chats changed since then.
4. Move the current `statev2.sqlite` and any associated `-wal`/`-shm` files into the recovery directory. Copy the selected backup into `userdata` as `statev2.sqlite`. Do not combine the restored database with the old WAL/SHM files.
5. Start T3 from its original executable to inspect the restored state without auto-sync. Keep both recovery copies until you have checked the result.

Default T3 data directory: `%USERPROFILE%\.t3\userdata`.

Default auto-sync backup directory: `%USERPROFILE%\.t3\codex-autosync\backups`.

Custom `T3CODE_HOME` installations use the corresponding `userdata` and `codex-autosync` subdirectories.

## Remove the launcher

1. Start T3 using its original executable whenever you want to bypass auto-sync.
2. Restore any previous shortcuts from `codex-autosync\shortcut-backups`, or create a new shortcut to the original T3 executable.
3. Remove the **T3 Code (Auto Sync)** desktop shortcut if it is no longer needed.
4. The `tools\codex-autosync` program directory can then be removed. Keep `codex-autosync\backups` if you might need a database recovery later.

These steps remove the launcher only. They do not delete Codex conversations or undo messages already appended to T3. Use database recovery only when you explicitly intend to restore an earlier database state.

## Rebuild a transcript cache

With the auto-sync launcher stopped, remove its `codex-autosync\source-cache` directory if needed. The next launch reads Codex again and rebuilds the cache. This does not remove T3 messages or Codex history. Caches contain conversation text and should remain private alongside backups.
