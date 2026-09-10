#!/usr/bin/env python3
"""
Model-Backend-Abstraktion für BACH
===================================

Pluggbare LLM-Backends: Ollama (lokal), OpenAI-kompatibel, Anthropic.
Jeder User kann sein eigenes Backend konfigurieren.

Verwendung:
    from hub._services.llm.model_backend import OllamaBackend, OpenAIBackend

    backend = OllamaBackend(base_url='http://localhost:11434', default_model='qwen3.6:35b-mlx')
    result = await backend.chat(messages, tools=tools_list, think=True)
    # result = {'content': '...', 'tool_calls': [...] or None}
"""
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


def _probe_model_api(
    models_url: str,
    headers: dict[str, str],
    model: str | None,
    timeout: float,
) -> tuple[bool, str]:
    """Probe a model-list endpoint without returning credentials or provider text."""
    import httpx

    try:
        response = httpx.get(models_url, headers=headers, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        status_code = getattr(exc.response, "status_code", 0)
        if status_code in {401, 403}:
            return False, "Authentifizierung abgelehnt"
        return False, "Dienstfehler"
    except httpx.HTTPError:
        return False, "nicht erreichbar"
    except (TypeError, ValueError):
        return False, "ungültige Antwort"

    raw_models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(raw_models, list):
        return False, "ungültige Antwort"

    model_ids = {
        str(item.get("id") or item.get("name") or item.get("model") or "")
        for item in raw_models
        if isinstance(item, dict)
    }
    model_ids.discard("")
    if not model_ids:
        return False, "keine Modelle"

    selected_model = str(model or "").strip()
    if selected_model and selected_model not in model_ids:
        return False, f"Modell fehlt: {selected_model}"
    return True, "bereit"


class ModelBackend(ABC):
    """Abstrakte Basis für LLM-Backends."""

    @abstractmethod
    async def chat(self, messages: list, tools: list = None,
                   think: bool = True, model: str = None) -> dict:
        """Chat-Completion mit optionalem Tool-Use.

        Returns:
            {'content': str, 'tool_calls': list|None, 'raw_message': dict}
        """
        ...

    @abstractmethod
    def list_models(self) -> list[str]:
        ...

    @abstractmethod
    def get_default_model(self) -> str:
        ...

    def tool_response_message(self, content: str, tool_call_id: str = "") -> dict:
        """Erzeugt die korrekte Tool-Response-Nachricht für dieses Backend."""
        return {"role": "tool", "content": str(content)}

    def availability(
        self,
        model: str | None = None,
        timeout: float = 1.5,
    ) -> tuple[bool, str]:
        """Return a bounded, side-effect-light, fail-closed readiness result."""
        return False, "nicht prüfbar"


class OllamaBackend(ModelBackend):
    """Ollama API Backend für lokale Modelle (Qwen, Llama, Mistral, etc.)."""

    def __init__(self, base_url: str = "http://localhost:11434",
                 default_model: str = "qwen3.8:27b-mlx",
                 keep_alive: str = "5m",
                 num_ctx: int | None = None,
                 request_timeout: float | None = None):
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.keep_alive = keep_alive
        configured_num_ctx = num_ctx if num_ctx is not None else os.environ.get("OLLAMA_NUM_CTX", "4096")
        try:
            self.num_ctx = int(configured_num_ctx)
        except (TypeError, ValueError) as exc:
            raise ValueError("Ollama num_ctx muss eine ganze Zahl sein") from exc
        if not 512 <= self.num_ctx <= 262144:
            raise ValueError("Ollama num_ctx muss zwischen 512 und 262144 liegen")
        configured_timeout = (
            request_timeout
            if request_timeout is not None
            else os.environ.get("OLLAMA_TIMEOUT_SECONDS", "600")
        )
        try:
            self.request_timeout = float(configured_timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError("Ollama request_timeout muss eine Zahl sein") from exc
        if not 1 <= self.request_timeout <= 3600:
            raise ValueError("Ollama request_timeout muss zwischen 1 und 3600 Sekunden liegen")
        self._models_cache: list[str] = []
        self._models_cache_time: float = 0

    async def chat(self, messages, tools=None, think=True, model=None):
        import httpx
        try:
            from hub.compute_lock import get_effective_keep_alive
            effective_ka = get_effective_keep_alive(default=self.keep_alive)
        except ImportError:
            effective_ka = self.keep_alive
        payload = {
            "model": model or self.default_model,
            "messages": messages,
            "stream": False,
            "think": think,
            "keep_alive": effective_ka,
            # Einige Modelle veröffentlichen sehr große Trainingskontexte. Ohne
            # explizite Grenze kann Ollama dafür zig GiB KV-Cache reservieren.
            "options": {"num_ctx": self.num_ctx},
        }
        if tools:
            payload["tools"] = tools

        timeout = self.request_timeout * (1.5 if think else 1)
        async with httpx.AsyncClient() as client:
            try:
                r = await client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=timeout,
                )
            except httpx.TimeoutException as exc:
                raise RuntimeError(
                    f"Ollama-Zeitüberschreitung nach {timeout:g} Sekunden"
                ) from exc
            r.raise_for_status()
            resp = r.json()

        if resp.get("error"):
            raise RuntimeError(f"Ollama-Fehler: {resp['error']}")
        msg = resp.get("message", {})
        content = msg.get("content", "")
        if not think and "</think>" in content:
            content = content.rsplit("</think>", 1)[1].strip()
        tool_calls = msg.get("tool_calls")
        if not content and not tool_calls:
            raise RuntimeError("Ollama lieferte eine leere Antwort")
        return {
            "content": content,
            "tool_calls": tool_calls,
            "raw_message": msg,
        }

    def list_models(self) -> list[str]:
        if self._models_cache and (time.time() - self._models_cache_time) < 60:
            return self._models_cache
        import httpx
        r = httpx.get(f"{self.base_url}/api/tags", timeout=5)
        self._models_cache = [m["name"] for m in r.json().get("models", [])]
        self._models_cache_time = time.time()
        return self._models_cache

    def get_default_model(self) -> str:
        return self.default_model

    def availability(
        self,
        model: str | None = None,
        timeout: float = 1.5,
    ) -> tuple[bool, str]:
        import httpx

        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=timeout)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, TypeError, ValueError):
            return False, "nicht erreichbar"

        raw_models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(raw_models, list):
            return False, "ungültige Antwort"

        model_names = {
            str(item.get("name") or item.get("model") or "")
            for item in raw_models
            if isinstance(item, dict)
        }
        model_names.discard("")
        if not model_names:
            return False, "keine Modelle"

        selected_model = str(model or self.default_model or "").strip()
        if selected_model and selected_model not in model_names:
            return False, f"Modell fehlt: {selected_model}"
        return True, "bereit"

    def tool_response_message(self, content: str, tool_call_id: str = "") -> dict:
        return {"role": "tool", "content": str(content)}


