---
name: bach
version: 3.10.0
type: skill
author: BACH Team
created: 2025-12-01
updated: 2026-10-25
anthropic_compatible: true

description: >
  Central management system for BACH. This is the ONLY skill
  that needs to be uploaded to Claude. It knows all local skills,
  performs version checks, and loads newer local versions when needed.
  Activates automatically with every skill usage.
---

# AS AGENT WORKING ON OPEN TASKS (Entry for Claude, Codex, Kimi, Gemini)

> **New since v3.10.0 (2026-10-25).** If your command is "read the SKILL.md and work on open tasks", this section applies first. Everything else in this file is reference and only read when needed.
> Detailed, copyable version: `Desktop\OCEAN\EINWEISUNG-EXTERNE-WORKER.md` (OneDrive from Lukas, not in repo). Lease contract: `docs/architecture/TASKDB-SALT-LEASE-VERTRAG-v1.md`, Clients: `docs/architecture/TASKDB-SALT-LEASE-CLIENTS-v1.md`. Local worker harness (Buddha): `docs/architecture/LOKALER-WORKER-HARNESS.md` (PR #520).

**Workflow in a single sentence:** boot → task selection → **lease, then work** → own worktree → tests → PR → result submission → next task. Without explicit stop instruction from Lukas, you do not stop.

### 1. Booting and mode
- Access to the Mac Studio via the provided SSH access; do not set up your own access credentials. Project under `$BACH_ROOT` (on the Mac Studio `~/services/bach`), Python from its venv. Read `AGENTS.md` and instructions from the part project you are working in.
- **Mode B (Mixed)** is for agents actively collaborating; the normal case. **Mode A (Library)** suffices if you are only working on tasks and not using BACH as a session: the lease method below runs via the lead service and requires no session start. Mode C (Session) only on explicit request.
- Before the first task, read the current plan `Desktop\OCEAN\AKTUELLER-PLAN.md` and `MODUL-ZUORDNUNG.md` (construction sites).

### 2. Find free tasks
- **Native:** `TaskLeaseClient.task_candidates(limit=100, offset=…)` (read all pages, not just the first), then `task_snapshot(task_id)` for the full description. `bach task list` shows the same tasks for view only.
- **Selection rule:**
  1. Only tasks whose dependencies are satisfied, without foreign active lease, and for which your tools suffice.
  2. **Highest priority first** (P0 before P1 before P2). If same priority, first who matches agenda priorities (current 25.10.2026: project planner, agent templates/control, Running & Living, GUI redesign, worker reliability; decisive is `AKTUELLER-PLAN.md`).
  3. **No OLLAMA tasks.** This is the background queue of local workers (Buddha, Ollama Cloud, OpenRouter). Also tasks for `USER`/`HUMAN`/`LUKAS` and foreign reserved tasks stay. `BACH` means jointly editable. Do not invent additional slot obligations.
  4. Review and testing tasks of other authors are explicitly suitable.
  5. If a task attaches to an open user decision or does not fit your abilities: ask or note in task note and take the next one. Never change rules or protective gates just to take a task.

### 3. Take over before you work
```
bach task take <id> --by <agent>@<host>          # Erfolg: "…uebernommen…" + Fence + Frist; Lease-ID/Fence merken
bach task renew <id> --by <user> --fence <int>   # rechtzeitig verlaengern; bei Fence-Wechsel Schreibaktionen stoppen
bach task submit <id> --by <user> --fence <int> --result "<Ergebnistext>"
bach task return <id> --by <user> --fence <int>  # Freigabe, Status zurueck auf pending
bach task block <id> --lease-id --by <user> --fence <int> [--note "<text>"]  # outcome=blocked
```
- Worker ID **`<agent>@<host>`**, own request ID and generation, never share with another worker. Start only after confirmed acceptance.
- Reject `renew` if lease expired or fence changed: **end all write operations for this task.** After confirmed content changes, update stored task version.
- **Do not use:** `bach task claim` (older claim without fence/lease-id) and `~/compute/luna-gui/task_tool.py claim` (sets only `assigned_to`, no lease). Both are not native take over and protect against duplicate work. `task_tool.py note` (append text to description) and `list` are usable as stopgaps until native counterpart exists.
- Signatures bindingly read from `system/hub/_services/task_lease_client.py`, not from this example.

### 4. Working
- **Own worktree per task** from `origin/main`: `git worktree add ~/services/bach-worktrees/<branch> -b <branch> origin/main`. Branch name `<agent>/<task>-<short>-<date>`. Main checkout `~/services/bach` is occupied (foreign, uncommitted changes): do not work, measure, or build there.
- **Construction site:** new domain logic belongs in the appropriate Ocean module repository according to `MODUL-ZUORDNUNG.md`, not in the BACH core.
- Verify result against task acceptance criteria. Execute tests of changed areas and only claim what you can prove. German end-user texts with real umlauts.
- Before commit: Secrets scan, read diff, only commit own files (no collective commit).
- Push branch, **create PR against `main`** and record in task. Commit, push, PR, merge, deploy, and domain acceptance individually reported. A branch is not an delivered state yet.

### 5. Submit
- **Done:** `client.submit_result(task_id, lease_id=…, fence=…, task_version=…, generation="<new-generation>", result="<text>")`. `result` is concrete text with **max 3000 characters** (achieved criteria, changes, PR link, commit SHA, real test results, limits); a pure completion message ("done") is rejected. The submit puts task into `review` and releases lease. Afterwards `task_result_snapshot(task_id)` read and result id/hash checked; chat text alone is no submit.
- **Partial or blockade:** Push WIP branch, then `client.release(task_id, lease_id=…, fence=…, outcome="return" | "blocked", note="<branch, sha, next step>")`. No global `done`, no artificially prolonged lease while waiting for humans. (`complete=false` only in local Buddha tool harness, see Harness documentation, not in SDK.)
- Afterwards **immediately the next task** (step 2). If just now no over-takable: report occupied reasons, short wait, check again. Do not end your assignment.
- Brief report per task: Task ID, work, evidence, commit/remote SHA, PR, read task/result/lease state. Review of own work marked as not independent.

### 6. Limits (always valid)
- **Do not merge**, do not push to `main`, do not deploy, do not restart services, do not change worker config, do not stop foreign jobs/workers, do not start `.SYNC` run. Merge via second review, deploy after acceptance.
- **`bach.db` never directly describe**, no own SQL changes, no copied database as authority. Always native API/sdk.
- **No locks in `OneDrive\.TOPICS` or `.TOPICS\.AI`:** they stop on the Mac the background worker Buddha and any rollout. Locks only for own worktree path.
- Foreign active leases, ongoing work of other agents, and locked paths remain protected. Tokens and access credentials never output or commit.

### 7. Known gaps (as of 25.10.2026)
- **There is still no native short command** `bach task take|renew|submit|return|block`; it is planned (`ANFORDERUNGEN-DETAIL.md`, section "Task system, leases and locks"). The permanent native way today is Python SDK `TaskLeaseClient` (above); `bach_api.task` offers only `lease_acquire`/`lease_read`/`lease_renew`/`lease_release`/`lease_decompose` without candidate list and without `submit_result`.
- `task_tool.py` is outside the repo (`~/compute/luna-gui/`); its `list` reads `bach.db` directly (read-only) and its `claim` is no lease.
- Instruction, plan, and `MODUL-ZUORDNUNG.md` are on Lukas' OneDrive Desktop, not in the repo; an agent running on the Mac reaches them not without copy.
- Origin contract for external results: #2339 is natively accepted, Main-merge and release pending (PR #507). Results until then honestly as submitted or partial.

> **Current status note for the rest of this file:** Everything below this section was last content-wise updated on 2026-03-12 (v3.8.0). Numbers (handlers, tables, hooks, topics), architecture overview v2.6 and task planning (5) have **not been remeasured** since; in case of conflict, code or measurement prevails. The task take over does not anymore run via `bach task claim` but as described above.

---

# VERSION NOTICE

# Check whether a newer version of this skill exists (local or central)

# ALWAYS use the version with the highest version number

# Version check: bach skills version bach

# Welcome to Bach

---

## RULES - GUIDELINES - STANDARDS

---

### ALWAYS (before anything else)

**(1) VERSION CHECK:** If multiple versions of this SKILL.md are available (local, central), compare version numbers and switch to the newest version if necessary, then continue reading there.
```bash
bach skills version bach   # Prueft ob aktuellere Version existiert
```

**(2) OPERATING SYSTEM CHECK:** Detect whether you are running on Windows, Mac, or Linux.
- Windows: No `/dev/null` AND no `NUL:`. Instead, omit output or use `2>&1`. Avoid `&&`, execute commands individually
- For nul files: `python tools/c_nul_cleaner.py --dir <path> --delete`

---

### NEXT: Determine access type / session mode

Choose the mode that fits your situation:

| Mode | When | Startup | Access |
|------|------|---------|--------|
| **A) Library** | Guest, read-only, individual queries, BACH as a tool | No startup | `from bach_api import task; task.list()` |
| **B) Mixed** | Prompted by user to start BACH, active collaboration | API Startup | `session.startup()` + API + `session.shutdown()` |
| **C) Session** | Classic, automatic start, detailed protocol | CLI Startup | `python bach.py --startup --partner=claude` |

