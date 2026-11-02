# Shared GUI route parity (Task #3769)

Bauort: `adapter:ellmos-system-gui`. The GUI module owns the static pages and
`page-reads.v1.json`; BACH owns these same-origin routes and private API authentication.

The Mac readback of GUI commit `1277f0afc6e55b7fb3aaf1242a0c8a92e8772093`
found 32 of 42 responses identical to the manifest. Eight routes returned older
content or redirected to legacy pages; two new page shells required credentials
and had no BACH page binding. An installed, verified dist was insufficient.

Every pinned page now uses the existing `SharedGUIReleaseMiddleware`. With an
explicit release it serves the already hash-verified page payload and rejects a
missing or invalid distribution with 503. Legacy redirects/templates cannot
silently replace those bytes. The library and installation/update page shells
use the same static-page policy as the other public shells. Private API data,
actions, unknown paths, host checks and device credentials retain their gates.

Regression coverage exercises all 42 pages with distinct synthetic release
bytes, all 42 missing-release responses, and private-API/unknown-path rejection.
These checks verify the adapter contract, not functional acceptance of every
backend feature or a deployed browser session.

Ocean's read consumer still declares the older 0.2.28 artifact and no active
runtime. Follow-up Task #3770 covers its shared-contract/pin alignment and old
fallback retirement. This BACH correction does not attest Ocean activation.
Commit, independent review, merge and the Mac runtime readback remain separate.
