"""
Embeddings Manager - Ollama Embeddings mit nomic-embed-text
"""
from typing import List, Optional
from langchain_ollama import OllamaEmbeddings
from langchain_core.embeddings import Embeddings
import logging

logger = logging.getLogger(__name__)


class EmbeddingsManager:
    """Verwaltet Embedding-Modelle für die Vektorisierung"""

    # Verfügbare Embedding-Modelle
    MODELS = {
        "nomic-embed-text": {
            "name": "nomic-embed-text",
            "dimensions": 768,
            "description": "Hochwertige Text-Embeddings, optimiert für RAG"
        },
        "mxbai-embed-large": {
            "name": "mxbai-embed-large",
            "dimensions": 1024,
            "description": "Große Embeddings für präzise Suche"
        },
        "all-minilm": {
            "name": "all-minilm",
            "dimensions": 384,
            "description": "Schnelle, kompakte Embeddings"
        }
    }

    DEFAULT_MODEL = "nomic-embed-text"

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        base_url: str = "http://localhost:11434",
        headers: Optional[dict] = None
    ):
        """
        Initialisiert den Embeddings Manager

        Args:
            model_name: Name des Embedding-Modells
            base_url: Ollama Server URL
            headers: Optional HTTP headers (e.g. for Bearer auth)
        """
        self.model_name = model_name
        self.base_url = base_url
        self._headers = headers or {}
        self._embeddings: Optional[Embeddings] = None

    @property
    def embeddings(self) -> Embeddings:
        """Lazy-Loading der Embeddings"""
        if self._embeddings is None:
            self._embeddings = self._create_embeddings()
        return self._embeddings

    def _create_embeddings(self) -> OllamaEmbeddings:
        """Erstellt die Ollama Embeddings Instanz"""
        logger.info(f"Initialisiere Ollama Embeddings mit Modell: {self.model_name}")

        kwargs = {
            "model": self.model_name,
            "base_url": self.base_url,
        }

        # langchain-ollama >=0.2.0 akzeptiert 'headers' nicht mehr direkt.
        # Auth-Headers müssen über client_kwargs (httpx) übergeben werden.
        if self._headers:
            kwargs["client_kwargs"] = {"headers": self._headers}

        try:
            return OllamaEmbeddings(**kwargs)
        except Exception as e:
            # Fallback ohne client_kwargs falls Version zu alt/neu
            logger.warning(f"OllamaEmbeddings mit client_kwargs fehlgeschlagen: {e}")
            kwargs.pop("client_kwargs", None)
            return OllamaEmbeddings(
                model=self.model_name,
                base_url=self.base_url,
            )

    def embed_query(self, text: str) -> List[float]:
        """
        Erstellt Embedding für eine Suchanfrage

        Args:
            text: Der zu embeddierende Text

        Returns:
            Liste von Floats (Embedding-Vektor)
        """
        return self.embeddings.embed_query(text)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Erstellt Embeddings für mehrere Dokumente

        Args:
            texts: Liste von Texten

        Returns:
            Liste von Embedding-Vektoren
        """
        return self.embeddings.embed_documents(texts)

    def get_model_info(self) -> dict:
        """Gibt Informationen über das aktuelle Modell zurück"""
        if self.model_name in self.MODELS:
            return self.MODELS[self.model_name]
        return {
            "name": self.model_name,
            "dimensions": "unknown",
            "description": "Benutzerdefiniertes Modell"
        }

    def switch_model(self, model_name: str) -> None:
        """
        Wechselt zu einem anderen Embedding-Modell

        Args:
            model_name: Name des neuen Modells
        """
        if model_name != self.model_name:
            logger.info(f"Wechsle Embedding-Modell: {self.model_name} -> {model_name}")
            self.model_name = model_name
            self._embeddings = None  # Reset für Lazy-Loading

    @classmethod
    def list_available_models(cls) -> List[dict]:
        """Listet alle verfügbaren Embedding-Modelle"""
        return [
            {"id": k, **v} for k, v in cls.MODELS.items()
        ]

    def test_connection(self) -> bool:
        """
        Testet die Verbindung zum Ollama Server

        Returns:
            True wenn Verbindung erfolgreich
        """
        try:
            # Versuche ein einfaches Embedding zu erstellen
            test_embedding = self.embed_query("test")
            return len(test_embedding) > 0
        except Exception as e:
            logger.error(f"Ollama Verbindungstest fehlgeschlagen: {e}")
            return False
