"""
Document Splitter - RecursiveCharacterTextSplitter für optimale Chunk-Erstellung
"""
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document as LangChainDocument
import logging

logger = logging.getLogger(__name__)


@dataclass
class ChunkMetadata:
    """Metadaten für einen Text-Chunk"""
    source: str
    chunk_index: int
    total_chunks: int
    start_char: int
    end_char: int
    document_id: Optional[str] = None


@dataclass
class TextChunk:
    """Ein Text-Chunk mit Metadaten"""
    content: str
    metadata: ChunkMetadata

    def to_langchain_document(self) -> LangChainDocument:
        """Konvertiert zu LangChain Document"""
        return LangChainDocument(
            page_content=self.content,
            metadata={
                "source": self.metadata.source,
                "chunk_index": self.metadata.chunk_index,
                "total_chunks": self.metadata.total_chunks,
                "start_char": self.metadata.start_char,
                "end_char": self.metadata.end_char,
                "document_id": self.metadata.document_id
            }
        )


class DocumentSplitter:
    """
    Intelligenter Dokument-Splitter mit RecursiveCharacterTextSplitter

    Teilt Texte hierarchisch nach:
    1. Paragraphen (\\n\\n)
    2. Zeilenumbrüche (\\n)
    3. Sätze (. ! ?)
    4. Wörter (Leerzeichen)
    5. Zeichen
    """

    # Vordefinierte Presets für verschiedene Anwendungsfälle
    PRESETS = {
        "default": {
            "chunk_size": 1000,
            "chunk_overlap": 200,
            "description": "Standard-Einstellung für die meisten Dokumente"
        },
        "precise": {
            "chunk_size": 500,
            "chunk_overlap": 100,
            "description": "Kleinere Chunks für präzise Antworten"
        },
        "context_heavy": {
            "chunk_size": 2000,
            "chunk_overlap": 400,
            "description": "Größere Chunks für mehr Kontext"
        },
        "code": {
            "chunk_size": 1500,
            "chunk_overlap": 200,
            "description": "Optimiert für Quellcode"
        },
        "summary": {
            "chunk_size": 3000,
            "chunk_overlap": 500,
            "description": "Große Chunks für Zusammenfassungen"
        }
    }

    # Standard-Separatoren für hierarchisches Splitting
    DEFAULT_SEPARATORS = [
        "\n\n",      # Paragraphen
        "\n",        # Zeilen
        ". ",        # Sätze
        "! ",        # Ausrufe
        "? ",        # Fragen
        "; ",        # Semikolon
        ", ",        # Komma
        " ",         # Wörter
        ""           # Zeichen
    ]

    # Separatoren für Code
    CODE_SEPARATORS = [
        "\nclass ",
        "\ndef ",
        "\n\tdef ",
        "\n\n",
        "\n",
        " ",
        ""
    ]

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        separators: Optional[List[str]] = None,
        is_code: bool = False
    ):
        """
        Initialisiert den Document Splitter

        Args:
            chunk_size: Maximale Größe eines Chunks in Zeichen
            chunk_overlap: Überlappung zwischen Chunks
            separators: Benutzerdefinierte Separatoren
            is_code: Ob es sich um Quellcode handelt
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        if separators:
            self.separators = separators
        elif is_code:
            self.separators = self.CODE_SEPARATORS
        else:
            self.separators = self.DEFAULT_SEPARATORS

        self._splitter = self._create_splitter()

    def _create_splitter(self) -> RecursiveCharacterTextSplitter:
        """Erstellt den LangChain TextSplitter"""
        return RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=self.separators,
            length_function=len,
            is_separator_regex=False
        )

    @classmethod
    def from_preset(cls, preset_name: str) -> 'DocumentSplitter':
        """
        Erstellt einen Splitter aus einem Preset

        Args:
            preset_name: Name des Presets (default, precise, context_heavy, code, summary)

        Returns:
            Konfigurierter DocumentSplitter
        """
        if preset_name not in cls.PRESETS:
            logger.warning(f"Preset '{preset_name}' nicht gefunden, verwende 'default'")
            preset_name = "default"

        preset = cls.PRESETS[preset_name]
        is_code = preset_name == "code"

        return cls(
            chunk_size=preset["chunk_size"],
            chunk_overlap=preset["chunk_overlap"],
            is_code=is_code
        )

    def split_text(
        self,
        text: str,
        source: str = "unknown",
        document_id: Optional[str] = None
    ) -> List[TextChunk]:
        """
        Teilt einen Text in Chunks

        Args:
            text: Der zu teilende Text
            source: Quellangabe (z.B. Dateiname)
            document_id: Optionale Dokument-ID

        Returns:
            Liste von TextChunk-Objekten
        """
        if not text or not text.strip():
            return []

        # Verwende LangChain Splitter
        raw_chunks = self._splitter.split_text(text)

        # Konvertiere zu TextChunk mit Metadaten
        chunks = []
        current_pos = 0

        for i, chunk_content in enumerate(raw_chunks):
            # Finde Position im Originaltext
            start_pos = text.find(chunk_content, current_pos)
            if start_pos == -1:
                start_pos = current_pos
            end_pos = start_pos + len(chunk_content)

            metadata = ChunkMetadata(
                source=source,
                chunk_index=i,
                total_chunks=len(raw_chunks),
                start_char=start_pos,
                end_char=end_pos,
                document_id=document_id
            )

            chunks.append(TextChunk(
                content=chunk_content,
                metadata=metadata
            ))

            current_pos = start_pos + 1

        logger.info(f"Text gesplittet: {len(chunks)} Chunks aus '{source}'")
        return chunks

    def split_documents(
        self,
        documents: List[Dict[str, Any]]
    ) -> List[TextChunk]:
        """
        Teilt mehrere Dokumente in Chunks

        Args:
            documents: Liste von Dokumenten mit 'content', 'path', und optional 'id'

        Returns:
            Liste aller TextChunks
        """
        all_chunks = []

        for doc in documents:
            content = doc.get("content", "")
            source = doc.get("path", "unknown")
            doc_id = doc.get("id")

            chunks = self.split_text(content, source, doc_id)
            all_chunks.extend(chunks)

        logger.info(f"Gesamt: {len(all_chunks)} Chunks aus {len(documents)} Dokumenten")
        return all_chunks

    def to_langchain_documents(
        self,
        chunks: List[TextChunk]
    ) -> List[LangChainDocument]:
        """
        Konvertiert TextChunks zu LangChain Documents

        Args:
            chunks: Liste von TextChunks

        Returns:
            Liste von LangChain Document-Objekten
        """
        return [chunk.to_langchain_document() for chunk in chunks]

    def get_config(self) -> dict:
        """Gibt die aktuelle Konfiguration zurück"""
        return {
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "separators": self.separators
        }

    def update_config(
        self,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None
    ) -> None:
        """
        Aktualisiert die Splitter-Konfiguration

        Args:
            chunk_size: Neue Chunk-Größe
            chunk_overlap: Neue Überlappung
        """
        if chunk_size is not None:
            self.chunk_size = chunk_size
        if chunk_overlap is not None:
            self.chunk_overlap = chunk_overlap

        self._splitter = self._create_splitter()
        logger.info(f"Splitter aktualisiert: size={self.chunk_size}, overlap={self.chunk_overlap}")

    @classmethod
    def list_presets(cls) -> List[dict]:
        """Listet alle verfügbaren Presets"""
        return [
            {"id": k, **v} for k, v in cls.PRESETS.items()
        ]
