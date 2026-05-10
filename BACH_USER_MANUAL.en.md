# BACH User Manual

**Version:** v3.9.1-tiramisu
**Generated:** 2026-03-12
**License:** MIT

---

BACH is a text-based operating system
for AI assistants. It connects humans and AI through a persistent
middleware with memory, tools, workflows and multi-LLM support.

This manual describes the installation, usage and extension of BACH.

---



---

## 2. Overview


# BACH - Text-Based Operating System for LLMs

**Version:** v3.9.1-tiramisu
**Status:** Production-Ready
**License:** MIT

## Overview

BACH is a text-based operating system that empowers Large Language Models (LLMs) to work, learn and organize independently. It provides a comprehensive infrastructure for task management, knowledge management, automation and LLM orchestration.

### Core Features

- **🤖 11 Boss Agents + 22 Experts** - Specialized agents for various task domains
- **🛠️ 550+ Tools** - Extensive tool library for file processing, analysis, automation (DB-registered)
- **📚 1870+ Skills** - Reusable workflows and templates (DB-registered)
- **🔄 58 Workflow Templates** - Pre-built process workflows
- **💾 Knowledge Store** - 138 Lessons + 248 Facts

## Installation

```bash
# Clone repository
git clone https://github.com/ellmos-ai/bach.git
cd bach

# Install dependencies
pip install -r requirements.txt

# Initialize BACH
python system/setup.py
```

## Quick Start

```bash
# Start BACH
python bach.py --startup

# Create a task
python bach.py task add "Analyze project structure"

# Retrieve knowledge
python bach.py wiki search "Task Management"

# Shut down BACH
python bach.py --shutdown
```

## Main Components

### 1. Task Management
Complete GTD system with prioritization, deadlines, tags and context tracking.

### 2. Knowledge System
Structured memory system with Facts, Lessons and automatic consolidation.

### 3. Agent Framework
Boss agents orchestrate experts for complex tasks (office, health, production, etc.).

### 4. Bridge System
Connector framework for external services (Telegram, Email, WhatsApp, etc.).

### 5. Automation
Scheduler for recurring tasks and event-based workflows.

## Documentation

- **[Getting Started](docs/getting-started.md)** - First steps with BACH
- **[API Reference](docs/reference/)** - Complete API documentation
- **[Skills Catalog](SKILLS.md)** - All available skills
- **[Agents Catalog](AGENTS.md)** - All available agents

## License

MIT License - see [LICENSE](LICENSE) for details.

## Support

