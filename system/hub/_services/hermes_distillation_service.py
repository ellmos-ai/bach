# SPDX-License-Identifier: MIT
"""
hermes_distillation_service.py - Hermes Skill-Lernen & Destillation Engine v1.0.0
=================================================================================

Lokale BACH-Heuristik: Hermes (kein nativer Hermes-Agent-Adapter)
Destillation von Verhaltensweisen, Lessons Learned und neuen Skills aus Roh-Logs
nach deterministischer Rauschreduzierung; Reduktion wird je Lauf gemessen.

Human-in-the-Loop:
Generierte Skills werden als Kandidaten (hermes_skill_candidates) angelegt und
mit Lessons als unveröffentlichte Entwürfe gespeichert. Inhaltsreview und native
Veröffentlichung sind getrennt; ein skill_versions-INSERT veröffentlicht keinen Skill.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .learning_review_service import (
    ensure_review_schema, project_candidate, proposal_binding,
    prohibit_legacy_promotion, record_review,
)

# ═══════════════════════════════════════════════════════════════
# 1. DATENSTRUKTUREN
# ═══════════════════════════════════════════════════════════════

@dataclass
class CleanedTranscriptResult:
    raw_char_count: int
    cleaned_char_count: int
    noise_reduction_percent: float
    turns_count: int
    signal_turns: list[dict[str, str]]
    consolidated_summary: str
    detected_topics: list[str] = field(default_factory=list)


@dataclass
class DistilledLesson:
    category: str
    title: str
    solution: str
    is_active: int = 0
    confidence: float = 0.9


@dataclass
class SkillCandidate:
    id: int | None = None
    name: str = ""
    category: str = "utilities"
    role: str = ""
    version: str = "1.0.0"
    description: str = ""
    trigger_phrases: list[str] = field(default_factory=list)
    frontmatter: dict[str, Any] = field(default_factory=dict)
    content: str = ""
    confidence: float = 0.85
    source_session: str | None = None
    noise_reduction_ratio: float = 0.0
    status: str = "pending"  # pending, approved, rejected
    approved_at: str | None = None
    approved_by: str | None = None
    rejection_reason: str | None = None
    created_at: str = ""


@dataclass
class DistillationResult:
    run_id: int
    session_id: str | None
    raw_char_count: int
    cleaned_char_count: int
    noise_reduction_percent: float
    lessons: list[dict[str, Any]]
    candidate: dict[str, Any] | None
    status: str = "completed"
    created_at: str = ""


# ═══════════════════════════════════════════════════════════════
# 2. RAUSCHREDUKTIONS-FILTER (NOISE REDUCTION PATTERNS)
# ═══════════════════════════════════════════════════════════════

# Füllfloskeln und rein formale Begrüßungen/Verabschiedungen
_GREETING_PATTERNS = [
    r"^(?:hallo|hi|guten\s+(?:morgen|tag|abend)|moin|servus|grüß\s+gott)[!.,\s]*",
    r"(?:vielen\s+dank|danke\s+dir|danke\s+schön|besten\s+dank)[!.,\s]*$",
    r"(?:schönen\s+(?:tag|abend|feiertag)|bis\s+bald|schöne\s+grüße)[!.,\s]*$",
    r"^(?:gerne|sehr\s+gerne|kein\s+problem|alles\s+klar|verstanden)[!.,\s]*$",
    r"(?:ich\s+hoffe,\s+das\s+hilft|lass\s+mich\s+wissen,\s+wenn\s+du\s+noch\s+etwas\s+brauchst)[!.,\s]*$"
]

_GREETING_RE = re.compile("|".join(_GREETING_PATTERNS), re.IGNORECASE)

_PURE_NOISE_RE = re.compile(
    r"^(?:hallo|hi|guten\s+(?:morgen|tag|abend)|moin|servus|grüß\s+gott|"
    r"vielen\s+dank|danke(?:\s+dir|\s+schön)?|besten\s+dank|"
    r"schönen\s+(?:tag|abend|feierabend|feiertag)|bis\s+bald|schöne\s+grüße|"
    r"gerne|sehr\s+gerne|kein\s+problem|alles\s+klar|verstanden|"
    r"mir\s+geht\s+es\s+(?:gut|ausgezeichnet|prima|super)|"
    r"wie\s+geht\s+es\s+dir(?:\s+heute)?|"
    r"ich\s+hoffe,\s+du\s+hast\s+einen\s+schönen\s+tag|"
    r"wie\s+kann\s+ich\s+dir\s+(?:heute\s+)?behilflich\s+sein|"
    r"sag\s+bescheid\s+wenn\s+du\s+noch\s+fragen\s+hast|"
    r"ich\s+hoffe,\s+das\s+hilft(?:\s+dir\s+weiter)?|[!.,\s?])+$",
    re.IGNORECASE
)

# Wiederholte Leerzeilen und Trennlinien
_WHITESPACE_RE = re.compile(r"\n{3,}")
_DIVIDER_RE = re.compile(r"^[-=_*]{4,}$", re.MULTILINE)

# Rausch-Muster in Tool- und Systemlogs (z.B. Stacktrace-Wüsten, Endlos-Status)
_PYTHON_TRACEBACK_RE = re.compile(
    r"Traceback \(most recent call last\):\r?\n(?:[ \t]+[^\r\n]*\r?\n)*(?:[^\s\r\n][^\r\n]*)?"
)
_PROGRESS_BURST_RE = re.compile(r"(?:Updating files:\s+\d+%[^\r\n]*\r?\n)+")


# ═══════════════════════════════════════════════════════════════
# 3. HERMES DISTILLATION SERVICE
# ═══════════════════════════════════════════════════════════════

class HermesDistillationService:
    """Kernservice fuer Skill-Lernen und Destillation aus Konversationen."""

    def __init__(self, db_path: str | Path | None = None):
        if db_path is not None:
            self.db_path = Path(db_path)
        else:
            # Dynamische Pfadaufloesung aus bach_paths
            try:
                from hub.bach_paths import BACH_DB
                self.db_path = Path(BACH_DB)
            except (ImportError, AttributeError):
                self.db_path = Path.home() / ".bach" / "bach.db"

    def _get_connection(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout = 30000")
        except sqlite3.Error:
            pass
        return conn

    def ensure_schema(self, conn: sqlite3.Connection | None = None) -> None:
        """Initialisiert die notwendigen Tabellen in bach.db."""
        close_needed = False
        if conn is None:
            conn = self._get_connection()
            close_needed = True

        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS hermes_skill_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT DEFAULT 'utilities',
                role TEXT,
                version TEXT DEFAULT '1.0.0',
                description TEXT,
                trigger_phrases TEXT,
                frontmatter TEXT,
                content TEXT NOT NULL,
                confidence REAL DEFAULT 0.85,
                source_session TEXT,
                noise_reduction_ratio REAL DEFAULT 0.0,
                status TEXT DEFAULT 'pending',
                approved_at TEXT,
                approved_by TEXT,
                rejection_reason TEXT,
                created_at TEXT NOT NULL
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS hermes_distillation_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                raw_char_count INTEGER,
                cleaned_char_count INTEGER,
                noise_reduction_percent REAL,
                lessons_count INTEGER,
                skills_count INTEGER,
                status TEXT,
                created_at TEXT NOT NULL
            );
        """)
        # memory_lessons und skill_versions existieren typischerweise bereits,
        # wir sichern sie hier ab
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory_lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT,
                title TEXT,
                solution TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TEXT
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS skill_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_name TEXT NOT NULL,
                version TEXT NOT NULL,
                changelog TEXT,
                author TEXT DEFAULT 'operator',
                content TEXT,
                created_at TEXT
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory_dream_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                noise_reduced INTEGER DEFAULT 0,
                items_consolidated INTEGER DEFAULT 0,
                summary TEXT,
                created_at TEXT
            );
        """)
        ensure_review_schema(conn, "hermes")
        conn.commit()
        if close_needed:
            conn.close()

    # ─────────────────────────────────────────────────────────────
    # A. RAUSCHREDUKTION (NOISE REDUCTION)
    # ─────────────────────────────────────────────────────────────

    def clean_transcript(
        self,
        messages_or_text: list[dict[str, Any]] | str,
        session_id: str | None = None
    ) -> CleanedTranscriptResult:
        """Filtert Füllwörter, Redundanz und Log-Wüsten und extrahiert Signal."""
        raw_char_count = 0
        signal_turns: list[dict[str, str]] = []
        topics: list[str] = []

        if isinstance(messages_or_text, str):
            # Rohtext als Einzeltturn normalisieren
            raw_char_count = len(messages_or_text)
            cleaned_text = self._clean_raw_text(messages_or_text)
            if cleaned_text:
                signal_turns.append({"role": "user_or_system", "content": cleaned_text})
                for t in self._detect_topics(cleaned_text):
                    if t not in topics:
                        topics.append(t)
        elif isinstance(messages_or_text, list):
            for item in messages_or_text:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role", "user"))
                content = str(item.get("content", ""))
                raw_char_count += len(content)

                # Reine Floskel-Turns vollständig als Rauschen verwerfen
                if _PURE_NOISE_RE.match(content.strip()):
                    continue

                cleaned = self._clean_turn_content(content, role)
                if cleaned and not _PURE_NOISE_RE.match(cleaned.strip()):
                    signal_turns.append({"role": role, "content": cleaned})

                    # Themen-Extraktion
                    extracted_topics = self._detect_topics(cleaned)
                    for t in extracted_topics:
                        if t not in topics:
                            topics.append(t)

        cleaned_char_count = sum(len(t["content"]) for t in signal_turns)
        if raw_char_count > 0:
            reduction = max(0.0, min(99.0, (1.0 - (cleaned_char_count / raw_char_count)) * 100.0))
        else:
            reduction = 0.0

        summary = self._synthesize_summary(signal_turns, topics)

        return CleanedTranscriptResult(
            raw_char_count=raw_char_count,
            cleaned_char_count=cleaned_char_count,
            noise_reduction_percent=round(reduction, 1),
            turns_count=len(signal_turns),
            signal_turns=signal_turns,
            consolidated_summary=summary,
            detected_topics=topics
        )

    def _clean_turn_content(self, text: str, role: str) -> str:
        """Reinigt den Text eines einzelnen Gesprächsbeitrags."""
        if not text:
            return ""

        # Systemrollen ohne Guardrail-Signal ueberspringen
        if role == "system" and len(text) > 5000 and "guard" not in text.lower() and "lock" not in text.lower():
            # Große System-Prompts auf wesentliche Leitplanken kondensieren
            lines = [l.strip() for l in text.splitlines() if any(k in l.lower() for k in ["guard", "rule", "lock", "regel", "achtung"])]
            text = "\n".join(lines[:10])

        # Git/Progress-Bursts bereinigen
        text = _PROGRESS_BURST_RE.sub("[Progress Output gekürzt]\n", text)

        # Riesige Tracebacks auf Kernzeile komprimieren
        def _compress_tb(match: re.Match) -> str:
            tb = match.group(0)
            tb_lines = tb.strip().splitlines()
            last_line = tb_lines[-1] if tb_lines else "Traceback"
            return f"[Traceback verdichtet: {last_line}]\n"

        text = _PYTHON_TRACEBACK_RE.sub(_compress_tb, text)

        # Höflichkeitsfloskeln innerhalb des Beitrags entfernen
        text = re.sub(
            r"(?:hallo[!.,\s]*|guten morgen[^!.]*!|vielen dank[^!.]*!|schönen feierabend[^!.]*!|ich hoffe das hilft[^!.]*!|sag bescheid[^!.]*!)",
            "",
            text,
            flags=re.IGNORECASE
        )

        # Floskeln an Zeilenanfang/-ende entfernen
        text = _GREETING_RE.sub("", text)
        text = _DIVIDER_RE.sub("---", text)
        text = _WHITESPACE_RE.sub("\n\n", text).strip()

        return text

    def _clean_raw_text(self, text: str) -> str:
        """Kondensiert beliebigen Freitext."""
        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if _PURE_NOISE_RE.match(stripped):
                continue
            # Floskeln am Zeilenanfang/Ende entfernen
            stripped = _GREETING_RE.sub("", stripped).strip()
            if stripped and not _PURE_NOISE_RE.match(stripped):
                lines.append(stripped)
        return "\n".join(lines)

    def _detect_topics(self, text: str) -> list[str]:
        """Erkennt Fachgebiete und Schlagworte im Text."""
        detected = []
        kw_map = {
            "fastapi": "FastAPI / Backend",
            "pytest": "Testing / Pytest",
            "mcp": "MCP Protokoll & Tools",
            "sqlite": "SQLite / bach.db",
            "windows": "Windows OS & PowerShell",
            "mac": "macOS / Mac Studio",
            "astro": "Astro GUI / Frontend",
            "mermaid": "Mermaid Diagramme",
            "git": "Git Hygiene & Branches",
            "lock": "Lock-System & Guardrails",
            "docker": "Container / Docker",
            "auth": "Sicherheit & Authentifizierung"
        }
        text_lower = text.lower()
        for kw, label in kw_map.items():
            if kw in text_lower and label not in detected:
                detected.append(label)
        return detected

    def _synthesize_summary(self, turns: list[dict[str, str]], topics: list[str]) -> str:
        """Erstellt eine verdichtete Gesamtzusammenfassung der Sitzung."""
        if not turns:
            return "Keine signifikanten Signale im Transkript gefunden."

        topics_str = ", ".join(topics) if topics else "Allgemein"
        first_user = next((t["content"] for t in turns if t["role"] in {"user", "user_or_system"}), "")
        first_user_snippet = (first_user[:120] + "...") if len(first_user) > 120 else first_user

        return (
            f"Fokus-Themen: {topics_str}. "
            f"Kern-Anliegen: '{first_user_snippet}'. "
            f"Enthält {len(turns)} Signal-Beiträge nach Rauschfilterung."
        )

    # ─────────────────────────────────────────────────────────────
    # B. LESSONS LEARNED EXTRAKTION
    # ─────────────────────────────────────────────────────────────

    def extract_lessons(self, cleaned: CleanedTranscriptResult) -> list[DistilledLesson]:
        """Extrahiert konkrete Fehler-Lösungs-Muster und Best Practices."""
        lessons: list[DistilledLesson] = []

        full_content = "\n\n".join(t["content"] for t in cleaned.signal_turns)

        # 1. Spezifische bekannte System-Muster prüfen
        if "charmap" in full_content.lower() or "unicodeencodeerror" in full_content.lower():
            lessons.append(DistilledLesson(
                category="windows_env",
                title="Windows PowerShell Unicode / Emoji Encode-Fehler",
                solution="Vor Python-Aufrufen mit Unicode-Ausgabe immer $env:PYTHONIOENCODING='utf-8' setzen."
            ))

        if "modulenotfounderror: no module named 'system'" in full_content.lower():
            lessons.append(DistilledLesson(
                category="testing",
                title="Pytest System-Import Pfad-Auflösung",
                solution="Bei Ausführung im Repo-Root PYTHONPATH=. explizit übergeben oder 'python -m pytest' nutzen."
            ))

        if "unable to render rich display" in full_content.lower() or "lint_mermaid" in full_content.lower():
            lessons.append(DistilledLesson(
                category="documentation",
                title="Mermaid Syntax-Guardrail für GitHub",
                solution="Labels mit Klammern oder Sonderzeichen immer in Anführungszeichen setzen: Node[\"Label (Info)\"]."
            ))

        # 1.5. Allgemeines Problem-Lösungs-Muster erfassen
        pl_match = re.search(
            r"(?:problem|fehler|bug|error|issue)[:\s]+(.*?)(?:lösung|fix|gelöst|behebung)[:\s]+(.*?)(?:\.|\n|\Z)",
            full_content,
            re.IGNORECASE
        )
        if pl_match:
            p_text = pl_match.group(1).strip()
            s_text = pl_match.group(2).strip()
            if p_text and s_text:
                cat = cleaned.detected_topics[0].lower().split()[0] if cleaned.detected_topics else "bugfix"
                lessons.append(DistilledLesson(
                    category=cat,
                    title=f"Fehlerbehebung: {p_text}"[:100],
                    solution=s_text[:300]
                ))

        # 2. Generische Mustererkennung
        for turn in cleaned.signal_turns:
            content = turn["content"]
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                line_lower = line.lower()
                if any(k in line_lower for k in ["merke:", "best practice:", "wichtig:", "lesson learned:"]):
                    title = line.split(":", 1)[1].strip() if ":" in line else line
                    solution_lines = lines[idx+1:idx+4]
                    solution = " ".join(l.strip() for l in solution_lines if l.strip()) or title
                    if len(title) > 5:
                        cat = cleaned.detected_topics[0].lower().split()[0] if cleaned.detected_topics else "general"
                        lessons.append(DistilledLesson(
                            category=cat,
                            title=title[:100],
                            solution=solution[:300]
                        ))

        # Duplikate filtern
        unique_lessons: list[DistilledLesson] = []
        seen_titles = set()
        for les in lessons:
            key = les.title.strip().lower()
            if key not in seen_titles:
                seen_titles.add(key)
                unique_lessons.append(les)

        return unique_lessons

    # ─────────────────────────────────────────────────────────────
    # C. SKILL-KANDIDATEN SYNTHESE (SKILL.md)
    # ─────────────────────────────────────────────────────────────

    def distill_skill(
        self,
        cleaned: CleanedTranscriptResult,
        session_id: str | None = None,
        skill_name_hint: str | None = None
    ) -> SkillCandidate:
        """Erzeugt einen normgerechten SKILL.md-Entwurf fuer die Human-in-the-Loop Freigabe."""
        # 1. Namen und Rolle ermitteln
        if skill_name_hint:
            raw_name = skill_name_hint
        elif cleaned.detected_topics:
            main_topic = cleaned.detected_topics[0].lower().replace(" / ", "-").replace(" ", "-")
            raw_name = f"learned-{main_topic}-ops"
        else:
            raw_name = "learned-workflow-helper"

        # Kebab-Case Validierung
        skill_name = re.sub(r"[^a-z0-9\-]", "-", raw_name.lower()).strip("-")
        if not skill_name:
            skill_name = "learned-custom-skill"

        category = "utilities"
        if any(t in skill_name for t in ["test", "fastapi", "code", "pytest"]):
            category = "dev"
        elif any(t in skill_name for t in ["windows", "mac", "cluster", "git", "lock"]):
            category = "infrastructure"

        role = f"Spezialisierter Assistent fuer {', '.join(cleaned.detected_topics) if cleaned.detected_topics else 'wiederkehrende Aufgaben'}"
        description = f"Autonom destillierter Skill aus Session {session_id or 'chat-run'}: {cleaned.consolidated_summary[:140]}"

        triggers = [
            f"{skill_name}",
            f"führe {skill_name} aus",
            f"hilf bei {cleaned.detected_topics[0] if cleaned.detected_topics else 'diesem Workflow'}"
        ]

        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

        frontmatter_dict = {
            "name": skill_name,
            "version": "1.0.0",
            "role": role,
            "category": category,
            "description": description,
            "triggers": triggers,
            "provenance": {
                "distilled_by": "hermes",
                "source_session": session_id or "adhoc_transcript",
                "distilled_at": now_iso,
                "confidence": 0.88,
                "noise_reduction_percent": cleaned.noise_reduction_percent
            }
        }

        # 2. SKILL.md Markdown Body generieren
        markdown_body = f"""---
