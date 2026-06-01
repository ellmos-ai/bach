#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Output Panel - Report display and export configuration
======================================================

Features:
- Live report preview
- Output format selection
- Export directory configuration
- Multi-format export
"""

import os
from pathlib import Path
from typing import List, Optional

try:
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLabel,
        QPushButton, QComboBox, QFileDialog, QGroupBox, QCheckBox,
        QLineEdit, QFormLayout, QProgressBar, QTabWidget,
        QMessageBox, QSplitter
    )
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QFont, QTextCharFormat, QSyntaxHighlighter
    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False
    class QWidget: pass
    class Signal:
        def __init__(self, *args): pass


class MarkdownHighlighter(QSyntaxHighlighter if PYSIDE_AVAILABLE else object):
    """Simple Markdown syntax highlighter."""

    def __init__(self, document):
        if not PYSIDE_AVAILABLE:
            return
        super().__init__(document)
        self._setup_formats()

    def _setup_formats(self):
        from PySide6.QtGui import QTextCharFormat, QColor, QFont

        # Headers
        self.header_format = QTextCharFormat()
        self.header_format.setFontWeight(QFont.Weight.Bold)
        self.header_format.setForeground(QColor("#2c3e50"))

        # Bold
        self.bold_format = QTextCharFormat()
        self.bold_format.setFontWeight(QFont.Weight.Bold)

        # Code
        self.code_format = QTextCharFormat()
        self.code_format.setFontFamily("Consolas")
        self.code_format.setBackground(QColor("#f5f5f5"))

        # List
        self.list_format = QTextCharFormat()
        self.list_format.setForeground(QColor("#27ae60"))

    def highlightBlock(self, text):
        import re

        # Headers
        if text.startswith("#"):
            self.setFormat(0, len(text), self.header_format)

        # Bold **text**
        for match in re.finditer(r'\*\*(.+?)\*\*', text):
            self.setFormat(match.start(), match.end() - match.start(), self.bold_format)

        # Code `text`
        for match in re.finditer(r'`(.+?)`', text):
            self.setFormat(match.start(), match.end() - match.start(), self.code_format)

        # Lists
        if re.match(r'^[\-\*]\s', text):
            self.setFormat(0, 2, self.list_format)


class OutputPanel(QWidget if PYSIDE_AVAILABLE else object):
    """
    Panel for report display and export.

    Signals:
        export_requested: Emitted when export is requested
    """

    if PYSIDE_AVAILABLE:
        export_requested = Signal(list, str)  # formats, directory
        prompt_export_requested = Signal()  # Prompt als .md exportieren

    def __init__(self, parent=None):
        if not PYSIDE_AVAILABLE:
            raise ImportError("PySide6 is required. Install with: pip install PySide6")

        super().__init__(parent)
        self._current_content = ""
        self._output_directory = Path.home() / "Documents"

        self._setup_ui()

    def _setup_ui(self):
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Tab widget for preview and settings
        tabs = QTabWidget()

        # Preview tab
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)

        # Preview header
        preview_header = QHBoxLayout()

        preview_label = QLabel("Bericht-Vorschau")
        preview_label.setStyleSheet("font-weight: bold;")

        self.copy_btn = QPushButton("Kopieren")
        self.copy_btn.clicked.connect(self._copy_to_clipboard)

        preview_header.addWidget(preview_label)
        preview_header.addStretch()
        preview_header.addWidget(self.copy_btn)

        preview_layout.addLayout(preview_header)

        # Preview text
        self.preview_edit = QTextEdit()
        self.preview_edit.setReadOnly(True)
        self.preview_edit.setFont(QFont("Consolas", 10))
        self.preview_edit.setStyleSheet("""
            QTextEdit {
                background-color: #fafafa;
                border: 1px solid #ddd;
                border-radius: 5px;
                padding: 10px;
            }
        """)

        # Add highlighter
        self.highlighter = MarkdownHighlighter(self.preview_edit.document())

        preview_layout.addWidget(self.preview_edit)

        tabs.addTab(preview_widget, "Vorschau")

        # Export settings tab
        export_widget = QWidget()
        export_layout = QVBoxLayout(export_widget)

        # Output directory
        dir_group = QGroupBox("Ausgabeordner")
        dir_layout = QHBoxLayout(dir_group)

        self.dir_edit = QLineEdit(str(self._output_directory))
        self.dir_edit.setReadOnly(True)

        self.browse_btn = QPushButton("Durchsuchen...")
        self.browse_btn.clicked.connect(self._browse_directory)

        dir_layout.addWidget(self.dir_edit)
        dir_layout.addWidget(self.browse_btn)

        export_layout.addWidget(dir_group)

        # Output formats
        format_group = QGroupBox("Ausgabeformate")
        format_layout = QVBoxLayout(format_group)

        self.format_checks = {}

        formats = [
            ("md", "Markdown (.md)", True),
            ("pdf", "PDF (.pdf)", True),
            ("docx", "Word (.docx)", False),
            ("txt", "Text (.txt)", False),
            ("html", "HTML (.html)", False)
        ]

        for fmt, label, default in formats:
            cb = QCheckBox(label)
            cb.setChecked(default)
            self.format_checks[fmt] = cb
            format_layout.addWidget(cb)

        export_layout.addWidget(format_group)

        # Profile management
        profile_group = QGroupBox("Ausgabeprofil")
        profile_layout = QFormLayout(profile_group)

        self.profile_combo = QComboBox()
        self.profile_combo.addItems(["Standard", "Vollständig", "Nur Markdown", "Nur PDF", "Akademisch"])
        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)

        self.save_profile_btn = QPushButton("Als Profil speichern")
        self.save_profile_btn.clicked.connect(self._save_profile)

        profile_layout.addRow("Profil:", self.profile_combo)
        profile_layout.addRow("", self.save_profile_btn)

        export_layout.addWidget(profile_group)

        export_layout.addStretch()

        tabs.addTab(export_widget, "Einstellungen")

        layout.addWidget(tabs)

        # Export button and progress
        export_bar = QHBoxLayout()

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)

        self.prompt_export_btn = QPushButton("Prompt exportieren")
        self.prompt_export_btn.setToolTip(
            "Exportiert den Analyse-Prompt als .md Datei\n"
            "(zum manuellen Einspeisen in ein LLM)"
        )
        self.prompt_export_btn.setStyleSheet("""
            QPushButton {
                background-color: #8e44ad;
                color: white;
                font-weight: bold;
                padding: 12px 15px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #7d3c98;
            }
        """)
        self.prompt_export_btn.clicked.connect(self._on_prompt_export)

        self.export_btn = QPushButton("Exportieren")
        self.export_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                font-weight: bold;
                padding: 12px 25px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)
        self.export_btn.clicked.connect(self._on_export)

        export_bar.addWidget(self.progress_bar, stretch=1)
        export_bar.addWidget(self.prompt_export_btn)
        export_bar.addWidget(self.export_btn)

        layout.addLayout(export_bar)

        # Status
        self.status_label = QLabel("Bereit zum Exportieren")
        self.status_label.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(self.status_label)

    def set_content(self, content: str):
        """Set the report content."""
        self._current_content = content
        self.preview_edit.setPlainText(content)

    def append_content(self, text: str):
        """Append text to the content (for streaming)."""
        self._current_content += text
        self.preview_edit.setPlainText(self._current_content)

        # Scroll to bottom
        cursor = self.preview_edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.preview_edit.setTextCursor(cursor)

    def clear_content(self):
        """Clear the content."""
        self._current_content = ""
        self.preview_edit.clear()

    def get_content(self) -> str:
        """Get the current content."""
        return self._current_content

    def _copy_to_clipboard(self):
        """Copy content to clipboard."""
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._current_content)
        self.status_label.setText("In Zwischenablage kopiert")

    def _browse_directory(self):
        """Browse for output directory."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Ausgabeordner wählen",
            str(self._output_directory)
        )

        if directory:
            self._output_directory = Path(directory)
            self.dir_edit.setText(directory)

    def _on_profile_changed(self, profile_name: str):
        """Handle profile selection change."""
        profiles = {
            "Standard": ["md", "pdf"],
            "Vollständig": ["md", "pdf", "docx", "html"],
            "Nur Markdown": ["md"],
            "Nur PDF": ["pdf"],
            "Akademisch": ["md", "pdf", "docx"]
        }

        formats = profiles.get(profile_name, ["md"])

        for fmt, cb in self.format_checks.items():
            cb.setChecked(fmt in formats)

    def _save_profile(self):
        """Save current format selection as profile."""
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "Profil speichern", "Profilname:")
        if ok and name:
            # Add to combo
            if self.profile_combo.findText(name) == -1:
                self.profile_combo.addItem(name)
            self.status_label.setText(f"Profil '{name}' gespeichert")

    def _on_export(self):
        """Handle export button click."""
        if not self._current_content:
            QMessageBox.warning(self, "Export", "Kein Inhalt zum Exportieren vorhanden.")
            return

        # Get selected formats
        formats = [fmt for fmt, cb in self.format_checks.items() if cb.isChecked()]

        if not formats:
            QMessageBox.warning(self, "Export", "Bitte mindestens ein Ausgabeformat wählen.")
            return

        self.export_requested.emit(formats, str(self._output_directory))

    def set_progress(self, value: int, maximum: int = 100):
        """Set export progress."""
        self.progress_bar.setMaximum(maximum)
        self.progress_bar.setValue(value)
        self.progress_bar.setVisible(value < maximum)

    def get_output_directory(self) -> Path:
        """Get the current output directory."""
        return self._output_directory

    def set_output_directory(self, directory: Path):
        """Set the output directory."""
        self._output_directory = Path(directory)
        self.dir_edit.setText(str(directory))

    def get_selected_formats(self) -> List[str]:
        """Get selected output formats."""
        return [fmt for fmt, cb in self.format_checks.items() if cb.isChecked()]

    def _on_prompt_export(self):
        """Handle prompt export button click."""
        self.prompt_export_requested.emit()

    def set_status(self, text: str):
        """Set the status text."""
        self.status_label.setText(text)
