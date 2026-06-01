"""
llmauto.modes.chain -- Ketten-Modus (Marble-Run)
==================================================
Sequentielle Agent-Ketten: Link1 -> Link2 -> ... -> LinkN -> (loop)
Portiert aus BACH_Dev/marble_run/marble.py, nutzt core-Module.
"""
import os
import sys
import time
import json
import subprocess
from pathlib import Path
from datetime import datetime

from ..core.runner import ClaudeRunner
from ..core.config import load_chain, list_chains, load_global_config, _ACTUAL_HOME, BACH_AVAILABLE, BACH_ROOT
from ..core.state import ChainState


LOG_DIR = Path(__file__).parent.parent / "logs"


def log(msg, chain_name="default", also_print=True):
    """Schreibt in Log-Datei und optional stdout."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    if also_print:
        print(line)
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / f"{chain_name}.log"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def resolve_prompt(link, chain_config):
    """Liest den Prompt-Text fuer ein Kettenglied."""
    prompt_key = link.get("prompt", "")
    prompts_section = chain_config.get("prompts", {})
    base_dir = Path(__file__).parent.parent

    # B45: bach:// URL-Schema fuer DB-Prompts (nur wenn BACH verfuegbar)
    if prompt_key.startswith("bach://"):
        prompt_name = prompt_key[len("bach://"):]
        if BACH_AVAILABLE and BACH_ROOT is not None:
            try:
                import sqlite3
                db_path = BACH_ROOT / "system" / "data" / "bach.db"
                if db_path.exists():
                    conn = sqlite3.connect(str(db_path.resolve()))
                    cursor = conn.execute(
                        "SELECT text FROM prompt_templates WHERE name = ?",
                        (prompt_name,)
                    )
                    row = cursor.fetchone()
                    conn.close()
                    if row:
                        return row[0]
            except Exception:
                pass  # Fallback auf Datei-Suche
        # Wenn nicht in DB gefunden, prompt_key ohne Prefix weiterverwenden
        prompt_key = prompt_name

    # 1. Prompt in der prompts-Sektion der Chain-Config nachschlagen
    if prompt_key in prompts_section:
        prompt_def = prompts_section[prompt_key]
        if isinstance(prompt_def, dict) and prompt_def.get("type") == "file":
            prompt_path = Path(prompt_def["path"])
            if not prompt_path.is_absolute():
                prompt_path = base_dir / prompt_path
            if prompt_path.exists():
                return prompt_path.read_text(encoding="utf-8")
            return f"Lies die Datei {prompt_path} und fuehre die darin beschriebene Aufgabe aus."
        elif isinstance(prompt_def, str):
            return prompt_def

    # 2. Direkt als Datei im prompts/ Ordner suchen
    prompt_file = base_dir / "prompts" / prompt_key
    if prompt_file.exists():
        return prompt_file.read_text(encoding="utf-8")

    # 3. Als .txt versuchen
    prompt_file_txt = base_dir / "prompts" / f"{prompt_key}.txt"
    if prompt_file_txt.exists():
        return prompt_file_txt.read_text(encoding="utf-8")

    # 4. Fallback: Prompt-Key als Datei-Referenz verwenden
    if Path(prompt_key).exists():
        return f"Lies die Datei {prompt_key} und fuehre die darin beschriebene Aufgabe aus."

    # 5. Als inline-Prompt verwenden
    return prompt_key if prompt_key else "Fuehre die naechste Aufgabe aus."


UNTIL_FULL_SUFFIX = (
    "\n\nWICHTIG: Dein Kontext ist deine Begrenzung. Arbeite so viele Aufgaben ab "
    "wie moeglich. Erst wenn du merkst, dass dein Kontext knapp wird oder eine "
    "Komprimierung stattfindet, schliesse die aktuelle Aufgabe sauber ab, "
    "schreibe ein vollstaendiges Handoff und beende dich."
)

# Lesbares Label fuer jede Selection-Strategie (B13)
SELECTION_LABELS = {
    "priority": "Nach Prioritaet (KRITISCH > HOCH > MITTEL > NIEDRIG)",
    "article_focused": "Artikelfokus -- alle Schritte fuer einen Artikel",
    "project_focused": "Projektfokus -- alle Aufgaben fuer ein Projekt",
    "fast_high_priority": "Schnelle Tasks mit hoher Prioritaet (Quick Wins)",
    "any": "Beliebig -- freie Auswahl",
    "batch": "Batch-Review (alle Worker-Aufgaben zusammen pruefen)",
    "sequential": "Sequentiell nach Plan-Reihenfolge",
}

REVIEW_SCOPE_LABELS = {
    "single": "Standard (eine Aufgabe pruefen)",
    "batch": "Batch (alle Aufgaben der Runde gemeinsam pruefen)",
}


def send_telegram_update(chain_name, state):
    """Sendet Telegram Status-Update (fehlertolerant)."""
    try:
        global_config = load_global_config()
        telegram = global_config.get("telegram", {})
        if not telegram.get("enabled", False):
            return

        import urllib.request
        import json

        bot_token = os.environ.get(
            telegram.get("bot_token_env", "LLMAUTO_TELEGRAM_BOT_TOKEN"), ""
        )
        chat_id = telegram.get("chat_id", "")

        if not bot_token or not chat_id:
            return

        runtime = f"{state.get_runtime_hours():.1f}h"
        runde = state.get_round()
        status = state.get_status()

        text = (
            f"llmauto [{chain_name}]\n"
            f"Runde: {runde} | Laufzeit: {runtime}\n"
            f"Status: {status}"
        )

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass  # Telegram ist optional


def generate_active_chain_md(chain_name, config, state, base_dir):
    """Generiert active_chain.md -- dynamisches Worker/Reviewer-Briefing.

    Schreibt in base_dir/state/active_chain.md (globale Datei fuer die
    aktuell laufende Kette). Wird beim Chain-Start aufgerufen.
    """
    mode = config.get("mode", "loop")
    desc = config.get("description", "")
    max_rounds = config.get("max_rounds", 0)
    runtime_hours = config.get("runtime_hours", 0)
    deadline = config.get("deadline", "")
    links = config.get("links", [])
    selection_strategy = config.get("selection_strategy", "")

    runde = state.get_round()
    runtime_str = f"{runtime_hours}h" if runtime_hours else "unbegrenzt"
    rounds_str = str(max_rounds) if max_rounds else "unbegrenzt"
    deadline_str = f" | Deadline: {deadline}" if deadline else ""
    selection_str = SELECTION_LABELS.get(selection_strategy, selection_strategy) if selection_strategy else "-"

    lines = [
        f"# Aktive llmauto-Kette: {chain_name}",
        "",
        f"## Ketten-Name: {config.get('chain_name', chain_name)}",
        f"## Beschreibung: {desc}",
        f"## Modus: {mode}",
        f"## Aktuelle Runde: {runde}",
        f"## Max-Runden: {rounds_str}",
        f"## Runtime-Limit: {runtime_str}{deadline_str}",
    ]

    if selection_strategy:
        lines.append(f"## Auswahl-Strategie: {selection_str}")

    lines += [
        "",
        "---",
        "",
        "### Ketten-Glieder:",
        "",
    ]

    for i, link in enumerate(links):
        role = link.get("role", "worker")
        model = link.get("model", "?")
        task_pool = link.get("task_pool", "")
        until_full = link.get("until_full", False)
        tasks_per_worker = link.get("tasks_per_worker")
        review_scope = link.get("review_scope", "")
        context_hint = link.get("context_hint", "")
        tg = "Telegram" if link.get("telegram_update", False) else "kein Telegram"
        lines.append(f"**Glied {i+1}: {link.get('name', role)}**")
        lines.append(f"- Rolle: {role} | Modell: {model}")
        if task_pool:
            lines.append(f"- Task-Pool: {task_pool}")
        if role == "worker" and tasks_per_worker is not None:
            task_label = "ALLE" if tasks_per_worker == -1 else str(tasks_per_worker)
            lines.append(f"- Aufgaben pro Runde: {task_label}")
        if until_full:
            lines.append("- Modus: until_full=true (bearbeitet bis Kontext-Limit)")
        if role == "reviewer" and review_scope:
            scope_label = REVIEW_SCOPE_LABELS.get(review_scope, review_scope)
            lines.append(f"- Review-Modus: {scope_label}")
        if context_hint:
            lines.append(f"- Strategie-Hinweis: {context_hint}")
        lines.append(f"- Benachrichtigung: {tg}")
        lines.append("")

    lines += ["---", ""]

    worker_links = [l for l in links if l.get("role") == "worker"]
    reviewer_links = [l for l in links if l.get("role") == "reviewer"]

    if worker_links:
        lines += ["### Anweisungen fuer Worker:", ""]
        # Aufgaben-Anzahl aus erstem Worker-Link
        wl0 = worker_links[0]
        tpw = wl0.get("tasks_per_worker")
        if tpw == -1:
            lines.append(
                "Bearbeite **ALLE offenen Aufgaben** fuer das aktuelle Projekt/den aktuellen Artikel. "
                "Hoere erst auf wenn keine offenen Tasks mehr vorhanden sind."
            )
        elif tpw and tpw > 1:
            lines.append(
                f"Bearbeite **{tpw} Aufgaben** in dieser Runde bevor du die Runde beendest. "
                f"Dokumentiere JEDE Aufgabe einzeln im Handoff."
            )
        elif any(l.get("until_full", False) for l in worker_links):
            lines.append(
                "Bearbeite so viele Aufgaben wie moeglich in dieser Runde. "
                "Dein Kontext ist deine Begrenzung."
            )
        else:
            lines.append("Bearbeite **1 Aufgabe** in dieser Runde.")
        if selection_strategy:
            lines.append(f"Auswahl-Strategie: {selection_str}")
        for wl in worker_links:
            pool = wl.get("task_pool", "")
            if pool:
                lines.append(f"Aufgaben-Pool: `{pool}`")
        lines.append("")

    if reviewer_links:
        rl0 = reviewer_links[0]
        rs = rl0.get("review_scope", "single")
        scope_label = REVIEW_SCOPE_LABELS.get(rs, rs)
        lines += [
            "### Anweisungen fuer Reviewer:",
            "",
            f"Review-Modus: {scope_label}",
        ]
        if rs == "batch":
            lines.append(
                "Pruefe JEDE Worker-Aufgabe separat. "
                "Gib ein Gesamturteil (APPROVED/NEEDS_FIX/BLOCKED) UND Einzelurteile pro Aufgabe."
            )
        else:
            lines.append("Pruefe die Arbeit des Workers und erteile APPROVED oder NEEDS_FIX.")
        lines.append("")

    lines += [
        "### Handoff-Format:",
        "",
        "```",
        f"# Handoff - Runde [N]",
        f"## Kette: {chain_name}",
        "## Rolle: [WORKER / REVIEWER]",
        "## Status: [DONE / NEEDS_REVIEW / BLOCKED]",
        "",
        "### Was wurde gemacht:",
        "[Konkrete Beschreibung]",
        "",
        "### Geaenderte Dateien:",
        "- [Pfad 1]: [Was geaendert]",
        "",
        "### Naechster Schritt:",
        "[Was als naechstes ansteht]",
        "```",
    ]

    out_path = base_dir / "state" / "active_chain.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


def _format_operator_steer(requests):
    """Formatiert vorgemerkte Operator-Hinweise fuer den naechsten Checkpoint."""
    if not requests:
        return ""

    lines = [
        "",
        "## Operator-Steering",
        "Am letzten sicheren Checkpoint wurde folgende Operator-Anweisung hinterlegt.",
        "Beachte sie jetzt vor allen freien Folgeentscheidungen, solange keine Sicherheitsregeln verletzt werden.",
        "",
    ]
    for idx, request in enumerate(requests, start=1):
        created_at = request.get("created_at") or "ohne Zeitstempel"
        lines.append(f"{idx}. [{created_at}] {request.get('message', '')}")
    return "\n".join(lines)


def _load_scheduler_operator_steer_from_env():
    """Liest globale Scheduler-Steering-Hinweise aus dem Environment ein."""
    raw = os.environ.get("BACH_SCHEDULER_OPERATOR_STEER")
    if not raw:
        return []

    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []

    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        return []

    normalized = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        message = str(item.get("message", "")).strip()
        if not message:
            continue
        normalized.append(
            {
                "message": message,
                "created_at": item.get("requested_at") or item.get("created_at"),
            }
        )
    return normalized


def _import_scheduler_operator_steer(state, chain_name):
    """Ueberfuehrt globale Scheduler-Hinweise in die reguläre Chain-Steering-Queue."""
    if "BACH_SCHEDULER_OPERATOR_STEER" not in os.environ:
        return 0

    requests = _load_scheduler_operator_steer_from_env()
    os.environ.pop("BACH_SCHEDULER_OPERATOR_STEER", None)
    if not requests:
        return 0

    appended = state.queue_steer_requests(requests)
    if appended:
        log(
            f"SCHEDULER-STEER importiert: {len(appended)} Hinweis(e) fuer den naechsten Checkpoint.",
            chain_name,
        )
    return len(appended)


def _apply_operator_controls(chain_name, state, config):
    """Wendet Pause-/Steuerungswuensche an sicheren Checkpoints an."""
    pause_request = state.get_pause_request()
    if pause_request:
        pause_reason = pause_request.get("reason", "Manuell pausiert")
        if state.get_status() != "PAUSED":
            log(f"PAUSE angefordert: {pause_reason}", chain_name)
            state.set_status("PAUSED")

        while state.is_pause_requested():
            should_stop, reason = state.check_shutdown(config)
            if should_stop:
                return False, "", reason
            time.sleep(2)

        log("PAUSE aufgehoben, Kette laeuft weiter.", chain_name)
        if state.get_status() == "PAUSED":
            state.set_status("RUNNING")

    steer_requests = state.consume_steer_requests()
    if steer_requests:
        log(
            f"STEER uebernommen: {len(steer_requests)} Operator-Hinweis(e) fuer den naechsten Modelllauf.",
            chain_name,
        )
    return True, _format_operator_steer(steer_requests), ""


def run_parallel_workers(chain_name, worker_links, config, state, global_config, base_dir, operator_steer=""):
    """Fuehrt Worker-Links parallel aus (SQ016).

    Args:
        chain_name: Name der Kette
        worker_links: Liste von Link-Dicts mit role="worker"
        config: Chain-Konfiguration
        state: ChainState-Objekt
        global_config: Globale llmauto-Konfiguration
        base_dir: llmauto Base-Verzeichnis

    Returns:
        dict: Mapping link_name -> Result-Dict
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _execute_worker(link):
        link_name = link.get("name", "worker")
        model = link.get("model") or global_config.get("default_model", "claude-sonnet-4-6")
        fallback = link.get("fallback_model")

        runner = ClaudeRunner(
            model=model,
            fallback_model=fallback,
            permission_mode=global_config.get("default_permission_mode", "dontAsk"),
            allowed_tools=global_config.get("default_allowed_tools"),
            timeout=global_config.get("default_timeout_seconds", 1800),
            cwd=str(base_dir),
        )

        prompt_text = resolve_prompt(link, config)
        home_win = _ACTUAL_HOME.rstrip(os.sep)
        drive, rest = home_win.split(":", 1)
        home_bash = "/" + drive.lower() + rest.replace("\\", "/")
        prompt_text = prompt_text.replace("{HOME}", home_win)
        prompt_text = prompt_text.replace("{BASH_HOME}", home_bash)

        if link.get("until_full", False):
            prompt_text += UNTIL_FULL_SUFFIX
        if operator_steer:
            prompt_text += operator_steer

        log(f"[PARALLEL] {link_name}: Starte {model}...", chain_name)
        result = runner.run(prompt_text)

        return link_name, result

    max_workers = min(len(worker_links), 4)
    results = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_execute_worker, link): link for link in worker_links}

        for future in as_completed(futures):
            link = futures[future]
            link_name = link.get("name", "worker")
            try:
                name, result = future.result()
                results[name] = result

                # Output-Log schreiben
                output_log = LOG_DIR / f"{chain_name}_{name}.log"
                try:
                    with open(output_log, "a", encoding="utf-8") as f:
                        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        f.write(f"\n{'='*60}\n[{ts}] PARALLEL | {name}\n{'='*60}\n")
                        if result["output"]:
                            f.write(result["output"] + "\n")
                        if result["stderr"]:
                            f.write(f"\n--- STDERR ---\n{result['stderr']}\n")
                except Exception:
                    pass

                if result["success"]:
                    log(f"[PARALLEL] {name}: OK ({result['duration_s']:.0f}s)", chain_name)
                else:
                    log(f"[PARALLEL] {name}: FEHLER (rc={result['returncode']})", chain_name)
            except Exception as e:
                log(f"[PARALLEL] {link_name}: EXCEPTION: {e}", chain_name)
                results[link_name] = {
                    "success": False, "output": "", "stderr": str(e),
                    "returncode": -4, "duration_s": 0, "model": "unknown",
                }

    return results


