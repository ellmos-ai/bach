# inbox Module

Standalone module for self-contained inbox folder scanning, safe intake filtering, and processing gates.

## Exports
- `InboxScanner`: Handles safe folder scanning, excludes temporary/locked files, categorizes incoming items.
- `intake_file`: Atomically moves incoming file to destination directory with collision prevention.
- `scan_inbox`: Functional entrypoint for folder inspection.
