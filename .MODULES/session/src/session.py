# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Standalone Module: session
=============================
Self-contained session management, duration calculation, and between-task coaching.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class SessionRecord:
    session_id: str
    user_id: str
    agent_id: str
    started_at: float
    ended_at: Optional[float] = None
    purpose: str = ""
    notes: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    is_active: bool = True

    @property
    def duration_seconds(self) -> float:
        end = self.ended_at if self.ended_at is not None else time.time()
        return max(0.0, end - self.started_at)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["duration_seconds"] = self.duration_seconds
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionRecord":
        clean = dict(data)
        clean.pop("duration_seconds", None)
        return cls(**clean)


class SessionManager:
    """Manages active and historical sessions independently without external dependencies."""

    def __init__(self, storage_path: Optional[Path | str] = None):
        self.storage_path = Path(storage_path) if storage_path else None
        self._sessions: Dict[str, SessionRecord] = {}
        self._active_session_id: Optional[str] = None
        if self.storage_path and self.storage_path.is_file():
            self._load()

    def start_session(
        self,
        user_id: str = "user",
        agent_id: str = "bach",
        purpose: str = "General Work",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SessionRecord:
        """Starts a new session, auto-closing any currently active session."""
        if self._active_session_id and self._active_session_id in self._sessions:
            self.end_session(self._active_session_id, notes=["Auto-closed by new session start."])

        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        record = SessionRecord(
            session_id=session_id,
            user_id=user_id,
            agent_id=agent_id,
            started_at=time.time(),
            purpose=purpose,
            metadata=dict(metadata or {}),
            is_active=True,
        )
        self._sessions[session_id] = record
        self._active_session_id = session_id
        self._save()
        return record

    def end_session(
        self,
        session_id: Optional[str] = None,
        notes: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[SessionRecord]:
        """Ends the specified or current active session."""
        target_id = session_id or self._active_session_id
        if not target_id or target_id not in self._sessions:
            return None

        record = self._sessions[target_id]
        if record.is_active:
            record.ended_at = time.time()
            record.is_active = False
            if notes:
                record.notes.extend(notes)
            if metadata:
                record.metadata.update(metadata)
            if self._active_session_id == target_id:
                self._active_session_id = None
            self._save()
        return record

    def get_active_session(self) -> Optional[SessionRecord]:
        """Returns the currently active session if one exists."""
        if self._active_session_id and self._active_session_id in self._sessions:
            rec = self._sessions[self._active_session_id]
            if rec.is_active:
                return rec
        return None

    def get_session(self, session_id: str) -> Optional[SessionRecord]:
        """Retrieves a session record by ID."""
        return self._sessions.get(session_id)

    def list_sessions(self, limit: int = 50) -> List[SessionRecord]:
        """Returns sessions sorted by start time descending."""
        records = sorted(self._sessions.values(), key=lambda r: r.started_at, reverse=True)
        return records[:limit]

    def between_task_check(self, session_id: Optional[str] = None, last_action: str = "") -> Dict[str, Any]:
        """Generates coaching nudges and health checks between tasks."""
        rec = self.get_session(session_id) if session_id else self.get_active_session()
        dur = rec.duration_seconds if rec else 0.0
        minutes = dur / 60.0

        nudge = "Keep up the great work!"
        if minutes > 90.0:
            nudge = "Long session: recommend a 5-minute break and posture check."
        elif minutes > 45.0:
            nudge = "Session midpoint: check hydration and verify roadmap focus."

        return {
            "session_id": rec.session_id if rec else None,
            "duration_minutes": round(minutes, 2),
            "last_action": last_action,
            "nudge": nudge,
            "status": "healthy",
        }

    def _save(self) -> None:
        if not self.storage_path:
            return
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "active_session_id": self._active_session_id,
                "sessions": [r.to_dict() for r in self._sessions.values()],
            }
            tmp = self.storage_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.storage_path)
        except OSError:
            pass

    def _load(self) -> None:
        if not self.storage_path or not self.storage_path.is_file():
            return
        try:
            raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
            self._active_session_id = raw.get("active_session_id")
            for item in raw.get("sessions", []):
                rec = SessionRecord.from_dict(item)
                self._sessions[rec.session_id] = rec
        except Exception:
            pass