def run_chain(chain_name, background=False):
    """Startet eine Kette (Hauptfunktion)."""
    base_dir = Path(__file__).parent.parent

    # Chain-Config laden
    config = load_chain(chain_name)
    links = config.get("links", [])
    if not links:
        print(f"Fehler: Kette '{chain_name}' hat keine Glieder (links).")
        return 1

    mode = config.get("mode", "loop")
    state = ChainState(chain_name, base_dir)

    # Hintergrund-Start
    if background:
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        env["PYTHONIOENCODING"] = "utf-8"
        # PYTHONPATH muss das Parent-Verzeichnis enthalten, damit
        # "python -m llmauto" das Paket findet (base_dir IST das Paket)
        parent_dir = str(base_dir.parent)
        env["PYTHONPATH"] = parent_dir
        subprocess.Popen(
            [sys.executable, "-m", "llmauto", "chain", "start", chain_name],
            env=env,
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0,
            cwd=parent_dir
        )
        print(f"Kette '{chain_name}' im Hintergrund gestartet (neues Fenster).")
        print(f"Status:  python -m llmauto chain status {chain_name}")
        print(f"Stoppen: python -m llmauto chain stop {chain_name}")
        return 0

    # Startzeit + Status setzen
    state.record_start()
    state.set_status("RUNNING")
    _import_scheduler_operator_steer(state, chain_name)

    # Dynamisches Worker/Reviewer-Briefing generieren (B12)
    generate_active_chain_md(chain_name, config, state, base_dir)

    log("=" * 60, chain_name)
    log(f"CHAIN GESTARTET: {chain_name}", chain_name)
    log(f"Modus: {mode} | Glieder: {len(links)} | Max-Runden: {config.get('max_rounds', '∞')}", chain_name)
    log(f"Runtime-Limit: {config.get('runtime_hours', 0)}h | Deadline: {config.get('deadline', '-')}", chain_name)
    log("=" * 60, chain_name)

    global_config = load_global_config()
    telegram_interval = 0  # Zaehler fuer Telegram-Updates

    try:
        while True:
            # SQ016: Parallele Worker-Ausfuehrung wenn aktiviert
            if config.get("parallel_workers", False):
                worker_links = [l for l in links if l.get("role") == "worker"]
                non_worker_links = [(i, l) for i, l in enumerate(links) if l.get("role") != "worker"]

                if len(worker_links) > 1:
                    # Shutdown-Check
                    should_stop, reason = state.check_shutdown(config)
                    if should_stop:
                        log(f"SHUTDOWN: {reason}", chain_name)
                        state.set_status("STOPPED")
                        send_telegram_update(chain_name, state)
                        return 0

                    can_continue, operator_steer, control_reason = _apply_operator_controls(
                        chain_name, state, config
                    )
                    if not can_continue:
                        log(f"SHUTDOWN: {control_reason}", chain_name)
                        state.set_status("STOPPED")
                        send_telegram_update(chain_name, state)
                        return 0

                    # Worker parallel ausfuehren
                    log(f"PARALLEL-MODUS: {len(worker_links)} Worker starten...", chain_name)
                    run_parallel_workers(
                        chain_name,
                        worker_links,
                        config,
                        state,
                        global_config,
                        base_dir,
                        operator_steer=operator_steer,
                    )

                    # Status-Schutz nach paralleler Ausfuehrung
                    current_status = state.get_status()
                    if current_status not in ("RUNNING", "ALL_DONE"):
                        log(f"  STATUS-KORREKTUR: '{current_status}' -> 'RUNNING'", chain_name)
                        state.set_status("RUNNING")

                    # Non-Worker (Reviewer etc.) sequentiell ausfuehren
                    for i, link in non_worker_links:
                        should_stop, reason = state.check_shutdown(config)
                        if should_stop:
                            log(f"SHUTDOWN: {reason}", chain_name)
                            state.set_status("STOPPED")
                            send_telegram_update(chain_name, state)
                            return 0

                        can_continue, operator_steer, control_reason = _apply_operator_controls(
                            chain_name, state, config
                        )
                        if not can_continue:
                            log(f"SHUTDOWN: {control_reason}", chain_name)
                            state.set_status("STOPPED")
                            send_telegram_update(chain_name, state)
                            return 0

                        link_name = link.get("name", f"link-{i+1}")
                        role = link.get("role", "worker")
                        model = link.get("model") or global_config.get("default_model", "claude-sonnet-4-6")
                        fallback = link.get("fallback_model")

                        runner = ClaudeRunner(
                            model=model,
                            fallback_model=fallback,
                            permission_mode=global_config.get("default_permission_mode", "dontAsk"),
                            allowed_tools=global_config.get("default_allowed_tools"),
                            timeout=global_config.get("default_timeout_seconds", 1800),
                            cwd=str(base_dir),
                        )

                        prompt_text = resolve_prompt(link, config)
                        home_win = _ACTUAL_HOME.rstrip(os.sep)
                        drive, rest = home_win.split(":", 1)
                        home_bash = "/" + drive.lower() + rest.replace("\\", "/")
                        prompt_text = prompt_text.replace("{HOME}", home_win)
                        prompt_text = prompt_text.replace("{BASH_HOME}", home_bash)

                        if link.get("until_full", False):
                            prompt_text += UNTIL_FULL_SUFFIX
                        if operator_steer:
                            prompt_text += operator_steer

                        log(f"{link_name} ({role}): Starte {model}...", chain_name)
                        result = runner.run(prompt_text)

                        # Output-Log
                        output_log = LOG_DIR / f"{chain_name}_{link_name}.log"
                        try:
                            with open(output_log, "a", encoding="utf-8") as f:
                                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                f.write(f"\n{'='*60}\n")
                                f.write(f"[{ts}] Runde {state.get_round()+1} | {link_name} | {model}\n")
                                f.write(f"{'='*60}\n")
                                if result["output"]:
                                    f.write(result["output"] + "\n")
                                if result["stderr"]:
                                    f.write(f"\n--- STDERR ---\n{result['stderr']}\n")
                        except Exception as e:
                            log(f"  WARNUNG: Output-Log fehlgeschlagen: {e}", chain_name)

                        if result["success"]:
                            log(f"{link_name}: OK ({result['duration_s']:.0f}s)", chain_name)
                        else:
                            log(f"{link_name}: FEHLER (rc={result['returncode']}, {result['duration_s']:.0f}s)", chain_name)
                            time.sleep(30)

                        current_status = state.get_status()
                        if current_status not in ("RUNNING", "ALL_DONE"):
                            log(f"  STATUS-KORREKTUR: '{current_status}' -> 'RUNNING'", chain_name)
                            state.set_status("RUNNING")

                        if link.get("telegram_update", False):
                            send_telegram_update(chain_name, state)

                        time.sleep(5)

                    # Runde abschliessen
                    current_round = state.increment_round()
                    log(f"RUNDE {current_round} ABGESCHLOSSEN (parallel)", chain_name)

                    if mode in ("once", "deadend"):
                        log(f"Modus '{mode}': Kette beendet nach einem Durchlauf.", chain_name)
                        state.set_status("COMPLETED")
                        send_telegram_update(chain_name, state)
                        return 0

                    continue

            # Bestehende sequentielle Logik (unveraendert)
            for i, link in enumerate(links):
                # Shutdown-Check vor jedem Glied
                should_stop, reason = state.check_shutdown(config)
                if should_stop:
                    log(f"SHUTDOWN: {reason}", chain_name)
                    state.set_status("STOPPED")
                    send_telegram_update(chain_name, state)
                    return 0

                can_continue, operator_steer, control_reason = _apply_operator_controls(
                    chain_name, state, config
                )
                if not can_continue:
                    log(f"SHUTDOWN: {control_reason}", chain_name)
                    state.set_status("STOPPED")
                    send_telegram_update(chain_name, state)
                    return 0

                link_name = link.get("name", f"link-{i+1}")
                role = link.get("role", "worker")
                model = link.get("model") or global_config.get("default_model", "claude-sonnet-4-6")
                fallback = link.get("fallback_model")

                # Continue-Modus: Dediziertes CWD damit --continue
                # immer die eigene letzte Session fortsetzt
                use_continue = link.get("continue", False)
                if use_continue:
                    link_cwd = state.state_dir / f"{link_name}-workspace"
                    link_cwd.mkdir(parents=True, exist_ok=True)
                    marker = link_cwd / ".session_marker"
                    is_continuation = marker.exists()
                    runner_cwd = str(link_cwd)
                else:
                    is_continuation = False
                    runner_cwd = str(base_dir)

                # Runner erstellen
                runner = ClaudeRunner(
                    model=model,
                    fallback_model=fallback,
                    permission_mode=global_config.get("default_permission_mode", "dontAsk"),
                    allowed_tools=global_config.get("default_allowed_tools"),
                    timeout=global_config.get("default_timeout_seconds", 1800),
                    cwd=runner_cwd,
                )

                # Prompt aufloesen + {HOME} durch tatsaechliches User-Home ersetzen
                prompt_text = resolve_prompt(link, config)
                home_win = _ACTUAL_HOME.rstrip(os.sep)  # z.B. C:\Users\YourUsername
                # C:\Users\YourUsername -> /c/Users/YourUsername (nur Laufwerksbuchstabe lowercase)
                drive, rest = home_win.split(":", 1)
                home_bash = "/" + drive.lower() + rest.replace("\\", "/")  # z.B. /c/Users/YourUsername
                prompt_text = prompt_text.replace("{HOME}", home_win)
                prompt_text = prompt_text.replace("{BASH_HOME}", home_bash)

                # until_full: Kontext-Begrenzungs-Hinweis anhaengen
                if link.get("until_full", False):
                    prompt_text += UNTIL_FULL_SUFFIX
                if operator_steer:
                    prompt_text += operator_steer

                if is_continuation:
                    log(f"{link_name} ({role}): CONTINUE {model}...", chain_name)
                else:
                    log(f"{link_name} ({role}): Starte {model}...", chain_name)
                result = runner.run(prompt_text, continue_conversation=is_continuation)

                # Output-Log: stdout/stderr jedes Glieds in eigene Datei schreiben
                output_log = LOG_DIR / f"{chain_name}_{link_name}.log"
                try:
                    with open(output_log, "a", encoding="utf-8") as f:
                        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        f.write(f"\n{'='*60}\n")
                        f.write(f"[{ts}] Runde {state.get_round()+1} | {link_name} | {model}\n")
                        f.write(f"{'='*60}\n")
                        if result["output"]:
                            f.write(result["output"])
                            f.write("\n")
                        if result["stderr"]:
                            f.write(f"\n--- STDERR ---\n{result['stderr']}\n")
                except Exception as e:
                    log(f"  WARNUNG: Output-Log fehlgeschlagen: {e}", chain_name)

                # Nach erstem erfolgreichen Run: Marker setzen
                if use_continue and result["success"] and not is_continuation:
                    marker.touch()

                if result["success"]:
                    log(f"{link_name}: OK ({result['duration_s']:.0f}s)", chain_name)
                else:
                    log(f"{link_name}: FEHLER (rc={result['returncode']}, {result['duration_s']:.0f}s)", chain_name)
                    stderr_short = result["stderr"][:200] if result["stderr"] else ""
                    if stderr_short:
                        log(f"  stderr: {stderr_short}", chain_name)
                    time.sleep(30)  # Bei Fehler laenger warten

                # Status-Schutz: Worker darf RUNNING nicht ueberschreiben
                # (LLMs schreiben manchmal COMPLETED/DONE in status.txt)
                current_status = state.get_status()
                if current_status not in ("RUNNING", "ALL_DONE"):
                    log(f"  STATUS-KORREKTUR: '{current_status}' -> 'RUNNING' (Worker hat status.txt manipuliert)", chain_name)
                    state.set_status("RUNNING")

                # Telegram-Update wenn fuer dieses Glied aktiviert
                telegram_interval += 1
                if link.get("telegram_update", False):
                    send_telegram_update(chain_name, state)

                # Kurze Pause zwischen Gliedern
                time.sleep(5)

            # Nach vollem Zyklus
            current_round = state.increment_round()
            log(f"RUNDE {current_round} ABGESCHLOSSEN", chain_name)

            # Bei mode "once" / "deadend": nach einem Durchlauf aufhoeren
            if mode in ("once", "deadend"):
                log(f"Modus '{mode}': Kette beendet nach einem Durchlauf.", chain_name)
                state.set_status("COMPLETED")
                send_telegram_update(chain_name, state)
                return 0

    except KeyboardInterrupt:
        log("MANUELL GESTOPPT (Ctrl+C)", chain_name)
        state.set_status("STOPPED")
        return 0


