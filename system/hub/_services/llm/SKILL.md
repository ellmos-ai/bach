---
name: llm-model-backend
version: 1.0.0
type: service
author: BACH Team
created: 2026-09-17
updated: 2026-09-17
anthropic_compatible: true
status: active

dependencies:
  tools: [httpx (Modell-Probe), asyncio]
  services: []
  workflows: []

description: >
  Pluggbare LLM-Backend-Abstraktion. Jeder User kann sein eigenes
  Backend konfigurieren: Ollama (lokal), OpenAI-kompatibel, LM Studio,
  Hermes, Anthropic oder CLI-basiert. Einheitliche chat()-Schnittstelle
  mit Tool-Calling und Think-Modus.
---

# LLM Model-Backend

**Kategorie:** LLM-Konnektivitaet
**Integration:** `hub/_services/chat/chat_runtime.py`,
`hub/_services/chat/telegram_chat.py`
**Handler:** keiner eigenstaendig — Nutzung ueber Chat-/Telegram-Service

---

## Zweck

Einheitliche Abstraktionsschicht fuer alle LLM-Provider, damit Chat-
und Agent-Runners provider-unabhaengig arbeiten koennen.

---

## API

Basis: `ModelBackend` (ABC) — konkrete Backends:

| Klasse | Ziel |
|---|---|
| `OllamaBackend` | lokaler Ollama-Server |
| `OpenAIBackend` | OpenAI-kompatible Endpunkte |
| `LMStudioBackend` | LM Studio (OpenAI-kompatibel) |
| `HermesBackend` | Hermes (OpenAI-kompatibel) |
| `AnthropicBackend` | Anthropic-API |
| `CLIBackend` | lokale CLI-Modelle |

```python
from hub._services.llm.model_backend import OllamaBackend

backend = OllamaBackend(
    base_url='http://localhost:11434',
    default_model='qwen3.6:35b-mlx',
)
result = await backend.chat(messages, tools=tools_list, think=True)
# result = {'content': '...', 'tool_calls': [...] or None}
```

Modell-Probe (`_probe_model_api`): prueft Modellenpunkte ohne
Rueckgabe von Credentials/Provider-Text; Fehlercodes:
Authentifizierung abgelehnt, Dienstfehler, nicht erreichbar,
ungueltige Antwort, keine Modelle, Modell fehlt.

---

## Abhaengigkeiten

- httpx (Modell-Listen-Probe)
- asyncio (async chat)
- Endpunkt-spezifische Credentials via User-Config (keine Klartexte
  im Modul — Fehlermeldungen sind credential-frei formuliert)