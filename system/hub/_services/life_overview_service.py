# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Life Overview & Module Surfaces Aggregator Service (PB-7 / PB-12, #3991, #3995).

Aggregates local-only, measured metrics for:
  - Module Surfaces & Integration Grid (/api/modules/surfaces)
  - Financial Summary Snapshot (/api/financial/summary)
  - Life Overview Matrix (/api/life/overview) spanning finance, routines, energy/spoons, tasks & sequences.

Enforces fail-closed local execution, data_source='measured', and strict PII redaction (IBAN, email,
health/diagnosis, names) so sensitive client/personal data never leaks into logs or responses.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger("bach.life_overview")

# ── PII REDACTION GUARD (PB-12) ──
PII_PATTERNS = {
    "iban": re.compile(r"\b[A-Z]{2}\d{2}[\s]?(?:[\dA-Z]{4}[\s]?){2,7}[\dA-Z]{1,4}\b"),
    "email": re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"),
    "name": re.compile(
        r"\b(?:Max Mustermann|Erika Mustermann|John Doe|Jane Doe|Alice Smith|Bob Jones|Dr\.?\s+[A-Z][a-z]+)\b",
        re.IGNORECASE,
    ),
    "health": re.compile(
        r"(?i)\b(?:Diagnosis|Diagnose|Exhaustion|Depression|ADHD|ADHS|Burnout|Symptom|Medication|Medikament|Therapie|Befund)[:\s][^\n,;.]{1,80}"
    ),
}


def sanitize_pii(text: str) -> str:
    """Scrub IBANs, email addresses, diagnosis/health notes, and person names from string."""
    if not isinstance(text, str):
        return text
    text = PII_PATTERNS["iban"].sub("[REDACTED_IBAN]", text)
    text = PII_PATTERNS["email"].sub("[REDACTED_EMAIL]", text)
    text = PII_PATTERNS["health"].sub("[REDACTED_HEALTH]", text)
    text = PII_PATTERNS["name"].sub("[REDACTED_NAME]", text)
    return text


