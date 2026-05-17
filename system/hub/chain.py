# SPDX-License-Identifier: MIT
"""
Chain Handler - Ausfuehrung von verketteten Tool-Befehlen
=========================================================

Unterstuetzt zwei Chain-Typen:
  1. Toolchains (DB): Sequentielle BACH-Befehle ohne LLM
  2. llmauto-Ketten (JSON): LLM-Agenten-Ketten via llmauto

Toolchain-Befehle (DB):
  bach chain list                Alle Chains anzeigen (beide Typen)
  bach chain run <id>            Toolchain ausfuehren
  bach chain add "JSON"          Neue Toolchain erstellen
  bach chain show <id>           Details ansehen
  bach chain log <id>            Logs einer Toolchain

llmauto-Befehle (JSON):
  bach chain create <name>       Neue llmauto-Kette erstellen (CLI)
  bach chain start <name>        llmauto-Kette starten (Hintergrund)
  bach chain stop <name>         llmauto-Kette stoppen
  bach chain pause <name>        llmauto-Kette am Checkpoint pausieren
  bach chain resume <name>       llmauto-Kette fortsetzen
  bach chain steer <name> "..."  Operator-Hinweis für nächsten Checkpoint
  bach chain status [name]       llmauto-Status anzeigen
  bach chain reset <name>        llmauto-State zuruecksetzen

Ref: SYS_002, SQ074
"""
import os
import sqlite3
import json
import time
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from .base import BaseHandler