def show_status(chain_name=None, base_dir=None):
    """Zeigt Status einer oder aller Ketten."""
    if base_dir is None:
        base_dir = Path(__file__).parent.parent
    state_dir = base_dir / "state"

    if chain_name:
        names = [chain_name]
    else:
        # Alle Ketten mit State-Verzeichnis
        if state_dir.exists():
            names = [d.name for d in state_dir.iterdir() if d.is_dir()]
        else:
            names = []

    if not names:
        print("Keine laufenden oder beendeten Ketten gefunden.")
        return 0

    for name in names:
        state = ChainState(name, base_dir)
        status = state.get_status()
        runde = state.get_round()
        runtime = f"{state.get_runtime_hours():.1f}h" if state.start_time_file.exists() else "-"

        # Aus handoff lesen
        handoff = state.get_handoff()
        last_task, last_status, last_role = "-", "-", "-"
        for line in handoff.split("\n"):
            if line.startswith("## Task:"):
                last_task = line.split(":", 1)[1].strip()
            elif line.startswith("## Status:") or line.startswith("## Urteil:"):
                last_status = line.split(":", 1)[1].strip()
            elif line.startswith("## Rolle:"):
                last_role = line.split(":", 1)[1].strip()

        # Chain-Config laden fuer max_rounds/runtime_hours
        try:
            config = load_chain(name)
            max_rounds = config.get("max_rounds", "?")
            max_runtime = f"{config.get('runtime_hours', '?')}h"
        except FileNotFoundError:
            max_rounds = "?"
            max_runtime = "?"

        print("=" * 50)
        print(f"  KETTE: {name}")
        print("=" * 50)
        print(f"  Status:       {status}")
        print(f"  Runde:        {runde} / {max_rounds}")
        print(f"  Laufzeit:     {runtime} / {max_runtime} max")
        print(f"  Letztes Glied: {last_role}")
        print(f"  Letzter Task: {last_task}")
        print(f"  Task-Status:  {last_status}")

        if state.is_stop_requested():
            print(f"  !!! STOP: {state.get_stop_reason()}")
        pause_request = state.get_pause_request()
        if pause_request:
            print(f"  !!! PAUSE: {pause_request.get('reason', 'Manuell pausiert')}")
        steer_requests = state.peek_steer_requests()
        if steer_requests:
            print(f"  !!! STEER: {len(steer_requests)} Nachricht(en) vorgemerkt")
            last_message = steer_requests[-1].get("message", "")
            if last_message:
                preview = last_message[:80]
                print(f"      Zuletzt: {preview}")

        print("=" * 50)
        print()

    return 0


