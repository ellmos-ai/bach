# BACH Quickstart Guide

**Version:** v3.9.0-tiramisu

## Your First BACH Workflow in 5 Minutes

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

# List tasks
python bach.py task list

# Complete a task
python bach.py task done 1
```

#### Store and Retrieve Knowledge

```bash
# Write a wiki note
python bach.py wiki write "bash-tricks" "Collecting useful bash commands"

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

#### Stop BACH

```bash
python bach.py --shutdown
```

---

## Essential Commands

---

## Next Steps

1. **Explore documentation**
   ```bash
   python bach.py docs list
   ```

2. **Discover agents**
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

## Configuration

BACH adapts automatically, but you can customize:

- **Configure partner:** `python bach.py partner register claude`
- **Change settings:** `python bach.py config list`
- **Set up connector:** `python bach.py connector list`

---

## Further Documentation

- **[README.md](README.md)** - Complete overview
- **[API Reference](docs/reference/api.md)** - Programming interface
- **[Skills Catalog](SKILLS.md)** - All available skills
- **[Agents Catalog](AGENTS.md)** - All available agents

---

## Tips

1. **Contextual work:** BACH remembers what you're working on
2. **Automation:** Use workflows for recurring tasks
3. **Integration:** Connect BACH with Claude, Gemini, or Ollama
4. **Backup:** Regularly `python bach.py backup create`

---

## Getting Help

```bash
# General help
python bach.py --help

# Handler-specific help
python bach.py <handler> --help

# Search documentation
python bach.py docs search "keyword"
```

---

Deutsche Version: [QUICKSTART.de.md](QUICKSTART.de.md)

*Generated with `bach docs generate quickstart --lang en`*
