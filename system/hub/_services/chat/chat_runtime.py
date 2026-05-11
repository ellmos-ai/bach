#!/usr/bin/env python3
"""
BACH Chat Runtime
==================

Kernlogik für interaktive Chat-Sessions: Kontextmanagement, Befehle,
Tool-Use-Loop, Sicherheitsmodi, Zusammenfassung.

Backend-unabhängig — arbeitet mit jedem ModelBackend (Ollama, OpenAI, etc.).

Verwendung:
    from hub._services.chat.chat_runtime import ChatRuntime
    from hub._services.llm.model_backend import OllamaBackend

    backend = OllamaBackend()
    runtime = ChatRuntime(backend, system_prompt="Du bist ein Assistent.")
    answer = await runtime.process("Hallo!", chat_id="user123")
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

log = logging.getLogger("bach.chat")

try:
    from hub.bach_paths import BACH_DB as _RUNTIME_DB
    RUNTIME_BACH_DB = str(_RUNTIME_DB)
except ImportError:
    RUNTIME_BACH_DB = str(Path(__file__).parent.parent.parent.parent / "data" / "bach.db")


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
    "ollama", "brew", "pip", "pip3", "python3",
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


def run_shell(cmd: str, timeout: int = CMD_TIMEOUT) -> str:
    timeout = min(max(timeout, 5), 120)
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
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
        "handler": {"type": "string", "description": "Handler: status, task, mem, search, help, tools, denkarium, calendar, contact, routine, timer, countdown, news, newspaper, lesson, snapshot, partner, connector, msg, backup, web-parse, web-scrape, skills, agent, maintain, sync, abo, steuer, gesundheit, haushalt, versicherung, inbox, wiki"},
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
            with open(p, "w") as f:
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
                                     f"PYTHONIOENCODING=utf-8 python bach.py --{handler} {op_args}")
                elif action == "health":
                    return run_shell(f"cd {shlex.quote(str(Path(__file__).parent.parent.parent.parent))} && "
                                     f"PYTHONIOENCODING=utf-8 python bach.py status")
                elif action == "services":
                    checks = {
                        "GUI Dashboard (:8000)": "curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost:8000/",
                        "Ollama (:11434)": "curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost:11434/api/tags",
                    }
                    lines = ["BACH Service-Check:"]
                    lines.append(f"  ✅ Control API (:8081) — läuft (diese Anfrage)")
                    for svc, cmd in checks.items():
                        code = run_shell(cmd).strip()
                        ok = code == "200"
                        lines.append(f"  {'✅' if ok else '❌'} {svc} — HTTP {code}")
                    ps_out = run_shell("ps aux | grep -E '(telegram_chat|server\\.py|chat_tray)' | grep -v grep | wc -l")
                    lines.append(f"  Prozesse (Bot/GUI/Tray): {ps_out.strip()}")
                    lines.append(f"  Uptime: {run_shell('uptime').strip()}")
                    return "\n".join(lines)
                elif action == "sync":
                    sync_script = Path.home() / "services" / "bach" / "sync-from-onedrive.sh"
                    if not sync_script.exists():
                        return "Sync-Script nicht gefunden: ~/services/bach/sync-from-onedrive.sh"
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
                    if lock_file.exists():
                        return f"Pipeline läuft (Lock: {lock_file}). Aktenordner: {pipeline.base_path}"
                    data_roh = pipeline.base_path / "data_roh"
                    clients = [d.name for d in data_roh.iterdir() if d.is_dir()] if data_roh.exists() else []
                    prompt_exists = (pipeline.base_path / "data_bundled" / "prompt.txt").exists()
                    status = f"Pipeline bereit. Basis: {pipeline.base_path}\n"
                    status += f"Klienten in data_roh/: {', '.join(clients) if clients else 'keine'}\n"
                    status += f"Prompt vorhanden: {'ja' if prompt_exists else 'nein'}"
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
                                f"Anonymisierter Prompt: {pipeline.base_path / 'data_bundled' / 'prompt.txt'}\n"
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
                        api_key = kf.read_text().strip()
                if api_key:
                    return _delegate_claude_api(full_prompt, api_key)
                cmd = ["claude", "-p", full_prompt]
            else:
                cmd = ["codex", "exec", full_prompt]
            try:
                r = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=120,
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
            try:
                Path(p).mkdir(parents=True, exist_ok=True)
                log.info(f"MKDIR: {p}")
                return f"Ordner erstellt: {p}"
            except Exception as e:
                return f"Fehler: {e}"

        return f"Unbekanntes Tool: {name}"
    except Exception as e:
        return f"Tool-Fehler ({name}): {e}"


# --- Chat Runtime ---

class ChatSession:
    """State für eine einzelne Chat-Session."""

    def __init__(self):
        self.messages: list[dict] = []
        self.think: bool = True
        self.mode: str = "safe"
        self.model: str = ""
        self.current_tool: str = ""
        self.tool_round: int = 0
        self.last_tools: list[str] = []
        self.voice_output: bool = False


class ChatRuntime:
    """Backend-unabhängige Chat-Runtime mit Tool-Use-Loop."""

    MAX_CONTEXT_CHARS = 24000
    SUMMARIZE_THRESHOLD = 16000
    MAX_MESSAGES = 40

    def __init__(self, backend, system_prompt: str = "",
                 bach_app=None, memory_fn=None, injector=None):
        self.backend = backend
        self.base_system = system_prompt
        self.bach_app = bach_app
        self.memory = memory_fn
        self.injector = injector
        self.sessions: dict[str, ChatSession] = {}
        self.max_tool_rounds: int = 12

    def get_session(self, chat_id: str) -> ChatSession:
        if chat_id not in self.sessions:
            s = ChatSession()
            s.model = self.backend.get_default_model()
            self.sessions[chat_id] = s
        return self.sessions[chat_id]

    def clear_session(self, chat_id: str):
        self.sessions.pop(chat_id, None)

    def build_system_prompt(self, session: ChatSession) -> str:
        capabilities = """