def stop_chain(chain_name, reason=None):
    """Erstellt STOP-Datei fuer eine Kette."""
    base_dir = Path(__file__).parent.parent
    state = ChainState(chain_name, base_dir)
    reason = reason or "Manuell gestoppt via llmauto"
    state.request_stop(reason)
    print(f"STOP-Datei erstellt fuer '{chain_name}'.")
    print(f"Pipeline stoppt nach aktuellem Glied.")
    print(f"Grund: {reason}")
    return 0


def pause_chain(chain_name, reason=None):
    """Merkt eine Pause fuer den naechsten sicheren Checkpoint vor."""
    base_dir = Path(__file__).parent.parent
    state = ChainState(chain_name, base_dir)
    reason = reason or "Manuell pausiert via llmauto"
    payload = state.request_pause(reason)
    print(f"PAUSE-Datei erstellt fuer '{chain_name}'.")
    print("Die Kette pausiert vor dem naechsten Modelllauf oder nach dem aktuellen Glied.")
    print(f"Grund: {payload.get('reason')}")
    return 0


def resume_chain(chain_name):
    """Hebt eine vorgemerkte Pause auf."""
    base_dir = Path(__file__).parent.parent
    state = ChainState(chain_name, base_dir)
    if not state.is_pause_requested():
        print(f"Keine Pause fuer '{chain_name}' vorgemerkt.")
        return 0
    state.clear_pause()
    if state.get_status() == "PAUSED":
        state.set_status("RUNNING")
    print(f"Pause fuer '{chain_name}' aufgehoben.")
    print("Die Kette wird am naechsten Poll/Checkpoint fortgesetzt.")
    return 0