class ChainHandler(BaseHandler):
    """Handler fuer Toolchains"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = self._canonical_db

    @property
    def profile_name(self) -> str:
        return "chain"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            # Toolchain-Operationen (DB)
            "list": "Alle Chains auflisten (Toolchains + llmauto-Ketten)",
            "run": "Toolchain ausfuehren (DB)",
            "add": "Neue Toolchain erstellen (DB)",
            "show": "Details einer Toolchain (DB)",
            "delete": "Toolchain loeschen (DB)",
            "log": "Logs einer Toolchain anzeigen (DB)",
            # llmauto-Operationen (JSON)
            "create": "Neue llmauto-Kette erstellen: bach chain create <name> [--mode once|loop] ...",
            "start": "llmauto-Kette starten: bach chain start <name>",
            "stop": "llmauto-Kette stoppen: bach chain stop <name>",
            "pause": "llmauto-Kette pausieren: bach chain pause <name> [Grund]",
            "resume": "llmauto-Kette fortsetzen: bach chain resume <name>",
            "steer": "llmauto-Kette steuern: bach chain steer <name> \"Hinweis\"",
            "status": "llmauto-Status anzeigen: bach chain status [name]",
            "reset": "llmauto-State zuruecksetzen: bach chain reset <name>",
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        # --- Toolchain-Operationen (DB) ---
        if operation == "list":
            return self._list()
        elif operation == "run":
            if not args: return False, "ID benoetigt: bach chain run <id>"
            return self._run(args[0], dry_run)
        elif operation == "add":
            return self._add(args)
        elif operation == "show":
            if not args: return False, "ID benoetigt: bach chain show <id>"
            return self._show(args[0])
        elif operation == "delete":
            if not args: return False, "ID benoetigt: bach chain delete <id>"
            return self._delete(args[0])
        elif operation == "log":
            if not args: return False, "ID benoetigt: bach chain log <id>"
            return self._log(args[0])
        # --- llmauto-Operationen (JSON) ---
        elif operation == "create":
            return self._create(args)
        elif operation == "start":
            if not args: return False, "Name benoetigt: bach chain start <name>"
            return self._llmauto_start(args[0])
        elif operation == "stop":
            if not args: return False, "Name benoetigt: bach chain stop <name>"
            return self._llmauto_stop(args[0])
        elif operation == "pause":
            if not args: return False, "Name benoetigt: bach chain pause <name> [Grund]"
            reason = " ".join(args[1:]) if len(args) > 1 else None
            return self._llmauto_pause(args[0], reason)
        elif operation == "resume":
            if not args: return False, "Name benoetigt: bach chain resume <name>"
            return self._llmauto_resume(args[0])
        elif operation == "steer":
            if len(args) < 2:
                return False, "Name und Hinweis benoetigt: bach chain steer <name> \"Hinweis\""
            return self._llmauto_steer(args[0], " ".join(args[1:]))
        elif operation == "status":
            name = args[0] if args else None
            return self._llmauto_status(name)
        elif operation == "reset":
            if not args: return False, "Name benoetigt: bach chain reset <name>"
            return self._llmauto_reset(args[0])
        else:
            return False, f"Unbekannte Operation: {operation}"

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _list(self) -> tuple:
        lines = []

        # --- Abschnitt 1: llmauto-Ketten (JSON) ---
        llmauto_names = self._list_llmauto_chains()
        if llmauto_names:
            lines.append("LLMAUTO-KETTEN")
            lines.append("=" * 40)
            lines.append(f"{'Name':<30} {'Modus':<8} {'Status':<12} Beschreibung")
            lines.append("-" * 75)
            for name in llmauto_names:
                try:
                    cfg_path = self.base_path / "tools" / "llmauto" / "chains" / f"{name}.json"
                    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                    mode = cfg.get("mode", "loop")
                    desc = cfg.get("description", "")[:35]
                    # Status aus state-Datei lesen (optional)
                    state_file = self.base_path / "tools" / "llmauto" / "state" / name / "status.txt"
                    status = state_file.read_text(encoding="utf-8").strip() if state_file.exists() else "-"
                    lines.append(f"{name:<30} {mode:<8} {status:<12} {desc}")
                except Exception:
                    lines.append(f"{name:<30} (Fehler beim Laden)")
            lines.append("")

        # --- Abschnitt 2: Toolchains (DB) ---
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT * FROM toolchains ORDER BY id").fetchall()
            if rows:
                lines.append("TOOLCHAINS (DB)")
                lines.append("=" * 40)
                lines.append(f"{'ID':<4} {'Name':<30} {'Trigger':<10} {'Active':<6} {'Last Run'}")
                lines.append("-" * 70)
                for r in rows:
                    active = "Yes" if r['is_active'] else "No"
                    last = r['last_run'] if r['last_run'] else "Never"
                    lines.append(f"{r['id']:<4} {r['name']:<30} {r['trigger_type']:<10} {active:<6} {last}")
        finally:
            conn.close()

        if not lines:
            return True, "Keine Chains definiert."

        return True, "\n".join(lines)

    def _run(self, chain_id: str, dry_run: bool) -> tuple:
        conn = self._get_conn()
        try:
            # Chain laden
            chain = conn.execute("SELECT * FROM toolchains WHERE id = ?", (chain_id,)).fetchone()
            if not chain:
                return False, f"Chain {chain_id} nicht gefunden."

            try:
                steps = json.loads(chain['steps_json'])
            except json.JSONDecodeError:
                return False, "Fehlerhaftes JSON in steps_definition."

            triggered_by = "manual"  # Default

            if dry_run:
                msg = [f"[DRY-RUN] Chain '{chain['name']}' ({len(steps)} Steps):"]
                self._dry_run_recursive(steps, msg, indent=1)
                return True, "\n".join(msg)

            # Ausfuehrung
            start_time = time.time()
            started_at_iso = datetime.now().isoformat()
            logs = []
            success = True
            
            print(f"Starte Chain '{chain['name']}'...")
            
            # Recursive execution needed for blocks
            steps_completed, failure_occurred, final_output_log, final_error_log = self._execute_steps(steps, logs)
            
            if failure_occurred:
                success = False

            duration = time.time() - start_time
            finished_at_iso = datetime.now().isoformat()
            status = 'success' if success else 'failed'
            
            # Run loggen (Updated Schema)
            # Schema: chain_id, status, log, duration_seconds, finished_at, steps_completed, steps_total, output, error, triggered_by
            full_log = "\n".join(logs)
            conn.execute("""
                INSERT INTO toolchain_runs (
                    chain_id, status, log, duration_seconds, started_at, finished_at,
                    steps_completed, steps_total, output, error, triggered_by
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                chain_id, status, full_log, duration, started_at_iso, finished_at_iso,
                steps_completed, len(steps), final_output_log, final_error_log, triggered_by
            ))
            
            # Last Run update
            conn.execute("UPDATE toolchains SET last_run = CURRENT_TIMESTAMP WHERE id = ?", (chain_id,))
            conn.commit()
            
            return True, f"Chain beendet ({status}, {duration:.2f}s).\nDetails: bach chain log {chain_id}"
            
        finally:
            conn.close()

    def _dry_run_recursive(self, steps, msg_list, indent):
        for i, step in enumerate(steps):
            prefix = "  " * indent
            if 'parallel' in step and step['parallel']:
                msg_list.append(f"{prefix}{i+1}. [PARALLEL BLOCK]")
                substeps = step.get('tools', [])
                for sub in substeps:
                     msg_list.append(f"{prefix}  - {sub.get('tool')} {sub.get('args')}")
            else:
                msg_list.append(f"{prefix}{i+1}. {step.get('tool')} {step.get('args')}")

    def _execute_steps(self, steps: list, logs: list) -> tuple:
        """
        Recursive execution engine.
        Returns: (steps_completed_count, failure_occurred, output_str, error_str)
        """
        import concurrent.futures
        
        steps_completed = 0
        failure_occurred = False
        outputs = []
        errors = []
        
        for i, step in enumerate(steps):
            # 1. PARALLEL EXECUTION
            if 'parallel' in step and step['parallel'] is True:
                subtools = step.get('tools', [])
                log_entry = f"Step {i+1}: Start Parallel Block ({len(subtools)} Tasks)"
                print(f"  > [PARALLEL] {len(subtools)} Tasks...")
                logs.append(log_entry)
                
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    futures = []
                    for subt in subtools:
                        futures.append(executor.submit(self._run_single_tool, subt))
                    
                    for future in concurrent.futures.as_completed(futures):
                        res = future.result()
                        # Merge parallel logs
                        logs.append(f"    [THREAD] {res['tool']}: {'SUCCESS' if res['success'] else 'FAILED'}\n{res['log']}")
                        if res['output']: outputs.append(res['output'])
                        if res['error']: errors.append(res['error'])
                        if not res['success']:
                            failure_occurred = True
                
                steps_completed += 1 # Count block as 1 step
                
            # 2. SEQUENTIAL EXECUTION
            else:
                res = self._run_single_tool(step)
                
                step_log = f"Step {i+1}: {step.get('tool')} {step.get('args')}\n"
                logs.append(step_log + res['log'])
                if res['output']: outputs.append(res['output'])
                if res['error']: errors.append(res['error'])
                
                if res['success']:
                    steps_completed += 1
                else:
                    failure_occurred = True
                    # ON FAILURE HANDLING
                    action = "abort" # default
                    if 'on_failure' in step:
                        on_fail = step['on_failure']
                        action = on_fail.get('action', 'abort')
                        msg = on_fail.get('message', 'Fehler aufgetreten')
                        logs.append(f"  [ON_FAILURE] {msg} -> Action: {action}")
                        print(f"    [ON_FAILURE] {msg} -> {action}")
                    
                    if action == 'abort':
                        logs.append("  [ABORT] Chain abgebrochen.")
                        break
                    elif action == 'continue':
                        logs.append("  [CONTINUE] Fehler ignoriert.")
                        failure_occurred = False # Reset flag if we continue explicitly? Or keep it? Let's keep it to mark run as "warning" ideally.
                        # But for now, simple boolean logic: if we continue, we proceed.
                    # 'retry' not implemented yet simple
                    
        final_out = "\n".join(outputs)
        final_err = "\n".join(errors)
        return steps_completed, failure_occurred, final_out, final_err

    def _run_single_tool(self, step_def: dict) -> dict:
        """
        Runs a single tool command and returns dict with results.
        """
        tool = step_def.get('tool')
        args = step_def.get('args', [])
        
        # Command build
        cmd = [sys.executable, "bach.py", tool] + [str(a) for a in args]
        
        print(f"  > {tool} {' '.join(str(x) for x in args)}")
        
        start = time.time()
        res = {
            "tool": tool,
            "success": False,
            "log": "",
            "output": "",
            "error": ""
        }
        
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace',
                cwd=str(self.base_path)
            )
            
            duration = time.time() - start
            res['output'] = proc.stdout
            res['error'] = proc.stderr
            
            if proc.returncode == 0:
                res['success'] = True
                res['log'] = f"[OK] ({duration:.2f}s) {proc.stdout[:200]}..."
            else:
                res['success'] = False
                res['log'] = f"[FAILED] ({duration:.2f}s) Code {proc.returncode}\nStderr: {proc.stderr}"
                
        except Exception as e:
            res['success'] = False
            res['error'] = str(e)
            res['log'] = f"[EXCEPTION] {e}"
            
        return res

    def _add(self, args: list) -> tuple:
        # Erwartet JSON-String als Argument oder interaktives Bauen (vereinfacht: Name + JSON)
        # Usage: bach chain add "Name" --steps '[{"tool":"scan","args":["--mode","quick"]}]'
        
        if len(args) < 1:
            return False, 'Usage: bach chain add "Name" --steps \'[...]\' [--trigger manual]'
            
        name = args[0]
        steps_json = "[]"
        trigger = "manual"
        
        # Argument parsing manually
        for i, arg in enumerate(args):
            if arg == "--steps" and i+1 < len(args):
                steps_json = args[i+1]
            elif arg == "--trigger" and i+1 < len(args):
                trigger = args[i+1]

        # Validierung
        try:
            json.loads(steps_json)
        except (json.JSONDecodeError, TypeError):
             return False, "Ungueltiges JSON fuer Steps."

        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT INTO toolchains (name, steps_json, trigger_type)
                VALUES (?, ?, ?)
            """, (name, steps_json, trigger))
            conn.commit()
            return True, f"Chain '{name}' erstellt."
        finally:
            conn.close()

    def _show(self, chain_id: str) -> tuple:
        conn = self._get_conn()
        try:
            chain = conn.execute("SELECT * FROM toolchains WHERE id = ?", (chain_id,)).fetchone()
            if not chain: return False, "Nicht gefunden."
            
            lines = [
                f"CHAIN: {chain['name']} (ID: {chain['id']})",
                f"Trigger: {chain['trigger_type']} {chain['trigger_value'] or ''}",
                f"Active: {chain['is_active']}",
                f"Last Run: {chain['last_run']}",
                "",
                "STEPS:"
            ]
            steps = json.loads(chain['steps_json'])
            for i, s in enumerate(steps):
                if 'parallel' in s and s['parallel']:
                    subtools = s.get('tools', [])
                    lines.append(f"  {i+1}. [PARALLEL BLOCK] ({len(subtools)} tasks)")
                    for sub in subtools:
                        lines.append(f"     - {sub.get('tool')} {sub.get('args')}")
                else:
                    lines.append(f"  {i+1}. {s.get('tool')} {s.get('args')}")
                
            return True, "\n".join(lines)
        finally:
            conn.close()

    def _delete(self, chain_id: str) -> tuple:
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM toolchains WHERE id = ?", (chain_id,))
            conn.commit()
            return True, f"Chain {chain_id} geloescht."
        finally:
            conn.close()

    def _log(self, chain_id: str) -> tuple:
         # Zeige letzten Run
        conn = self._get_conn()
        try:
            run = conn.execute("SELECT * FROM toolchain_runs WHERE chain_id = ? ORDER BY id DESC LIMIT 1", (chain_id,)).fetchone()
            if not run: return False, "Keine Logs gefunden."

            return True, f"LAST RUN ({run['started_at']}) - {run['status']}\nDuration: {run['duration_seconds']:.2f}s\n\nLOG:\n{run['log']}"
        finally:
            conn.close()

    # =========================================================
    # llmauto-Integration (B09)
    # Startet/stoppt/status llmauto-Ketten als Subprocess.
    # Ketten liegen in system/tools/llmauto/chains/*.json
    # =========================================================

    def _create(self, args: list) -> tuple:
        """Erstellt eine neue llmauto-Kette via CLI-Argumente (kein interaktiver Input).

        Syntax:
            bach chain create <name> [--mode once|loop] [--description "..."]
                [--max-rounds N] [--add-link role:model:prompt] [--from-template tpl]
        """
        if not args:
            return False, (
                "Usage: bach chain create <name> [--mode once|loop] "
                "[--description \"...\"] [--max-rounds N] "
                "[--add-link role:model:prompt_key] [--from-template template_name]"
            )

        name = args[0]
        if name.startswith("--"):
            return False, f"Erster Parameter muss der Ketten-Name sein, nicht '{name}'."

        chains_dir = self.base_path / "tools" / "llmauto" / "chains"
        chains_dir.mkdir(parents=True, exist_ok=True)
        chain_file = chains_dir / f"{name}.json"

        # --- Argumente parsen ---
        mode = "once"
        description = ""
        max_rounds = 5
        links_raw = []  # Liste von "role:model:prompt_key"
        from_template = None

        i = 1
        while i < len(args):
            arg = args[i]
            if arg == "--mode" and i + 1 < len(args):
                mode = args[i + 1]
                if mode not in ("once", "loop"):
                    return False, f"Ungueltiger Modus '{mode}'. Erlaubt: once, loop"
                i += 2
            elif arg == "--description" and i + 1 < len(args):
                description = args[i + 1]
                i += 2
            elif arg == "--max-rounds" and i + 1 < len(args):
                try:
                    max_rounds = int(args[i + 1])
                except ValueError:
                    return False, f"--max-rounds erwartet eine Zahl, nicht '{args[i + 1]}'."
                i += 2
            elif arg == "--add-link" and i + 1 < len(args):
                links_raw.append(args[i + 1])
                i += 2
            elif arg == "--from-template" and i + 1 < len(args):
                from_template = args[i + 1]
                i += 2
            else:
                return False, f"Unbekanntes Argument: {arg}"

        # --- --from-template: Bestehende Chain kopieren ---
        if from_template is not None:
            tpl_file = chains_dir / f"{from_template}.json"
            if not tpl_file.exists():
                available = self._list_llmauto_chains()
                return False, (
                    f"Template '{from_template}' nicht gefunden.\n"
                    f"Verfuegbar: {', '.join(available) or '(keine)'}"
                )
            try:
                tpl_data = json.loads(tpl_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                return False, f"Fehler beim Lesen des Templates: {e}"

            tpl_data["chain_name"] = name
            if description:
                tpl_data["description"] = description
            if mode != "once":
                tpl_data["mode"] = mode
            tpl_data["_created"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            tpl_data["_creator"] = "bach chain create"

            if chain_file.exists():
                return False, f"Kette '{name}' existiert bereits: {chain_file}"

            chain_file.write_text(
                json.dumps(tpl_data, indent=4, ensure_ascii=False),
                encoding="utf-8",
            )
            return True, f"Kette '{name}' aus Template '{from_template}' erstellt.\nDatei: {chain_file}"

        # --- Normale Erstellung ---
        # Model-Shortnames aufloesen
        model_map = {
            "sonnet": "claude-sonnet-4-6",
            "opus": "claude-opus-4-6",
            "haiku": "claude-haiku-4-5-20251001",
        }

        links = []
        for idx, link_spec in enumerate(links_raw, 1):
            parts = link_spec.split(":")
            if len(parts) != 3:
                return False, (
                    f"Ungueltiges Link-Format '{link_spec}'. "
                    f"Erwartet: role:model:prompt_key (z.B. worker:sonnet:worker_prompt)"
                )
            role, model_short, prompt_key = parts
            model_id = model_map.get(model_short, model_short)
            # Falls model_short schon ein voller ID ist, behalten
            if not model_id.startswith("claude-"):
                return False, (
                    f"Unbekanntes Modell '{model_short}'. "
                    f"Erlaubt: sonnet, opus, haiku (oder voller Modell-ID)"
                )
            link = {
                "name": f"{role}-{idx}",
                "role": role,
                "model": model_id,
                "prompt": prompt_key,
            }
            if role == "worker":
                link["until_full"] = True
            links.append(link)

        chain_data = {
            "chain_name": name,
            "description": description,
            "mode": mode,
            "max_rounds": max_rounds,
            "runtime_hours": 1,
            "links": links,
            "prompts": {},
            "_created": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "_creator": "bach chain create",
        }

        if mode == "loop":
            chain_data["max_consecutive_blocks"] = 3

        if chain_file.exists():
            return False, f"Kette '{name}' existiert bereits: {chain_file}"

        chain_file.write_text(
            json.dumps(chain_data, indent=4, ensure_ascii=False),
            encoding="utf-8",
        )

        link_info = f"{len(links)} Link(s)" if links else "keine Links (manuell in JSON hinzufuegen)"
        return True, (
            f"Kette '{name}' erstellt ({mode}, max {max_rounds} Runden, {link_info}).\n"
            f"Datei: {chain_file}"
        )

    def _list_llmauto_chains(self) -> list:
        """Listet verfuegbare llmauto Chain-Configs auf."""
        chains_dir = self.base_path / "tools" / "llmauto" / "chains"
        if not chains_dir.exists():
            return []
        return sorted([p.stem for p in chains_dir.glob("*.json")])

    def _run_llmauto(self, cmd_args: list) -> subprocess.CompletedProcess:
        """Hilfsmethode: llmauto-Subprocess ausfuehren."""
        tools_dir = str(self.base_path / "tools")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        cmd = [sys.executable, "-m", "llmauto"] + cmd_args
        return subprocess.run(
            cmd,
            cwd=tools_dir,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8", errors="replace",
        )

    def _llmauto_start(self, name: str) -> tuple:
        """Startet eine llmauto-Kette im Hintergrund (neues Fenster)."""
        chain_file = self.base_path / "tools" / "llmauto" / "chains" / f"{name}.json"
        if not chain_file.exists():
            available = self._list_llmauto_chains()
            hint = ", ".join(available) or "(keine)"
            return False, f"llmauto-Kette '{name}' nicht gefunden.\nVerfuegbar: {hint}"

        tools_dir = str(self.base_path / "tools")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        cmd = [sys.executable, "-m", "llmauto", "chain", "start", name, "--bg"]
        try:
            # --bg in llmauto startet selbst einen neuen Prozess (neues Fenster auf Windows)
            proc = subprocess.run(
                cmd,
                cwd=tools_dir,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8", errors="replace",
            )
            if proc.returncode == 0:
                out = proc.stdout.strip() or f"llmauto-Kette '{name}' gestartet."
                return True, out
            else:
                return False, f"Start fehlgeschlagen (rc={proc.returncode}):\n{proc.stderr}"
        except Exception as e:
            return False, f"Fehler beim Starten: {e}"

    def _llmauto_stop(self, name: str) -> tuple:
        """Stoppt eine laufende llmauto-Kette."""
        proc = self._run_llmauto(["chain", "stop", name])
        if proc.returncode == 0:
            return True, proc.stdout.strip() or f"llmauto-Kette '{name}' gestoppt."
        return False, f"Stop fehlgeschlagen (rc={proc.returncode}):\n{proc.stderr}"

    def _llmauto_pause(self, name: str, reason: str | None = None) -> tuple:
        """Pausiert eine laufende llmauto-Kette am nächsten sicheren Checkpoint."""
        args = ["chain", "pause", name]
        if reason:
            args.append(reason)
        proc = self._run_llmauto(args)
        if proc.returncode == 0:
            return True, proc.stdout.strip() or f"llmauto-Kette '{name}' wird pausiert."
        return False, f"Pause fehlgeschlagen (rc={proc.returncode}):\n{proc.stderr}"

    def _llmauto_resume(self, name: str) -> tuple:
        """Hebt eine Pause für eine llmauto-Kette auf."""
        proc = self._run_llmauto(["chain", "resume", name])
        if proc.returncode == 0:
            return True, proc.stdout.strip() or f"llmauto-Kette '{name}' wird fortgesetzt."
        return False, f"Resume fehlgeschlagen (rc={proc.returncode}):\n{proc.stderr}"

    def _llmauto_steer(self, name: str, message: str) -> tuple:
        """Hinterlegt einen Operator-Hinweis für die nächste llmauto-Runde."""
        proc = self._run_llmauto(["chain", "steer", name, message])
        if proc.returncode == 0:
            return True, proc.stdout.strip() or f"Steering für '{name}' vorgemerkt."
        return False, f"Steer fehlgeschlagen (rc={proc.returncode}):\n{proc.stderr}"

    def _llmauto_status(self, name: str = None) -> tuple:
        """Zeigt Status aller oder einer llmauto-Kette."""
        args = ["chain", "status"]
        if name:
            args.append(name)
        proc = self._run_llmauto(args)
        if proc.returncode == 0:
            return True, proc.stdout.strip() or "Kein Status verfuegbar."
        return False, f"Status fehlgeschlagen (rc={proc.returncode}):\n{proc.stderr}"

    def _llmauto_reset(self, name: str) -> tuple:
        """Setzt den State einer llmauto-Kette zurueck."""
        proc = self._run_llmauto(["chain", "reset", name])
        if proc.returncode == 0:
            return True, proc.stdout.strip() or f"State '{name}' zurueckgesetzt."
        return False, f"Reset fehlgeschlagen (rc={proc.returncode}):\n{proc.stderr}"
