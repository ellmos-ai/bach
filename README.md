<p>
  <img src="logo_bach_text.jpg" alt="BACH logo" width="400" align="left">
  <img src="ellmos-logo.jpg" alt="ellmos logo" width="200" align="right">
</p>
<br clear="both">

# ellmos BACH - Text-Based Operating System for LLMs

*The stream that unites everything.*

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)
![License](https://img.shields.io/badge/License-MIT-green)
![Version](https://img.shields.io/badge/Version-v3.11.1-orange)
![Status](https://img.shields.io/badge/Status-Production--Ready-brightgreen)
![Tests](https://img.shields.io/badge/Tests-4144%20passed-brightgreen)

**Version:** v3.11.1

<p align="center">
  <img src="overview.jpg" alt="BACH Overview" width="700">
</p>

## Overview

**BACH** is a text-based operating system that empowers Large Language Models (LLMs) to work autonomously, learn, and self-organize. Part of the **ellmos** family (Extra Large Language Model Operating Systems), BACH provides comprehensive infrastructure for task management, knowledge management, automation, and LLM orchestration.

### Key Features

- **113+ Handlers** - Full CLI and API coverage of all system functions
- **550+ Tools** - Extensive tool library for file processing, analysis, and automation
- **1870+ Skills** - Reusable workflows and templates
- **58 Workflow Templates** - Pre-built process workflows
- **4100+ Tests** - Comprehensive test suite covering handlers, services, GUI, and MCP servers
- **Knowledge Store** - Lessons, Facts, and Multi-Level Memory System (6 memory types)
- **Agent CLI** - `bach agent start/stop/list` for direct agent control
- **Agent Doctor** - `bach agent doctor [name] [--json]` validates Claude CLI availability, runtime dirs, skill files, and stale PID state before a launch
- **Scheduler Doctor** - `bach scheduler doctor [--json]` plus `bach scheduler session doctor [--json]` validate automation scripts, PID state, DB/config/profile surfaces, and suggest recovery steps before background services are started
- **Session Steering Controls** - `bach scheduler session pause/resume/steer/clear-steer` lets operators gate or retarget the next profile-specific auto-session without editing daemon config by hand
- **Machine-readable Control & Status Surfaces** - `bach agent list/start/stop/status --json` plus `bach scheduler status/jobs/session status --json` for external tooling and automation-safe polling
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

- **[ellmos-codecommander-mcp](https://www.npmjs.com/package/ellmos-codecommander-mcp)** v1.3.8 - Code analysis and refactoring tools (17 tools)
- **[ellmos-filecommander-mcp](https://www.npmjs.com/package/ellmos-filecommander-mcp)** v1.7.8 - File management and batch operations (44 tools)

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

# Shut down BACH
python bach.py --shutdown
```

## Core Components

### 1. Task Management
Full GTD system with prioritization, deadlines, tags, and context tracking.

### 2. Knowledge System
Structured memory system with Facts, Lessons, and automatic consolidation (6 memory types, 210+ DB tables).

### 3. Agent Framework
11 Boss agents orchestrate 22 experts for complex tasks. The Agent CLI allows direct starting, stopping, and listing of agents via `bach agent`.

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

- **[Quickstart Guide](QUICKSTART.md)** - Get your first workflow running in 5 minutes
- **[User Manual](BACH_USER_MANUAL.md)** - Complete handbook
- **[Skills Catalog](SKILLS.md)** - All available skills
- **[Agents Catalog](AGENTS.md)** - All available agents and experts
- **[Workflows](WORKFLOWS.md)** - 59 workflow templates
- **[SKILL.md](SKILL.md)** - LLM operating instructions (for Claude, Gemini, Ollama)

## See Also: OpenClaw

How does BACH compare to [OpenClaw](https://github.com/openclaw/openclaw), a popular open-source AI assistant?

| | **BACH** | **OpenClaw** |
|---|---|---|
| **Focus** | LLM Operating System -- deep autonomy, structured memory, multi-agent orchestration | Personal AI Assistant -- broad messaging gateway, voice, companion apps |
| **Tools/Skills** | 550+ tools, 1870+ skills, 59 workflows (local, curated) | Community-driven skill/plugin ecosystem; recent releases emphasize manifest-first plugin metadata and install safety |
| **Memory** | 6 memory types with decay, conflict detection, consolidation (210+ DB tables) | Session/runtime workspace with bootstrap files such as `AGENTS.md`, `TOOLS.md`, `USER.md`, and related context files |
| **Agents** | Boss-Expert orchestration (11 boss agents + 22 experts), SharedMemory Bus | Agent runtime with multi-session/channel operation |
| **Messaging** | Telegram, Email, WhatsApp (Bridge System) | 20+ platforms (WhatsApp, Telegram, Slack, Discord, Signal, Teams, Matrix...) |
| **Interfaces** | CLI, Python API, PySide6 GUI, Web GUI, Telegram Bot, Web Chat, System Tray | CLI, WebChat, macOS/iOS/Android apps, Voice |
| **MCP** | Own MCP servers (FileCommander, CodeCommander) | Native MCP Registry |
| **Stack** | Python 3.10+, SQLite | TypeScript, Node.js 22+ |
| **License** | MIT | MIT |

**In short:** BACH goes deep (structured memory, autonomous agents, scheduler, 210+ DB tables). OpenClaw goes wide (20+ messengers, native apps, voice, large community). Different philosophies, complementary strengths.

### Competitive Watch

As of 2026-05-16, GitHub Releases still marks `2026.5.12` as OpenClaw's latest stable release, while the newest visible pre-release is now `2026.5.16-beta.1`; the package landing page likewise advertises `2026.5.16-beta.1-slim` as its latest tagged image, and the recent image list also shows `2026.5.14-beta.3-slim`. The newest official notes continue to shift attention away from raw channel breadth and toward operator control, release hardening, and safer runtime boundaries: localized onboarding/setup flows, config-gated warm caching for resolved skills, ambient group-chat room events, scheduled-run fallback semantics for subagents, per-agent Codex MCP scoping plus default approval modes, malformed extension metadata rejection, MIME sniffing before agent-visible file ingestion, and config persistence that ignores malformed stored state. BACH already covers adjacent control-plane territory with manifest-first metadata, fail-closed setup checks, broader install scanning for skills/MCP/plugins, privacy-preserving secret/reference handling, memory/wiki provenance views, canonical `bach path` surfaces, machine-readable agent/scheduler status surfaces, workspace-scoped agent-runtime cache invalidation, stable Windows agent tracking via durable console PIDs, `bach agent doctor`, `bach scheduler doctor` / `bach scheduler session doctor`, machine-readable `bach agent start/stop --json` responses for automation-safe operator control, `bach agent steer` as an operator-notes bridge, and profile-scoped session controls via `bach scheduler session pause`, `resume`, `steer`, and `clear-steer`, plus chain-level operator controls through `bach chain pause`, `bach chain resume`, and `bach chain steer` at safe llmauto checkpoints. Next high-leverage steps remain extending comparable steering semantics to broader agent/scheduler runs, tightening per-agent tool/connector scopes, hardening ingest validation and malformed-state cleanup, adding low-cardinality telemetry and release-validation lanes, and deciding which backend fallback semantics fit BACH's multi-partner model.

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

*ellmos BACH v3.11.1 - Text-Based Operating System for LLMs*

---

## Haftung / Liability

Dieses Projekt ist eine **unentgeltliche Open-Source-Schenkung** im Sinne der §§ 516 ff. BGB. Die Haftung des Urhebers ist gemäß **§ 521 BGB** auf **Vorsatz und grobe Fahrlässigkeit** beschränkt. Ergänzend gelten die Haftungsausschlüsse aus GPL-3.0 / MIT / Apache-2.0 §§ 15–16 (je nach gewählter Lizenz).

Nutzung auf eigenes Risiko. Keine Wartungszusage, keine Verfügbarkeitsgarantie, keine Gewähr für Fehlerfreiheit oder Eignung für einen bestimmten Zweck.

This project is an unpaid open-source donation. Liability is limited to intent and gross negligence (§ 521 German Civil Code). Use at your own risk. No warranty, no maintenance guarantee, no fitness-for-purpose assumed.
