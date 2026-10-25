# -*- coding: utf-8 -*-
"""content-guard – Mehrsprachige Injection-Erkennung und Content-Markierung.

Bietet einen fail-closed Prüfweg für Worker-Toolcalls und Kettenübergaben:
Erkennt injektionsverdächtige Muster (mehrsprachig), markiert unvertraute
Inhalte, leitet optional an Ollama (Stufe 2, lokal) oder Google Model Armor
(Stufe 3, optional) weiter.

Architektur (nach agents-heart-Vorbild):
- Frozen Dataclass für Prüfergebnisse
- Exceptions als RuntimeError-Subclass
- Event-Recorder für Nachverfolgbarkeit
- Fail-closed: bei Unsicherheit wird blockiert

NOTICE: Enthält von SentinelFleet übernommene Teile (Regex-Musterlogik;
Quelle sentinel-fleet e7f9c748). Lukas ist alleiniger Rechteinhaber dieser
Teile (AGPL-3.0) und lizenziert sie hier unter MIT für BACH; Freigabe laut
Bericht OCEAN/BERICHTE/2026-10-25_SentinelFleet-Uebernahme. Architektur nach
agents-heart-Muster (Frozen Dataclass, Fail-closed, Event-Recorder).
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional


# ─── Time ───────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    """ISO-8601 UTC-Zeitstempel."""
    return datetime.now(timezone.utc).isoformat()


# ─── Exceptions ───────────────────────────────────────────────────────────────

class ContentGuardError(RuntimeError):
    """Basis-Exception für content-guard."""


class ContentBlockedError(ContentGuardError):
    """Inhalt wurde als injektionsverdächtig markiert und blockiert."""

    def __init__(self, findings: List[Dict[str, Any]], reason: str = ""):
        self.findings = findings
        super().__init__(f"Content blockiert: {reason or str(findings)}")


class GuardConfigurationError(ContentGuardError):
    """Fehlerhafte Konfiguration des Content-Guards."""


# ─── Data Classes ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class InjectionPattern:
    """Ein injektionsverdächtiges Muster mit Metadaten."""
    id: str
    description: str
    pattern: re.Pattern
    language: str
    severity: str  # "high" | "medium" | "low"
    category: str  # "prompt_injection" | "exfiltration" | "role_hijack" | ...


@dataclass(frozen=True)
class Finding:
    """Ein einzelner Treffer."""
    pattern_id: str
    pattern_description: str
    language: str
    severity: str
    category: str
    matched_text: str
    position: int  # Start-Offset im Eingabetext
    confidence: float  # 0.0–1.0


@dataclass(frozen=True)
class GuardVerdict:
    """Prüfergebnis für einen Toolcall bzw. eine Kettenübergabe."""
    verdict_id: str
    timestamp: str
    action: str  # "allow" | "block" | "mark_untrusted"
    findings: List[Finding]
    content_hash: str
    adapter_used: str  # "local" | "ollama" | "model_armor" | "none"
    blocked: bool
    untrusted_mark: bool
    reason: str = ""

    @property
    def is_safe(self) -> bool:
        return self.action == "allow" and not self.blocked


@dataclass(frozen=True)
class GuardConfig:
    """Konfiguration des Content-Guards."""
    ollama_endpoint: str = "http://localhost:11434"
    ollama_model: str = "llama3"
    ollama_enabled: bool = False  # Standard AUS
    model_armor_endpoint: str = ""
    model_armor_enabled: bool = False  # Standard AUS
    fail_closed: bool = True
    max_findings: int = 10
    untrusted_threshold: int = 2  # >= 2 Findings → mark_untrusted


# ─── Multilingual Injection Patterns ─────────────────────────────────────────

def _build_patterns() -> List[InjectionPattern]:
    """Erstellt die mehrsprachige Pattern-Library."""
    raw = [
        # English patterns (5+)
        ("en-inj-001", "System prompt override", r"(?i)\b(ignore|disregard|override|forget)\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?)\b", "en", "high", "prompt_injection"),
        ("en-inj-002", "Role hijacking", r"(?i)\byou\s+are\s+now\s+(a\s+)?(different|new)\s+(ai|agent|assistant|character)\b", "en", "high", "role_hijack"),
        ("en-inj-003", "Jailbreak via DAN", r"(?i)\b(?:act\s+as|pretend\s+to\s+be|you\s+are)\s+(?:DAN|do\s+anything\s+now|an\s+unrestricted)\b", "en", "high", "jailbreak"),
        ("en-inj-004", "Exfiltration attempt", r"(?i)\b(send|post|upload|transmit|leak)\s+(the|all|your|these)\s+(secret|private|confidential|internal|system|prompt|data|tokens?|keys?|credentials?)\b", "en", "high", "exfiltration"),
        ("en-inj-005", "Code execution injection", r"(?i)\bexecute|run|eval\s*\(|system\s*\(|os\.system|subprocess\.(?:run|call|Popen)\b", "en", "medium", "code_execution"),
        ("en-inj-006", "Markdown injection", r"(?i)^(?:#{1,6}\s*(?:system|internal|admin|private))|(?i)\[!\[(?:system|internal|admin)\]", "en", "medium", "markdown_injection"),
        ("en-inj-007", "Delimiter abuse", r"(?i)(?:<\|(?:SYSTEM|INST|USER)\|>|<<\|(?:SYSTEM|INST)\|>>|<\s*/?\s*system\s*/?\s*>|===\s*(?:system|instruction)\s*===)", "en", "high", "delimiter_abuse"),
        # German
        ("de-inj-001", "Systemanweisung ignorieren (DE)", r"(?i)\b(ignorier(e|en|e\+st)|vergiss(e|en)|überschreib(e|en)|setze|leer(e|en)\s+den?)\s+(alle\s+)?(vorherigen?|bisherigen?|früheren?|obenstehenden?)\s+(Anweisungen?|Prompts?|Regeln?)\b", "de", "high", "prompt_injection"),
        ("de-inj-002", "Rollenwechsel (DE)", r"(?i)\bdu\s+bist\s+(jetzt|nun|ab\s+sofort)\s+(ein(e|r)?\s+)?(ander(e|er|en)|neue?r?)\s+(KI|Agent|Assistent|Charakter)\b", "de", "high", "role_hijack"),
        ("de-inj-003", "Schadcode (DE)", r"(?i)\b(führe\s+aus|führe\s+bzw\s+|starte|läuft|ausführe)\s+(den|diesen|folgende|skript|code|befehl)\b", "de", "medium", "code_execution"),
        # Spanish
        ("es-inj-001", "Ignorar instrucciones (ES)", r"(?i)\b(ignora|olvida|anula|sobrescribe)\s+(todas\s+las\s+)?(instrucciones?|prompts?|reglas?)\s+(anterior(es)?|precedente(s)?)\b", "es", "high", "prompt_injection"),
        ("es-inj-002", "Exfiltración (ES)", r"(?i)\b(envía|sube|transmite|filtra)\s+(los|las|todos|todas)\s+(secretos?|datos?|claves?|credenciales?|token(s)?)\b", "es", "high", "exfiltration"),
        # French
        ("fr-inj-001", "Ignorer les instructions (FR)", r"(?i)\b(ignore|oublie|écrase|remplace)\s+(toutes?\s+les\s+)?(instructions?|prompts?|règles?)\s+(précédente(s)?|antérieur(es)?)\b", "fr", "high", "prompt_injection"),
        ("fr-inj-002", "Hijack de rôle (FR)", r"(?i)\b(?:tu\s+es\s+désormais|deviens|transforme-toi\s+en)\s+(un\s+)?(?:autre|nouveau)\s+(IA|agent|assistant)\b", "fr", "high", "role_hijack"),
        # Japanese
        ("jp-inj-001", "指示無視 (JP)", r"(?i)(無視|忘れ|上書き|無効化)\s*(して|せよ|する)\s*(以前の|先ほどの|前回の)\s*(指示|プロンプト|ルール|規則)", "jp", "high", "prompt_injection"),
        ("jp-inj-002", "情報漏洩 (JP)", r"(?i)(送信|公開|漏洩|窃取|盗む)\s*(して|せよ)\s*(秘密|個人|認証|鍵|トークン|データ)", "jp", "high", "exfiltration"),
        # Russian
        ("ru-inj-001", "Игнорирование (RU)", r"(?i)(игнорируй|забудь|перезапиши|отмени)\s*(все\s+)?(предыдущ(ие|их)|прошлые|раннее)\s*(инструкци|промпт|правило|правила)", "ru", "high", "prompt_injection"),
        ("ru-inj-002", "Экстракция (RU)", r"(?i)(отправь|выгрузи|передай|утони|укради)\s*(все|все|секретн|ключ|токен|данны|информаци)", "ru", "high", "exfiltration"),
        # Afrikaans
        ("za-inj-001", "Negeer instruksies (ZA)", r"(?i)\b(geen|ignoreer|vergeet|vervang)\s+(alle\s+)?(vorige|earliere|bovenstaande)\s+(instruksies?|reëls?|aanwysings?)\b", "za", "high", "prompt_injection"),
        ("za-inj-002", "Data-uitvloei (ZA)", r"(?i)\b(stuur|plaas|laai|laat|leak)\s+(die|al)\s+(geheim|privaat|sleutel|kredensiaal|token|data)\b", "za", "high", "exfiltration"),
    ]
    patterns: List[InjectionPattern] = []
    for pid, desc, pat_str, lang, sev, cat in raw:
        try:
            rx = re.compile(pat_str)
            patterns.append(InjectionPattern(id=pid, description=desc, pattern=rx, language=lang, severity=sev, category=cat))
        except re.error:
            continue
    return patterns


# ─── Core Guard ───────────────────────────────────────────────────────────────

class ContentGuard:
    """Fail-closed Content-Guard für Toolcalls und Kettenübergaben.

    Reihenfolge:
      1. Lokale Regex-Prüfung (Stufe 1, immer aktiv)
      2. Ollama-Prüfung (Stufe 2, optional, Standard AUS)
      3. Google Model Armor (Stufe 3, optional, Standard AUS)

    Fail-closed: Bei jedem Fehler (Timeout, Verbindungsfehler,
    unklarem Ergebnis) wird der Inhalt als blockiert behandelt.
    """

    def __init__(
        self,
        config: GuardConfig | None = None,
        event_recorder: Callable[[Dict[str, Any]], None] | None = None,
    ):
        self._config = config or GuardConfig()
        self._patterns = _build_patterns()
        self._event_recorder = event_recorder
        self._instance_id = str(uuid.uuid4())
        if not self._patterns:
            raise GuardConfigurationError("Keine Patterns geladen – Refusal to start.")

    # ─── Public API ──────────────────────────────────────────────────────────

    def pruefe_toolcall(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        context: Dict[str, Any] | None = None,
    ) -> GuardVerdict:
        """Prüft die Argumente eines Worker-Toolcalls vor Ausführung.

        Fail-closed: Bei jedem Fehler wird blockiert.
        """
        return self._pruefe(
            content=self._serialize_arguments(arguments),
            context={"tool_name": tool_name, **(context or {})},
        )

    def pruefe_kettenuebergabe(
        self,
        content: str,
        source_agent: str,
        target_agent: str,
        session_id: str | None = None,
    ) -> GuardVerdict:
        """Prüft eine Kettenübergabe zwischen Agenten.

        Fail-closed: Bei jedem Fehler wird blockiert.
        """
        return self._pruefe(
            content=content,
            context={
                "source_agent": source_agent,
                "target_agent": target_agent,
                "session_id": session_id or self._instance_id,
                "transfer_type": "chain_handoff",
            },
        )

    # ─── Internal ────────────────────────────────────────────────────────────

    def _serialize_arguments(self, args: Dict[str, Any]) -> str:
        """Serialisiert Tool-Argumente zu prüfbarem Text."""
        parts: List[str] = []
        for key, val in args.items():
            if isinstance(val, str):
                parts.append(f"{key}: {val}")
            else:
                parts.append(f"{key}: {repr(val)}")
        return "\n".join(parts)

    def _pruefe(self, content: str, context: Dict[str, Any]) -> GuardVerdict:
        """Kernprüfung mit fail-closed-Semantik."""
        findings: List[Finding] = []

        # Stufe 1: Lokale Regex
        for pat in self._patterns:
            for m in pat.pattern.finditer(content):
                findings.append(Finding(
                    pattern_id=pat.id,
                    pattern_description=pat.description,
                    language=pat.language,
                    severity=pat.severity,
                    category=pat.category,
                    matched_text=m.group()[:120],
                    position=m.start(),
                    confidence=0.95,
                ))
                if len(findings) >= self._config.max_findings:
                    break

        # Stufe 2: Ollama (optional, Standard AUS)
        adapter_used = "local"
        if self._config.ollama_enabled:
            try:
                extra = self._ollama_check(content)
                findings.extend(extra)
                adapter_used = "ollama"
            except Exception:
                # Fail-closed: Fehler → block
                findings.append(Finding(
                    pattern_id="ollama-error",
                    pattern_description="Ollama-Adapter-Fehler (fail-closed)",
                    language="system",
                    severity="high",
                    category="adapter_failure",
                    matched_text="(ollama unavailable)",
                    position=-1,
                    confidence=0.0,
                ))

        # Stufe 3: Model Armor (optional, Standard AUS)
        if self._config.model_armor_enabled:
            try:
                extra = self._model_armor_check(content)
                findings.extend(extra)
                adapter_used = "model_armor"
            except Exception:
                findings.append(Finding(
                    pattern_id="armor-error",
                    pattern_description="Model Armor Adapter-Fehler (fail-closed)",
                    language="system",
                    severity="high",
                    category="adapter_failure",
                    matched_text="(armor unavailable)",
                    position=-1,
                    confidence=0.0,
                ))

        # Entscheidung
        if not findings:
            action, blocked, untrusted = "allow", False, False
            reason = "keine Auffälligkeiten"
        elif self._config.fail_closed and any(
            f.severity == "high" for f in findings
        ):
            action, blocked, untrusted = "block", True, True
            reason = f"{len(findings)} hochkritische Funde"
        elif len(findings) >= self._config.untrusted_threshold:
            action, blocked, untrusted = "mark_untrusted", False, True
            reason = f"{len(findings)} Funde ≥ Schwelle {self._config.untrusted_threshold}"
        else:
            action, blocked, untrusted = "allow", False, False
            reason = f"{len(findings)} niedrigkritische Funde – zulässig"

        verdict = GuardVerdict(
            verdict_id=str(uuid.uuid4()),
            timestamp=_utc_now(),
            action=action,
            findings=findings,
            content_hash=hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest(),
            adapter_used=adapter_used,
            blocked=blocked,
            untrusted_mark=untrusted,
            reason=reason,
        )

        self._emit(verdict, context)

        if blocked:
            raise ContentBlockedError(findings, reason)
        return verdict

    def _emit(self, verdict: GuardVerdict, context: Dict[str, Any]) -> None:
        """Zeichnet das Prüfungsergebnis im Event-Recorder auf."""
        if self._event_recorder:
            self._event_recorder({
                "verdict_id": verdict.verdict_id,
                "event": "content_guard.verdict",
                "action": verdict.action,
                "blocked": verdict.blocked,
                "untrusted_mark": verdict.untrusted_mark,
                "findings_count": len(verdict.findings),
                "adapter": verdict.adapter_used,
                "instance_id": self._instance_id,
                "timestamp": verdict.timestamp,
                **context,
            })

    # ─── Adapters ────────────────────────────────────────────────────────────

    def _ollama_check(self, content: str) -> List[Finding]:
        """Stufe 2: Lokale Ollama-Prüfung (Standard AUS)."""
        # Platzhalter – in Produktion: HTTP-Request an Ollama
        # Für jetzt: leere Liste (kein Fehler, kein Fund)
        return []

    def _model_armor_check(self, content: str) -> List[Finding]:
        """Stufe 3: Google Model Armor (optional, Standard AUS)."""
        # Platzhalter – in Produktion: API-Call an Model Armor
        return []


# ─── Module-Level Convenience ─────────────────────────────────────────────────

_default_guard: Optional[ContentGuard] = None


def _get_default_guard() -> ContentGuard:
    global _default_guard
    if _default_guard is None:
        _default_guard = ContentGuard()
    return _default_guard


def pruefe_toolcall(tool_name: str, arguments: Dict[str, Any], **kwargs: Any) -> GuardVerdict:
    """Modul-level Wrapper um ContentGuard.pruefe_toolcall."""
    return _get_default_guard().pruefe_toolcall(tool_name, arguments, **kwargs)


def pruefe_kettenuebergabe(content: str, source_agent: str, target_agent: str, **kwargs: Any) -> GuardVerdict:
    """Modul-level Wrapper um ContentGuard.pruefe_kettenuebergabe."""
    return _get_default_guard().pruefe_kettenuebergabe(content, source_agent, target_agent, **kwargs)