- Mode C can switch to B at any time (use API instead of CLI)
- Modes B and C can switch to A at any time (single query without session)
- When in doubt: **Mode B** (recommended for LLM sessions)

---

### IN MODE B and C: Rules for active use

**(1) Reading and Writing -- Using BACH means co-developing BACH:**

Anyone who uses BACH co-develops BACH. Every access is an opportunity to improve the system.

- **(a) Handler First:** Every function belongs as a Handler in `hub/`. A Handler is automatically accessible via CLI **and** API. No separate code for different access paths.
- **(b) Fill gaps:** If Handlers, API modules, Skills, Tools, Workflows, or other components are missing -- create them. Missing Handlers have the highest priority as they are the foundation for all access paths.
- **(c) Custom contributions welcome:** Creating your own Skills, Workflows, Tools, MCPs is explicitly encouraged. When editing existing ones, coordinate with the user.
- **(d) Fix-or-Task:** Problems either lead to an immediate fix (small) or a task in the queue (large). The deciding factor: effort vs. benefit. Then return to the actual task.
- **(e) Self-Healing:** If you find errors in BACH (paths, commands, outdated references, broken imports), fix them immediately and inform the user. BACH repairs itself through its users.
- **(f) Self-Extension:** If you lack a capability, give it to yourself! Use `bach skills create` to scaffold new tools, handlers, agents, experts, or services. After `bach skills reload` they are immediately available. See: `bach help self-extension`

