#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Workflow Panel - Visual workflow editor and report type selection
================================================================

Features:
- Report type selection
- Visual workflow display with steps
- Step status indicators
- Interactive step editing
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field

try:
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
        QPushButton, QFrame, QScrollArea, QGroupBox, QTextEdit,
        QSplitter, QListWidget, QListWidgetItem, QDialog,
        QFormLayout, QLineEdit, QSpinBox, QCheckBox, QDialogButtonBox
    )
    from PySide6.QtCore import Qt, Signal, QSize
    from PySide6.QtGui import QPainter, QColor, QPen, QFont
    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False
    class QWidget: pass
    class Signal:
        def __init__(self, *args): pass


@dataclass
class WorkflowStep:
    """A single step in a workflow."""
    id: str
    name: str
    description: str
    step_type: str  # extract, analyze, synthesize, format
    config: Dict = field(default_factory=dict)
    status: str = "pending"  # pending, running, completed, error
    result: str = ""
    order: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "step_type": self.step_type,
            "config": self.config,
            "order": self.order
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowStep":
        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            step_type=data.get("step_type", "analyze"),
            config=data.get("config", {}),
            order=data.get("order", 0)
        )


@dataclass
class Workflow:
    """A complete workflow definition."""
    id: str
    name: str
    description: str
    report_type: str
    steps: List[WorkflowStep] = field(default_factory=list)
    output_formats: List[str] = field(default_factory=lambda: ["md"])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "report_type": self.report_type,
            "steps": [s.to_dict() for s in self.steps],
            "output_formats": self.output_formats
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Workflow":
        steps = [WorkflowStep.from_dict(s) for s in data.get("steps", [])]
        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            report_type=data.get("report_type", "analysis"),
            steps=steps,
            output_formats=data.get("output_formats", ["md"])
        )


# Predefined workflows
DEFAULT_WORKFLOWS = {
    "standard": Workflow(
        id="standard",
        name="Standard-Analyse",
        description="Umfassende Dokumentenanalyse mit strukturiertem Bericht",
        report_type="analysis",
        steps=[
            WorkflowStep("1", "Textextraktion", "Extrahiere Text aus allen Dokumenten", "extract", order=1),
            WorkflowStep("2", "Einzelanalysen", "Führe Detailrecherchen durch", "analyze", order=2),
            WorkflowStep("3", "Synthese", "Kombiniere Erkenntnisse", "synthesize", order=3),
            WorkflowStep("4", "Berichterstellung", "Erstelle strukturierten Bericht", "format", order=4),
            WorkflowStep("5", "Ausgabe", "Exportiere in Zielformate", "export", order=5)
        ],
        output_formats=["md", "pdf"]
    ),
    "quick": Workflow(
        id="quick",
        name="Schnell-Zusammenfassung",
        description="Kurze Zusammenfassung ohne Detailanalysen",
        report_type="summary",
        steps=[
            WorkflowStep("1", "Textextraktion", "Extrahiere Text", "extract", order=1),
            WorkflowStep("2", "Zusammenfassung", "Erstelle Zusammenfassung", "synthesize", order=2),
            WorkflowStep("3", "Ausgabe", "Exportiere", "export", order=3)
        ],
        output_formats=["md"]
    ),
    "research": Workflow(
        id="research",
        name="Forschungsbericht",
        description="Ausführliche Analyse mit Quellenverweisen",
        report_type="research",
        steps=[
            WorkflowStep("1", "Textextraktion", "Extrahiere alle Dokumente", "extract", order=1),
            WorkflowStep("2", "Einzelanalysen", "Analysiere jedes Dokument", "analyze", order=2),
            WorkflowStep("3", "Querverweise", "Identifiziere Zusammenhänge", "analyze",
                        config={"mode": "cross_reference"}, order=3),
            WorkflowStep("4", "Literaturverzeichnis", "Erstelle Quellenverzeichnis", "format",
                        config={"include_citations": True}, order=4),
            WorkflowStep("5", "Synthese", "Kombiniere zu Forschungsbericht", "synthesize", order=5),
            WorkflowStep("6", "Ausgabe", "Exportiere mit Zitaten", "export", order=6)
        ],
        output_formats=["md", "pdf", "docx"]
    ),
    "comparison": Workflow(
        id="comparison",
        name="Dokumentenvergleich",
        description="Vergleiche mehrere Dokumente systematisch",
        report_type="comparison",
        steps=[
            WorkflowStep("1", "Textextraktion", "Extrahiere alle Dokumente", "extract", order=1),
            WorkflowStep("2", "Strukturanalyse", "Analysiere Dokumentstruktur", "analyze",
                        config={"mode": "structure"}, order=2),
            WorkflowStep("3", "Vergleich", "Erstelle Vergleichsmatrix", "analyze",
                        config={"mode": "comparison"}, order=3),
            WorkflowStep("4", "Synthese", "Fasse Unterschiede zusammen", "synthesize", order=4),
            WorkflowStep("5", "Ausgabe", "Exportiere Vergleichsbericht", "export", order=5)
        ],
        output_formats=["md", "pdf"]
    )
}