class OpenAIBackend(ModelBackend):
    """OpenAI-kompatibles API Backend (OpenAI, Together, Groq, vLLM, etc.)."""

    def __init__(self, base_url: str = "https://api.openai.com/v1",
                 api_key: str = "", default_model: str = "gpt-4o"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.default_model = default_model
        self._last_tool_call_ids: list[str] = []

    async def chat(self, messages, tools=None, think=True, model=None):
        import httpx
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        headers["Content-Type"] = "application/json"

        payload: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=120,
            )
            resp = r.json()

        choice = resp.get("choices", [{}])[0]
        msg = choice.get("message", {})
        raw_tool_calls = msg.get("tool_calls")

        tool_calls = None
        if raw_tool_calls:
            self._last_tool_call_ids = [tc.get("id", "") for tc in raw_tool_calls]
            tool_calls = []
            for tc in raw_tool_calls:
                fn = tc.get("function", {})
                args = fn.get("arguments", "{}")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                tool_calls.append({"function": {"name": fn.get("name", ""), "arguments": args}})

        return {
            "content": msg.get("content", "") or "",
            "tool_calls": tool_calls,
            "raw_message": msg,
        }

    def list_models(self) -> list[str]:
        import httpx
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            r = httpx.get(f"{self.base_url}/models", headers=headers, timeout=5)
            return [m["id"] for m in r.json().get("data", [])]
        except Exception:
            return []

    def get_default_model(self) -> str:
        return self.default_model

    def availability(
        self,
        model: str | None = None,
        timeout: float = 1.5,
    ) -> tuple[bool, str]:
        api_key = str(self.api_key or "").strip()
        if not api_key:
            return False, "Key fehlt"
        return _probe_model_api(
            f"{self.base_url}/models",
            {"Authorization": f"Bearer {api_key}"},
            model or self.default_model,
            timeout,
        )

    def tool_response_message(self, content: str, tool_call_id: str = "") -> dict:
        msg = {"role": "tool", "content": str(content)}
        if tool_call_id:
            msg["tool_call_id"] = tool_call_id
        return msg


