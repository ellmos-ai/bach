#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Document Manager - Central document handling for NoteSpaceLLM
=============================================================

Manages documents, their selection state, and associated sub-queries.

Features:
- Add files and directories
- Track selection state (included/excluded from report)
- Associate sub-queries with documents
- Extract and cache document content
- RAG integration for semantic search
"""

import os
import hashlib
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Callable, TYPE_CHECKING
import uuid

if TYPE_CHECKING:
    from ..rag.engine import RAGEngine

logger = logging.getLogger(__name__)


class DocumentStatus(Enum):
    """Status of a document in the analysis pipeline."""
    PENDING = "pending"          # Not yet processed
    EXTRACTING = "extracting"    # Text extraction in progress
    READY = "ready"              # Ready for analysis
    ANALYZING = "analyzing"      # Sub-query analysis in progress
    COMPLETED = "completed"      # All analyses complete
    ERROR = "error"              # Error occurred


@dataclass
class DocumentItem:
    """Represents a single document in the workspace."""
    id: str
    path: Path
    name: str
    extension: str
    size_bytes: int
    created_at: datetime
    modified_at: datetime

    # State
    is_selected: bool = True     # Include in report generation
    status: DocumentStatus = DocumentStatus.PENDING
    error_message: str = ""

    # Content
    content_hash: str = ""
    extracted_text: str = ""
    text_length: int = 0

    # Metadata
    is_directory: bool = False
    parent_id: Optional[str] = None  # For nested directories
    sub_query_ids: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    # RAG State
    is_indexed: bool = False     # Ob im RAG-Index
    chunk_count: int = 0         # Anzahl der Chunks im Index

    @classmethod
    def from_path(cls, filepath: Path, parent_id: Optional[str] = None) -> "DocumentItem":
        """Create a DocumentItem from a file path."""
        stat = filepath.stat()
        return cls(
            id=str(uuid.uuid4()),
            path=filepath,
            name=filepath.name,
            extension=filepath.suffix.lower(),
            size_bytes=stat.st_size if filepath.is_file() else 0,
            created_at=datetime.fromtimestamp(stat.st_ctime),
            modified_at=datetime.fromtimestamp(stat.st_mtime),
            is_directory=filepath.is_dir(),
            parent_id=parent_id
        )

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "path": str(self.path),
            "name": self.name,
            "extension": self.extension,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at.isoformat(),
            "modified_at": self.modified_at.isoformat(),
            "is_selected": self.is_selected,
            "status": self.status.value,
            "error_message": self.error_message,
            "content_hash": self.content_hash,
            "text_length": self.text_length,
            "is_directory": self.is_directory,
            "parent_id": self.parent_id,
            "sub_query_ids": self.sub_query_ids,
            "tags": self.tags,
            "is_indexed": self.is_indexed,
            "chunk_count": self.chunk_count
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DocumentItem":
        """Deserialize from dictionary."""
        return cls(
            id=data["id"],
            path=Path(data["path"]),
            name=data["name"],
            extension=data["extension"],
            size_bytes=data["size_bytes"],
            created_at=datetime.fromisoformat(data["created_at"]),
            modified_at=datetime.fromisoformat(data["modified_at"]),
            is_selected=data.get("is_selected", True),
            status=DocumentStatus(data.get("status", "pending")),
            error_message=data.get("error_message", ""),
            content_hash=data.get("content_hash", ""),
            text_length=data.get("text_length", 0),
            is_directory=data.get("is_directory", False),
            parent_id=data.get("parent_id"),
            sub_query_ids=data.get("sub_query_ids", []),
            tags=data.get("tags", []),
            is_indexed=data.get("is_indexed", False),
            chunk_count=data.get("chunk_count", 0)
        )


class DocumentManager:
    """
    Manages the document workspace for a NoteSpaceLLM project.

    Responsibilities:
    - Add/remove documents and directories
    - Track selection state
    - Cache extracted text
    - Manage sub-query associations
    """

    # Supported file types
    SUPPORTED_EXTENSIONS = {
        # Text
        ".txt", ".md", ".rst", ".log",
        # Documents
        ".pdf", ".docx", ".doc", ".odt", ".rtf",
        # Data
        ".json", ".xml", ".yaml", ".yml", ".csv",
        # Code (for analysis)
        ".py", ".js", ".ts", ".java", ".cpp", ".c", ".h",
        # Spreadsheets
        ".xlsx", ".xls", ".ods",
        # Email
        ".eml", ".msg"
    }

    def __init__(self, project_path: Optional[Path] = None, rag_engine: Optional['RAGEngine'] = None):
        """
        Initialize the document manager.

        Args:
            project_path: Path to store document cache and state
            rag_engine: Optional RAG engine for semantic search
        """
        self.project_path = project_path
        self._documents: Dict[str, DocumentItem] = {}
        self._on_change_callbacks: List[Callable] = []
        self._rag_engine: Optional['RAGEngine'] = rag_engine
        self._auto_index: bool = True  # Automatisch indexieren wenn Text extrahiert
        self._auto_extract: bool = True  # Automatisch Text extrahieren bei add_file
        self._text_extractor = None  # Lazy-loaded
        self._pending_extractions: List[str] = []  # doc_ids waiting for async extraction

        if project_path:
            self._cache_dir = project_path / ".cache"
            self._cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def documents(self) -> List[DocumentItem]:
        """Get all documents."""
        return list(self._documents.values())

    @property
    def selected_documents(self) -> List[DocumentItem]:
        """Get only selected documents."""
        return [d for d in self._documents.values() if d.is_selected and not d.is_directory]

    @property
    def root_documents(self) -> List[DocumentItem]:
        """Get top-level documents (no parent)."""
        return [d for d in self._documents.values() if d.parent_id is None]

    def get_document(self, doc_id: str) -> Optional[DocumentItem]:
        """Get a document by ID."""
        return self._documents.get(doc_id)

    def get_children(self, parent_id: str) -> List[DocumentItem]:
        """Get child documents of a directory."""
        return [d for d in self._documents.values() if d.parent_id == parent_id]

    def add_file(self, filepath: Path, parent_id: Optional[str] = None) -> Optional[DocumentItem]:
        """
        Add a single file to the workspace.

        Args:
            filepath: Path to the file
            parent_id: Optional parent directory ID

        Returns:
            DocumentItem if successful, None if file type not supported
        """
        filepath = Path(filepath).resolve()

        if not filepath.exists():
            return None

        if filepath.is_file():
            if filepath.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
                return None

        # Check for duplicates
        for doc in self._documents.values():
            if doc.path == filepath:
                return doc  # Already exists

        doc = DocumentItem.from_path(filepath, parent_id)
        self._documents[doc.id] = doc
        self._notify_change("add", doc)

        # Auto-Extraktion wird NICHT mehr synchron ausgeführt.
        # Stattdessen signalisiert pending_extraction, dass die GUI
        # einen ExtractionWorker starten soll.
        if self._auto_extract and not doc.is_directory:
            doc.status = DocumentStatus.EXTRACTING
            self._pending_extractions.append(doc.id)

        return doc

    def add_directory(self, dirpath: Path, recursive: bool = True) -> List[DocumentItem]:
        """
        Add a directory and its contents.

        Args:
            dirpath: Path to the directory
            recursive: Include subdirectories

        Returns:
            List of added DocumentItems
        """
        dirpath = Path(dirpath).resolve()

        if not dirpath.exists() or not dirpath.is_dir():
            return []

        added = []

        # Add the directory itself
        dir_doc = self.add_file(dirpath)
        if dir_doc:
            added.append(dir_doc)

            # Add contents
            added.extend(self._scan_directory(dirpath, dir_doc.id, recursive))

        return added

    def _scan_directory(self, dirpath: Path, parent_id: str, recursive: bool) -> List[DocumentItem]:
        """Recursively scan a directory."""
        added = []

        try:
            for item in sorted(dirpath.iterdir()):
                if item.name.startswith("."):
                    continue

                if item.is_file():
                    doc = self.add_file(item, parent_id)
                    if doc:
                        added.append(doc)

                elif item.is_dir() and recursive:
                    # Add subdirectory
                    subdir_doc = self.add_file(item, parent_id)
                    if subdir_doc:
                        added.append(subdir_doc)
                        added.extend(self._scan_directory(item, subdir_doc.id, recursive))

        except PermissionError:
            pass  # Skip directories we can't access

        return added

    def remove_document(self, doc_id: str, recursive: bool = True) -> bool:
        """
        Remove a document from the workspace.

        Args:
            doc_id: Document ID to remove
            recursive: Also remove children if directory

        Returns:
            True if removed
        """
        doc = self._documents.get(doc_id)
        if not doc:
            return False

        if recursive and doc.is_directory:
            # Remove all children first
            children = self.get_children(doc_id)
            for child in children:
                self.remove_document(child.id, recursive=True)

        del self._documents[doc_id]
        self._notify_change("remove", doc)
        return True

    def toggle_selection(self, doc_id: str) -> bool:
        """Toggle document selection state."""
        doc = self._documents.get(doc_id)
        if doc:
            doc.is_selected = not doc.is_selected
            self._notify_change("update", doc)
            return doc.is_selected
        return False

    def set_selection(self, doc_id: str, selected: bool) -> None:
        """Set document selection state."""
        doc = self._documents.get(doc_id)
        if doc:
            doc.is_selected = selected
            self._notify_change("update", doc)

    def select_all(self) -> None:
        """Select all documents."""
        for doc in self._documents.values():
            doc.is_selected = True
        self._notify_change("bulk_update", None)

    def deselect_all(self) -> None:
        """Deselect all documents."""
        for doc in self._documents.values():
            doc.is_selected = False
        self._notify_change("bulk_update", None)

    def add_sub_query(self, doc_id: str, query_id: str) -> bool:
        """Associate a sub-query with a document."""
        doc = self._documents.get(doc_id)
        if doc and query_id not in doc.sub_query_ids:
            doc.sub_query_ids.append(query_id)
            self._notify_change("update", doc)
            return True
        return False

    def remove_sub_query(self, doc_id: str, query_id: str) -> bool:
        """Remove a sub-query association."""
        doc = self._documents.get(doc_id)
        if doc and query_id in doc.sub_query_ids:
            doc.sub_query_ids.remove(query_id)
            self._notify_change("update", doc)
            return True
        return False

    def set_status(self, doc_id: str, status: DocumentStatus, error: str = "") -> None:
        """Update document status."""
        doc = self._documents.get(doc_id)
        if doc:
            doc.status = status
            doc.error_message = error
            self._notify_change("update", doc)

    def add_tag(self, doc_id: str, tag: str) -> None:
        """Add a tag to a document."""
        doc = self._documents.get(doc_id)
        if doc and tag not in doc.tags:
            doc.tags.append(tag)
            self._notify_change("update", doc)

    def remove_tag(self, doc_id: str, tag: str) -> None:
        """Remove a tag from a document."""
        doc = self._documents.get(doc_id)
        if doc and tag in doc.tags:
            doc.tags.remove(tag)
            self._notify_change("update", doc)

    def get_statistics(self) -> dict:
        """Get workspace statistics."""
        docs = self.documents
        selected = self.selected_documents

        return {
            "total_documents": len([d for d in docs if not d.is_directory]),
            "total_directories": len([d for d in docs if d.is_directory]),
            "selected_documents": len(selected),
            "total_size_bytes": sum(d.size_bytes for d in docs),
            "total_text_length": sum(d.text_length for d in docs),
            "status_counts": {
                status.value: len([d for d in docs if d.status == status])
                for status in DocumentStatus
            },
            "by_extension": self._count_by_extension(docs)
        }

    def _count_by_extension(self, docs: List[DocumentItem]) -> Dict[str, int]:
        """Count documents by extension."""
        counts = {}
        for doc in docs:
            if not doc.is_directory:
                ext = doc.extension or "unknown"
                counts[ext] = counts.get(ext, 0) + 1
        return counts

    def on_change(self, callback: Callable) -> None:
        """Register a callback for document changes."""
        self._on_change_callbacks.append(callback)

    def _notify_change(self, action: str, document: Optional[DocumentItem]) -> None:
        """Notify listeners of changes."""
        for callback in self._on_change_callbacks:
            try:
                callback(action, document)
            except Exception as e:
                logging.warning("Change callback failed: %s", e)

    def save_state(self, filepath: Path) -> None:
        """Save workspace state to file."""
        state = {
            "documents": [d.to_dict() for d in self._documents.values()],
            "saved_at": datetime.now().isoformat()
        }
        filepath.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def load_state(self, filepath: Path) -> bool:
        """Load workspace state from file."""
        if not filepath.exists():
            return False

        try:
            state = json.loads(filepath.read_text(encoding="utf-8"))
            self._documents.clear()

            for doc_data in state.get("documents", []):
                doc = DocumentItem.from_dict(doc_data)
                self._documents[doc.id] = doc

            self._notify_change("load", None)
            return True

        except Exception:
            return False

    def clear(self) -> None:
        """Remove all documents."""
        self._documents.clear()
        self._notify_change("clear", None)

    # ==================== RAG Integration ====================

    def _try_auto_extract(self, doc: DocumentItem) -> None:
        """Versucht automatische Textextraktion für ein Dokument."""
        try:
            if self._text_extractor is None:
                from .text_extractor import TextExtractor
                self._text_extractor = TextExtractor()

            doc.status = DocumentStatus.EXTRACTING
            self._notify_change("update", doc)

            result = self._text_extractor.extract(doc.path)

            if result.success:
                self.update_content(doc.id, result.text)
                logger.info(f"Auto-Extraktion: {doc.name} ({result.word_count} Woerter)")
            else:
                doc.status = DocumentStatus.ERROR
                doc.error_message = result.error
                self._notify_change("update", doc)
                logger.warning(f"Auto-Extraktion fehlgeschlagen: {doc.name}: {result.error}")

        except Exception as e:
            doc.status = DocumentStatus.ERROR
            doc.error_message = str(e)
            self._notify_change("update", doc)
            logger.error(f"Auto-Extraktion Fehler: {doc.name}: {e}")

    def set_rag_engine(self, rag_engine: 'RAGEngine') -> None:
        """
        Setzt die RAG Engine für semantische Suche.

        Args:
            rag_engine: Die RAG Engine Instanz
        """
        self._rag_engine = rag_engine
        logger.info("RAG Engine verbunden")

    def pop_pending_extractions(self) -> List[tuple]:
        """Gibt ausstehende Extraktionen zurück und leert die Queue.

        Returns:
            Liste von (doc_id, doc_path, doc_name) Tupeln
        """
        result = []
        for doc_id in self._pending_extractions:
            doc = self._documents.get(doc_id)
            if doc and not doc.is_directory:
                result.append((doc.id, doc.path, doc.name))
        self._pending_extractions.clear()
        return result

    def set_auto_index(self, enabled: bool) -> None:
        """Aktiviert/Deaktiviert automatische Indexierung."""
        self._auto_index = enabled

    def index_document(self, doc_id: str) -> bool:
        """
        Indexiert ein einzelnes Dokument im RAG-Index.

        Args:
            doc_id: Die Dokument-ID

        Returns:
            True bei Erfolg
        """
        if not self._rag_engine:
            logger.warning("RAG Engine nicht konfiguriert")
            return False

        doc = self._documents.get(doc_id)
        if not doc or doc.is_directory:
            return False

        if not doc.extracted_text:
            logger.warning(f"Dokument {doc_id} hat keinen extrahierten Text")
            return False

        try:
            result = self._rag_engine.index_document(
                content=doc.extracted_text,
                document_id=doc.id,
                source=str(doc.path),
                metadata={
                    "name": doc.name,
                    "extension": doc.extension,
                    "tags": doc.tags
                }
            )

            if result.success:
                doc.is_indexed = True
                doc.chunk_count = result.chunks_created
                self._notify_change("indexed", doc)
                logger.info(f"Dokument indexiert: {doc.name} ({result.chunks_created} Chunks)")
                return True
            else:
                logger.error(f"Indexierung fehlgeschlagen: {result.error}")
                return False

        except Exception as e:
            logger.error(f"Fehler bei Indexierung von {doc_id}: {e}")
            return False

    def index_all_documents(self) -> Dict[str, bool]:
        """
        Indexiert alle Dokumente mit extrahiertem Text.

        Returns:
            Dict mit doc_id -> Erfolg
        """
        results = {}
        for doc in self._documents.values():
            if not doc.is_directory and doc.extracted_text:
                results[doc.id] = self.index_document(doc.id)
        return results

    def index_selected_documents(self) -> Dict[str, bool]:
        """
        Indexiert nur ausgewählte Dokumente.

        Returns:
            Dict mit doc_id -> Erfolg
        """
        results = {}
        for doc in self.selected_documents:
            if doc.extracted_text:
                results[doc.id] = self.index_document(doc.id)
        return results

    def remove_from_index(self, doc_id: str) -> bool:
        """
        Entfernt ein Dokument aus dem RAG-Index.

        Args:
            doc_id: Die Dokument-ID

        Returns:
            True bei Erfolg
        """
        if not self._rag_engine:
            return False

        doc = self._documents.get(doc_id)
        if not doc:
            return False

        try:
            success = self._rag_engine.remove_document(doc_id)
            if success:
                doc.is_indexed = False
                doc.chunk_count = 0
                self._notify_change("deindexed", doc)
            return success
        except Exception as e:
            logger.error(f"Fehler beim Entfernen aus Index: {e}")
            return False

    def search_documents(
        self,
        query: str,
        k: int = 5,
        only_selected: bool = True
    ) -> List[Dict]:
        """
        Semantische Suche in Dokumenten.

        Args:
            query: Suchanfrage
            k: Anzahl Ergebnisse
            only_selected: Nur in ausgewählten Dokumenten suchen

        Returns:
            Liste von Suchergebnissen mit Chunks und Scores
        """
        if not self._rag_engine:
            logger.warning("RAG Engine nicht konfiguriert")
            return []

        # Filtere nach Dokument-IDs wenn nur ausgewählte
        doc_ids = None
        if only_selected:
            doc_ids = [d.id for d in self.selected_documents if d.is_indexed]

            if not doc_ids:
                logger.info("Keine indexierten Dokumente ausgewählt")
                return []

        try:
            results = self._rag_engine.search(
                query=query,
                k=k,
                document_ids=doc_ids
            )

            return [
                {
                    "content": doc.page_content,
                    "source": doc.metadata.get("source"),
                    "document_id": doc.metadata.get("document_id"),
                    "score": score
                }
                for doc, score in results
            ]

        except Exception as e:
            logger.error(f"Fehler bei Suche: {e}")
            return []

    def query_documents(
        self,
        question: str,
        k: int = 5,
        only_selected: bool = True
    ) -> Optional[Dict]:
        """
        RAG-Query: Suche + Antwortgenerierung.

        Args:
            question: Die Frage
            k: Anzahl Kontext-Dokumente
            only_selected: Nur ausgewählte Dokumente

        Returns:
            Dict mit answer, sources, confidence oder None
        """
        if not self._rag_engine:
            logger.warning("RAG Engine nicht konfiguriert")
            return None

        doc_ids = None
        if only_selected:
            doc_ids = [d.id for d in self.selected_documents if d.is_indexed]

            if not doc_ids:
                return {
                    "answer": "Keine indexierten Dokumente ausgewählt.",
                    "sources": [],
                    "confidence": 0.0
                }

        try:
            result = self._rag_engine.query(
                question=question,
                k=k,
                document_ids=doc_ids
            )

            return {
                "answer": result.answer,
                "sources": result.source_documents,
                "confidence": result.confidence,
                "query": result.query
            }

        except Exception as e:
            logger.error(f"Fehler bei Query: {e}")
            return None

    def get_rag_statistics(self) -> Dict:
        """Gibt RAG-Statistiken zurück."""
        indexed_docs = [d for d in self._documents.values() if d.is_indexed]
        total_chunks = sum(d.chunk_count for d in indexed_docs)

        stats = {
            "indexed_documents": len(indexed_docs),
            "total_chunks": total_chunks,
            "rag_enabled": self._rag_engine is not None,
            "auto_index": self._auto_index
        }

        if self._rag_engine:
            engine_stats = self._rag_engine.get_statistics()
            stats.update(engine_stats)

        return stats

    # Override update_content to auto-index
    def update_content(self, doc_id: str, text: str) -> None:
        """Update extracted text for a document."""
        doc = self._documents.get(doc_id)
        if doc:
            doc.extracted_text = text
            doc.text_length = len(text)
            doc.content_hash = hashlib.md5(text.encode()).hexdigest()
            doc.status = DocumentStatus.READY
            self._notify_change("update", doc)

            # Auto-indexieren wenn aktiviert
            if self._auto_index and self._rag_engine and text:
                self.index_document(doc_id)
