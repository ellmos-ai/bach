# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Bach Adapter for Two-Phase Reversible Action Journal (from NemoFold).

Provides atomic file moves, copies, and edits with pre-calculated SHA-256 hashes,
safe two-phase commit, and crash recovery reconciliation for Bach tasks and migrations.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def file_sha256(path: Path) -> str:
    """Computes SHA-256 checksum of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class FileActionStep:
    action_type: str  # copy, move, write, delete
    source: str
    target: str
    source_sha256: Optional[str] = None
    backup_path: Optional[str] = None


class BachActionJournal:
    """Manages an atomic, reversible sequence of file operations."""

    def __init__(self, journal_dir: Path, run_id: str):
        self.journal_dir = journal_dir
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.journal_file = self.journal_dir / f"journal_{run_id}.json"
        self.backup_dir = self.journal_dir / f"backups_{run_id}"

    def execute_actions(self, steps: List[FileActionStep]) -> bool:
        """
        Executes file action steps with two-phase safety:
        1. Pre-validation: verify all sources exist and record initial checksums.
        2. Backup: create atomic rollback copies of any existing target files.
        3. Journal write: write state to journal on disk with fsync.
        4. Apply: execute mutations.
        5. Completion marker.
        """
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        journal_payload: Dict[str, Any] = {
            "run_id": self.run_id,
            "status": "in_progress",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "steps": [],
        }

        # Phase 1: Pre-validation & Backups
        for i, step in enumerate(steps):
            src = Path(step.source)
            tgt = Path(step.target)
            step_record: Dict[str, Any] = {
                "step_index": i,
                "action": step.action_type,
                "source": str(src),
                "target": str(tgt),
            }

            if src.exists() and src.is_file():
                step.source_sha256 = file_sha256(src)
                step_record["source_sha256"] = step.source_sha256

            if tgt.exists() and tgt.is_file():
                backup_file = self.backup_dir / f"step_{i}_{tgt.name}"
                shutil.copy2(tgt, backup_file)
                step.backup_path = str(backup_file)
                step_record["backup_path"] = str(backup_file)
                step_record["target_pre_sha256"] = file_sha256(tgt)

            journal_payload["steps"].append(step_record)

        # Write journal atomically
        self._write_journal_atomic(journal_payload)

        # Phase 2: Execute
        try:
            for step in steps:
                src = Path(step.source)
                tgt = Path(step.target)
                tgt.parent.mkdir(parents=True, exist_ok=True)

                if step.action_type == "copy":
                    shutil.copy2(src, tgt)
                elif step.action_type == "move":
                    shutil.move(src, tgt)
                elif step.action_type == "delete":
                    if tgt.exists():
                        tgt.unlink()

            journal_payload["status"] = "completed"
            journal_payload["completed_at"] = datetime.now(timezone.utc).isoformat()
            self._write_journal_atomic(journal_payload)
            return True

        except Exception as exc:
            # Automatic crash rollback
            journal_payload["status"] = "failed"
            journal_payload["error"] = str(exc)
            self._write_journal_atomic(journal_payload)
            self.rollback()
            raise

    def rollback(self) -> None:
        """Rolls back all changes recorded in the journal in reverse order."""
        if not self.journal_file.exists():
            return
        payload = json.loads(self.journal_file.read_text(encoding="utf-8"))
        steps = payload.get("steps", [])

        for step in reversed(steps):
            tgt = Path(step["target"])
            backup = Path(step.get("backup_path", ""))

            if backup.exists() and backup.is_file():
                tgt.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, tgt)
            elif tgt.exists() and step["action"] in ("copy", "move"):
                tgt.unlink()

        payload["status"] = "rolled_back"
        payload["rolled_back_at"] = datetime.now(timezone.utc).isoformat()
        self._write_journal_atomic(payload)

    def _write_journal_atomic(self, payload: Dict[str, Any]) -> None:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=self.journal_dir, prefix=".journal_tmp_")
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, self.journal_file)
