"""
NemoFold Workflow-Lernen & Step-Ketten Synthese Service (Ocean Subsystem).

Analysiert autonome Session-Logs und Werkzeugfolgen ueber mehrere Sessions,
erkennt wiederkehrende Aktionsmuster (Heuristik-Detektor), giesst sie in
strukturierte, wiederverwendbare Step-Ketten (MarbleRun / Toolchains) und
prüft deren Metadaten statisch. Diese Heuristik führt weder Tests noch einen
Action-Journal-Rollback aus und veröffentlicht keine native Kette.

Verknuepft mit Ticket T-20261003-605028960 / Ocean Task 490 (#1688).
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .learning_review_service import (
    LearningConflict, ensure_review_schema, project_candidate, proposal_binding,
    prohibit_legacy_promotion, record_review,
)

logger = logging.getLogger("nemofold_workflow_service")


# ═══════════════════════════════════════════════════════════════
# SCHEMA DEFINITION
# ═══════════════════════════════════════════════════════════════

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS nemofold_workflow_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chain_name TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT,
    trigger_type TEXT DEFAULT 'manual',
    steps_json TEXT NOT NULL,
    confidence_score REAL DEFAULT 0.8,
    tuv_status TEXT DEFAULT 'certified',
    tuv_report_json TEXT,
    status TEXT DEFAULT 'pending',
    provenance_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reviewed_by TEXT,
    review_notes TEXT,
    promoted_to_chain_id INTEGER
);

CREATE TABLE IF NOT EXISTS nemofold_synthesis_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    source_ref TEXT,
    patterns_detected INTEGER DEFAULT 0,
    chains_synthesized INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    details_json TEXT
);
"""

# ═══════════════════════════════════════════════════════════════
# NORMALIZATION & ACTION CLASSIFIERS
# ═══════════════════════════════════════════════════════════════

TOOL_ACTION_MAP: dict[str, tuple[str, str, str]] = {
    # Tool/Command -> (Semantic Category, Default Agent, Reversibility)
    "fc_read_file": ("search_inspect", "Ati", "safe_read"),
    "view_file": ("search_inspect", "Ati", "safe_read"),
    "fc_search_files": ("search_inspect", "Ati", "safe_read"),
    "fc_search_content": ("search_inspect", "Ati", "safe_read"),
    "search_web": ("search_inspect", "Ati", "safe_read"),
    "read_url_content": ("search_inspect", "Ati", "safe_read"),
    "cc_analyze_code": ("analyze_diagnose", "bach", "safe_read"),
    "cc_diagnose_imports": ("analyze_diagnose", "bach", "safe_read"),
    "cc_analyze_methods": ("analyze_diagnose", "bach", "safe_read"),
    "controlcenter_check_lock": ("security_gate", "bach", "safe_read"),
    "lock_status": ("security_gate", "bach", "safe_read"),
    "replace_file_content": ("edit_transform", "codex", "two_phase_journal"),
    "write_to_file": ("edit_transform", "codex", "two_phase_journal"),
    "fc_edit_file": ("edit_transform", "codex", "two_phase_journal"),
    "fc_write_file": ("edit_transform", "codex", "two_phase_journal"),
    "pytest": ("verify_test", "Ollama Local", "safe_exec"),
    "test_run": ("verify_test", "Ollama Local", "safe_exec"),
    "ruff_check": ("verify_test", "Ollama Local", "safe_exec"),
    "lint_mermaid": ("verify_test", "Ollama Local", "safe_exec"),
    "git_commit": ("commit_release", "Sentinel", "reversible_git"),
    "gh_pr_create": ("commit_release", "Sentinel", "reversible_git"),
}


