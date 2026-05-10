---
name: bach
version: 3.9.1
type: skill
author: BACH Team
created: 2025-12-01
updated: 2026-03-12
anthropic_compatible: true

description: >
  Central management system for BACH. This is the ONLY skill
  that needs to be uploaded to Claude. It knows all local skills,
  performs version checks, and loads newer local versions when needed.
  Activates automatically with every skill usage.
---

# VERSION NOTICE

# Check if a newer version of this skill exists (local or central)

# ALWAYS use the version with the highest version number

# Version check: bach skills version bach

# Welcome to Bach

---

## RULES - GUIDELINES - STANDARDS

---

### ALWAYS (before anything else)

**(1) VERSION CHECK:** When different versions of this SKILL.md are available (local, central), compare version numbers and switch to the newest version if needed, then continue reading there.
```bash
bach skills version bach   # Check if a newer version exists
```

**(2) OPERATING SYSTEM CHECK:** Detect whether you are working on Windows, Mac, or Linux.
- Windows: No `/dev/null` AND no `NUL:`. Instead, omit output or use `2>&1`. Avoid `&&`, execute commands individually
- For nul files: `python tools/c_nul_cleaner.py --dir <path> --delete`

---

### THEN: Clarify access type / session mode

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

### IN MODE B and C: Rules for active usage

**(1) Reading and Writing -- BACH usage is co-development:**

Whoever uses BACH co-develops BACH. Every access is an opportunity to improve the system.

- **(a) Handler First:** Every function belongs as a handler in `hub/`. A handler is automatically accessible via CLI **and** API. No separate code for different access paths.
- **(b) Fill gaps:** If handlers, API modules, skills, tools, workflows, or other components are missing -- create them. Missing handlers have the highest priority; they are the foundation for all access paths.
- **(c) Own creations welcome:** Creating your own skills, workflows, tools, MCPs is explicitly encouraged. When modifying existing ones, coordinate with the user.
- **(d) Fix-or-Task:** Problems lead either to an immediate fix (small) or a task in the queue (large). Decisive factor: effort vs. benefit. Then return to the actual task.
- **(e) Self-Healing:** If you find errors in BACH (paths, commands, outdated references, broken imports), fix them immediately and inform the user. BACH repairs itself through its users.
- **(f) Self-Extension:** If you lack a capability, give it to yourself! Use `bach skills create` to scaffold new tools, handlers, agents, experts, or services. After `bach skills reload` they are immediately available. See: `bach help self-extension`

**(2) Execute the startup procedure** (see below). Read mandatory packages and optionally (`-->`) voluntary references. Packages are tagged with mode labels:
- `[C]` -> Read only in Session mode
- `[B]` -> Read only in Mixed mode, skip in Session mode
- `[B/C]` -> Read in both modes
- Without label -> Always read when needed

**(3) Read additional packages when needed** (topic packages further below).

---

### IN MODE A: Rules for guest/tool usage

Read additional packages when needed. No startup required, no shutdown expected.

```python
from bach_api import task, memory, tools, steuer
task.list()         # Immediately usable
tools.search("ocr") # Find a tool
```

---

### Document Structure (Navigation Map)

```
ALWAYS (before anything else)
+-- (1) VERSION CHECK
+-- (2) OPERATING SYSTEM CHECK

CLARIFY ACCESS TYPE
+-- A) Library       -> Guest, read-only, tool
+-- B) Mixed         -> User-guided, API + Startup (recommended)
+-- C) Session       -> Classic, CLI + full protocol

IN MODE B and C
+-- (1) Reading = Co-development
|   +-- (a) Handler First
|   +-- (b) Fill gaps
|   +-- (c) Own creations welcome
|   +-- (d) Fix-or-Task
|   +-- (e) Self-Healing
+-- (2) Execute startup procedure
|   +-- (1) Start              [B/C]
|   +-- (2) System knowledge   [B/C]
|   +-- (3) Memory             [B/C]
|   +-- (4) Capabilities       [B/C]
|   +-- (5) Task planning      [B/C]
|   +-- (6) Protocols           [C]
+-- (3) Additional packages when needed

IN MODE A
+-- Additional packages when needed

TOPIC PACKAGES (all modes, when needed)
+-- Teamwork
+-- Problem solving
+-- Coding
+-- Maintenance
+-- File management
+-- Self-Extension              [B/C]
+-- Shutdown                    [B/C]

REFERENCE
+-- Skill Architecture
+-- Three Access Modes (API modules, when-to-use-what)
+-- Overall Architecture Diagram
+-- Hooks & Injektoren
+-- Changelog
```

