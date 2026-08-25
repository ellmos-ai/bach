<img src="assets/banner_v2.png" width="100%" alt="BACH Banner">

# ellmos BACH — Text-Based Operating System for LLMs

> The stream that unites everything.

[![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Version](https://img.shields.io/badge/Version-v3.13.0--bluesky-orange)](CHANGELOG.md)
[![Status](https://img.shields.io/badge/Status-Production--Ready-brightgreen)](ROADMAP.md)
[![Tests](https://img.shields.io/badge/Tests-4436%20collected-blue)](system/tests/)

**Version:** v3.13.0-bluesky

## 🎬 Demo video

See BACH working live — dashboard, Codex backend, operator steering — in 2:22:

[![BACH demo — local-first LLM operating system (2:22)](https://img.youtube.com/vi/Gv5nxF8HssU/maxresdefault.jpg)](https://youtu.be/Gv5nxF8HssU)

## Built with OpenAI Codex & GPT-5.6

BACH uses Codex both as a first-class runtime backend and as a repository-development partner. For the exact automation schedules, model routes, and auditable session IDs, see the [verified Build Week attribution](#openai-build-week--codex-and-gpt-56) below.

## Languages

BACH is documented and shipped with translation surfaces for six languages:

**🇬🇧 English** | [🇩🇪 Deutsch](README.de.md) | [🇪🇸 Español](README.es.md) | [🇷🇺 Русский](README.ru.md) | [🇯🇵 日本語](README.ja.md) | [🇨🇳 中文](README.zh.md)

The current release snapshot enables `de`, `en`, `es`, `ru`, `ja`, and `zh` in `system/exports/translations/languages_config.release.json` and exports matching locale files in `system/exports/translations/locales/`. For crawlers and direct language entry points, each language also has its own `README.md` under `docs/i18n/<lang>/`.

<p align="center">
  <img src="overview.jpg" alt="BACH Overview" width="700">
</p>

## Overview

**BACH** is a text-based operating system that empowers Large Language Models (LLMs) to work autonomously, learn, and self-organize. Part of the **ellmos** family (Extra Large Language Model Operating Systems), BACH provides comprehensive infrastructure for task management, knowledge management, automation, and LLM orchestration.

## Discovery Context

BACH is best described as a **local-first LLM operating system**: a persistent Python/SQLite workbench for autonomous agents, structured memory, scheduler-driven automation, prompt chains, MCP server integration, and multilingual operator surfaces. It is not a chatbot wrapper, hosted agent SaaS, Bash unit-test framework, music project, or LangChain-style pipeline library.

Canonical GitHub repository: `ellmos-ai/bach`. Machine-readable project context for LLM crawlers is available in [`llms.txt`](llms.txt).

Useful search phrases include `ellmos-ai/bach`, `local-first LLM operating system`, `text-based OS for LLM agents`, `SQLite memory for AI agents`, `BACH ellmos agent OS`, `personal agentic OS Python SQLite`, and `multi-agent orchestration with MCP servers`.

## OpenAI Build Week — Codex and GPT-5.6

BACH uses Codex in two distinct roles:

- **Runtime backend:** `codex-cli` is one of five pluggable chat backends, and BACH agents can delegate coding tasks through `codex exec`.
- **Repository development:** three active Codex automations maintain the project: `bach-daily-care-and-dev-check`, `bach-start-and-health-checks`, and `bach-github-release-service`. Since July 21, 2026, all three have been configured for GPT-5.6 (`gpt-5.6-terra`); the first two run daily, while the release service runs weekly.
- **Verified model routing:** in Codex Session `019f85c6-4339-7f13-b8e5-bf1823fd8432`, GPT-5.6 Sol with high reasoning audited all 78 automation definitions and routed BACH's development and release jobs to Terra/high and health checks to Terra/medium.
- **Final submission audit:** GPT-5.6 Sol in Codex Session `019f8674-fe9a-7d91-a80f-7ee799e8ced0` reviewed and certified the pending BACH changes, corrected the competition attribution, and completed the web-scrape hardening and regression tests.

For auditability, the GPT-5.6 automation attribution applies from that configuration change forward; earlier automation runs used earlier Codex models.

### Key Features

- **113+ Handlers** - Full CLI and API coverage of all system functions
- **550+ Tools** - Extensive tool library for file processing, analysis, and automation
- **1870+ Skills** - Reusable workflows and templates
- **Skill Source Registry** - `bach skills version bach` resolves the canonical repo-root skill via `system/data/skill_sources.json` and can compare optional Codex/Claude user copies without fuzzy filename drift
- **71 Workflow Templates** - Pre-built process workflows
- **4400+ Tests** - Comprehensive automated coverage across handlers, services, GUI, and MCP servers
- **Knowledge Store** - Lessons, Facts, and Multi-Level Memory System (6 memory types)
- **Agent CLI** - `bach agent start/stop/list` for direct agent control
- **Agent Doctor** - `bach agent doctor [name] [--json]` validates Claude CLI availability, runtime dirs, skill files, and stale PID state before a launch
- **Agent Operator Controls** - `bach agent pause/resume/checkpoint/steer/clear-steer [name] [--json]` lets operators stage cooperative pause requests and guidance before or during a run, record explicit safe-checkpoint acknowledgements, mirror that state into `OPERATOR_NOTES.md`, preserve queued hints across the next `bach agent start`, inject them into the generated session `CLAUDE.md`, and expose nested `operator_control` snapshots plus `queued_for_next_start` for automation-safe polling
- **Agent Runtime Policy Defaults** - `bach agent start` now accepts `--permission-mode`, `--allowed-tools`, and `--max-turns`, and can preload the same defaults from agent SKILL frontmatter for per-agent guardrails
- **Scheduler Doctor** - `bach scheduler doctor [--json]` plus `bach scheduler session doctor [--json]` validate automation scripts, PID state, DB/config/profile surfaces, and suggest recovery steps before background services are started
- **Session Steering Controls** - `bach scheduler session pause/resume/steer/clear-steer [--json]` lets operators gate or retarget the next profile-specific auto-session without editing daemon config by hand
- **Scheduler Run Controls** - `bach scheduler pause/resume/steer/clear-steer [--json]` now exposes the same operator control plane for due scheduler jobs, including global pause and queued run guidance without hand-editing control files; queued scheduler hints now also hydrate llmauto chains into their next safe-checkpoint prompt path
- **Machine-readable Control & Status Surfaces** - `bach agent list/start/stop/pause/resume/checkpoint/steer/clear-steer/status --json`, `bach scheduler status/jobs/session status --json`, and `bach scheduler session pause/resume/steer/clear-steer --json`, including queue state, `queued_for_next_start`, timestamps, checkpoint acknowledgements, and operator-note metadata for automation-safe polling
- **Upgrade Drift & Repair** - `bach upgrade list <path> --json`, `bach upgrade status/check --json`, and `bach upgrade repair [--dry-run] [--version <tag>]` expose automation-safe version, status, drift, repair hints, and recovery for broken distribution metadata
- **Path Surface** - `bach path` exposes canonical system/workspace/DB paths, validation, resolve helpers, and DB overrides in text or JSON
- **Prompt System** - Central prompt management with board system and versioning
- **Install Security Gate** - Static pre-load scans block obvious code-injection patterns during `skills install`/`plugins load`; MCP setup validates allowlisted packages/configs fail-closed, plugin setup contracts now require explicit shell/desktop/MCP checks, and blocked local imports are quarantined
- **Manifest-first Plugins** - `bach plugins inspect` previews activation, provider/model, setup, and capability metadata without importing plugin runtime code
- **Structured `bach_api` Core** - `task` and `memory` now expose discoverable methods via `dir(...)`, return Python objects for common reads/writes, and still keep `raw(...)` for legacy handler-style calls
- **SharedMemory Bus** - Multi-agent coordination with conflict detection and decay
- **USMC Bridge** - United Shared Memory Communication for cross-agent communication
- **llmauto Chains** - Claude prompts as chain steps with `bach://` URL resolution
- **Chat Service** - Multi-backend Telegram bot (5 backends), Control API, Web Dashboard, cross-platform System Tray

## Installation

```bash
# Clone the repository
git clone https://github.com/ellmos-ai/bach.git
cd bach

# Install dependencies and make `bach` CLI available
pip install -e .

# Pre-flight check
bach setup preflight

# Full install (MCP servers, hooks, secrets, user profile)
bach setup full-install
```

## MCP Servers (Claude Code Integration)

BACH provides two MCP servers for integration with Claude Code, Cursor, and other IDEs. Cross-platform tested on Windows, macOS (ARM64), and Linux:

```bash
# Install and configure MCP servers (recommended)
python system/bach.py setup mcp

# Or manually via npm:
npm install -g ellmos-codecommander-mcp ellmos-filecommander-mcp
```

- **[ellmos-codecommander-mcp](https://www.npmjs.com/package/ellmos-codecommander-mcp)** v1.3.14 - Code analysis and refactoring tools (21 tools)
- **[ellmos-filecommander-mcp](https://www.npmjs.com/package/ellmos-filecommander-mcp)** v1.9.1 - File management and batch operations (46 tools)

## Quick Start

```bash
# Start BACH
python bach.py --startup

# Create a task
python bach.py task add "Analyze project structure"

# Manage agents
python bach.py agent list
python bach.py agent start bueroassistent

# Manage prompts
python bach.py prompt list
python bach.py prompt add "My Prompt" --content "..."

# Check scheduler status
python bach.py scheduler status

# Import versioned everyday-data exports (idempotent)
python bach.py abo import PATH/abotracker-export-v1.json
python bach.py versicherung import PATH/bach-fin-insurances-v1.json

# Register recurring imports only after a valid export file exists
python bach.py abo schedule-import PATH/abotracker-export-v1.json --interval 24h
python bach.py versicherung schedule-import PATH/bach-fin-insurances-v1.json --interval 24h

# Preview and refresh the current monthly/year-to-date finance summary
python bach.py haushalt financial-summary refresh --dry-run
python bach.py haushalt financial-summary refresh

# Shut down BACH
python bach.py --shutdown
```

The import commands require the exact schemas `abotracker-export-v1` and
`bach.fin_insurances.v1`. AboTracker billing cycles are not treated as confirmed
next-payment dates. Scheduled jobs are active, idempotent file imports and are
created only after the current source file passes validation.

The finance summary keeps observed mail-derived expenditure separate from the
current recurring subscription run rate. Legacy subscription duplicates are
deduplicated by provider for calculations and dashboard reads; conflicting
duplicates fail closed instead of being guessed or deleted.

## Core Components

### 1. Task Management
Full GTD system with prioritization, deadlines, tags, and context tracking.

### 2. Knowledge System
Structured memory system with Facts, Lessons, and automatic consolidation (6 memory types, 210+ DB tables).

### 3. Agent Framework
11 Boss agents orchestrate 22 experts for complex tasks. The Agent CLI allows direct starting, stopping, and listing of agents via `bach agent`, and now also supports prelaunch steering queues, cooperative pause requests, and explicit safe-checkpoint acknowledgements via `bach agent checkpoint`. Queued hints are injected into the generated session `CLAUDE.md` at launch, `OPERATOR_NOTES.md` mirrors steering, pause, and checkpoint state, and live JSON status surfaces expose the nested `operator_control` snapshot for dashboards.

<p align="center">
  <img src="sketch_bach_boss_agents.jpg" alt="BACH Boss Agents" width="600"><br>
  <i>Illustration shows BACH's five original boss agents: ati, officeassistant, finance-assistant, health-assistant, personal-assistant. The current system ships 11 boss agents and 22 experts.</i>
</p>

### 4. Prompt System
Central management of prompt templates with board collections and full versioning (`bach prompt`).

### 5. Chat Service & Bridge System
Multi-backend Telegram bot with pluggable LLM backends (Ollama, Claude CLI, Codex CLI, Claude API, OpenAI API), HTTP Control API with web dashboard, and cross-platform system tray. Connector framework for additional services (Email, WhatsApp, etc.) and USMC Bridge for cross-agent communication.

### 6. Automation
SchedulerService for time-based jobs (chains, tasks, scripts) and event-driven workflows via the hook framework.

### 7. SharedMemory
Multi-agent coordination with context generation, conflict detection, decay, and delta queries.

### 8. llmauto Integration
Chain steps as LLM prompts with `bach://` URL resolution for dynamic context embedding.

## The ellmos Family

All ellmos projects follow a water metaphor -- from a spring to a full stream:

| Tier | Project | Description | Repository |
|------|---------|-------------|------------|
| 1 | **USMC** | United Shared Memory Client -- the spring (shared memory only) | [github.com/ellmos-ai/usmc](https://github.com/ellmos-ai/usmc) |
| 2 | **Rinnsal** | The trickle -- USMC + llmauto (LLM orchestration), extremely compact | [github.com/ellmos-ai/rinnsal](https://github.com/ellmos-ai/rinnsal) |
| 3 | **BACH** | The stream that unites everything -- 113+ handlers, 1870+ skills, agents, GUI, bridge | [github.com/ellmos-ai/bach](https://github.com/ellmos-ai/bach) |

## Documentation

- **Languages:** [English](README.md) | [Deutsch](README.de.md) | [Español](README.es.md) | [Русский](README.ru.md) | [日本語](README.ja.md) | [中文](README.zh.md)
- **[Quickstart Guide](QUICKSTART.md)** - Get your first workflow running in 5 minutes
- **[User Manual](BACH_USER_MANUAL.md)** - Complete handbook
- **[Skills Catalog](SKILLS.template.md)** - Template and public entry point for available skills
- **[Agents Catalog](AGENTS.template.md)** - Template and public entry point for agents and experts
- **[Workflows](WORKFLOWS.template.md)** - 71 workflow templates
- **[SKILL template](SKILL.template.md)** - LLM operating instructions template for Claude, Gemini, Ollama, and Codex-style agents

## See Also: OpenClaw

How does BACH compare to [OpenClaw](https://github.com/openclaw/openclaw), a popular open-source AI assistant?

| | **BACH** | **OpenClaw** |
|---|---|---|
| **Focus** | LLM Operating System -- deep autonomy, structured memory, multi-agent orchestration | Personal AI Assistant -- broad messaging gateway, voice, companion apps |
| **Tools/Skills** | 550+ tools, 1870+ skills, 71 workflows (local, curated) | Community-driven skill/plugin ecosystem; recent releases emphasize manifest-first plugin metadata and install safety |
| **Memory** | 6 memory types with decay, conflict detection, consolidation (210+ DB tables) | Session/runtime workspace with bootstrap files such as `AGENTS.md`, `TOOLS.md`, `USER.md`, and related context files |
| **Agents** | Boss-Expert orchestration (11 boss agents + 22 experts), SharedMemory Bus | Agent runtime with multi-session/channel operation |
| **Messaging** | Telegram, Email, WhatsApp (Bridge System) | 20+ platforms (WhatsApp, Telegram, Slack, Discord, Signal, Teams, Matrix...) |
| **Interfaces** | CLI, Python API, PySide6 GUI, Web GUI, Telegram Bot, Web Chat, System Tray | CLI, WebChat, macOS/iOS/Android apps, Voice |
| **MCP** | Own MCP servers (FileCommander, CodeCommander) | Native MCP Registry |
| **Stack** | Python 3.10+, SQLite | TypeScript, Node.js 22+ |
| **License** | MIT | MIT |

**In short:** BACH goes deep (structured memory, autonomous agents, scheduler, 210+ DB tables). OpenClaw goes wide (20+ messengers, native apps, voice, large community). Different philosophies, complementary strengths.

### Competitive Watch

As of July 19, 2026, OpenClaw stable remains `2026.7.1`; the newest visible prerelease is `2026.7.2-beta.3`, published on July 18, 2026 at 23:16 UTC. It extends the already tracked MCP-isolation, task-ledger, remote-worker, and recovery signals with remote coding sessions on owning hosts, guided Control UI/channel setup, stronger gateway/session recovery, safer channel operation, and versioned external-supervisor restart handoffs. The best-fit impulses for BACH are supervised restart handoffs, terminal resume on the owning host, guided setup hardening, and recovery-safe channel/session flows; broad mobile/channel parity remains outside BACH's current focus. Source: [openclaw/openclaw releases](https://github.com/openclaw/openclaw/releases/tag/v2026.7.2-beta.3).

On the BACH side, the July 19 care pass sealed the live release catalog: `bach upgrade repair --version v3.13.0-bluesky --json` registered the current release, and `bach upgrade check --json` now reports stable/latest `v3.13.0-bluesky`, `release_entries=2`, `current_release_registered=true`, `repair_recommended=false`, and `local_modifications=0`. `test-agent` doctor/start dry-run and usecase `50` also ran successfully.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Support

- **Issues:** [GitHub Issues](https://github.com/ellmos-ai/bach/issues)
- **Discussions:** [GitHub Discussions](https://github.com/ellmos-ai/bach/discussions)

---

## Deutsche Version

BACH ist ein textbasiertes Betriebssystem, das Large Language Models (LLMs) befähigt, eigenständig zu arbeiten, zu lernen und sich zu organisieren.

Die vollständige deutsche Dokumentation findest du hier: **[README.de.md](README.de.md)**

---

*ellmos BACH v3.13.0-bluesky - Text-Based Operating System for LLMs*

---

## Haftung / Liability

Dieses Projekt ist eine **unentgeltliche Open-Source-Schenkung** im Sinne der §§ 516 ff. BGB. Die Haftung des Urhebers ist gemäß **§ 521 BGB** auf **Vorsatz und grobe Fahrlässigkeit** beschränkt. Ergänzend gelten die Haftungsausschlüsse aus GPL-3.0 / MIT / Apache-2.0 §§ 15–16 (je nach gewählter Lizenz).

Nutzung auf eigenes Risiko. Keine Wartungszusage, keine Verfügbarkeitsgarantie, keine Gewähr für Fehlerfreiheit oder Eignung für einen bestimmten Zweck.

This project is an unpaid open-source donation. Liability is limited to intent and gross negligence (§ 521 German Civil Code). Use at your own risk. No warranty, no maintenance guarantee, no fitness-for-purpose assumed.
