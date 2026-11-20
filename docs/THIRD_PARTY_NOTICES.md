# Third-party notices

## T3 Code

Source: https://github.com/pingdotgg/t3code

Copyright (c) 2026 T3 Tools Inc. Licensed under the MIT License.

The schema-only fixture (`tests/schema_fixture.sql`) comes from the T3 Code 0.1.9 database schema. The imported-message event shapes, projection updates, history-alignment compatibility work and transcript deduplication behavior in `src/autosync.py` and `src/writer.cjs` were developed with reference to the corresponding T3 implementation. They are treated as containing adaptations of that work for attribution purposes.

The complete upstream permission notice is included in [licenses/T3-CODE-MIT.txt](../licenses/T3-CODE-MIT.txt). It must accompany redistributed copies or substantial portions of the referenced implementation, including release packages.

No T3 application binaries, real conversations, credentials or database contents are distributed by this project.

Python and Node.js are separately installed runtimes; their binaries are not included in the release archive.
