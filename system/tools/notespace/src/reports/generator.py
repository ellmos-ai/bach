#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Report Generator - Orchestrates the report generation pipeline
==============================================================

Manages the full workflow from documents to final report.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Iterator, Callable

from ..core.document_manager import DocumentManager, DocumentItem, DocumentStatus
from ..core.sub_query import SubQueryManager, SubQuery, SubQueryStatus
from ..core.text_extractor import TextExtractor
from ..llm.client import LLMClient


@dataclass
class GenerationResult:
    """Result of report generation."""
    success: bool
    content: str = ""
    word_count: int = 0
    generation_time_seconds: float = 0.0
    documents_used: int = 0
    subqueries_used: int = 0
    error: str = ""


@dataclass
class GenerationProgress:
    """Progress information for report generation."""
    current_step: str
    step_number: int
    total_steps: int
    percentage: float
    message: str = ""


class ReportGenerator:
    """
    Orchestrates the complete report generation pipeline.

    Pipeline:
    1. Extract text from documents
    2. Run sub-query analyses
    3. Build context from documents and analyses
    4. Generate report with LLM
    5. Post-process and format
    """

    def __init__(
        self,
        document_manager: DocumentManager,
        subquery_manager: SubQueryManager,
        llm_client: LLMClient,
        text_extractor: Optional[TextExtractor] = None
    ):
        """
        Initialize the generator.

        Args:
            document_manager: Document manager with loaded documents
            subquery_manager: Sub-query manager with queries
            llm_client: LLM client for generation
            text_extractor: Text extractor (created if not provided)
        """
        self.documents = document_manager
        self.subqueries = subquery_manager
        self.llm = llm_client
        self.extractor = text_extractor or TextExtractor()

        self._progress_callback: Optional[Callable[[GenerationProgress], None]] = None
        self._cancel_requested = False

    def set_progress_callback(self, callback: Callable[[GenerationProgress], None]):
        """Set a callback for progress updates."""
        self._progress_callback = callback

    def cancel(self):
        """Request cancellation of generation."""
        self._cancel_requested = True

    def _report_progress(self, step: str, step_num: int, total: int, message: str = ""):
        """Report progress to callback."""
        if self._progress_callback:
            progress = GenerationProgress(
                current_step=step,
                step_number=step_num,
                total_steps=total,
                percentage=(step_num / total) * 100,
                message=message
            )
            self._progress_callback(progress)

    def generate(
        self,
        main_question: str,
        report_type: str = "analysis",
        include_subqueries: bool = True,
        max_context_chars: int = 80000,
        stream: bool = False
    ) -> GenerationResult:
        """
        Generate a complete report.

        Args:
            main_question: The main research question
            report_type: Type of report (analysis, summary, research, comparison)
            include_subqueries: Include sub-query results
            max_context_chars: Maximum context size
            stream: Stream the response (yields chunks)

        Returns:
            GenerationResult with the report content
        """
        self._cancel_requested = False
        start_time = datetime.now()
        total_steps = 5

        try:
            # Step 1: Extract text
            self._report_progress("Textextraktion", 1, total_steps, "Extrahiere Dokumententext...")
            self._extract_document_text()

            if self._cancel_requested:
                return GenerationResult(False, error="Abgebrochen")

            # Step 2: Run sub-queries
            if include_subqueries:
                self._report_progress("Detailanalysen", 2, total_steps, "Führe Einzelanalysen durch...")
                self._run_subqueries()

            if self._cancel_requested:
                return GenerationResult(False, error="Abgebrochen")

            # Step 3: Build context
            self._report_progress("Kontext aufbauen", 3, total_steps, "Baue Analysekontext auf...")
            context = self._build_context(max_context_chars, include_subqueries)

            if self._cancel_requested:
                return GenerationResult(False, error="Abgebrochen")

            # Step 4: Build prompt
            self._report_progress("Prompt erstellen", 4, total_steps, "Erstelle Berichts-Prompt...")
            prompt = self._build_prompt(main_question, report_type, context)

            # Step 5: Generate report
            self._report_progress("Generierung", 5, total_steps, "Generiere Bericht mit LLM...")

            if stream:
                content = ""
                for chunk in self.llm.stream_chat(prompt, ""):
                    if self._cancel_requested:
                        return GenerationResult(False, content, error="Abgebrochen")
                    content += chunk
                    # Progress callback could yield chunks here
            else:
                content = self.llm.chat(prompt, "")

            # Calculate stats
            generation_time = (datetime.now() - start_time).total_seconds()
            docs_used = len(self.documents.selected_documents)
            queries_used = len([q for q in self.subqueries.queries if q.status == SubQueryStatus.COMPLETED])

            return GenerationResult(
                success=True,
                content=content,
                word_count=len(content.split()),
                generation_time_seconds=generation_time,
                documents_used=docs_used,
                subqueries_used=queries_used
            )

        except Exception as e:
            return GenerationResult(False, error=str(e))

    def generate_stream(
        self,
        main_question: str,
        report_type: str = "analysis",
        include_subqueries: bool = True,
        max_context_chars: int = 80000
    ) -> Iterator[str]:
        """
        Generate report with streaming response.

        Yields:
            Text chunks as they are generated
        """
        self._cancel_requested = False

        # Extract and analyze first
        self._extract_document_text()
        if include_subqueries:
            self._run_subqueries()

        # Build context and prompt
        context = self._build_context(max_context_chars, include_subqueries)
        prompt = self._build_prompt(main_question, report_type, context)

        # Stream the response
        for chunk in self.llm.stream_chat(prompt, ""):
            if self._cancel_requested:
                break
            yield chunk

    def _extract_document_text(self):
        """Extract text from all selected documents."""
        docs = self.documents.selected_documents

        for doc in docs:
            if doc.status == DocumentStatus.READY and doc.extracted_text:
                continue  # Already extracted

            self.documents.set_status(doc.id, DocumentStatus.EXTRACTING)

            result = self.extractor.extract(doc.path)
            if result.success:
                self.documents.update_content(doc.id, result.text)
            else:
                self.documents.set_status(doc.id, DocumentStatus.ERROR, result.error)

    def _run_subqueries(self):
        """Run all pending sub-queries."""
        queries = self.subqueries.pending_queries

        for query in queries:
            if self._cancel_requested:
                break

            doc = self.documents.get_document(query.document_id)
            if not doc or not doc.extracted_text:
                self.subqueries.set_error(query.id, "Dokument nicht verfügbar")
                continue

            self.subqueries.set_running(query.id)

            try:
                prompt = query.build_prompt(doc.extracted_text)
                response = self.llm.chat(prompt, "")
                self.subqueries.set_result(query.id, response)
            except Exception as e:
                self.subqueries.set_error(query.id, str(e))

    def _build_context(self, max_chars: int, include_subqueries: bool) -> str:
        """Build the document context string."""
        parts = []
        current_size = 0

        # Add document contents
        for doc in self.documents.selected_documents:
            if not doc.extracted_text:
                continue

            doc_section = f"=== DOKUMENT: {doc.name} ===\n{doc.extracted_text}\n"

            if current_size + len(doc_section) > max_chars:
                # Truncate this document
                remaining = max_chars - current_size - 100
                if remaining > 500:
                    doc_section = f"=== DOKUMENT: {doc.name} ===\n{doc.extracted_text[:remaining]}\n[... gekuerzt ...]\n"
                    parts.append(doc_section)
                break

            parts.append(doc_section)
            current_size += len(doc_section)

        # Add sub-query results
        if include_subqueries:
            subquery_results = self.subqueries.get_results_for_report()
            for doc_id, results in subquery_results.items():
                doc = self.documents.get_document(doc_id)
                doc_name = doc.name if doc else doc_id

                for r in results:
                    sq_section = f"\n--- Detailanalyse: {doc_name} ({r['type']}) ---\n"
                    sq_section += f"Frage: {r['query']}\n"
                    sq_section += f"Ergebnis: {r['result']}\n"

                    if current_size + len(sq_section) > max_chars:
                        break

                    parts.append(sq_section)
                    current_size += len(sq_section)

        return "\n".join(parts)

    def _build_prompt(self, main_question: str, report_type: str, context: str) -> str:
        """Build the LLM prompt for report generation."""
        templates = {
            "analysis": self._analysis_template,
            "summary": self._summary_template,
            "research": self._research_template,
            "comparison": self._comparison_template
        }

        template_func = templates.get(report_type, self._analysis_template)
        return template_func(main_question, context)

    def _analysis_template(self, question: str, context: str) -> str:
        """Template for analysis report."""
        return f"""Du bist ein erfahrener Analyst und erstellst professionelle Analyseberichte.

HAUPTFRAGESTELLUNG:
{question}

DOKUMENTENKONTEXT:
{context}

AUFGABE:
Erstelle einen strukturierten Analysebericht, der die Hauptfragestellung beantwortet.

Strukturiere den Bericht wie folgt:
1. **Zusammenfassung** - Kernerkenntnisse in 3-5 Sätzen
2. **Einleitung** - Kontext und Fragestellung
3. **Analyse** - Detaillierte Untersuchung der Kernthemen
4. **Erkenntnisse** - Wichtige Befunde und Muster
5. **Schlussfolgerungen** - Beantwortung der Hauptfrage
6. **Empfehlungen** - Handlungsvorschläge (falls relevant)

Verwende Markdown-Formatierung für Struktur und Lesbarkeit."""

    def _summary_template(self, question: str, context: str) -> str:
        """Template for summary report."""
        return f"""Du bist ein Experte für Textzusammenfassungen.

FOKUS:
{question}

DOKUMENTENKONTEXT:
{context}

AUFGABE:
Erstelle eine prägnante Zusammenfassung der Dokumente.

Strukturiere wie folgt:
1. **Überblick** - Was behandeln die Dokumente?
2. **Kernpunkte** - Die wichtigsten Aussagen (Stichpunkte)
3. **Fazit** - Gesamtbild in 2-3 Sätzen

Halte die Zusammenfassung kurz und fokussiert. Verwende Markdown."""

    def _research_template(self, question: str, context: str) -> str:
        """Template for research report."""
        return f"""Du bist ein wissenschaftlicher Analyst und erstellst Forschungsberichte.

FORSCHUNGSFRAGE:
{question}

QUELLENKONTEXT:
{context}

AUFGABE:
Erstelle einen wissenschaftlich strukturierten Forschungsbericht.

Strukturiere wie folgt:
1. **Abstract** - Zusammenfassung der Forschung
2. **Einleitung** - Hintergrund und Fragestellung
3. **Methodik** - Wie wurden die Quellen analysiert?
4. **Ergebnisse** - Detaillierte Befunde
5. **Diskussion** - Interpretation und Einordnung
6. **Schlussfolgerungen** - Beantwortung der Forschungsfrage
7. **Quellenverweise** - Bezüge zu den Dokumenten

Verwende akademischen Stil und Markdown-Formatierung."""

    def _comparison_template(self, question: str, context: str) -> str:
        """Template for comparison report."""
        return f"""Du bist ein Experte für vergleichende Analysen.

VERGLEICHSFRAGE:
{question}

DOKUMENTENKONTEXT:
{context}

AUFGABE:
Erstelle einen systematischen Vergleichsbericht.

Strukturiere wie folgt:
1. **Überblick** - Was wird verglichen?
2. **Gemeinsamkeiten** - Was haben die Dokumente gemeinsam?
3. **Unterschiede** - Wo unterscheiden sie sich?
4. **Vergleichsmatrix** - Tabellarische Gegenüberstellung (falls sinnvoll)
5. **Bewertung** - Stärken und Schwächen
6. **Fazit** - Gesamtbewertung

Verwende Tabellen wo sinnvoll und Markdown-Formatierung."""
