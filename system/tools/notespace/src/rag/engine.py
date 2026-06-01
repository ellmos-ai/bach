"""
RAG Engine - Kernkomponente für Retrieval Augmented Generation
Kombiniert LangChain, ChromaDB und Ollama Embeddings
"""
import os
import logging
from typing import List, Optional, Dict, Any, Tuple
from pathlib import Path
from dataclasses import dataclass

from langchain_chroma import Chroma
from langchain_core.documents import Document as LangChainDocument
from langchain_ollama import ChatOllama
from langchain_core.prompts import PromptTemplate

from .embeddings import EmbeddingsManager
from .splitter import DocumentSplitter, TextChunk

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """Ergebnis einer RAG-Abfrage"""
    answer: str
    source_documents: List[Dict[str, Any]]
    query: str
    confidence: float = 0.0


@dataclass
class DocumentIndexResult:
    """Ergebnis einer Dokument-Indexierung"""
    document_id: str
    chunks_created: int
    success: bool
    error: Optional[str] = None


class RAGEngine:
    """
    RAG Engine mit LangChain, ChromaDB und Ollama

    Features:
    - Dokument-Indexierung mit automatischem Chunking
    - Semantische Suche über ChromaDB
    - Kontextbasierte Antwortgenerierung
    - Multi-Dokument-Queries
    - Filterung nach Dokumenten
    """

    DEFAULT_COLLECTION = "notespace_documents"
    DEFAULT_PERSIST_DIR = "./storage/chroma_db"

    # RAG Prompt Template
    RAG_PROMPT_TEMPLATE = """Beantworte die Frage NUR anhand des Kontexts. Zitiere relevante Stellen. Sage ehrlich wenn die Antwort nicht im Kontext steht. Antworte auf Deutsch.

KONTEXT:
{context}

FRAGE: {question}

ANTWORT:"""

    def __init__(
        self,
        persist_directory: str = DEFAULT_PERSIST_DIR,
        collection_name: str = DEFAULT_COLLECTION,
        embedding_model: str = "nomic-embed-text",
        llm_model: str = "llama3.2",
        ollama_base_url: str = "http://localhost:11434",
        api_key: str = ""
    ):
        """
        Initialisiert die RAG Engine

        Args:
            persist_directory: Verzeichnis für ChromaDB-Persistenz
            collection_name: Name der ChromaDB-Collection
            embedding_model: Ollama Embedding-Modell
            llm_model: Ollama LLM-Modell für Antwortgenerierung
            ollama_base_url: Ollama Server URL
            api_key: Optional API key for authenticated Ollama proxy
        """
        self.persist_directory = persist_directory
        self.collection_name = collection_name
        self.ollama_base_url = ollama_base_url

        # Erstelle Persist-Verzeichnis
        Path(persist_directory).mkdir(parents=True, exist_ok=True)

        # Build auth headers for remote Ollama proxy
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # Initialisiere Komponenten
        self.embeddings_manager = EmbeddingsManager(
            model_name=embedding_model,
            base_url=ollama_base_url,
            headers=headers
        )

        self.splitter = DocumentSplitter.from_preset("default")

        # LLM für Antwortgenerierung
        llm_kwargs = {
            "model": llm_model,
            "base_url": ollama_base_url,
            "temperature": 0.3,
        }
        # langchain-ollama >=0.2.0: Auth-Headers über client_kwargs
        if headers:
            llm_kwargs["client_kwargs"] = {"headers": headers}

        try:
            self.llm = ChatOllama(**llm_kwargs)
        except Exception as e:
            logger.warning(f"ChatOllama mit client_kwargs fehlgeschlagen: {e}")
            self.llm = ChatOllama(
                model=llm_model,
                base_url=ollama_base_url,
                temperature=0.3,
            )

        # ChromaDB Vector Store
        self._vectorstore: Optional[Chroma] = None

        # Prompt Template
        self.prompt = PromptTemplate(
            template=self.RAG_PROMPT_TEMPLATE,
            input_variables=["context", "question"]
        )

        logger.info(f"RAG Engine initialisiert: {embedding_model} + {llm_model}")

    @property
    def vectorstore(self) -> Chroma:
        """Lazy-Loading des Vector Stores"""
        if self._vectorstore is None:
            self._vectorstore = Chroma(
                collection_name=self.collection_name,
                embedding_function=self.embeddings_manager.embeddings,
                persist_directory=self.persist_directory
            )
        return self._vectorstore

    def index_document(
        self,
        content: str,
        document_id: str,
        source: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> DocumentIndexResult:
        """
        Indexiert ein einzelnes Dokument

        Args:
            content: Dokumentinhalt
            document_id: Eindeutige Dokument-ID
            source: Quellenangabe (z.B. Dateipfad)
            metadata: Zusätzliche Metadaten

        Returns:
            DocumentIndexResult mit Status
        """
        try:
            # Entferne vorhandene Chunks für dieses Dokument
            self._remove_document_chunks(document_id)

            # Splitte Text in Chunks
            chunks = self.splitter.split_text(
                text=content,
                source=source,
                document_id=document_id
            )

            if not chunks:
                return DocumentIndexResult(
                    document_id=document_id,
                    chunks_created=0,
                    success=True
                )

            # Konvertiere zu LangChain Documents
            lc_documents = []
            for chunk in chunks:
                doc_metadata = {
                    "document_id": document_id,
                    "source": source,
                    "chunk_index": chunk.metadata.chunk_index,
                    "total_chunks": chunk.metadata.total_chunks
                }
                if metadata:
                    doc_metadata.update(metadata)

                lc_documents.append(LangChainDocument(
                    page_content=chunk.content,
                    metadata=doc_metadata
                ))

            # Füge zu ChromaDB hinzu
            self.vectorstore.add_documents(lc_documents)

            logger.info(f"Dokument indexiert: {document_id} ({len(chunks)} Chunks)")

            return DocumentIndexResult(
                document_id=document_id,
                chunks_created=len(chunks),
                success=True
            )

        except Exception as e:
            logger.error(f"Fehler bei Indexierung von {document_id}: {e}")
            return DocumentIndexResult(
                document_id=document_id,
                chunks_created=0,
                success=False,
                error=str(e)
            )

    def index_documents(
        self,
        documents: List[Dict[str, Any]]
    ) -> List[DocumentIndexResult]:
        """
        Indexiert mehrere Dokumente

        Args:
            documents: Liste mit dict(content, document_id, source, metadata)

        Returns:
            Liste von DocumentIndexResult
        """
        results = []
        for doc in documents:
            result = self.index_document(
                content=doc.get("content", ""),
                document_id=doc.get("document_id", doc.get("id", "")),
                source=doc.get("source", doc.get("path", "")),
                metadata=doc.get("metadata")
            )
            results.append(result)

        successful = sum(1 for r in results if r.success)
        logger.info(f"Batch-Indexierung: {successful}/{len(results)} erfolgreich")

        return results

    def _remove_document_chunks(self, document_id: str) -> None:
        """Entfernt alle Chunks eines Dokuments aus dem Index"""
        try:
            # Hole Collection direkt
            collection = self.vectorstore._collection
            # Lösche nach document_id
            collection.delete(where={"document_id": document_id})
            logger.debug(f"Chunks für {document_id} entfernt")
        except Exception as e:
            logger.warning(f"Konnte Chunks nicht entfernen: {e}")

    def search(
        self,
        query: str,
        k: int = 5,
        document_ids: Optional[List[str]] = None,
        score_threshold: float = 0.0
    ) -> List[Tuple[LangChainDocument, float]]:
        """
        Semantische Suche in indexierten Dokumenten

        Args:
            query: Suchanfrage
            k: Anzahl der Ergebnisse
            document_ids: Optional - nur in diesen Dokumenten suchen
            score_threshold: Minimaler Relevanz-Score

        Returns:
            Liste von (Document, Score) Tupeln
        """
        # Filter nach Dokument-IDs wenn angegeben
        filter_dict = None
        if document_ids:
            filter_dict = {"document_id": {"$in": document_ids}}

        # Führe Suche durch
        results = self.vectorstore.similarity_search_with_score(
            query=query,
            k=k,
            filter=filter_dict
        )

        # Filtere nach Score
        if score_threshold > 0:
            results = [(doc, score) for doc, score in results if score >= score_threshold]

        return results

    def query(
        self,
        question: str,
        k: int = 5,
        document_ids: Optional[List[str]] = None
    ) -> RetrievalResult:
        """
        RAG-Query: Suche + Antwortgenerierung

        Args:
            question: Die Frage
            k: Anzahl der Kontext-Dokumente
            document_ids: Optional - nur diese Dokumente verwenden

        Returns:
            RetrievalResult mit Antwort und Quellen
        """
        # Suche relevante Chunks
        search_results = self.search(
            query=question,
            k=k,
            document_ids=document_ids
        )

        if not search_results:
            return RetrievalResult(
                answer="Keine relevanten Informationen in den indexierten Dokumenten gefunden.",
                source_documents=[],
                query=question,
                confidence=0.0
            )

        # Baue Kontext
        context_parts = []
        source_docs = []

        for doc, score in search_results:
            context_parts.append(f"[Quelle: {doc.metadata.get('source', 'Unbekannt')}]\n{doc.page_content}")

            source_docs.append({
                "content": doc.page_content,
                "source": doc.metadata.get("source"),
                "document_id": doc.metadata.get("document_id"),
                "chunk_index": doc.metadata.get("chunk_index"),
                "score": float(score)
            })

        context = "\n\n---\n\n".join(context_parts)

        # Generiere Antwort mit LLM
        prompt_text = self.prompt.format(context=context, question=question)
        response = self.llm.invoke(prompt_text)

        # Berechne durchschnittliche Konfidenz
        avg_score = sum(d["score"] for d in source_docs) / len(source_docs) if source_docs else 0

        return RetrievalResult(
            answer=response.content,
            source_documents=source_docs,
            query=question,
            confidence=avg_score
        )

    def query_with_context(
        self,
        question: str,
        additional_context: str = "",
        k: int = 5,
        document_ids: Optional[List[str]] = None
    ) -> RetrievalResult:
        """
        RAG-Query mit zusätzlichem Kontext (z.B. Chat-Historie)

        Args:
            question: Die Frage
            additional_context: Zusätzlicher Kontext (z.B. vorherige Nachrichten)
            k: Anzahl der Kontext-Dokumente
            document_ids: Optional - nur diese Dokumente verwenden

        Returns:
            RetrievalResult mit Antwort und Quellen
        """
        # Kombiniere Frage mit Kontext für bessere Suche
        search_query = f"{additional_context}\n{question}" if additional_context else question

        # Führe normale Query durch
        result = self.query(
            question=search_query,
            k=k,
            document_ids=document_ids
        )

        # Speichere originale Frage
        result.query = question

        return result

    def get_document_chunks(self, document_id: str) -> List[Dict[str, Any]]:
        """
        Gibt alle Chunks eines Dokuments zurück

        Args:
            document_id: Die Dokument-ID

        Returns:
            Liste der Chunks mit Metadaten
        """
        results = self.vectorstore.similarity_search(
            query="",  # Leere Query, wir wollen alle
            k=1000,
            filter={"document_id": document_id}
        )

        return [
            {
                "content": doc.page_content,
                "metadata": doc.metadata
            }
            for doc in results
        ]

    def get_statistics(self) -> Dict[str, Any]:
        """Gibt Statistiken über den Index zurück"""
        try:
            collection = self.vectorstore._collection
            count = collection.count()

            return {
                "total_chunks": count,
                "collection_name": self.collection_name,
                "persist_directory": self.persist_directory,
                "embedding_model": self.embeddings_manager.model_name,
                "llm_model": self.llm.model
            }
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Statistiken: {e}")
            return {"error": str(e)}

    def clear_index(self) -> bool:
        """
        Löscht den gesamten Index

        Returns:
            True bei Erfolg
        """
        try:
            # Lösche Collection
            self.vectorstore.delete_collection()
            # Reset für Neuinitialisierung
            self._vectorstore = None
            logger.info("Index gelöscht")
            return True
        except Exception as e:
            logger.error(f"Fehler beim Löschen des Index: {e}")
            return False

    def remove_document(self, document_id: str) -> bool:
        """
        Entfernt ein Dokument aus dem Index

        Args:
            document_id: Die Dokument-ID

        Returns:
            True bei Erfolg
        """
        try:
            self._remove_document_chunks(document_id)
            logger.info(f"Dokument {document_id} aus Index entfernt")
            return True
        except Exception as e:
            logger.error(f"Fehler beim Entfernen von {document_id}: {e}")
            return False

    def update_splitter_config(
        self,
        preset: Optional[str] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None
    ) -> None:
        """
        Aktualisiert die Splitter-Konfiguration

        Args:
            preset: Preset-Name oder None
            chunk_size: Chunk-Größe
            chunk_overlap: Überlappung
        """
        if preset:
            self.splitter = DocumentSplitter.from_preset(preset)
        else:
            self.splitter.update_config(chunk_size, chunk_overlap)

        logger.info(f"Splitter aktualisiert: {self.splitter.get_config()}")

    def test_connection(self) -> Dict[str, bool]:
        """
        Testet alle Verbindungen

        Returns:
            Dict mit Status für jede Komponente
        """
        results = {
            "embeddings": False,
            "vectorstore": False,
            "llm": False
        }

        # Test Embeddings
        results["embeddings"] = self.embeddings_manager.test_connection()

        # Test VectorStore
        try:
            _ = self.vectorstore._collection.count()
            results["vectorstore"] = True
        except Exception:
            pass

        # Test LLM
        try:
            response = self.llm.invoke("Test")
            results["llm"] = len(response.content) > 0
        except Exception:
            pass

        return results
