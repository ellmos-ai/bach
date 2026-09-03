#!/usr/bin/env python3
"""BACH's tool surface for the chat runtime -- the injected ``ToolProvider``.

Since wave 2 of the BACH-GUI module cut (decision D-20260830-002) the chat
runtime itself comes from the neutral module ``ellmos-chat``; the tools stay
here, because they are BACH: ``bach_command`` reaches the 110+ CHIAH handlers
through ``bach_app.execute``, and ``maintain``/``foerderbericht``/``weather``
lazily import ``hub._services.*``. The module never sees any of that -- it asks
``BachToolProvider`` for definitions and calls ``execute``.

The definitions, their safe/full gating and ``exec_tool`` are unchanged from
the pre-cut ``chat_runtime.py``; only their address moved.
"""
import json
import logging
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from ellmos_chat import Mode, as_mode

log = logging.getLogger("bach.chat")

try:
    from hub.bach_paths import BACH_DB as _RUNTIME_DB
    RUNTIME_BACH_DB = str(_RUNTIME_DB)
except ImportError:
    RUNTIME_BACH_DB = os.environ.get("BACH_DB", "")


# --- Sicherheit ---

BLOCKED_PATTERNS = [
    re.compile(r"rm\s+(-[rRf]+\s+)?/($|\s)"),
    re.compile(r"rm\s+(-[rRf]+\s+)?~($|\s)"),
    re.compile(r"mkfs\b"),
    re.compile(r"dd\s+if="),
    re.compile(r">\s*/dev/sd"),
    re.compile(r":\(\)\s*\{"),
]

SAFE_BASES = frozenset({
    "ls", "cat", "head", "tail", "grep", "find", "wc", "file", "stat",
    "echo", "date", "which", "whoami", "hostname", "uname", "env",
    "df", "du", "uptime", "ps", "top", "sw_vers", "sysctl",
    "ollama", "brew", "pip", "pip3",
    "docker", "git", "curl",
    "bach",
})

CMD_TIMEOUT = 30


def is_blocked(cmd: str) -> bool:
    return any(pat.search(cmd) for pat in BLOCKED_PATTERNS)


def is_safe_command(cmd: str) -> bool:
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return False
    if not parts:
        return False
    return os.path.basename(parts[0]) in SAFE_BASES


BLOCKED_WRITE_PREFIXES = (
    "/etc", "/usr", "/bin", "/sbin", "/System", "/Library",
    "/var/root", "/private/etc",
)

BACH_SYSTEM_DIR = str(Path(__file__).resolve().parents[2])


def is_safe_write_path(path_str: str, mode: str) -> Optional[str]:
    """Return error message if path is blocked for writes in safe mode, else None."""
    if mode != "safe":
        return None
    p = str(Path(path_str).resolve())
    for prefix in BLOCKED_WRITE_PREFIXES:
        if p.startswith(prefix):
            return f"Schreibzugriff auf {prefix}/ im Safe-Mode nicht erlaubt"
    if p.startswith(BACH_SYSTEM_DIR) and "/user/" not in p.lower():
        return "Schreibzugriff auf BACH-Systemdateien im Safe-Mode nicht erlaubt"
    return None


def run_shell(cmd: str, timeout: int = CMD_TIMEOUT) -> str:
    timeout = min(max(timeout, 5), 120)
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            timeout=timeout, stdin=subprocess.DEVNULL,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        out = r.stdout
        if r.stderr:
            out += "\n[stderr] " + r.stderr
        return (out or "(keine Ausgabe)")[:4000]
    except subprocess.TimeoutExpired:
        return f"Timeout nach {timeout}s"
    except Exception as e:
        return f"Fehler: {e}"


# --- Tool-Definitionen ---

def _tool(name, desc, props, required=None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required or [],
            },
        },
    }


