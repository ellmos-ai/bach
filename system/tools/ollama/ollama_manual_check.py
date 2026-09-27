# SPDX-License-Identifier: MIT
"""Manueller Ollama-Rauchtest gegen einen lokal laufenden Server.

T-20260927-283375364: Umbenannt von test_tokens.py. Braucht einen lokalen
Ollama-Server auf localhost:11434 und hatte keine echten Assertions (nur
print + try/except-Schlucken) -- pytest wertete das immer als "passed",
unabhaengig vom tatsaechlichen Ergebnis. Der Dateiname matcht pytests
Discovery-Muster (test_*.py) bewusst nicht mehr; Aufruf manuell:
    python ollama_manual_check.py
"""
import json
import requests


def check_ollama_tokens():
    url = "http://localhost:11434/api/generate"
    payload = {
        "model": "llama3.2",
        "prompt": "Say hello in one word",
        "stream": False
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        if response.status_code == 200:
            data = response.json()
            print(f"Response: {data.get('response')}")
            print(f"Prompt Tokens: {data.get('prompt_eval_count')}")
            print(f"Response Tokens: {data.get('eval_count')}")
            print(f"Total Duration: {data.get('total_duration')}")
        else:
            print(f"Error: {response.status_code}")
    except Exception as e:
        print(f"Exception: {e}")


if __name__ == "__main__":
    check_ollama_tokens()
