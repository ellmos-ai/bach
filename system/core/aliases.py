# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

"""
Command Aliases - Kurzformen und Multi-Handler-Mappings
========================================================
Zentrale Alias-Tabelle fuer CLI-Befehle.
"""

# Aliases: Kurzform -> Handler-Name
# Diese werden nach dem Auto-Discovery angewendet.
COMMAND_ALIASES = {
    # Kurzformen
    "mem": "memory",
    "cv": "curriculum",
    "msg": "messages",
    "tool": "tools",
    "skill": "skills",
    "data": "data_analysis",
    "mail": "email",
    "hook": "hooks",
    "plugin": "plugins",
    "daemon": "scheduler",
    "health": "healthcheck",
    "swarm": "schwarm",
    "consolidate": "consolidation",

    # Multi-Handler-Dateien: time.py hat 5 Handler
    # (werden automatisch erkannt wenn profile_name != dateiname)
    # clock, timer, countdown, between, beat -> alle in time.py

    # Multi-Handler: tuev.py hat 2 Handler
    # tuev, usecase -> beide in tuev.py
}

# Default-Operation pro Handler (wenn kein sub_cmd angegeben)
DEFAULT_OPERATIONS = {
    "task": "list",
    "memory": "status",
    "startup": "",
    "shutdown": "",
    "status": "",
    "help": "",
    "backup": "list",
    "steuer": "status",
    "abo": "list",
    "ati": "status",
    "gui": "info",
    "daemon": "status",
    "scheduler": "status",
    "prompt": "list",
    "inbox": "status",
    "scan": "status",
    "calendar": "week",
    "contact": "list",
    "doc": "help",
    "lesson": "list",
    "wiki": "list",
    "tools": "list",
    "msg": "list",
    "partner": "list",
    "session": "status",
    "consolidate": "status",
    "bericht": "help",
    "clock": "status",
    "timer": "list",
    "countdown": "list",
    "between": "status",
    "beat": "",
    "tuev": "status",
    "usecase": "list",
    "agent": "list",
    "chain": "list",
    "routine": "list",
    "gesundheit": "status",
    "haushalt": "status",
    "versicherung": "status",
    "lang": "status",
    "email": "drafts",
    "extensions": "list",
    "hooks": "status",
    "plugins": "list",
    "mount": "list",
    "path": "",
    "fs": "",
}

# Spezial-Handler mit eigenem Init (nicht standard BaseHandler(base_path))
SPECIAL_HANDLERS = {
    "llm": {
        "module": "multi_llm_protocol",
        "class": "MultiLLMHandler",
        "extra_init": True,  # braucht partner-Argument
    },
}
