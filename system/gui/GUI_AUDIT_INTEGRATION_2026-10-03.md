# BACH/Ocean GUI audit integration — 2026-10-03

This isolated integration branch starts at Gemini's clean `c2055a7c` and ports the verified source corrections from review commit `88171f50`. The newer calendar, agent cockpit, team and MarbleRun UI code from `c2055a7c` remains in place. No production installation or remote state was changed.

## Integrated corrections

- Remove embedded device credentials and query-token persistence from the Astro layout and Memory page. The existing manual device login remains available. An API 401 displays a link to it.
- Reject Compare-Race execution with HTTP 501 until provider calls exist; the chat page states this clearly and renders future results as DOM text.
- Identify the four MCP Cookbooks as static examples and render their content as DOM text. Live MCP discovery is a separate missing contract.
- Treat blueprint materialization as configuration only. It no longer writes an online presence or claims to start a worker.
- Replace unmeasured dashboard and new cockpit success badges with unknown/configured states. The current nine-area frontend structure is preserved.
- Mark the three Core model slots and Telegram/WhatsApp connector activity as not checked until status endpoints report their state. The existing save/toggle controls still explain that they have no connected endpoint.
- Reject unverified tokens if device verification fails offline; the existing localStorage mechanism is still in use and needs a separate session design.

## Verified source contracts

| Surface | Source | Observed contract |
| --- | --- | --- |
| Tasks | `server.py:1648` | `GET /api/tasks` filters status, project/category, assignee, priority and limit. No title/search parameter. |
| Agent blueprints | `api/unified_api.py:340`, `:382`, `:487`, `:525` | BACH DB blueprints; materialize sets a flag, while presence is a separate table. No worker spawn in these handlers. |
| Compare-Race | `api/unified_api.py:1111` | Previous answer, latency, score and winner were calculated without models; integration returns 501. |
| MCP Cookbooks | `api/unified_api.py:1421` | Four static example recipes, now source-labelled. |
| Cluster cockpit | `api/unified_api.py:2567` | Task counts and optional Fackel stand are read; Trithon, Muschelgrund sync and Salt lease had constant success values. They are now unknown without probes. |
| Artifact viewer | `api/unified_api.py:1184`, `:1239`, `:1261`, `:2276` | Two different list endpoints exist. Content/download use a path guard; full guard coverage remains unreviewed. |
| Device auth | `server.py:1303`, `:5155` | Middleware accepts Bearer header or cookie, but no cookie setter was found. Several API prefixes remain available without a token; broader authorization is separate work. |

## Open concept and operation gaps

- `api/unified_api.py:826-877`: MarbleRun's run endpoint writes simulated completed steps and runs. It does not dispatch workers. Legacy stored runs need an explicit provenance plan before changing their schema or status.
- `api/unified_api.py:951-1015`: Governance status declares healthy/enforced and reads locks only from an optional cache. Cache absence cannot prove zero locks.
- `api/unified_api.py:1596` onward: the cognitive-state payload combines BACH DB counts with static claims such as verified hooks, policies and lock state. These are conceptual UI content, not live checks.
- `api/unified_api.py:1971-2135`: Facts, lessons, working memory and sessions use local BACH DB tables. A USMC/Gardener federation contract is not established by these handlers.
- Revoke and rotate the exposed device token after identifying current consumers; removing it from new source/build does not invalidate an existing token in Git history or installed HTML.
- The isolated branch has not been merged, pushed or deployed. The existing browser token persistence and API allowlist need a coordinated auth contract.

## Local verification

- `npm ci --offline --no-audit --no-fund` and `npm run build` completed in this isolated worktree; Astro generated 16 pages.
- `python -m py_compile system/gui/api/unified_api.py` and `git diff --cached --check` passed.
- A byte search over 39 files in this worktree's Astro source and generated dist found zero copies of the previously embedded credential. The credential value was not written to this report.