TOOLS_SAFE = [
    _tool("list_directory", "Dateien und Ordner in einem Verzeichnis auflisten", {
        "path": {"type": "string", "description": "Verzeichnispfad"},
        "details": {"type": "boolean", "description": "Ausführlich mit Rechten und Größe"},
    }),
    _tool("read_file", "Inhalt einer Datei lesen (max 200 Zeilen)", {
        "path": {"type": "string", "description": "Dateipfad"},
        "lines": {"type": "integer", "description": "Max Zeilen (Standard 50)"},
    }, ["path"]),
    _tool("search_text", "In Dateien nach einem Muster suchen (grep)", {
        "pattern": {"type": "string", "description": "Suchmuster (Regex)"},
        "path": {"type": "string", "description": "Suchpfad"},
        "recursive": {"type": "boolean", "description": "Rekursiv"},
    }, ["pattern"]),
    _tool("system_status", "Systemstatus: Uptime, RAM, Disk, CPU", {}),
    _tool("ollama_info", "Ollama-Informationen abrufen", {
        "action": {"type": "string", "enum": ["list", "running", "show"]},
        "model": {"type": "string", "description": "Modellname (nur bei show)"},
    }),
    _tool("bach_command", "BACH-Befehl ausführen (Memory, Tasks, Kalender, Denkarium, News, etc.)", {
        "handler": {"type": "string", "description": "Handler: status, task, mem, search, help, tools, denkarium, calendar, contact, routine, timer, countdown, news, newspaper, lesson, snapshot, partner, connector, msg, backup, web-parse, web-scrape, skills, agent, maintain, sync, abo, steuer, gesundheit, mediplaner, haushalt, versicherung, inbox, wiki"},
        "operation": {"type": "string", "description": "Operation: list, add, done, facts, write, read, search, context, today, brainstorm, promote, stats, fetch, generate, create, load"},
        "args": {"type": "array", "items": {"type": "string"}, "description": "Argumente"},
    }, ["handler"]),
    _tool("get_datetime", "Aktuelles Datum und Uhrzeit abfragen", {}),
    _tool("safe_shell", "Lesenden Shell-Befehl ausführen", {
        "command": {"type": "string", "description": "Shell-Befehl (nur lesende Befehle erlaubt)"},
    }, ["command"]),
    _tool("web_search", "Im Internet nach Informationen suchen (DuckDuckGo)", {
        "query": {"type": "string", "description": "Suchanfrage"},
        "max_results": {"type": "integer", "description": "Maximale Ergebnisse (Standard 5, max 10)"},
    }, ["query"]),
    _tool("task_manage", "BACH-Tasks verwalten: anlegen, auflisten, Status ändern", {
        "action": {"type": "string", "enum": ["list", "add", "done", "detail"], "description": "Aktion"},
        "title": {"type": "string", "description": "Task-Titel (bei add)"},
        "priority": {"type": "string", "enum": ["P1", "P2", "P3", "P4"], "description": "Priorität (bei add, Standard P3)"},
        "task_id": {"type": "integer", "description": "Task-ID (bei done/detail)"},
    }, ["action"]),
    _tool("maintain", "Systemwartung: fällige Tasks prüfen, Wartungsoperationen ausführen", {
        "action": {"type": "string", "enum": ["check", "run", "health", "services", "sync"],
                   "description": "check=fällige Tasks, run=Wartung, health=BACH-Status, services=Service-Check, sync=OneDrive→Mirror"},
        "operation": {"type": "string",
                      "description": "Bei run: registry, skills, docs, backup, clean, memory, recurring"},
    }, ["action"]),
    _tool("foerderbericht", "Förderbericht-Pipeline: Anonymisierung und Berichterstellung", {
        "action": {"type": "string", "enum": ["prepare", "status", "cleanup"],
                   "description": "prepare=Phase 1 (Anonymisierung, kein LLM), status=Pipeline-Status, cleanup=Zwischendateien löschen"},
        "zeitraum": {"type": "string", "description": "Berichtszeitraum (z.B. '01.01.2025 - 31.12.2025')"},
        "eltern": {"type": "array", "items": {"type": "string"}, "description": "Elternnamen zur Anonymisierung"},
        "adresse": {"type": "string", "description": "Klienten-Adresse zur Anonymisierung"},
    }, ["action"]),
    _tool("delegate", "Aufgabe an Claude Code oder Codex CLI delegieren", {
        "target": {"type": "string", "enum": ["claude", "codex"], "description": "Ziel-Agent"},
        "prompt": {"type": "string", "description": "Aufgabe oder Frage für den Agenten"},
        "context": {"type": "string", "description": "Optionaler Kontext zur Aufgabe"},
    }, ["target", "prompt"]),
    _tool("weather", "Aktuelles Wetter für einen Ort oder Koordinaten abfragen (wttr.in)", {
        "location": {"type": "string", "description": "Ortsname (z.B. 'Berlin') oder Koordinaten ('52.52,13.405')"},
    }, ["location"]),
    _tool("edit_file", "Text in einer Datei ersetzen (suchen und ersetzen)", {
        "path": {"type": "string", "description": "Dateipfad"},
        "old_text": {"type": "string", "description": "Zu ersetzender Text (muss exakt vorkommen)"},
        "new_text": {"type": "string", "description": "Neuer Text"},
        "all": {"type": "boolean", "description": "Alle Vorkommen ersetzen (Standard: nur erstes)"},
    }, ["path", "old_text", "new_text"]),
    _tool("move_file", "Datei oder Ordner verschieben oder umbenennen", {
        "source": {"type": "string", "description": "Quellpfad"},
        "destination": {"type": "string", "description": "Zielpfad"},
    }, ["source", "destination"]),
    _tool("copy_file", "Datei oder Ordner kopieren", {
        "source": {"type": "string", "description": "Quellpfad"},
        "destination": {"type": "string", "description": "Zielpfad"},
    }, ["source", "destination"]),
    _tool("file_info", "Detaillierte Informationen zu einer Datei oder einem Ordner", {
        "path": {"type": "string", "description": "Pfad zur Datei oder zum Ordner"},
    }, ["path"]),
    _tool("recycle", "Datei oder Ordner in den Papierkorb verschieben (wiederherstellbar)", {
        "path": {"type": "string", "description": "Pfad zum Löschen (wird in Papierkorb verschoben)"},
    }, ["path"]),
    _tool("create_directory", "Neuen Ordner erstellen (inkl. Elternordner)", {
        "path": {"type": "string", "description": "Pfad des neuen Ordners"},
    }, ["path"]),
    _tool("web_fetch", "Inhalt einer URL abrufen (Webseite, API, JSON)", {
        "url": {"type": "string", "description": "Die abzurufende URL"},
        "extract_text": {"type": "boolean", "description": "Nur sichtbaren Text extrahieren (bei HTML, Standard: true)"},
        "max_chars": {"type": "integer", "description": "Maximale Zeichenanzahl (Standard 4000, max 8000)"},
    }, ["url"]),
]