class NemoFoldWorkflowService:
    """Kernservice fuer Workflow-Lernen, Heuristik-Detektion und Ketten-Synthese."""

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            from hub.bach_paths import BACH_DB
            self.db_path = str(BACH_DB)
        else:
            self.db_path = str(db_path)
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout = 30000")
        except sqlite3.OperationalError:
            pass
        return conn

    def _ensure_schema(self) -> None:
        conn = self._get_conn()
        try:
            conn.executescript(SCHEMA_SQL)
            ensure_review_schema(conn, "nemofold")
            conn.commit()
        finally:
            conn.close()

    # ─────────────────────────────────────────────────────────────
    # 1. PARSING & NORMALISIERUNG
    # ─────────────────────────────────────────────────────────────

    def parse_events_from_transcript(self, transcript_content: str) -> list[dict[str, Any]]:
        """Extrahiert Werkzeugaufrufe und Shell-Aktionen aus JSONL oder Freitext-Logs."""
        events: list[dict[str, Any]] = []
        if not transcript_content or not transcript_content.strip():
            return events

        # Versuch 1: JSONL zeilenweise
        lines = transcript_content.strip().split("\n")
        jsonl_parsed = False
        for line in lines:
            line_str = line.strip()
            if not line_str.startswith("{") or not line_str.endswith("}"):
                continue
            try:
                data = json.loads(line_str)
                jsonl_parsed = True
                tool_calls = data.get("tool_calls", [])
                for tc in tool_calls:
                    fn_name = tc.get("name") or tc.get("tool") or ""
                    args = tc.get("args") or tc.get("parameters") or {}
                    if fn_name:
                        events.append(self._normalize_event(fn_name, args, data.get("source", "agent")))

                # Check direct action or message commands
                content = str(data.get("content", ""))
                self._extract_embedded_commands(content, events)
            except (json.JSONDecodeError, ValueError, KeyError):
                continue

        if jsonl_parsed and events:
            return self._coalesce_events(events)

        # Versuch 2: Freitext / Regex-Extraktion von Tool-Aufrufen & Shell-Commands
        self._extract_embedded_commands(transcript_content, events)
        return self._coalesce_events(events)

    def _extract_embedded_commands(self, text: str, events: list[dict[str, Any]]) -> None:
        """Erkennt Tool-Befehle und Shell-Invocations aus Fließtexten."""
        # Pattern für Tools: tool_name(args) oder [tool_name]
        tool_pattern = re.compile(
            r"(?:\b(?:call|invoking|running|use)\s+)?`?([a-zA-Z0-9_\-\.]+)\(([^()\r\n]{0,500})\)`?",
            re.IGNORECASE,
        )
        for m in tool_pattern.finditer(text):
            t_name = m.group(1).lower()
            if t_name in TOOL_ACTION_MAP or any(k in t_name for k in ["file", "search", "test", "lint", "git", "diff", "analyze"]):
                events.append(self._normalize_event(t_name, {"raw_args": m.group(2)[:100]}, "transcript_regex"))

        # Pattern für Shell-Befehle wie pytest, ruff, git commit, gh pr
        if "pytest" in text:
            events.append(self._normalize_event("pytest", {"command": "pytest"}, "shell_match"))
        if "ruff check" in text:
            events.append(self._normalize_event("ruff_check", {"command": "ruff check"}, "shell_match"))
        if "lint_mermaid" in text:
            events.append(self._normalize_event("lint_mermaid", {"command": "lint_mermaid"}, "shell_match"))
        if "git commit" in text:
            events.append(self._normalize_event("git_commit", {"command": "git commit"}, "shell_match"))
        if "gh pr create" in text:
            events.append(self._normalize_event("gh_pr_create", {"command": "gh pr create"}, "shell_match"))

    def _normalize_event(self, tool_name: str, args: dict[str, Any], source: str) -> dict[str, Any]:
        cleaned_tool = tool_name.strip().lower()
        mapping = TOOL_ACTION_MAP.get(cleaned_tool)
        if not mapping:
            # Heuristische Einordnung
            if any(k in cleaned_tool for k in ["read", "view", "search", "list", "get", "query", "fetch", "cat"]):
                cat, ag, rev = ("search_inspect", "Ati", "safe_read")
            elif any(k in cleaned_tool for k in ["analyze", "diagnose", "diff", "check", "inspect", "ast"]):
                cat, ag, rev = ("analyze_diagnose", "bach", "safe_read")
            elif any(k in cleaned_tool for k in ["write", "edit", "replace", "create", "patch", "modify"]):
                cat, ag, rev = ("edit_transform", "codex", "two_phase_journal")
            elif any(k in cleaned_tool for k in ["test", "lint", "pytest", "eval", "verify", "audit"]):
                cat, ag, rev = ("verify_test", "Ollama Local", "safe_exec")
            elif any(k in cleaned_tool for k in ["git", "commit", "push", "pr", "deploy", "release"]):
                cat, ag, rev = ("commit_release", "Sentinel", "reversible_git")
            else:
                cat, ag, rev = ("generic_step", "bach", "standard")
        else:
            cat, ag, rev = mapping

        return {
            "tool": cleaned_tool,
            "category": cat,
            "agent": ag,
            "reversibility": rev,
            "args_summary": {k: str(v)[:80] for k, v in args.items()} if isinstance(args, dict) else {},
            "source": source
        }

    def _coalesce_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Fasst unmittelbar aufeinanderfolgende identische Aktionen zusammen."""
        if not events:
            return []
        coalesced: list[dict[str, Any]] = []
        for ev in events:
            if coalesced and coalesced[-1]["category"] == ev["category"] and coalesced[-1]["tool"] == ev["tool"]:
                # Zähler erhöhen statt Liste aufzublähen
                coalesced[-1]["repeat_count"] = coalesced[-1].get("repeat_count", 1) + 1
            else:
                ev_copy = dict(ev)
                ev_copy["repeat_count"] = 1
                coalesced.append(ev_copy)
        return coalesced

    # ─────────────────────────────────────────────────────────────
    # 2. HEURISTIK-DETEKTOR & WORKFLOW-SYNTHESE
    # ─────────────────────────────────────────────────────────────

    def synthesize_chains_from_events(
        self,
        events: list[dict[str, Any]],
        context_name: str = "Autonome Session",
        min_steps: int = 2
    ) -> list[dict[str, Any]]:
        """Synthetisiert wiederverwendbare Step-Ketten aus normalisierten Event-Sequenzen."""
        if not events or len(events) < min_steps:
            return []

        synthesized_chains: list[dict[str, Any]] = []

        # Wir detektieren klassische Pipeline-Muster:
        categories = [e["category"] for e in events]

        # 1. Dev / Refactoring / Bugfix Pattern:
        if "edit_transform" in categories:
            chain = self._build_dev_renovation_chain(events, context_name)
            if chain:
                synthesized_chains.append(chain)

        # 2. Research & Extraction Pattern:
        if "search_inspect" in categories and "analyze_diagnose" in categories and "edit_transform" not in categories:
            chain = self._build_research_extraction_chain(events, context_name)
            if chain:
                synthesized_chains.append(chain)

        # 3. 4-Eyes Multi-Agent Review Pattern:
        if "verify_test" in categories and len(events) >= 3:
            chain = self._build_multi_agent_review_chain(events, context_name)
            if chain:
                synthesized_chains.append(chain)

        # Fallback: Allgemeine sequenzielle Step-Kette
        if not synthesized_chains and len(events) >= min_steps:
            chain = self._build_generic_step_chain(events, context_name)
            if chain:
                synthesized_chains.append(chain)

        return synthesized_chains

    def _build_dev_renovation_chain(self, events: list[dict[str, Any]], context_name: str) -> dict[str, Any]:
        slug = f"nemofold-dev-pipeline-{int(datetime.now(timezone.utc).timestamp())}"
        steps = [
            {
                "step_index": 1,
                "name": "Bausubstanz- & Code-Inspektion",
                "agent": "Ati",
                "tool": "fc_search_content",
                "category": "search_inspect",
                "inputs": {"scope": "repo_code", "query": "target_symbols"},
                "expected_output": "code_locations_list",
                "reversible": True,
                "action_journal_support": True,
                "description": "Erkundung relevanter Dateien, Signaturen und Lock-Status."
            },
            {
                "step_index": 2,
                "name": "AST-Analyse & Vorab-Diagnose",
                "agent": "bach",
                "tool": "cc_analyze_code",
                "category": "analyze_diagnose",
                "inputs": {"target": "$step1.output"},
                "expected_output": "diagnostics_report",
                "reversible": True,
                "action_journal_support": True,
                "description": "Pruefung auf Importfehler, Vertragsluecken und Klassenstrukturen."
            },
            {
                "step_index": 3,
                "name": "Praezise Transformation & Code-Edit",
                "agent": "codex",
                "tool": "replace_file_content",
                "category": "edit_transform",
                "inputs": {"instruction": "apply_patch", "files": "$step1.output"},
                "expected_output": "patch_receipt",
                "reversible": True,
                "action_journal_support": True,
                "description": "Punktgenaue Modifikation unter Two-Phase Action-Journal Protokoll."
            },
            {
                "step_index": 4,
                "name": "Regressionstests & Syntax-Audits",
                "agent": "Ollama Local",
                "tool": "pytest",
                "category": "verify_test",
                "inputs": {"test_command": "pytest -q", "linters": ["ruff check", "lint_mermaid"]},
                "expected_output": "test_and_lint_report",
                "reversible": True,
                "action_journal_support": False,
                "description": "Automatisierte 4-Augen-Validierung im lokalen Sandbox-Runner."
            },
            {
                "step_index": 5,
                "name": "Human-in-the-Loop Release & PR-Handoff",
                "agent": "Sentinel",
                "tool": "gh_pr_create",
                "category": "commit_release",
                "inputs": {"branch": "feat/*", "title": "Automated Verified Pipeline"},
                "expected_output": "pull_request_url",
                "reversible": True,
                "action_journal_support": False,
                "description": "Erstellung des PRs ohne unautorisierten Direct-Main-Push."
            }
        ]

        tuv_status, tuv_report = self._evaluate_workflow_tuv(steps)

        return {
            "name": slug,
            "title": f"Gelehrter Dev-Fix Workflow ({context_name})",
            "description": "Aus Session extrahierte 5-stufige Software-Renovierungs- und Fix-Pipeline mit Rollback-Schutz.",
            "trigger_type": "manual",
            "steps": steps,
            "confidence_score": 0.92,
            "tuv_status": tuv_status,
            "tuv_report": tuv_report,
            "provenance": {
                "synthesized_by": "nemofold:heuristic-detector:v1",
                "session_context": context_name,
                "observed_event_count": len(events),
                "pattern_type": "dev_renovation_pipeline"
            }
        }

    def _build_research_extraction_chain(self, events: list[dict[str, Any]], context_name: str) -> dict[str, Any]:
        slug = f"nemofold-research-chain-{int(datetime.now(timezone.utc).timestamp())}"
        steps = [
            {
                "step_index": 1,
                "name": "Föderierte Wissensrecherche",
                "agent": "Ati",
                "tool": "fc_search_content",
                "category": "search_inspect",
                "inputs": {"query": "knowledge_topic", "sources": ["docs/", "notes/"]},
                "expected_output": "document_snippets",
                "reversible": True,
                "action_journal_support": True,
                "description": "Volltextsuche ueber lokale Markdown-Dokumente und Wissensbestaende."
            },
            {
                "step_index": 2,
                "name": "Evidenz-Strukturierung & Faktenfilter",
                "agent": "bach",
                "tool": "cc_analyze_code",
                "category": "analyze_diagnose",
                "inputs": {"raw_sources": "$step1.output"},
                "expected_output": "verified_claims_and_evidence",
                "reversible": True,
                "action_journal_support": True,
                "description": "Ausschluss von Halluzinationen und Isolierung harter Fakten."
            },
            {
                "step_index": 3,
                "name": "Synthese & Briefing-Ablage",
                "agent": "codex",
                "tool": "write_to_file",
                "category": "edit_transform",
                "inputs": {"target_path": "docs/briefings/", "content": "$step2.output"},
                "expected_output": "briefing_file_receipt",
                "reversible": True,
                "action_journal_support": True,
                "description": "Erstellung eines kompakten Ergebnisberichts."
            }
        ]

        tuv_status, tuv_report = self._evaluate_workflow_tuv(steps)

        return {
            "name": slug,
            "title": f"Recherche- & Wissens-Kette ({context_name})",
            "description": "Mehrstufiger Wissensrecherche- und Fakten-Extraktions-Workflow.",
            "trigger_type": "event",
            "steps": steps,
            "confidence_score": 0.88,
            "tuv_status": tuv_status,
            "tuv_report": tuv_report,
            "provenance": {
                "synthesized_by": "nemofold:heuristic-detector:v1",
                "session_context": context_name,
                "observed_event_count": len(events),
                "pattern_type": "research_extraction_pipeline"
            }
        }

    def _build_multi_agent_review_chain(self, events: list[dict[str, Any]], context_name: str) -> dict[str, Any]:
        slug = f"nemofold-interrater-review-{int(datetime.now(timezone.utc).timestamp())}"
        steps = [
            {
                "step_index": 1,
                "name": "Erster Modell-Check (Primär-Agent)",
                "agent": "bach",
                "tool": "cc_analyze_code",
                "category": "analyze_diagnose",
                "inputs": {"target": "diff_or_code"},
                "expected_output": "rater1_evaluation",
                "reversible": True,
                "action_journal_support": True,
                "description": "Primaer-Evaluation von Syntax, Logik und Vorgaben."
            },
            {
                "step_index": 2,
                "name": "Inter-Rater Zweitprüfung (Lokal-Modell)",
                "agent": "Ollama Local",
                "tool": "test_run",
                "category": "verify_test",
                "inputs": {"evaluation_rubric": "standard", "code": "$step1.inputs"},
                "expected_output": "rater2_evaluation",
                "reversible": True,
                "action_journal_support": True,
                "description": "Unabhaengige Gegenpruefung durch lokales Offline-Modell."
            },
            {
                "step_index": 3,
                "name": "Konsens-Berechnung & Freigabe-Entscheidung",
                "agent": "Sentinel",
                "tool": "lock_status",
                "category": "security_gate",
                "inputs": {"r1": "$step1.output", "r2": "$step2.output"},
                "expected_output": "consensus_verdict",
                "reversible": True,
                "action_journal_support": False,
                "description": "Berechnung der Inter-Rater-Reliabilitaet (Fleiss Kappa / Cohen Kappa)."
            }
        ]

        tuv_status, tuv_report = self._evaluate_workflow_tuv(steps)

        return {
            "name": slug,
            "title": f"Inter-Rater 4-Augen Review ({context_name})",
            "description": "NemoFold Multi-Model Review- und Konsens-Kette zur Qualitaetssicherung.",
            "trigger_type": "manual",
            "steps": steps,
            "confidence_score": 0.95,
            "tuv_status": tuv_status,
            "tuv_report": tuv_report,
            "provenance": {
                "synthesized_by": "nemofold:heuristic-detector:v1",
                "session_context": context_name,
                "observed_event_count": len(events),
                "pattern_type": "interrater_review_pipeline"
            }
        }

    def _build_generic_step_chain(self, events: list[dict[str, Any]], context_name: str) -> dict[str, Any]:
        slug = f"nemofold-generic-chain-{int(datetime.now(timezone.utc).timestamp())}"
        steps = []
        for idx, ev in enumerate(events[:6], 1):
            steps.append({
                "step_index": idx,
                "name": f"Schritt {idx}: {ev['tool'].replace('_', ' ').title()}",
                "agent": ev.get("agent", "bach"),
                "tool": ev["tool"],
                "category": ev.get("category", "generic_step"),
                "inputs": ev.get("args_summary", {}),
                "expected_output": f"step{idx}_result",
                "reversible": ev.get("reversibility") != "irreversible",
                "action_journal_support": ev.get("reversibility") == "two_phase_journal",
                "description": f"Automatisch synthetisierter Schritt aus {ev['tool']}."
            })

        tuv_status, tuv_report = self._evaluate_workflow_tuv(steps)

        return {
            "name": slug,
            "title": f"Sequenzielle Kette ({context_name})",
            "description": f"Generische {len(steps)}-Schritte-Pipeline abgeleitet aus Session-Werkzeugfolgen.",
            "trigger_type": "manual",
            "steps": steps,
            "confidence_score": 0.75,
            "tuv_status": tuv_status,
            "tuv_report": tuv_report,
            "provenance": {
                "synthesized_by": "nemofold:heuristic-detector:v1",
                "session_context": context_name,
                "observed_event_count": len(events),
                "pattern_type": "generic_sequential_pipeline"
            }
        }

    # ─────────────────────────────────────────────────────────────
    # 3. WORKFLOW-TÜV & ROLLBACK-SCHUTZ
    # ─────────────────────────────────────────────────────────────

    def _evaluate_workflow_tuv(self, steps: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
        """
        Prüft ausschließlich deklarierte Kettenmetadaten; keine Ausführungsabnahme:
        - Keine ungeschuetzten destruktiven Shell-Commands.
        - Schreibende Schritte muessen Two-Phase Action-Journal Rollback unterstuetzen.
        - Release-Schritte duerfen nicht ungeprueft direkt auf main pushen.
        """
        issues = []
        has_rollback_support = True
        has_tests = False

        for step in steps:
            tool = step.get("tool", "")
            cat = step.get("category", "")

            # Test-Phase vorhanden?
            if cat == "verify_test" or "test" in tool:
                has_tests = True

            # Rollback check fuer schreibende Schritte
            if cat == "edit_transform" and not step.get("action_journal_support", False):
                issues.append(f"Schritt '{step['name']}' modifiziert Code ohne 2-Phase Action Journal.")
                has_rollback_support = False

            # Direct push guard
            if "push" in tool and "pr" not in tool and "main" in str(step.get("inputs", {})):
                issues.append(f"Schritt '{step['name']}' versucht potenziellen Direct-Main-Push ohne PR-Gatter.")

        if not has_tests:
            issues.append("Kette besitzt keinen expliziten Test- oder Verifikationsschritt.")

        if not issues:
            status = "certified"
            rating = "A+"
        elif len(issues) == 1 and has_rollback_support:
            status = "needs_review"
            rating = "B"
        else:
            status = "needs_review" if has_rollback_support else "rejected"
            rating = "C" if has_rollback_support else "F"

        report = {
            "rating": rating,
            "issues": issues,
            "has_rollback_support": has_rollback_support,
            "has_test_gate": has_tests,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "tuv_inspector": "nemofold.workflow-tuv.v1",
            "analysis_kind": "static_metadata",
            "empirically_validated": False
        }
        return status, report

    # ─────────────────────────────────────────────────────────────
    # 4. KANDIDATEN-MANAGEMENT & DATENBANK-PERSISTENZ
    # ─────────────────────────────────────────────────────────────

    def store_candidate(self, chain_data: dict[str, Any]) -> int:
        """Store a versioned draft; re-synthesis invalidates a previous review."""
        conn = self._get_conn()
        try:
            now = datetime.now(timezone.utc).isoformat()
            confidence = chain_data.get("confidence_score", 0.8)
            if (type(confidence) not in {int, float} or not math.isfinite(confidence)
                    or not 0 <= confidence <= 1):
                raise ValueError("Konfidenz muss eine endliche Zahl zwischen 0 und 1 sein")
            item = {
                "chain_name": chain_data["name"],
                "title": chain_data.get("title", chain_data["name"]),
                "description": chain_data.get("description", ""),
                "trigger_type": chain_data.get("trigger_type", "manual"),
                "steps_json": json.dumps(chain_data.get("steps", []), ensure_ascii=False),
                "confidence_score": float(confidence),
                "tuv_status": chain_data.get("tuv_status", "needs_review"),
                "tuv_report_json": json.dumps(chain_data.get("tuv_report", {}), ensure_ascii=False),
                "provenance_json": json.dumps(chain_data.get("provenance", {}), ensure_ascii=False),
            }
            for field in ("chain_name", "title", "description", "trigger_type", "tuv_status"):
                if not isinstance(item[field], str):
                    raise ValueError(f"{field} muss Text sein")
            if not item["chain_name"].strip() or "\x00" in item["chain_name"]:
                raise ValueError("Kandidatenname erforderlich")
            proposal, digest = proposal_binding("nemofold", item)
            conn.execute("BEGIN IMMEDIATE")
            prior = conn.execute(
                "SELECT * FROM nemofold_workflow_candidates WHERE chain_name=?", (item["chain_name"],)
            ).fetchone()
            if prior is not None:
                if prior["proposal_json"] == proposal and prior["candidate_digest"] == digest:
                    conn.commit()
                    return prior["id"]
                if prior["status"] == "approved" or prior["promoted_to_chain_id"] is not None:
                    raise LearningConflict("Historisch veröffentlichter Kandidat bleibt unverändert; neuen Namen verwenden.")
                revision = prior["candidate_revision"] + 1
                conn.execute("""UPDATE nemofold_workflow_candidates SET
                    title=?,description=?,trigger_type=?,steps_json=?,confidence_score=?,
                    tuv_status=?,tuv_report_json=?,provenance_json=?,updated_at=?,
                    candidate_revision=?,candidate_digest=?,proposal_json=?,status='pending',
                    reviewed_by=NULL,review_notes=NULL WHERE id=?""", (
                    *(item[key] for key in ("title", "description", "trigger_type", "steps_json",
                        "confidence_score", "tuv_status", "tuv_report_json", "provenance_json")),
                    now, revision, digest, proposal, prior["id"],
                ))
                candidate_id = prior["id"]
            else:
                keys = tuple(item)
                cur = conn.execute(
                    f"INSERT INTO nemofold_workflow_candidates ({','.join(keys)},created_at,updated_at,"
                    f"candidate_revision,candidate_digest,proposal_json,status) VALUES ({','.join('?' for _ in keys)},?,?,?,?,?,'pending')",
                    (*item.values(), now, now, 1, digest, proposal),
                )
                candidate_id = cur.lastrowid
            conn.commit()
            return candidate_id
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def list_candidates(self, status: str | None = None) -> list[dict[str, Any]]:
        """Listet Workflow-Kandidaten auf (optional gefiltert nach status)."""
        conn = self._get_conn()
        try:
            if status and status != "all":
                rows = conn.execute("""
                    SELECT * FROM nemofold_workflow_candidates
                    WHERE status = ?
                    ORDER BY id DESC
                """, (status,)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM nemofold_workflow_candidates
                    ORDER BY id DESC
                """).fetchall()

            candidates = []
            for r in rows:
                c = project_candidate("nemofold", r)
                try:
                    c["steps"] = json.loads(c.get("steps_json") or "[]")
                except (json.JSONDecodeError, ValueError):
                    c["steps"] = []
                try:
                    c["tuv_report"] = json.loads(c.get("tuv_report_json") or "{}")
                except (json.JSONDecodeError, ValueError):
                    c["tuv_report"] = {}
                try:
                    c["provenance"] = json.loads(c.get("provenance_json") or "{}")
                except (json.JSONDecodeError, ValueError):
                    c["provenance"] = {}
                candidates.append(c)
            return candidates
        finally:
            conn.close()

    def get_candidate(self, candidate_id: int) -> dict[str, Any] | None:
        """Liefert die Details eines einzelnen Workflow-Kandidaten."""
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM nemofold_workflow_candidates WHERE id = ?", (candidate_id,)).fetchone()
            if not row:
                return None
            c = project_candidate("nemofold", row)
            try:
                c["steps"] = json.loads(c.get("steps_json") or "[]")
            except (json.JSONDecodeError, ValueError):
                c["steps"] = []
            try:
                c["tuv_report"] = json.loads(c.get("tuv_report_json") or "{}")
            except (json.JSONDecodeError, ValueError):
                c["tuv_report"] = {}
            try:
                c["provenance"] = json.loads(c.get("provenance_json") or "{}")
            except (json.JSONDecodeError, ValueError):
                c["provenance"] = {}
            return c
        finally:
            conn.close()

    def approve_candidate(self, candidate_id: int, operator: str = "operator", notes: str = "") -> dict[str, Any]:
        """Legacy direct activation is unavailable; review and publication differ."""
        conn = self._get_conn()
        try:
            prohibit_legacy_promotion(conn, "nemofold", candidate_id)
        finally:
            conn.close()

    def review_candidate(self, candidate_id: int, *, expected_revision=None, expected_digest=None,
                         request_id=None, actor="", notes="") -> dict[str, Any]:
        conn = self._get_conn()
        try:
            return record_review(conn, "nemofold", candidate_id,
                expected_revision=expected_revision, expected_digest=expected_digest,
                request_id=request_id, actor=actor, decision="reviewed", notes=notes)
        finally:
            conn.close()

    def reject_candidate(self, candidate_id: int, reason: str = "", operator: str = "operator", *,
                         expected_revision=None, expected_digest=None, request_id=None, actor=None) -> dict[str, Any]:
        conn = self._get_conn()
        try:
            receipt = record_review(conn, "nemofold", candidate_id,
                expected_revision=expected_revision, expected_digest=expected_digest,
                request_id=request_id, actor=actor if actor is not None else operator,
                decision="rejected", notes=reason)
            return {**receipt, "success": True, "reason": reason}
        finally:
            conn.close()

    # ─────────────────────────────────────────────────────────────
    # 5. HIGH-LEVEL SYNTHESIS PIPELINE
    # ─────────────────────────────────────────────────────────────

    def run_synthesis(
        self,
        source_type: str = "transcript",
        source_ref: str | None = None,
        raw_text: str | None = None
    ) -> dict[str, Any]:
        """
        Fuehrt einen vollstaendigen Syntheselauf durch:
        1. Holt Events aus Transcript, Snapshot oder Sessions
        2. Filtert und normalisiert die Werkzeugfolge
        3. Erkennt wiederkehrende Muster
        4. Validiert mit dem Workflow-TÜV
        5. Speichert gefundene Ketten in der Kandidaten-Queue
        """
        now = datetime.now(timezone.utc).isoformat()
        events: list[dict[str, Any]] = []

        if raw_text:
            events = self.parse_events_from_transcript(raw_text)
        elif source_type == "session_snapshot" and source_ref:
            conn = self._get_conn()
            try:
                row = conn.execute("SELECT snapshot_data, working_memory, notes FROM session_snapshots WHERE session_id = ?", (source_ref,)).fetchone()
                if row:
                    combined = f"{row[0] or ''}\n{row[1] or ''}\n{row[2] or ''}"
                    events = self.parse_events_from_transcript(combined)
            finally:
                conn.close()
        elif source_type == "database_sessions":
            conn = self._get_conn()
            try:
                # Sammle Werkzeugaufrufe aus letzten Snapshots
                rows = conn.execute("SELECT snapshot_data FROM session_snapshots ORDER BY id DESC LIMIT 5").fetchall()
                combined = "\n".join([r[0] for r in rows if r[0]])
                events = self.parse_events_from_transcript(combined)
            finally:
                conn.close()

        # Heuristik & Synthese
        context_name = source_ref or "Ad-hoc Session"
        chains = self.synthesize_chains_from_events(events, context_name=context_name)

        candidate_ids = []
        for ch in chains:
            c_id = self.store_candidate(ch)
            candidate_ids.append(c_id)

        # Logge Run
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT INTO nemofold_synthesis_runs (
                    source_type, source_ref, patterns_detected, chains_synthesized, details_json
                ) VALUES (?, ?, ?, ?, ?)
            """, (
                source_type,
                source_ref,
                len(events),
                len(chains),
                json.dumps({"candidate_ids": candidate_ids, "timestamp": now})
            ))
            conn.commit()
        finally:
            conn.close()

        return {
            "success": True,
            "source_type": source_type,
            "source_ref": source_ref,
            "observed_events": len(events),
            "chains_synthesized": len(chains),
            "candidate_ids": candidate_ids,
            "chains": chains,
            "executed_at": now
        }

    # ─────────────────────────────────────────────────────────────
    # 6. STATISTIKEN & LIVE-METRIKEN
    # ─────────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Liefert Live-Kennzahlen fuer das Dashboard und den Ocean-Schaltplan."""
        conn = self._get_conn()
        try:
            total_cand = conn.execute("SELECT COUNT(*) FROM nemofold_workflow_candidates").fetchone()[0]
            pending_cand = conn.execute("SELECT COUNT(*) FROM nemofold_workflow_candidates WHERE status = 'pending'").fetchone()[0]
            approved_cand = conn.execute("SELECT COUNT(*) FROM nemofold_workflow_candidates WHERE status = 'approved'").fetchone()[0]
            rejected_cand = conn.execute("SELECT COUNT(*) FROM nemofold_workflow_candidates WHERE status = 'rejected'").fetchone()[0]
            certified_tuv = conn.execute("SELECT COUNT(*) FROM nemofold_workflow_candidates WHERE tuv_status = 'certified'").fetchone()[0]

            total_runs = conn.execute("SELECT COUNT(*) FROM nemofold_synthesis_runs").fetchone()[0]

            avg_conf = conn.execute("SELECT AVG(confidence_score) FROM nemofold_workflow_candidates").fetchone()[0] or 0.0

            # Letzte 5 Kandidaten
            recent_rows = conn.execute("""
                SELECT id, chain_name, title, status, tuv_status, confidence_score, created_at
                FROM nemofold_workflow_candidates
                ORDER BY id DESC LIMIT 5
            """).fetchall()
            recent_candidates = [dict(r) for r in recent_rows]

            return {
                "subsystem": "Nemofold",
                "status": "active",
                "total_runs": total_runs,
                "total_candidates": total_cand,
                "pending_candidates": pending_cand,
                "approved_candidates": approved_cand,
                "rejected_candidates": rejected_cand,
                "tuv_certified_count": certified_tuv,
                "tuv_analysis_kind": "static_metadata",
                "native_promotion_available": False,
                "average_confidence": round(avg_conf, 2),
                "recent_candidates": recent_candidates
            }
        finally:
            conn.close()
