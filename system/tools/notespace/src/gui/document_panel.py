#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Document Panel - File/Directory management with Drag & Drop
============================================================

Features:
- Drag & drop file/folder addition
- Tree view of documents
- Checkbox selection for report inclusion
- Right-click context menu for sub-queries
- Status indicators
"""

from pathlib import Path
from typing import Optional, List, Callable

try:
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
        QPushButton, QMenu, QFileDialog, QLabel, QProgressBar,
        QInputDialog, QMessageBox, QHeaderView, QAbstractItemView
    )
    from PySide6.QtCore import Qt, QMimeData, Signal
    from PySide6.QtGui import QDragEnterEvent, QDropEvent, QAction, QIcon
    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False
    # Stub classes for import
    class QWidget:
        pass
    class Signal:
        def __init__(self, *args): pass


class DocumentPanel(QWidget if PYSIDE_AVAILABLE else object):
    """
    Panel for managing documents in a project.

    Signals:
        document_selected: Emitted when a document is clicked
        selection_changed: Emitted when checkbox selection changes
        subquery_requested: Emitted when user requests a sub-query
    """

    if PYSIDE_AVAILABLE:
        document_selected = Signal(str)  # document_id
        selection_changed = Signal()
        subquery_requested = Signal(str, str, str)  # doc_id, query_type, query_text
        files_added = Signal()  # Emitted after files were added (for async extraction)

    def __init__(self, parent=None):
        if not PYSIDE_AVAILABLE:
            raise ImportError("PySide6 is required. Install with: pip install PySide6")

        super().__init__(parent)
        self._document_manager = None
        self._subquery_manager = None
        self._item_map = {}  # doc_id -> QTreeWidgetItem

        self._setup_ui()
        self._setup_drag_drop()

    def _setup_ui(self):
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Header with buttons
        header = QHBoxLayout()

        self.add_files_btn = QPushButton("+ Dateien")
        self.add_files_btn.clicked.connect(self._on_add_files)

        self.add_folder_btn = QPushButton("+ Ordner")
        self.add_folder_btn.clicked.connect(self._on_add_folder)

        self.select_all_btn = QPushButton("Alle")
        self.select_all_btn.clicked.connect(self._on_select_all)

        self.deselect_all_btn = QPushButton("Keine")
        self.deselect_all_btn.clicked.connect(self._on_deselect_all)

        header.addWidget(self.add_files_btn)
        header.addWidget(self.add_folder_btn)
        header.addStretch()
        header.addWidget(self.select_all_btn)
        header.addWidget(self.deselect_all_btn)

        layout.addLayout(header)

        # Document tree
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Dokument", "Status", "Größe"])
        self.tree.setColumnCount(3)

        # Enable drag & drop
        self.tree.setAcceptDrops(True)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

        # Selection
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        # Sizing
        header_view = self.tree.header()
        header_view.setStretchLastSection(False)
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        # Context menu
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)

        # Signals
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemChanged.connect(self._on_item_changed)

        layout.addWidget(self.tree)

        # Status bar
        self.status_label = QLabel("Keine Dokumente")
        layout.addWidget(self.status_label)

        # Progress bar (hidden by default)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

    def _setup_drag_drop(self):
        """Configure drag and drop."""
        self.setAcceptDrops(True)

    def set_managers(self, document_manager, subquery_manager):
        """Set the document and sub-query managers."""
        self._document_manager = document_manager
        self._subquery_manager = subquery_manager

        # Register for changes
        document_manager.on_change(self._on_document_change)

        # Load existing documents
        self._refresh_tree()

    def _refresh_tree(self):
        """Refresh the document tree."""
        self.tree.clear()
        self._item_map.clear()

        if not self._document_manager:
            return

        # Block signals during refresh
        self.tree.blockSignals(True)

        # Add root documents
        for doc in self._document_manager.root_documents:
            self._add_document_item(doc, None)

        self.tree.blockSignals(False)

        # Update status
        self._update_status()

    def _add_document_item(self, doc, parent_item):
        """Add a document item to the tree."""
        if parent_item:
            item = QTreeWidgetItem(parent_item)
        else:
            item = QTreeWidgetItem(self.tree)

        # Store mapping
        self._item_map[doc.id] = item
        item.setData(0, Qt.ItemDataRole.UserRole, doc.id)

        # Set text
        item.setText(0, doc.name)
        item.setText(1, self._status_text(doc.status))
        item.setText(2, self._format_size(doc.size_bytes))

        # Checkbox for selection
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Checked if doc.is_selected else Qt.CheckState.Unchecked)

        # Icon based on type
        if doc.is_directory:
            item.setExpanded(True)
            # Add children
            for child in self._document_manager.get_children(doc.id):
                self._add_document_item(child, item)

        return item

    def _status_text(self, status) -> str:
        """Convert status enum to display text."""
        from ..core.document_manager import DocumentStatus
        status_map = {
            DocumentStatus.PENDING: "Ausstehend",
            DocumentStatus.EXTRACTING: "Extrahiere...",
            DocumentStatus.READY: "Bereit",
            DocumentStatus.ANALYZING: "Analysiere...",
            DocumentStatus.COMPLETED: "Fertig",
            DocumentStatus.ERROR: "Fehler"
        }
        return status_map.get(status, str(status.value))

    def _format_size(self, size_bytes: int) -> str:
        """Format file size for display."""
        if size_bytes == 0:
            return "-"
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"

    def _update_status(self):
        """Update the status label."""
        if not self._document_manager:
            self.status_label.setText("Keine Dokumente")
            return

        stats = self._document_manager.get_statistics()
        self.status_label.setText(
            f"{stats['selected_documents']} von {stats['total_documents']} ausgewählt"
        )

    def _on_document_change(self, action: str, document):
        """Handle document manager changes."""
        if action in ("add", "remove", "load", "clear"):
            self._refresh_tree()
        elif action in ("update", "bulk_update"):
            self._refresh_tree()

    def _on_item_clicked(self, item, column):
        """Handle item click."""
        try:
            doc_id = item.data(0, Qt.ItemDataRole.UserRole)
            if doc_id:
                self.document_selected.emit(doc_id)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Fehler bei Item-Klick: {e}")

    def _on_item_changed(self, item, column):
        """Handle item checkbox change."""
        if column == 0:
            try:
                doc_id = item.data(0, Qt.ItemDataRole.UserRole)
                if doc_id and self._document_manager:
                    checked = item.checkState(0) == Qt.CheckState.Checked
                    self._document_manager.set_selection(doc_id, checked)
                    self._update_status()
                    self.selection_changed.emit()
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Fehler bei Checkbox-Änderung: {e}")

    def _show_context_menu(self, position):
        """Show context menu on right-click."""
        item = self.tree.itemAt(position)
        if not item:
            return

        doc_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not doc_id:
            return

        doc = self._document_manager.get_document(doc_id)
        if not doc or doc.is_directory:
            return

        menu = QMenu(self)

        # Sub-query actions
        menu.addAction("Zusammenfassung erstellen", lambda: self._add_subquery(doc_id, "summary"))
        menu.addAction("Informationen extrahieren...", lambda: self._add_subquery_custom(doc_id, "extract"))
        menu.addAction("Analysieren...", lambda: self._add_subquery_custom(doc_id, "analyze"))
        menu.addAction("Frage stellen...", lambda: self._add_subquery_custom(doc_id, "question"))

        menu.addSeparator()

        # Quick templates
        submenu = menu.addMenu("Schnellanalyse")
        submenu.addAction("Kernaussagen", lambda: self._add_subquery(doc_id, "key_points"))
        submenu.addAction("Zeitachse", lambda: self._add_subquery(doc_id, "timeline"))
        submenu.addAction("Personen/Orte", lambda: self._add_subquery(doc_id, "entities"))

        menu.addSeparator()

        # Document actions
        menu.addAction("Entfernen", lambda: self._remove_document(doc_id))

        menu.exec(self.tree.mapToGlobal(position))

    def _add_subquery(self, doc_id: str, query_type: str):
        """Add a predefined sub-query."""
        from ..core.sub_query import SubQueryTemplates, SubQueryType

        if not self._subquery_manager:
            return

        templates = {
            "summary": lambda: SubQueryTemplates.key_points(doc_id),
            "key_points": lambda: SubQueryTemplates.key_points(doc_id),
            "timeline": lambda: SubQueryTemplates.timeline(doc_id),
            "entities": lambda: SubQueryTemplates.entities(doc_id),
        }

        if query_type in templates:
            query = templates[query_type]()
            self._subquery_manager.add_query(query)
            self._document_manager.add_sub_query(doc_id, query.id)
            self.subquery_requested.emit(doc_id, query_type, query.query_text)

    def _add_subquery_custom(self, doc_id: str, query_type: str):
        """Add a custom sub-query with user input."""
        prompts = {
            "extract": "Welche Informationen extrahieren?",
            "analyze": "Was soll analysiert werden?",
            "question": "Welche Frage stellen?"
        }

        text, ok = QInputDialog.getText(
            self,
            "Detailrecherche",
            prompts.get(query_type, "Eingabe:")
        )

        if ok and text and self._subquery_manager:
            from ..core.sub_query import SubQuery, SubQueryType

            type_map = {
                "extract": SubQueryType.EXTRACT,
                "analyze": SubQueryType.ANALYZE,
                "question": SubQueryType.QUESTION
            }

            query = SubQuery.create(doc_id, type_map.get(query_type, SubQueryType.CUSTOM), text)
            self._subquery_manager.add_query(query)
            self._document_manager.add_sub_query(doc_id, query.id)
            self.subquery_requested.emit(doc_id, query_type, text)

    def _remove_document(self, doc_id: str):
        """Remove a document."""
        if self._document_manager:
            # Also remove sub-queries
            if self._subquery_manager:
                self._subquery_manager.remove_queries_for_document(doc_id)
            self._document_manager.remove_document(doc_id)

    def _on_add_files(self):
        """Handle add files button."""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Dateien hinzufügen",
            "",
            "Alle unterstützten (*.pdf *.docx *.doc *.rtf *.txt *.md *.xlsx *.xls *.pptx *.py *.csv *.json *.xml *.eml *.msg);;Dokumente (*.pdf *.docx *.doc *.rtf *.txt *.md);;Tabellen (*.xlsx *.xls *.csv);;Code (*.py *.js *.java *.cpp *.c *.h);;Alle Dateien (*)"
        )

        if files and self._document_manager:
            for filepath in files:
                self._document_manager.add_file(Path(filepath))
            self.files_added.emit()

    def _on_add_folder(self):
        """Handle add folder button."""
        folder = QFileDialog.getExistingDirectory(self, "Ordner hinzufügen")

        if folder and self._document_manager:
            self._document_manager.add_directory(Path(folder))

    def _on_select_all(self):
        """Select all documents."""
        if self._document_manager:
            self._document_manager.select_all()
            self._refresh_tree()

    def _on_deselect_all(self):
        """Deselect all documents."""
        if self._document_manager:
            self._document_manager.deselect_all()
            self._refresh_tree()

    # Drag and Drop handlers
    def dragEnterEvent(self, event: 'QDragEnterEvent'):
        """Handle drag enter."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: 'QDropEvent'):
        """Handle drop event."""
        if not self._document_manager:
            return

        urls = event.mimeData().urls()
        for url in urls:
            try:
                path = Path(url.toLocalFile())
                if path.is_dir():
                    self._document_manager.add_directory(path)
                elif path.is_file():
                    self._document_manager.add_file(path)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Fehler beim Hinzufügen von {url.toLocalFile()}: {e}")

        event.acceptProposedAction()
        self.files_added.emit()

    def set_progress(self, value: int, maximum: int = 100):
        """Set progress bar value."""
        self.progress_bar.setMaximum(maximum)
        self.progress_bar.setValue(value)
        self.progress_bar.setVisible(value < maximum)
