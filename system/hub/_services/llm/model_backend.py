#!/usr/bin/env python3
"""
Model-Backend-Abstraktion für BACH
===================================

Pluggbare LLM-Backends: Ollama (lokal), OpenAI-kompatibel, Anthropic.
Jeder User kann sein eigenes Backend konfigurieren.

Verwendung:
    from hub._services.llm.model_backend import OllamaBackend, OpenAIBackend

    backend = OllamaBackend(base_url='http://localhost:11434', default_model='qwen3.5:35b-a3b')
    result = await backend.chat(messages, tools=tools_list, think=True)
    # result = {'content': '...', 'tool_calls': [...] or None}
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional


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


class OllamaBackend(ModelBackend):
    """Ollama API Backend für lokale Modelle (Qwen, Llama, Mistral, etc.)."""

    def __init__(self, base_url: str = "http://localhost:11434",
                 default_model: str = "qwen3.5:35b-a3b"):
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self._models_cache: list[str] = []
        self._models_cache_time: float = 0

    async def chat(self, messages, tools=None, think=True, model=None):
        import httpx
        payload = {
            "model": model or self.default_model,
            "messages": messages,
            "stream": False,
            "think": think,
        }
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=180 if think else 120,
            )
            resp = r.json()

        msg = resp.get("message", {})
        return {
            "content": msg.get("content", ""),
            "tool_calls": msg.get("tool_calls"),
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

    def tool_response_message(self, content: str, tool_call_id: str = "") -> dict:
        msg = {"role": "tool", "content": str(content)}
        if tool_call_id:
            msg["tool_call_id"] = tool_call_id
        return msg


class AnthropicBackend(ModelBackend):
    """Anthropic Claude API Backend."""

    def __init__(self, api_key: str = "", default_model: str = "claude-sonnet-4-20250514"):
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
                       "claude-sonnet-4-20250514", "claude-opus-4-20250514"],
            "search_names": ["claude", "claude.exe", "claude.cmd"],
        },
        "codex": {
            "cmd_template": ["{path}", "--quiet", "--model", "{model}",
                             "--approval-mode", "auto-edit"],
            "continue_flag": None,
            "models": ["gpt-4o", "o4-mini", "o3"],
            "search_names": ["codex", "codex.exe", "codex.cmd"],
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

    def reset_session(self):
        self._session_active = False


def create_backend(config: dict) -> ModelBackend:
    """Factory: Backend aus Config-Dict erzeugen.

    config = {
        'type': 'ollama' | 'openai' | 'anthropic' | 'claude-cli' | 'codex-cli',
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
            default_model=config.get("default_model", "qwen3.5:35b-a3b"),
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
            default_model=config.get("default_model", "claude-sonnet-4-20250514"),
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
