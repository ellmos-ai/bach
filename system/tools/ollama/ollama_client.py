# SPDX-License-Identifier: MIT
"""
OllamaClient - REST-API Wrapper fuer lokale Ollama-Instanz
=========================================================

Zentrale Client-Klasse fuer alle Ollama-Interaktionen in BACH.
Ersetzt direkte requests-Aufrufe in Handlern und Tools.

Usage:
    from tools.ollama_client import OllamaClient
    
    client = OllamaClient()
    if client.is_available():
        models = client.list_models()
        response = client.generate("Was ist BACH?")

Erstellt: 2026-01-23 (Task 296)
Version: 1.0.0
"""
import json
import subprocess
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass


@dataclass
class OllamaModel:
    """Modell-Information."""
    name: str
    size_bytes: int
    modified_at: str = ""
    digest: str = ""
    
    @property
    def size_gb(self) -> float:
        """Groesse in GB."""
        return self.size_bytes / (1024**3)
    
    def __str__(self) -> str:
        return f"{self.name} ({self.size_gb:.1f} GB)"


@dataclass
class OllamaResponse:
    """Antwort von Ollama."""
    success: bool
    text: str = ""
    model: str = ""
    total_duration: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str = ""
    
    @property
    def total_tokens(self) -> int:
        """Gesamtanzahl der Tokens."""
        return self.prompt_tokens + self.completion_tokens

    @property
    def duration_seconds(self) -> float:
        """Dauer in Sekunden."""
        return self.total_duration / 1e9 if self.total_duration else 0