class LMStudioBackend(OpenAIBackend):
    """LM Studio Backend für lokale Modelle via OpenAI-kompatibles API (Port 1234).

    Standardmäßig erreichbar unter http://localhost:1234/v1.
    Unterstützt automatische Modell-Erkennung geladener Modelle über /v1/models.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:1234/v1",
        api_key: str = "lm-studio",
        default_model: str = "auto",
    ):
        super().__init__(
            base_url=base_url,
            api_key=api_key or "lm-studio",
            default_model=default_model,
        )
        self._models_cache: list[str] = []
        self._models_cache_time: float = 0

    def list_models(self) -> list[str]:
        if self._models_cache and (time.time() - self._models_cache_time) < 30:
            return self._models_cache
        import httpx

        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            r = httpx.get(f"{self.base_url}/models", headers=headers, timeout=5)
            r.raise_for_status()
            data = r.json().get("data", [])
            models = [
                str(m.get("id") or m.get("model") or m.get("name") or "")
                for m in data
                if isinstance(m, dict)
            ]
            self._models_cache = [m for m in models if m]
            self._models_cache_time = time.time()
        except Exception:
            return self._models_cache or []
        return self._models_cache

    def get_default_model(self) -> str:
        if self.default_model and self.default_model.lower() not in ("auto", "default"):
            return self.default_model
        models = self.list_models()
        if models:
            return models[0]
        return self.default_model or "auto"

    async def chat(self, messages, tools=None, think=True, model=None):
        target_model = model
        if not target_model:
            target_model = self.get_default_model()
            if target_model.lower() in ("auto", "default", ""):
                target_model = "local-model"
        return await super().chat(
            messages=messages, tools=tools, think=think, model=target_model
        )

    def availability(
        self,
        model: str | None = None,
        timeout: float = 1.5,
    ) -> tuple[bool, str]:
        import httpx

        # Fast non-blocking socket probe on local address when unmocked
        # to prevent Windows WSAConnect 2s+ delays when server is offline
        if getattr(httpx.get, "__module__", "").startswith("httpx"):
            import socket
            from urllib.parse import urlparse

            try:
                parsed = urlparse(self.base_url)
                host = parsed.hostname or "127.0.0.1"
                port = parsed.port or 1234
                if host in ("localhost", "127.0.0.1", "::1"):
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(min(timeout, 0.2))
                    try:
                        sock.connect(("127.0.0.1", port))
                    except Exception:
                        return False, "nicht erreichbar"
                    finally:
                        sock.close()
            except Exception:
                pass

        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        target_model = model or self.default_model
        probe_model = (
            None
            if (not target_model or target_model.lower() in ("auto", "default"))
            else target_model
        )
        return _probe_model_api(
            f"{self.base_url}/models",
            headers,
            probe_model,
            timeout,
        )


class HermesBackend(OpenAIBackend):
    """Nous Hermes API Backend für lokale und Cloud-Modelle (OpenRouter, Together, vLLM, Ollama).

    Unterstützt:
    - Standard OpenAI Function Calling
    - Automatisches Fallback-Parsing für Hermes <tool_call> XML-Tags im Text-Stream
    - Automatisches Extrahieren / Trennen von <thought> bzw. <reasoning> Tags
    - OpenRouter Default-Endpunkt (https://openrouter.ai/api/v1) mit Model nousresearch/hermes-3-llama-3.1-8b
    """

    HERMES_TOOL_REGEX = re.compile(
        r"<tool_call>\s*({.*?})\s*</tool_call>", re.DOTALL
    )
    HERMES_THOUGHT_REGEX = re.compile(
        r"<thought>(.*?)</thought>", re.DOTALL | re.IGNORECASE
    )

    def __init__(
        self,
        base_url: str = "https://openrouter.ai/api/v1",
        api_key: str = "",
        default_model: str = "nousresearch/hermes-3-llama-3.1-8b",
        site_url: str = "https://github.com/ellmos-ai/bach",
        app_name: str = "BACH Agent",
    ):
        super().__init__(
            base_url=base_url or "https://openrouter.ai/api/v1",
            api_key=api_key
            or os.environ.get("OPENROUTER_API_KEY", "")
            or os.environ.get("HERMES_API_KEY", ""),
            default_model=default_model or "nousresearch/hermes-3-llama-3.1-8b",
        )
        self.site_url = site_url
        self.app_name = app_name

    def _get_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if "openrouter.ai" in self.base_url:
            headers["HTTP-Referer"] = self.site_url
            headers["X-Title"] = self.app_name
        return headers

    async def chat(self, messages, tools=None, think=True, model=None):
        import httpx

        headers = self._get_headers()
        payload: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=120,
            )
            r.raise_for_status()
            data = r.json()

        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        raw_content = msg.get("content", "") or ""

        tool_calls = []
        # 1. Native OpenAI-style tool calls
        if "tool_calls" in msg and msg["tool_calls"]:
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                args = fn.get("arguments", "{}")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        pass
                tool_calls.append(
                    {
                        "id": tc.get("id", ""),
                        "function": {"name": fn.get("name", ""), "arguments": args},
                    }
                )

        # 2. Hermes XML <tool_call> fallback
        cleaned_content = raw_content
        if not tool_calls and "<tool_call>" in raw_content:
            matches = self.HERMES_TOOL_REGEX.findall(raw_content)
            for idx, raw_json in enumerate(matches):
                try:
                    parsed = json.loads(raw_json)
                    fn_name = parsed.get("name", "")
                    fn_args = parsed.get("arguments", {})
                    if fn_name:
                        tool_calls.append(
                            {
                                "id": f"hermes_call_{idx}_{int(time.time())}",
                                "function": {"name": fn_name, "arguments": fn_args},
                            }
                        )
                except Exception:
                    pass
            cleaned_content = self.HERMES_TOOL_REGEX.sub("", cleaned_content).strip()

        # 3. Hermes <thought> Tag Handling
        thought_content = ""
        thought_match = self.HERMES_THOUGHT_REGEX.search(cleaned_content)
        if thought_match:
            thought_content = thought_match.group(1).strip()
            if not think:
                cleaned_content = self.HERMES_THOUGHT_REGEX.sub("", cleaned_content).strip()

        res_msg = dict(msg)
        if thought_content:
            res_msg["thought"] = thought_content

        return {
            "content": cleaned_content,
            "tool_calls": tool_calls or None,
            "raw_message": res_msg,
        }

    def availability(
        self,
        model: str | None = None,
        timeout: float = 1.5,
    ) -> tuple[bool, str]:
        import httpx

        if getattr(httpx.get, "__module__", "").startswith("httpx"):
            import socket
            from urllib.parse import urlparse

            try:
                parsed = urlparse(self.base_url)
                host = parsed.hostname or "127.0.0.1"
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                if host in ("localhost", "127.0.0.1", "::1"):
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(min(timeout, 0.2))
                    try:
                        sock.connect(("127.0.0.1", port))
                    except Exception:
                        return False, "nicht erreichbar"
                    finally:
                        sock.close()
            except Exception:
                pass

        headers = self._get_headers()
        return _probe_model_api(
            f"{self.base_url}/models",
            headers,
            model or self.default_model,
            timeout,
        )


class AnthropicBackend(ModelBackend):
    """Anthropic Claude API Backend."""

    def __init__(self, api_key: str = "", default_model: str = "claude-sonnet-4-6"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.default_model = default_model
        self.base_url = "https://api.anthropic.com/v1"

    async def chat(self, messages, tools=None, think=True, model=None):
        import httpx
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        system_msg = ""
        chat_msgs = []
        for m in messages:
            if m.get("role") == "system":
                system_msg = m.get("content", "")
            else:
                chat_msgs.append({"role": m["role"], "content": m.get("content", "")})

        payload: dict[str, Any] = {
            "model": model or self.default_model,
            "max_tokens": 4096,
            "messages": chat_msgs,
        }
        if system_msg:
            payload["system"] = system_msg
        if tools:
            anthropic_tools = []
            for t in tools:
                fn = t.get("function", {})
                anthropic_tools.append({
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                })
            payload["tools"] = anthropic_tools

        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{self.base_url}/messages",
                json=payload,
                headers=headers,
                timeout=120,
            )
            resp = r.json()

        content_blocks = resp.get("content", [])
        text_parts = []
        tool_calls = []
        for block in content_blocks:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "function": {
                        "name": block["name"],
                        "arguments": block.get("input", {}),
                    }
                })

        return {
            "content": "\n".join(text_parts),
            "tool_calls": tool_calls if tool_calls else None,
            "raw_message": resp,
        }

    def list_models(self) -> list[str]:
        return [self.default_model]

    def get_default_model(self) -> str:
        return self.default_model

    def availability(
        self,
        model: str | None = None,
        timeout: float = 1.5,
    ) -> tuple[bool, str]:
        api_key = str(self.api_key or "").strip()
        if not api_key:
            return False, "Key fehlt"
        return _probe_model_api(
            f"{self.base_url}/models",
            {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            model or self.default_model,
            timeout,
        )

    def tool_response_message(self, content: str, tool_call_id: str = "") -> dict:
        return {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tool_call_id, "content": str(content)}
        ]}


class CLIBackend(ModelBackend):
    """Backend für CLI-basierte Agenten (Claude Code, Codex).

    Nutzt eine Hintergrund-CLI-Session mit --continue für Kontext-Erhalt.
    Die CLI verwaltet ihre eigenen Tools — kein externer Tool-Loop nötig.
    """

    manages_own_tools = True

    KNOWN_CLIS = {
        "claude": {
            "cmd_template": ["{path}", "-p", "--output-format", "text",
                             "--model", "{model}"],
            "continue_flag": "--continue",
            "models": ["sonnet", "opus", "haiku",
                       "claude-sonnet-4-6", "claude-opus-4-6"],
            "search_names": ["claude", "claude.exe", "claude.cmd"],
            "readiness_args": ["auth", "status"],
        },
        "codex": {
            "cmd_template": ["{path}", "--quiet", "--model", "{model}",
                             "--approval-mode", "auto-edit"],
            "continue_flag": None,
            "models": ["gpt-4o", "o4-mini", "o3"],
            "search_names": ["codex", "codex.exe", "codex.cmd"],
            "readiness_args": ["login", "status"],
        },
    }

    def __init__(self, cli_name: str = "claude", cli_path: str = "",
                 default_model: str = "", cwd: str = "",
                 permission_mode: str = "restricted",
                 allowed_tools: str = "Read,Grep,Glob,Bash,WebFetch,WebSearch",
                 max_turns: int = 30, timeout: int = 0):
        self.cli_name = cli_name
        self.cli_path = cli_path or self._find_cli(cli_name)
        preset = self.KNOWN_CLIS.get(cli_name, self.KNOWN_CLIS["claude"])
        self.default_model = default_model or (
            preset["models"][0] if preset["models"] else "sonnet"
        )
        self.cwd = cwd or str(Path.home())
        self.permission_mode = permission_mode
        self.allowed_tools = allowed_tools
        self.max_turns = max_turns
        self.timeout = timeout
        self._session_active = False

    def _find_cli(self, cli_name: str) -> str:
        preset = self.KNOWN_CLIS.get(cli_name, {})
        for name in preset.get("search_names", [cli_name]):
            found = shutil.which(name)
            if found:
                return found
        candidates = []
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA", "")
            if appdata:
                candidates.append(str(Path(appdata) / "npm" / f"{cli_name}.cmd"))
            localappdata = os.environ.get("LOCALAPPDATA", "")
            if localappdata:
                for p in Path(localappdata).glob(
                    f"Microsoft/WinGet/Packages/Anthropic*/**/{cli_name}.exe"
                ):
                    candidates.append(str(p))
        else:
            candidates.extend([
                f"/usr/local/bin/{cli_name}",
                str(Path.home() / ".local" / "bin" / cli_name),
            ])
        for c in candidates:
            if Path(c).exists():
                return c
        return cli_name

    async def chat(self, messages, tools=None, think=True, model=None):
        prompt = self._messages_to_prompt(messages)
        response = await self._run_cli(prompt, model=model)
        return {
            "content": response,
            "tool_calls": None,
            "raw_message": {"content": response},
        }

    def _messages_to_prompt(self, messages: list) -> str:
        parts = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if not content:
                continue
            if role == "system":
                parts.append(f"[System]\n{content}")
            elif role == "user":
                parts.append(content)
            elif role == "assistant":
                parts.append(f"[Vorherige Antwort]\n{content}")
        return "\n\n".join(parts)

    async def _run_cli(self, prompt: str, model: str = None) -> str:
        model = model or self.default_model
        preset = self.KNOWN_CLIS.get(self.cli_name, self.KNOWN_CLIS["claude"])

        cmd = []
        for part in preset["cmd_template"]:
            cmd.append(part.replace("{path}", self.cli_path).replace("{model}", model))

        if self.max_turns > 0 and self.cli_name == "claude":
            cmd += ["--max-turns", str(self.max_turns)]

        if self._session_active and preset.get("continue_flag"):
            cmd.append(preset["continue_flag"])

        if self.cli_name == "claude":
            if self.permission_mode == "full":
                cmd.append("--dangerously-skip-permissions")
            else:
                cmd += ["--allowedTools", self.allowed_tools]

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        creation_flags = 0x08000000 if sys.platform == "win32" else 0

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, lambda: self._run_subprocess(cmd, prompt, env, creation_flags)
        )

        if response and not response.startswith("Fehler:"):
            self._session_active = True

        return response

    def _run_subprocess(self, cmd: list, prompt: str, env: dict,
                        creation_flags: int) -> str:
        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=env, cwd=self.cwd,
                creationflags=creation_flags,
            )
            if proc.poll() is not None:
                stderr = proc.stderr.read().decode("utf-8", errors="replace")[:500]
                return f"Fehler: CLI beendet (exit={proc.returncode}). {stderr}"

            try:
                proc.stdin.write(prompt.encode("utf-8"))
                proc.stdin.close()
            except BrokenPipeError:
                stderr = proc.stderr.read().decode("utf-8", errors="replace")[:500]
                return f"Fehler: Broken pipe. {stderr}"

            stdout_data = []
            last_activity = time.time()
            inactivity_timeout = self.timeout if self.timeout > 0 else 300

            while True:
                try:
                    chunk = proc.stdout.read(4096)
                    if not chunk:
                        break
                    stdout_data.append(chunk)
                    last_activity = time.time()
                except Exception:
                    break
                if time.time() - last_activity > inactivity_timeout:
                    proc.kill()
                    return "Fehler: Inaktivitäts-Timeout"

            proc.wait(timeout=10)
            result = b"".join(stdout_data).decode("utf-8", errors="replace").strip()

            if proc.returncode != 0 and not result:
                stderr = proc.stderr.read().decode("utf-8", errors="replace")[:1000]
                return f"Fehler: CLI exit {proc.returncode}. {stderr}"

            return result or "(keine Antwort)"

        except FileNotFoundError:
            return f"Fehler: CLI '{cmd[0]}' nicht gefunden. Installieren?"
        except subprocess.TimeoutExpired:
            proc.kill()
            return "Fehler: Timeout"
        except Exception as e:
            return f"Fehler: {e}"

    def list_models(self) -> list[str]:
        preset = self.KNOWN_CLIS.get(self.cli_name, {})
        return preset.get("models", [self.default_model])

    def get_default_model(self) -> str:
        return self.default_model

    def availability(
        self,
        model: str | None = None,
        timeout: float = 1.5,
    ) -> tuple[bool, str]:
        del model
        cli_path = str(self.cli_path or "").strip()
        resolved_path = cli_path if Path(cli_path).is_file() else shutil.which(cli_path)
        if not cli_path or not resolved_path:
            return False, "nicht gefunden"

        readiness_args = self.KNOWN_CLIS.get(self.cli_name, {}).get("readiness_args")
        if not readiness_args:
            return False, "Prüfung nicht unterstützt"

        try:
            probe_timeout = max(0.1, float(timeout))
        except (TypeError, ValueError):
            return False, "Prüfung fehlgeschlagen"

        creation_flags = 0x08000000 if sys.platform == "win32" else 0
        try:
            result = subprocess.run(
                [str(resolved_path), *readiness_args],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=probe_timeout,
                check=False,
                creationflags=creation_flags,
            )
        except subprocess.TimeoutExpired:
            return False, "Prüfung Zeitüberschreitung"
        except OSError:
            return False, "nicht ausführbar"

        if result.returncode != 0:
            return False, "Anmeldung nicht bestätigt"
        return True, "bereit"

    def reset_session(self):
        self._session_active = False


def backend_identifier(backend: ModelBackend) -> str:
    """Stable Control-API key for a concrete backend instance."""
    if isinstance(backend, LMStudioBackend):
        return "lmstudio"
    if isinstance(backend, HermesBackend):
        return "hermes"
    if isinstance(backend, OllamaBackend):
        return "ollama"
    if isinstance(backend, CLIBackend):
        return backend.cli_name if backend.cli_name in {"claude", "codex"} else ""
    if isinstance(backend, AnthropicBackend):
        return "claude-api"
    if isinstance(backend, OpenAIBackend):
        return "openai"
    return ""


def create_backend(config: dict) -> ModelBackend:
    """Factory: Backend aus Config-Dict erzeugen.

    config = {
        'type': 'ollama' | 'lmstudio' | 'hermes' | 'openai' | 'anthropic' | 'claude-cli' | 'codex-cli',
        'base_url': '...',       # optional (API backends)
        'api_key': '...',        # optional (API backends)
        'cli_path': '...',       # optional (CLI backends)
        'default_model': '...',  # optional
        'permission_mode': '...',  # optional (CLI backends: restricted/full)
    }
    """
    backend_type = config.get("type", "ollama").lower()

    if backend_type == "ollama":
        return OllamaBackend(
            base_url=config.get("base_url", "http://localhost:11434"),
            default_model=config.get("default_model", "qwen3.8:27b-mlx"),
            num_ctx=config.get("num_ctx"),
            request_timeout=config.get("timeout_seconds"),
        )
    elif backend_type in ("lmstudio", "lm-studio", "lm_studio"):
        return LMStudioBackend(
            base_url=config.get("base_url", "http://localhost:1234/v1"),
            api_key=config.get("api_key", "lm-studio"),
            default_model=config.get("default_model", "auto"),
        )
    elif backend_type in ("hermes", "hermes-agent", "nous-hermes", "openrouter"):
        return HermesBackend(
            base_url=config.get("base_url", "https://openrouter.ai/api/v1"),
            api_key=config.get("api_key", ""),
            default_model=config.get("default_model", "nousresearch/hermes-3-llama-3.1-8b"),
        )
    elif backend_type in ("openai", "openai_compat", "openai-api"):
        return OpenAIBackend(
            base_url=config.get("base_url", "https://api.openai.com/v1"),
            api_key=config.get("api_key", ""),
            default_model=config.get("default_model", "gpt-4o"),
        )
    elif backend_type in ("anthropic", "claude-api"):
        return AnthropicBackend(
            api_key=config.get("api_key", ""),
            default_model=config.get("default_model", "claude-sonnet-4-6"),
        )
    elif backend_type in ("claude", "claude-cli"):
        return CLIBackend(
            cli_name="claude",
            cli_path=config.get("cli_path", ""),
            default_model=config.get("default_model", "sonnet"),
            cwd=config.get("cwd", ""),
            permission_mode=config.get("permission_mode", "restricted"),
            allowed_tools=config.get("allowed_tools",
                                     "Read,Grep,Glob,Bash,WebFetch,WebSearch"),
            max_turns=int(config.get("max_turns", 30)),
        )
    elif backend_type in ("codex", "codex-cli"):
        return CLIBackend(
            cli_name="codex",
            cli_path=config.get("cli_path", ""),
            default_model=config.get("default_model", "o4-mini"),
            cwd=config.get("cwd", ""),
        )
    else:
        raise ValueError(f"Unbekannter Backend-Typ: {backend_type}")
