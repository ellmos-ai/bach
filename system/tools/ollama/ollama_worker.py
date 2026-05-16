#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
OLLAMA WORKER - Async Job-Verarbeitung
======================================
Laueft im Hintergrund, verarbeitet Jobs aus pending/ via Ollama,
schreibt Ergebnisse nach completed/.

Usage:
  python ollama_worker.py          # Einmal alle pending Jobs verarbeiten
  python ollama_worker.py --daemon # Dauerhaft laufen
"""

import json
import time
import sys
import requests
from pathlib import Path
from datetime import datetime

# Konfiguration
BASE_DIR = Path(__file__).parent.parent / "DATA" / "ollama_queue"
PENDING = BASE_DIR / "pending"
COMPLETED = BASE_DIR / "completed"
OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "mistral:latest"

def log(msg: str):
    """Logging mit Timestamp"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def is_ollama_ready() -> bool:
    """Prueft ob Ollama bereit ist"""
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        return r.status_code == 200
    except (requests.RequestException, OSError):
        return False

def process_job(job_file: Path) -> bool:
    """Verarbeitet einen einzelnen Job"""
    log(f"Verarbeite: {job_file.name}")
    
    try:
        job = json.loads(job_file.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"  FEHLER beim Lesen: {e}")
        return False
    
    prompt = job.get("prompt", "")
    model = job.get("model", DEFAULT_MODEL)
    job_id = job.get("id", job_file.stem)
    
    log(f"  Model: {model}")
    log(f"  Prompt: {prompt[:80]}...")
    
    try:
        # Streaming fuer besseres Timeout-Verhalten
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": model,
                "prompt": prompt,
                "stream": True
            },
            stream=True,
            timeout=300
        )
        
        result_text = ""
        for line in response.iter_lines():
            if line:
                data = json.loads(line)
                result_text += data.get("response", "")
                if data.get("done"):
                    break
        
        # Ergebnis speichern
        result = {
            "id": job_id,
            "status": "completed",
            "prompt": prompt[:200] + "..." if len(prompt) > 200 else prompt,
            "result": result_text,
            "model": model,
            "completed_at": datetime.now().isoformat()
        }
        
        result_file = COMPLETED / f"{job_id}_result.json"
        result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        
        # Original-Job loeschen
        job_file.unlink()
        
        log(f"  FERTIG! Ergebnis: {result_file.name}")
        return True
        
    except requests.exceptions.Timeout:
        log(f"  TIMEOUT nach 300s")
        return False
    except Exception as e:
        log(f"  FEHLER: {e}")
        return False

def process_all_pending():
    """Verarbeitet alle pending Jobs"""
    pending_jobs = list(PENDING.glob("*.json"))
    
    if not pending_jobs:
        log("Keine pending Jobs")
        return
    
    log(f"Gefunden: {len(pending_jobs)} Jobs")
    
    if not is_ollama_ready():
        log("WARNUNG: Ollama nicht erreichbar!")
        return
    
    for job_file in pending_jobs:
        process_job(job_file)
        time.sleep(1)  # Kurze Pause zwischen Jobs

def daemon_mode():
    """Dauerhaft laufen und polling"""
    log("DAEMON MODE gestartet - Polling alle 5 Sekunden")
    log("Druecke Ctrl+C zum Beenden")
    
    try:
        while True:
            pending_jobs = list(PENDING.glob("*.json"))
            if pending_jobs:
                if is_ollama_ready():
                    for job_file in pending_jobs:
                        process_job(job_file)
                else:
                    log("Ollama nicht bereit, warte...")
            time.sleep(5)
    except KeyboardInterrupt:
        log("Daemon beendet")

if __name__ == "__main__":
    # Verzeichnisse sicherstellen
    PENDING.mkdir(parents=True, exist_ok=True)
    COMPLETED.mkdir(parents=True, exist_ok=True)
    
    if "--daemon" in sys.argv:
        daemon_mode()
    else:
        process_all_pending()