Du hast Zugriff auf Werkzeuge (Tools), die du bei Bedarf aufrufen kannst.

SAFE-MODUS (Standard):
- list_directory, read_file, search_text — Dateisystem lesen
- edit_file — Text in Dateien ersetzen (suchen/ersetzen)
- move_file — Dateien/Ordner verschieben oder umbenennen
- copy_file — Dateien/Ordner kopieren
- file_info — Detaillierte Datei-/Ordner-Informationen
- recycle — In Papierkorb verschieben (wiederherstellbar, statt Löschen)
- create_directory — Neuen Ordner erstellen
- safe_shell — Lesende Shell-Befehle (ls, cat, grep, git, docker, ps, etc.)
- system_status — Systeminfos (CPU, RAM, Disk)
- ollama_info — Modelle und Status
- bach_command — BACH Memory, Tasks, Suche, Status
- get_datetime — Datum/Uhrzeit
- web_search — Im Internet suchen (DuckDuckGo)
- weather — Aktuelles Wetter abfragen
- task_manage — Tasks anlegen, auflisten, erledigen
- maintain — Systemwartung: fällige Tasks (check), Wartung (run), BACH-Status (health), Service-Check (services)
- delegate — Aufgabe an Claude Code oder Codex CLI delegieren

FULL-MODUS (nur nach /mode full bestätigt):
- execute_command — Beliebige Shell-Befehle
- write_file — Dateien schreiben

BACH-HANDLER (alle via bach_command nutzbar):
- denkarium write/read/search/brainstorm/promote/stats — Gedanken-Sammler und Logbuch
- calendar list/add/today/week — Termine und Kalender
- contact list/search/show — Kontaktverwaltung
- routine list/add/complete — Routinen und Gewohnheiten
- countdown list — Countdowns und Timer
- mem write/read/fact/facts/search/context — Memory-System
- lesson add/list — Lessons Learned
- help <thema> — Dokumentation zu jedem Thema (260+ Help-Dateien)

WICHTIGSTE REGEL — SUCHE ALS FALLBACK:
Wenn der User einen Service, ein Tool oder eine Funktion anfragt die du nicht kennst:
1. ZUERST: bach_command mit "help <thema>" nutzen — findet die passende Dokumentation
2. DANN: bach_command mit "search <begriff>" — durchsucht Handler, Tools und Skills
3. NIEMALS sagen "das kann ich nicht" ohne vorher gesucht zu haben
BACH hat 110+ Handler — du kennst hier nur die wichtigsten. Die Suche findet den Rest.

REGELN:
- Nutze Tools aktiv, wenn der User nach Informationen fragt
- Nutze web_search, wenn du aktuelle Informationen brauchst oder der User fragt
- Nutze task_manage, wenn der User Tasks verwalten will
- Nutze maintain, wenn der User nach Systemstatus, Wartung oder Health fragt
- Nutze delegate, wenn eine Aufgabe besser von Claude (Coding, Analyse) oder Codex (schnelle Code-Generierung) erledigt wird
- Nutze edit_file zum Bearbeiten von Dateien (suchen/ersetzen)
- Nutze recycle zum Löschen — verschiebt in den Papierkorb statt endgültig zu löschen
- Nutze weather für Wetterabfragen
- Nutze denkarium, wenn der User Gedanken notieren, im Logbuch schreiben oder brainstormen will
- Nutze calendar, wenn der User nach Terminen fragt oder welche anlegen will
- Nutze contact, wenn der User Kontakte sucht oder anzeigen will
- Nutze routine, wenn der User nach Routinen oder Gewohnheiten fragt
- Führe Befehle aus, wenn der User es wünscht
- Antworte immer auf Deutsch
- Sei präzise, hilfreich, und zeige Tool-Ergebnisse klar an
- Du KANNST Befehle ausführen — sag nicht, dass du das nicht kannst