name: {skill_name}
version: 1.0.0
role: {role}
category: {category}
description: {description}
triggers:
{chr(10).join(f'  - "{t}"' for t in triggers)}
provenance:
  distilled_by: hermes
  source_session: {session_id or 'adhoc_transcript'}
  distilled_at: "{now_iso}"
  confidence: 0.88
  noise_reduction_percent: {cleaned.noise_reduction_percent}
---

# {skill_name.title()}

## 1. Übersicht & Zweck
{description}

Dieser unveröffentlichte Entwurf stammt aus der lokalen BACH-Heuristik **hermes_distillation_service**.
Die enthaltenen Hinweise sind Kandidaten; Tests, Wiederverwendung und native Veröffentlichung sind noch nicht bestätigt.

## 2. Trigger-Bedingungen (Wann aktivieren?)
Aktiviere diesen Skill bei folgenden Anfragen oder Stichworten:
{chr(10).join(f'- `{t}`' for t in triggers)}

## 3. Verhaltensregeln & Leitplanken (Safety & Guardrails)
- **Fail-Closed:** Vorgänge bei unerwarteten Fehlern sofort stoppen und Zustand nicht inkonsistent hinterlassen.
- **Lock-Schutz:** Prüfe vor Schreiboperationen auf Verzeichnis- und Dateisperren (`LOCK.user.*`, `LOCK.txt`).
- **Codierung:** Unter Windows Ausgaben immer explizit in UTF-8 halten.