---

### Skill Architecture v2.0 (NEW)

#### Version Check Principle

**ALWAYS use the newest version** - regardless of whether stored locally or centrally:

```bash
bach skills version <name>    # Check versions
bach tools version <name>     # Check tool versions
```

#### Skill Structure: One Skill = One Folder

Each skill, agent, expert is **fully self-contained** in its own folder:

```
agents/entwickler/
+-- SKILL.md              # Definition with standard header
+-- tool_xyz.py           # Specific tools (flat)
+-- protocol_abc.md       # Specific protocols (flat)
+-- config.json           # Optional
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
  [Description]
---
```

**Templates:** `system/skills/_templates/TEMPLATE_*.md`

#### Expansion Stages

BACH exists in three stages: **USMC** (Memory core), **Rinnsal** (+ LLM orchestration), **BACH** (complete system). Details: [README.md](README.md#ausbaustufen)

#### Three Access Modes

BACH offers **two parallel access paths** (CLI + Library API), which can be combined into **three modes**. Both paths use the same handlers and the same DB.

##### Mode 1: Session Mode (CLI -- classic)

Full startup/shutdown protocol via the command line. For interactive terminal sessions.

```bash
cd system
python bach.py --startup --partner=claude --mode=silent --watch
# ... work ...
python bach.py --shutdown "Summary"
```

##### Mode 2: Library Mode (API -- lightweight)

Direct access to handlers without session overhead. For scripts, quick queries, or LLMs that only need individual operations.

```python
from bach_api import task, memory, steuer, partner, tools, injector

task.list()                              # Query tasks
memory.write("Important note")           # Write to memory
steuer.status()                          # Tax status
partner.list()                           # List partners
injector.process("I am stuck")           # Cognitive help
```

##### Mode 3: Mixed Mode (API with session lifecycle)

Full startup/shutdown via the API. **Recommended for LLM sessions** -- combines session management with ergonomic API access.

```python
from bach_api import session, task, memory, injector

# Start session (= python bach.py --startup --partner=claude --mode=silent)
session.startup(partner="claude", mode="silent")

# Work with API
task.list()
memory.write("Note")
injector.process("complex task")

# End session (= python bach.py --shutdown "Summary")
session.shutdown("What was done. Next: What comes next.")
```

##### Available API Modules

```python
from bach_api import (
    # Session Lifecycle
    session,     # startup(), shutdown(), shutdown_quick(), shutdown_emergency()

    # Core Handlers
    task,        # add(), list(), done(), assign(), ...
    memory,      # write(), read(), status(), fact(), search(), ...
    backup,      # create(), list(), info()
    status,      # run()

    # Domain Handlers
    steuer,      # status(), beleg(), posten(), export()
    lesson,      # add(), last(), list(), search()
    partner,     # list(), status(), delegate(), info()
    logs,        # status(), tail(), show()
    msg,         # send(), unread(), read()
    email,       # send(), draft(), drafts(), confirm(), setup()

    # Cognitive Injektoren
    injector,    # process(), check_between(), tool_reminder(), status(), toggle()

    # Hook Framework
    hooks,       # on(), off(), emit(), status(), list_events()

    # Plugin API (Dynamic Extension)
    plugins,     # register_tool(), register_hook(), register_handler(), load_plugin()

    # Raw Access (any handler)
    app,         # app().execute("handler", "operation", ["args"])
)
```

##### When to use what

| Situation | Recommendation |
|-----------|----------------|
| LLM session (recommended) | Mixed Mode: `session.startup()` + API |
| Quick single query | Library Mode: directly `task.list()` |
| Human at terminal | Session Mode: `python bach.py --startup` |
| Read files, search code | Directly (Glob/Grep/Read) |
| Handler not in bach_api | `app().execute("handler", "op", ["args"])` |

**Architecture:** `core/registry.py` auto-discovers 113+ handlers (Auto-Discovery). New handlers only need a `.py` file in `hub/` -- no manual mapping. Hot-Reload: `app().reload_registry()`

#### Component Types

| Type | Folder | Characteristic |
|------|--------|----------------|
| **Agent** | `agents/<name>/` | Orchestrates experts, own folder |
| **Expert** | `agents/_experts/<name>/` | Deep domain knowledge, own folder |
| **Service** | `hub/_services/<name>/` | General purpose, close to handlers, own folder |
| **Protocol** | `skills/workflows/` | 1 file = 1 protocol (formerly workflow), category subfolders allowed |
| **Connector** | `connectors/` | External integrations (MCP, APIs) |
| **Tool (general)** | `tools/` | Reusable |
| **Tool (specific)** | In skill folder | Only for this skill |

#### Skill Sources & Security

| Class | Sources | Approach |
|-------|---------|----------|
| **Gold standard** | Self-written | Best integration |
| **Reputable** | anthropics/skills, anthropics/claude-cookbooks | Adoptable after review |
| **Untrusted** | Other GitHub repos | ONLY rewrite from scratch |
| **Blacklist** | `data/skill_blacklist.json` | FORBIDDEN |

---

## STARTUP PROCEDURE [B/C]: (1) -> (2) -> (3) -> (4) -> (5) -> (6)

*Only in Mode B (Mixed) and C (Session). Mode A skips this section.*

---

### (1) START Bach now [B/C]

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
# Mode B (API)
session.startup(partner="gemini", mode="silent")
# Mode C (CLI)
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

Or via API: `help.run("cli")`, `help.run("features")`, etc.

#### Handler Discovery & Search

BACH has 113+ handlers in `hub/`. **Every handler is a CLI command.** To find handlers, tools, skills, or help topics:

```bash
# Fuzzy search in help topics (187+ topics, fuzzy match!)
bach help <search term>           # e.g. bach help web -> suggests web_scrape, web_parse

# List handlers
bach help list                    # All 187+ help topics
bach help cli                     # CLI command overview

# Search tools
bach tools list                   # All Python tools
bach tools search <keyword>       # Full-text search in tool names and contents

# Search skills & agents
bach skills list                  # All skills in the DB
bach skills search <keyword>      # Filter skills by keyword
bach agent list                   # All agents

# Call any handler directly
bach <handler-name> <operation>   # e.g. bach web-scrape get <url>
```

**Important:** If you don't know which handler exists, use `bach help <search term>` -- the fuzzy search suggests matching topics, even with imprecise terms.

#### Files for review

- `system/CHANGELOG.md` - Version history
- `system/ROADMAP.md` - Planned features & architecture overview

#### Root Documents (generated from DB, updated on `bach --shutdown`)

- `AGENTS.md` - All boss agents and experts with status and paths
- `PARTNERS.md` - LLM partners and delegation
- `SKILLS.md` - Skill index
- `WORKFLOWS.md` - Protocol index
- `CHAINS.md` - Toolchains
- `USECASES.md` - Use cases
- `USER.md` - User profile
- `MEMORY.md` - Memory snapshot
- `BACH_HELP_REFERENCE.md` - Complete help reference

#### Core Principles

- **BACH as organism**: Connectors/Bridge are the **senses & voice** (perception + communication with the outside world). LLMs are the **mind** (thinking, understanding, deciding). The database and text files are the **memory**. The GUI is the **face**. API, CLI, tools, agents, skills, and workflows are the **hands** (action potential).
- **Handler First**: Every function as a handler in `hub/` -- automatically accessible via CLI **and** API
- **API preferred**: LLMs use `bach_api` instead of CLI. Humans use CLI or GUI.
- **Systemic**: Reusable for any user
- **dist_type**: 0=USER (personal), 1=TEMPLATE (customizable), 2=CORE (system)
- **Idempotent**: Imports repeatable without duplicates
- **Version check**: Always use the newest version

> **CORE PRINCIPLE:** BACH is NOT primarily developed for a single user, but as a reusable system.

#### Working Principles

Six fundamental rules for all BACH partners (LLMs, agents, experts):

1. **Own resources first** -- Check memory, wiki, tools, and DB before asking the user
2. **Results over process** -- What counts is the result, not the method
3. **Act instead of announce** -- Don't explain what you will do, just do it
4. **Have an opinion** -- You may disagree and make your own suggestions
5. **Stay compact** -- System prompts under 1000 tokens, keep injections lean
6. **Secure knowledge** -- Write insights to memory before context is lost

**Partner-specific instructions:**
- **Claude**: Read `CLAUDE.md` in the root directory (Knowledge Capture rule, integration)
- **Gemini**: Read `GEMINI.md` in the root directory (Knowledge Capture rule, integration)
- **Ollama**: Read `OLLAMA.md` in the root directory (Knowledge Capture rule, integration)

These files contain detailed knowledge capture rules and partner-specific settings.

#### Database Schema (138 tables in bach.db)

| # | Area | Key Tables |
|---|------|------------|
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
| 14 | Use Cases | `usecases`, `toolchains` |

Complete schema: `system/data/schema/schema.sql` (138 tables + views + FTS)

---

### BACH v2.6 OVERALL ARCHITECTURE

```text
  +=====================================================================+
  |                             USER INTERFACES                         |
  |  +-----------+  +-----------+  +-----------+  +-------------------+ |
  |  |    CLI    |  | Lib-API   |  |    GUI    |  |  MCP v2.2 (IDE)   | |
  |  |  bach.py  |  | bach_api  |  | server.py |  |  mcp_server.py   | |
  |  +-----+-----+  +-----+-----+  +-----+-----+  +--------+--------+ |
  +========|==============|==============|==================|===========+
           |              |              |                  |
  +========v==============v==============v==================v===========+
  |                    CORE LAYER (core/*.py)                           |
  |  app.py -> registry.py -> Auto-Discovery of 75+ handlers           |
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
  | agents/ (folders)     |   |   | connectors/ (MCP, APIs)           |
  | agents/_experts/      |   |   | partners/ (Multi-LLM config)      |
  +-----------------------+   |   +------------------------------------+
                              |
  +---------------------------v----------------------------------------+
  |   SKILLS & TOOLS LAYER                     |    DATA LAYER         |
  |                                            |                       |
  | skills/workflows/ (formerly _workflows)    | bach.db (Unified)     |
  | skills/_templates/ (Standard templates)    | File system            |
  | hub/_services/ (folders)                   | inbox/outbox/          |
  | tools/*.py | c_*.py | injectors.py         |                       |
  +--------------------------------------------+-----------------------+
              |
  +-----------v-----------+
  | SELF-EXTENSION LAYER  |
  |                       |
  | skills create (6 typ) |
  | skills reload (Hot)   |
  | hooks.on/emit (14 Ev) |
  | Plugin API (planned)  |
  +-----------------------+
```

---

### (3) MEMORY: Load your episodic context [B/C]

```bash
bach help memory
bach help lessons
bach help consolidation
```

#### The Cognitive Memory Model (5 Types)

| Type | Equivalent | Function | Command |
|------|------------|----------|---------|
| **Working** | Short-term | Current session | `bach mem write` |
| **Episodic** | Diary | Completed sessions | `bach --memory session` |
| **Semantic** | World knowledge | Facts, wiki, help | `bach --memory fact` |
| **Procedural** | Know-how | Tools, skills, workflows | `bach help tools` |
| **Associative** | Linking | Consolidation, triggers | `bach consolidate` |

---

### (4) CAPABILITIES: Load knowledge about your capabilities [B/C]

```bash
bach help skills
bach help tools
```

**Hierarchy:**

- **Agents**: Orchestrate multiple domains, own folder
- **Experts**: Deep domain knowledge, own folder
- **Services**: General-purpose services, close to handlers

**Important directories:**

- `system/agents/` - Agents (each with own folder)
- `system/agents/_experts/` - Experts (each with own folder)
- `system/hub/_services/` - Services (each with own folder)
- `system/skills/workflows/` - Protocols (single files, formerly _workflows)
- `system/skills/_templates/` - Standard templates
- `system/connectors/` - External integrations (MCP, APIs)
- `system/partners/` - Multi-LLM configurations

---

### (5) TASK PLANNING [B/C]

#### (5.1) Recognize user requests

- Recognize concrete user requests mentioned in the prompt as tasks
- Define tasks and plan your approach
- If no concrete requests are present, proceed to 5.2

#### (5.2) Load task context

```python
# API (preferred)
from bach_api import task
task.list()
```

```bash
# CLI
bach help tasks
bach task list
```

- Independently select tasks and assign them to yourself

---

### (6) PROCEDURAL KNOWLEDGE & PROTOCOLS [C]

*In Mode B optional -- protocols are documentation, not code.*

```bash
bach help protocol
bach help between-tasks
bach help practices
```

**Path:** `system/skills/workflows/`

---

## TOPIC PACKAGES (read when needed -- all modes)

### TOPIC: Collaboration (PACKAGE: TEAMWORK)

*When to read:* You are working with partners in the system.

```bash
bach help partners
bach help multi_llm
bach help delegate
```

**Chat system:**

```python
# API
from bach_api import msg, partner
msg.send("gemini", "Please research...")
msg.unread()
partner.delegate("Research", "--to=gemini")
```

```bash
# CLI
bach msg send claude "Text"
bach msg unread
```

**Lock system:**

```bash
bach llm lock <file>            # Lock BEFORE writing
bach llm unlock [file]          # Release lock
bach llm status                 # Who has which locks?
```

---

### TOPIC: Problem Solving (PACKAGE: PROBLEM SOLVING)

*When to read:* You encounter problems or blockers.

```bash
bach help operatoren
bach help planning
bach help problemloesung
bach help strategien
```

---

### TOPIC: Coding Tasks (PACKAGE: CODING)

*When to read:* You are working on code or fixing bugs.

```bash
bach help ati
bach help coding
bach help bugfix
```

---

### TOPIC: Maintenance (PACKAGE: MAINTENANCE)

*When to read:* You are working on maintenance tasks.

```bash
bach help maintain
bach help wartung
bach help recurring
bach daemon status
```

---

### TOPIC: File Management (PACKAGE: FILE MANAGEMENT)

*When to read:* You are performing file operations.

```bash
bach help trash
bach help migrate
bach help distribution
```

---

### TOPIC: Reading Websites (PACKAGE: WEB)

*When to read:* You need to fetch web pages, extract content, or perform web analysis.

```bash
bach help web_parse
bach help web_scrape
```

**Two handlers for different purposes:**

| Handler | Command | Purpose | Technology |
|---------|---------|---------|------------|
| `web_parse` | `bach web-parse url/clean <url>` | **Content extraction** (main content as Markdown) | trafilatura/html2text |
| `web_scrape` | `bach web-scrape get/links/forms/headers <url>` | **Structure analysis** (links, forms, headers) | requests + Regex |

**Recommendation:** For text content use `web-parse clean <url>` (removes nav/header/footer). For raw data or link lists use `web-scrape`. Both use HTTP requests -- JS-rendered pages only deliver the server-side HTML portion.

**Skill:** `skills/workflows/webseiten-lesen.md` -- Detailed procedure with decision tree.

---

### TOPIC: Self-Extension (PACKAGE: SELF-EXTENSION) [B/C]

*When to read:* You lack a capability or want to extend BACH.

```bash
bach help self-extension
bach help hooks
bach help skills
```

**Create new capabilities (5 types):**

```bash
bach skills create voice-processor --type tool       # Scaffold new tool
bach skills create email-agent --type agent           # Scaffold new agent
bach skills create tax-expert --type expert            # Scaffold new expert
bach skills create api-gateway --type handler          # Scaffold new CLI command
bach skills create data-sync --type service            # Scaffold new service
```

**After creation: Hot-Reload (no restart needed!)**

```bash
bach skills reload
```

**Hook Framework (14 events):**

```python
from core.hooks import hooks

# Attach own logic to system events
hooks.on('after_task_create', my_function, name='my_plugin')
hooks.on('after_startup', startup_check, name='my_plugin')

# Show events
# bach hooks events
```

**Plugin API (Dynamic extension at runtime):**

```python
from bach_api import plugins

# Register tool (immediately usable)
plugins.register_tool("my_tool", my_function, "Description")

# Register hook (subscribe to event)
plugins.register_hook("after_task_done", callback, plugin="my-plugin")

# Register handler (new CLI command!)
plugins.register_handler("my_cmd", MyHandler)

# Load plugin from manifest
plugins.load_plugin("plugins/my-plugin/plugin.json")
```

```bash
# CLI: Plugin management
bach plugins list          # Loaded plugins
bach plugins create name   # Scaffold plugin
bach plugins load path     # Load plugin
bach plugins unload name   # Unload plugin
```

**Self-Extension Loop:**
1. RECOGNIZE -> Identify missing capability
2. CREATE -> `bach skills create <name> --type <type>` or `plugins.register_tool()`
3. IMPLEMENT -> Write code
4. REGISTER -> `bach skills reload` or `plugins.load_plugin()`
5. USE -> Immediately available
6. REFLECT -> `bach lesson add "What was learned"`

---

### TOPIC: Shutdown (PACKAGE: SHUTDOWN) [B/C]

*When to read:* The session is ending. Only relevant in Mode B and C.

**Mode B (API -- recommended):**
```python
from bach_api import session, memory
memory.session("TOPIC: What was done. NEXT: What comes next.")
session.shutdown("Summary", partner="claude")
# Or quick:
session.shutdown_quick("Short note")
```

**Mode C (CLI):**
```bash
bach help shutdown
bach --memory session "TOPIC: What was done. NEXT: What comes next."
bach --shutdown
```

---

## HOOKS & INJEKTOREN

### Hook Framework (Technical Event System)

Hooks allow attaching custom logic to 14 lifecycle events -- without modifying existing code.

```python
from core.hooks import hooks

# Register listener
hooks.on('after_task_done', auto_backup, name='backup_plugin')
hooks.on('after_startup', health_check, priority=10, name='health')

# CLI
# bach hooks status    -> Shows all hooks
# bach hooks events    -> Lists all 14 events
# bach hooks log       -> Recent executions
```

**Events:** `before_startup`, `after_startup`, `before_shutdown`, `after_shutdown`, `before_command`, `after_command`, `after_task_create`, `after_task_done`, `after_task_delete`, `after_memory_write`, `after_lesson_add`, `after_skill_create`, `after_skill_reload`, `after_email_send`

> Hooks are the **technical framework**. Injektoren are the **cognitive subsystem**. They operate independently of each other.

---

### Injektoren (Cognitive Orchestration)

The 6 Injektoren simulate **thinking and associations** as the **Central Executive**. Available via CLI and API.

| Injektor | Sub-functions | API-capable |
|----------|---------------|:-----------:|
| **strategy_injector** | Metacognition, decision support, error analysis | Yes |
| **context_injector** | Tool recommendation, memory retrieval, requirements analysis | Partial* |
| **between_injector** | Quality control, task transition, result validation | Yes |
| **time_injector** | Time awareness (timebeat), message check | Yes |
| **tool_injector** | Tool reminder, duplicate warning | Yes |
| **task_assigner** | Auto-assignment, task decomposition | Yes |

*\*context_injector contains CLI commands as hints. Filterable in API mode.*

**CLI:**
```bash
bach --inject status            # Status of all Injektoren
bach --inject toggle <name>     # Toggle on/off
```

**API:**
```python
from bach_api import injector

injector.process("text")              # Apply all Injektoren to text
injector.check_between("task done")   # Quality check after task completion
injector.tool_reminder()              # Available tools (once)
injector.assign_task()                # Auto-assign next task
injector.time_check()                 # Time + messages
injector.status()                     # Status of all Injektoren
injector.toggle("strategy_injector")  # Toggle individual on/off
injector.set_mode("api")              # Filter CLI hints from context
```

---

## CHANGELOG

### v3.8.0 (2026-03-12)

- **Handler Discovery**: New section in Section (2) -- `bach help <search term>` documented as primary discovery mechanism for 109+ handlers
- **Search reference**: `bach help list`, `bach tools search`, `bach skills search` as search entry points
- **Topic package WEB**: New package with references to `web_parse` and `web_scrape` handlers
- **Skill `webseiten-lesen`**: New workflow skill with decision tree for web content extraction
- **Documentation**: Handlers are now discoverable in SKILL.md instead of only via CLI
- **English version**: SKILL_EN.md created as full translation

### v3.2.0-butternut (2026-02-28)

- **Agent CLI**: `AgentLauncherHandler` -- `bach agent start/stop/list` for direct agent control
- **Prompt system**: `PromptHandler` -- `bach prompt list/add/edit/show/board-create` for central prompt management
- **SharedMemory extensions**: `current-task`, `generate-context`, `conflict-resolution`, `decay`, `changes-since`
- **USMC Bridge**: United Shared Memory Client (`hub/_services/usmc_bridge.py`)
- **llmauto chains**: Claude prompts as chain steps + `bach://` URL resolution
- **Scheduler**: `job_type='chain'` + rename `daemon_jobs` -> `scheduler_jobs`
- **New API modules**: `agent`, `prompt` in `bach_api`
- **Ports**: SharedMemoryHandler, ApiProberHandler, N8nManagerHandler, UserSyncHandler, Stigmergy service
- **Tables**: 4 new DB tables: `prompt_templates`, `prompt_versions`, `prompt_boards`, `prompt_board_items`
- **109+ handlers** (previously: 75+)

### v2.6.0 (2026-02-13)

- **Directory restructuring**: Clear separation of agents, skills, connectors, and partners
  - `skills/_agents/` -> `agents/` (top-level under system/)
  - `skills/_experts/` -> `agents/_experts/` (experts belong to agents)
  - `skills/_workflows/` -> `skills/workflows/` (workflows now called protocols)
  - `skills/_connectors/` -> `connectors/` (top-level under system/)
  - `skills/_partners/` -> `partners/` (top-level under system/)
- **PathHealer**: Automatic path correction in all affected files
- **Component type `protocol`**: Replaces `workflow` in the type hierarchy
- **Component type `connector`**: New for external integrations (MCP, APIs)
- **Architecture diagram**: AGENTS LAYER and CONNECTORS & PARTNERS as separate sections
- **SKILL.md v2.6**: All references, tables, and diagrams adapted to new structure

### v2.5.0 (2026-02-13)

- **Self-Extension System**: AI partners can give themselves new capabilities
  - `bach skills create <name> --type <type>` (5 types: tool, agent, expert, handler, service)
  - `bach skills reload` (hot-reload: registry + tools + skills DB)
  - Self-Extension Loop: RECOGNIZE -> CREATE -> REGISTER -> USE -> REFLECT
- **Hook Framework**: Extensible event system with 14 lifecycle events
  - `core/hooks.py` - HookRegistry singleton, priorities, event log
  - `hub/hooks.py` - CLI: `bach hooks status/events/log/test`
  - Integration in: startup, shutdown, task, memory, lesson, skills, app
  - Hooks != Injektoren: Technical framework vs. cognitive subsystem
- **Email Handler**: Gmail API with draft safety (send, draft, confirm, cancel)
- **Registry Hot-Reload**: `app().reload_registry()` without restart
- **Rule (f) Self-Extension**: "If you lack a capability, give it to yourself!"
- **Documentation**: hooks.txt, self-extension.txt, cli.txt, skills.txt, ROADMAP.md

### v2.4.0 (2026-02-08)

- **MCP Server v2.2**: 23 tools, 8 resources, 3 prompts - all three MCP primitives
- **Email adapter**: SMTP_SSL in notify.py (ported from BachForelle)
- **BachFliege + BachForelle**: Analyzed and archived (`docs/_archive/con5_BACHFLIEGE_BACHFORELLE_ARCHIV.md`)

### v2.3.0 (2026-02-06)

- **Ruleset completely revised**: ALWAYS -> Access type -> Mode-specific
- **Three modes**: A (Library), B (Mixed), C (Session) with [B], [C], [B/C] tags
- **Co-development principle**: "BACH usage is co-development" as core rule
- **bach_api.py extended**: session, partner, logs, msg, tools, help, injector
- **14 API modules**: Complete programmatic access to all handlers
- **Injektoren via API**: All 6 Injektoren usable via library + CLI filter
- **Session lifecycle via API**: `session.startup()` / `session.shutdown()`
- Architecture diagram updated (Core Layer + bach_api)
- All sections tagged with mode labels

### v2.2.0 (2026-02-06)

- Two access paths (CLI + Library API) documented
- bach_api.py base modules: task, memory, backup, steuer, lesson, status

### v2.1.0 (2026-02-04)

- Skill Architecture v2.0 integrated
- Version check principle introduced
- Standard header documented
- Skill source classification added
- Injektor sub-functions documented

### v2.0.2 (2026-01-01)

- Initial version

---

**BACH Skill Architecture v2.0**
