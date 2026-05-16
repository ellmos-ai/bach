# SPDX-License-Identifier: MIT
"""
specialist.py - Spezialist-Muster fuer Agent-Routing
=====================================================
Analysiert eine Aufgabe und routet an den passenden BACH-Boss-Agenten.

Ablauf:
  1. Verfuegbare Agenten aus bach_agents Tabelle laden
  2. Aufgabe analysieren (via LLM oder Keyword-Matching)
  3. Besten Agenten empfehlen (oder direkt ausfuehren)

Usage (als Modul):
    from tools.schwarm.specialist import SpecialistPattern
    sp = SpecialistPattern(task="Plane einen Arzttermin")
    result = sp.run()

Usage (CLI):
    python -m tools.schwarm.specialist "Aufgabe" --auto-execute

Ref: BACH v3.8.0-SUGAR
"""
import argparse
import json
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from .runner import ClaudeRunner, log_schwarm_run

try:
    from hub.bach_paths import BACH_DB as _DB_PATH
except ImportError:
    _DB_PATH = Path(__file__).parent.parent.parent / "data" / "bach.db"


class SpecialistPattern:
    """Spezialist-Muster: Aufgabe an den passenden Agenten routen."""

    MODEL_MAP = {
        "haiku": "claude-haiku-4-5-20251001",
        "sonnet": "claude-sonnet-4-6",
        "opus": "claude-opus-4-6",
    }

    def __init__(self, task: str, auto_execute: bool = False,
                 model: str = "haiku", timeout: int = 300):
        """
        Initialisiert das Spezialist-Muster.

        Args:
            task: Die zu bearbeitende Aufgabe
            auto_execute: True = Agent direkt ausfuehren, False = nur Empfehlung
            model: Modell fuer die Routing-Entscheidung (default: haiku)
            timeout: Timeout pro Aufruf in Sekunden
        """
        self.task = task
        self.auto_execute = auto_execute
        self.model = self.MODEL_MAP.get(model, model)
        self.timeout = timeout

    def _load_agents(self) -> List[Dict]:
        """Laedt verfuegbare Agenten aus der bach_agents Tabelle.

        Returns:
            Liste von Agent-Dicts mit name, display_name, category, description, etc.
        """
        if not _DB_PATH.exists():
            return []

        try:
            conn = sqlite3.connect(str(_DB_PATH))
            conn.row_factory = sqlite3.Row

            # Pruefen ob Tabelle existiert
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='bach_agents'"
            )
            if not cursor.fetchone():
                conn.close()
                return []

            rows = conn.execute("""
                SELECT name, display_name, type, category, description,
                       skill_path, is_active
                FROM bach_agents
                WHERE is_active = 1
                ORDER BY priority DESC, name
            """).fetchall()

            conn.close()

            return [
                {
                    "name": row["name"],
                    "display_name": row["display_name"],
                    "type": row["type"],
                    "category": row["category"] or "",
                    "description": row["description"] or "",
                    "skill_path": row["skill_path"] or "",
                }
                for row in rows
            ]

        except Exception:
            return []

    def _load_experts(self, agent_name: str) -> List[Dict]:
        """Laedt Experten eines Agenten aus bach_experts.

        Args:
            agent_name: Name des Boss-Agenten

        Returns:
            Liste von Experten-Dicts
        """
        if not _DB_PATH.exists():
            return []

        try:
            conn = sqlite3.connect(str(_DB_PATH))
            conn.row_factory = sqlite3.Row

            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='bach_experts'"
            )
            if not cursor.fetchone():
                conn.close()
                return []

            # Agent-ID ermitteln
            agent_row = conn.execute(
                "SELECT id FROM bach_agents WHERE name = ?", (agent_name,)
            ).fetchone()

            if not agent_row:
                conn.close()
                return []

            rows = conn.execute("""
                SELECT name, display_name, description, domain, capabilities
                FROM bach_experts
                WHERE agent_id = ? AND is_active = 1
                ORDER BY name
            """, (agent_row["id"],)).fetchall()

            conn.close()

            return [
                {
                    "name": row["name"],
                    "display_name": row["display_name"],
                    "description": row["description"] or "",
                    "domain": row["domain"] or "",
                    "capabilities": row["capabilities"] or "",
                }
                for row in rows
            ]

        except Exception:
            return []

    def _keyword_match(self, agents: List[Dict]) -> Optional[Dict]:
        """Fallback-Routing via Keyword-Matching.

        Vergleicht Woerter in der Aufgabe mit Agent-Beschreibungen.

        Args:
            agents: Verfuegbare Agenten

        Returns:
            Bester Agent oder None
        """
        task_lower = self.task.lower()
        task_words = set(re.findall(r'\w+', task_lower))

        best_agent = None
        best_score = 0

        for agent in agents:
            # Keywords aus Beschreibung, Kategorie und Name
            agent_text = (
                f"{agent['description']} {agent['category']} "
                f"{agent['display_name']} {agent['name']}"
            ).lower()
            agent_words = set(re.findall(r'\w+', agent_text))

            # Ueberschneidung berechnen
            overlap = task_words & agent_words
            score = len(overlap)

            if score > best_score:
                best_score = score
                best_agent = agent

        return best_agent if best_score > 0 else None

    def _llm_route(self, agents: List[Dict]) -> Optional[Dict]:
        """LLM-basiertes Routing: Claude waehlt den passenden Agenten.

        Args:
            agents: Verfuegbare Agenten

        Returns:
            Bester Agent oder None
        """
        # Agenten-Uebersicht fuer den Prompt
        agent_lines = []
        for i, agent in enumerate(agents):
            agent_lines.append(
                f"  {i+1}. {agent['name']} ({agent['display_name']})\n"
                f"     Kategorie: {agent['category']}\n"
                f"     Beschreibung: {agent['description']}"
            )
        agents_text = "\n".join(agent_lines)

        prompt = (
            f"Du bist ein Router. Waehle den am besten passenden Agenten "
            f"fuer die folgende Aufgabe.\n\n"
            f"Aufgabe: {self.task}\n\n"
            f"Verfuegbare Agenten:\n{agents_text}\n\n"
            f"Antworte NUR mit dem exakten Namen des besten Agenten "
            f"(z.B. 'persoenlicher-assistent'). "
            f"Falls kein Agent passt, antworte mit 'KEINER'.\n\n"
            f"Bester Agent:"
        )

        runner = ClaudeRunner(
            model=self.model,
            timeout=self.timeout,
            allowed_tools=[],
        )

        print(f"[SPEZIALIST] LLM-Routing ({self.model})...")
        result = runner.run(prompt)

        if not result["success"]:
            print(f"[SPEZIALIST] LLM-Routing fehlgeschlagen: {result['stderr']}")
            return None

        chosen_name = result["output"].strip().strip("'\"").lower()

        if chosen_name == "keiner":
            return None

        # Agent nach Name finden
        for agent in agents:
            if agent["name"].lower() == chosen_name:
                return agent

        # Fuzzy-Match: Teilstring
        for agent in agents:
            if agent["name"].lower() in chosen_name or chosen_name in agent["name"].lower():
                return agent

        return None

    def _execute_agent(self, agent: Dict) -> Dict:
        """Fuehrt die Aufgabe mit dem gewaehlten Agenten aus.

        Args:
            agent: Der gewaehlte Agent

        Returns:
            Ergebnis-Dict
        """
        # Agent-Skill-Datei als System-Prompt laden
        skill_path = agent.get("skill_path", "")
        system_context = ""

        if skill_path:
            skill_file = _DB_PATH.parent.parent / skill_path
            if skill_file.exists():
                try:
                    system_context = skill_file.read_text(encoding="utf-8")[:2000]
                except Exception:
                    pass

        prompt = (
            f"Du bist der Agent '{agent['display_name']}' "
            f"({agent['description']}).\n\n"
        )
        if system_context:
            prompt += f"Dein Skill-Kontext:\n{system_context}\n\n"
        prompt += f"Bearbeite folgende Aufgabe:\n{self.task}"

        runner = ClaudeRunner(
            model=self.model,
            timeout=self.timeout,
            allowed_tools=[],
        )

        print(f"[SPEZIALIST] Ausfuehrung mit {agent['display_name']} ({self.model})...")
        result = runner.run(prompt)

        return {
            "success": result["success"],
            "output": result["output"],
            "duration_s": result["duration_s"],
            "tokens_in": result.get("tokens_in", 0),
            "tokens_out": result.get("tokens_out", 0),
            "cost_usd": result.get("cost_usd", 0.0),
        }

    def run(self, dry_run: bool = False) -> Dict:
        """Fuehrt das Spezialist-Muster aus.

        Args:
            dry_run: Nur Konfiguration anzeigen, keine API-Aufrufe

        Returns:
            Dict mit agent, recommendation, result (bei auto_execute), stats
        """
        print(f"\n{'=' * 60}")
        print(f"  SCHWARM SPEZIALIST")
        print(f"{'=' * 60}")
        print(f"  Aufgabe:       {self.task[:80]}...")
        print(f"  Auto-Execute:  {self.auto_execute}")
        print(f"  Modell:        {self.model}")
        print()

        # Agenten laden
        agents = self._load_agents()
        if not agents:
            msg = "Keine aktiven Agenten in bach_agents gefunden."
            print(f"[FEHLER] {msg}")
            return {"success": False, "error": msg}

        print(f"[SPEZIALIST] {len(agents)} aktive Agenten gefunden:")
        for agent in agents:
            print(f"  - {agent['name']} ({agent['category']}): {agent['description'][:50]}")

        if dry_run:
            print(f"\n[DRY-RUN] Wuerde Routing durchfuehren fuer: {self.task[:80]}")
            print(f"  Methode 1: LLM-Routing ({self.model})")
            print(f"  Methode 2: Keyword-Matching (Fallback)")
            if self.auto_execute:
                print(f"  Danach: Aufgabe an gewaehlten Agenten delegieren")
            return {"dry_run": True, "available_agents": agents}

        start_time = time.time()
        total_tokens_in = 0
        total_tokens_out = 0
        total_cost = 0.0

        # Routing: Zuerst LLM, dann Keyword-Fallback
        print()
        chosen_agent = self._llm_route(agents)

        if chosen_agent is None:
            print("[SPEZIALIST] LLM konnte keinen Agent waehlen, nutze Keyword-Matching...")
            chosen_agent = self._keyword_match(agents)

        if chosen_agent is None:
            elapsed = time.time() - start_time
            msg = "Kein passender Agent gefunden."
            print(f"[SPEZIALIST] {msg}")
            log_schwarm_run(
                pattern="specialist", task=self.task[:500],
                tokens_in=0, tokens_out=0, cost_usd=0.0,
                workers=1, duration_ms=int(elapsed * 1000),
                status="failed",
                result_summary="Kein passender Agent gefunden",
            )
            return {"success": False, "error": msg, "available_agents": agents}

        print(f"\n[SPEZIALIST] Gewaehlter Agent: {chosen_agent['display_name']}")
        print(f"  Name:       {chosen_agent['name']}")
        print(f"  Kategorie:  {chosen_agent['category']}")
        print(f"  Beschreibung: {chosen_agent['description']}")

        # Experten laden
        experts = self._load_experts(chosen_agent["name"])
        if experts:
            print(f"  Experten:   {', '.join(e['display_name'] for e in experts)}")

        # Auto-Execute
        execution_result = None
        if self.auto_execute:
            print()
            execution_result = self._execute_agent(chosen_agent)
            total_tokens_in += execution_result.get("tokens_in", 0)
            total_tokens_out += execution_result.get("tokens_out", 0)
            total_cost += execution_result.get("cost_usd", 0.0)

        elapsed = time.time() - start_time

        # Kosten-Tracking in DB
        try:
            log_schwarm_run(
                pattern="specialist",
                task=self.task[:500],
                tokens_in=total_tokens_in,
                tokens_out=total_tokens_out,
                cost_usd=total_cost,
                workers=1,
                duration_ms=int(elapsed * 1000),
                status="completed",
                result_summary=(
                    f"agent={chosen_agent['name']}, "
                    f"auto_execute={self.auto_execute}, "
                    f"experts={len(experts)}"
                ),
            )
        except Exception:
            pass

        # Ergebnis ausgeben
        print(f"\n{'=' * 60}")
        print(f"  ERGEBNIS")
        print(f"{'=' * 60}")
        print(f"  Empfohlener Agent: {chosen_agent['display_name']}")
        print(f"  Agent-Name:        {chosen_agent['name']}")
        print(f"  Kategorie:         {chosen_agent['category']}")
        print(f"  Dauer:             {elapsed:.1f}s")
        print(f"  Kosten:            ${total_cost:.4f}")

        if execution_result:
            if execution_result["success"]:
                print(f"\n  --- AGENT-ERGEBNIS ---")
                for line in execution_result["output"].split("\n"):
                    print(f"  {line}")
            else:
                print(f"\n  [FEHLER] Agent-Ausfuehrung fehlgeschlagen.")
        else:
            print(f"\n  Nutze: bach agent {chosen_agent['name']} \"<aufgabe>\"")
            print(f"  Oder:  bach schwarm specialist \"<aufgabe>\" --auto-execute")

        print(f"{'=' * 60}")

        return {
            "success": True,
            "agent": chosen_agent,
            "experts": experts,
            "recommendation": (
                f"Agent '{chosen_agent['display_name']}' ({chosen_agent['name']}) "
                f"ist am besten geeignet fuer diese Aufgabe."
            ),
            "execution_result": execution_result,
            "stats": {
                "total_duration_s": elapsed,
                "tokens_in": total_tokens_in,
                "tokens_out": total_tokens_out,
                "cost_usd": total_cost,
                "model": self.model,
                "auto_execute": self.auto_execute,
                "available_agents": len(agents),
            },
        }