def steer_chain(chain_name, message):
    """Haengt einen Operator-Hinweis an den naechsten sicheren Checkpoint."""
    base_dir = Path(__file__).parent.parent
    state = ChainState(chain_name, base_dir)
    state.request_steer(message)
    pending = state.peek_steer_requests()
    print(f"Steering fuer '{chain_name}' vorgemerkt.")
    print(f"Nachrichten in Queue: {len(pending)}")
    print("Die Hinweise werden vor dem naechsten Modelllauf in den Prompt eingeblendet.")
    return 0


def show_log(chain_name, lines=20):
    """Zeigt Log-Eintraege einer Kette."""
    log_file = LOG_DIR / f"{chain_name}.log"
    if not log_file.exists():
        print(f"Kein Log fuer '{chain_name}' vorhanden.")
        return 0
    content = log_file.read_text(encoding="utf-8").strip().split("\n")
    for line in content[-lines:]:
        print(line)
    return 0


def reset_chain(chain_name):
    """Setzt State einer Kette zurueck."""
    base_dir = Path(__file__).parent.parent
    state = ChainState(chain_name, base_dir)
    state.reset()
    print(f"Kette '{chain_name}' zurueckgesetzt auf Runde 0.")
    print(f"Starten mit: python -m llmauto chain start {chain_name}")
    return 0