class OllamaClient:
    """
    REST-API Client fuer lokale Ollama-Instanz.
    
    Features:
    - Verbindungspruefung
    - Modell-Listing
    - Text-Generierung
    - Embeddings
    - Fallback auf curl wenn requests fehlt
    """
    
    DEFAULT_URL = "http://localhost:11434"
    DEFAULT_MODEL = "llama3.2"
    DEFAULT_EMBED_MODEL = "nomic-embed-text"
    
    def __init__(self, base_url: str = None, timeout: int = 120):
        """
        Initialisiert den Client.
        
        Args:
            base_url: Ollama-Server URL (default: http://localhost:11434)
            timeout: Request-Timeout in Sekunden
        """
        self.base_url = base_url or self.DEFAULT_URL
        self.timeout = timeout
        self._requests = None
        self._load_requests()
    
    def _load_requests(self) -> None:
        """Laedt requests-Modul falls verfuegbar."""
        try:
            import requests
            self._requests = requests
        except ImportError:
            self._requests = None
    
    @property
    def has_requests(self) -> bool:
        """Prueft ob requests-Modul verfuegbar ist."""
        return self._requests is not None
    
    # -------------------------------------------------------------------------
    # Verbindungspruefung
    # -------------------------------------------------------------------------
    
    def is_available(self) -> bool:
        """
        Prueft ob Ollama-Server erreichbar ist.
        
        Returns:
            True wenn Server antwortet, sonst False
        """
        status = self.get_status()
        return status.get("online", False)
    
    def get_status(self) -> Dict[str, Any]:
        """
        Holt Server-Status inkl. Version.
        
        Returns:
            {"online": bool, "version": str, "error": str}
        """
        result = {"online": False, "version": "", "error": ""}
        
        try:
            data = self._get("/api/version")
            if data:
                result["online"] = True
                result["version"] = data.get("version", "unbekannt")
        except Exception as e:
            result["error"] = str(e)
        
        return result
    
    # -------------------------------------------------------------------------
    # Modell-Listing
    # -------------------------------------------------------------------------
    
    def list_models(self) -> List[OllamaModel]:
        """
        Listet alle installierten Modelle.
        
        Returns:
            Liste von OllamaModel-Objekten
        """
        models = []
        
        try:
            data = self._get("/api/tags")
            if data and "models" in data:
                for m in data["models"]:
                    models.append(OllamaModel(
                        name=m.get("name", ""),
                        size_bytes=m.get("size", 0),
                        modified_at=m.get("modified_at", ""),
                        digest=m.get("digest", "")
                    ))
        except Exception:
            pass
        
        return models
    
    def has_model(self, model_name: str) -> bool:
        """
        Prueft ob ein Modell installiert ist.
        
        Args:
            model_name: Name des Modells (z.B. "llama3.2")
        """
        models = self.list_models()
        return any(m.name.startswith(model_name) for m in models)
    
    # -------------------------------------------------------------------------
    # Text-Generierung
    # -------------------------------------------------------------------------
    
    def generate(
        self, 
        prompt: str, 
        model: str = None,
        system: str = None,
        temperature: float = None,
        stream: bool = False
    ) -> OllamaResponse:
        """
        Generiert Text mit Ollama.
        
        Args:
            prompt: Eingabe-Prompt
            model: Modellname (default: llama3.2)
            system: System-Prompt (optional)
            temperature: Kreativitaet 0.0-1.0 (optional)
            stream: Streaming-Modus (default: False)
        
        Returns:
            OllamaResponse mit Ergebnis
        """
        model = model or self.DEFAULT_MODEL
        
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": stream
        }
        
        if system:
            payload["system"] = system
        if temperature is not None:
            payload["options"] = {"temperature": temperature}
        
        try:
            data = self._post("/api/generate", payload)
            if data:
                return OllamaResponse(
                    success=True,
                    text=data.get("response", ""),
                    model=data.get("model", model),
                    total_duration=data.get("total_duration", 0),
                    prompt_tokens=data.get("prompt_eval_count", 0),
                    completion_tokens=data.get("eval_count", 0)
                )
            else:
                return OllamaResponse(success=False, error="Keine Antwort")
        except Exception as e:
            return OllamaResponse(success=False, error=str(e))
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        model: str = None,
        stream: bool = False
    ) -> OllamaResponse:
        """
        Chat-Completion mit Ollama.
        
        Args:
            messages: Liste von {"role": "user/assistant/system", "content": "..."}
            model: Modellname
            stream: Streaming-Modus
        
        Returns:
            OllamaResponse
        """
        model = model or self.DEFAULT_MODEL
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream
        }
        
        try:
            data = self._post("/api/chat", payload)
            if data and "message" in data:
                return OllamaResponse(
                    success=True,
                    text=data["message"].get("content", ""),
                    model=data.get("model", model),
                    total_duration=data.get("total_duration", 0),
                    prompt_tokens=data.get("prompt_eval_count", 0),
                    completion_tokens=data.get("eval_count", 0)
                )
            else:
                return OllamaResponse(success=False, error="Keine Antwort")
        except Exception as e:
            return OllamaResponse(success=False, error=str(e))
    
    # -------------------------------------------------------------------------
    # Embeddings
    # -------------------------------------------------------------------------
    
    def embed(
        self, 
        text: str, 
        model: str = None
    ) -> Tuple[bool, List[float]]:
        """
        Erstellt Embedding fuer Text.
        
        Args:
            text: Eingabetext
            model: Embedding-Modell (default: nomic-embed-text)
        
        Returns:
            (success, embedding_vector)
        """
        model = model or self.DEFAULT_EMBED_MODEL
        
        payload = {
            "model": model,
            "prompt": text
        }
        
        try:
            data = self._post("/api/embeddings", payload)
            if data and "embedding" in data:
                return True, data["embedding"]
            else:
                return False, []
        except Exception:
            return False, []
    
    # -------------------------------------------------------------------------
    # Interne HTTP-Methoden
    # -------------------------------------------------------------------------
    
    def _get(self, endpoint: str) -> Optional[Dict]:
        """GET-Request an Ollama."""
        url = f"{self.base_url}{endpoint}"
        
        if self._requests:
            response = self._requests.get(url, timeout=self.timeout)
            if response.status_code == 200:
                return response.json()
            return None
        else:
            return self._curl_get(url)
    
    def _post(self, endpoint: str, data: Dict) -> Optional[Dict]:
        """POST-Request an Ollama."""
        url = f"{self.base_url}{endpoint}"
        
        if self._requests:
            response = self._requests.post(
                url, 
                json=data, 
                timeout=self.timeout
            )
            if response.status_code == 200:
                return response.json()
            return None
        else:
            return self._curl_post(url, data)
    
    def _curl_get(self, url: str) -> Optional[Dict]:
        """Fallback GET via curl."""
        try:
            result = subprocess.run(
                ["curl", "-s", url],
                capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=self.timeout
            )
            if result.returncode == 0 and result.stdout:
                return json.loads(result.stdout)
        except Exception:
            pass
        return None

    def _curl_post(self, url: str, data: Dict) -> Optional[Dict]:
        """Fallback POST via curl."""
        try:
            result = subprocess.run(
                ["curl", "-s", "-X", "POST", url,
                 "-H", "Content-Type: application/json",
                 "-d", json.dumps(data)],
                capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=self.timeout
            )
            if result.returncode == 0 and result.stdout:
                return json.loads(result.stdout)
        except Exception:
            pass
        return None


# =============================================================================
# Convenience-Funktionen
# =============================================================================

def check_ollama() -> Dict[str, Any]:
    """Quick-Check ob Ollama verfuegbar ist."""
    client = OllamaClient()
    return client.get_status()


def ask_ollama(prompt: str, model: str = None) -> str:
    """Quick-Funktion fuer einfache Anfragen."""
    client = OllamaClient()
    response = client.generate(prompt, model=model)
    return response.text if response.success else f"Fehler: {response.error}"


# =============================================================================
# CLI Test
# =============================================================================

if __name__ == "__main__":
    print("OllamaClient Test")
    print("=" * 50)
    
    client = OllamaClient()
    
    # Status
    status = client.get_status()
    print(f"\nServer: {'ONLINE' if status['online'] else 'OFFLINE'}")
    if status['version']:
        print(f"Version: {status['version']}")
    
    # Modelle
    if status['online']:
        models = client.list_models()
        print(f"\nModelle: {len(models)}")
        for m in models:
            print(f"  - {m}")