WARTUNGSROLLE:
Du bist auch für Systemwartung zuständig. Wenn der User danach fragt:
- maintain(check) zeigt fällige wiederkehrende Tasks
- maintain(run, operation) führt Wartung aus (registry, skills, docs, backup, clean, memory, recurring)
- maintain(health) zeigt den Gesamtstatus
"""
        s = self.base_system + "\n\n" + capabilities
        s += f"\n[Modus={session.mode}, Denken={'AN' if session.think else 'AUS'}, Modell={session.model}]"
        return s

    def _get_bach_context(self, text: str) -> str:
        if not self.injector or not self.memory:
            return ""
        parts = []
        try:
            inj = self.injector.process(text)
            if inj:
                parts.append("Kontext:\n" + "\n".join(str(i) for i in inj[:3]))
        except Exception:
            pass
        try:
            ctx = self.memory("context")
            if ctx and isinstance(ctx, str) and len(ctx) > 10:
                parts.append(ctx[:2000])
        except Exception:
            pass
        return "\n\n".join(parts)

    async def process(self, text: str, chat_id: str) -> str:
        """Verarbeitet eine User-Nachricht und gibt die Antwort zurück."""
        session = self.get_session(chat_id)
        session.messages.append({"role": "user", "content": text})

        total = sum(len(m.get("content", "")) for m in session.messages)
        if total > self.SUMMARIZE_THRESHOLD or len(session.messages) > self.MAX_MESSAGES:
            await self._summarize(session)

        bach_ctx = self._get_bach_context(text)

        sys_prompt = self.build_system_prompt(session)
        if bach_ctx:
            sys_prompt += f"\n\n--- BACH ---\n{bach_ctx}"

        msgs = [{"role": "system", "content": sys_prompt}] + session.messages

        if getattr(self.backend, "manages_own_tools", False):
            try:
                result = await self.backend.chat(msgs, think=session.think,
                                                 model=session.model)
                answer = result.get("content", "(keine Antwort)")
            except Exception as e:
                answer = f"Backend-Fehler: {e}"
        else:
            tools = TOOLS_FULL if session.mode == "full" else TOOLS_SAFE
            answer = await self._tool_loop(msgs, session, tools)
        session.messages.append({"role": "assistant", "content": answer})
        return answer

    async def _tool_loop(self, msgs: list, session: ChatSession,
                         tools: list) -> str:
        max_rounds = self.max_tool_rounds
        round_num = 0
        session.tool_round = 0
        session.last_tools = []
        while True:
            if max_rounds > 0 and round_num > max_rounds:
                session.current_tool = ""
                return result.get("content", "") or "(Max Tool-Runden erreicht)"
            try:
                result = await self.backend.chat(
                    msgs, tools=tools, think=session.think, model=session.model
                )
            except Exception as e:
                session.current_tool = ""
                return f"Backend-Fehler: {e}"

            tool_calls = result.get("tool_calls")
            if not tool_calls:
                session.current_tool = ""
                return result.get("content", "(keine Antwort)")

            raw_msg = result.get("raw_message", {})
            if raw_msg:
                msgs.append(raw_msg)

            round_num += 1
            session.tool_round = round_num
            for i, tc in enumerate(tool_calls):
                fn = tc.get("function", {})
                t_name = fn.get("name", "")
                t_args = fn.get("arguments", {})
                session.current_tool = t_name
                if t_name and t_name not in session.last_tools:
                    session.last_tools = (session.last_tools + [t_name])[-5:]
                log.info(f"Tool [{round_num}]: {t_name}({json.dumps(t_args, ensure_ascii=False)[:200]})")
                t_result = exec_tool(
                    t_name, t_args, session.mode,
                    bach_app=self.bach_app,
                    default_model=session.model,
                )
                tool_call_id = ""
                if hasattr(self.backend, "_last_tool_call_ids"):
                    ids = self.backend._last_tool_call_ids
                    if i < len(ids):
                        tool_call_id = ids[i]
                msgs.append(
                    self.backend.tool_response_message(str(t_result), tool_call_id)
                )

    async def _summarize(self, session: ChatSession):
        if len(session.messages) < 6:
            return
        old = session.messages[:-4]
        recent = session.messages[-4:]

        old_text = "\n".join(
            f"{'User' if m['role'] == 'user' else 'Assistent'}: {m.get('content', '')[:300]}"
            for m in old if m.get("role") in ("user", "assistant")
        )

        prompt = [
            {"role": "system", "content": "Fasse den Gesprächsverlauf in 2-3 Sätzen zusammen."},
            {"role": "user", "content": old_text[:6000]},
        ]

        try:
            result = await self.backend.chat(prompt, think=False)
            summary = result.get("content", "")[:500]

            if self.memory:
                try:
                    self.memory("write", f"Chat: {summary[:300]}")
                except Exception:
                    pass

            session.messages = [
                {"role": "system", "content": f"Bisheriger Kontext: {summary}"}
            ] + recent
        except Exception:
            session.messages = recent
