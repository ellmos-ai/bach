#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenAI Client - OpenAI API Integration
=======================================

Connects to OpenAI's API for GPT models.
"""

import json
import os
from typing import Iterator, Optional
import urllib.request
import urllib.error

from .client import LLMClient


class OpenAIClient(LLMClient):
    """
    Client for OpenAI API.

    Requires OPENAI_API_KEY environment variable.
    """

    API_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self, model: str = "gpt-4o-mini", api_key: Optional[str] = None):
        """
        Initialize the OpenAI client.

        Args:
            model: The model to use (gpt-4, gpt-4o-mini, gpt-3.5-turbo, etc.)
            api_key: API key (falls back to OPENAI_API_KEY env var)
        """
        super().__init__(model)
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._is_available = bool(self.api_key)

    def chat(self, prompt: str, context: str = "") -> str:
        """Send a chat message and get a response."""
        if not self._is_available:
            raise ConnectionError("OpenAI API key not configured")

        messages = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": prompt})

        data = {
            "model": self.model,
            "messages": messages,
            "stream": False
        }

        req = urllib.request.Request(
            self.API_URL,
            data=json.dumps(data).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                result = json.loads(response.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            raise ConnectionError(f"OpenAI API error: {e.code} - {error_body}")

    def stream_chat(self, prompt: str, context: str = "") -> Iterator[str]:
        """Stream a chat response."""
        if not self._is_available:
            raise ConnectionError("OpenAI API key not configured")

        messages = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": prompt})

        data = {
            "model": self.model,
            "messages": messages,
            "stream": True
        }

        req = urllib.request.Request(
            self.API_URL,
            data=json.dumps(data).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                for line in response:
                    line = line.decode("utf-8").strip()
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            pass

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            raise ConnectionError(f"OpenAI API error: {e.code} - {error_body}")

    def get_models(self) -> list:
        """Get available models from OpenAI."""
        # Return common models - OpenAI doesn't have a good list endpoint
        return [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "gpt-4",
            "gpt-3.5-turbo"
        ]

    def count_tokens(self, text: str) -> int:
        """
        Estimate token count for OpenAI models.

        More accurate than base class for OpenAI's tokenizer.
        """
        # Try to use tiktoken if available
        try:
            import tiktoken
            enc = tiktoken.encoding_for_model(self.model)
            return len(enc.encode(text))
        except ImportError:
            # Fall back to rough estimate
            return len(text) // 4