TOOLS_FULL = TOOLS_SAFE + [
    _tool("execute_command", "Beliebigen Shell-Befehl ausführen (nur im Full-Modus)", {
        "command": {"type": "string", "description": "Shell-Befehl"},
        "timeout": {"type": "integer", "description": "Timeout in Sekunden (max 120)"},
    }, ["command"]),
    _tool("write_file", "Datei schreiben oder erstellen", {
        "path": {"type": "string", "description": "Dateipfad"},
        "content": {"type": "string", "description": "Dateiinhalt"},
    }, ["path", "content"]),
]


# --- Delegation ---

def _delegate_claude_api(prompt: str, api_key: str,
                         model: str = "claude-sonnet-4-6") -> str:
    import httpx
    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 2048,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=120,
        )
        data = r.json()
        if r.status_code != 200:
            return f"Claude API Fehler ({r.status_code}): {data.get('error', {}).get('message', str(data)[:500])}"
        blocks = data.get("content", [])
        text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return (text or "(keine Antwort)")[:3000]
    except httpx.TimeoutException:
        return "Claude API Timeout (120s)"
    except Exception as e:
        return f"Claude API Fehler: {e}"


# --- Tool-Ausführung ---

def exec_tool(name: str, args: Any, mode: str, bach_app=None,
              default_model: str = "") -> str:
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (json.JSONDecodeError, TypeError):
            args = {}

    try:
        if name == "list_directory":
            p = shlex.quote(args.get("path") or os.path.expanduser("~"))
            return run_shell(f"ls -la {p}" if args.get("details") else f"ls {p}")

        if name == "read_file":
            p = args.get("path", "")
            if not p:
                return "Kein Pfad angegeben"
            n = min(int(args.get("lines", 50)), 200)
            return run_shell(f"head -n {n} {shlex.quote(p)}")

        if name == "search_text":
            pat = args.get("pattern", "")
            p = shlex.quote(args.get("path", "."))
            flag = "-r" if args.get("recursive", True) else ""
            return run_shell(f"grep {flag} -n --color=never {shlex.quote(pat)} {p}")

        if name == "system_status":
            parts = [
                run_shell("uptime"),
                "Disk: " + run_shell("df -h / | tail -1"),
                "Speicher: " + run_shell("memory_pressure | head -3"),
                "CPU: " + run_shell("sysctl -n machdep.cpu.brand_string"),
            ]
            return "\n".join(parts)[:4000]

        if name == "ollama_info":
            act = args.get("action", "list")
            if act == "list":
                return run_shell("ollama list")
            if act == "running":
                return run_shell("ollama ps")
            if act == "show":
                m = shlex.quote(args.get("model", default_model))
                return run_shell(f"ollama show {m}")
            return "Unbekannte Aktion: " + act

        if name == "bach_command":
            if not bach_app:
                return "BACH nicht verfügbar"
            _HANDLER_ALIASES = {
                "kalender": "calendar", "kontakte": "contact",
                "contacts": "contact", "routinen": "routine",
                "routines": "routine", "notes": "denkarium",
                "timers": "timer", "counters": "countdown",
                "lessons": "lesson", "partners": "partner",
                "agents": "agent", "messages": "msg",
            }
            h = args.get("handler", "")
            h = _HANDLER_ALIASES.get(h, h)
            op = args.get("operation", "")
            ex = args.get("args", [])
            ok, out = bach_app.execute(h, op, ex)
            r = str(out)[:4000] if out else "(keine Ausgabe)"
            return r if ok else "Fehler: " + r

        if name == "get_datetime":
            return datetime.now().strftime("%Y-%m-%d %H:%M:%S (%A)")

        if name == "safe_shell":
            cmd = args.get("command", "")
            if not cmd:
                return "Kein Befehl angegeben"
            if not is_safe_command(cmd):
                return f"Befehl nicht in der Safe-Liste. Erlaubt: {', '.join(sorted(SAFE_BASES)[:15])}..."
            if is_blocked(cmd):
                return "Befehl blockiert (Sicherheit)"
            return run_shell(cmd)

        if name == "execute_command":
            if mode != "full":
                return "Nur im Full-Modus. Aktivieren: /mode full bestätigt"
            cmd = args.get("command", "")
            t = int(args.get("timeout", CMD_TIMEOUT))
            if is_blocked(cmd):
                return f"Befehl blockiert (Sicherheit): {cmd}"
            log.info(f"FULL-CMD: {cmd}")
            return run_shell(cmd, t)

        if name == "write_file":
            if mode != "full":
                return "Nur im Full-Modus."
            p = args.get("path", "")
            c = args.get("content", "")
            if not p:
                return "Kein Pfad"
            Path(p).parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(c)
            log.info(f"WRITE: {p} ({len(c)} chars)")
            return f"Geschrieben: {p} ({len(c)} Zeichen)"

        if name == "web_search":
            query = args.get("query", "")
            if not query:
                return "Keine Suchanfrage angegeben"
            max_r = min(int(args.get("max_results", 5)), 10)
            try:
                from duckduckgo_search import DDGS
                results = DDGS().text(query, max_results=max_r)
                if not results:
                    return f"Keine Ergebnisse für: {query}"
                out = []
                for r in results:
                    title = r.get("title", "")
                    href = r.get("href", "")
                    body = r.get("body", "")[:300]
                    out.append(f"**{title}**\n{href}\n{body}")
                return "\n\n".join(out)[:4000]
            except ImportError:
                return "Web-Suche nicht verfügbar (ddgs nicht installiert)"
            except Exception as e:
                return f"Suchfehler: {e}"

        if name == "task_manage":
            action = args.get("action", "list")
            try:
                conn = sqlite3.connect(RUNTIME_BACH_DB)
                conn.row_factory = sqlite3.Row
                try:
                    if action == "list":
                        rows = conn.execute(
                            "SELECT id, title, priority, status FROM tasks "
                            "WHERE status IN ('pending','in-progress') "
                            "ORDER BY priority, id DESC LIMIT 20"
                        ).fetchall()
                        if not rows:
                            return "Keine offenen Tasks."
                        lines = [f"[{r['id']}] {r['priority']} {r['status']}: {r['title']}" for r in rows]
                        return "\n".join(lines)

                    if action == "add":
                        title = args.get("title", "")
                        if not title:
                            return "Kein Titel angegeben"
                        prio = args.get("priority", "P3")
                        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        cur = conn.execute(
                            "INSERT INTO tasks (title, priority, status, created_at, updated_at) "
                            "VALUES (?, ?, 'pending', ?, ?)",
                            (title, prio, now, now)
                        )
                        conn.commit()
                        return f"Task #{cur.lastrowid} erstellt: {title} ({prio})"

                    if action == "done":
                        tid = args.get("task_id")
                        if not tid:
                            return "Keine Task-ID angegeben"
                        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        r = conn.execute(
                            "UPDATE tasks SET status='done', completed_at=?, updated_at=? WHERE id=?",
                            (now, now, tid)
                        )
                        conn.commit()
                        if r.rowcount == 0:
                            return f"Task #{tid} nicht gefunden"
                        return f"Task #{tid} erledigt."

                    if action == "detail":
                        tid = args.get("task_id")
                        if not tid:
                            return "Keine Task-ID angegeben"
                        row = conn.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
                        if not row:
                            return f"Task #{tid} nicht gefunden"
                        return "\n".join(f"{k}: {row[k]}" for k in row.keys())

                    return f"Unbekannte Aktion: {action}"
                finally:
                    conn.close()
            except Exception as e:
                return f"Task-Fehler: {e}"

        if name == "maintain":
            action = args.get("action", "check")
            operation = args.get("operation", "")
            try:
                if action == "check":
                    base = str(Path(__file__).parent.parent.parent.parent)
                    if base not in sys.path:
                        sys.path.insert(0, base)
                    from hub._services.recurring.recurring_tasks import list_recurring_tasks
                    tasks = list_recurring_tasks()
                    if not tasks:
                        return "Keine wiederkehrenden Tasks konfiguriert."
                    lines = []
                    for tid, info in tasks.items():
                        status = info.get("status", "?")
                        due = info.get("next_due", "?")
                        text = info.get("task_text", tid)[:60]
                        marker = "🔴 FÄLLIG" if status == "overdue" else ("🟡 bald" if status == "due_soon" else "✅")
                        lines.append(f"{marker} {tid}: {text} (nächst: {due})")
                    return "\n".join(lines)
                elif action == "run":
                    if not operation:
                        return "Bitte 'operation' angeben: registry, skills, docs, backup, clean, memory, recurring"
                    op_map = {
                        "registry": "maintain registry",
                        "skills": "maintain skills",
                        "docs": "maintain docs report",
                        "backup": "backup status",
                        "clean": "maintain clean",
                        "memory": "mem gc",
                        "recurring": "recurring check",
                    }
                    cmd = op_map.get(operation)
                    if not cmd:
                        return f"Unbekannte Operation: {operation}. Erlaubt: {', '.join(op_map)}"
                    parts = cmd.split()
                    handler, op_args = parts[0], " ".join(parts[1:])
                    return run_shell(f"cd {shlex.quote(str(Path(__file__).parent.parent.parent.parent))} && "
                                     f"PYTHONIOENCODING=utf-8 python bach.py --{handler} {op_args}", 60)
                elif action == "health":
                    return run_shell(f"cd {shlex.quote(str(Path(__file__).parent.parent.parent.parent))} && "
                                     f"PYTHONIOENCODING=utf-8 python bach.py status", 60)
                elif action == "services":
                    http_checks = {
                        "GUI Dashboard (:8000)": "curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost:8000/",
                        "Ollama (:11434)": "curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost:11434/api/tags",
                    }
                    proc_checks = {
                        "Telegram Bot": "telegram_chat",
                        "GUI Server": "gui/server\\.py",
                        "Chat Tray": "chat_tray",
                    }
                    lines = ["BACH Service-Check:"]
                    lines.append(f"  ✅ Control API (:8081) — läuft (diese Anfrage)")
                    for svc, cmd in http_checks.items():
                        code = run_shell(cmd).strip()
                        ok = code == "200"
                        lines.append(f"  {'✅' if ok else '❌'} {svc} — HTTP {code}")
                    for svc, pattern in proc_checks.items():
                        ps_out = run_shell(f"pgrep -f '{pattern}' 2>/dev/null").strip()
                        if ps_out:
                            pids = ps_out.replace('\n', ', ')
                            lines.append(f"  ✅ {svc} — PID {pids}")
                        else:
                            lines.append(f"  ❌ {svc} — nicht gefunden")
                    lines.append(f"  Uptime: {run_shell('uptime').strip()}")
                    return "\n".join(lines)
                elif action == "sync":
                    sync_script = Path.home() / "services" / "bach" / "sync_mirror.sh"
                    if not sync_script.exists():
                        return "Sync-Script nicht gefunden: ~/services/bach/sync_mirror.sh"
                    out = run_shell(f"bash {sync_script} 2>&1")
                    return f"OneDrive → Mirror Sync abgeschlossen.\n{out.strip()}" if out.strip() else "OneDrive → Mirror Sync abgeschlossen (keine Änderungen)."
                else:
                    return f"Unbekannte Aktion: {action}. Erlaubt: check, run, health, services, sync"
            except Exception as e:
                return f"Wartungsfehler: {e}"

        if name == "foerderbericht":
            action = args.get("action", "status")
            try:
                base = str(Path(__file__).parent.parent.parent.parent)
                if base not in sys.path:
                    sys.path.insert(0, base)
                from hub._services.document.foerderbericht_pipeline import FoerderberichtPipeline
                pipeline = FoerderberichtPipeline()
                lock_file = pipeline.base_path / ".pipeline_lock"

                if action == "status":
                    data_roh = pipeline.base_path / "data_roh"
                    client_count = (
                        len([d for d in data_roh.iterdir() if d.is_dir()])
                        if data_roh.exists() else 0
                    )
                    prompt_exists = (pipeline.base_path / "data_bundled" / "prompt.txt").exists()
                    state = "Pipeline läuft." if lock_file.exists() else "Pipeline bereit."
                    status = state + "\n"
                    status += f"Akte erkannt: {'ja' if client_count else 'nein'} ({client_count} Ordner)\n"
                    status += f"Anonymisierter Prompt vorhanden: {'ja' if prompt_exists else 'nein'}"
                    return status

                elif action == "prepare":
                    zeitraum = args.get("zeitraum", "01.01.2025 - 31.12.2025")
                    eltern = args.get("eltern")
                    adresse = args.get("adresse")
                    result = pipeline.prepare_prompt(
                        berichtszeitraum=zeitraum,
                        parent_names=eltern,
                        client_address=adresse,
                    )
                    if result.success:
                        return (f"Phase 1 abgeschlossen. Tarnname: {result.tarnname}\n"
                                f"Anonymisierter Prompt bereit.\n"
                                f"Dauer: {result.duration_s:.1f}s\nSchritte: {', '.join(result.steps_completed)}")
                    return f"Phase 1 fehlgeschlagen: {result.error}"

                elif action == "cleanup":
                    for folder in ["data_ano", "data_bundled"]:
                        p = pipeline.base_path / folder
                        if p.exists():
                            import shutil
                            shutil.rmtree(p)
                            p.mkdir()
                    if lock_file.exists():
                        lock_file.unlink()
                    return "Zwischendateien gelöscht (data_ano/, data_bundled/), Lock entfernt."

                return f"Unbekannte Aktion: {action}. Erlaubt: prepare, status, cleanup"
            except Exception as e:
                return f"Pipeline-Fehler: {e}"

        if name == "delegate":
            target = args.get("target", "")
            prompt = args.get("prompt", "")
            context = args.get("context", "")
            if target not in ("claude", "codex"):
                return f"Unbekanntes Ziel: {target}. Erlaubt: claude, codex"
            if not prompt:
                return "Kein Prompt angegeben"
            depth = int(os.environ.get("BACH_DELEGATION_DEPTH", "0"))
            if depth >= 2:
                return "Maximale Delegationstiefe erreicht (2). Abbruch."
            full_prompt = prompt
            if context:
                full_prompt = f"Kontext: {context}\n\nAufgabe: {prompt}"
            env = {**os.environ, "PYTHONIOENCODING": "utf-8",
                   "BACH_DELEGATION_DEPTH": str(depth + 1)}
            log.info(f"DELEGATE -> {target} (depth={depth}): {prompt[:100]}")
            if target == "claude":
                api_key = os.environ.get("ANTHROPIC_API_KEY", "")
                if not api_key:
                    kf = Path.home() / ".credentials" / "anthropic_api_key"
                    if kf.exists():
                        api_key = kf.read_text(encoding="utf-8").strip()
                if api_key:
                    return _delegate_claude_api(full_prompt, api_key)
                cmd = ["claude", "-p", full_prompt]
            else:
                cmd = ["codex", "exec", full_prompt]
            try:
                r = subprocess.run(
                    cmd, capture_output=True, text=True,
                    encoding='utf-8', errors='replace', timeout=120,
                    stdin=subprocess.DEVNULL, env=env,
                )
                out = (r.stdout or "").strip()
                if r.returncode != 0 and r.stderr:
                    out += f"\n[stderr] {r.stderr.strip()[:500]}"
                return (out or "(keine Ausgabe)")[:3000]
            except subprocess.TimeoutExpired:
                return f"Delegation an {target} abgebrochen (Timeout 120s)"
            except FileNotFoundError:
                return f"{target} CLI nicht gefunden — API-Key unter ~/.credentials/anthropic_api_key hinterlegen für API-Fallback"
            except Exception as e:
                return f"Delegation fehlgeschlagen: {e}"

        if name == "weather":
            location = args.get("location", "")
            if not location:
                return "Kein Ort angegeben"
            try:
                from hub._services.weather.weather_service import get_weather_text, get_weather
                parts = location.replace(" ", "").split(",")
                if len(parts) == 2:
                    try:
                        lat, lon = float(parts[0]), float(parts[1])
                        return get_weather_text(lat, lon)
                    except ValueError:
                        pass
                url = f"https://wttr.in/{urllib.parse.quote(location)}?format=j1&lang=de"
                req = urllib.request.Request(url, headers={"User-Agent": "BACH/1.0"})
                with urllib.request.urlopen(req, timeout=12) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                cc = data["current_condition"][0]
                area = data.get("nearest_area", [{}])[0]
                area_name = area.get("areaName", [{}])[0].get("value", location)
                country = area.get("country", [{}])[0].get("value", "")
                desc = cc.get("lang_de", [{}])
                desc_text = desc[0].get("value", cc.get("weatherDesc", [{}])[0].get("value", "")) if desc else cc.get("weatherDesc", [{}])[0].get("value", "")
                temp = cc.get("temp_C", "?")
                feels = cc.get("FeelsLikeC", "?")
                hum = cc.get("humidity", "?")
                wind = cc.get("windspeedKmph", "?")
                return (f"Wetter in {area_name}, {country}:\n"
                        f"Temperatur: {temp}°C (gefühlt: {feels}°C) | {desc_text}\n"
                        f"Wind: {wind} km/h | Luftfeuchtigkeit: {hum}%")
            except Exception as e:
                return f"Wetter-Fehler: {e}"

        if name == "edit_file":
            p = args.get("path", "")
            old_text = args.get("old_text", "")
            new_text = args.get("new_text", "")
            if not p or not old_text:
                return "Pfad und old_text sind erforderlich"
            if err := is_safe_write_path(p, mode):
                return err
            try:
                content = Path(p).read_text(encoding="utf-8")
            except FileNotFoundError:
                return f"Datei nicht gefunden: {p}"
            except Exception as e:
                return f"Lesefehler: {e}"
            if old_text not in content:
                return f"Text nicht gefunden in {p}"
            if args.get("all"):
                new_content = content.replace(old_text, new_text)
                count = content.count(old_text)
            else:
                new_content = content.replace(old_text, new_text, 1)
                count = 1
            try:
                Path(p).write_text(new_content, encoding="utf-8")
                log.info(f"EDIT: {p} ({count}x ersetzt)")
                return f"Bearbeitet: {p} ({count} Ersetzung{'en' if count > 1 else ''})"
            except Exception as e:
                return f"Schreibfehler: {e}"

        if name == "move_file":
            src = args.get("source", "")
            dst = args.get("destination", "")
            if not src or not dst:
                return "source und destination sind erforderlich"
            if err := is_safe_write_path(src, mode):
                return err
            if err := is_safe_write_path(dst, mode):
                return err
            try:
                import shutil
                shutil.move(src, dst)
                log.info(f"MOVE: {src} -> {dst}")
                return f"Verschoben: {src} → {dst}"
            except Exception as e:
                return f"Fehler beim Verschieben: {e}"

        if name == "copy_file":
            src = args.get("source", "")
            dst = args.get("destination", "")
            if not src or not dst:
                return "source und destination sind erforderlich"
            if err := is_safe_write_path(dst, mode):
                return err
            try:
                import shutil
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
                log.info(f"COPY: {src} -> {dst}")
                return f"Kopiert: {src} → {dst}"
            except Exception as e:
                return f"Fehler beim Kopieren: {e}"

        if name == "file_info":
            p = args.get("path", "")
            if not p:
                return "Kein Pfad angegeben"
            try:
                st = os.stat(p)
                import stat
                ftype = "Ordner" if stat.S_ISDIR(st.st_mode) else "Datei"
                size = st.st_size
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.1f} KB"
                elif size < 1024 * 1024 * 1024:
                    size_str = f"{size / (1024 * 1024):.1f} MB"
                else:
                    size_str = f"{size / (1024 * 1024 * 1024):.2f} GB"
                mtime = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                ctime = datetime.fromtimestamp(st.st_ctime).strftime("%Y-%m-%d %H:%M:%S")
                perms = oct(st.st_mode)[-3:]
                lines = [
                    f"Typ: {ftype}",
                    f"Pfad: {p}",
                    f"Größe: {size_str}",
                    f"Geändert: {mtime}",
                    f"Erstellt: {ctime}",
                    f"Rechte: {perms}",
                ]
                if ftype == "Ordner":
                    try:
                        entries = os.listdir(p)
                        lines.append(f"Einträge: {len(entries)}")
                    except PermissionError:
                        lines.append("Einträge: (keine Berechtigung)")
                return "\n".join(lines)
            except FileNotFoundError:
                return f"Nicht gefunden: {p}"
            except Exception as e:
                return f"Fehler: {e}"

        if name == "recycle":
            p = args.get("path", "")
            if not p:
                return "Kein Pfad angegeben"
            if err := is_safe_write_path(p, mode):
                return err
            if not os.path.exists(p):
                return f"Nicht gefunden: {p}"
            try:
                trash = Path.home() / ".Trash"
                basename = Path(p).name
                dest = trash / basename
                if dest.exists():
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    dest = trash / f"{Path(basename).stem}_{ts}{Path(basename).suffix}"
                import shutil
                shutil.move(p, str(dest))
                log.info(f"RECYCLE: {p} -> {dest}")
                return f"In Papierkorb verschoben: {p}"
            except Exception as e:
                return f"Fehler beim Recyceln: {e}"

        if name == "create_directory":
            p = args.get("path", "")
            if not p:
                return "Kein Pfad angegeben"
            if err := is_safe_write_path(p, mode):
                return err
            try:
                Path(p).mkdir(parents=True, exist_ok=True)
                log.info(f"MKDIR: {p}")
                return f"Ordner erstellt: {p}"
            except Exception as e:
                return f"Fehler: {e}"

        if name == "web_fetch":
            url = args.get("url", "")
            if not url:
                return "Keine URL angegeben"
            if not url.startswith(("http://", "https://")):
                return "Nur http:// und https:// URLs erlaubt"
            extract = args.get("extract_text", True)
            max_chars = min(int(args.get("max_chars", 4000)), 8000)
            try:
                import httpx
                r = httpx.get(url, follow_redirects=True, timeout=15,
                              headers={"User-Agent": "BACH/3.9"})
                ct = r.headers.get("content-type", "")
                if "json" in ct:
                    return json.dumps(r.json(), indent=2, ensure_ascii=False)[:max_chars]
                text = r.text
                if extract and "html" in ct.lower():
                    try:
                        from lxml import html as lxml_html
                        doc = lxml_html.fromstring(text)
                        for el in doc.xpath("//script|//style|//noscript"):
                            el.getparent().remove(el)
                        text = doc.text_content()
                    except Exception:
                        text = re.sub(r"<[^>]+>", "", text)
                    text = re.sub(r"\n{3,}", "\n\n", text).strip()
                return text[:max_chars]
            except Exception as e:
                return f"Fehler beim Abrufen: {e}"

        return f"Unbekanntes Tool: {name}"
    except Exception as e:
        return f"Tool-Fehler ({name}): {e}"


