#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sub-Query System - Document-specific detail research
====================================================

Allows adding focused research questions to specific documents
that will be analyzed before the main report generation.
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Callable


class SubQueryStatus(Enum):
    """Status of a sub-query."""
    PENDING = "pending"          # Not yet executed
    RUNNING = "running"          # Currently being processed
    COMPLETED = "completed"      # Analysis complete
    ERROR = "error"              # Error during analysis


class SubQueryType(Enum):
    """Type of sub-query analysis."""
    SUMMARY = "summary"          # Summarize the document
    EXTRACT = "extract"          # Extract specific information
    ANALYZE = "analyze"          # Detailed analysis
    COMPARE = "compare"          # Compare with other documents
    QUESTION = "question"        # Answer specific question
    CUSTOM = "custom"            # Custom prompt


@dataclass
class SubQuery:
    """
    A sub-query attached to a document for detailed research.

    These queries are executed before the main report generation
    and their results are incorporated into the main analysis.
    """
    id: str
    document_id: str
    query_type: SubQueryType
    query_text: str
    status: SubQueryStatus = SubQueryStatus.PENDING

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Results
    result_text: str = ""
    result_tokens: int = 0
    error_message: str = ""

    # Settings
    priority: int = 0  # Higher = process first
    include_in_report: bool = True  # Include results in main report
    max_tokens: int = 2000

    @classmethod
    def create(cls, document_id: str, query_type: SubQueryType, query_text: str,
               priority: int = 0) -> "SubQuery":
        """Create a new sub-query."""
        return cls(
            id=str(uuid.uuid4()),
            document_id=document_id,
            query_type=query_type,
            query_text=query_text,
            priority=priority
        )

    @classmethod
    def summary(cls, document_id: str, focus: str = "") -> "SubQuery":
        """Create a summary sub-query."""
        text = "Erstelle eine strukturierte Zusammenfassung dieses Dokuments."
        if focus:
            text += f" Fokus auf: {focus}"
        return cls.create(document_id, SubQueryType.SUMMARY, text)

    @classmethod
    def extract_info(cls, document_id: str, what: str) -> "SubQuery":
        """Create an extraction sub-query."""
        return cls.create(
            document_id,
            SubQueryType.EXTRACT,
            f"Extrahiere die folgenden Informationen: {what}"
        )

    @classmethod
    def analyze(cls, document_id: str, aspect: str) -> "SubQuery":
        """Create an analysis sub-query."""
        return cls.create(
            document_id,
            SubQueryType.ANALYZE,
            f"Analysiere das Dokument hinsichtlich: {aspect}"
        )

    @classmethod
    def question(cls, document_id: str, question: str) -> "SubQuery":
        """Create a question sub-query."""
        return cls.create(
            document_id,
            SubQueryType.QUESTION,
            question
        )

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "document_id": self.document_id,
            "query_type": self.query_type.value,
            "query_text": self.query_text,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result_text": self.result_text,
            "result_tokens": self.result_tokens,
            "error_message": self.error_message,
            "priority": self.priority,
            "include_in_report": self.include_in_report,
            "max_tokens": self.max_tokens
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SubQuery":
        """Deserialize from dictionary."""
        return cls(
            id=data["id"],
            document_id=data["document_id"],
            query_type=SubQueryType(data["query_type"]),
            query_text=data["query_text"],
            status=SubQueryStatus(data.get("status", "pending")),
            created_at=datetime.fromisoformat(data["created_at"]),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            result_text=data.get("result_text", ""),
            result_tokens=data.get("result_tokens", 0),
            error_message=data.get("error_message", ""),
            priority=data.get("priority", 0),
            include_in_report=data.get("include_in_report", True),
            max_tokens=data.get("max_tokens", 2000)
        )

    def build_prompt(self, document_text: str) -> str:
        """Build the LLM prompt for this sub-query."""
        prompt_templates = {
            SubQueryType.SUMMARY: """Erstelle eine strukturierte Zusammenfassung des folgenden Dokuments.

DOKUMENT:
{document}

AUFGABE:
{query}

Antworte strukturiert mit Abschnitten und Stichpunkten.""",

            SubQueryType.EXTRACT: """Analysiere das folgende Dokument und extrahiere die gewünschten Informationen.

DOKUMENT:
{document}

EXTRAKTIONSAUFGABE:
{query}

Liste die gefundenen Informationen klar auf.""",

            SubQueryType.ANALYZE: """Führe eine detaillierte Analyse des folgenden Dokuments durch.

DOKUMENT:
{document}

ANALYSEAUFTRAG:
{query}

Strukturiere deine Analyse mit klaren Abschnitten.""",

            SubQueryType.COMPARE: """Vergleiche und analysiere das folgende Dokument.

DOKUMENT:
{document}

VERGLEICHSAUFGABE:
{query}

Hebe Gemeinsamkeiten und Unterschiede hervor.""",

            SubQueryType.QUESTION: """Beantworte die folgende Frage basierend auf dem Dokument.

DOKUMENT:
{document}

FRAGE:
{query}

Antworte praezise und beziehe dich auf konkrete Stellen im Dokument.""",

            SubQueryType.CUSTOM: """Führe die folgende Aufgabe am Dokument aus.

DOKUMENT:
{document}

AUFGABE:
{query}"""
        }

        template = prompt_templates.get(self.query_type, prompt_templates[SubQueryType.CUSTOM])

        # Truncate document if too long
        max_doc_chars = 50000
        if len(document_text) > max_doc_chars:
            document_text = document_text[:max_doc_chars] + "\n\n[... Dokument gekuerzt ...]"

        return template.format(document=document_text, query=self.query_text)