class WorkflowStepWidget(QFrame if PYSIDE_AVAILABLE else object):
    """Widget representing a single workflow step."""

    if PYSIDE_AVAILABLE:
        clicked = Signal(str)  # step_id

    def __init__(self, step: WorkflowStep, parent=None):
        if not PYSIDE_AVAILABLE:
            return
        super().__init__(parent)
        self.step = step
        self._setup_ui()

    def _setup_ui(self):
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        self.setLineWidth(2)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)

        # Step number and name
        header = QHBoxLayout()

        self.number_label = QLabel(f"{self.step.order}")
        self.number_label.setStyleSheet("""
            background-color: #3498db;
            color: white;
            border-radius: 12px;
            padding: 4px 8px;
            font-weight: bold;
        """)
        self.number_label.setFixedSize(24, 24)
        self.number_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.name_label = QLabel(self.step.name)
        self.name_label.setStyleSheet("font-weight: bold; font-size: 12px;")

        header.addWidget(self.number_label)
        header.addWidget(self.name_label)
        header.addStretch()

        layout.addLayout(header)

        # Description
        self.desc_label = QLabel(self.step.description)
        self.desc_label.setWordWrap(True)
        self.desc_label.setStyleSheet("color: #666; font-size: 10px;")
        layout.addWidget(self.desc_label)

        # Status indicator
        self.status_label = QLabel(self._status_text())
        self.status_label.setStyleSheet(self._status_style())
        layout.addWidget(self.status_label)

        self.setMinimumWidth(200)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _status_text(self) -> str:
        status_map = {
            "pending": "Ausstehend",
            "running": "Läuft...",
            "completed": "Fertig",
            "error": "Fehler"
        }
        return status_map.get(self.step.status, self.step.status)

    def _status_style(self) -> str:
        colors = {
            "pending": "#95a5a6",
            "running": "#f39c12",
            "completed": "#27ae60",
            "error": "#e74c3c"
        }
        color = colors.get(self.step.status, "#95a5a6")
        return f"color: {color}; font-size: 10px; font-style: italic;"

    def update_status(self, status: str):
        """Update the step status."""
        self.step.status = status
        self.status_label.setText(self._status_text())
        self.status_label.setStyleSheet(self._status_style())

        # Update border color based on status
        border_colors = {
            "pending": "#bdc3c7",
            "running": "#f39c12",
            "completed": "#27ae60",
            "error": "#e74c3c"
        }
        color = border_colors.get(status, "#bdc3c7")
        self.setStyleSheet(f"WorkflowStepWidget {{ border: 2px solid {color}; border-radius: 5px; }}")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.step.id)
        super().mousePressEvent(event)


