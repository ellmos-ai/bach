# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Bach Adapter for Zero-Trust Model Armor (from SentinelFleet).

Intercepts prompt text and tool arguments across Bach services (chat, agent executor,
task runner) to prevent prompt injections, jailbreaks, and unintended PII exposure.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from .model_armor import ModelArmor, ArmorInspectionResult

logger = logging.getLogger("bach.model_armor")


class BachModelArmorGuard:
    """Synchronous & resilient guard for Bach agent inputs and tool execution."""

    @classmethod
    def inspect_prompt(cls, prompt_text: str) -> Tuple[bool, Optional[str]]:
        """
        Validates a prompt before passing it to any local or cloud LLM.
        Returns (is_safe, error_or_reason).
        """
        if not prompt_text:
            return True, None

        result: ArmorInspectionResult = ModelArmor.inspect_prompt(prompt_text)
        if not result.is_safe:
            patterns = ", ".join(result.blocked_patterns)
            logger.warning("Prompt blocked by ModelArmor: patterns=%s", patterns)
            return False, f"Prompt security check failed: blocked pattern(s) detected: {patterns}"

        return True, None

    @classmethod
    def inspect_tool_arguments(cls, tool_name: str, arguments: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Recursively inspects tool arguments before invoking a tool handler.
        """
        if not arguments:
            return True, None

        result: ArmorInspectionResult = ModelArmor.inspect_arguments(arguments)
        if not result.is_safe:
            patterns = ", ".join(result.blocked_patterns)
            logger.warning("Tool arguments for '%s' blocked by ModelArmor: %s", tool_name, patterns)
            return False, f"Tool argument security violation for '{tool_name}': {patterns}"

        return True, None

    @classmethod
    def sanitize_outgoing_text(cls, text: str) -> str:
        """Sanitizes PII (IBANs, API keys, credit cards) from text before export or external transfer."""
        if not text:
            return text
        sanitized, redacted = ModelArmor.sanitize_pii(text)
        if redacted:
            logger.info("Redacted sensitive PII items: %d item(s)", len(redacted))
        return sanitized
