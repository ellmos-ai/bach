# SPDX-License-Identifier: MIT
"""
Swarm Handler - LLM Swarm Execution Patterns
==========================================================

Available patterns:
  - parallel-chunks:  Parallelized chunk processing (translate, summarize)
  - hierarchy:        Manager-Worker structure
  - stigmergy:        Indirect coordination via shared state (pheromone)
  - consensus:        Multiple LLMs vote on a question
  - specialist:       Route task to specialized agent

Commands (primary: 'bach swarm', alias: 'bach schwarm'):
  bach swarm list                                  Show available patterns
  bach swarm run <pattern> <task>                  Execute swarm pattern
  bach swarm translate --file <path> [--workers N] Swarm translation
  bach swarm summarize [--batch-size N]            Chunk summaries
  bach swarm benchmark [--compare] [--workers N]   Performance benchmark
  bach swarm consensus <question> [--voters N]     Consensus vote
  bach swarm hierarchy <task> [--workers N]        Boss-Worker aggregator
  bach swarm stigmergy <task> [--agents N]         Pheromone-based coordination
  bach swarm specialist <task> [--auto-execute]    Route to specialist agent
  bach swarm status                                Run history

Ref: BACH v3.8.0-SUGAR / renamed from 'schwarm' + 'epstein' in v3.11.1
"""
import json
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from .base import BaseHandler
from .lang import t