class WorkflowPanel(QWidget if PYSIDE_AVAILABLE else object):
    """
    Panel for workflow selection and visualization.

    Signals:
        workflow_changed: Emitted when workflow selection changes
        step_clicked: Emitted when a workflow step is clicked
    """

    if PYSIDE_AVAILABLE:
        workflow_changed = Signal(str)  # workflow_id
        step_clicked = Signal(str)  # step_id
        start_requested = Signal()

    def __init__(self, parent=None):
        if not PYSIDE_AVAILABLE:
            raise ImportError("PySide6 is required. Install with: pip install PySide6")

        super().__init__(parent)
        self._workflows = dict(DEFAULT_WORKFLOWS)
        self._current_workflow: Optional[Workflow] = None
        self._step_widgets: List[WorkflowStepWidget] = []

        self._setup_ui()
        self._load_workflow("standard")

    def _setup_ui(self):
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Report type and workflow selection
        selection_group = QGroupBox("Berichtstyp und Workflow")
        selection_layout = QFormLayout(selection_group)

        self.report_type_combo = QComboBox()
        self.report_type_combo.addItems([
            "Analyse",
            "Zusammenfassung",
            "Forschungsbericht",
            "Vergleich"
        ])
        self.report_type_combo.currentTextChanged.connect(self._on_report_type_changed)

        self.workflow_combo = QComboBox()
        for wf in self._workflows.values():
            self.workflow_combo.addItem(wf.name, wf.id)
        self.workflow_combo.currentIndexChanged.connect(self._on_workflow_changed)

        selection_layout.addRow("Berichtstyp:", self.report_type_combo)
        selection_layout.addRow("Workflow:", self.workflow_combo)

        layout.addWidget(selection_group)

        # Workflow visualization
        workflow_group = QGroupBox("Workflow-Schritte")
        workflow_layout = QVBoxLayout(workflow_group)

        # Scroll area for steps
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.steps_container = QWidget()
        self.steps_layout = QVBoxLayout(self.steps_container)
        self.steps_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll.setWidget(self.steps_container)
        workflow_layout.addWidget(scroll)

        layout.addWidget(workflow_group, stretch=1)

        # Main question input
        question_group = QGroupBox("Hauptfragestellung")
        question_layout = QVBoxLayout(question_group)

        self.question_edit = QTextEdit()
        self.question_edit.setPlaceholderText(
            "Definiere die zentrale Fragestellung für den Bericht...\n\n"
            "Beispiel: 'Welche Faktoren beeinflussten die Entwicklung im Jahr 2025?'"
        )
        self.question_edit.setMaximumHeight(100)
        question_layout.addWidget(self.question_edit)

        layout.addWidget(question_group)

        # Action buttons
        actions = QHBoxLayout()

        self.edit_workflow_btn = QPushButton("Workflow bearbeiten")
        self.edit_workflow_btn.clicked.connect(self._on_edit_workflow)

        self.start_btn = QPushButton("Bericht erstellen")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                font-weight: bold;
                padding: 10px 20px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #2ecc71;
            }
        """)
        self.start_btn.clicked.connect(lambda: self.start_requested.emit())

        actions.addWidget(self.edit_workflow_btn)
        actions.addStretch()
        actions.addWidget(self.start_btn)

        layout.addLayout(actions)

    def _load_workflow(self, workflow_id: str):
        """Load and display a workflow."""
        if workflow_id not in self._workflows:
            return

        self._current_workflow = self._workflows[workflow_id]

        # Clear existing steps
        for widget in self._step_widgets:
            widget.deleteLater()
        self._step_widgets.clear()

        # Add step widgets
        for step in sorted(self._current_workflow.steps, key=lambda s: s.order):
            widget = WorkflowStepWidget(step, self.steps_container)
            widget.clicked.connect(self._on_step_clicked)
            self._step_widgets.append(widget)
            self.steps_layout.addWidget(widget)

        # Add stretch at the end
        self.steps_layout.addStretch()

    def _on_report_type_changed(self, text: str):
        """Handle report type change."""
        type_map = {
            "Analyse": "standard",
            "Zusammenfassung": "quick",
            "Forschungsbericht": "research",
            "Vergleich": "comparison"
        }

        workflow_id = type_map.get(text, "standard")
        idx = self.workflow_combo.findData(workflow_id)
        if idx >= 0:
            self.workflow_combo.setCurrentIndex(idx)

    def _on_workflow_changed(self, index: int):
        """Handle workflow selection change."""
        workflow_id = self.workflow_combo.currentData()
        if workflow_id:
            self._load_workflow(workflow_id)
            self.workflow_changed.emit(workflow_id)

    def _on_step_clicked(self, step_id: str):
        """Handle step click."""
        self.step_clicked.emit(step_id)

    def _on_edit_workflow(self):
        """Open workflow editor dialog."""
        if not self._current_workflow:
            return

        dialog = WorkflowEditorDialog(self._current_workflow, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Update workflow
            self._load_workflow(self._current_workflow.id)

    def get_main_question(self) -> str:
        """Get the main question text."""
        return self.question_edit.toPlainText().strip()

    def set_main_question(self, question: str):
        """Set the main question text."""
        self.question_edit.setPlainText(question)

    def get_current_workflow(self) -> Optional[Workflow]:
        """Get the currently selected workflow."""
        return self._current_workflow

    def update_step_status(self, step_id: str, status: str):
        """Update the status of a workflow step."""
        for widget in self._step_widgets:
            if widget.step.id == step_id:
                widget.update_status(status)
                break

    def reset_step_statuses(self):
        """Reset all step statuses to pending."""
        for widget in self._step_widgets:
            widget.update_status("pending")

    def add_workflow(self, workflow: Workflow):
        """Add a custom workflow."""
        self._workflows[workflow.id] = workflow
        self.workflow_combo.addItem(workflow.name, workflow.id)

    def save_workflows(self, filepath: Path):
        """Save workflows to file."""
        data = {wf_id: wf.to_dict() for wf_id, wf in self._workflows.items()}
        filepath.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load_workflows(self, filepath: Path):
        """Load workflows from file."""
        if not filepath.exists():
            return

        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            for wf_id, wf_data in data.items():
                self._workflows[wf_id] = Workflow.from_dict(wf_data)

            # Update combo box
            self.workflow_combo.clear()
            for wf in self._workflows.values():
                self.workflow_combo.addItem(wf.name, wf.id)

        except Exception:
            pass


class WorkflowEditorDialog(QDialog if PYSIDE_AVAILABLE else object):
    """Dialog for editing workflow steps."""

    def __init__(self, workflow: Workflow, parent=None):
        if not PYSIDE_AVAILABLE:
            return
        super().__init__(parent)
        self.workflow = workflow
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle(f"Workflow bearbeiten: {self.workflow.name}")
        self.setMinimumSize(500, 400)

        layout = QVBoxLayout(self)

        # Step list
        self.step_list = QListWidget()
        for step in self.workflow.steps:
            item = QListWidgetItem(f"{step.order}. {step.name}")
            item.setData(Qt.ItemDataRole.UserRole, step.id)
            self.step_list.addItem(item)

        layout.addWidget(self.step_list)

        # Step editing
        form = QFormLayout()

        self.name_edit = QLineEdit()
        self.desc_edit = QLineEdit()
        self.order_spin = QSpinBox()
        self.order_spin.setRange(1, 20)

        form.addRow("Name:", self.name_edit)
        form.addRow("Beschreibung:", self.desc_edit)
        form.addRow("Reihenfolge:", self.order_spin)

        layout.addLayout(form)

        # Connect selection
        self.step_list.currentItemChanged.connect(self._on_step_selected)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(buttons)

    def _on_step_selected(self, current, previous):
        if not current:
            return

        step_id = current.data(Qt.ItemDataRole.UserRole)
        step = next((s for s in self.workflow.steps if s.id == step_id), None)

        if step:
            self.name_edit.setText(step.name)
            self.desc_edit.setText(step.description)
            self.order_spin.setValue(step.order)
