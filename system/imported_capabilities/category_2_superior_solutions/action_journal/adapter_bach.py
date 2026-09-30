# SPDX-License-Identifier: MIT
"""Guarded consumer of the unchanged Nemo ActionJournal; no runtime wiring.

Caller supplies roots and an exclusive host mutation-lease context for ALL
paths. Its entered callable must freshly prove ownership/locks with exactly
True. No permissive default or separate lock implementation is supplied.
Only copy/move to absent targets; write/delete have no defined payload contract.
Crash recovery is explicit exact-plan retry, then undo, never a background job.
"""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from types import FunctionType, SimpleNamespace

from tools.fs_protection import sanitize_host_path

from . import action_journal as nemo_core
from . import smart_inbox as nemo_smart
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


def _private_consumer(owner):
    """Bind trusted unchanged Nemo code to per-consumer mutation primitives."""

    class GuardedPath(type(Path())):
        def replace(self, target):
            owner._boundary(self, target)
            if Path(target).exists():
                raise FileExistsError(target)
            owner._boundary(self, target)
            return super().replace(target)

        def unlink(self, missing_ok=False):
            owner._boundary(self)
            return super().unlink(missing_ok=missing_ok)

        def mkdir(self, mode=0o777, parents=False, exist_ok=False):
            owner._boundary(self)
            return super().mkdir(mode=mode, parents=parents, exist_ok=exist_ok)

        def open(self, mode="r", *args, **kwargs):
            if any(flag in mode for flag in "wax+"):
                raise PermissionError(
                    "Consumer paths cannot open arbitrary writable files"
                )
            return super().open(mode, *args, **kwargs)

        def _denied(self, *args, **kwargs):
            raise PermissionError("Unsupported path mutation")

        rename = rmdir = touch = chmod = lchmod = symlink_to = hardlink_to = _denied

    class Stream:
        def __init__(self, raw, fd):
            self.raw, self.fd = raw, fd
            owner._streams.add(self)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

        def write(self, data):
            view = memoryview(data)
            total = 0
            while total < len(view):
                owner._boundary(owner._fds[self.fd])
                count = self.raw.write(view[total:])
                if type(count) is not int or count <= 0 or count > len(view) - total:
                    raise OSError("Unbuffered write did not make valid progress")
                total += count
            return total

        def flush(self):
            owner._boundary(owner._fds[self.fd])
            self.raw.flush()

        def fileno(self):
            if self.fd not in owner._fds:
                raise PermissionError("Unknown/closed consumer file descriptor")
            return self.fd

        def close(self):
            try:
                self.raw.close()  # unbuffered close cannot commit deferred writes
            finally:
                owner._fds.pop(self.fd, None)
                owner._streams.discard(self)

    class OS:
        path = SimpleNamespace(exists=os.path.exists)

        def fdopen(self, fd, mode):
            if fd not in owner._fds or mode != "wb":
                raise PermissionError("Only own binary temporary FDs are writable")
            owner._boundary(owner._fds[fd])
            return Stream(os.fdopen(fd, mode, buffering=0), fd)

        def fsync(self, fd):
            if fd not in owner._fds:
                raise PermissionError("Unknown consumer FD")
            owner._boundary(owner._fds[fd])
            os.fsync(fd)

        def replace(self, temporary, final):
            temporary, final = Path(temporary), Path(final)
            if temporary not in owner._temps:
                raise PermissionError(
                    "Only own registered temporary paths may be committed"
                )
            owner._boundary(temporary, final)
            if final != owner.journal_file and final.exists():
                raise FileExistsError(final)
            owner._boundary(temporary, final)
            os.replace(temporary, final)
            owner._temps.discard(temporary)

        def unlink(self, temporary):
            temporary = Path(temporary)
            if temporary not in owner._temps:
                raise PermissionError("Only own temporary paths may be cleaned")
            owner._boundary(temporary)
            os.unlink(temporary)
            owner._temps.discard(temporary)

    class Temps:
        def mkstemp(self, *, prefix, dir):
            directory = Path(dir)
            owner._boundary(directory)
            fd, name = tempfile.mkstemp(prefix=prefix, dir=directory)
            path = Path(name)
            owner._temps.add(path)
            owner._fds[fd] = path
            # If revoked after creation, _lease finally closes FD, leaving an
            # explicitly observable private temp; it never deletes without lease.
            owner._check()
            return fd, name

    private_os, private_temp = OS(), Temps()

    class Consumer(ActionJournal):
        pass

    def bind(function, module):
        environment = dict(function.__globals__)
        environment.update(
            Path=GuardedPath,
            os=private_os,
            tempfile=private_temp,
            ActionJournal=Consumer,
        )
        # Read-only hash dispatch preserves the original module-specific helper
        # and permits fault instrumentation without mutating source globals.
        environment["file_sha256"] = lambda path: module.file_sha256(path)
        if module is nemo_core:
            environment.update(apply_move=forward, undo_move=backward)
        clone = FunctionType(
            function.__code__,
            environment,
            function.__name__,
            function.__defaults__,
            function.__closure__,
        )
        clone.__kwdefaults__ = function.__kwdefaults__
        return clone

    forward = bind(nemo_smart.apply_move, nemo_smart)
    backward = bind(nemo_smart.undo_move, nemo_smart)
    for name, member in vars(ActionJournal).items():
        if isinstance(member, staticmethod):
            setattr(Consumer, name, staticmethod(bind(member.__func__, nemo_core)))
        elif isinstance(member, FunctionType):
            setattr(Consumer, name, bind(member, nemo_core))
    return Consumer(owner.journal_file, run_id=owner.run_id)


