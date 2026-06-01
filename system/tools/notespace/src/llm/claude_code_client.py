#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claude Code Client - LLM via Claude Code CLI (subprocess)
==========================================================

Zwei Modi:
1. API-Like-Modus: Claude Code im Hintergrund, Ergebnis zurück
2. Chat-Modus: Konsole öffnet sich, Nutzer kann weiter chatten

Voraussetzung: `claude` CLI muss im PATH sein.
"""

import json
import re
import shutil
import subprocess
import tempfile
import threading
import logging
from pathlib import Path
from typing import Iterator, Optional, Callable

from .client import LLMClient

logger = logging.getLogger(__name__)


class ClaudeCodeClient(LLMClient):
    """
    LLM Client der Claude Code CLI als Backend nutzt.

    Modi:
    - "api": Hintergrund-Ausführung, Ergebnis wird zurückgegeben
    - "chat": Konsole öffnet sich für interaktives Chatten
    """

    CLAUDE_CMD = "claude"  # muss im PATH sein
    ALLOWED_MODELS = {"sonnet", "opus", "haiku"}

    def __init__(self, model: str = "sonnet", mode: str = "api"):
        """
        Args:
            model: Claude-Modell (sonnet, opus, haiku)
            mode: "api" (Hintergrund) oder "chat" (Konsole öffnet sich)
        """
        if model not in self.ALLOWED_MODELS:
            raise ValueError(f"Unbekanntes Modell: {model!r}. Erlaubt: {self.ALLOWED_MODELS}")
        super().__init__(model)
        self.mode = mode
        self._check_availability()

    def _check_availability(self):
        """Prüfen ob claude CLI verfügbar ist."""
        self._is_available = shutil.which(self.CLAUDE_CMD) is not None
        if not self._is_available:
            logger.warning("Claude Code CLI nicht gefunden. Bitte installieren: npm install -g @anthropic-ai/claude-code")

    def chat(self, prompt: str, context: str = "") -> str:
        """
        Sende Prompt an Claude Code und erhalte Antwort.

        Im API-Modus: Hintergrund-Ausführung mit --print Flag.
        Im Chat-Modus: öffnet Konsole, gibt leeren String zurück.
        """
        if not self._is_available:
            raise ConnectionError("Claude Code CLI nicht verfügbar")

        if self.mode == "chat":
            self._open_chat_console(prompt, context)
            return "(Chat-Modus: Konsole wurde geöffnet)"

        return self._api_call(prompt, context)

    def stream_chat(self, prompt: str, context: str = "") -> Iterator[str]:
        """Streaming-Antwort von Claude Code."""
        if not self._is_available:
            raise ConnectionError("Claude Code CLI nicht verfügbar")

        if self.mode == "chat":
            self._open_chat_console(prompt, context)
            yield "(Chat-Modus: Konsole wurde geöffnet)"
            return

        # API-Modus mit Streaming
        full_prompt = self._build_prompt(prompt, context)

        cmd = [self.CLAUDE_CMD, "--print", "--model", self.model]

        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )

            # Prompt via stdin senden
            process.stdin.write(full_prompt)
            process.stdin.close()

            # Stdout zeilenweise lesen
            for line in process.stdout:
                yield line

            process.wait()

            if process.returncode != 0:
                stderr = process.stderr.read()
                if stderr.strip():
                    logger.error(f"Claude Code stderr: {stderr}")

        except Exception as e:
            logger.error(f"Claude Code Stream-Fehler: {e}")
            yield f"\n[Fehler: {e}]"

    def get_models(self) -> list:
        """Verfügbare Claude-Modelle."""
        return ["sonnet", "opus", "haiku"]

    def _build_prompt(self, prompt: str, context: str) -> str:
        """Baut den vollständigen Prompt zusammen."""
        if context:
            return f"{context}\n\n{prompt}"
        return prompt

    def _api_call(self, prompt: str, context: str) -> str:
        """Hintergrund-Aufruf mit --print Flag."""
        full_prompt = self._build_prompt(prompt, context)

        cmd = [self.CLAUDE_CMD, "--print", "--model", self.model]

        try:
            result = subprocess.run(
                cmd,
                input=full_prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=600,  # 10 Minuten Timeout
            )

            if result.returncode == 0:
                return result.stdout.strip()
            else:
                error = result.stderr.strip() or "Unbekannter Fehler"
                logger.error(f"Claude Code Fehler: {error}")
                raise RuntimeError(f"Claude Code: {error}")

        except subprocess.TimeoutExpired:
            raise RuntimeError("Claude Code: Timeout nach 10 Minuten")

    def _open_chat_console(self, prompt: str, context: str):
        """öffnet eine Konsole mit Claude Code im Chat-Modus."""
        # Prompt-Datei erstellen (wird von Claude Code gelesen)
        prompt_file = self._create_prompt_file(prompt, context)

        # Konsole öffnen mit initialem Prompt
        import sys

        # Defense-in-depth: Model-String sanitizen bevor er in Shell-Code eingebettet wird
        safe_model = re.sub(r'[^a-zA-Z0-9._-]', '', self.model)

        if sys.platform == "win32":
            # Windows: start cmd mit claude Befehl
            # Der Prompt wird via stdin-Pipe an claude gesendet
            bat_content = f'''@echo off
chcp 65001 >nul
echo === NoteSpaceLLM Chat-Modus ===
echo Prompt-Datei: {prompt_file}
echo ================================
echo.
type "{prompt_file}"
echo.
echo ================================
echo Claude Code wird gestartet...
echo.
claude --model {safe_model} --resume < "{prompt_file}"
echo.
pause
'''
            bat_file = Path(tempfile.gettempdir()) / "notespacellm_chat.bat"
            bat_file.write_text(bat_content, encoding="utf-8")
            subprocess.Popen(
                ["cmd", "/c", "start", "cmd", "/k", str(bat_file)],
            )
        else:
            # Linux/Mac
            subprocess.Popen(
                ["x-terminal-emulator", "-e", "bash", "-c",
                 f'cat "{prompt_file}" | claude --model {safe_model} --resume; exec bash'],
            )

        logger.info(f"Chat-Konsole geöffnet mit Prompt-Datei: {prompt_file}")

    def _create_prompt_file(self, prompt: str, context: str) -> Path:
        """Erstellt eine Prompt-Datei für den Chat-Modus."""
        full_prompt = self._build_prompt(prompt, context)

        prompt_dir = Path(tempfile.gettempdir()) / "notespacellm_prompts"
        prompt_dir.mkdir(exist_ok=True)

        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        prompt_file = prompt_dir / f"prompt_{timestamp}.md"
        prompt_file.write_text(full_prompt, encoding="utf-8")

        return prompt_file

    @staticmethod
    def export_prompt(prompt: str, context: str, output_path: Path) -> Path:
        """
        Exportiert den Prompt als .md Datei.

        Args:
            prompt: Die Aufgabe/Frage
            context: Dokumenten-Kontext
            output_path: Speicherpfad

        Returns:
            Pfad zur gespeicherten Datei
        """
        content = f"""# NoteSpaceLLM - Analyse-Prompt

## Aufgabe

{prompt}

## Dokumenten-Kontext

{context}
"""
        output_path.write_text(content, encoding="utf-8")
        logger.info(f"Prompt exportiert: {output_path}")
        return output_path