# --- ToolProvider (ellmos-chat) ---

class BachToolProvider:
    """BACH's tools behind the module's ``ToolProvider`` protocol.

    Deliberately not a ``ToolRegistry``: BACH defines every tool the registry
    would have built in, plus the ones it does not (``bach_command``,
    ``task_manage``, ``maintain``, ``foerderbericht``, ``delegate``,
    ``ollama_info``, ``move_file``, ``copy_file``, ``recycle``), and it exposes
    ``edit_file``/``create_directory`` in Safe mode behind
    ``is_safe_write_path``. Starting from the registry would mean overriding
    almost all of it and still inheriting a ``read_file_write`` tool BACH never
    had. Adopting the module's hardened built-ins is a separate, user-visible
    decision -- its ``safe_shell`` refuses ``git``/``docker``/``curl``, which
    BACH's system prompt advertises.
    """

    def __init__(self, bach_app=None, default_model: Callable[[], str] | None = None):
        self.bach_app = bach_app
        self._default_model = default_model

    def get_tools(self, mode) -> list[dict]:
        return TOOLS_FULL if as_mode(mode) is Mode.FULL else TOOLS_SAFE

    def execute(self, name: str, args: Any, mode) -> str:
        return exec_tool(
            name,
            args,
            as_mode(mode).value,
            bach_app=self.bach_app,
            default_model=self._default_model() if self._default_model else "",
        )