class SubQueryManager:
    """
    Manages sub-queries across all documents in a project.

    Responsibilities:
    - Create and delete sub-queries
    - Execute sub-queries with LLM
    - Track status and results
    - Aggregate results for report generation
    """

    def __init__(self):
        self._queries: Dict[str, SubQuery] = {}
        self._on_change_callbacks: List[Callable] = []

    @property
    def queries(self) -> List[SubQuery]:
        """Get all sub-queries."""
        return list(self._queries.values())

    @property
    def pending_queries(self) -> List[SubQuery]:
        """Get pending sub-queries, sorted by priority."""
        pending = [q for q in self._queries.values() if q.status == SubQueryStatus.PENDING]
        return sorted(pending, key=lambda q: q.priority, reverse=True)

    @property
    def completed_queries(self) -> List[SubQuery]:
        """Get completed sub-queries."""
        return [q for q in self._queries.values() if q.status == SubQueryStatus.COMPLETED]

    def get_query(self, query_id: str) -> Optional[SubQuery]:
        """Get a sub-query by ID."""
        return self._queries.get(query_id)

    def get_queries_for_document(self, document_id: str) -> List[SubQuery]:
        """Get all sub-queries for a specific document."""
        return [q for q in self._queries.values() if q.document_id == document_id]

    def add_query(self, query: SubQuery) -> None:
        """Add a sub-query."""
        self._queries[query.id] = query
        self._notify_change("add", query)

    def create_query(self, document_id: str, query_type: SubQueryType, query_text: str,
                    priority: int = 0) -> SubQuery:
        """Create and add a new sub-query."""
        query = SubQuery.create(document_id, query_type, query_text, priority)
        self.add_query(query)
        return query

    def remove_query(self, query_id: str) -> bool:
        """Remove a sub-query."""
        if query_id in self._queries:
            query = self._queries.pop(query_id)
            self._notify_change("remove", query)
            return True
        return False

    def remove_queries_for_document(self, document_id: str) -> int:
        """Remove all sub-queries for a document."""
        to_remove = [q.id for q in self._queries.values() if q.document_id == document_id]
        for qid in to_remove:
            self.remove_query(qid)
        return len(to_remove)

    def set_result(self, query_id: str, result: str, tokens: int = 0) -> None:
        """Set the result for a sub-query."""
        query = self._queries.get(query_id)
        if query:
            query.result_text = result
            query.result_tokens = tokens
            query.status = SubQueryStatus.COMPLETED
            query.completed_at = datetime.now()
            self._notify_change("update", query)

    def set_error(self, query_id: str, error: str) -> None:
        """Set an error for a sub-query."""
        query = self._queries.get(query_id)
        if query:
            query.error_message = error
            query.status = SubQueryStatus.ERROR
            query.completed_at = datetime.now()
            self._notify_change("update", query)

    def set_running(self, query_id: str) -> None:
        """Mark a sub-query as running."""
        query = self._queries.get(query_id)
        if query:
            query.status = SubQueryStatus.RUNNING
            query.started_at = datetime.now()
            self._notify_change("update", query)

    def reset_query(self, query_id: str) -> None:
        """Reset a sub-query to pending state."""
        query = self._queries.get(query_id)
        if query:
            query.status = SubQueryStatus.PENDING
            query.started_at = None
            query.completed_at = None
            query.result_text = ""
            query.result_tokens = 0
            query.error_message = ""
            self._notify_change("update", query)

    def get_results_for_report(self) -> Dict[str, List[dict]]:
        """
        Get all completed sub-query results formatted for report generation.

        Returns:
            Dict mapping document_id to list of result dicts
        """
        results: Dict[str, List[dict]] = {}

        for query in self._queries.values():
            if query.status != SubQueryStatus.COMPLETED or not query.include_in_report:
                continue

            if query.document_id not in results:
                results[query.document_id] = []

            results[query.document_id].append({
                "type": query.query_type.value,
                "query": query.query_text,
                "result": query.result_text
            })

        return results

    def get_statistics(self) -> dict:
        """Get sub-query statistics."""
        queries = self.queries
        return {
            "total": len(queries),
            "pending": len([q for q in queries if q.status == SubQueryStatus.PENDING]),
            "running": len([q for q in queries if q.status == SubQueryStatus.RUNNING]),
            "completed": len([q for q in queries if q.status == SubQueryStatus.COMPLETED]),
            "errors": len([q for q in queries if q.status == SubQueryStatus.ERROR]),
            "total_result_tokens": sum(q.result_tokens for q in queries),
            "by_type": {
                t.value: len([q for q in queries if q.query_type == t])
                for t in SubQueryType
            }
        }

    def on_change(self, callback: Callable) -> None:
        """Register a callback for changes."""
        self._on_change_callbacks.append(callback)

    def _notify_change(self, action: str, query: Optional[SubQuery]) -> None:
        """Notify listeners of changes."""
        for callback in self._on_change_callbacks:
            try:
                callback(action, query)
            except Exception:
                pass

    def save_state(self, filepath: Path) -> None:
        """Save sub-queries to file."""
        state = {
            "queries": [q.to_dict() for q in self._queries.values()],
            "saved_at": datetime.now().isoformat()
        }
        filepath.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def load_state(self, filepath: Path) -> bool:
        """Load sub-queries from file."""
        if not filepath.exists():
            return False

        try:
            state = json.loads(filepath.read_text(encoding="utf-8"))
            self._queries.clear()

            for query_data in state.get("queries", []):
                query = SubQuery.from_dict(query_data)
                self._queries[query.id] = query

            self._notify_change("load", None)
            return True

        except Exception:
            return False

    def clear(self) -> None:
        """Remove all sub-queries."""
        self._queries.clear()
        self._notify_change("clear", None)


