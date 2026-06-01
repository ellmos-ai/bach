#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anthropic Client - Claude API Integration
==========================================

Connects to Anthropic's API for Claude models.
"""

import json
import os
from typing import Iterator, Optional
import urllib.request
import urllib.error

from .client import LLMClient


class AnthropicClient(LLMClient):
    """
    Client for Anthropic's Claude API.

    Requires ANTHROPIC_API_KEY environment variable.
    """

    API_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"

    def __init__(self, model: str = "claude-3-haiku-20240307", api_key: Optional[str] = None):
        """
        Initialize the Anthropic client.

        Args:
            model: The model to use (claude-3-opus, claude-3-sonnet, claude-3-haiku, etc.)
            api_key: API key (falls back to ANTHROPIC_API_KEY env var)
        """
        super().__init__(model)
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._is_available = bool(self.api_key)

    def chat(self, prompt: str, context: str = "") -> str:
        """Send a chat message and get a response."""
        if not self._is_available:
            raise ConnectionError("Anthropic API key not configured")

        data = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}]
        }

        if context:
            data["system"] = context

        req = urllib.request.Request(
            self.API_URL,
            data=json.dumps(data).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": self.API_VERSION
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                result = json.loads(response.read().decode("utf-8"))
                content_blocks = result.get("content", [])
                text_blocks = [b["text"] for b in content_blocks if b["type"] == "text"]
                return "".join(text_blocks)

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            raise ConnectionError(f"Anthropic API error: {e.code} - {error_body}")

    def stream_chat(self, prompt: str, context: str = "") -> Iterator[str]:
        """Stream a chat response."""
        if not self._is_available:
            raise ConnectionError("Anthropic API key not configured")

        data = {
            "model": self.model,
            "max_tokens": 4096,
            "stream": True,
            "messages": [{"role": "user", "content": prompt}]
        }

        if context:
            data["system"] = context

        req = urllib.request.Request(
            self.API_URL,
            data=json.dumps(data).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": self.API_VERSION
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                for line in response:
                    line = line.decode("utf-8").strip()

                    if not line or line.startswith(":"):
                        continue

                    if line.startswith("data: "):
                        data_str = line[6:]
                        try:
                            event = json.loads(data_str)
                            event_type = event.get("type", "")

                            if event_type == "content_block_delta":
                                delta = event.get("delta", {})
                                if delta.get("type") == "text_delta":
                                    text = delta.get("text", "")
                                    if text:
                                        yield text

                            elif event_type == "message_stop":
                                break

                        except json.JSONDecodeError:
                            pass

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            raise ConnectionError(f"Anthropic API error: {e.code} - {error_body}")

    def get_models(self) -> list:
        """Get available Claude models."""
        return [
            "claude-3-5-sonnet-20241022",
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307"
        ]

    def count_tokens(self, text: str) -> int:
        """
        Estimate token count for Claude.

        Claude uses a similar tokenizer to GPT models.
        """
        # Rough estimate
        return len(text) // 4