def main():
    """CLI-Einstieg fuer Spezialist-Muster."""
    parser = argparse.ArgumentParser(
        description="Schwarm Spezialist-Muster: Aufgabe an passenden Agenten routen"
    )
    parser.add_argument("task", nargs="?", help="Die zu bearbeitende Aufgabe")
    parser.add_argument(
        "--auto-execute", action="store_true",
        help="Agent direkt ausfuehren (default: nur Empfehlung)"
    )
    parser.add_argument(
        "--model", "-m", default="haiku",
        help="Modell fuer Routing: haiku, sonnet, opus (default: haiku)"
    )
    parser.add_argument(
        "--timeout", type=int, default=300,
        help="Timeout pro Aufruf in Sekunden (default: 300)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Nur Konfiguration anzeigen"
    )

    args = parser.parse_args()

    if not args.task:
        parser.print_help()
        print("\nBeispiel: python -m tools.schwarm.specialist \"Plane einen Arzttermin\" --auto-execute")
        return 1

    pattern = SpecialistPattern(
        task=args.task,
        auto_execute=args.auto_execute,
        model=args.model,
        timeout=args.timeout,
    )

    result = pattern.run(dry_run=args.dry_run)
    return 0 if result.get("success") or result.get("dry_run") else 1


if __name__ == "__main__":
    sys.exit(main())