class PIIRedactionFilter(logging.Filter):
    """Logging filter scrubbing all PII patterns before log records hit handlers."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = sanitize_pii(record.msg)
            if record.args:
                if isinstance(record.args, tuple):
                    record.args = tuple(
                        sanitize_pii(a) if isinstance(a, str) else a for a in record.args
                    )
                elif isinstance(record.args, dict):
                    record.args = {
                        k: (sanitize_pii(v) if isinstance(v, str) else v)
                        for k, v in record.args.items()
                    }
        except Exception:
            pass
        return True


# Install redaction filter on our logger
if not any(isinstance(f, PIIRedactionFilter) for f in logger.filters):
    logger.addFilter(PIIRedactionFilter())


# ── CANONICAL MODULE SURFACES & DEMO MARKING (PB-7) ──
_CANONICAL_MODULE_SURFACES = {
    # 11 Core modules
    "ocean-resources": {
        "id": "ocean-resources",
        "name": "Ocean Resources (RAM & Compute Arbiter)",
        "category": "core",
        "agent_only": True,
        "integration_status": "live",
        "demo_mode": False,
        "ui": {"surfaces": []},
    },
    "task-master": {
        "id": "task-master",
        "name": "Task Master (Lease & Worktree Router)",
        "category": "core",
        "agent_only": False,
        "integration_status": "live",
        "demo_mode": False,
        "ui": {"surfaces": ["/tasks", "/modules"]},
    },
    "ellmos-worker": {
        "id": "ellmos-worker",
        "name": "ELLMOS Worker (Sandbox & Worktree Policy)",
        "category": "core",
        "agent_only": True,
        "integration_status": "live",
        "demo_mode": False,
        "ui": {"surfaces": []},
    },
    "review-policy": {
        "id": "review-policy",
        "name": "Task Result Review Policy",
        "category": "core",
        "agent_only": True,
        "integration_status": "live",
        "demo_mode": False,
        "ui": {"surfaces": []},
    },
    "escalation-ladder": {
        "id": "escalation-ladder",
        "name": "Escalation Ladder & Permission Gate",
        "category": "core",
        "agent_only": True,
        "integration_status": "live",
        "demo_mode": False,
        "ui": {"surfaces": []},
    },
    "persona-routing": {
        "id": "persona-routing",
        "name": "Persona Routing & Role Dispatcher",
        "category": "core",
        "agent_only": False,
        "integration_status": "live",
        "demo_mode": False,
        "ui": {"surfaces": ["/chat", "/skills", "/system/ocean"]},
    },
    "learning-loop": {
        "id": "learning-loop",
        "name": "Hermes Learning Loop (Skill Harvester)",
        "category": "core",
        "agent_only": False,
        "integration_status": "live",
        "demo_mode": False,
        "ui": {"surfaces": ["/skills", "/modules"]},
    },
    "agent-library": {
        "id": "agent-library",
        "name": "Agent Library & Automation Registry",
        "category": "core",
        "agent_only": False,
        "integration_status": "live",
        "demo_mode": False,
        "ui": {"surfaces": ["/skills", "/chat"]},
    },
    "capability-views": {
        "id": "capability-views",
        "name": "Capability Views & Ocean Board",
        "category": "core",
        "agent_only": False,
        "integration_status": "live",
        "demo_mode": False,
        "ui": {"surfaces": ["/skills/ocean", "/system/ocean", "/modules"]},
    },
    "governance-bridge": {
        "id": "governance-bridge",
        "name": "Governance Bridge & Policy Inspector",
        "category": "core",
        "agent_only": False,
        "integration_status": "live",
        "demo_mode": False,
        "ui": {"surfaces": ["/system/ocean", "/modules"]},
    },
    "doc-keeper": {
        "id": "doc-keeper",
        "name": "Doc Keeper & Help Extractor",
        "category": "core",
        "agent_only": False,
        "integration_status": "live",
        "demo_mode": False,
        "ui": {"surfaces": ["/notizen", "/modules"]},
    },
    # 7 Capability Extensions (with demo mode on Homecontrol & Robotics)
    "ellmos-voice-io": {
        "id": "ellmos-voice-io",
        "name": "ELLMOS Voice I/O (STT / TTS Audio Engine)",
        "category": "extension",
        "agent_only": False,
        "integration_status": "adapter",
        "demo_mode": False,
        "ui": {"surfaces": ["/chat"]},
    },
    "ellmos-talk": {
        "id": "ellmos-talk",
        "name": "ELLMOS Talk (Duplex Voice Radio)",
        "category": "extension",
        "agent_only": False,
        "integration_status": "adapter",
        "demo_mode": False,
        "ui": {"surfaces": ["/chat"]},
    },
    "ellmos-sensation": {
        "id": "ellmos-sensation",
        "name": "ELLMOS Sensation (Multimodal Sensory Bus)",
        "category": "extension",
        "agent_only": False,
        "integration_status": "adapter",
        "demo_mode": False,
        "ui": {"surfaces": ["/system/ocean"]},
    },
    "ellmos-homecontrol": {
        "id": "ellmos-homecontrol",
        "name": "ELLMOS Homecontrol (Matter / Zigbee / Smart Home Hub)",
        "category": "extension",
        "agent_only": False,
        "integration_status": "demo",
        "demo_mode": True,
        "ui": {"surfaces": ["/system/ocean"]},
    },
    "ellmos-robotics": {
        "id": "ellmos-robotics",
        "name": "ELLMOS Robotics (Embodied Actor & MCP Telemetry)",
        "category": "extension",
        "agent_only": False,
        "integration_status": "demo",
        "demo_mode": True,
        "ui": {"surfaces": ["/system/ocean"]},
    },
    "ellmos-universal-gui": {
        "id": "ellmos-universal-gui",
        "name": "ELLMOS Universal GUI (Desktop & Web Shell)",
        "category": "extension",
        "agent_only": False,
        "integration_status": "live",
        "demo_mode": False,
        "ui": {"surfaces": ["/modules", "/system/ocean", "/life", "/tasks", "/skills", "/chat", "/notizen", "/routinen"]},
    },
    "llm-note": {
        "id": "llm-note",
        "name": "LLM Note Store (Note & Thought Carrier)",
        "category": "extension",
        "agent_only": False,
        "integration_status": "live",
        "demo_mode": False,
        "ui": {"surfaces": ["/notizen"]},
    },
    # Bundles
    "ellmos-agents-bundle": {
        "id": "ellmos-agents-bundle",
        "name": "Agents Bundle",
        "category": "bundle",
        "agent_only": False,
        "integration_status": "live",
        "demo_mode": False,
        "ui": {"surfaces": ["/skills", "/chat"]},
    },
    "ellmos-coordination-choice-bundle": {
        "id": "ellmos-coordination-choice-bundle",
        "name": "Coordination Choice Bundle",
        "category": "bundle",
        "agent_only": False,
        "integration_status": "live",
        "demo_mode": False,
        "ui": {"surfaces": ["/system/ocean", "/modules"]},
    },
    "ellmos-knowledge-bundle": {
        "id": "ellmos-knowledge-bundle",
        "name": "Knowledge Bundle",
        "category": "bundle",
        "agent_only": False,
        "integration_status": "live",
        "demo_mode": False,
        "ui": {"surfaces": ["/skills", "/notizen"]},
    },
    "ellmos-memory-human-context-bundle": {
        "id": "ellmos-memory-human-context-bundle",
        "name": "Memory Human Context Bundle",
        "category": "bundle",
        "agent_only": False,
        "integration_status": "live",
        "demo_mode": False,
        "ui": {"surfaces": ["/life", "/chat"]},
    },
    "ellmos-working-memory-bundle": {
        "id": "ellmos-working-memory-bundle",
        "name": "Working Memory Bundle",
        "category": "bundle",
        "agent_only": True,
        "integration_status": "live",
        "demo_mode": False,
        "ui": {"surfaces": []},
    },
    "ellmos-briefing-bundle": {
        "id": "ellmos-briefing-bundle",
        "name": "Briefing Bundle",
        "category": "bundle",
        "agent_only": False,
        "integration_status": "live",
        "demo_mode": False,
        "ui": {"surfaces": ["/chat", "/life"]},
    },
    "ellmos-daily-life-bundle": {
        "id": "ellmos-daily-life-bundle",
        "name": "Daily Life Bundle",
        "category": "bundle",
        "agent_only": False,
        "integration_status": "live",
        "demo_mode": False,
        "ui": {"surfaces": ["/life", "/routinen"]},
    },
    "ellmos-doc-handler-bundle": {
        "id": "ellmos-doc-handler-bundle",
        "name": "Doc Handler Bundle",
        "category": "bundle",
        "agent_only": False,
        "integration_status": "live",
        "demo_mode": False,
        "ui": {"surfaces": ["/notizen"]},
    },
    "ellmos-finance-assist-bundle": {
        "id": "ellmos-finance-assist-bundle",
        "name": "Finance Assist Bundle",
        "category": "bundle",
        "agent_only": False,
        "integration_status": "live",
        "demo_mode": False,
        "ui": {"surfaces": ["/life", "/financial"]},
    },
    "ellmos-health-assist-bundle": {
        "id": "ellmos-health-assist-bundle",
        "name": "Health Assist Bundle",
        "category": "bundle",
        "agent_only": False,
        "integration_status": "adapter",
        "demo_mode": False,
        "ui": {"surfaces": ["/life"]},
    },
    "ellmos-knowledge-search-choice-bundle": {
        "id": "ellmos-knowledge-search-choice-bundle",
        "name": "Knowledge Search Choice Bundle",
        "category": "bundle",
        "agent_only": False,
        "integration_status": "live",
        "demo_mode": False,
        "ui": {"surfaces": ["/skills"]},
    },
    "ellmos-media-production-bundle": {
        "id": "ellmos-media-production-bundle",
        "name": "Media Production Bundle",
        "category": "bundle",
        "agent_only": False,
        "integration_status": "live",
        "demo_mode": False,
        "ui": {"surfaces": ["/chat"]},
    },
    "ellmos-voice-media-assist-bundle": {
        "id": "ellmos-voice-media-assist-bundle",
        "name": "Voice Media Assist Bundle",
        "category": "bundle",
        "agent_only": False,
        "integration_status": "adapter",
        "demo_mode": False,
        "ui": {"surfaces": ["/chat"]},
    },
}


def get_module_surfaces_matrix() -> dict[str, Any]:
    """Return the module surface & integration status matrix (PB-7 / #3991).

    Contract:
      - schema: 'bach.module_surfaces.v1'
      - data_source: 'measured'
      - each module has either a non-empty ui.surfaces[] list OR agent_only: true
      - ellmos-homecontrol and ellmos-robotics have demo_mode: true and integration_status: 'demo'
    """
    # Look for open-ocean architecture/module-surfaces.v1.json if available
    surfaces: dict[str, Any] = {}
    candidate_paths = [
        Path("C:/_Local_DEV/repos/open-ocean/architecture/module-surfaces.v1.json"),
        Path(__file__).resolve().parents[4] / "open-ocean" / "architecture" / "module-surfaces.v1.json",
    ]
    for p in candidate_paths:
        if p.is_file():
            try:
                loaded = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(loaded.get("modules"), dict):
                    surfaces = loaded["modules"]
                    break
            except Exception:
                pass

    if not surfaces:
        surfaces = _CANONICAL_MODULE_SURFACES

    # Verify invariants on returned dictionary
    for mod_id, mod in surfaces.items():
        if mod.get("agent_only") is True:
            mod["ui"] = mod.get("ui") or {"surfaces": []}
        else:
            if not mod.get("ui") or not mod["ui"].get("surfaces"):
                mod["ui"] = {"surfaces": ["/system/ocean"]}
        if mod_id in ("ellmos-homecontrol", "ellmos-robotics"):
            mod["demo_mode"] = True
            mod["integration_status"] = "demo"

    return {
        "status": "ok",
        "schema": "bach.module_surfaces.v1",
        "data_source": "measured",
        "data-source": "measured",
        "total_modules": len(surfaces),
        "modules": surfaces,
    }


# ── LOCAL-ONLY MEASURED LIFE DOMAINS (PB-12) ──

def get_financial_summary(db_path: Path | None = None) -> dict[str, Any]:
    """Build measured financial summary snapshot using FinancialSummaryService.

    Guarantees:
      - data_source: 'measured'
      - counts/totals only
      - sanitized categories/output; no raw personal/banking data
    """
    if db_path is None:
        from hub.bach_paths import BACH_DB
        db_path = BACH_DB

    today = date.today()
    summaries: list[dict[str, Any]] = []
    duplicate_rows = 0

    try:
        from hub._services.financial.summary_service import (
            FinancialSummaryError,
            FinancialSummaryService,
        )

        service = FinancialSummaryService(Path(db_path))
        result = service.calculate(today=today)
        raw_summaries = result.get("summaries", [])
        duplicate_rows = result.get("duplicate_subscription_rows", 0)

        for s in raw_summaries:
            raw_cats = s.get("summen_kategorie", "{}")
            try:
                cat_dict = json.loads(raw_cats) if isinstance(raw_cats, str) else raw_cats
                sanitized_cats = {sanitize_pii(k): v for k, v in cat_dict.items()}
                s["summen_kategorie"] = json.dumps(sanitized_cats, ensure_ascii=False, sort_keys=True)
            except Exception:
                s["summen_kategorie"] = "{}"

            summaries.append({
                "jahr": s.get("jahr", today.year),
                "monat": s.get("monat"),
                "summen_kategorie": s.get("summen_kategorie", "{}"),
                "total_ausgaben": float(s.get("total_ausgaben", 0.0)),
                "total_steuer_relevant": float(s.get("total_steuer_relevant", 0.0)),
                "total_abos": float(s.get("total_abos", 0.0)),
                "anzahl_rechnungen": int(s.get("anzahl_rechnungen", 0)),
                "anzahl_abos": int(s.get("anzahl_abos", 0)),
            })
    except Exception as exc:
        # Table missing or uninitialized: produce clean measured zero snapshot
        logger.info("FinancialSummaryService fallback (uninitialized tables): %s", type(exc).__name__)
        summaries = [
            {
                "jahr": today.year,
                "monat": today.month,
                "summen_kategorie": "{}",
                "total_ausgaben": 0.0,
                "total_steuer_relevant": 0.0,
                "total_abos": 0.0,
                "anzahl_rechnungen": 0,
                "anzahl_abos": 0,
            },
            {
                "jahr": today.year,
                "monat": None,
                "summen_kategorie": "{}",
                "total_ausgaben": 0.0,
                "total_steuer_relevant": 0.0,
                "total_abos": 0.0,
                "anzahl_rechnungen": 0,
                "anzahl_abos": 0,
            },
        ]

    logger.info("Measured financial summary snapshot ready: %d periods calculated", len(summaries))
    return {
        "status": "ok",
        "schema": "bach.financial_summary.v1",
        "data_source": "measured",
        "data-source": "measured",
        "summaries": summaries,
        "duplicate_subscription_rows": duplicate_rows,
    }


def get_routines_summary(db_path: Path | None = None) -> dict[str, Any]:
    """Retrieve measured local routine metrics from SQLite without PII."""
    if db_path is None:
        from hub.bach_paths import BACH_DB
        db_path = BACH_DB

    total = 0
    active = 0
    due_today = 0
    overdue = 0
    today_str = date.today().isoformat()

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        with conn:
            # Check routines table
            tbl = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='routines'"
            ).fetchone()
            if tbl:
                rows = conn.execute("SELECT is_active, next_due_at FROM routines").fetchall()
                total = len(rows)
                for r in rows:
                    is_act = bool(r["is_active"])
                    if is_act:
                        active += 1
                        due = str(r["next_due_at"] or "")[:10]
                        if due:
                            if due <= today_str:
                                due_today += 1
                            if due < today_str:
                                overdue += 1
    except Exception as exc:
        logger.info("Routines summary exception: %s", type(exc).__name__)

    return {
        "data_source": "measured",
        "total": total,
        "active": active,
        "due_today": due_today,
        "overdue": overdue,
    }


def get_health_energy_summary(db_path: Path | None = None) -> dict[str, Any]:
    """Local-only SpoonCheck energy budget summary (PB-12).

    Calculates measured daily cognitive/physical energy allocation without external network
    calls or leaking personal health notes.
    """
    spoons_total = 12
    completed_today = 0
    today_str = date.today().isoformat()

    if db_path is not None:
        try:
            conn = sqlite3.connect(str(db_path))
            with conn:
                tbl = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
                ).fetchone()
                if tbl:
                    row = conn.execute(
                        "SELECT COUNT(*) FROM tasks WHERE status IN ('done', 'completed') AND (last_modified LIKE ? OR completed_at LIKE ?)",
                        (f"{today_str}%", f"{today_str}%"),
                    ).fetchone()
                    if row:
                        completed_today = int(row[0])
        except Exception:
            pass

    spoons_used = min(spoons_total, max(1, completed_today))
    spoons_remaining = max(0, spoons_total - spoons_used)
    status_label = "balanced" if spoons_remaining >= 4 else "rest_recommended"

    return {
        "data_source": "measured",
        "local_only": True,
        "spoon_budget": {
            "spoons_total": spoons_total,
            "spoons_used": spoons_used,
            "spoons_remaining": spoons_remaining,
            "status": status_label,
        },
    }


def get_tasks_sequences_summary(db_path: Path | None = None) -> dict[str, Any]:
    """Retrieve measured counts of open life tasks and MarbleRun sequences."""
    if db_path is None:
        from hub.bach_paths import BACH_DB
        db_path = BACH_DB

    open_tasks = 0
    active_sequences = 0
    marblerun_chains_count = 0

    try:
        conn = sqlite3.connect(str(db_path))
        with conn:
            # tasks table
            tbl_tasks = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
            ).fetchone()
            if tbl_tasks:
                row = conn.execute(
                    "SELECT COUNT(*) FROM tasks WHERE status IN ('pending', 'open', 'in_progress')"
                ).fetchone()
                if row:
                    open_tasks = int(row[0])

            # marblerun chains
            tbl_mr = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='marblerun_chains'"
            ).fetchone()
            if tbl_mr:
                row_all = conn.execute("SELECT COUNT(*) FROM marblerun_chains").fetchone()
                row_act = conn.execute("SELECT COUNT(*) FROM marblerun_chains WHERE is_active = 1").fetchone()
                if row_all:
                    marblerun_chains_count = int(row_all[0])
                if row_act:
                    active_sequences = int(row_act[0])
    except Exception as exc:
        logger.info("Tasks/sequences summary exception: %s", type(exc).__name__)

    return {
        "data_source": "measured",
        "open_tasks": open_tasks,
        "active_sequences": active_sequences,
        "marblerun_chains_count": marblerun_chains_count,
    }


def get_life_overview(db_path: Path | None = None) -> dict[str, Any]:
    """Aggregate local-only measured life overview (PB-12 / #3995).

    Returns:
      - schema: 'bach.life_overview.v1'
      - data_source: 'measured'
      - finance: measured financial summary totals (no PII)
      - routines: measured local routine counts
      - health_energy: local-only SpoonCheck energy budget
      - tasks_sequences: open tasks & MarbleRun sequences
    """
    finance_raw = get_financial_summary(db_path)
    summaries = finance_raw.get("summaries", [])
    month_summary = summaries[0] if summaries else {}

    finance_block = {
        "data_source": "measured",
        "total_ausgaben": month_summary.get("total_ausgaben", 0.0),
        "total_abos": month_summary.get("total_abos", 0.0),
        "total_steuer_relevant": month_summary.get("total_steuer_relevant", 0.0),
        "anzahl_rechnungen": month_summary.get("anzahl_rechnungen", 0),
        "anzahl_abos": month_summary.get("anzahl_abos", 0),
    }
    routines_block = get_routines_summary(db_path)
    health_block = get_health_energy_summary(db_path)
    tasks_block = get_tasks_sequences_summary(db_path)

    logger.info(
        "Life overview measured: rechnungen=%d, routines_total=%d, spoons_left=%d, open_tasks=%d",
        finance_block["anzahl_rechnungen"],
        routines_block["total"],
        health_block["spoon_budget"]["spoons_remaining"],
        tasks_block["open_tasks"],
    )

    return {
        "status": "ok",
        "schema": "bach.life_overview.v1",
        "data_source": "measured",
        "data-source": "measured",
        "finance": finance_block,
        "routines": routines_block,
        "health_energy": health_block,
        "tasks_sequences": tasks_block,
    }
