#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Plan Agent v1.0.0 — SQ018
Strukturierte Planungsprotokolle erstellen und verwalten.
Abgeleitet von PortableAgent — funktioniert mit und ohne BACH.

Usage:
  python plan_agent.py create "Plan Title" --goal "..."
  python plan_agent.py list [--status draft|active|completed|archived]
  python plan_agent.py show <plan_id>
  python plan_agent.py next <plan_id>
  python plan_agent.py export <plan_id> [--format markdown|json]
"""

import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

from portable_base import BACH_AVAILABLE, BACH_ROOT, PortableAgent

SCRIPT_DIR = Path(__file__).parent

# Storage directory
# BACH_PLANS_DIR (Testisolation, T-20260902-646684582): faellt sonst je nach
# BACH_AVAILABLE auf das Repo oder auf das produktive ~/.bach/plans zurueck.
_plans_env = os.environ.get("BACH_PLANS_DIR")
if _plans_env:
    PLANS_DIR = Path(_plans_env).expanduser()
elif BACH_AVAILABLE and (BACH_ROOT / "system" / "data").exists():
    PLANS_DIR = BACH_ROOT / "system" / "data" / "plans"
else:
    PLANS_DIR = Path.home() / ".bach" / "plans"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _new_id(prefix: str = "plan") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class PlanAgent(PortableAgent):
    """Agent fuer strukturierte Planungsprotokolle."""

    AGENT_NAME = "PlanAgent"
    VERSION = "1.0.0"

    def __init__(self, config_path: Optional[str] = None):
        super().__init__(config_path)
        PLANS_DIR.mkdir(parents=True, exist_ok=True)

    # --- Storage helpers ---

    def _plan_path(self, plan_id: str) -> Path:
        return PLANS_DIR / f"{plan_id}.json"

    def _save_plan(self, plan: Dict) -> None:
        path = self._plan_path(plan["id"])
        with open(path, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)

    def _load_plan(self, plan_id: str) -> Optional[Dict]:
        path = self._plan_path(plan_id)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _all_plans(self) -> List[Dict]:
        plans = []
        for p in sorted(PLANS_DIR.glob("plan-*.json")):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    plans.append(json.load(f))
            except (json.JSONDecodeError, OSError):
                continue
        return plans

    # --- Core methods ---

    def create_plan(
        self, title: str, goal: str, steps: Optional[List[Dict]] = None
    ) -> Dict:
        """Erstellt einen neuen Plan."""
        now = _now()
        plan_id = _new_id("plan")

        built_steps = []
        for i, s in enumerate(steps or []):
            built_steps.append(
                {
                    "id": f"step-{i}",
                    "title": s.get("title", f"Schritt {i + 1}"),
                    "description": s.get("description", ""),
                    "status": "pending",
                    "dependencies": s.get("dependencies", []),
                    "assignee": s.get("assignee"),
                    "artifacts": [],
                }
            )

        plan = {
            "id": plan_id,
            "title": title,
            "goal": goal,
            "status": "draft",
            "steps": built_steps,
            "created_at": now,
            "updated_at": now,
        }
        self._save_plan(plan)
        self.logger.info(f"Plan erstellt: {plan_id} — {title}")
        return plan

    def add_step(
        self,
        plan_id: str,
        title: str,
        description: str = "",
        dependencies: Optional[List[str]] = None,
    ) -> Dict:
        """Fuegt einem Plan einen neuen Schritt hinzu."""
        plan = self._load_plan(plan_id)
        if plan is None:
            raise ValueError(f"Plan nicht gefunden: {plan_id}")

        idx = len(plan["steps"])
        step = {
            "id": f"step-{idx}",
            "title": title,
            "description": description,
            "status": "pending",
            "dependencies": dependencies or [],
            "assignee": None,
            "artifacts": [],
        }
        plan["steps"].append(step)
        plan["updated_at"] = _now()
        self._save_plan(plan)
        self.logger.info(f"Step hinzugefuegt: {step['id']} -> {plan_id}")
        return step

    def update_step(
        self,
        plan_id: str,
        step_id: str,
        status: Optional[str] = None,
        assignee: Optional[str] = None,
    ) -> Dict:
        """Aktualisiert Status oder Assignee eines Steps."""
        plan = self._load_plan(plan_id)
        if plan is None:
            raise ValueError(f"Plan nicht gefunden: {plan_id}")

        for step in plan["steps"]:
            if step["id"] == step_id:
                if status:
                    step["status"] = status
                if assignee is not None:
                    step["assignee"] = assignee
                plan["updated_at"] = _now()
                # Auto-update plan status
                self._sync_plan_status(plan)
                self._save_plan(plan)
                return step

        raise ValueError(f"Step nicht gefunden: {step_id} in {plan_id}")

    def _sync_plan_status(self, plan: Dict) -> None:
        """Setzt Plan-Status basierend auf Step-Status."""
        statuses = [s["status"] for s in plan["steps"]]
        if not statuses:
            return
        if all(s == "completed" for s in statuses):
            plan["status"] = "completed"
        elif any(s in ("in_progress", "completed") for s in statuses):
            plan["status"] = "active"

    def get_plan(self, plan_id: str) -> Optional[Dict]:
        """Gibt vollstaendigen Plan zurueck."""
        return self._load_plan(plan_id)

    def list_plans(self, status: Optional[str] = None) -> List[Dict]:
        """Listet alle Plaene, optional nach Status gefiltert."""
        plans = self._all_plans()
        if status:
            plans = [p for p in plans if p["status"] == status]
        return [
            {
                "id": p["id"],
                "title": p["title"],
                "status": p["status"],
                "steps_total": len(p["steps"]),
                "steps_done": sum(1 for s in p["steps"] if s["status"] == "completed"),
                "updated_at": p["updated_at"],
            }
            for p in plans
        ]

    def get_next_steps(self, plan_id: str) -> List[Dict]:
        """Gibt alle nicht-blockierten, ausstehenden Steps zurueck."""
        plan = self._load_plan(plan_id)
        if plan is None:
            raise ValueError(f"Plan nicht gefunden: {plan_id}")

        completed = {s["id"] for s in plan["steps"] if s["status"] == "completed"}
        result = []
        for step in plan["steps"]:
            if step["status"] != "pending":
                continue
            deps = set(step.get("dependencies", []))
            if deps.issubset(completed):
                result.append(step)
        return result

    def generate_plan(self, goal_description: str) -> Dict:
        """LLM-gestuetzte Plan-Generierung (Stub: Template-Plan)."""
        return self.create_plan(
            title=f"Plan: {goal_description[:60]}",
            goal=goal_description,
            steps=[
                {"title": "Analyse", "description": "Anforderungen analysieren"},
                {
                    "title": "Design",
                    "description": "Loesung entwerfen",
                    "dependencies": ["step-0"],
                },
                {
                    "title": "Implementierung",
                    "description": "Loesung umsetzen",
                    "dependencies": ["step-1"],
                },
                {
                    "title": "Test",
                    "description": "Ergebnis pruefen",
                    "dependencies": ["step-2"],
                },
                {
                    "title": "Abschluss",
                    "description": "Dokumentation und Uebergabe",
                    "dependencies": ["step-3"],
                },
            ],
        )

    def export_plan(self, plan_id: str, fmt: str = "markdown") -> str:
        """Exportiert Plan als Markdown oder JSON."""
        plan = self._load_plan(plan_id)
        if plan is None:
            raise ValueError(f"Plan nicht gefunden: {plan_id}")

        if fmt == "json":
            return json.dumps(plan, indent=2, ensure_ascii=False)

        # Markdown export
        lines = [
            f"# {plan['title']}",
            "",
            f"**Ziel:** {plan['goal']}",
            f"**Status:** {plan['status']}",
            f"**Erstellt:** {plan['created_at']}",
            f"**Aktualisiert:** {plan['updated_at']}",
            "",
            "## Schritte",
            "",
        ]
        status_icons = {
            "pending": "[ ]",
            "in_progress": "[~]",
            "completed": "[x]",
            "blocked": "[!]",
        }
        for step in plan["steps"]:
            icon = status_icons.get(step["status"], "[ ]")
            line = f"- {icon} **{step['title']}**"
            if step.get("assignee"):
                line += f" (@{step['assignee']})"
            lines.append(line)
            if step.get("description"):
                lines.append(f"  {step['description']}")
            if step.get("dependencies"):
                deps = ", ".join(step["dependencies"])
                lines.append(f"  _Abhaengig von: {deps}_")
        lines.append("")
        return "\n".join(lines)

    # --- PortableAgent Interface ---

    def run(self, **kwargs) -> Any:
        action = kwargs.get("action", "status")
        if action == "create":
            return self.create_plan(kwargs["title"], kwargs.get("goal", ""))
        if action == "list":
            return self.list_plans(kwargs.get("status"))
        if action == "show":
            return self.get_plan(kwargs["plan_id"])
        if action == "next":
            return self.get_next_steps(kwargs["plan_id"])
        return self.status()

    def status(self) -> Dict:
        plans = self._all_plans()
        return {
            "agent": self.AGENT_NAME,
            "version": self.VERSION,
            "bach_available": self.bach_available,
            "plans_dir": str(PLANS_DIR),
            "plans_total": len(plans),
            "plans_active": sum(1 for p in plans if p["status"] == "active"),
            "plans_draft": sum(1 for p in plans if p["status"] == "draft"),
            "plans_completed": sum(1 for p in plans if p["status"] == "completed"),
        }

    def config(self) -> Dict:
        return self._config

    def standalone_config_template(self) -> Dict:
        return {
            "agent": self.AGENT_NAME,
            "version": self.VERSION,
            "plans_dir": str(PLANS_DIR),
        }


# --- CLI ---


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Plan Agent v1.0.0 — SQ018")
    sub = parser.add_subparsers(dest="command")

    # create
    p_create = sub.add_parser("create", help="Neuen Plan erstellen")
    p_create.add_argument("title", help="Plan-Titel")
    p_create.add_argument("--goal", default="", help="Planziel")

    # list
    p_list = sub.add_parser("list", help="Plaene auflisten")
    p_list.add_argument("--status", choices=["draft", "active", "completed", "archived"])

    # show
    p_show = sub.add_parser("show", help="Plan anzeigen")
    p_show.add_argument("plan_id", help="Plan-ID")

    # next
    p_next = sub.add_parser("next", help="Naechste Schritte anzeigen")
    p_next.add_argument("plan_id", help="Plan-ID")

    # export
    p_export = sub.add_parser("export", help="Plan exportieren")
    p_export.add_argument("plan_id", help="Plan-ID")
    p_export.add_argument("--format", choices=["markdown", "json"], default="markdown")

    # status
    sub.add_parser("status", help="Agent-Status")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    agent = PlanAgent()

    if args.command == "create":
        plan = agent.create_plan(args.title, args.goal)
        print(f"\nPlan erstellt: {plan['id']}")
        print(f"  Titel: {plan['title']}")
        print(f"  Ziel:  {plan['goal']}")

    elif args.command == "list":
        plans = agent.list_plans(args.status)
        if not plans:
            print("\nKeine Plaene gefunden.")
            return
        print(f"\n{'ID':<16} {'Status':<12} {'Fortschritt':<14} Titel")
        print("-" * 70)
        for p in plans:
            progress = f"{p['steps_done']}/{p['steps_total']}"
            print(f"{p['id']:<16} {p['status']:<12} {progress:<14} {p['title']}")

    elif args.command == "show":
        plan = agent.get_plan(args.plan_id)
        if not plan:
            print(f"Plan nicht gefunden: {args.plan_id}")
            return
        print(agent.export_plan(args.plan_id, "markdown"))

    elif args.command == "next":
        try:
            steps = agent.get_next_steps(args.plan_id)
        except ValueError as e:
            print(str(e))
            return
        if not steps:
            print("Keine offenen Schritte verfuegbar.")
            return
        print(f"\nNaechste Schritte fuer {args.plan_id}:")
        for s in steps:
            print(f"  - {s['id']}: {s['title']}")
            if s.get("description"):
                print(f"    {s['description']}")

    elif args.command == "export":
        try:
            output = agent.export_plan(args.plan_id, args.format)
        except ValueError as e:
            print(str(e))
            return
        print(output)

    elif args.command == "status":
        st = agent.status()
        print(f"\nPlan Agent v{st['version']}")
        print(f"  BACH: {'ja' if st['bach_available'] else 'nein'}")
        print(f"  Plaene: {st['plans_total']} gesamt")
        print(f"    Draft: {st['plans_draft']}")
        print(f"    Aktiv: {st['plans_active']}")
        print(f"    Fertig: {st['plans_completed']}")
        print(f"  Verzeichnis: {st['plans_dir']}")


if __name__ == "__main__":
    main()
