# BACH Quickstart Guide

**Version:** v3.9.1-tiramisu

## Your First BACH Workflow in 5 Minutes

### 1. Installation (2 Minutes)

```bash
# Clone repository
git clone https://github.com/ellmos-ai/bach.git
cd bach

# Run pre-flight check
bach setup preflight

# Full install (MCP servers, hooks, secrets, user profile)
bach setup full-install
```

> **Note:** `bach` is the CLI entry point (`system/bach.py`). If `bach` is not
> in your PATH, use `python system/bach.py` instead.

### 2. First Steps (3 Minutes)

#### Start BACH

```bash
bach --startup
```

#### Create and Manage Tasks

```bash
# Create a new task
bach task add "First BACH experiment"

# List tasks
bach task list

# Complete a task
bach task done 1
```

#### Store and Retrieve Knowledge

```bash
# Store an important fact
bach mem fact "API endpoint: https://api.example.com/v2"

# Retrieve facts
bach mem read facts

# Write a wiki note
bach wiki write "bash-tricks" "Useful bash commands"
```

#### Check System Status

```bash
bach status
```

#### Stop BACH

```bash
bach --shutdown
```

---

## Essential Commands

| Command | Description |
|---|---|
| `bach --startup` | Start session with all subsystems |
| `bach --shutdown` | Clean shutdown |
| `bach status` | System health check |
| `bach task list` | Show open tasks |
| `bach mem read facts` | Browse stored facts |
| `bach help <topic>` | Topic-specific help |
| `bach setup check` | Validate installation |

---

## Deployment Scenarios

BACH has **one installer**. Configuration determines the deployment mode:

### Single System (Default)
Standard setup, no sync needed.

```bash
bach setup full-install
```

### Multi-System (OneDrive Sync)
BACH in OneDrive, local database per system, synced via ProSync.

```bash
bach setup full-install
bach setup prosync --multi-system
```

### Server / Headless
BACH on a persistent host. Start managed services through the Startspine so that process
ownership, actual ports, readiness, and shutdown remain traceable. The default endpoints are
loopback-only. Remote access requires a separately configured authenticated ingress; do not
expose the Control API directly on `0.0.0.0`.

```bash
bach setup full-install
python start/startspine.py start --chat --gui
python start/startspine.py status --json
```

---

## Next Steps

1. **Explore documentation:** `bach help list`
2. **Discover agents:** `bach agent list`
3. **Browse skills:** `cat SKILLS.md`
4. **Create your own workflow:** See [skills/workflows/](system/skills/workflows/)

---

## Configuration

```bash
# Register a partner (Claude, Gemini, Ollama)
bach partner register claude

# View settings
bach config list

# List connectors
bach connector list
```

---

## Further Documentation

- **[README.md](README.md)** - Complete overview
- **[User Manual](BACH_USER_MANUAL.en.md)** - Comprehensive guide
- **[Skills Catalog](SKILLS.md)** - All available skills
- **[Agents Catalog](AGENTS.md)** - All available agents
- **[Installation Guide](system/docs/help/install.txt)** - Detailed install docs

---

## Tips

1. **Contextual work:** BACH remembers what you're working on across sessions
2. **Automation:** Use workflows for recurring tasks
3. **Integration:** Connect with Claude, Gemini, Ollama, or OpenAI
4. **Backup:** `bach backup create` for manual backups (automatic on shutdown)
5. **Help:** `bach help <topic>` for any handler or concept

---

## Getting Help

```bash
# General help
bach --help

# Handler-specific help
bach help <handler>

# Search documentation
bach docs search "keyword"
```

---

Deutsche Version: [QUICKSTART.de.md](QUICKSTART.de.md)