# Pre-defined sub-query templates
class SubQueryTemplates:
    """Common sub-query templates."""

    @staticmethod
    def key_points(document_id: str) -> SubQuery:
        """Extract key points from a document."""
        return SubQuery.create(
            document_id,
            SubQueryType.EXTRACT,
            "Extrahiere die wichtigsten Kernaussagen und Schlussfolgerungen."
        )

    @staticmethod
    def timeline(document_id: str) -> SubQuery:
        """Extract timeline/dates from a document."""
        return SubQuery.create(
            document_id,
            SubQueryType.EXTRACT,
            "Erstelle eine chronologische Liste aller erwahnten Daten und Ereignisse."
        )

    @staticmethod
    def entities(document_id: str) -> SubQuery:
        """Extract named entities."""
        return SubQuery.create(
            document_id,
            SubQueryType.EXTRACT,
            "Liste alle genannten Personen, Organisationen und Orte auf."
        )

    @staticmethod
    def methodology(document_id: str) -> SubQuery:
        """Analyze methodology."""
        return SubQuery.create(
            document_id,
            SubQueryType.ANALYZE,
            "Analysiere die verwendete Methodik und bewerte ihre Staerken und Schwaechen."
        )

    @staticmethod
    def data_quality(document_id: str) -> SubQuery:
        """Assess data quality."""
        return SubQuery.create(
            document_id,
            SubQueryType.ANALYZE,
            "Bewerte die Qualität und Vollständigkeit der im Dokument enthaltenen Daten."
        )

    @staticmethod
    def contradictions(document_id: str) -> SubQuery:
        """Find contradictions."""
        return SubQuery.create(
            document_id,
            SubQueryType.ANALYZE,
            "Identifiziere mögliche Widersprüche oder inkonsistente Aussagen."
        )