class SchwarmHandler(BaseHandler):
    """Handler fuer Schwarm-basierte LLM-Operationen."""

    PATTERNS = {
        "parallel-chunks": {
            "name": "Parallel Chunks",
            "desc": "Parallelized chunk processing (translate, summarize)",
            "status": "aktiv",
        },
        "hierarchy": {
            "name": "Hierarchy",
            "desc": "Manager-Worker structure with task delegation",
            "status": "aktiv",
        },
        "stigmergy": {
            "name": "Stigmergy",
            "desc": "Indirect coordination via shared state (pheromone)",
            "status": "aktiv",
        },
        "consensus": {
            "name": "Consensus",
            "desc": "Multiple LLMs vote, majority-vote or similarity",
            "status": "aktiv",
        },
        "specialist": {
            "name": "Specialist",
            "desc": "Route task to specialized agent",
            "status": "aktiv",
        },
    }

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self.db_path = self._canonical_db
        self.tools_dir = self.base_path / "tools" / "schwarm"

    @property
    def profile_name(self) -> str:
        return "schwarm"

    @property
    def target_file(self) -> Path:
        return self.tools_dir

    def get_operations(self) -> dict:
        return {
            "list": t("schwarm_list_desc", default="Verfuegbare Schwarm-Muster anzeigen"),
            "run": t("schwarm_run_desc", default="Schwarm-Muster ausfuehren: bach schwarm run <muster> <aufgabe>"),
            "translate": t("schwarm_translate_desc", default="Schwarm-Uebersetzung (Parallel Chunks)"),
            "summarize": t("schwarm_summarize_desc", default="Chunk-Zusammenfassungen generieren"),
            "benchmark": t("schwarm_benchmark_desc", default="Performance-Benchmark (sequentiell vs. parallel)"),
            "consensus": t("schwarm_consensus_desc", default="Konsensus-Abstimmung mit mehreren LLMs"),
            "hierarchy": t("schwarm_hierarchy_desc", default="Boss-Worker-Aggregator Hierarchie-Muster"),
            "stigmergy": t("schwarm_stigmergy_desc", default="Pheromon-basierte Schwarm-Koordination"),
            "specialist": t("schwarm_specialist_desc", default="Aufgabe an spezialisierten Agenten routen"),
            "status": t("schwarm_status_desc", default="Schwarm-Run-Historie und Statistiken"),
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation == "list":
            return self._list_patterns()
        elif operation == "run":
            return self._run_pattern(args, dry_run)
        elif operation == "translate":
            return self._translate(args, dry_run)
        elif operation == "summarize":
            return self._summarize(args, dry_run)
        elif operation == "benchmark":
            return self._benchmark(args, dry_run)
        elif operation == "consensus":
            return self._consensus(args, dry_run)
        elif operation == "hierarchy":
            return self._hierarchy(args, dry_run)
        elif operation == "stigmergy":
            return self._stigmergy(args, dry_run)
        elif operation == "specialist":
            return self._specialist(args, dry_run)
        elif operation == "status":
            return self._status(args)
        else:
            return False, f"Unbekannte Operation: {operation}\nNutze: bach schwarm list"

    # =========================================================
    # list -- Verfuegbare Muster
    # =========================================================

    def _list_patterns(self) -> tuple:
        lines = [
            "SCHWARM-MUSTER",
            "=" * 60,
            f"{'Muster':<15} {'Name':<25} {'Status':<8} Beschreibung",
            "-" * 60,
        ]

        for key, pattern in self.PATTERNS.items():
            status_icon = "[OK]" if pattern["status"] == "aktiv" else "[--]"
            lines.append(
                f"{key:<15} {pattern['name']:<25} {status_icon:<8} {pattern['desc']}"
            )

        lines.append("")
        lines.append("Verwendung:")
        lines.append("  bach schwarm run <muster> <aufgabe>")
        lines.append("  bach schwarm consensus \"Frage?\" --voters 5")
        lines.append("  bach schwarm translate --dry-run")
        lines.append("  bach schwarm benchmark --compare")

        return True, "\n".join(lines)

    # =========================================================
    # run -- Muster ausfuehren
    # =========================================================

    def _run_pattern(self, args: list, dry_run: bool) -> tuple:
        if not args:
            return False, (
                "Usage: bach swarm run <pattern> <task>\n\n"
                "Patterns: parallel-chunks, consensus, hierarchy, stigmergy, specialist\n"
                "Example: bach swarm run consensus \"Was ist der beste Python-Linter?\""
            )

        pattern = args[0].lower()
        # Legacy aliases
        pattern = {"epstein": "parallel-chunks", "konsensus": "consensus",
                   "hierarchie": "hierarchy", "spezialist": "specialist"}.get(pattern, pattern)
        task = " ".join(args[1:]) if len(args) > 1 else ""

        if pattern not in self.PATTERNS:
            available = ", ".join(self.PATTERNS.keys())
            return False, f"Unknown pattern: {pattern}\nAvailable: {available}"

        if self.PATTERNS[pattern]["status"] != "aktiv":
            return False, f"Pattern '{pattern}' not yet implemented (status: {self.PATTERNS[pattern]['status']})"

        if not task:
            return False, f"Task required: bach swarm run {pattern} \"<task>\""

        # Route to pattern
        if pattern == "consensus":
            return self._consensus([task], dry_run)
        elif pattern == "parallel-chunks":
            return True, (
                f"Parallel Chunks pattern uses specific sub-commands:\n"
                f"  bach swarm translate --dry-run\n"
                f"  bach swarm summarize --dry-run\n"
                f"  bach swarm benchmark --compare"
            )
        elif pattern == "hierarchy":
            return self._hierarchy([task], dry_run)
        elif pattern == "stigmergy":
            return self._stigmergy([task], dry_run)
        elif pattern == "specialist":
            return self._specialist([task], dry_run)
        else:
            return False, f"Pattern '{pattern}' not yet implemented."

    # =========================================================
    # translate -- Wrapper fuer translate_swarm.py
    # =========================================================

    def _translate(self, args: list, dry_run: bool) -> tuple:
        script = self.tools_dir / "translate_swarm.py"
        if not script.exists():
            return False, f"translate_swarm.py nicht gefunden: {script}"

        cmd_args = [sys.executable, str(script)]

        # Argumente parsen und weiterleiten
        i = 0
        while i < len(args):
            arg = args[i]
            if arg == "--file" and i + 1 < len(args):
                # --file wird als --namespace interpretiert (Compat)
                cmd_args.extend(["--namespace", args[i + 1]])
                i += 2
            elif arg in ("--workers", "-w") and i + 1 < len(args):
                cmd_args.extend(["--workers", args[i + 1]])
                i += 2
            elif arg == "--max-workers" and i + 1 < len(args):
                cmd_args.extend(["--max-workers", args[i + 1]])
                i += 2
            elif arg == "--chunk-size" and i + 1 < len(args):
                cmd_args.extend(["--chunk-size", args[i + 1]])
                i += 2
            elif arg == "--limit" and i + 1 < len(args):
                cmd_args.extend(["--limit", args[i + 1]])
                i += 2
            elif arg in ("--namespace", "-n") and i + 1 < len(args):
                cmd_args.extend(["--namespace", args[i + 1]])
                i += 2
            elif arg == "--inventory":
                cmd_args.append("--inventory")
                i += 1
            elif arg == "--dry-run":
                cmd_args.append("--dry-run")
                i += 1
            else:
                i += 1

        if dry_run and "--dry-run" not in cmd_args:
            cmd_args.append("--dry-run")

        return self._run_tool(cmd_args, "translate_swarm")

    # =========================================================
    # summarize -- Wrapper fuer summarize_chunks.py
    # =========================================================

    def _summarize(self, args: list, dry_run: bool) -> tuple:
        script = self.tools_dir / "summarize_chunks.py"
        if not script.exists():
            return False, f"summarize_chunks.py nicht gefunden: {script}"

        cmd_args = [sys.executable, str(script)]

        i = 0
        while i < len(args):
            arg = args[i]
            if arg == "--batch-size" and i + 1 < len(args):
                cmd_args.extend(["--batch-size", args[i + 1]])
                i += 2
            elif arg == "--model" and i + 1 < len(args):
                cmd_args.extend(["--model", args[i + 1]])
                i += 2
            elif arg == "--dry-run":
                cmd_args.append("--dry-run")
                i += 1
            else:
                i += 1

        if dry_run and "--dry-run" not in cmd_args:
            cmd_args.append("--dry-run")

        return self._run_tool(cmd_args, "summarize_chunks")

    # =========================================================
    # benchmark -- Wrapper fuer benchmark.py
    # =========================================================

    def _benchmark(self, args: list, dry_run: bool) -> tuple:
        script = self.tools_dir / "benchmark.py"
        if not script.exists():
            return False, f"benchmark.py nicht gefunden: {script}"

        cmd_args = [sys.executable, str(script)]

        i = 0
        while i < len(args):
            arg = args[i]
            if arg == "--compare":
                cmd_args.append("--compare")
                i += 1
            elif arg == "--parallel":
                cmd_args.append("--parallel")
                i += 1
            elif arg == "--sequential":
                cmd_args.append("--sequential")
                i += 1
            elif arg == "--run":
                cmd_args.append("--run")
                i += 1
            elif arg in ("--workers", "-w") and i + 1 < len(args):
                cmd_args.extend(["--workers", args[i + 1]])
                i += 2
            elif arg == "--max-workers" and i + 1 < len(args):
                cmd_args.extend(["--max-workers", args[i + 1]])
                i += 2
            elif arg in ("--category", "-c") and i + 1 < len(args):
                cmd_args.extend(["--category", args[i + 1]])
                i += 2
            elif arg in ("--model", "-m") and i + 1 < len(args):
                cmd_args.extend(["--model", args[i + 1]])
                i += 2
            elif arg == "--export" and i + 1 < len(args):
                cmd_args.extend(["--export", args[i + 1]])
                i += 2
            elif arg == "--dry-run":
                cmd_args.append("--dry-run")
                i += 1
            else:
                i += 1

        if dry_run and "--dry-run" not in cmd_args:
            cmd_args.append("--dry-run")

        return self._run_tool(cmd_args, "benchmark")

    # =========================================================
    # consensus -- Konsensus-Muster direkt
    # =========================================================

    def _consensus(self, args: list, dry_run: bool) -> tuple:
        if not args:
            return False, (
                "Usage: bach schwarm consensus \"<frage>\" [--voters N] [--model haiku|sonnet] "
                "[--method similarity|majority]\n\n"
                "Beispiel:\n"
                "  bach schwarm consensus \"Was ist der beste Ansatz fuer Error-Handling in Python?\" --voters 5"
            )

        # Argumente parsen
        question = args[0]
        voters = 3
        model = "haiku"
        method = "similarity"

        i = 1
        while i < len(args):
            arg = args[i]
            if arg in ("--voters", "-v") and i + 1 < len(args):
                try:
                    voters = int(args[i + 1])
                except ValueError:
                    return False, f"--voters erwartet eine Zahl, nicht '{args[i + 1]}'"
                i += 2
            elif arg in ("--model", "-m") and i + 1 < len(args):
                model = args[i + 1]
                i += 2
            elif arg == "--method" and i + 1 < len(args):
                method = args[i + 1]
                if method not in ("similarity", "majority"):
                    return False, f"--method muss 'similarity' oder 'majority' sein, nicht '{method}'"
                i += 2
            else:
                # Unbekannte Argumente als Teil der Frage behandeln
                question += " " + args[i]
                i += 1

        if dry_run:
            return True, (
                f"[DRY-RUN] Konsensus-Abstimmung:\n"
                f"  Frage:   {question}\n"
                f"  Voter:   {voters}\n"
                f"  Modell:  {model}\n"
                f"  Methode: {method}\n\n"
                f"Wuerde {voters} parallele LLM-Aufrufe starten."
            )

        # Konsensus ausfuehren
        try:
            from tools.schwarm.consensus import ConsensusPattern

            pattern = ConsensusPattern(
                question=question,
                num_voters=voters,
                model=model,
                method=method,
            )
            result = pattern.run()

            if result.get("consensus") and result["consensus"].get("consensus"):
                answer = result["consensus"]["consensus"]
                confidence = result["consensus"].get("confidence", 0)
                return True, (
                    f"KONSENSUS-ERGEBNIS (Konfidenz: {confidence:.2f})\n"
                    f"{'=' * 60}\n"
                    f"{answer}\n"
                    f"{'=' * 60}\n"
                    f"Voter: {voters}, Modell: {model}, Methode: {method}\n"
                    f"Kosten: ${result['stats']['cost_usd']:.4f}"
                )
            else:
                return False, "Kein Konsens gefunden."

        except ImportError as e:
            return False, f"Fehler beim Laden des Konsensus-Moduls: {e}"
        except Exception as e:
            return False, f"Fehler bei Konsensus-Ausfuehrung: {e}"

    # =========================================================
    # hierarchy -- Boss-Worker-Aggregator
    # =========================================================

    def _hierarchy(self, args: list, dry_run: bool) -> tuple:
        if not args:
            return False, (
                "Usage: bach schwarm hierarchy \"<aufgabe>\" [--workers N] "
                "[--boss-model sonnet|opus] [--worker-model haiku|sonnet]\n\n"
                "Beispiel:\n"
                "  bach schwarm hierarchy \"Erstelle eine REST-API Dokumentation\" --workers 4"
            )

        # Argumente parsen
        task = args[0]
        workers = 0  # 0 = dynamisch
        max_workers = 0
        boss_model = "sonnet"
        worker_model = "haiku"
        workers_explicit = False

        i = 1
        while i < len(args):
            arg = args[i]
            if arg in ("--workers", "-w") and i + 1 < len(args):
                try:
                    workers = int(args[i + 1])
                    workers_explicit = True
                except ValueError:
                    return False, f"--workers erwartet eine Zahl, nicht '{args[i + 1]}'"
                i += 2
            elif arg == "--max-workers" and i + 1 < len(args):
                try:
                    max_workers = int(args[i + 1])
                except ValueError:
                    return False, f"--max-workers erwartet eine Zahl, nicht '{args[i + 1]}'"
                i += 2
            elif arg == "--boss-model" and i + 1 < len(args):
                boss_model = args[i + 1]
                i += 2
            elif arg == "--worker-model" and i + 1 < len(args):
                worker_model = args[i + 1]
                i += 2
            else:
                task += " " + args[i]
                i += 1

        # Dynamische Worker-Berechnung wenn nicht explizit gesetzt
        if not workers_explicit or workers <= 0:
            try:
                from tools.schwarm.runner import calculate_dynamic_workers
                # Hierarchy: Workers basierend auf geschaetzter Sub-Task-Anzahl
                # Default-Annahme: ~4 Sub-Tasks pro Aufgabe
                estimated_subtasks = 4
                workers = calculate_dynamic_workers(estimated_subtasks, max_workers=max_workers)
            except ImportError:
                workers = 3  # Fallback auf bisherigen Default

        if dry_run:
            return True, (
                f"[DRY-RUN] Hierarchie-Muster:\n"
                f"  Aufgabe:       {task}\n"
                f"  Worker:        {workers}\n"
                f"  Boss-Modell:   {boss_model}\n"
                f"  Worker-Modell: {worker_model}\n\n"
                f"Wuerde 1 Boss + {workers} Worker + 1 Aggregator starten."
            )

        try:
            from tools.schwarm.hierarchy import HierarchyPattern

            pattern = HierarchyPattern(
                task=task,
                num_workers=workers,
                boss_model=boss_model,
                worker_model=worker_model,
            )
            result = pattern.run()

            if result.get("success") and result.get("result"):
                return True, (
                    f"HIERARCHIE-ERGEBNIS\n"
                    f"{'=' * 60}\n"
                    f"{result['result']}\n"
                    f"{'=' * 60}\n"
                    f"Sub-Tasks: {len(result.get('subtasks', []))}, "
                    f"Worker: {workers}, "
                    f"Kosten: ${result['stats']['cost_usd']:.4f}"
                )
            else:
                error = result.get("error", "Unbekannter Fehler")
                return False, f"Hierarchie fehlgeschlagen: {error}"

        except ImportError as e:
            return False, f"Fehler beim Laden des Hierarchie-Moduls: {e}"
        except Exception as e:
            return False, f"Fehler bei Hierarchie-Ausfuehrung: {e}"

    # =========================================================
    # stigmergy -- Pheromon-basierte Koordination
    # =========================================================

    def _stigmergy(self, args: list, dry_run: bool) -> tuple:
        if not args:
            return False, (
                "Usage: bach schwarm stigmergy \"<aufgabe>\" [--agents N] "
                "[--rounds N] [--evaporation 0.1] [--model haiku|sonnet]\n\n"
                "Beispiel:\n"
                "  bach schwarm stigmergy \"Wie strukturiere ich einen Microservice?\" --agents 4 --rounds 3"
            )

        # Argumente parsen
        task = args[0]
        num_agents = 3
        rounds = 2
        evaporation = 0.1
        model = "haiku"

        i = 1
        while i < len(args):
            arg = args[i]
            if arg in ("--agents", "-a") and i + 1 < len(args):
                try:
                    num_agents = int(args[i + 1])
                except ValueError:
                    return False, f"--agents erwartet eine Zahl, nicht '{args[i + 1]}'"
                i += 2
            elif arg in ("--rounds", "-r") and i + 1 < len(args):
                try:
                    rounds = int(args[i + 1])
                except ValueError:
                    return False, f"--rounds erwartet eine Zahl, nicht '{args[i + 1]}'"
                i += 2
            elif arg in ("--evaporation", "-e") and i + 1 < len(args):
                try:
                    evaporation = float(args[i + 1])
                except ValueError:
                    return False, f"--evaporation erwartet eine Zahl, nicht '{args[i + 1]}'"
                i += 2
            elif arg in ("--model", "-m") and i + 1 < len(args):
                model = args[i + 1]
                i += 2
            else:
                task += " " + args[i]
                i += 1

        if dry_run:
            return True, (
                f"[DRY-RUN] Stigmergy-Muster:\n"
                f"  Aufgabe:       {task}\n"
                f"  Agenten:       {num_agents}\n"
                f"  Runden:        {rounds}\n"
                f"  Verdunstung:   {evaporation:.1%}\n"
                f"  Modell:        {model}\n\n"
                f"Wuerde {num_agents * rounds} LLM-Aufrufe ueber {rounds} Runden starten."
            )

        try:
            from tools.schwarm.stigmergy_pattern import StigmergyPattern

            pattern = StigmergyPattern(
                task=task,
                num_agents=num_agents,
                rounds=rounds,
                evaporation_rate=evaporation,
                model=model,
            )
            result = pattern.run()

            if result.get("success") and result.get("result"):
                return True, (
                    f"STIGMERGY-ERGEBNIS (Bester Pfad: {result.get('best_path', '?')})\n"
                    f"{'=' * 60}\n"
                    f"{result['result']}\n"
                    f"{'=' * 60}\n"
                    f"Runden: {rounds}, Agenten: {num_agents}, "
                    f"Pheromone: {len(result.get('pheromones', []))}, "
                    f"Kosten: ${result['stats']['cost_usd']:.4f}"
                )
            else:
                return False, "Stigmergy: Kein Ergebnis gefunden."

        except ImportError as e:
            return False, f"Fehler beim Laden des Stigmergy-Moduls: {e}"
        except Exception as e:
            return False, f"Fehler bei Stigmergy-Ausfuehrung: {e}"

    # =========================================================
    # specialist -- Aufgabe an spezialisierten Agenten routen
    # =========================================================

    def _specialist(self, args: list, dry_run: bool) -> tuple:
        if not args:
            return False, (
                "Usage: bach schwarm specialist \"<aufgabe>\" [--auto-execute] "
                "[--model haiku|sonnet]\n\n"
                "Beispiel:\n"
                "  bach schwarm specialist \"Plane einen Arzttermin\"\n"
                "  bach schwarm specialist \"Erstelle eine Steuererklaerung\" --auto-execute"
            )

        # Argumente parsen
        task = args[0]
        auto_execute = False
        model = "haiku"

        i = 1
        while i < len(args):
            arg = args[i]
            if arg == "--auto-execute":
                auto_execute = True
                i += 1
            elif arg in ("--model", "-m") and i + 1 < len(args):
                model = args[i + 1]
                i += 2
            else:
                task += " " + args[i]
                i += 1

        if dry_run:
            return True, (
                f"[DRY-RUN] Spezialist-Muster:\n"
                f"  Aufgabe:       {task}\n"
                f"  Auto-Execute:  {auto_execute}\n"
                f"  Modell:        {model}\n\n"
                f"Wuerde Agenten aus bach_agents laden und Routing durchfuehren."
            )

        try:
            from tools.schwarm.specialist import SpecialistPattern

            pattern = SpecialistPattern(
                task=task,
                auto_execute=auto_execute,
                model=model,
            )
            result = pattern.run()

            if result.get("success"):
                agent = result.get("agent", {})
                recommendation = result.get("recommendation", "")
                output_parts = [
                    f"SPEZIALIST-ERGEBNIS",
                    f"{'=' * 60}",
                    f"Empfehlung: {recommendation}",
                ]

                exec_result = result.get("execution_result")
                if exec_result and exec_result.get("success"):
                    output_parts.append(f"\nAGENT-ANTWORT:\n{exec_result['output']}")

                output_parts.extend([
                    f"{'=' * 60}",
                    f"Kosten: ${result['stats']['cost_usd']:.4f}",
                ])

                return True, "\n".join(output_parts)
            else:
                error = result.get("error", "Kein passender Agent gefunden")
                return False, f"Spezialist: {error}"

        except ImportError as e:
            return False, f"Fehler beim Laden des Spezialist-Moduls: {e}"
        except Exception as e:
            return False, f"Fehler bei Spezialist-Ausfuehrung: {e}"

    # =========================================================
    # status -- Run-Historie
    # =========================================================

    def _status(self, args: list) -> tuple:
        if not self.db_path.exists():
            return False, "bach.db nicht gefunden"

        # Sicherstellen dass Tabelle existiert
        try:
            from tools.schwarm.runner import ensure_schwarm_table
            ensure_schwarm_table(self.db_path)
        except ImportError:
            pass

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row

        # Pruefen ob Tabelle existiert
        table_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schwarm_runs'"
        ).fetchone()

        if not table_exists:
            conn.close()
            return True, "Keine Schwarm-Runs vorhanden (Tabelle noch nicht erstellt)."

        # Letzte 20 Runs
        limit = 20
        if args and args[0].isdigit():
            limit = int(args[0])

        rows = conn.execute("""
            SELECT id, pattern, task, tokens_in, tokens_out, cost_usd,
                   workers, duration_ms, status, created_at
            FROM schwarm_runs
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)).fetchall()

        if not rows:
            conn.close()
            return True, "Keine Schwarm-Runs vorhanden."

        # Statistiken
        stats = conn.execute("""
            SELECT
                COUNT(*) as total_runs,
                SUM(tokens_in) as total_tokens_in,
                SUM(tokens_out) as total_tokens_out,
                SUM(cost_usd) as total_cost,
                SUM(duration_ms) as total_duration_ms
            FROM schwarm_runs
        """).fetchone()

        conn.close()

        lines = [
            "SCHWARM-RUN HISTORIE",
            "=" * 80,
            f"{'ID':<5} {'Muster':<20} {'Status':<12} {'Worker':<7} {'Dauer':<10} {'Kosten':<10} {'Datum'}",
            "-" * 80,
        ]

        for row in rows:
            duration_s = row['duration_ms'] / 1000 if row['duration_ms'] else 0
            cost_str = f"${row['cost_usd']:.4f}" if row['cost_usd'] else "$0.0000"
            date_str = row['created_at'][:16] if row['created_at'] else "-"
            task_short = (row['task'] or "")[:30]

            lines.append(
                f"{row['id']:<5} {row['pattern']:<20} {row['status']:<12} "
                f"{row['workers'] or 1:<7} {duration_s:<10.1f} {cost_str:<10} {date_str}"
            )

        # Gesamt-Statistik
        lines.append("")
        lines.append("=" * 80)
        lines.append("GESAMT-STATISTIK")
        lines.append(f"  Runs:        {stats['total_runs']}")
        lines.append(f"  Tokens In:   {stats['total_tokens_in'] or 0:,}")
        lines.append(f"  Tokens Out:  {stats['total_tokens_out'] or 0:,}")
        lines.append(f"  Kosten:      ${stats['total_cost'] or 0:.4f}")
        total_s = (stats['total_duration_ms'] or 0) / 1000
        lines.append(f"  Dauer:       {total_s:.1f}s ({total_s/60:.1f}min)")

        return True, "\n".join(lines)

    # =========================================================
    # Hilfsmethoden
    # =========================================================

    def _run_tool(self, cmd: list, tool_name: str) -> tuple:
        """Fuehrt ein Schwarm-Tool als Subprocess aus."""
        import os
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
                cwd=str(self.base_path),
                env=env,
            )

            output = result.stdout
            if result.stderr:
                output += f"\n[STDERR]\n{result.stderr}"

            if result.returncode == 0:
                return True, output
            else:
                return False, f"[FEHLER] {tool_name} beendet mit Code {result.returncode}\n{output}"

        except subprocess.TimeoutExpired:
            return False, f"[TIMEOUT] {tool_name} nach 600s abgebrochen"
        except Exception as e:
            return False, f"[FEHLER] {tool_name}: {e}"