**(2) Execute the startup procedure** (see below). Read mandatory packages and optionally (`-->`) voluntary references. Packages are tagged with mode labels:
- `[C]` -> Read only in Session mode
- `[B]` -> Read only in Mixed mode, skip in Session mode
- `[B/C]` -> Read in both modes
- Without label -> Always read when needed

**(3) Read additional packages when needed** (topic packages further below).

---

### IN MODE A: Rules for guest/tool use

Read additional packages when needed. No startup required, no shutdown expected.

```python
from bach_api import task, memory, tools, steuer
task.list()         # Sofort nutzbar
tools.search("ocr") # Werkzeug finden
```

---

### Document structure (Navigation map)

```
IMMER (vor allem anderen)
├── (1) VERSIONS-CHECK
└── (2) BETRIEBSSYSTEM-CHECK

ZUGRIFFSART klaeren
├── A) Bibliothek    → Gast, lesend, Werkzeug
├── B) Gemischt      → User-gefuehrt, API + Startup (empfohlen)
└── C) Session       → Klassisch, CLI + volles Protokoll

IM MODUS B und C
├── (1) Lesen = Mitentwicklung
│   ├── (a) Handler First
│   ├── (b) Luecken fuellen
│   ├── (c) Eigenes erwuenscht
│   ├── (d) Fix-or-Task
│   └── (e) Self-Healing
├── (2) Startprozedur durchfuehren
│   ├── (1) Start              [B/C]
│   ├── (2) Systemwissen       [B/C]
│   ├── (3) Memory             [B/C]
│   ├── (4) Faehigkeiten       [B/C]
│   ├── (5) Aufgabenplanung    [B/C]
│   └── (6) Protokolle          [C]
└── (3) Zusatzpakete bei Bedarf

IM MODUS A
└── Zusatzpakete bei Bedarf

THEMEN-PAKETE (alle Modi, bei Bedarf)
├── Teamarbeit
├── Problemloesung
├── Coding
├── Wartung
├── Dateiverwaltung
├── Self-Extension              [B/C]
└── Shutdown                    [B/C]

REFERENZ
├── Skill-Architektur
├── Drei Zugriffsmodi (API-Module, Wann-was-nutzen)
├── Gesamtarchitektur-Diagramm
├── Hooks & Injektoren
└── Changelog
```

---

### Skill Architecture v2.0 (NEW)

#### Version Check Principle

**ALWAYS use the newest version** - regardless of whether stored locally or centrally:

```bash
bach skills version <name>    # Prüfe Versionen
bach tools version <name>     # Prüfe Tool-Versionen
```

#### Skill Structure: One Skill = One Folder

Each skill, agent, expert is **fully self-contained** in its own folder:

```
agents/entwickler/
├── SKILL.md              # Definition mit Standard-Header
├── tool_xyz.py           # Spezifische Tools (flat)
├── protocol_abc.md       # Spezifische Protokolle (flat)
└── config.json           # Optional
```

**Rules:**

- < 5 files: Flat (everything in root)
- >= 5 files: Subfolders `tools/`, `protocols/` allowed
- **When in doubt, keep tools duplicated** (general + skill-specific)
- After export it must work without BACH

#### Standard Header (mandatory for all components)

```yaml
---
name: [name]
version: X.Y.Z
type: skill | agent | expert | service | protocol
author: [author]
created: YYYY-MM-DD
updated: YYYY-MM-DD
anthropic_compatible: true
dependencies:
  tools: []
  services: []
  protocols: []
description: >
  [Beschreibung]
---
```

Templates: `system/skills/_templates/TEMPLATE_*.md`

#### Expansion stages