- **Issues:** [GitHub Issues](https://github.com/ellmos-ai/bach/issues)
- **Discussions:** [GitHub Discussions](https://github.com/ellmos-ai/bach/discussions)

---

*Generated with `bach docs generate readme`*



---

## 3. Quick Start


# BACH Quickstart Guide

**Version:** unknown

## 🚀 Your First BACH Workflow in 5 Minutes

### 1. Installation (2 Minutes)

```bash
# Clone repository
git clone https://github.com/ellmos-ai/bach.git
cd bach

# Install dependencies
pip install -r requirements.txt

# Initialize BACH
python system/setup.py
```

### 2. First Steps (3 Minutes)

#### Start BACH

```bash
python bach.py --startup
```

#### Create and Manage Tasks

```bash
# Create a new task
python bach.py task add "First BACH experiment"

# Show tasks
python bach.py task list

# Complete a task
python bach.py task done 1
```

#### Store and Retrieve Knowledge

```bash
# Write a note to the wiki
python bach.py wiki write "bash-tricks" "Collect useful Bash commands"

# Search knowledge
python bach.py wiki search "bash"
```

#### Use the Memory System

```bash
# Store an important fact
python bach.py mem write fact "Project deadline: 2024-12-31"

# Retrieve facts
python bach.py mem read facts
```

#### Shut Down BACH

```bash
python bach.py --shutdown
```

---

## 📚 Most Important Commands

---

## 🎯 Next Steps

1. **Explore documentation**
   ```bash
   python bach.py docs list
   ```

2. **Get to know agents**
   ```bash
   python bach.py agent list
   ```

3. **Browse skills**
   ```bash
   cat SKILLS.md
   ```

4. **Create your own workflow**
   - See: [Skills/_workflows/](skills/_workflows/)
   - Examples for recurring tasks

---

## 🔧 Configuration

BACH adapts automatically, but you can customize:

- **Configure partner:** `python bach.py partner register claude`
- **Change settings:** `python bach.py config list`
- **Set up connector:** `python bach.py connector list`

---

## 📖 Further Documentation

- **[README.md](README.md)** - Complete overview
- **[API Reference](docs/reference/api.md)** - Programming interface
- **[Skills Catalog](SKILLS.md)** - All available skills
- **[Agents Catalog](AGENTS.md)** - All available agents

---

## 💡 Tips

1. **Contextual work:** BACH remembers what you're working on
2. **Automation:** Use workflows for recurring tasks
3. **Integration:** Connect BACH with Claude, Gemini or Ollama
4. **Backup:** Regularly run `python bach.py backup create`

---

## ❓ Getting Help

```bash
# General help
python bach.py --help

# Handler-specific help
python bach.py <handler> --help

# Search documentation
python bach.py docs search "keyword"
```

---

*Generated with `bach docs generate quickstart`*

**Good luck with BACH! 🎵**



---

## 4. Commands & Handlers


## Commands & Handlers

BACH has 97 handlers:

- **bach abo** -- Abo Handler - Subscription management (Expert Agent)
- **bach agents** -- Agents Handler - Agent management
- **bach apibook** -- Copyright (c) 2026 BACH Contributors
- **bach ati** -- ATI Handler - Advanced Tool Integration Agent
- **bach bach_paths** -- Copyright (c) 2026 BACH Contributors
- **bach backup** -- Backup Handler - Backup management
- **bach bericht** -- bericht.py - Foerderbericht handler
- **bach calendar_handler** -- Copyright (c) 2026 BACH Contributors
- **bach chain** -- Chain Handler - Execution of chained tool commands
- **bach claude_bridge** -- Copyright (c) 2026 BACH Contributors
- **bach connections** -- Connections Handler - Connections and Actors model
- **bach connector** -- Copyright (c) 2026 BACH Contributors
- **bach consolidation** -- Consolidation Handler - Memory consolidation
- **bach contact** -- ContactHandler - Contact management CLI
- **bach context** -- Context Handler - Context search and long-term memory
- **bach cookbook** -- Copyright (c) 2026 BACH Contributors
- **bach cv** -- Copyright (c) 2026 BACH Contributors
- **bach daemon** -- Daemon Handler - Daemon service management
- **bach daily_agent** -- Copyright (c) 2026 BACH Contributors
- **bach data_analysis** -- BACH Data Analysis Handler
- **bach db** -- DB Handler - Database operations (replaces Supabase MCP)
- **bach db_sync** -- Copyright (c) 2026 BACH Contributors
- **bach denkarium** -- Denkarium Handler - Logbook + thought collector
- **bach dist** -- BACH Distribution Handler
- **bach doc** -- Copyright (c) 2026 BACH Contributors
- **bach docs** -- Docs Handler - Main documentation (Markdown + Legacy)
- **bach docs_search** -- Copyright (c) 2026 BACH Contributors
- **bach email** -- Copyright (c) 2026 BACH Contributors
- **bach extensions** -- Copyright (c) 2026 BACH Contributors
- **bach folders** -- BACH Folders CLI Handler
- **bach fs** -- Copyright (c) 2026 BACH Contributors
- **bach gesundheit** -- GesundheitHandler - Health assistant CLI
- **bach gui** -- GUI Handler - Web server management
- **bach haushalt** -- HaushaltHandler - Household management CLI
- **bach health** -- Copyright (c) 2026 BACH Contributors
- **bach help** -- Help Handler - Shows help texts from .txt files
- **bach hooks** -- Copyright (c) 2026 BACH Contributors
- **bach inbox** -- BACH Inbox Handler v1.0
- **bach inject** -- Inject Handler - Injector control and task assignment
- **bach integration** -- Integration Handler - LLM partner bridge
- **bach lang** -- Copyright (c) 2026 BACH Contributors
- **bach lesson** -- Lesson Handler - Lessons Learned Management
- **bach logs** -- Logs Handler - Log management
- **bach maintain** -- BACH Maintain Handler
- **bach mem** -- Mem Handler - Memory management
- **bach memory** -- Memory Handler - DB-based memory management
- **bach messages** -- Messages Handler - Messaging system CLI
- **bach mount** -- BACH Mount Handler
- **bach multi_llm_protocol** -- Multi-LLM Protocol Handler - Coordination of parallel agents
- **bach news** -- Copyright (c) 2026 BACH Contributors
- **bach newspaper** -- Copyright (c) 2026 BACH Contributors
- **bach notify** -- Copyright (c) 2026 BACH Contributors
- **bach obsidian** -- Copyright (c) 2026 BACH Contributors
- **bach ollama** -- Ollama Handler - Local AI interaction
- **bach partner** -- Partner Handler - Partner management
- **bach partner_config_manager** -- PartnerConfigManager - LLM partner configuration
- **bach path** -- Copyright (c) 2026 BACH Contributors
- **bach pipeline** -- Pipeline handler for BACH
- **bach plugins** -- Copyright (c) 2026 BACH Contributors
- **bach press** -- Copyright (c) 2026 BACH Contributors
- **bach profile** -- Copyright (c) 2026 BACH Contributors
- **bach profiler** -- Copyright (c) 2026 BACH Contributors
- **bach recurring** -- BACH Recurring Tasks Handler v1.0.0
- **bach reflection** -- Copyright (c) 2026 BACH Contributors
- **bach restore** -- File Restore Handler (SQ020/HQ6)
- **bach routine** -- RoutineHandler - Household Routine Management CLI
- **bach sandbox** -- Copyright (c) 2026 BACH Contributors
- **bach scan** -- Scan Handler - Scanner management
- **bach seal** -- Kernel Seal Handler (SQ021)
- **bach search** -- SearchHandler - Unified Search CLI for BACH
- **bach secrets** -- secrets_handler.py — Secrets Management Handler (SQ076)
- **bach session** -- SessionHandler - Session management for BACH
- **bach settings** -- Settings Handler - Manage system settings
- **bach shared_memory** -- Shared Memory Handler - Multi-agent memory management (SQ043)
- **bach shutdown** -- Shutdown Handler - End session (DB-based)
- **bach skills** -- Skills Handler - Skill management (v2.0 architecture)
- **bach smarthome** -- Copyright (c) 2026 BACH Contributors
- **bach snapshot** -- Snapshot Handler - Session snapshot management
- **bach sources** -- Sources Handler - Context sources system
- **bach startup** -- Startup Handler - Start session (DB-based)
- **bach status** -- Status Handler - Quick system overview
- **bach steuer** -- Steuer Handler - Tax receipt management
- **bach sync** -- Sync Handler - Filesystem to DB synchronization
- **bach task** -- TaskHandler - Task management for BACH
- **bach test** -- BACH Test Handler
- **bach time** -- Time Handler - CLI for time system
- **bach tokens** -- Tokens Handler - Token tracking
- **bach tools** -- Tools Handler - Tool management
- **bach trash** -- BACH Trash Handler
- **bach tuev** -- TUeV Handler - Workflow quality assurance
- **bach update** -- Copyright (c) 2026 BACH Contributors
- **bach upgrade** -- Copyright (c) 2026 BACH Contributors
- **bach versicherung** -- Copyright (c) 2026 BACH Contributors
- **bach watcher** -- Copyright (c) 2026 BACH Contributors
- **bach web_parse** -- Copyright (c) 2026 BACH Contributors
- **bach web_scrape** -- Copyright (c) 2026 BACH Contributors
- **bach wiki** -- Wiki Handler - Display wiki articles from wiki/


---

## 5. Skills & Protocols


# BACH Skills Catalog

**Count:** 940 Skills
**Generated:** Automatically from the skills database

## Overview

This catalog lists all available skills, grouped by type.

### Skills by Type

- **agent**: 24 Skills
- **definition**: 2 Skills
- **expert**: 28 Skills
- **extension**: 38 Skills
- **file**: 711 Skills
- **os**: 1 Skills
- **profile**: 9 Skills
- **protocol**: 25 Skills
- **service**: 48 Skills
- **skill**: 46 Skills
- **template**: 8 Skills

---

## AGENT (24)

### `agent/README`

### `agent/ati/ATI`
**Category:** ati
>

### `agent/ati/ATI_PROJECT_BOOTSTRAPPING`
**Category:** ati
>

### `agent/ati/README`
**Category:** ati

### `agent/ati/_policies/POLICIES_README`
**Category:** ati

### `agent/ati/modules/README`
**Category:** ati

### `agent/ati/prompt_templates/analysis_prompt`
**Category:** ati

### `agent/ati/prompt_templates/review_prompt`
**Category:** ati

### `agent/ati/prompt_templates/task_prompt`
**Category:** ati

### `agent/ati/session/DEPRECATED`
**Category:** ati

### `agent/bewerbungsexperte`
>

### `agent/bueroassistent`
>

### `agent/entwickler`
>

### `agent/förderplaner`
>

### `agent/gesundheitsassistent`
>

### `agent/haushaltsmanagement`

### `agent/persoenlicher-assistent`
>

### `agent/production`
>

### `agent/psycho-berater`

### `agent/research`

### `agent/steuer-agent`
>

### `agent/test-agent`

### `agent/versicherungen`
>

### `test-agent-x`
BACH agent: test-agent-x

---

## DEFINITION (2)

### `SKILL_AGENT_OS_DEFINITIONS`
**Category:** core
Core skill definition: SKILL_AGENT_OS_DEFINITIONS

### `SKILL_ANALYSE`
**Category:** core
Core skill definition: SKILL_ANALYSE

---

## EXPERT (28)

### `aboservice`
**Category:** _experts
aboservice

### `data-analysis`
**Category:** _experts
data-analysis

### `expert/_mediaproduction/musik`
**Category:** _mediaproduction

### `expert/_mediaproduction/podcast`
**Category:** _mediaproduction

### `expert/_mediaproduction/video`
**Category:** _mediaproduction

### `expert/_textproduction/pr`
**Category:** _textproduction

### `expert/_textproduction/storys`
**Category:** _textproduction

### `expert/_textproduction/text`
**Category:** _textproduction

### `expert/aboservice/CONCEPT`
**Category:** aboservice

### `expert/aboservice/README`
**Category:** aboservice

### `expert/data-analysis/CONCEPT`
**Category:** data-analysis

### `expert/financial_mail/CONCEPT`
**Category:** financial_mail

### `expert/foerderplaner/foerderplaner`
**Category:** foerderplaner
>

### `expert/gesundheitsverwalter/CONCEPT`
**Category:** gesundheitsverwalter

### `expert/haushaltsmanagement/CONCEPT`
**Category:** haushaltsmanagement

### `expert/haushaltsmanagement/aufgaben`
**Category:** haushaltsmanagement

### `expert/mr_tiktak/CONCEPT`
**Category:** mr_tiktak

### `expert/psycho-berater/CONCEPT`
**Category:** psycho-berater

### `expert/psycho-berater/rolle`
**Category:** psycho-berater

### `expert/report_generator/report_generator`
**Category:** report_generator
>

### `expert/steuer/steuer-agent`
**Category:** steuer
>

### `expert/wikiquizzer/CONCEPT`
**Category:** wikiquizzer

### `financial_mail`
**Category:** _experts
financial_mail

### `gesundheitsverwalter`
**Category:** _experts
gesundheitsverwalter

### `health_import`
**Category:** _experts
health_import

### `mr_tiktak`
**Category:** _experts
mr_tiktak

### `test-tool-demo`

*... (3483 more lines, see SKILLS.md)*


---

## 6. Agents & Experts


# BACH Agents & Experts

**Generated:** 2026-02-22 13:53
**Source:** bach.db (bach_agents, bach_experts)
**Generator:** `bach export mirrors` or `python tools/agents_export.py`

---

## Boss Agents (Orchestrators)

Boss agents orchestrate complex workflows and delegate to experts.

### Developer Agent (ATI)
- **Name:** ati
- **Type:** Expert
- **Category:** None
- **Path:** `None`
- **Status:** active
- **Version:** 1.2.0
- **Description:** Specialized in tool monitoring and software development.

### Office Assistant (Bueroassistent)
- **Name:** bueroassistent
- **Type:** boss
- **Category:** professional
- **Path:** `agents/bueroassistent.txt`
- **Status:** active
- **Version:** 1.0.0
- **Description:** Taxes, funding planning, documentation

### Financial Assistant (Finanzassistent)
- **Name:** finanz-assistent
- **Type:** assistant
- **Category:** professional
- **Path:** `None`
- **Status:** active
- **Version:** 1.0.0
- **Description:** Financial mails, subscriptions, insurance

### Health Assistant (Gesundheitsassistent)
- **Name:** gesundheitsassistent
- **Type:** boss
- **Category:** private
- **Path:** `agents/gesundheitsassistent.txt`
- **Status:** active
- **Version:** 1.0.0
- **Description:** Medical documentation and health management

### Personal Assistant (Persoenlicher Assistent)
- **Name:** persoenlicher-assistent
- **Type:** boss
- **Category:** private
- **Path:** `agents/persoenlicher-assistent.txt`
- **Status:** active
- **Version:** 1.0.0
- **Description:** Appointment management, research, organization

---

## Experts (Specialized Executors)

Experts carry out specific tasks and are delegated to by boss agents.

### Subscription Service (Abo-Service)
- **Name:** aboservice
- **Domain:** finance
- **Path:** `None`
- **Status:** active
- **Version:** 1.0.0

### Application Expert (Bewerbungsexperte)
- **Name:** bewerbungsexperte
- **Domain:** career
- **Path:** `None`
- **Status:** active
- **Version:** 1.0.0

### Data Analysis (Daten-Analyse)
- **Name:** data-analysis
- **Domain:** analytics
- **Path:** `None`
- **Status:** active
- **Version:** 1.0.0

### Decision Briefing
- **Name:** decision-briefing
- **Domain:** None
- **Path:** `agents\_experts\decision-briefing\CONCEPT.md`
- **Status:** active
- **Version:** 1.0.0
- **Description:** The Decision-Briefing expert is the central system for pending decisions and user tasks in BACH. It:

### Financial Mails (Finanz-Mails)
- **Name:** financial_mail
- **Domain:** finance
- **Path:** `None`
- **Status:** active
- **Version:** 1.0.0

### Funding Planner (Foerderplaner)
- **Name:** foerderplaner
- **Domain:** education
- **Path:** `agents/_experts/foerderplaner/`
- **Status:** active
- **Version:** 1.0.0
- **Description:** ICF funding planning, material research

### Health Manager (Gesundheitsverwalter)
- **Name:** gesundheitsverwalter
- **Domain:** health
- **Path:** `agents/_experts/gesundheitsverwalter/`
- **Status:** active
- **Version:** 1.0.0
- **Description:** Medical reports, lab values, medications

### Household Management (Haushaltsmanagement)
- **Name:** haushaltsmanagement
- **Domain:** household
- **Path:** `agents/_experts/haushaltsmanagement/`
- **Status:** active
- **Version:** 1.0.0
- **Description:** Household ledger, inventory, shopping lists

### Health Import
- **Name:** health_import
- **Domain:** health
- **Path:** `None`
- **Status:** active
- **Version:** 1.0.0

### Schedule Optimizer (Termin-Optimierer)
- **Name:** mr_tiktak
- **Domain:** time
- **Path:** `None`
- **Status:** active
- **Version:** 1.0.0

### Psychological Counselor (Psycho-Berater)
- **Name:** psycho-berater
- **Domain:** psychology
- **Path:** `agents/_experts/psycho-berater/`
- **Status:** active
- **Version:** 1.0.0
- **Description:** Therapeutic conversations, session protocols

### Report Generator (Bericht-Generator)
- **Name:** report_generator
- **Domain:** documentation
- **Path:** `None`
- **Status:** active
- **Version:** 1.0.0

### Tax Expert (Steuer-Experte)
- **Name:** steuer-agent
- **Domain:** finance
- **Path:** `agents/_experts/steuer/`
- **Status:** active
- **Version:** 1.0.0
- **Description:** Tax receipts, deductible expenses

### Transcription Service (Transkriptions-Service)
- **Name:** transkriptions-service
- **Domain:** media
- **Path:** `agents/_experts/transkriptions-service/`
- **Status:** active
- **Version:** 1.0.0
- **Description:** Transcribe audio files and conversations, speaker recognition, cleanup, export

### Wiki Learning Aid (Wiki-Lernhilfe)
- **Name:** wikiquizzer
- **Domain:** education
- **Path:** `None`
- **Status:** active
- **Version:** 1.0.0

---

## Status Categories

- **FUNCTIONAL:** Fully functional, production-ready
- **PARTIAL:** Basic functions present, but incomplete
- **SKELETON:** Structure present, but implementation largely missing

---

## Character Model (ENT-41)

Each boss agent has a `## Charakter` section in its SKILL.md:
- **Tone:** How does the agent communicate?
- **Focus:** What does it orient itself toward?
- **Stance:** What values does it represent?

See: BACH_Dev/MASTERPLAN_PENDING.txt → SQ049 Agent Audit & Upgrade

---

## Working Principles

All agents follow the global working principles from Root-SKILL.md:
- Distinguish what is own, what is foreign
- Text is truth
- Read first, then modify
- Do not create duplicates
- React flexibly to user corrections

---

## Usage

```bash
# Start boss agent (with partner delegation)
bach agent start bueroassistent --partner=claude-code

# Call expert directly (if permitted)
bach expert run bewerbungsexperte --task="Cover letter for position X"

# Show agent list
bach agent list

# Show expert list
bach expert list
```

---

## File Synchronization

This file is automatically generated from:
- `bach_agents` (table for boss agents)
- `bach_experts` (table for experts)

**Trigger:**
- `bach --shutdown` (via finalize_on_idle)
- `bach export mirrors` (manual)

**dist_type:** 1 (TEMPLATE) - resettable, but customizable

---

## See Also

- **PARTNERS.md** - LLM partners and delegation
- **USECASES.md** - Use cases
- **WORKFLOWS.md** - 25 Protocol skills as index
- **CHAINS.md** - Toolchains



---

## 7. LLM Partners


# BACH Partners

Automatically generated from the database (delegation_rules, partner_recognition, interaction_protocols).
Last update: 2026-02-22 13:53

## Delegation Rules

**Total:** 4 rules

### Zone: zone_1

- **zone_1_full_access** ⭐⭐⭐
  - Full access: All partners available, optimal quality
  - Preferred: Claude

### Zone: zone_2

- **zone_2_moderate** ⭐⭐⭐
  - Moderate economy: Prefer cost-effective partners
  - Preferred: Ollama

### Zone: zone_3

- **zone_3_conservative** ⭐⭐
  - Conservative: Only local partners (Ollama) preferred
  - Preferred: Ollama

### Zone: zone_4

- **zone_4_emergency** ⭐
  - Emergency: Only escalation or local processing
  - Preferred: Human

## Partner Recognition

**Total:** 10 Partners

- **Claude** (api) ✓
  - Zone: zone_1 | Cost: $$$ | Priority: 100
  - Capabilities: ["general", "coding", "analysis", "writing"]

- **Ollama** (local) ✓
  - Zone: zone_3 | Cost: $ | Priority: 80
  - Capabilities: ["coding", "general"]

- **Gemini** (api) ✓
  - Zone: zone_1 | Cost: $$ | Priority: 70
  - Capabilities: ["general", "research", "coding"]

- **Copilot** (api) ✓
  - Zone: zone_2 | Cost: $$ | Priority: 60
  - Capabilities: ["coding", "completion"]

- **ChatGPT** (api) ✓
  - Zone: zone_1 | Cost: $$$ | Priority: 50
  - Capabilities: ["general", "writing"]

- **Perplexity** (api) ✓
  - Zone: zone_2 | Cost: $$ | Priority: 40
  - Capabilities: ["research", "search"]

- **Mistral** (api) ✓
  - Zone: zone_2 | Cost: $$ | Priority: 30
  - Capabilities: ["coding", "general"]

- **Anthropic-Local** (local) ✗
  - Zone: zone_4 | Cost: $ | Priority: 20
  - Capabilities: ["general"]

- **Custom-Agent** (local) ✗
  - Zone: zone_4 | Cost: $ | Priority: 10
  - Capabilities: ["custom"]

- **Human** (human) ✓
  - Zone: zone_4 | Cost: $ | Priority: 5
  - Capabilities: ["review", "decision", "escalation"]

## Interaction Protocols

**Total:** 10 Protocols

### confirmation

#### receipt

Acknowledgment of receipt

- **Timeout:** 60s | **Retries:** 3 | **Priority:** 50

### delegation

#### task_delegation

Delegate task to partner

- **Timeout:** 300s | **Retries:** 3 | **Priority:** 90
- **Applicable Partners:** ["Claude", "Ollama", "Copilot"]

### discovery

#### compare

Comparison: What does the partner have that I don't

- **Timeout:** 60s | **Retries:** 3 | **Priority:** 50

#### handshake

Mutual recognition between instances

- **Timeout:** 60s | **Retries:** 3 | **Priority:** 50

### escalation

#### human_escalation

Escalation to user

- **Timeout:** 60s | **Retries:** 3 | **Priority:** 50
- **Applicable Partners:** ["Human"]

### query

#### simple_query

Simple question-answer

- **Timeout:** 30s | **Retries:** 2 | **Priority:** 100
- **Applicable Partners:** ["Claude", "Ollama", "Gemini", "ChatGPT", "Mistral"]

#### code_review

Request code review

- **Timeout:** 120s | **Retries:** 2 | **Priority:** 80
- **Applicable Partners:** ["Claude", "Copilot", "ChatGPT"]

#### research_query

Research request

- **Timeout:** 180s | **Retries:** 3 | **Priority:** 70
- **Applicable Partners:** ["Perplexity", "Claude", "Gemini"]

### transfer

#### request

Import request to partner

- **Timeout:** 60s | **Retries:** 3 | **Priority:** 50

#### transfer

Data transfer between partners

- **Timeout:** 60s | **Retries:** 3 | **Priority:** 50



---

## 8. Workflows


# BACH Workflows

Automatically generated from the filesystem (skills/workflows/).
Last update: 2026-02-22 13:53

**Total:** 29 Workflows

## Analysis

### Workflow: Document Requirements Analysis

**Version:** 1.2.0

**File:** `skills/workflows/analysis\docs-analyse.md`

### Workflow: Help-Expert-Review

**Version:** 1.4.0

**File:** `skills/workflows/analysis\help-expert-review.md`

### Workflow: Help-Forensik

**Version:** 1.0.0

**File:** `skills/workflows/analysis\help-forensic.md`

### Skill Coverage Analysis Workflow

**Purpose:** Systematic analysis of BACH skill coverage compared to industry standards.

**File:** `skills/workflows/analysis\skill-abdeckungsanalyse.md`

### Workflow: Wiki Authors

**Version:** 2.0.0

**File:** `skills/workflows/analysis\wiki-author.md`

## Dev

### Bugfix Protocol for Python/PyQt6 Projects

> **Goal:** Systematic approach to bugs to save time and quickly identify known issues.

**File:** `skills/workflows/dev\bugfix-protokoll.md`

### CLI Change Checklist

**Version:** 1.0

**File:** `skills/workflows/dev\cli-aenderung-checkliste.md`

### BACH Development Cycle (Dev Cycle)

> **Goal:** Structured process from feature request to validated system.

**File:** `skills/workflows/dev\dev-zyklus.md`

### Workflow: File Renaming with Wrapper (Evolutionary Migration)

**Version:** 1.0.0

**File:** `skills/workflows/dev\migrate-rename.md`

### MCP Server Release Protocol (NPM + GitHub)

> **Goal:** Structured process for publishing BACH MCP servers on GitHub and NPM.

**File:** `skills/workflows/dev\npm-mcp-publish.md`

### Workflow: Folder Flattening

Goal: Transform nested folder structures into a flat, machine-readable structure.

**File:** `skills/workflows/dev\ordner-flattening.md`

### Self-Extension Workflow

> **Goal:** BACH autonomous self-extension through AI partners (Claude, Gemini, etc.)

**File:** `skills/workflows/dev\self-extension.md`

### Service/Agent Validator Workflow

Quality assurance for new services, agents and experts in the BACH system.

**File:** `skills/workflows/dev\service-agent-validator.md`

## Integration

### Agent/Skill Finder Workflow

Find the right agent, expert or skill for a user request.

**File:** `skills/workflows/integration\agent-skill-finder.md`

### Gemini Delegation Workflow

> **Delegate resource-intensive tasks to Google Gemini**

**File:** `skills/workflows/integration\gemini-delegation.md`

### Google Drive Delegation Workflow - SKILL v1.0

Multi-AI collaboration via Google Drive as shared workspace.

**File:** `skills/workflows/integration\google-drive.md`

## System

### Claude-Bach Integration

name: claude-bach-vernetzung

**File:** `skills/workflows/system\claude-bach-vernetzung.md`

### Cross-System-Sync

name: cross-system-sync

**File:** `skills/workflows/system\cross-system-sync.md`

### System Integration Analysis: Integration & Consistency

**Version:** 1.0

**File:** `skills/workflows/system\system-anschlussanalyse.md`

### System Cleanup: Maintenance and Archiving

**Version:** 1.0

**File:** `skills/workflows/system\system-aufraeumen.md`

### System Mapping: Cartography and Feature Discovery

**Version:** 1.0

**File:** `skills/workflows/system\system-mapping.md`

### System Synopsis: Comparative Analysis

**Version:** 1.0

**File:** `skills/workflows/system\system-synopse.md`

### System Testing: B/O/E Tests

**Version:** 1.0

**File:** `skills/workflows/system\system-testverfahren.md`

### Desire Path Analysis & Swarm Operations (Elephant Path / Swarm Ops)

**Version:** 2.0

**File:** `skills/workflows/system\trampelpfadanalyse.md`

## Workflows

### CV Generation

name: cv-generierung

**File:** `skills/workflows/cv-generierung.md`

### 🧠 Model-Switching Strategy V2

> **Version:** 2.0.0

**File:** `skills/workflows/ing-strategie.md`

### Standard Onboarding Procedure for New Software Projects

**Version:** 1.0

**File:** `skills/workflows/projekt-aufnahme.md`

### Synthesis Workflow: New System from Best-of

**Version:** 1.0

**File:** `skills/workflows/synthese.md`

### Batch Translation with Haiku (EN/DE/Multi-Language)

> **Goal:** Systematic translation of BACH components (help, wiki, skills) into multiple languages using Claude Haiku (cost-effective, fast).

**File:** `skills/workflows/translate_haiku.md`



---

## 9. Use Cases


# BACH Use Cases

Automatically generated from the database (usecases).
Last update: 2026-02-22 13:53

**Total:** 50 Use Cases

## ASSISTANT

### ○ Maintain character sheet about user ⭐⭐⭐⭐

Learning preferences, peculiarities, needs of the user documented and considered.

**Last Test:** 2026-02-21 22:36:11 | **Score:** 80/100

### ○ Create dossier or briefing ⭐⭐⭐⭐

Before meetings: Research person/topic and prepare in structured format.

**Last Test:** 2026-02-21 22:36:11 | **Score:** 80/100

### ○ Manage calendar ⭐⭐⭐⭐

Manage and keep up-to-date appointments, tasks, locations, people, bookings.

**Last Test:** 2026-02-21 22:36:11 | **Score:** 80/100

### ○ Morning daily briefing ⭐⭐⭐⭐

Present day's appointments, open topics, important briefings for special appointments.

**Last Test:** 2026-02-21 22:36:11 | **Score:** 80/100

### ○ Search location restaurant hotel ⭐⭐

Find locations with contact details and opening hours. Suggest suitable locations.

**Last Test:** 2026-02-21 22:36:11 | **Score:** 50/100

### ○ Plan travel route ⭐⭐

Search and compile train connections, hotels. Provide booking links.

**Last Test:** 2026-02-21 22:36:11 | **Score:** 50/100

## CARE MODULE

### ○ Manage doctor appointments and reminders ⭐⭐⭐⭐

Store doctor appointments and retrieve on request. Reminder function.

**Last Test:** 2026-02-21 22:36:11 | **Score:** 80/100

### ○ Keep medication plan up to date ⭐⭐⭐⭐

Current medication plan from reports + user correction. Name, active ingredient, dosage, time of day, effect.

**Last Test:** 2026-02-21 22:36:11 | **Score:** 80/100

### ○ Manage preventive care plan ⭐⭐⭐⭐

Track preventive examinations with status: skin screening, dentist, vaccinations, blood tests, check-up.

**Last Test:** 2026-02-21 22:36:11 | **Score:** 80/100

## DATA MODULE

### ○ Manage diagnoses and hypotheses ⭐⭐⭐⭐

Categorize diagnoses: confirmed/suspected/hypothesis/disproven with evidence. Maintain evidence collections.

**Last Test:** 2026-02-21 22:36:11 | **Score:** 80/100

### ○ Track medication history ⭐⭐⭐⭐

Track medications: start, end, dosage, reason, effect, side effects over time.

**Last Test:** 2026-02-21 22:36:11 | **Score:** 80/100

### ○ Create examination plan ⭐⭐⭐⭐

Derive pending/recommended diagnostics from diagnoses and suspected diagnoses. Prioritized by importance.

**Last Test:** 2026-02-21 22:36:11 | **Score:** 80/100

### ○ Analyze symptom coverage ⭐⭐

Which diagnoses explain which symptoms? Overlaps? Remaining symptoms without explanation? Percentage.

**Last Test:** 2026-02-21 22:36:11 | **Score:** 50/100

### ○ Document symptom progression ⭐⭐

Track symptoms over time: onset, disappearance, improvement, deterioration. Active/inactive status.

**Last Test:** 2026-02-21 22:36:11 | **Score:** 50/100

## DOCUMENT MODULE

### ○ Update medical document directory ⭐⭐⭐⭐

Detect new PDFs, categorize (knowledge/patient), add to directory. Check if documents have been added or deleted.

**Last Test:** 2026-02-21 22:36:11 | **Score:** 80/100

## FINANCE

### ○ Plan recurring annual costs ⭐⭐⭐⭐

Monthly overview of irregular annual costs (vehicle, inspection, university, insurance, broadcasting fee). Source: Recurring Costs Overview.docx

**Last Test:** 2026-02-21 22:36:11 | **Score:** 80/100

## HEALTH

### ○ Maintain medication overview ⭐⭐⭐⭐

Current medication with dosage, intake time, effect. Extracted from medical reports. Source: Medication Overview.pdf

**Last Test:** 2026-02-21 22:36:11 | **Score:** 80/100

## HOUSEHOLD

### ○ Manage household tasks by schedule ⭐⭐⭐⭐⭐

Daily/weekly/monthly/quarterly/semi-annually/annually - track tasks with last completed status. Source: Household tasks from daily to annually.docx

**Last Test:** 2026-02-06 08:13:06 | **Score:** 100/100

## CAREER

### ○ Track career goals and core areas ⭐⭐⭐⭐

3 core areas: Learning therapy practice, special education teaching, software side business. Track qualification paths. Source: Career Goals Core Areas.docx

**Last Test:** 2026-02-21 22:36:11 | **Score:** 80/100

### ○ Document continuing education and self-study ⭐⭐⭐⭐

Record further training, certificates, courses with date and status. Source: Documentation Continuing Education.docx

**Last Test:** 2026-02-21 22:36:11 | **Score:** 80/100

## SELF-MANAGEMENT

### ○ Apply ADHD strategies ⭐⭐⭐⭐⭐

Reusable lists, body doubling, shorten planning phase. Source: ADHD strategies.docx

**Last Test:** 2026-02-06T14:53:52.135262 | **Score:** 100/100

### ○ Check life areas balance ⭐⭐⭐⭐

7 life areas with activity pool. Rotation instead of overload. Work vs hobby assignment. Source: Life Areas Overview.docx

**Last Test:** 2026-02-21 22:36:11 | **Score:** 80/100

## SOFTWARE

### ○ Create FormBuilder forms ⭐⭐⭐⭐⭐

Create and export forms with A3 FormBuilder.

**Last Test:** 2026-02-06 08:13:06 | **Score:** 100/100

### ○ Read HausLagerist database ⭐⭐⭐⭐⭐

Read database hauslagerist.db: household items, storage location, inventory.

**Last Test:** 2026-02-06 08:13:06 | **Score:** 100/100

### ○ Use MediPlaner database ⭐⭐⭐⭐⭐

Read mediplaner.db: medication plans, intake times, dosages.

**Last Test:** 2026-02-06 08:13:06 | **Score:** 100/100

### ○ Index ProFiler knowledge ⭐⭐⭐⭐⭐

Fully integrate ProFiler: scan PDFs, OCR, knowledge indexing, create and use databases.

**Last Test:** 2026-02-06 08:13:06 | **Score:** 100/100

### ○ Run RPG-Agent game mastering ⭐⭐⭐⭐⭐

Integrate RPG: Function as game master in role-playing games, manage worlds, run sessions.

**Last Test:** 2026-02-06 08:13:06 | **Score:** 100/100

### ○ Use MasterRoutine database ⭐⭐⭐⭐

Read routine_master.db: routines, tasks, schedule-based reminders.

**Last Test:** 2026-02-21 22:36:11 | **Score:** 80/100

### ○ Create and export MetaWiki ⭐⭐⭐

Create MetaWiki structure (hierarchical Markdown wikis) and export as function to BACH.

**Last Test:** 2026-02-21 22:36:11 | **Score:** 70/100

### ○ Integrate FinancialProof dashboard ⭐⭐

Provide financial analysis app with AI deep analysis (ARIMA, Monte Carlo, ML) as dashboard in financial agent.

**Last Test:** 2026-02-21 22:36:11 | **Score:** 50/100

### ○ Use MediaBrain database ⭐⭐

Read media_brain.db: media collection, categories, metadata.

**Last Test:** 2026-02-21 22:36:11 | **Score:** 50/100

## THERAPY

### ○ Create worksheets for autism support ⭐⭐⭐

Research from knowledge database, generate specific worksheets and exercises based on client description.

**Last Test:** 2026-02-21 22:36:11 | **Score:** 70/100

### ○ Create worksheets for psychological counseling ⭐⭐⭐

Use knowledge from database for counseling, create exercises and worksheets.

**Last Test:** 2026-02-21 22:36:11 | **Score:** 70/100

## KNOWLEDGE

### ○ Navigate and use knowledge database ⭐⭐⭐⭐

Retrieve, structure, link knowledge from knowledge database folder.

**Last Test:** 2026-02-21 22:36:11 | **Score:** 80/100

## docs-analyse

### ○ Create ASCII resume ⭐⭐⭐⭐⭐

Claude create me a current text-based ASCII resume from my employer documents

**Last Test:** 2026-02-06 08:13:06 | **Score:** 100/100

### ○ Export doctor contacts ⭐⭐⭐⭐⭐

Claude give me a clear text excerpt of all phone numbers and email addresses of my stored doctors

**Last Test:** 2026-02-06T14:54:07.470400 | **Score:** 100/100

### ○ Search for important document ⭐⭐⭐⭐⭐

Claude find me the document that contains my tax identification number

**Last Test:** 2026-02-06 08:13:06 | **Score:** 100/100

### ○ Summarize medical reports ⭐⭐⭐⭐

Claude read all reports on the topic thyroid. Give me a directory (name, specialty, doctor, contact, findings) and summarize

**Last Test:** 2026-02-21 22:36:11 | **Score:** 80/100

### ○ List my insurance policies ⭐⭐⭐⭐

List of my insurance policies with policy number, tariff, costs, contact, coverage analysis

**Last Test:** 2026-02-21 22:53:52 | **Score:** 80/100

### ○ Query insurance directory ⭐⭐⭐⭐

What types of insurance exist? Rules for when they make sense? Table with overview

**Last Test:** 2026-02-21 22:53:52 | **Score:** 80/100

### ○ Insurance consultation ⭐⭐⭐⭐

Claude should I take out a specific insurance? Analysis based on existing policies

**Last Test:** 2026-02-21 22:53:52 | **Score:** 80/100

## ordner-flattening

### ○ Office Lens auto-categorization ⭐⭐⭐⭐

Automatically scan, categorize and distribute newly photographed and uploaded documents to filesystem or user in BACH

**Last Test:** 2026-02-21 22:36:11 | **Score:** 80/100

## reflection_status

### ○ Reflection Status

bach reflection status shows performance report

**Last Test:** 2026-02-21T05:53:30.950266 | **Score:** 0/100

## system-synopse

### ○ Subscription reconciliation with mails ⭐⭐⭐⭐⭐

Compare recognized financial mails with stored subscriptions. Show differences

**Last Test:** 2026-02-06 08:13:06 | **Score:** 100/100

### ○ Change subscription status ⭐⭐⭐⭐⭐

Claude set subscription 1,3,5 to inactive and 2 to active. Show expected monthly costs

**Last Test:** 2026-02-06 08:13:06 | **Score:** 100/100

### ○ Show subscription overview ⭐⭐⭐⭐⭐

Claude give me an overview of my subscriptions and recurring costs with current status

**Last Test:** 2026-02-06 08:13:06 | **Score:** 100/100

### ○ Irregular costs preview ⭐⭐

Financial agent please give me an overview of what irregular costs might I expect next month?

**Last Test:** 2026-02-06 08:13:06 | **Score:** 50/100

## system-testverfahren

### ○ Mark tasks as completed ⭐⭐⭐⭐⭐

Task 1, 4, 5 I have completed - update the database

**Last Test:** 2026-02-06 08:13:06 | **Score:** 100/100

### ○ Query household routine ⭐⭐⭐⭐⭐

Claude do I need to change my bed sheets? (Routine check based on schedule)

**Last Test:** 2026-02-06 08:13:06 | **Score:** 100/100

### ○ Query weekly tasks ⭐⭐⭐⭐⭐

Claude which tasks are due this week? (from routines: daily, weekly, monthly)

**Last Test:** 2026-02-06 08:13:06 | **Score:** 100/100



---

## 10. Security


# Security Policy

## Reporting a Vulnerability

If you find a security vulnerability in BACH, please report it responsibly:

1. **Do NOT open a public issue**
2. Email: [tbd@example.com] or use GitHub's private vulnerability reporting
3. Include: description, steps to reproduce, potential impact

## Scope

BACH runs locally. The main attack surface is:
- Bridge/Connector endpoints (Telegram, Discord, etc.)
- GUI web server (FastAPI, localhost only by default)
- File system access (bach.db, user data)
- MCP server (localhost only)

## Response

As a solo project, response times may vary. Critical issues will be
prioritized. Please allow reasonable time before public disclosure.



---

## 11. Contributing


# Contributing to BACH

BACH is maintained as part of the ellmos project family. Contributions are welcome
but there's no guarantee of response time.

## How to contribute

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Run tests (`bach test` or `python -m pytest`)
5. Commit with clear message
6. Open a Pull Request

## Guidelines

- Keep changes focused (one feature/fix per PR)
- Follow existing code style (Python, PEP8-ish)
- Add/update tests if applicable
- Update docs if behavior changes
- Don't break existing functionality

## What gets merged?

- Bug fixes: Almost always welcome
- New features: Open an Issue first to discuss
- Refactoring: Only if it clearly improves something
- New agents/skills: Very welcome as separate modules

## What won't get merged?

- Breaking changes without discussion
- Large refactors without prior agreement
- Features that add complexity without clear benefit
- Changes to CORE (dist_type=2) without good reason

---

> **BACH is a personal project.** It's maintained by one person in their free time.
> There's no support team, no SLA, no guaranteed response time.
> If you like it, use it. If you want to improve it, contribute.
> If it doesn't fit your needs, fork it and make it yours.



---

## 12. Changelog


# BACH Changelog

**Current Version:** unknown
**Generated:** Automatically from dist_file_versions (delta mode)

## Overview

This changelog shows **changes** between versions (delta), not all files.

### Legend

- 🔴 **CORE** (dist_type=2) - Kernel files, critical for BACH
- 🟡 **TEMPLATE** (dist_type=1) - Customizable templates
- ⚪ **USER** (dist_type=0) - User data

---

## Version History

### v3.1.6

**Changes:** 234 files (233 changed, 1 added, 0 removed)

#### Changed (233):

- ⚪ `AGENTS.md` (60d0df76) ← (3f3eb7b5)
- ⚪ `CHAINS.md` (aab8bef5) ← (23a1b56b)
- 🟡 `CHANGELOG.md` (425c2252) ← (d893d280)
- 🟡 `CLAUDE.md` (20411eca) ← (fa4ad3be)
- 🟡 `GEMINI.md` (13079ed6) ← (2ed4b7f2)
- 🟡 `MEMORY.md` (cfd45923) ← (590d73c2)
- 🟡 `OLLAMA.md` (c0dd177a) ← (1248ac62)
- ⚪ `PARTNERS.md` (85035efd) ← (04790b75)
- 🟡 `QUICKSTART.md` (7c6f80ff) ← (b66e6e14)
- 🟡 `QUICKSTART.pdf` (61166b3a) ← (60961281)
- 🟡 `README.md` (3e365688) ← (63bcfe1d)
- 🟡 `SKILLS.md` (04878ebf) ← (e72ed587)
- ⚪ `USECASES.md` (5a1692ba) ← (46d39315)
- ⚪ `WORKFLOWS.md` (c9f972ea) ← (82df479d)
- 🔴 `bach.py` (7c8fed1c) ← (7f0eeb88)
- ... and 218 more changed files

#### Added (1):

- 🔴 `system/tools/memory_working_cleanup.py` (a3bb8be4)

---

### v3.1.3

**Changes:** 5 files (5 changed, 0 added, 0 removed)

#### Changed (5):

- 🔴 `bach.py` (7f0eeb88) ← (3bf7277f)
- ⚪ `system/data/bach.db` (80157bad) ← (3e70d643)
- 🔴 `system/hub/pipeline.py` (03b25825) ← (5fe1f95f)
- 🔴 `system/hub/reflection.py` (f57b113a) ← (39efc250)
- 🔴 `system/tools/rezeptbuch.py` (e396a942) ← (a0f84b48)

---

### v3.1.2

**Changes:** 229 files (228 changed, 0 added, 1 removed)

#### Changed (228):

- 🔴 `bach.py` (3bf7277f) ← (b30130f2)
- ⚪ `system/data/bach.db` (3e70d643) ← (87ece3f3)
- 🔴 `system/hub/_services/claude_bridge/__init__.py` (2e956ba8) ← (b7be3d17)
- 🔴 `system/hub/_services/claude_bridge/bridge_daemon.py` (a1ad98e6) ← (6c0dfa37)
- 🔴 `system/hub/_services/claude_bridge/bridge_fackel_wrapper.py` (346055ce) ← (c00c3ab2)
- 🔴 `system/hub/_services/claude_bridge/bridge_tray.py` (cd0dc7da) ← (4c0c6fdd)
- 🔴 `system/hub/_services/claude_bridge/fackel.py` (a0afb919) ← (3fc9b8c4)
- 🔴 `system/hub/_services/claude_bridge/security.py` (89e33e67) ← (64b64275)
- 🔴 `system/hub/_services/claude_bridge/setup_wizard.py` (6420f2ca) ← (d791aacc)
- 🔴 `system/hub/_services/claude_bridge/skill_loader.py` (3f6b89ce) ← (276ea6e2)
- 🔴 `system/hub/_services/claude_bridge/telegram_test.py` (9384707e) ← (2889cb4d)
- 🔴 `system/hub/_services/claude_bridge/test_skills_load.py` (b18a4e8a) ← (42dfd379)
- 🔴 `system/hub/_services/config.py` (ccf8828b) ← (b0343825)
- 🔴 `system/hub/_services/connector/__init__.py` (1b58d7e9) ← (334db53d)
- 🔴 `system/hub/_services/connector/queue_processor.py` (ad148b2d) ← (24646c15)
- ... and 213 more changed files

#### Removed (1):

- 🔴 `system/tools/memory_working_cleanup.py` (2a330fe7)

---

### v2.6.0

**Changes:** 676 files (0 changed, 676 added, 0 removed)

#### Added (676):

- 🔴 `bach.py` (b30130f2)
- 🟡 `USER.md` (pending-)
- ⚪ `AGENTS.md` (8f8f8a52)
- ⚪ `CHAINS.md` (7e9f44bd)
- 🟡 `CHANGELOG.md` (f652adf7)
- 🟡 `CLAUDE.md` (b010d924)
- 🟡 `CONTRIBUTING.md` (f4c34afd)
- 🟡 `GEMINI.md` (e8ff0089)
- 🔴 `LICENSE` (9697c9d5)
- 🟡 `MEMORY.md` (b80b1262)
- 🟡 `OLLAMA.md` (6e25f14f)
- ⚪ `PARTNERS.md` (82303b39)
- 🟡 `QUICKSTART.md` (b66e6e14)
- 🟡 `QUICKSTART.pdf` (8fc97569)
- 🟡 `README.md` (d9915533)
- ... and 661 more added files

---


## Format

Each entry shows **delta changes** since the previous version:

- **Changed**: Files with new hash (old hash → new hash)
- **Added**: New files in this version
- **Removed**: Files removed from this version
- **Icon**: Dist type (CORE/TEMPLATE/USER)
- **Hash**: Short hash (first 8 characters)

## Complete History

For complete version history see the `dist_file_versions` table:

```bash
bach db query "SELECT * FROM dist_file_versions ORDER BY version DESC"
```

---

*Generated with `bach docs generate changelog` (delta mode since v3.1.6)*



---

## 13. Licenses


# BACH - Third-Party Licenses
<!-- AUTO-GENERATED via SQ034 (2026-02-18) - update when dependencies change -->

This document lists all third-party Python packages used by BACH,
their versions (as tested), and their respective licenses.

> **SQ072/ENT-32 (2026-02-19):** PyMuPDF (fitz) was removed as a core dependency.
> Core PDF reading now uses pypdf (MIT) + pdfplumber (MIT).
> PyMuPDF remains as an OPTIONAL dependency for: PDF rendering for OCR,
> PDF redaction (_vendor/), redaction detection.
> Tax agent files (dist_type=0) are not part of the release.
> This makes BACH publishable as an MIT project without AGPL infection from PyMuPDF.

---

## Core Dependencies

| Package | Version | License | Notes |
|---------|---------|---------|-------|
| `requests` | 2.32.5 | Apache-2.0 | HTTP client |
| `httpx` | 0.28.1 | BSD-3-Clause | Async HTTP |
| `aiohttp` | 3.13.0 | Apache-2.0 AND MIT | Async HTTP sessions |
| `PyYAML` | 6.0.2 | MIT | YAML parsing |
| `toml` | 0.10.2 | MIT | TOML parsing |
| `python-dotenv` | 1.2.1 | BSD (see metadata) | .env file loading |
| `pydantic` | 2.12.5 | MIT (see metadata) | Data validation |
| `xmltodict` | 1.0.2 | MIT | XML ↔ dict |
| `defusedxml` | 0.7.1 | PSFL (Python SF License) | Secure XML parsing |
| `lxml` | 6.0.0 | BSD-3-Clause | XML/HTML processing |
| `emoji` | 2.15.0 | BSD | Emoji handling |
| `ftfy` | 6.3.1 | Apache-2.0 | Unicode/encoding repair |
| `rapidfuzz` | 3.14.3 | MIT (see metadata) | Fuzzy string matching |
| `markdown` | 3.10 | BSD (see metadata) | Markdown → HTML |
| `watchdog` | 6.0.0 | Apache-2.0 | File system monitoring |
| `psutil` | 7.0.0 | BSD-3-Clause | System/process info |
| `GitPython` | 3.1.46 | BSD-3-Clause | Git operations |
| `colorama` | 0.4.6 | BSD | ANSI terminal colors |
| `rich` | 14.2.0 | MIT | Rich terminal output |
| `click` | 8.2.1 | BSD (see metadata) | CLI argument parsing |
| `typer` | 0.21.1 | MIT (see metadata) | Typed CLI building |
| `tqdm` | 4.67.1 | MPL-2.0 AND MIT | Progress bars |
| `cryptography` | 45.0.5 | Apache-2.0 OR BSD-3-Clause | Encryption |
| `keyring` | 25.7.0 | MIT (see metadata) | OS keychain |
| `peewee` | 3.19.0 | MIT (see metadata) | Lightweight ORM |
| `pypdf` | 6.4.0 | MIT (see metadata) | PDF text extraction (core, replaces PyMuPDF for reading) |
| `pdfplumber` | 0.11.7 | MIT | PDF text/table extraction (core, fallback after pypdf) |
| `pikepdf` | 10.0.2 | MPL-2.0 (see metadata) | PDF low-level editing |
| `pyperclip` | 1.9.0 | BSD | Clipboard access |
| `pyautogui` | 0.9.54 | BSD | GUI automation |

---

## Optional Dependencies

### Document Processing

| Package | Version | License | Notes |
|---------|---------|---------|-------|
| `PyMuPDF` | 1.26.4 | **AGPL-3.0 OR Commercial** | ⚠️ OPTIONAL: PDF render/redact/OCR-render (fitz). SQ072/ENT-32: Core PDF reading replaced by pypdf+pdfplumber. Install only for OCR-rendering or redaction features. |
| `extract_msg` | 0.55.0 | **GPL** | ⚠️ OPTIONAL: Parse .msg Outlook files (report_generator). SQ072/ENT-32: Moved to optional due to GPL incompatibility with MIT. Install only if you need Outlook .msg parsing. |
| `pdf2image` | 1.17.0 | MIT | PDF → image (requires poppler) |
| `reportlab` | 4.4.5 | BSD | PDF generation |
| `fpdf2` | 2.8.3 | **LGPL-3.0** | Lightweight PDF creation |
| `weasyprint` | 68.1 | BSD | HTML/CSS → PDF |
| `Pillow` | 10.4.0 | HPND (PIL License) | Image processing |
| `pytesseract` | 0.3.13 | Apache-2.0 | OCR wrapper |
| `python-docx` | 1.2.0 | MIT | Word .docx files |
| `python-pptx` | 1.0.2 | MIT | PowerPoint .pptx files |
| `openpyxl` | 3.1.5 | MIT | Excel .xlsx files |

### AI / LLM Partners

| Package | Version | License | Notes |
|---------|---------|---------|-------|
| `anthropic` | 0.79.0 | MIT | Claude API (primary LLM) |
| `ollama` | 0.6.1 | MIT (see metadata) | Ollama local LLM |
| `openai-whisper` | 20250625 | MIT | Speech-to-text (Whisper) |

### Data Analysis / Market

| Package | Version | License | Notes |
|---------|---------|---------|-------|
| `numpy` | 2.3.1 | BSD | Numerical computing |
| `pandas` | 2.3.1 | BSD | Data analysis |
| `scipy` | 1.16.0 | BSD | Scientific computing |
| `matplotlib` | 3.10.6 | PSF License | Plotting |
| `yfinance` | 1.0 | Apache | Yahoo Finance data |

### Vector Database / RAG

| Package | Version | License | Notes |
|---------|---------|---------|-------|
| `chromadb` | 1.4.1 | Apache-2.0 | Embedded vector DB |

### GUI / Web Server

| Package | Version | License | Notes |
|---------|---------|---------|-------|
| `PyQt6` | 6.10.0 | GPL-3.0 (see metadata) | ⚠️ Qt GUI framework |
| `fastapi` | 0.128.0 | MIT (see metadata) | Web API framework |
| `uvicorn` | 0.40.0 | BSD (see metadata) | ASGI server |
| `starlette` | 0.50.0 | BSD (see metadata) | ASGI framework |
| `pystray` | 0.19.5 | LGPL-3.0 | System tray icon |
| `tkinterdnd2` | 0.4.3 | MIT | Drag & drop (Tk) |
| `selenium` | 4.38.0 | Apache-2.0 | Browser automation |

### Google Services

| Package | Version | License | Notes |
|---------|---------|---------|-------|
| `google-api-python-client` | 2.187.0 | Apache-2.0 | Google APIs |
| `google-auth-oauthlib` | 1.2.3 | Apache-2.0 | Google OAuth2 |

### Voice / Audio

| Package | Version | License | Notes |
|---------|---------|---------|-------|
| `pyttsx3` | 2.99 | MIT (see metadata) | Text-to-speech |

### Windows-Specific

| Package | Version | License | Notes |
|---------|---------|---------|-------|
| `pywin32` | 311 | PSF | Windows COM/API |

### Development / Testing

| Package | Version | License | Notes |
|---------|---------|---------|-------|
| `pytest` | 9.0.2 | MIT (see metadata) | Test runner |

---

## Packages Referenced But Not Installed

These are referenced in the source code but not currently installed
(planned integrations, optional features, or legacy code):

| Import name | PyPI package | Notes |
|-------------|-------------|-------|
| `fitz` | PyMuPDF | Already listed above (different import name) |
| `sklearn` | `scikit-learn` | ML market analysis models |
| `tensorflow` | `tensorflow` | Neural network (market analysis) |
| `statsmodels` | `statsmodels` | Statistical models (market analysis) |
| `playwright` | `playwright` | Web automation (testing examples only) |
| `html2text` | `html2text` | HTML → Markdown (web parse) |
| `croniter` | `croniter` | Cron expressions (GUI scheduler) |
| `google` | `google-generativeai` | Gemini API (planned) |
| `mcp` | `mcp` | MCP SDK (tools/mcp_server.py) |
| `pyaudio` | `pyaudio` | Audio I/O (voice STT) |
| `vosk` | `vosk` | Offline speech recognition |
| `openwakeword` | `openWakeWord` | Wake word detection |
| `piper` | `piper-tts` | Neural TTS (voice) |
| `whisper` | `openai-whisper` | Already listed above |
| `telegram` | `python-telegram-bot` | Telegram connector |
| `textract` | `textract` | Document text extraction |

---

## ⚠️ License Compatibility Notes

Critical items requiring attention before public release:

1. **PyMuPDF (AGPL-3.0):** ✅ RESOLVED by SQ072 (2026-02-19). Core PDF reading
   migrated to pypdf+pdfplumber (MIT). PyMuPDF is now ONLY optional for
   special features (OCR rendering, redaction). Tax expert files
   (dist_type=0) are excluded from release. AGPL infection of the
   MIT release is thus eliminated.

2. **extract_msg (GPL):** Used in 2 files for .msg email parsing.
   GPL is similarly restrictive. Can be made optional (only install
   if .msg parsing is needed).

3. **PyQt6 (GPL-3.0):** Used only in `gui/prompt_manager.py` and
   `pdf_schwaerzer_pro.py`. Both are optional/tool components.
   Can be classified as optional.

4. **fpdf2 (LGPL-3.0):** LGPL allows linking from non-GPL code
   without copyleft propagation. Generally compatible.

5. **pystray (LGPL-3.0):** Same as fpdf2, generally compatible.

**Recommended BACH license given the above:**
If retaining PyMuPDF and PyQt6: **GPL-3.0 or AGPL-3.0**
If replacing/making optional: **MIT or Apache-2.0** (preferred for open source)

---

*Generated: 2026-02-18 | BACH v2.6.0 (Vanilla) | Python 3.12*
*To regenerate: python BACH_Dev/tools/scan_imports.py (SQ034)*