class BachActionJournal:
    def __init__(
        self,
        journal_dir: Path,
        run_id: str,
        *,
        allowed_roots: Iterable[Path] | None = None,
        mutation_guard: Callable[[tuple[Path, ...]], AbstractContextManager]
        | None = None,
    ):
        if not isinstance(run_id, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,128}", run_id
        ):
            raise ValueError("run_id contains unsafe characters")
        self.run_id = run_id
        self._roots = tuple(Path(root).resolve() for root in (allowed_roots or ()))
        self._guard = mutation_guard
        self._checker = None
        self._entry_lock = Lock()
        self._leased_paths = frozenset()
        self._temps, self._streams = set(), set()
        self._fds = {}
        # No filesystem writes during construction/failed preflight.
        self.journal_dir = Path(journal_dir).absolute()
        self.journal_file = self.journal_dir / f"journal_{run_id}.json"
        self._core = _private_consumer(self)

    def _path(self, value: str | Path, *, resource=True) -> Path:
        if not self._roots:
            raise PermissionError("Explicit allowed roots are required")
        raw = Path(value)
        if not raw.is_absolute():
            raise ValueError("Absolute resource paths are required")
        clean = sanitize_host_path(
            raw, base_path=self._roots[0], allowed_roots=self._roots
        )
        for candidate in (raw, *raw.parents):
            if (
                candidate.is_symlink()
                or getattr(candidate, "is_junction", lambda: False)()
            ):
                raise PermissionError("Aliased resource paths are refused")
        if resource and clean.is_relative_to(self.journal_dir.resolve()):
            raise PermissionError(
                "Journal resources cannot be action sources or targets"
            )
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
        protected = [
            self._path(self.journal_file, resource=False),
            self._path(self.journal_dir, resource=False),
        ]
        ancestor = self.journal_dir.parent
        while not ancestor.exists():
            protected.append(self._path(ancestor, resource=False))
            ancestor = ancestor.parent
        protected.append(self._path(ancestor, resource=False))
        protected.extend(resources)
        protected.extend(path.parent for path in resources)
        return tuple(dict.fromkeys(protected))

    def _check(self):
        if not callable(self._checker) or self._checker() is not True:
            raise PermissionError(
                "Mutation lease/lock ownership is absent, expired or unknown"
            )

    def _boundary(self, *paths):
        for path in paths:
            clean = self._path(path, resource=False)
            if clean not in self._leased_paths and clean not in self._temps:
                raise PermissionError(
                    "Mutation path is not owned by this consumer lease"
                )
        self._check()

    @property
    def retained_temporary_paths(self):
        """Observable private leftovers, never a completed action receipt."""
        return tuple(sorted(path for path in self._temps if path.exists()))

    @contextmanager
    def _lease(self, paths):
        if not self._entry_lock.acquire(blocking=False):
            raise PermissionError("Concurrent/reentrant use of one consumer is refused")
        try:
            if not callable(self._guard):
                raise PermissionError("Explicit exclusive mutation guard is required")
            lease = self._guard(paths)
            if not hasattr(lease, "__enter__") or not hasattr(lease, "__exit__"):
                raise PermissionError("Guard must supply an exclusive lease context")
            with lease as checker:
                self._checker = checker
                self._leased_paths = frozenset(paths)
                try:
                    self._check()
                    yield
                    self._check()
                finally:
                    # Handle closure performs no path mutation or buffered write.
                    closing_error = None
                    for stream in tuple(self._streams):
                        try:
                            stream.close()
                        except OSError as error:
                            closing_error = error
                    for fd in tuple(self._fds):
                        try:
                            os.close(fd)
                        except OSError as error:
                            closing_error = error
                        finally:
                            self._fds.pop(fd, None)
                    self._checker = None
                    self._leased_paths = frozenset()
                    if closing_error is not None:
                        raise closing_error
        finally:
            self._entry_lock.release()

    @staticmethod
    def _plan(entry):
        return StoragePlan(
            source=entry["source"],
            target=entry["target"],
            allowed=True,
            reasons=(),
            retention_action="keep",
            original_policy="move" if entry["operation"] == "move" else "keep",
            operation=entry["operation"],
        )

    def _load(self):
        self._path(self.journal_file, resource=False)
        payload = self._core._load()
        entries = payload["entries"]
        if not entries:
            raise ValueError("Journal requires at least one entry")
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("operation") not in {
                "copy",
                "move",
            }:
                raise ValueError("Unsupported journal action")
            digest = entry.get("sha256")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("Invalid source digest")
            if entry.get("target_sha256") != digest:
                raise ValueError("Copy/move cannot change resource bytes")
            if entry.get("action_id") != move_action_id(
                self._plan(entry), sha256=digest
            ):
                raise ValueError("Journal action identity mismatch")
            if entry.get("status") not in {"planned", "executed", "undone"}:
                raise ValueError("Invalid journal state")
            receipt = entry.get("undo_receipt")
            if entry["status"] != "planned":
                expected = self._core._receipt(entry)
                if not isinstance(receipt, dict) or any(
                    receipt.get(key) != getattr(expected, key)
                    for key in ("action_id", "before", "after", "undo_plan")
                ):
                    raise ValueError(
                        "Undo receipt does not match the controlled action"
                    )
        self._paths(entries)
        return payload

    def execute_actions(self, steps: list[FileActionStep]) -> bool:
        if not steps:
            raise ValueError("At least one action is required")
        entries = []
        for step in steps:
            if step.action_type not in {"copy", "move"} or step.backup_path is not None:
                raise ValueError("Only copy/move to an absent target are supported")
            entries.append(
                {
                    "operation": step.action_type,
                    "source": str(self._path(step.source)),
                    "target": str(self._path(step.target)),
                }
            )
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
                    if any(
                        entry[key] != prior[key]
                        for key in ("operation", "source", "target")
                    ):
                        raise ValueError("Retry must use exactly the original plan")
                    digest = prior["sha256"]
                    if prior["status"] == "undone":
                        raise ValueError("An undone journal cannot be executed again")
                    if not src.exists():
                        if (
                            entry["operation"] != "move"
                            or not target.is_file()
                            or file_sha256(target) != digest
                        ):
                            raise RuntimeError("Move cannot be reconciled")
                    elif file_sha256(src) != digest or (
                        entry["operation"] == "move" and target.exists()
                    ):
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