BACH exists in three stages: **USMC** (Memory core), **Ridge** (+ LLM orchestration), **BACH** (complete system). Details: [README.md](README.md#expansion-stages)

#### Three Access modes

BACH provides **two parallel access paths** (CLI + Library-API), which can be combined in **three modes**. Both paths use the same handlers and the same DB.

##### Mode 1: Session mode (CLI -- classic)

Full startup/shutdown logging over the command line. For interactive terminal sessions.

```bash
cd system
python bach.py --startup --partner=claude --mode=silent --watch
# ... arbeiten ...
python bach.py --shutdown "Zusammenfassung"
```

##### Mode 2: Library mode (API -- lightweight)

Direct access to handlers without session overhead. For scripts, quick queries, or LLMs only needing single operations.

```python
from bach_api import task, memory, steuer, partner, tools, injector

task.list()                              # Tasks abfragen
memory.write("Wichtige Notiz")           # Memory schreiben
steuer.status()                          # Steuer-Status
partner.list()                           # Partner auflisten
injector.process("ich bin blockiert")    # Kognitive Hilfe
```

##### Mode 3: Mixed mode (API + Session-Lifecycle)

Full startup/shutdown over the API. **Recommended for LLM sessions** -- combines session management with ergonomic API access.

```python
from bach_api import session, task, memory, injector

# Session starten (= python bach.py --startup --partner=claude --mode=silent)
session.startup(partner="claude", mode="silent")

# Arbeiten mit API
task.list()
memory.write("Notiz")
injector.process("komplexe aufgabe")

# Session beenden (= python bach.py --shutdown "Zusammenfassung")
session.shutdown("Was gemacht wurde. Naechste: Was kommt.")
```

##### Available API modules

```python
from bach_api import (
    # Session-Lifecycle
    session,     # startup(), shutdown(), shutdown_quick(), shutdown_emergency()

    # Kern-Handler
    task,        # add(), list(), done(), assign(), ...
    memory,      # write(), read(), status(), fact(), search(), ...
    backup,      # create(), list(), info()
    status,      # run()

    # Domain-Handler
    steuer,      # status(), beleg(), posten(), export()
    lesson,      # add(), last(), list(), search()
    partner,     # list(), status(), delegate(), info()
    logs,        # status(), tail(), show()
    msg,         # send(), unread(), read()
    email,       # send(), draft(), drafts(), confirm(), setup()

    # Kognitive Injektoren
    injector,    # process(), check_between(), tool_reminder(), status(), toggle()

    # Hook-Framework
    hooks,       # on(), off(), emit(), status(), list_events()

    # Plugin-API (Dynamische Erweiterung)
    plugins,     # register_tool(), register_hook(), register_handler(), load_plugin()

    # Raw-Zugriff (beliebiger Handler)
    app,         # app().execute("handler", "operation", ["args"])
)
```

##### When to use what

| Situation | Recommendation |
|-----------|----------------|
| LLM session (recommended) | Mixed mode: `session.startup()` + API |
| Quick single query | Library mode: directly `task.list()` |
| Human at terminal | Session mode: `python bach.py --startup` |
| Files read, code search | Direct (glob/grep/read) |
| Handler not in bach_api | `app().execute("handler", "op", ["args"])` |

**Architecture:** `core/registry.py` recognizes 113+ handlers automatically (Auto-Discovery). New handlers only need a `.py` file in `hub/` -- no manual mapping. Hot-Reload: `app().reload_registry()`.

#### Component types

| Type | Folder | Characteristics |
|------|--------|-----------------|
| **Agent** | `agents/<name>/` | Orchestrates multiple domains, own folder |
| **Expert** | `agents/_experts/<name>/` | Deep domain knowledge, own folder |
| **Service** | `hub/_services/<name>/` | General services, handler-near |
| **Protocol** | `skills/workflows/` | 1 file = 1 protocol (formerly workflow), category subdirectories allowed |
| **Connector** | `connectors/` | External connections (MCP, APIs) |
| **Tool (general)** | `tools/` | Reusable |
| **Tool (specific)** | In skill folder | Only for this skill |

#### Skill sources & security

| Class | Sources | Approach |
|--------|---------|----------|
| **Gold standard** | Self-written | Best integration |
| **Serious** | anthropics/skills, anthropics/claude-cookbooks | After review 1:1 takeover possible |
| **Unsure** | Other GitHub repos | ONLY rewrite |
| **Blacklist** | `data/skill_blacklist.json` | FORBIDDEN |

---

## (1) STARTEP now BACH [B/C]: (1) → (2) → (3) → (4) → (5) → (6)

*Only in Mode B (Mixed) and C (Session). Mode A skips this section.*

---

### (1) STARTe now BACH [B/C]

**Mode C (Session/CLI):**

```bash
cd system
python bach.py --startup --partner=claude --mode=silent --watch
```

**Mode B (Mixed/API -- recommended):**

```python
from bach_api import session
session.startup(partner="claude", mode="silent")
```

**For Gemini:**

```python
# Modus B (API)
session.startup(partner="gemini", mode="silent")
# Modus C (CLI)
# python bach.py --startup --partner=gemini --mode=silent --watch
```

---

### (2) SYSTEM: Load your system knowledge [B/C]

```bash
bach help cli
bach help bach_info
bach help features
bach help naming
bach help guidelines
bach help architecture
# --> bach help injectors
```

Or API: `help.run("cli")`, `help.run("features")`, etc.

#### Handler discovery & search

BACH has 113+ handlers in `hub/`. **Each handler is a CLI command.** To find handlers, tools, skills, or help topics:

```bash
# Fuzzy-Suche in Help-Themen (187+ Themen, Fuzzy-Match!)
bach help <suchbegriff>           # z.B. bach help web → schlaegt web_scrape, web_parse vor

# Handler auflisten
bach help list                    # Alle 187+ Help-Themen
bach help cli                     # CLI-Befehlsuebersicht

# Tools durchsuchen
bach tools list                   # Alle Python-Tools
bach tools search <keyword>       # Volltextsuche in Tool-Namen und -Inhalten

# Skills & Agents durchsuchen
bach skills list                  # Alle Skills in der DB
bach skills search <keyword>      # Skills nach Keyword filtern
bach agent list                   # Alle Agenten

# Beliebigen Handler direkt aufrufen
bach <handler-name> <operation>   # z.B. bach web-scrape get <url>
```

**Important:** If you don’t know which handler exists, use `bach help <search-term>` -- fuzzy search suggests matching topics, even with imprecise terms.

#### Files to examine

- `system/CHANGELOG.md` - Version history
- `system/ROADMAP.md` - Planned features & architecture overview

#### Root documents (generated from DB, updated at `bach --shutdown`)

- `AGENTS.md` - All boss agents and experts with status and paths
- `PARTNERS.md` - LLM partners and delegation
- `SKILLS.md` - Skill index
- `WORKFLOWS.md` - Protocol index
- `CHAINS.md` - Toolchains
- `USECASES.md` - Application cases
- `USER.md` - User profile
- `MEMORY.md` - Memory snapshot
- `BACH_HELP_REFERENCE.md` - Complete help reference

#### Core principles

- **BACH as organism:** Connectors/Bridge are the **senses & voice** (perception + communication with outer world). LLMs are the **mind** (thinking, understanding, deciding). The database and text files are the **memory**. The GUI is the **face**. API, CLI, tools, agents, skills, and workflows are the **hands** (action potential).
- **Handler First:** Every function as a Handler in `hub/` -- automatically accessible via CLI **and** API
- **API preferred:** LLMs use `bach_api` instead of CLI. Humans use CLI or GUI.
- **System-wide:** Reusable for any user
- **dist_type:** 0=USER (personal), 1=TEMPLATE (customizable), 2=CORE (system)
- **Idempotent:** Imports repeatable without duplicates
- **Version check:** Always use newest version

> **CORE PRINCIPLE:** BACH is NOT primarily developed for a single user, but as a reusable system.

#### Working principles

Six ground rules for all BACH partners (LLMs, agents, experts):

1. **Own resources first** — Check memory, wiki, tools, and DB before asking user
2. **Results before process** — What counts is the result, not the method
3. **Do instead of announce** — Do not explain what you will do, just do it
4. **Have opinions** — You may disagree and make own suggestions
5. **Keep compact** — System prompts under 1000 tokens, keep injections lean
6. **Secure knowledge** — Write insights to memory before context is lost

**Partner-specific instructions:**
- **Claude:** Read `CLAUDE.md` in root directory (knowledge capture rule, integration)
- **Gemini:** Read `GEMINI.md` in root directory (knowledge capture rule, integration)
- **Ollama:** Read `OLLAMA.md` in root directory (knowledge capture rule, integration)

These files contain detailed knowledge capture rules and partner-specific settings.

#### Database schema (138 tables in bach.db)

| # | Area | Important tables |
|---|---------|---------------------|
| 1 | System | `system_identity`, `system_config`, `instance_identity` |
| 2 | Tasks | `tasks` |
| 3 | Memory | `memory_working`, `memory_facts`, `memory_lessons`, `memory_sessions` |
| 4 | Tools | `tools` (550+ entries) |
| 5 | Skills | `skills` (1870+ entries) |
| 6 | Agents | `bach_agents`, `bach_experts`, `agent_synergies` |
| 7 | Files | `files_truth`, `files_trash`, `dist_files` |
| 8 | Automation | `automation_triggers`, `automation_routines`, `automation_injectors` |
| 9 | Monitoring | `monitor_tokens`, `monitor_success`, `monitor_processes`, `monitor_pricing` |
| 10 | Connections | `connections`, `connector_messages`, `partner_presence` |
| 11 | Languages | `languages_config`, `languages_translations` |
| 12 | Distribution | `distribution_manifest`, `dist_type_defaults`, `releases`, `snapshots` |
| 13 | Wiki | `wiki` (87 articles) |
| 14 | Usecases | `usecases`, `toolchains` |

Complete schema: `system/data/schema/schema.sql` (138 tables + Views + FTS)

---

### BACH v2.6 overall architecture

```text
  +=====================================================================+
  |                             USER-INTERFACES                         |
  |  +-----------+  +-----------+  +-----------+  +-------------------+ |
  |  |    CLI    |  | Lib-API   |  |    GUI    |  |  MCP v2.2 (IDE)   | |
  |  |  bach.py  |  | bach_api  |  | server.py |  |  mcp_server.py   | |
  |  +-----+-----+  +-----+-----+  +-----+-----+  +--------+--------+ |
  +========|==============|==============|==================|===========+
           |              |              |                  |
  +========v==============v==============v==================v===========+
  |                    CORE LAYER (core/*.py)                           |
  |  app.py → registry.py → Auto-Discovery von 75+ Handlern            |
  |  base.py (BaseHandler) | db.py (Schema-First) | hooks.py (Events)  |
  +=========|==============|=======================================+====+
            |              |                                       |
  +==========v==============v=======================================v===+
  |                          HUB LAYER (hub/*.py)                       |
  |  System: startup, shutdown, status, backup, tokens, inject, hooks   |
  |  Domain: steuer, abo, haushalt, gesundheit, contact, calendar, email|
  |  Data: task, memory, db, session, logs, wiki, docs, inbox           |
  |  Multi-AI: agents, partner, daemon, ollama, ati                     |
  |  Extension: skills (create/reload), hooks (status/events/log/test)  |
  +====|======================|======================|=================+
       |                      |                      |
  +----v------------------+   |   +------------------v-----------------+
  |   AGENTS LAYER        |   |   |   CONNECTORS & PARTNERS           |
  |                       |   |   |                                    |
  | agents/ (Ordner)      |   |   | connectors/ (MCP, APIs)           |
  | agents/_experts/      |   |   | partners/ (Multi-LLM-Konfig)      |
  +-----------------------+   |   +------------------------------------+
                              |
  +---------------------------v----------------------------------------+
  |   SKILLS & TOOLS LAYER                     |    DATA LAYER         |
  |                                            |                       |
  | skills/workflows/ (ehem. _workflows)      | bach.db (Unified)     |
  | skills/_templates/ (Standard-Templates)    | Dateisystem            |
  | hub/_services/ (Ordner)                    | inbox/outbox/          |
  | tools/*.py | c_*.py | injectors.py         |                       |
  +--------------------------------------------+-----------------------+
              |
  +-----------v-----------+
  | SELF-EXTENSION LAYER  |
  |                       |
  | skills create (6 Typ) |
  | skills reload (Hot)   |
  | hooks.on/emit (14 Ev) |
  | Plugin-API (geplant)  |
  +-----------------------+
```

---

### (3) MEMORY: Load your episodic context [B/C]

```bash
bach help memory
bach help lessons
bach help consolidation
```

#### The cognitive memory model (5 types)

| Type | Equivalent | Function | Command |
|------|------------|----------|--------|
| **Working** | Short-term | Current session | `bach mem write` |
| **Episodic** | Diary | Completed sessions | `bach --memory session` |
| **Semantic** | World knowledge | Facts, wiki, help | `bach --memory fact "key:value"` |
| **Procedural** | Know-how | Tools, skills, workflows | `bach help tools` |
| **Associative** | Connection | Consolidation, trigger | `bach consolidate` |

---

### (4) CAPABILITIES: Load knowledge about your capabilities [B/C]

```bash
bach help skills
bach help tools
```

**Hierarchy:**

- **Agents:** Orchestrate multiple areas, own folder
- **Experts:** Deep domain knowledge, own folder
- **Services:** General services, handler-near

**Important directories:**

- `system/agents/` - Agents (each own folder)
- `system/agents/_experts/` - Experts (each own folder)
- `system/hub/_services/` - Services (each own folder)
- `system/skills/workflows/` - Protocols (single files, formerly _workflows)
- `system/skills/_templates/` - Standard templates
- `system/connectors/` - External connections (MCP, APIs)
- `system/partners/` - Multi-LLM configurations

---

### (5) TASK PLANNING [B/C]

#### (5.1) Detect user wishes

- Detect concrete user wishes mentioned in prompt as tasks
- Define tasks and plan your approach
- If no concrete wishes present, go to 5.2

#### (5.2) Load task context

```python
# API (bevorzugt)
from bach_api import task
task.list()
```

```bash
# CLI
bach help tasks
bach task list
```

- Independently select tasks. **Since 2026-10-25: Take over and submit run via Lease, see section "AS AGENT WORKING ON OPEN TASKS" at top.** `bach task claim` is outdated (claim without fence/lease-id).

---

### (6) PROCEDURAL KNOWLEDGE & PROTOCOLS [C]

*In Mode B optional -- protocols are documentation, no code.*

```bash
bach help protocol
bach help between-tasks
bach help practices
```

**Path:** `system/skills/workflows/`

---

## TOPIC PACKAGES (when needed read -- all modes)

### TOPIC: Teamwork (PACKAGE: TEAMWORK)

*When to read:* You work with partners in the system.

```bash
bach help partners
bach help multi_llm
bach help delegate
```

**Chat system:**

```python
# API
from bach_api import msg, partner
msg.send("gemini", "Bitte recherchiere...")
msg.unread()
partner.delegate("Recherche", "--to=gemini")
```

```bash
# CLI
bach msg send claude "Text"
bach msg unread
```

**Lock system:**

```bash
bach llm lock <datei>           # Lock VOR Schreiben
bach llm unlock [datei]         # Lock freigeben
bach llm status                 # Wer hat welche Locks?
```

---

### TOPIC: Problem solving (PACKAGE: PROBLEM SOLVING)

*When to read:* You encounter problems or blockages.

```bash
bach help operatoren
bach help planning
bach help problemloesung
bach help strategien
```

---

### TOPIC: Coding tasks (PACKAGE: CODING)

*When to read:* You edit code or fix bugs.

```bash
bach help ati
bach help coding
bach help bugfix
```

---

### TOPIC: Maintenance (PACKAGE: MAINTENANCE)

*When to read:* You edit maintenance tasks.

```bash
bach help maintain
bach help wartung
bach help recurring
bach daemon status
```

---

### TOPIC: File management (PACKAGE: FILE MANAGEMENT)

*When to read:* You perform file operations.

```bash
bach help trash
bach help migrate
bach help distribution
```

---

### TOPIC: Web reading (PACKAGE: WEB)

*When to read:* You need to retrieve web pages, extract contents, or perform web analysis.

```bash
bach help web_parse
bach help web_scrape
```

**Two handlers for different purposes:**

| Handler | Command | Purpose | Technique |
|---------|--------|---------|-----------|
| `web_parse` | `bach web-parse url/clean <url>` | **Content extraction** (main content as Markdown) | trafilatura/html2text |
| `web_scrape` | `bach web-scrape get/links/forms/headers <url>` | **Structure analysis** (links, forms, headers) | requests + Regex |

**Recommendation:** For text contents use `web-parse clean <url>` (removes nav/header/footer). For raw data or link lists use `web-scrape`. Both use HTTP requests -- JS-rendered pages deliver only server-side HTML.

**Skill:** `skills/workflows/webseiten-lesen.md` -- Detailed procedure with decision tree.

---

### TOPIC: Self-extension (PACKAGE: SELF-EXTENSION) [B/C]

*When to read:* You lack a capability or want to extend BACH.

```bash
bach help self-extension
bach help hooks
bach help skills
```

**Create new capabilities (5 types):**

```bash
bach skills create voice-processor --type tool       # Neues Tool scaffolden
bach skills create email-agent --type agent           # Neuen Agent scaffolden
bach skills create tax-expert --type expert            # Neuen Experten scaffolden
bach skills create api-gateway --type handler          # Neuen CLI-Befehl scaffolden
bach skills create data-sync --type service            # Neuen Service scaffolden
```

**After creation: Hot-Reload (no restart!)**

```bash
bach skills reload
```

**Hook-framework (14 events):**

```python
from core.hooks import hooks

# Eigene Logik an System-Events haengen
hooks.on('after_task_create', meine_funktion, name='mein_plugin')
hooks.on('after_startup', startup_check, name='mein_plugin')

# Events anzeigen
# bach hooks events
```

**Events:** `before_startup`, `after_startup`, `before_shutdown`, `after_shutdown`, `before_command`, `after_command`, `after_task_create`, `after_task_done`, `after_task_delete`, `after_memory_write`, `after_lesson_add`, `after_skill_create`, `after_skill_reload`, `after_email_send`

> Hooks are the **technical framework**. Injectors are the **cognitive subsystem**. They work independently of each other.

---

### TOPIC: Shutdown (PACKAGE: SHUTDOWN) [B/C]

*When to read:* The session is ending. Only in Mode B and C relevant.

**Mode B (API -- recommended):**
```python
from bach_api import plugins

# Tool registrieren (sofort nutzbar)
plugins.register_tool("mein_tool", meine_funktion, "Beschreibung")

# Hook registrieren (Event abonnieren)
plugins.register_hook("after_task_done", callback, plugin="mein-plugin")

# Handler registrieren (neuer CLI-Befehl!)
plugins.register_handler("mein_cmd", MeinHandler)

# Plugin aus Manifest laden
plugins.load_plugin("plugins/mein-plugin/plugin.json")
```

`SESSION_ID` is the own ID from the startup report. For multiple open
 sessions always specify ID and partner; an unclear selection is rejected.

**Mode C (CLI):**
```bash
# CLI: Plugin-Verwaltung
bach plugins list          # Geladene Plugins
bach plugins create name   # Plugin scaffolden
bach plugins load pfad     # Plugin laden
bach plugins unload name   # Plugin entladen
```

---

## HOOKS & INJECTORS

### Hook-framework (technical event-system)

Hooks allow to attach own logic to 14 lifecycle events -- without changing existing code.

```python
from bach_api import session, memory
memory.session("THEMA: Was gemacht. NAECHSTE: Was kommt.", session_id="SESSION_ID", partner="claude")
session.shutdown("Zusammenfassung", partner="claude", session_id="SESSION_ID")
# Oder schnell:
session.shutdown_quick("Kurze Notiz", partner="claude", session_id="SESSION_ID")
```

**Events:** `before_startup`, `after_startup`, `before_shutdown`, `after_shutdown`, `before_command`, `after_command`, `after_task_create`, `after_task_done`, `after_task_delete`, `after_memory_write`, `after_lesson_add`, `after_skill_create`, `after_skill_reload`, `after_email_send`

> Hooks are the **technical framework**. Injectors are the **cognitive subsystem**. They work independently of each other.

---

### Injectors (cognitive orchestration)

The 6 injectors simulate **thinking and associations** as **Central Executive**. Available over CLI and API.

| Injector | Subfunctions | API-capable |
|----------|-------------|-------------|
|----------|-------------|-------------|
| **strategy_injector** | Metacognition, decision support, error analysis | Yes |
| **context_injector** | Tool recommendation, memory retrieval, requirement analysis | Partially* |
| **between_injector** | Quality control, task transition, result validation | Yes |
| **time_injector** | Time feeling (Timebeat), news check | Yes |
| **tool_injector** | Tool reminder, duplicate warning | Yes |
| **task_assigner** | Auto-assignment, task decomposition | Yes |

***context_injector contains CLI commands as hints. In API mode filterable.*

**CLI:**
```bash
bach help shutdown
bach --memory session "THEMA: Was gemacht. NAECHSTE: Was kommt."
bach --shutdown
```

**API:**
```python
from core.hooks import hooks

# Listener registrieren
hooks.on('after_task_done', auto_backup, name='backup_plugin')
hooks.on('after_startup', health_check, priority=10, name='health')

# CLI
# bach hooks status    → Zeigt alle Hooks
# bach hooks events    → Listet alle 14 Events
# bach hooks log       → Letzte Ausfuehrungen
```

```bash
bach --inject status            # Status aller Injektoren
bach --inject toggle <name>     # An/Aus schalten
```

```python
from bach_api import injector

injector.process("text")              # Alle Injektoren auf Text anwenden
injector.check_between("task done")   # Quality-Check nach Task-Abschluss
injector.tool_reminder()              # Verfuegbare Tools (einmalig)
injector.assign_task()                # Naechste Aufgabe automatisch zuweisen
injector.time_check()                 # Uhrzeit + Nachrichten
injector.status()                     # Status aller Injektoren
injector.toggle("strategy_injector")  # Einzeln an/aus
injector.set_mode("api")              # CLI-Hinweise aus Kontext filtern
```

---

## CHANGELOG

### v3.10.0 (2026-10-25)

- **Agent entry**: New section at top "AS AGENT WORKING ON OPEN TASKS" (booting, task selection, lease take over, worktree, tests, PR, result submission, next task; limits; known gaps). Goal: an agent (Claude, Codex, Kimi, Gemini) boots alone with this file.
- **Outdated marked:** `bach task claim` and (5.2) "assign yourself"; numbers and architecture overview below the new section are from 2026-03-12 and not remeasured.
- No contents deleted. Modes A, B, C unchanged.

### v3.8.0 (2026-03-12)

- **Handler discovery:** New section in (2) -- `bach help <search-term>` as primary discovery mechanism for 109+ handlers documented
- **Search reference:** `bach help list`, `bach tools search`, `bach skills search` as search entry points
- **Topic package WEB:** New package with reference to `web_parse` and `web_scrape` handler
- **Skill `webseiten-lesen`:** New workflow skill with decision tree for web content extraction
- **Documentation:** Handlers now findable in SKILL.md instead of only via CLI

### v3.2.0-butternut (2026-02-28)

- **Agent CLI:** `AgentLauncherHandler` -- `bach agent start/stop/list` for direct agent control
- **Prompt system:** `PromptHandler` -- `bach prompt list/add/edit/show/board-create` for central prompt management
- **SharedMemory extensions:** `current-task`, `generate-context`, `conflict-resolution`, `decay`, `changes-since`
- **USMC Bridge:** United Shared Memory Client (`hub/_services/usmc_bridge.py`)
- **llmauto chains:** Claude prompts as Chain steps + `bach://`-URL resolution
- **Scheduler:** `job_type='chain'` + rename `daemon_jobs` → `scheduler_jobs`
- **New API modules:** `agent`, `prompt` in `bach_api`
- **Portings:** SharedMemoryHandler, ApiProberHandler, N8nManagerHandler, UserSyncHandler, Stigmergy-service
- **Tables:** 4 new DB tables: `prompt_templates`, `prompt_versions`, `prompt_boards`, `prompt_board_items`
- **109+ handlers** (previously: 75+)

### v2.6.0 (2026-02-13)

- **Directory restructuring:** Clear separation of Agents, Skills, Connectors and Partners
  - `skills/_agents/` → `agents/` (Top-level under system/)
  - `skills/_experts/` → `agents/_experts/` (Experts belong to Agents)
  - `skills/_workflows/` → `skills/workflows/` (Workflows now called Protocols)
  - `skills/_connectors/` → `connectors/` (Top-level under system/)
  - `skills/_partners/` → `partners/` (Top-level under system/)
- **PathHealer:** Automatic path correction in all affected files
- **Component type `protocol`:** Replaces `workflow` in type hierarchy
- **Component type `connector`:** New for external connections (MCP, APIs)
- **Architecture diagram:** AGENTS LAYER and CONNECTORS & PARTNERS as own sections
- **SKILL.md v2.6:** All references, tables and diagrams adjusted to new structure

### v2.5.0 (2026-02-13)

- **Self-Extension system:** AI partners can give themselves new capabilities
  - `bach skills create <name> --type <typ>` (5 types: tool, agent, expert, handler, service)
  - `bach skills reload` (Hot-Reload: Registry + Tools + Skills-DB)
  - Self-Extension Loop: DETECT → CREATE → REGISTER → USE → REFLECT
- **Hook-framework:** Extensible event system with 14 lifecycle events
  - `core/hooks.py` - HookRegistry singleton, priorities, event log
  - `hub/hooks.py` - CLI: `bach hooks status/events/log/test`
  - Integration in: Startup, Shutdown, Task, Memory, Lesson, Skills, App
  - Hooks != Injectors: technical framework vs. cognitive subsystem
- **Email handler:** Gmail API with draft safety (send, draft, confirm, cancel)
- **Registry Hot-Reload:** `app().reload_registry()` without restart
- **Rule (f) Self-Extension:** "If you lack a capability, give it to yourself!"
- **Documentation:** hooks.txt, self-extension.txt, cli.txt, skills.txt, ROADMAP.md

### v2.4.0 (2026-02-08)

- **MCP Server v2.2:** 23 tools, 8 resources, 3 prompts - all three MCP primitives
- **Email adapter:** SMTP_SSL in notify.py (ported from BachForelle)
- **BachFliege + BachForelle:** Analyzes and archives (`docs/_archive/con5_BACHFLIEGE_BACHFORELLE_ARCHIVE.md`)

### v2.3.0 (2026-02-06)

- **Rulebook completely re-worked:** IMMER → Determine access type → Mode-specific
- **Three modes:** A (Library), B (Mixed), C (Session) with [B], [C], [B/C] tags
- **Co-development principle:** "Using BACH means co-developing BACH" as core rule
- **bach_api.py extended:** session, partner, logs, msg, tools, help, injector
- **14 API modules:** Complete programmatic access to all handlers
- **Injectors over API:** All 6 injectors usable via Library + CLI filters
- **Session-Lifecycle via API:** `session.startup()` / `session.shutdown()`
- **Architecture diagram updated** (Core Layer + bach_api)
- **All sections tagged with mode** [B], [C] or [B/C]

### v2.2.0 (2026-02-06)

- Two access paths (CLI + Library-API) documented
- bach_api.py Basismodule: task, memory, backup, steuer, lesson, status

### v2.1.0 (2026-02-04)

- Skill-Architecture v2.0 integrated
- Version-Check-Principle introduced
- Standard header
  completed.

### v2.0.2 (2026-01-01)

- Initial version