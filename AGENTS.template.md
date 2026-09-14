# BACH Agents & Experts

**Generated:** (automatically from bach.db)
**Source:** bach.db (bach_agents, bach_experts)
**Generator:** `bach export mirrors` or `python tools/agents_export.py`

---

## Boss Agents (Orchestrators)

Boss agents orchestrate complex workflows and delegate to experts.

### Developer Agent (ATI)
- **Type:** Expert
- **Status:** active
- **Description:** Specialized in tool monitoring and software development.

### Office Assistant
- **Type:** boss
- **Category:** professional
- **Description:** Taxes, funding planning, documentation

### Health Assistant
- **Type:** boss
- **Category:** personal
- **Description:** Medical reports, medications, lab results, preventive care

### Personal Assistant
- **Type:** boss
- **Category:** personal
- **Description:** Briefings, appointments, calendar, household

### Production
- **Type:** boss
- **Category:** creative
- **Description:** Content creation and media production

---

## Experts

Experts are specialized sub-agents under boss agents.

*(Automatically generated from bach.db)*

---

## Measurement and change-work baseline

For every measurement and change, create a fresh worktree from `origin/<default>`:

```bash
git worktree add <path> -b <branch> origin/<default>
```

Do not measure or build in the main clone's working tree. The main clone may have an old feature branch checked out and therefore show a stale state. Keep the lock in the main clone (resolvable with `git rev-parse --git-common-dir`); perform the work in the fresh worktree.

---

<!--
  NOTE: This file is a template.
  BACH generates the complete list automatically.
-->

---
🇩🇪 [Deutsche Version](AGENTS.template.de.md)
