# SPDX-License-Identifier: MIT
"""Guarded consumer of the unchanged Nemo ActionJournal; no runtime wiring.

Caller supplies roots and an exclusive host mutation-lease context for ALL
paths. Its entered callable must freshly prove ownership/locks with exactly
True. No permissive default or separate lock implementation is supplied.
Only copy/move to absent targets; write/delete have no defined payload contract.
Crash recovery is explicit exact-plan retry, then undo, never a background job.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path

from tools.fs_protection import sanitize_host_path

from .action_journal import ActionJournal
from .smart_inbox import file_sha256, move_action_id
from .storage_policy import StoragePlan


@dataclass
class FileActionStep:
    action_type: str
    source: str
    target: str
    source_sha256: str | None = None
    backup_path: str | None = None  # External backup authority is refused.

class _GuardedJournal(ActionJournal):
    def __init__(self, owner):
        super().__init__(owner.journal_file, run_id=owner.run_id)
        self.owner = owner
    def _load(self):
        if self.owner._checker is not None:
            self.owner._check()
        payload = super()._load()
        if self.owner._checker is not None:
            self.owner._check()
        return payload
    def _write(self, payload):
        self.owner._check()
        super()._write(payload)
        # A journal fsync may outlive a TTL; never start the next resource
        # mutation after losing the host-held exclusive lease during that write.
        self.owner._check()
    def _write_target(self, path, data):
        self.owner._check()
        super()._write_target(path, data)

class BachActionJournal:
    def __init__(self, journal_dir: Path, run_id: str, *,
                 allowed_roots: Iterable[Path] | None = None,
                 mutation_guard: Callable[[tuple[Path, ...]], AbstractContextManager] | None = None):
        if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", run_id):
            raise ValueError("run_id contains unsafe characters")
        self.run_id = run_id
        self._roots = tuple(Path(root).resolve() for root in (allowed_roots or ()))
        self._guard = mutation_guard
        self._checker = None
        # No filesystem writes during construction/failed preflight.
        self.journal_dir = Path(journal_dir).absolute()
        self.journal_file = self.journal_dir / f"journal_{run_id}.json"
        self._core = _GuardedJournal(self)

    def _path(self, value: str | Path, *, resource=True) -> Path:
        if not self._roots:
            raise PermissionError("Explicit allowed roots are required")
        raw = Path(value)
        if not raw.is_absolute():
            raise ValueError("Absolute resource paths are required")
        clean = sanitize_host_path(raw, base_path=self._roots[0], allowed_roots=self._roots)
        for candidate in (raw, *raw.parents):
            if candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
                raise PermissionError("Aliased resource paths are refused")
        if resource and clean.is_relative_to(self.journal_dir.resolve()):
            raise PermissionError("Journal resources cannot be action sources or targets")
        if clean.exists() and resource and not clean.is_file():
            raise PermissionError("Only regular resource files are supported")
        if clean.is_file() and clean.stat().st_nlink != 1:
            raise PermissionError("Hard-linked resources are refused")
        return clean

    def _paths(self, entries):
        resources = []
        for entry in entries:
            resources.extend((self._path(entry["source"]), self._path(entry["target"])))
        if len(set(resources)) != len(resources):
            raise ValueError("Sources and targets must be disjoint, without aliases")
        # Include directory ownership: Nemo creates journal temp files and
        # renames resource files, which also mutate their parent directories.
        protected = [self._path(self.journal_file, resource=False), self._path(self.journal_dir, resource=False)]
        protected.extend(resources)
        protected.extend(path.parent for path in resources)
        return tuple(dict.fromkeys(protected))

    def _check(self):
        if not callable(self._checker) or self._checker() is not True:
            raise PermissionError("Mutation lease/lock ownership is absent, expired or unknown")

    @contextmanager
    def _lease(self, paths):
        if self._checker is not None:
            raise PermissionError("Concurrent/reentrant use of one journal instance is refused")
        if not callable(self._guard):
            raise PermissionError("Explicit exclusive mutation guard is required")
        lease = self._guard(paths)
        if not hasattr(lease, "__enter__") or not hasattr(lease, "__exit__"):
            raise PermissionError("Guard must supply an exclusive lease context")
        with lease as checker:
            self._checker = checker
            try:
                self._check()
                yield
                self._check()
            finally:
                self._checker = None

    @staticmethod
    def _plan(entry):
        return StoragePlan(source=entry["source"], target=entry["target"], allowed=True,
                           reasons=(), retention_action="keep",
                           original_policy="move" if entry["operation"] == "move" else "keep",
                           operation=entry["operation"])

    def _load(self):
        self._path(self.journal_file, resource=False)
        payload = self._core._load()
        entries = payload["entries"]
        if not entries:
            raise ValueError("Journal requires at least one entry")
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("operation") not in {"copy", "move"}:
                raise ValueError("Unsupported journal action")
            digest = entry.get("sha256")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("Invalid source digest")
            if entry.get("target_sha256") != digest:
                raise ValueError("Copy/move cannot change resource bytes")
            if entry.get("action_id") != move_action_id(self._plan(entry), sha256=digest):
                raise ValueError("Journal action identity mismatch")
            if entry.get("status") not in {"planned", "executed", "undone"}:
                raise ValueError("Invalid journal state")
            receipt = entry.get("undo_receipt")
            if entry["status"] != "planned":
                expected = self._core._receipt(entry)
                if not isinstance(receipt, dict) or any(receipt.get(key) != getattr(expected, key) for key in ("action_id", "before", "after", "undo_plan")):
                    raise ValueError("Undo receipt does not match the controlled action")
        self._paths(entries)
        return payload

    def execute_actions(self, steps: list[FileActionStep]) -> bool:
        if not steps:
            raise ValueError("At least one action is required")
        entries = []
        for step in steps:
            if step.action_type not in {"copy", "move"} or step.backup_path is not None:
                raise ValueError("Only copy/move to an absent target are supported")
            entries.append({"operation": step.action_type, "source": str(self._path(step.source)), "target": str(self._path(step.target))})
        paths = self._paths(entries)
        with self._lease(paths):
            # Repeat preflight under the host's exclusive mutation lease.
            self._paths(entries)
            existing = self._load()["entries"] if self.journal_file.exists() else None
            if existing is not None and len(existing) != len(entries):
                raise ValueError("Retry must use exactly the original plan")
            for index, (step, entry) in enumerate(zip(steps, entries, strict=True)):
                src, target = Path(entry["source"]), Path(entry["target"])
                if existing is not None:
                    prior = existing[index]
                    if any(entry[key] != prior[key] for key in ("operation", "source", "target")):
                        raise ValueError("Retry must use exactly the original plan")
                    digest = prior["sha256"]
                    if prior["status"] == "undone":
                        raise ValueError("An undone journal cannot be executed again")
                    if not src.exists():
                        if entry["operation"] != "move" or not target.is_file() or file_sha256(target) != digest:
                            raise RuntimeError("Move cannot be reconciled")
                    elif file_sha256(src) != digest or (entry["operation"] == "move" and target.exists()):
                        raise RuntimeError("Controlled source/target changed")
                    if target.exists() and file_sha256(target) != digest:
                        raise RuntimeError("Controlled target changed")
                else:
                    if not src.is_file():
                        raise FileNotFoundError(src)
                    if target.exists():
                        raise FileExistsError(target)
                    digest = file_sha256(src)
                if step.source_sha256 is not None and step.source_sha256 != digest:
                    raise RuntimeError("Expected source SHA-256 does not match")
                if not target.parent.is_dir():
                    raise FileNotFoundError(target.parent)
            plans = tuple(self._plan(entry) for entry in entries)
            self._check()
            self._core.execute(plans)
            self._check()
            return True

    def rollback(self) -> None:
        if not self.journal_file.exists():
            self._path(self.journal_file, resource=False)
            return
        payload = self._load()
        with self._lease(self._paths(payload["entries"])):
            current = self._load()
            if current != payload:
                raise RuntimeError("Journal changed while acquiring its lease")
            self._check()
            self._core.undo()  # Nemo preflights ALL resources before the first undo.
            self._check()