## 4. Standard-Ablauf (Workflow-Schritte)
1. **Ist-Zustand prüfen:** Umgebungs- und Versionsprüfung durchführen.
2. **Kernaufgabe ausführen:** Befolgen der aus der Session destillierten Schritte:
   - Themenfokus: {', '.join(cleaned.detected_topics) if cleaned.detected_topics else 'Allgemeine Ausführung'}.
   - Validierung aller Zwischenschritte vor dem finalen Abschluss.
3. **Ergebnis sichern & testen:** Pytest-Suite und Mermaid/Linter-Gates durchlaufen lassen.

## 5. Destillierte Signal-Muster
{chr(10).join(f"- **{t['role']}**: {t['content'][:150]}..." for t in cleaned.signal_turns[:3])}
"""

        return SkillCandidate(
            name=skill_name,
            category=category,
            role=role,
            version="1.0.0",
            description=description,
            trigger_phrases=triggers,
            frontmatter=frontmatter_dict,
            content=markdown_body,
            confidence=0.88,
            source_session=session_id,
            noise_reduction_ratio=round(cleaned.noise_reduction_percent / 100.0, 3),
            status="pending",
            created_at=now_iso
        )

    # ─────────────────────────────────────────────────────────────
    # D. VOLLSTÄNDIGE DISTILLATIONS-PIPELINE
    # ─────────────────────────────────────────────────────────────

    def run_pipeline(
        self,
        messages_or_text: list[dict[str, Any]] | str,
        session_id: str | None = None,
        skill_name_hint: str | None = None,
        persist: bool = True
    ) -> DistillationResult:
        """Fuehrt die komplette Destillationskette aus und speichert Resultate."""
        self.ensure_schema()

        # 1. Rauschreduktion
        cleaned = self.clean_transcript(messages_or_text, session_id=session_id)

        # 2. Lessons Learned Extraktion
        lessons = self.extract_lessons(cleaned)

        # 3. Skill-Kandidaten Synthese
        candidate = self.distill_skill(cleaned, session_id=session_id, skill_name_hint=skill_name_hint)

        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        run_id = 0
        candidate_dict = asdict(candidate)

        if persist:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()

                # Drafts stay inside the candidate, outside all active memory readers.
                draft_json = json.dumps([asdict(lesson) for lesson in lessons], ensure_ascii=False)

                # B. Kandidaten in hermes_skill_candidates speichern
                cursor.execute("""
                    INSERT INTO hermes_skill_candidates (
                        name, category, role, version, description, trigger_phrases,
                        frontmatter, content, confidence, source_session,
                        noise_reduction_ratio, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """, (
                    candidate.name,
                    candidate.category,
                    candidate.role,
                    candidate.version,
                    candidate.description,
                    json.dumps(candidate.trigger_phrases, ensure_ascii=False),
                    json.dumps(candidate.frontmatter, ensure_ascii=False),
                    candidate.content,
                    candidate.confidence,
                    candidate.source_session,
                    candidate.noise_reduction_ratio,
                    now_iso
                ))
                candidate_id = cursor.lastrowid
                candidate.id = candidate_id
                candidate_dict["id"] = candidate_id
                cursor.execute("UPDATE hermes_skill_candidates SET lessons_draft_json=? WHERE id=?",
                    (draft_json, candidate_id))
                row = cursor.execute("SELECT * FROM hermes_skill_candidates WHERE id=?", (candidate_id,)).fetchone()
                proposal, digest = proposal_binding("hermes", row)
                cursor.execute("""UPDATE hermes_skill_candidates SET
                    candidate_revision=1,candidate_digest=?,proposal_json=? WHERE id=?""",
                    (digest, proposal, candidate_id))
                candidate_dict.update(candidate_revision=1, candidate_digest=digest,
                    lessons_draft=[asdict(lesson) for lesson in lessons], promotion_available=False)

                # C. Run in hermes_distillation_runs speichern
                cursor.execute("""
                    INSERT INTO hermes_distillation_runs (
                        session_id, raw_char_count, cleaned_char_count,
                        noise_reduction_percent, lessons_count, skills_count,
                        status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'completed', ?)
                """, (
                    session_id,
                    cleaned.raw_char_count,
                    cleaned.cleaned_char_count,
                    cleaned.noise_reduction_percent,
                    len(lessons),
                    1,
                    now_iso
                ))
                run_id = cursor.lastrowid

                # D. Log-Eintrag in memory_dream_log
                cursor.execute("""
                    INSERT INTO memory_dream_log (noise_reduced, items_consolidated, summary, created_at)
                    VALUES (?, ?, ?, ?)
                """, (
                    max(0, cleaned.raw_char_count - cleaned.cleaned_char_count),
                    0,  # Draft extraction is not active memory consolidation.
                    f"Hermes Entwürfe Run #{run_id}: {cleaned.consolidated_summary[:120]}",
                    now_iso
                ))

                conn.commit()
            finally:
                conn.close()

        return DistillationResult(
            run_id=run_id,
            session_id=session_id,
            raw_char_count=cleaned.raw_char_count,
            cleaned_char_count=cleaned.cleaned_char_count,
            noise_reduction_percent=cleaned.noise_reduction_percent,
            lessons=[asdict(l) for l in lessons],
            candidate=candidate_dict,
            status="completed",
            created_at=now_iso
        )

    # ─────────────────────────────────────────────────────────────
    # E. KANDIDATEN-VERWALTUNG & HUMAN-IN-THE-LOOP APPROVAL
    # ─────────────────────────────────────────────────────────────

    def list_candidates(self, status: str = "pending", limit: int = 50) -> list[dict[str, Any]]:
        """Liefert Skill-Kandidaten aus der DB."""
        self.ensure_schema()
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = "SELECT * FROM hermes_skill_candidates"
            params: list[Any] = []
            if status and status != "all":
                query += " WHERE status = ?"
                params.append(status)
            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)

            rows = cursor.execute(query, params).fetchall()
            candidates = []
            for r in rows:
                item = project_candidate("hermes", r)
                try:
                    item["trigger_phrases"] = json.loads(item.get("trigger_phrases") or "[]")
                except (json.JSONDecodeError, TypeError):
                    item["trigger_phrases"] = []
                try:
                    item["frontmatter"] = json.loads(item.get("frontmatter") or "{}")
                except (json.JSONDecodeError, TypeError):
                    item["frontmatter"] = {}
                item["lessons_draft"] = json.loads(item["lessons_draft_json"])
                candidates.append(item)
            return candidates
        finally:
            conn.close()

    def get_candidate(self, candidate_id: int) -> dict[str, Any] | None:
        """Liefert einen einzelnen Kandidaten anhand seiner ID."""
        self.ensure_schema()
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            row = cursor.execute(
                "SELECT * FROM hermes_skill_candidates WHERE id = ?",
                (candidate_id,)
            ).fetchone()
            if not row:
                return None
            item = project_candidate("hermes", row)
            try:
                item["trigger_phrases"] = json.loads(item.get("trigger_phrases") or "[]")
            except (json.JSONDecodeError, TypeError):
                item["trigger_phrases"] = []
            try:
                item["frontmatter"] = json.loads(item.get("frontmatter") or "{}")
            except (json.JSONDecodeError, TypeError):
                item["frontmatter"] = {}
            item["lessons_draft"] = json.loads(item["lessons_draft_json"])
            return item
        finally:
            conn.close()

    def approve_candidate(self, candidate_id: int, approved_by: str = "operator") -> dict[str, Any]:
        """Legacy direct activation cannot stand in for native publication."""
        self.ensure_schema()
        conn = self._get_connection()
        try:
            prohibit_legacy_promotion(conn, "hermes", candidate_id)
        finally:
            conn.close()

    def review_candidate(self, candidate_id: int, *, expected_revision=None, expected_digest=None,
                         request_id=None, actor="", notes="") -> dict[str, Any]:
        self.ensure_schema()
        conn = self._get_connection()
        try:
            return record_review(conn, "hermes", candidate_id,
                expected_revision=expected_revision, expected_digest=expected_digest,
                request_id=request_id, actor=actor, decision="reviewed", notes=notes)
        finally:
            conn.close()

    def reject_candidate(self, candidate_id: int, reason: str = "", *, expected_revision=None,
                         expected_digest=None, request_id=None, actor="operator") -> dict[str, Any]:
        self.ensure_schema()
        conn = self._get_connection()
        try:
            receipt = record_review(conn, "hermes", candidate_id,
                expected_revision=expected_revision, expected_digest=expected_digest,
                request_id=request_id, actor=actor, decision="rejected", notes=reason)
            return {**receipt, "reason": reason}
        finally:
            conn.close()

    def get_stats(self) -> dict[str, Any]:
        """Liefert Gesamtmetriken fuer das Ocean-Manifest und Dashboard."""
        self.ensure_schema()
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            total_runs = cursor.execute("SELECT COUNT(*) FROM hermes_distillation_runs").fetchone()[0]
            avg_reduction = cursor.execute("SELECT AVG(noise_reduction_percent) FROM hermes_distillation_runs").fetchone()[0] or 0.0
            total_candidates = cursor.execute("SELECT COUNT(*) FROM hermes_skill_candidates").fetchone()[0]
            pending_candidates = cursor.execute("SELECT COUNT(*) FROM hermes_skill_candidates WHERE status = 'pending'").fetchone()[0]
            approved_candidates = cursor.execute("SELECT COUNT(*) FROM hermes_skill_candidates WHERE status = 'approved'").fetchone()[0]
            total_lessons = cursor.execute("SELECT COUNT(*) FROM memory_lessons").fetchone()[0]

            return {
                "total_runs": total_runs,
                "average_noise_reduction_percent": round(float(avg_reduction), 1),
                "total_candidates": total_candidates,
                "pending_candidates": pending_candidates,
                "approved_candidates": approved_candidates,
                "total_lessons_learned": total_lessons,
                "native_promotion_available": False,
                "status": "active"
            }
        finally:
            conn.close()


# Singleton Instanz
_default_service: HermesDistillationService | None = None

def get_hermes_service() -> HermesDistillationService:
    global _default_service
    if _default_service is None:
        _default_service = HermesDistillationService()
    return _default_service
