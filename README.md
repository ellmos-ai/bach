<p>
  <img src="logo_bach_text.jpg" alt="BACH logo" width="400" align="left">
  <img src="ellmos-logo.jpg" alt="ellmos logo" width="200" align="right">
</p>
<br clear="both">

# ellmos BACH - Text-Based Operating System for LLMs

*The stream that unites everything.*

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)
![License](https://img.shields.io/badge/License-MIT-green)
![Version](https://img.shields.io/badge/Version-v3.8.0--sugar--of--babel-orange)
![Status](https://img.shields.io/badge/Status-Production--Ready-brightgreen)

**Version:** v3.8.0-sugar-of-babel

<p align="center">
  <img src="overview.jpg" alt="BACH Overview" width="700">
</p>

## Overview

**BACH** is a text-based operating system that empowers Large Language Models (LLMs) to work autonomously, learn, and self-organize. Part of the **ellmos** family (Extra Large Language Model Operating Systems), BACH provides comprehensive infrastructure for task management, knowledge management, automation, and LLM orchestration.

### Key Features

- **109+ Handlers** - Full CLI and API coverage of all system functions
- **373+ Tools** - Extensive tool library for file processing, analysis, and automation
- **932+ Skills** - Reusable workflows and templates
- **54 Protocol Workflows** - Pre-built process workflows
- **Knowledge Store** - Lessons, Facts, and Multi-Level Memory System
- **Agent CLI** - `bach agent start/stop/list` for direct agent control
- **Prompt System** - Central prompt management with board system and versioning
- **Install Security Gate** - Static pre-load scans block obvious code-injection patterns during `skills install`/`plugins load`; MCP setup validates allowlisted packages/configs fail-closed, plugin setup contracts now require explicit shell/desktop/MCP checks, and blocked local imports are quarantined
- **Manifest-first Plugins** - `bach plugins inspect` previews activation, provider/model, setup, and capability metadata without importing plugin runtime code
- **SharedMemory Bus** - Multi-agent coordination with conflict detection and decay
- **USMC Bridge** - United Shared Memory Communication for cross-agent communication
- **llmauto Chains** - Claude prompts as chain steps with `bach://` URL resolution
- **Chat Service** - Multi-backend Telegram bot (5 backends), Control API, Web Dashboard, cross-platform System Tray

## Installation

```bash
# Clone the repository
git clone https://github.com/ellmos-ai/bach.git
cd bach

# Install dependencies
pip install -r requirements.txt

# Optional: make `bach` and `from bach_api import ...` work directly from the repo root
pip install -e .

# Initialize BACH
python system/setup.py
```

## MCP Servers (Claude Code Integration)

BACH provides two MCP servers for integration with Claude Code, Cursor, and other IDEs:

```bash
# Install and configure MCP servers (recommended)
python system/bach.py setup mcp

# Or manually via npm:
npm install -g ellmos-codecommander-mcp ellmos-filecommander-mcp
```

- **[ellmos-codecommander-mcp](https://www.npmjs.com/package/ellmos-codecommander-mcp)** - Code analysis and refactoring tools
- **[ellmos-filecommander-mcp](https://www.npmjs.com/package/ellmos-filecommander-mcp)** - File management and batch operations

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
Structured memory system with Facts, Lessons, and automatic consolidation (5 memory types).

### 3. Agent Framework
Boss agents orchestrate experts for complex tasks. The Agent CLI allows direct starting, stopping, and listing of agents via `bach agent`.

<p align="center">
  <img src="sketch_bach_boss_agents.jpg" alt="BACH Boss Agents" width="600"><br>
  <i>The 5 Boss Agents: ati, officeassistant, finance-assistant, health-assistant, personal-assistant</i>
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
| 3 | **BACH** | The stream that unites everything -- 109+ handlers, 932+ skills, agents, GUI, bridge | [github.com/ellmos-ai/bach](https://github.com/ellmos-ai/bach) |

## Documentation

- **[Quickstart Guide](QUICKSTART.md)** - Get your first workflow running in 5 minutes
- **[User Manual](BACH_USER_MANUAL.md)** - Complete handbook
- **[Skills Catalog](SKILLS.md)** - All available skills
- **[Agents Catalog](AGENTS.md)** - All available agents and experts
- **[Workflows](WORKFLOWS.md)** - 54 protocol workflows
- **[SKILL.md](SKILL.md)** - LLM operating instructions (for Claude, Gemini, Ollama)

## See Also: OpenClaw

How does BACH compare to [OpenClaw](https://github.com/openclaw/openclaw), the popular open-source AI assistant (about 369k GitHub stars observed on 2026-05-07)?

| | **BACH** | **OpenClaw** |
|---|---|---|
| **Focus** | LLM Operating System -- deep autonomy, structured memory, multi-agent orchestration | Personal AI Assistant -- broad messaging gateway, voice, companion apps |
| **Tools/Skills** | 373+ tools, 932+ skills, 54 workflows (local, curated) | Community-driven skill/plugin ecosystem; recent releases emphasize manifest-first plugin metadata and install safety |
| **Memory** | 5 memory types with decay, conflict detection, consolidation (145+ DB tables) | Session/runtime workspace with bootstrap files such as `AGENTS.md`, `TOOLS.md`, `USER.md`, and related context files |
| **Agents** | Boss-Expert orchestration (5 boss agents), SharedMemory Bus | Agent runtime with multi-session/channel operation |
| **Messaging** | Telegram, Email, WhatsApp (Bridge System) | 20+ platforms (WhatsApp, Telegram, Slack, Discord, Signal, Teams, Matrix...) |
| **Interfaces** | CLI, Python API, PySide6 GUI, Web GUI, Telegram Bot, Web Chat, System Tray | CLI, WebChat, macOS/iOS/Android apps, Voice |
| **MCP** | Own MCP servers (FileCommander, CodeCommander) | Native MCP Registry |
| **Stack** | Python 3.10+, SQLite | TypeScript, Node.js 22+ |
| **License** | MIT | MIT |

**In short:** BACH goes deep (structured memory, autonomous agents, scheduler, 145+ DB tables). OpenClaw goes wide (20+ messengers, native apps, voice, massive community). Different philosophies, complementary strengths.

### Competitive Watch (2026-05-07)

As of May 7, 2026, OpenClaw's latest stable GitHub release is `2026.5.5`, published on May 6, 2026. For BACH, the relevant takeaways from the recent `2026.4.x` to `2026.5.5` release line are still not the broader channel surface, but control-plane hardening: workspace-scoped plugin metadata snapshot reuse on hot paths, install hints for missing official external plugins, collision-safe session-memory capture around repeated resets/new sessions, and stricter fail-closed config/setup behavior.

BACH should keep selectively adopting the parts that fit its operating-system model: manifest-first metadata, fail-closed setup checks, broader install scanning for skills/MCP/plugins, privacy-preserving secret/reference handling, active-run steering at safe checkpoints, memory/wiki provenance views, and low-cardinality telemetry. BACH now also validates malformed existing Claude config JSON before hook or MCP setup writes, which moves the setup-check track forward without pulling in OpenClaw's wider channel/runtime surface.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Support

- **Issues:** [GitHub Issues](https://github.com/ellmos-ai/bach/issues)
- **Discussions:** [GitHub Discussions](https://github.com/ellmos-ai/bach/discussions)

---

## Deutsche Version

BACH ist ein textbasiertes Betriebssystem, das Large Language Models (LLMs) befaehigt, eigenstaendig zu arbeiten, zu lernen und sich zu organisieren.

Die vollstaendige deutsche Dokumentation findest du hier: **[README.de.md](README.de.md)**

---

*ellmos BACH v3.8.0-sugar-of-babel - Text-Based Operating System for LLMs*

---

## Haftung / Liability

Dieses Projekt ist eine **unentgeltliche Open-Source-Schenkung** im Sinne der §§ 516 ff. BGB. Die Haftung des Urhebers ist gemäß **§ 521 BGB** auf **Vorsatz und grobe Fahrlässigkeit** beschränkt. Ergänzend gelten die Haftungsausschlüsse aus GPL-3.0 / MIT / Apache-2.0 §§ 15–16 (je nach gewählter Lizenz).

Nutzung auf eigenes Risiko. Keine Wartungszusage, keine Verfügbarkeitsgarantie, keine Gewähr für Fehlerfreiheit oder Eignung für einen bestimmten Zweck.

This project is an unpaid open-source donation. Liability is limited to intent and gross negligence (§ 521 German Civil Code). Use at your own risk. No warranty, no maintenance guarantee, no fitness-for-purpose assumed.

