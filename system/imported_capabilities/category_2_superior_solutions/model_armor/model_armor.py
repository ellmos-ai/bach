"""Model Armor & Inline Guardrails (Anti-Prompt-Injection & PII Masking)."""

import re
import asyncio
from typing import Any, Dict, List, Tuple
from pydantic import BaseModel


class ArmorInspectionResult(BaseModel):
    is_safe: bool
    blocked_patterns: List[str] = []
    sanitized_data: Any = None
    redacted_fields: List[str] = []


class ModelArmor:
    # Injection and Jailbreak patterns
    INJECTION_PATTERNS = [
        re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
        re.compile(r"system\s*prompt\s*override", re.IGNORECASE),
        re.compile(r"reveal\s+(your\s+)?(system\s+prompt|credentials|api[_\s-]?key)", re.IGNORECASE),
        re.compile(r"you\s+are\s+now\s+in\s+DAN\s+mode", re.IGNORECASE),
        re.compile(r"<script>.*?</script>", re.IGNORECASE),
    ]

    # Sensitive PII patterns
    IBAN_PATTERN = re.compile(r"\b[A-Z]{2}[0-9]{2}(?:[ ]?[0-9]{4}){4}(?:[ ]?[0-9]{1,2})?\b")
    API_KEY_PATTERN = re.compile(r"(AIza[0-9A-Za-z-_]{30,}|sk-[a-zA-Z0-9]{20,})")
    CREDIT_CARD_PATTERN = re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b")

    MAX_RECURSION_DEPTH = 10
    MAX_STRING_SCAN_BYTES = 500_000

    @classmethod
    def inspect_prompt(cls, prompt_text: str) -> ArmorInspectionResult:
        """Scan input prompts for adversarial injections and jailbreaks."""
        detected = []
        # Protect against oversized prompts
        text_to_scan = prompt_text[:cls.MAX_STRING_SCAN_BYTES] if len(prompt_text) > cls.MAX_STRING_SCAN_BYTES else prompt_text

        for pattern in cls.INJECTION_PATTERNS:
            if pattern.search(text_to_scan):
                detected.append(pattern.pattern)

        # A small canonical pass catches spacing/punctuation evasions without pretending this
        # regex layer is a complete semantic defence. Authorization and least privilege remain
        # separate gates.
        canonical = re.sub(r"[^a-z]", "", text_to_scan.lower())
        for phrase in (
            "ignorepreviousinstructions",
            "ignorepriorinstructions",
            "disregardearlierdirections",
            "revealsystemprompt",
        ):
            if phrase in canonical:
                detected.append(f"canonical:{phrase}")

        if detected:
            return ArmorInspectionResult(
                is_safe=False,
                blocked_patterns=detected,
                sanitized_data=None
            )

        return ArmorInspectionResult(
            is_safe=True,
            sanitized_data=prompt_text
        )

    @classmethod
    def inspect_arguments(cls, value: Any, depth: int = 0) -> ArmorInspectionResult:
        """Inspect every untrusted string in a nested argument payload."""
        if depth > cls.MAX_RECURSION_DEPTH:
            return ArmorInspectionResult(
                is_safe=False,
                blocked_patterns=["argument nesting exceeds inspection depth"],
            )
        strings: List[str] = []
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                result = cls.inspect_arguments(item, depth + 1)
                if not result.is_safe:
                    return result
        elif isinstance(value, (list, tuple)):
            for item in value:
                result = cls.inspect_arguments(item, depth + 1)
                if not result.is_safe:
                    return result
        for text in strings:
            result = cls.inspect_prompt(text)
            if not result.is_safe:
                return result
        return ArmorInspectionResult(is_safe=True, sanitized_data=value)

    @classmethod
    def sanitize_pii(cls, text: str) -> Tuple[str, List[str]]:
        """Sanitize sensitive data and return sanitized text with list of redacted items."""
        redacted = []

        # Redact IBANs
        if cls.IBAN_PATTERN.search(text):
            text = cls.IBAN_PATTERN.sub("[REDACTED_IBAN]", text)
            redacted.append("IBAN")

        # Redact API Keys
        if cls.API_KEY_PATTERN.search(text):
            text = cls.API_KEY_PATTERN.sub("[REDACTED_API_KEY]", text)
            redacted.append("API_KEY")

        # Redact Credit Cards
        if cls.CREDIT_CARD_PATTERN.search(text):
            text = cls.CREDIT_CARD_PATTERN.sub("[REDACTED_CREDIT_CARD]", text)
            redacted.append("CREDIT_CARD")

        return text, redacted

    @classmethod
    def sanitize_arguments(cls, args: Dict[str, Any], depth: int = 0) -> Dict[str, Any]:
        """Deep synchronous sanitization of dictionary arguments with recursion bounds."""
        if depth > cls.MAX_RECURSION_DEPTH:
            return args

        clean = {}
        for k, v in args.items():
            if isinstance(v, str):
                clean_v, _ = cls.sanitize_pii(v)
                clean[k] = clean_v
            elif isinstance(v, dict):
                clean[k] = cls.sanitize_arguments(v, depth=depth + 1)
            elif isinstance(v, list):
                clean_list = []
                for item in v:
                    if isinstance(item, str):
                        item_clean, _ = cls.sanitize_pii(item)
                        clean_list.append(item_clean)
                    elif isinstance(item, dict):
                        clean_list.append(cls.sanitize_arguments(item, depth=depth + 1))
                    else:
                        clean_list.append(item)
                clean[k] = clean_list
            else:
                clean[k] = v
        return clean

    @classmethod
    async def sanitize_arguments_async(cls, args: Dict[str, Any]) -> Dict[str, Any]:
        """Non-blocking async sanitization offloading regex processing to a worker thread."""
        return await asyncio.to_thread(cls.sanitize_arguments, args)
