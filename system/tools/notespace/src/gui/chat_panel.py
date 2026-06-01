#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chat Panel - Interactive LLM chat over documents
================================================

Features:
- Chat interface for document discussions
- Context-aware responses based on loaded documents
- RAG-basierte semantische Suche mit ChromaDB
- Message history
- Streaming responses
"""

from datetime import datetime
from typing import List, Optional, Callable, TYPE_CHECKING
from dataclasses import dataclass, field
import logging

if TYPE_CHECKING:
    from ..rag.engine import RAGEngine
    from ..core.document_manager import DocumentManager

logger = logging.getLogger(__name__)

try:
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit,
        QPushButton, QLabel, QScrollArea, QFrame, QSplitter
    )
    from PySide6.QtCore import Qt, Signal, QThread, QTimer
    from PySide6.QtGui import QTextCursor, QFont
    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False
    class QWidget: pass
    class QThread: pass
    class Signal:
        def __init__(self, *args): pass


@dataclass
class ChatMessage:
    """A single chat message."""
    role: str  # user, assistant, system
    content: str
    timestamp: datetime
    document_refs: List[str] = None  # Referenced document IDs
    sources: List[dict] = None  # RAG source documents
    confidence: float = 0.0  # RAG confidence score

    def __post_init__(self):
        if self.document_refs is None:
            self.document_refs = []
        if self.sources is None:
            self.sources = []


class MessageWidget(QFrame if PYSIDE_AVAILABLE else object):
    """Widget for displaying a single chat message."""

    def __init__(self, message: ChatMessage, parent=None):
        if not PYSIDE_AVAILABLE:
            return
        super().__init__(parent)
        self.message = message
        self._setup_ui()

    def _setup_ui(self):
        self.setFrameStyle(QFrame.Shape.StyledPanel)

        # Style based on role
        if self.message.role == "user":
            self.setStyleSheet("""
                MessageWidget {
                    background-color: #e8f4fd;
                    border-radius: 10px;
                    margin: 5px 50px 5px 10px;
                    padding: 10px;
                }
            """)
        elif self.message.role == "assistant":
            self.setStyleSheet("""
                MessageWidget {
                    background-color: #f5f5f5;
                    border-radius: 10px;
                    margin: 5px 10px 5px 50px;
                    padding: 10px;
                }
            """)
        else:  # system
            self.setStyleSheet("""
                MessageWidget {
                    background-color: #fff3cd;
                    border-radius: 10px;
                    margin: 5px;
                    padding: 10px;
                }
            """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)

        # Header with role and time
        header = QHBoxLayout()

        role_text = {
            "user": "Du",
            "assistant": "Assistent",
            "system": "System"
        }.get(self.message.role, self.message.role)

        self.role_label = QLabel(role_text)
        self.role_label.setStyleSheet("font-weight: bold; font-size: 11px;")

        self.time_label = QLabel(self.message.timestamp.strftime("%H:%M"))
        self.time_label.setStyleSheet("color: #888; font-size: 10px;")

        header.addWidget(self.role_label)
        header.addStretch()
        header.addWidget(self.time_label)

        layout.addLayout(header)

        # Content
        self.content_label = QLabel(self.message.content)
        self.content_label.setWordWrap(True)
        self.content_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse |
            Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        layout.addWidget(self.content_label)

        # Document references
        if self.message.document_refs:
            refs_label = QLabel(f"Dokumente: {', '.join(self.message.document_refs)}")
            refs_label.setStyleSheet("color: #666; font-size: 10px; font-style: italic;")
            layout.addWidget(refs_label)

        # RAG Sources
        if self.message.sources:
            sources_text = "Quellen: "
            source_names = list(set(s.get('source', 'Unbekannt').split('/')[-1] for s in self.message.sources[:3]))
            sources_text += ", ".join(source_names)
            if self.message.confidence > 0:
                sources_text += f" (Konfidenz: {self.message.confidence:.0%})"

            sources_label = QLabel(sources_text)
            sources_label.setStyleSheet("color: #27ae60; font-size: 10px; font-style: italic;")
            sources_label.setWordWrap(True)
            layout.addWidget(sources_label)

    def update_content(self, content: str):
        """Update the message content (for streaming)."""
        self.message.content = content
        self.content_label.setText(content)


class LLMWorker(QThread if PYSIDE_AVAILABLE else object):
    """Worker thread for LLM API calls."""

    if PYSIDE_AVAILABLE:
        response_chunk = Signal(str)
        response_complete = Signal(str)
        error_occurred = Signal(str)

    def __init__(self, llm_client, prompt: str, context: str):
        if not PYSIDE_AVAILABLE:
            return
        super().__init__()
        self.llm_client = llm_client
        self.prompt = prompt
        self.context = context
        self._stop_requested = False

    def run(self):
        """Execute the LLM call."""
        try:
            full_response = ""

            # Stream the response
            for chunk in self.llm_client.stream_chat(self.prompt, self.context):
                if self._stop_requested:
                    break
                full_response += chunk
                self.response_chunk.emit(chunk)

            self.response_complete.emit(full_response)

        except Exception as e:
            self.error_occurred.emit(str(e))

    def stop(self):
        """Request stop."""
        self._stop_requested = True


class RAGWorker(QThread if PYSIDE_AVAILABLE else object):
    """Worker thread for RAG queries."""

    if PYSIDE_AVAILABLE:
        response_ready = Signal(dict)
        error_occurred = Signal(str)

    def __init__(self, rag_engine: 'RAGEngine', question: str, document_ids: List[str] = None, k: int = 5):
        if not PYSIDE_AVAILABLE:
            return
        super().__init__()
        self.rag_engine = rag_engine
        self.question = question
        self.document_ids = document_ids
        self.k = k

    def run(self):
        """Execute the RAG query."""
        try:
            result = self.rag_engine.query(
                question=self.question,
                k=self.k,
                document_ids=self.document_ids
            )

            self.response_ready.emit({
                "answer": result.answer,
                "sources": result.source_documents,
                "confidence": result.confidence,
                "query": result.query
            })

        except Exception as e:
            logger.error(f"RAG Worker Fehler: {e}")
            self.error_occurred.emit(str(e))


class ChatPanel(QWidget if PYSIDE_AVAILABLE else object):
    """
    Panel for interactive LLM chat.

    Signals:
        message_sent: Emitted when user sends a message
    """

    if PYSIDE_AVAILABLE:
        message_sent = Signal(str)

    def __init__(self, parent=None):
        if not PYSIDE_AVAILABLE:
            raise ImportError("PySide6 is required. Install with: pip install PySide6")

        super().__init__(parent)
        self._messages: List[ChatMessage] = []
        self._message_widgets: List[MessageWidget] = []
        self._llm_client = None
        self._document_context = ""
        self._current_worker: Optional[LLMWorker] = None
        self._streaming_widget: Optional[MessageWidget] = None

        # RAG Integration
        self._rag_engine: Optional['RAGEngine'] = None
        self._document_manager: Optional['DocumentManager'] = None
        self._use_rag: bool = True  # RAG bevorzugen wenn verfügbar
        self._rag_k: int = 5  # Anzahl Kontext-Chunks

        self._setup_ui()

    def _setup_ui(self):
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Header
        header = QHBoxLayout()
        title = QLabel("Dokumenten-Chat")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")

        self.clear_btn = QPushButton("Verlauf löschen")
        self.clear_btn.clicked.connect(self._clear_history)

        # RAG Toggle
        self.rag_toggle = QPushButton("RAG: AN")
        self.rag_toggle.setCheckable(True)
        self.rag_toggle.setChecked(True)
        self.rag_toggle.clicked.connect(self._toggle_rag)
        self.rag_toggle.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                border: none;
                padding: 5px 10px;
                border-radius: 3px;
                font-size: 10px;
            }
            QPushButton:checked {
                background-color: #27ae60;
            }
            QPushButton:!checked {
                background-color: #95a5a6;
            }
        """)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.rag_toggle)
        header.addWidget(self.clear_btn)

        layout.addLayout(header)

        # Chat history
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.messages_container = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.messages_layout.addStretch()

        scroll.setWidget(self.messages_container)
        layout.addWidget(scroll, stretch=1)

        self.scroll_area = scroll

        # Input area
        input_frame = QFrame()
        input_frame.setStyleSheet("""
            QFrame {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 5px;
            }
        """)
        input_layout = QHBoxLayout(input_frame)

        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Frage zu den Dokumenten stellen...")
        self.input_edit.returnPressed.connect(self._send_message)
        self.input_edit.setStyleSheet("""
            QLineEdit {
                border: none;
                background: transparent;
                padding: 10px;
                font-size: 13px;
            }
        """)

        self.send_btn = QPushButton("Senden")
        self.send_btn.clicked.connect(self._send_message)
        self.send_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
            }
        """)

        input_layout.addWidget(self.input_edit)
        input_layout.addWidget(self.send_btn)

        layout.addWidget(input_frame)

        # Status
        self.status_label = QLabel("Bereit")
        self.status_label.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(self.status_label)

        # Add welcome message
        self._add_system_message(
            "Willkommen! Ich kann Fragen zu den geladenen Dokumenten beantworten. "
            "Wähle Dokumente aus und stelle Fragen zum Inhalt."
        )

    def set_llm_client(self, client):
        """Set the LLM client for chat."""
        self._llm_client = client

    def set_rag_engine(self, rag_engine: 'RAGEngine'):
        """Set the RAG engine for semantic search."""
        self._rag_engine = rag_engine
        self._update_rag_status()
        logger.info("RAG Engine im Chat-Panel verbunden")

    def set_document_manager(self, doc_manager: 'DocumentManager'):
        """Set the document manager for RAG queries."""
        self._document_manager = doc_manager

    def set_document_context(self, context: str):
        """Set the document context for the chat."""
        self._document_context = context
        doc_count = context.count("---")
        self._update_status()

    def _toggle_rag(self):
        """Toggle RAG mode."""
        self._use_rag = self.rag_toggle.isChecked()
        self.rag_toggle.setText("RAG: AN" if self._use_rag else "RAG: AUS")
        self._update_status()

    def _update_rag_status(self):
        """Update RAG status display."""
        if self._rag_engine:
            stats = self._rag_engine.get_statistics()
            self.rag_toggle.setToolTip(
                f"ChromaDB: {stats.get('total_chunks', 0)} Chunks indexiert\n"
                f"Embedding: {stats.get('embedding_model', 'N/A')}"
            )

    def _update_status(self):
        """Update status label."""
        parts = []

        if self._use_rag and self._rag_engine:
            stats = self._rag_engine.get_statistics()
            parts.append(f"RAG: {stats.get('total_chunks', 0)} Chunks")
        elif self._document_context:
            parts.append(f"Kontext: ~{len(self._document_context)} Zeichen")

        if self._document_manager:
            selected = len(self._document_manager.selected_documents)
            indexed = len([d for d in self._document_manager.selected_documents if d.is_indexed])
            parts.append(f"Docs: {indexed}/{selected} indexiert")

        self.status_label.setText(" | ".join(parts) if parts else "Bereit")

    def _send_message(self):
        """Send the user's message."""
        text = self.input_edit.text().strip()
        if not text:
            return

        self.input_edit.clear()

        # Add user message
        user_msg = ChatMessage("user", text, datetime.now())
        self._add_message(user_msg)

        # Signal
        self.message_sent.emit(text)

        # Get response - RAG oder Legacy
        if self._use_rag and self._rag_engine:
            self._request_rag_response(text)
        elif self._llm_client:
            self._request_response(text)
        else:
            self._add_system_message("Kein LLM-Client oder RAG-Engine konfiguriert. Bitte Einstellungen prüfen.")

    def _request_response(self, prompt: str):
        """Request a response from the LLM."""
        if self._current_worker and self._current_worker.isRunning():
            return

        # Disable input
        self.input_edit.setEnabled(False)
        self.send_btn.setEnabled(False)
        self.status_label.setText("Generiere Antwort...")

        # Create streaming message widget
        streaming_msg = ChatMessage("assistant", "", datetime.now())
        self._streaming_widget = self._add_message(streaming_msg)

        # Build context prompt -- optimized for small models (qwen3:4b etc.)
        context_prompt = f"""Du bist ein Dokumentenanalyse-Assistent.
PRIORITAET: Beantworte die Nutzerfrage direkt und praezise.
REGEL: Nur Informationen aus dem Kontext verwenden. Wenn nicht vorhanden, sage das.
SPRACHE: Deutsch.

=== KONTEXT ===
{self._document_context[:50000]}

=== FRAGE ===
{prompt}"""

        # Start worker
        self._current_worker = LLMWorker(self._llm_client, prompt, context_prompt)
        self._current_worker.response_chunk.connect(self._on_response_chunk)
        self._current_worker.response_complete.connect(self._on_response_complete)
        self._current_worker.error_occurred.connect(self._on_response_error)
        self._current_worker.start()

    def _on_response_chunk(self, chunk: str):
        """Handle streaming response chunk."""
        if self._streaming_widget:
            current = self._streaming_widget.message.content
            self._streaming_widget.update_content(current + chunk)
            self._scroll_to_bottom()

    def _on_response_complete(self, response: str):
        """Handle complete response."""
        self.input_edit.setEnabled(True)
        self.send_btn.setEnabled(True)
        self.status_label.setText("Bereit")
        self._streaming_widget = None
        self._scroll_to_bottom()

    def _on_response_error(self, error: str):
        """Handle response error."""
        self.input_edit.setEnabled(True)
        self.send_btn.setEnabled(True)
        self.status_label.setText("Fehler")

        # Update streaming widget with error
        if self._streaming_widget:
            self._streaming_widget.update_content(f"Fehler: {error}")
        else:
            self._add_system_message(f"Fehler: {error}")

        self._streaming_widget = None

    # ==================== RAG Methods ====================

    def _request_rag_response(self, question: str):
        """Request a RAG-based response."""
        # Disable input
        self.input_edit.setEnabled(False)
        self.send_btn.setEnabled(False)
        self.status_label.setText("🔍 RAG-Suche...")

        # Get selected document IDs for filtering
        doc_ids = None
        if self._document_manager:
            selected_docs = self._document_manager.selected_documents
            indexed_docs = [d for d in selected_docs if d.is_indexed]
            if indexed_docs:
                doc_ids = [d.id for d in indexed_docs]
            else:
                # Keine indexierten Dokumente
                self._add_system_message(
                    "⚠️ Keine indexierten Dokumente gefunden. "
                    "Bitte Dokumente laden und indexieren (automatisch bei Text-Extraktion)."
                )
                self.input_edit.setEnabled(True)
                self.send_btn.setEnabled(True)
                self._update_status()
                return

        # Start RAG worker
        self._current_worker = RAGWorker(
            rag_engine=self._rag_engine,
            question=question,
            document_ids=doc_ids,
            k=self._rag_k
        )
        self._current_worker.response_ready.connect(self._on_rag_response)
        self._current_worker.error_occurred.connect(self._on_rag_error)
        self._current_worker.start()

    def _on_rag_response(self, result: dict):
        """Handle RAG response."""
        self.input_edit.setEnabled(True)
        self.send_btn.setEnabled(True)
        self._update_status()

        # Create assistant message with sources
        assistant_msg = ChatMessage(
            role="assistant",
            content=result.get("answer", "Keine Antwort erhalten."),
            timestamp=datetime.now(),
            sources=result.get("sources", []),
            confidence=result.get("confidence", 0.0)
        )
        self._add_message(assistant_msg)

        # Log for debugging
        logger.info(f"RAG Response: {len(result.get('sources', []))} Quellen, Konfidenz: {result.get('confidence', 0):.2%}")

    def _on_rag_error(self, error: str):
        """Handle RAG error."""
        self.input_edit.setEnabled(True)
        self.send_btn.setEnabled(True)
        self._update_status()

        self._add_system_message(f"❌ RAG-Fehler: {error}")
        logger.error(f"RAG Error: {error}")

    def set_rag_k(self, k: int):
        """Set the number of context chunks for RAG."""
        self._rag_k = max(1, min(k, 20))
        logger.info(f"RAG k={self._rag_k}")

    def _add_message(self, message: ChatMessage) -> MessageWidget:
        """Add a message to the chat."""
        self._messages.append(message)

        widget = MessageWidget(message, self.messages_container)
        self._message_widgets.append(widget)

        # Insert before stretch
        self.messages_layout.insertWidget(
            self.messages_layout.count() - 1,
            widget
        )

        self._scroll_to_bottom()
        return widget

    def _add_system_message(self, text: str):
        """Add a system message."""
        msg = ChatMessage("system", text, datetime.now())
        self._add_message(msg)

    def _scroll_to_bottom(self):
        """Scroll to the bottom of the chat."""
        QTimer.singleShot(50, lambda: self.scroll_area.verticalScrollBar().setValue(
            self.scroll_area.verticalScrollBar().maximum()
        ))

    def _clear_history(self):
        """Clear chat history."""
        for widget in self._message_widgets:
            widget.deleteLater()

        self._messages.clear()
        self._message_widgets.clear()

        self._add_system_message("Verlauf gelöscht. Stelle eine neue Frage.")

    def stop_generation(self):
        """Stop the current generation."""
        if self._current_worker and self._current_worker.isRunning():
            self._current_worker.stop()
            self._current_worker.wait()
            self._on_response_error("Abgebrochen")

    def get_messages(self) -> List[ChatMessage]:
        """Get all messages."""
        return list(self._messages)

    def export_chat(self) -> str:
        """Export chat history as text."""
        lines = []
        for msg in self._messages:
            role = {"user": "Du", "assistant": "Assistent", "system": "System"}.get(msg.role, msg.role)
            lines.append(f"[{msg.timestamp.strftime('%H:%M')}] {role}:")
            lines.append(msg.content)
            lines.append("")
        return "\n".join(lines)
