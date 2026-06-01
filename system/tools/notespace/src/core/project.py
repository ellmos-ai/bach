#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Project Management - NoteSpaceLLM Project Container
===================================================

A project encapsulates all data for a report generation session:
- Documents and their selection state
- Sub-queries and their results
- Main question/thesis
- Workflow configuration
- Output settings
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from .document_manager import DocumentManager
from .sub_query import SubQueryManager


@dataclass
class OutputProfile:
    """Output format configuration."""
    name: str
    formats: List[str]  # e.g., ["md", "pdf", "docx"]
    is_default: bool = False

    def to_dict(self) -> dict:
        return {"name": self.name, "formats": self.formats, "is_default": self.is_default}

    @classmethod
    def from_dict(cls, data: dict) -> "OutputProfile":
        return cls(data["name"], data["formats"], data.get("is_default", False))


@dataclass
class ProjectSettings:
    """Project-level settings."""
    output_directory: Path = field(default_factory=lambda: Path("./output"))
    output_profile: str = "default"
    llm_provider: str = "ollama"  # ollama, openai, anthropic, local
    llm_model: str = "llama3"
    ollama_base_url: str = "http://localhost:11434"
    ollama_api_key: str = ""
    max_context_tokens: int = 8000
    language: str = "de"

    def to_dict(self) -> dict:
        # LLM connection settings (provider, model, URL, key) are stored in
        # ~/.notespacellm/config.json (app_config), NOT in project.json.
        return {
            "output_directory": str(self.output_directory),
            "output_profile": self.output_profile,
            "max_context_tokens": self.max_context_tokens,
            "language": self.language
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectSettings":
        from .app_config import get_app_config
        app_cfg = get_app_config()
        return cls(
            output_directory=Path(data.get("output_directory", "./output")),
            output_profile=data.get("output_profile", "default"),
            llm_provider=app_cfg.llm_provider,
            llm_model=app_cfg.llm_model,
            ollama_base_url=app_cfg.ollama_base_url,
            ollama_api_key=app_cfg.ollama_api_key,
            max_context_tokens=data.get("max_context_tokens", 8000),
            language=data.get("language", "de")
        )


@dataclass
class Project:
    """
    A NoteSpaceLLM project containing all data for report generation.

    Workflow:
    1. Create project with main question
    2. Add documents and directories
    3. Select relevant documents
    4. Add sub-queries for detailed research
    5. Choose report type and workflow
    6. Generate report
    """
    id: str
    name: str
    main_question: str = ""
    description: str = ""

    # Report configuration
    report_type: str = "analysis"  # analysis, summary, comparison, research
    workflow_id: str = "standard"

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    modified_at: datetime = field(default_factory=datetime.now)

    # Settings
    settings: ProjectSettings = field(default_factory=ProjectSettings)

    # Managers (not serialized directly)
    _document_manager: DocumentManager = field(default=None, repr=False)
    _subquery_manager: SubQueryManager = field(default=None, repr=False)

    # Additional metadata
    tags: List[str] = field(default_factory=list)
    notes: str = ""

    def __post_init__(self):
        if self._document_manager is None:
            self._document_manager = DocumentManager()
        if self._subquery_manager is None:
            self._subquery_manager = SubQueryManager()

    @classmethod
    def create(cls, name: str, main_question: str = "", report_type: str = "analysis") -> "Project":
        """Create a new project."""
        return cls(
            id=str(uuid.uuid4()),
            name=name,
            main_question=main_question,
            report_type=report_type
        )

    @property
    def documents(self) -> DocumentManager:
        """Access the document manager."""
        return self._document_manager

    @property
    def subqueries(self) -> SubQueryManager:
        """Access the sub-query manager."""
        return self._subquery_manager

    def update_modified(self) -> None:
        """Update the modification timestamp."""
        self.modified_at = datetime.now()

    def get_summary(self) -> dict:
        """Get a summary of the project state."""
        doc_stats = self._document_manager.get_statistics()
        query_stats = self._subquery_manager.get_statistics()

        return {
            "id": self.id,
            "name": self.name,
            "main_question": self.main_question,
            "report_type": self.report_type,
            "workflow_id": self.workflow_id,
            "created_at": self.created_at.isoformat(),
            "modified_at": self.modified_at.isoformat(),
            "documents": {
                "total": doc_stats["total_documents"],
                "selected": doc_stats["selected_documents"],
                "ready": doc_stats["status_counts"].get("ready", 0)
            },
            "subqueries": {
                "total": query_stats["total"],
                "completed": query_stats["completed"],
                "pending": query_stats["pending"]
            }
        }

    def to_dict(self) -> dict:
        """Serialize the project to a dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "main_question": self.main_question,
            "description": self.description,
            "report_type": self.report_type,
            "workflow_id": self.workflow_id,
            "created_at": self.created_at.isoformat(),
            "modified_at": self.modified_at.isoformat(),
            "settings": self.settings.to_dict(),
            "tags": self.tags,
            "notes": self.notes,
            # Document and subquery state will be saved separately
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        """Deserialize from dictionary."""
        return cls(
            id=data["id"],
            name=data["name"],
            main_question=data.get("main_question", ""),
            description=data.get("description", ""),
            report_type=data.get("report_type", "analysis"),
            workflow_id=data.get("workflow_id", "standard"),
            created_at=datetime.fromisoformat(data["created_at"]),
            modified_at=datetime.fromisoformat(data.get("modified_at", data["created_at"])),
            settings=ProjectSettings.from_dict(data.get("settings", {})),
            tags=data.get("tags", []),
            notes=data.get("notes", "")
        )

    def save(self, directory: Path) -> None:
        """
        Save the project to a directory.

        Creates:
        - project.json: Project metadata
        - documents.json: Document state
        - subqueries.json: Sub-query state
        """
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)

        # Save project metadata
        project_file = directory / "project.json"
        project_file.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

        # Save document state
        docs_file = directory / "documents.json"
        self._document_manager.save_state(docs_file)

        # Save sub-query state
        queries_file = directory / "subqueries.json"
        self._subquery_manager.save_state(queries_file)

        self.update_modified()

    @classmethod
    def load(cls, directory: Path) -> Optional["Project"]:
        """Load a project from a directory."""
        directory = Path(directory)

        project_file = directory / "project.json"
        if not project_file.exists():
            return None

        try:
            data = json.loads(project_file.read_text(encoding="utf-8"))
            project = cls.from_dict(data)

            # Load document state
            docs_file = directory / "documents.json"
            if docs_file.exists():
                project._document_manager.load_state(docs_file)

            # Load sub-query state
            queries_file = directory / "subqueries.json"
            if queries_file.exists():
                project._subquery_manager.load_state(queries_file)

            return project

        except Exception:
            return None


class ProjectManager:
    """
    Manages multiple projects.

    Handles project creation, loading, and listing.
    """

    def __init__(self, projects_directory: Path):
        """
        Initialize the project manager.

        Args:
            projects_directory: Root directory for all projects
        """
        self.projects_dir = Path(projects_directory)
        self.projects_dir.mkdir(parents=True, exist_ok=True)

        self._current_project: Optional[Project] = None
        self._output_profiles: Dict[str, OutputProfile] = {}

        # Initialize default profiles
        self._init_default_profiles()

    def _init_default_profiles(self) -> None:
        """Initialize default output profiles."""
        self._output_profiles = {
            "default": OutputProfile("default", ["md"], is_default=True),
            "full": OutputProfile("full", ["md", "pdf", "docx"]),
            "markdown_only": OutputProfile("markdown_only", ["md"]),
            "pdf_only": OutputProfile("pdf_only", ["pdf"]),
            "academic": OutputProfile("academic", ["md", "pdf", "bib"])
        }

    @property
    def current(self) -> Optional[Project]:
        """Get the currently open project."""
        return self._current_project

    def list_projects(self) -> List[dict]:
        """
        List all available projects.

        Returns:
            List of project summaries
        """
        projects = []

        for item in self.projects_dir.iterdir():
            if item.is_dir():
                project_file = item / "project.json"
                if project_file.exists():
                    try:
                        data = json.loads(project_file.read_text(encoding="utf-8"))
                        projects.append({
                            "id": data["id"],
                            "name": data["name"],
                            "directory": str(item),
                            "modified_at": data.get("modified_at", data["created_at"]),
                            "report_type": data.get("report_type", "analysis")
                        })
                    except Exception:
                        pass

        # Sort by modification date, newest first
        projects.sort(key=lambda p: p["modified_at"], reverse=True)
        return projects

    def create_project(self, name: str, main_question: str = "",
                      report_type: str = "analysis") -> Project:
        """
        Create a new project.

        Args:
            name: Project name
            main_question: Main research question
            report_type: Type of report to generate

        Returns:
            The created project
        """
        project = Project.create(name, main_question, report_type)

        # Create project directory
        project_dir = self.projects_dir / self._safe_dirname(name)
        project_dir.mkdir(parents=True, exist_ok=True)

        # Save initial state
        project.save(project_dir)

        self._current_project = project
        return project

    def open_project(self, project_id_or_name: str) -> Optional[Project]:
        """
        Open an existing project.

        Args:
            project_id_or_name: Project ID or name

        Returns:
            The project if found
        """
        # Search by ID or name
        for item in self.projects_dir.iterdir():
            if item.is_dir():
                project_file = item / "project.json"
                if project_file.exists():
                    try:
                        data = json.loads(project_file.read_text(encoding="utf-8"))
                        if data["id"] == project_id_or_name or data["name"] == project_id_or_name:
                            project = Project.load(item)
                            if project:
                                self._current_project = project
                                return project
                    except Exception:
                        pass

        return None

    def save_current(self) -> bool:
        """Save the current project."""
        if not self._current_project:
            return False

        # Find project directory
        for item in self.projects_dir.iterdir():
            if item.is_dir():
                project_file = item / "project.json"
                if project_file.exists():
                    try:
                        data = json.loads(project_file.read_text(encoding="utf-8"))
                        if data["id"] == self._current_project.id:
                            self._current_project.save(item)
                            return True
                    except Exception:
                        pass

        return False

    def close_project(self) -> None:
        """Close the current project (saves automatically)."""
        if self._current_project:
            self.save_current()
            self._current_project = None

    def delete_project(self, project_id: str) -> bool:
        """
        Delete a project.

        Args:
            project_id: Project ID to delete

        Returns:
            True if deleted
        """
        import shutil

        for item in self.projects_dir.iterdir():
            if item.is_dir():
                project_file = item / "project.json"
                if project_file.exists():
                    try:
                        data = json.loads(project_file.read_text(encoding="utf-8"))
                        if data["id"] == project_id:
                            # Close if current
                            if self._current_project and self._current_project.id == project_id:
                                self._current_project = None

                            shutil.rmtree(item)
                            return True
                    except Exception:
                        pass

        return False

    def _safe_dirname(self, name: str) -> str:
        """Create a safe directory name from project name."""
        # Remove invalid characters
        safe = "".join(c for c in name if c.isalnum() or c in " -_").strip()
        safe = safe.replace(" ", "_")

        # Add timestamp for uniqueness
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{safe}_{timestamp}"

    # Output profiles
    def get_output_profiles(self) -> List[OutputProfile]:
        """Get all output profiles."""
        return list(self._output_profiles.values())

    def get_output_profile(self, name: str) -> Optional[OutputProfile]:
        """Get an output profile by name."""
        return self._output_profiles.get(name)

    def add_output_profile(self, profile: OutputProfile) -> None:
        """Add or update an output profile."""
        self._output_profiles[profile.name] = profile

    def remove_output_profile(self, name: str) -> bool:
        """Remove an output profile."""
        if name in self._output_profiles and not self._output_profiles[name].is_default:
            del self._output_profiles[name]
            return True
        return False

    def save_profiles(self, filepath: Path) -> None:
        """Save output profiles to file."""
        data = {
            name: profile.to_dict()
            for name, profile in self._output_profiles.items()
        }
        filepath.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load_profiles(self, filepath: Path) -> bool:
        """Load output profiles from file."""
        if not filepath.exists():
            return False

        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            for name, profile_data in data.items():
                self._output_profiles[name] = OutputProfile.from_dict(profile_data)
            return True
        except Exception:
            return False
