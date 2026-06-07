#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Ollama Zusammenfassung von Session-Berichten"""

import requests
import json
import os
import sys
from pathlib import Path

OLLAMA_URL = "http://localhost:11434/api/generate"

def summarize(text: str, model: str = "mistral") -> str:
    """Sendet Text an Ollama zur Zusammenfassung"""
    
    prompt = f"""Fasse die folgenden Session-Berichte eines Software-Entwicklungsprojekts zusammen.
Gib eine kompakte Zusammenfassung in 5-10 Saetzen auf Deutsch.
Was waren die Hauptthemen, wichtigsten Erkenntnisse und wiederkehrenden Muster?

BERICHTE:
{text}

ZUSAMMENFASSUNG:"""

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": model,
                "prompt": prompt,
                "stream": False
            },
            timeout=120
        )
        
        if response.status_code == 200:
            result = response.json()
            return result.get("response", "Keine Antwort")
        else:
            return f"Fehler: {response.status_code}"
            
    except requests.exceptions.ConnectionError:
        return "Fehler: Ollama nicht erreichbar (localhost:11434)"
    except Exception as e:
        return f"Fehler: {e}"

def load_reports(directory: Path, count: int = 5) -> str:
    """Laedt die letzten n Berichte"""
    reports = sorted(directory.glob("Bericht_*.md"))[-count:]
    
    combined = []
    for report in reports:
        content = report.read_text(encoding="utf-8", errors="replace")
        # Nur die wichtigsten Teile extrahieren
        lines = []
        for line in content.split("\n"):
            if line.startswith("#") or line.startswith("-") or line.startswith("|"):
                lines.append(line)
        combined.append(f"=== {report.name} ===\n" + "\n".join(lines[:30]))
    
    return "\n\n".join(combined)

if __name__ == "__main__":
    archive = Path(
        os.environ.get(
            "BACH_REPORT_ARCHIVE",
            str(Path.home() / ".bach" / "memory" / "archive"),
        )
    ).expanduser()
    
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    
    print(f"Lade {count} Berichte...")
    text = load_reports(archive, count)
    
    print(f"Sende an Ollama/Mistral ({len(text)} Zeichen)...")
    result = summarize(text)
    
    print("\n" + "="*60)
    print("ZUSAMMENFASSUNG:")
    print("="*60)
    print(result)
