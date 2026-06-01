#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM Client - Base class and factory for LLM clients
====================================================

Provides a unified interface for different LLM providers.
"""

from abc import ABC, abstractmethod
from typing import Iterator, Optional, Dict, Any


class LLMClient(ABC):
    """
    Abstract base class for LLM clients.

    All LLM providers implement this interface.
    """

    def __init__(self, model: str = ""):
        self.model = model
        self._is_available = False

    @property
    def is_available(self) -> bool:
        """Check if the LLM is available."""
        return self._is_available

    @abstractmethod
    def chat(self, prompt: str, context: str = "") -> str:
        """
        Send a chat message and get a response.

        Args:
            prompt: The user's message
            context: Optional system context

        Returns:
            The assistant's response
        """
        pass

    @abstractmethod
    def stream_chat(self, prompt: str, context: str = "") -> Iterator[str]:
        """
        Stream a chat response.

        Args:
            prompt: The user's message
            context: Optional system context

        Yields:
            Response chunks as they arrive
        """
        pass

    @abstractmethod
    def get_models(self) -> list:
        """
        Get available models.

        Returns:
            List of model names
        """
        pass

    def set_model(self, model: str):
        """Set the model to use."""
        self.model = model

    def count_tokens(self, text: str) -> int:
        """
        Estimate token count for text.

        This is a rough estimate - actual count varies by model.
        """
        # Rough estimate: ~4 characters per token for German/English
        return len(text) // 4


def create_llm_client(provider: str, model: str = "",
                      base_url: str = "", **kwargs) -> LLMClient:
    """
    Factory function to create LLM clients.

    Args:
        provider: The LLM provider (ollama, openai, anthropic)
        model: The model to use
        base_url: Server URL (only used for ollama)

    Returns:
        An LLMClient instance

    Raises:
        ValueError: If provider is not supported
    """
    provider = provider.lower()

    if provider == "ollama":
        from .ollama_client import OllamaClient
        url = base_url or OllamaClient.DEFAULT_URL
        return OllamaClient(model or "llama3", base_url=url, api_key=kwargs.get("api_key", ""))

    elif provider == "openai":
        from .openai_client import OpenAIClient
        return OpenAIClient(model or "gpt-4o-mini")

    elif provider == "anthropic":
        from .anthropic_client import AnthropicClient
        return AnthropicClient(model or "claude-3-haiku-20240307")

    elif provider == "claude-code":
        from .claude_code_client import ClaudeCodeClient
        mode = kwargs.get("claude_code_mode", "api")
        return ClaudeCodeClient(model or "sonnet", mode=mode)

    else:
        raise ValueError(f"Unsupported provider: {provider}. "
                        f"Supported: ollama, openai, anthropic, claude-code")
