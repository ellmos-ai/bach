#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: action_journal.py
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version ocean.k9_boundary.action_journal

Description:
    CAP-2.3 reversibles 2-Phasen Action Journal für die Ocean
    K9-BOUNDARY Dateisystem-Schicht (open-ocean).

    Bietet transaktionale Dateisystem-Operationen mit:
    - Preflight-Validierung (Existenz, Berechtigungen, Checksummen,
      Kollisionsprüfung)
    - 2-Phasen-Commit: prepare / execute
    - SHA-256 Checksummen für Inhalte und Backups
    - automatischem Rollback bei execute-Fehlern
    - persistentem JSON-Journal für Recovery

    Unterstützte Operationen:
    - copy:  Datei kopieren
    - move:  Datei verschieben/umbenennen
    - write: Bytes in Datei schreiben (neu oder überschreiben)
    - delete: Datei oder leeres Verzeichnis löschen
    - mkdir: Verzeichnis anlegen

Usage:
    from pathlib import Path
    from tools.ocean.k9_boundary import ActionJournal

    tx = ActionJournal(Path("/tmp/k9_workspace"))
    tx.add_copy(Path("/tmp/a.txt"), Path("/tmp/k9_workspace/b.txt"))
    tx.add_write(Path("/tmp/k9_workspace/c.txt"), b"hello")
    tx.prepare()
    tx.execute()

Recovery:
    tx = ActionJournal(Path("/tmp/k9_workspace"))
    tx.recover()   # Liest .action_journal.json und rollt zurück, falls nötig.
"""

from __future__ import annotations

__version__ = "1.0.0"
__author__ = "BACH Team"

import hashlib
import json
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class JournalState(str, Enum):
    """Zustände des 2-Phasen-Journals."""
    EMPTY = "empty"
    PREPARED = "prepared"
    EXECUTED = "executed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class ActionJournalError(Exception):
    """Basis-Fehler für das Action Journal."""


class PreflightError(ActionJournalError):
    """Ein oder mehrere Preflight-Prüfungen sind fehlgeschlagen."""


class ExecuteError(ActionJournalError):
    """Fehler während der Execute-Phase."""


class RollbackError(ActionJournalError):
    """Fehler während des Rollbacks."""


def _sha256_bytes(data: bytes) -> str:
    """SHA-256 Checksumme über Bytes."""
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    """SHA-256 Checksumme über eine Datei (chunked, speicherschonend)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _now_iso() -> str:
    """ISO-Zeitstempel in UTC."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class FileOp:
    """Eine einzelne Dateisystem-Operation innerhalb der Transaktion."""
    op: str  # copy|move|write|delete|mkdir
    src: Optional[str] = None
    dst: Optional[str] = None
    content: Optional[str] = None  # base64 für binär sicher
    checksum: Optional[str] = None  # erwartete SHA-256 der Quelle/des Inhalts
    backup: Optional[str] = None  # relativer Backup-Pfad nach prepare
    src_backup: Optional[str] = None  # Backup der Quelle bei move

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # base64-Felder serialisieren wir als String
        return {k: v for k, v in d.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FileOp":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class JournalEntry:
    """Persistente Journal-Repräsentation."""
    version: str
    created: str
    state: str
    workspace: str
    ops: List[Dict[str, Any]] = field(default_factory=list)


class ActionJournal:
    """Reversible 2-Phasen Dateisystem-Transaktion."""

    JOURNAL_FILE = ".action_journal.json"
    BACKUP_DIR = ".action_journal_backup"
    SUPPORTED_OPS = {"copy", "move", "write", "delete", "mkdir"}

    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace).resolve()
        self.journal_path = self.workspace / self.JOURNAL_FILE
        self.backup_dir = self.workspace / self.BACKUP_DIR
        self._ops: List[FileOp] = []
        self._state = JournalState.EMPTY
        self._prepared = False

    # ------------------------------------------------------------------
    # Öffentliche API: Operationen registrieren
    # ------------------------------------------------------------------

    def add_copy(self, src: Path, dst: Path, *, checksum: Optional[str] = None) -> None:
        """Kopiert `src` nach `dst`. Optionaler SHA-256 der Quelle."""
        self._ops.append(FileOp(
            op="copy",
            src=str(Path(src).resolve()),
            dst=str(self._resolve_dst(dst)),
            checksum=checksum,
        ))

    def add_move(self, src: Path, dst: Path, *, checksum: Optional[str] = None) -> None:
        """Verschiebt `src` nach `dst`. Optionaler SHA-256 der Quelle."""
        self._ops.append(FileOp(
            op="move",
            src=str(Path(src).resolve()),
            dst=str(self._resolve_dst(dst)),
            checksum=checksum,
        ))

    def add_write(
        self,
        dst: Path,
        content: bytes,
        *,
        checksum: Optional[str] = None,
    ) -> None:
        """Schreibt `content` nach `dst`. Optionaler SHA-256 des Inhalts."""
        import base64
        expected = checksum or _sha256_bytes(content)
        self._ops.append(FileOp(
            op="write",
            dst=str(self._resolve_dst(dst)),
            content=base64.b64encode(content).decode("ascii"),
            checksum=expected,
        ))

    def add_delete(self, path: Path, *, checksum: Optional[str] = None) -> None:
        """Löscht `path` (Datei oder leeres Verzeichnis). Optionaler SHA-256."""
        self._ops.append(FileOp(
            op="delete",
            src=str(Path(path).resolve()),
            checksum=checksum,
        ))

    def add_mkdir(self, path: Path) -> None:
        """Legt Verzeichnis `path` an."""
        self._ops.append(FileOp(
            op="mkdir",
            dst=str(self._resolve_dst(path)),
        ))

    # ------------------------------------------------------------------
    # Preflight
    # ------------------------------------------------------------------

    def preflight(self) -> Tuple[bool, List[str]]:
        """
        Führt Vorabprüfungen für alle registrierten Operationen aus.
        Gibt (ok, fehlerliste) zurück, ohne Dateien zu verändern.
        """
        errors: List[str] = []
        seen_dst: set = set()

        for idx, op in enumerate(self._ops):
            prefix = f"Op[{idx}] {op.op}"

            if op.op not in self.SUPPORTED_OPS:
                errors.append(f"{prefix}: unbekannte Operation '{op.op}'")
                continue

            if op.op in {"copy", "move", "delete"}:
                if not op.src:
                    errors.append(f"{prefix}: src fehlt")
                    continue
                src_path = Path(op.src)
                if not src_path.exists():
                    errors.append(f"{prefix}: Quelle existiert nicht: {src_path}")
                    continue
                if op.checksum and src_path.is_file():
                    actual = _sha256_file(src_path)
                    if actual != op.checksum:
                        errors.append(
                            f"{prefix}: Checksumme mismatch (erwartet {op.checksum}, "
                            f"ist {actual})"
                        )

            if op.op in {"copy", "move", "write", "mkdir"}:
                if not op.dst:
                    errors.append(f"{prefix}: dst fehlt")
                    continue
                dst_path = Path(op.dst)
                # Ziel muss innerhalb des Workspace liegen (K9-BOUNDARY)
                try:
                    dst_path.resolve().relative_to(self.workspace)
                except ValueError:
                    errors.append(
                        f"{prefix}: Ziel außerhalb des Workspace: {dst_path}"
                    )
                    continue
                if op.op in {"copy", "move", "write"}:
                    if str(dst_path) in seen_dst:
                        errors.append(f"{prefix}: doppeltes Ziel {dst_path}")
                    seen_dst.add(str(dst_path))
                    parent = dst_path.parent
                    if parent.exists() and not parent.is_dir():
                        errors.append(f"{prefix}: Parent ist keine Directory: {parent}")
                    # Schreibbarkeit kann nicht auf allen OS robust geprüft werden,
                    # aber parent muss existieren oder angelegt werden (mkdir erlaubt).

            if op.op == "write":
                if not op.content:
                    errors.append(f"{prefix}: write ohne content")
                    continue
                # content-checksum wird nicht mehr in preflight abgelehnt;
                # ggf. erst in execute geprüft.

            if op.op == "delete":
                src_path = Path(op.src)
                if src_path.is_dir() and any(src_path.iterdir()):
                    errors.append(f"{prefix}: Directory nicht leer: {src_path}")

        return (not errors, errors)

    # ------------------------------------------------------------------
    # Phase 1: Prepare
    # ------------------------------------------------------------------

    def prepare(self) -> None:
        """
        1-Phase: Preflight, Workspace-Berechtigungen prüfen, Backups für
        potenziell zerstörerische Operationen anlegen, Journal schreiben.
        """
        if self._state not in {JournalState.EMPTY, JournalState.FAILED}:
            raise ActionJournalError(
                f"prepare() nicht erlaubt im Zustand {self._state.value}"
            )

        ok, errors = self.preflight()
        if not ok:
            raise PreflightError("; ".join(errors))

        self.workspace.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        # Bestehendes Journal mit anderem Zustand darf nicht überschrieben werden.
        if self.journal_path.exists():
            raise ActionJournalError(
                f"Journal existiert bereits: {self.journal_path}. "
                "Bitte recover() oder reset() aufrufen."
            )

        for idx, op in enumerate(self._ops):
            if op.op in {"copy", "move", "write"}:
                dst_path = Path(op.dst)
                if dst_path.exists():
                    backup_name = f"{idx}_{dst_path.name}"
                    backup_path = self.backup_dir / backup_name
                    if dst_path.is_file():
                        shutil.copy2(dst_path, backup_path)
                    elif dst_path.is_dir():
                        shutil.copytree(dst_path, backup_path, dirs_exist_ok=True)
                    op.backup = str(backup_path.relative_to(self.workspace))
                if op.op == "move":
                    src_path = Path(op.src)
                    if src_path.exists() and src_path.is_file():
                        src_backup_name = f"{idx}_src_{src_path.name}"
                        src_backup_path = self.backup_dir / src_backup_name
                        shutil.copy2(src_path, src_backup_path)
                        op.src_backup = str(src_backup_path.relative_to(self.workspace))
            elif op.op == "delete":
                src_path = Path(op.src)
                if src_path.exists() and src_path.is_file():
                    backup_name = f"{idx}_{src_path.name}"
                    backup_path = self.backup_dir / backup_name
                    shutil.copy2(src_path, backup_path)
                    op.backup = str(backup_path.relative_to(self.workspace))

        self._write_journal(JournalState.PREPARED)
        self._state = JournalState.PREPARED
        self._prepared = True

    # ------------------------------------------------------------------
    # Phase 2: Execute
    # ------------------------------------------------------------------

    def execute(self) -> None:
        """
        2-Phase: Führt alle Operationen aus. Bei Fehler wird automatisch
        ein Rollback ausgelöst.
        """
        if self._state != JournalState.PREPARED:
            raise ActionJournalError(
                f"execute() erfordert Zustand 'prepared', ist aber {self._state.value}"
            )

        try:
            for idx, op in enumerate(self._ops):
                self._apply_op(op)
                # Fortschritt im Journal speichern (best-effort).
                self._write_journal(JournalState.EXECUTED, progress=idx + 1)
            self._write_journal(JournalState.EXECUTED)
            self._state = JournalState.EXECUTED
        except Exception as exc:
            self._write_journal(JournalState.FAILED, error=str(exc))
            self._state = JournalState.FAILED
            try:
                self.rollback()
            except RollbackError:
                raise
            except Exception as rb_exc:
                raise RollbackError(f"Rollback fehlgeschlagen: {rb_exc}") from rb_exc
            raise ExecuteError(f"execute fehlgeschlagen, rollback ausgeführt: {exc}") from exc

    def _apply_op(self, op: FileOp) -> None:
        if op.op == "copy":
            dst = Path(op.dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(op.src, dst)
        elif op.op == "move":
            dst = Path(op.dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(op.src, dst)
        elif op.op == "write":
            import base64
            dst = Path(op.dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            content = base64.b64decode(op.content)
            with open(dst, "wb") as fh:
                fh.write(content)
            actual = _sha256_file(dst)
            if op.checksum and actual != op.checksum:
                raise ExecuteError(
                    f"write Checksum mismatch nach Schreiben: {dst}"
                )
        elif op.op == "delete":
            src = Path(op.src)
            if src.is_file():
                src.unlink()
            elif src.is_dir():
                src.rmdir()
            else:
                raise ExecuteError(f"delete: unbekannter Typ: {src}")
        elif op.op == "mkdir":
            Path(op.dst).mkdir(parents=True, exist_ok=True)
        else:
            raise ExecuteError(f"unbekannte Operation: {op.op}")

    # ------------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------------

    def rollback(self) -> None:
        """
        Macht die Transaktion rückgängig: stellt Backups wieder her,
        löscht neu angelegte Dateien/Verzeichnisse, aktualisiert Journal.
        """
        if self._state == JournalState.ROLLED_BACK:
            return

        errors: List[str] = []

        # In umgekehrter Reihenfolge rückgängig machen.
        for op in reversed(self._ops):
            try:
                self._revert_op(op)
            except Exception as exc:
                errors.append(f"rollback {op.op}: {exc}")

        self._write_journal(JournalState.ROLLED_BACK)
        self._state = JournalState.ROLLED_BACK

        if errors:
            raise RollbackError("; ".join(errors))

    def _revert_op(self, op: FileOp) -> None:
        if op.op in {"copy", "write"}:
            dst = Path(op.dst)
            if dst.exists():
                if dst.is_file():
                    dst.unlink()
                elif dst.is_dir():
                    shutil.rmtree(dst)
            if op.backup:
                backup_path = self.workspace / op.backup
                if backup_path.exists():
                    backup_path.parent.mkdir(parents=True, exist_ok=True)
                    if backup_path.is_file():
                        shutil.copy2(backup_path, dst)
                    elif backup_path.is_dir():
                        shutil.copytree(backup_path, dst, dirs_exist_ok=True)
        elif op.op == "move":
            dst = Path(op.dst)
            src = Path(op.src)
            if dst.exists():
                if dst.is_file():
                    dst.unlink()
                elif dst.is_dir():
                    shutil.rmtree(dst)
            if op.src_backup:
                src_backup_path = self.workspace / op.src_backup
                if src_backup_path.exists():
                    src.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_backup_path, src)
            elif src.exists():
                # Fallback: src existiert noch, nichts tun
                pass
        elif op.op == "delete":
            src = Path(op.src)
            if op.backup:
                backup_path = self.workspace / op.backup
                if backup_path.exists() and not src.exists():
                    src.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup_path, src)
        elif op.op == "mkdir":
            dst = Path(op.dst)
            if dst.exists() and dst.is_dir() and not any(dst.iterdir()):
                dst.rmdir()

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    def recover(self) -> JournalState:
        """
        Liest ein persistiertes Journal ein und führt notwendige
        Abschlussaktionen aus (rollback bei failed/prepared).
        """
        if not self.journal_path.exists():
            return JournalState.EMPTY

        with open(self.journal_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        entry = JournalEntry(**data)
        self._state = JournalState(entry.state)
        self._ops = [FileOp.from_dict(o) for o in entry.ops]

        if self._state in {JournalState.PREPARED, JournalState.FAILED}:
            self.rollback()
        return self._state

    def reset(self) -> None:
        """
        Löscht Journal und Backups, setzt die Transaktion zurück.
        Nur erlaubt, wenn keine ausstehende Transaktion vorliegt.
        """
        if self._state in {JournalState.PREPARED, JournalState.FAILED}:
            raise ActionJournalError(
                "reset() nicht erlaubt im Zustand prepared/failed; "
                "bitte rollback() oder recover() aufrufen."
            )
        if self.backup_dir.exists():
            shutil.rmtree(self.backup_dir)
        if self.journal_path.exists():
            self.journal_path.unlink()
        self._ops = []
        self._state = JournalState.EMPTY
        self._prepared = False

    # ------------------------------------------------------------------
    # Intern: Journal schreiben / auflösen
    # ------------------------------------------------------------------

    def _resolve_dst(self, dst: Path) -> Path:
        """Löst Zielpfade relativ zum Workspace auf."""
        path = Path(dst)
        if path.is_absolute():
            return path.resolve()
        return (self.workspace / path).resolve()

    def _write_journal(
        self,
        state: JournalState,
        *,
        progress: Optional[int] = None,
        error: Optional[str] = None,
    ) -> None:
        entry = JournalEntry(
            version="1.0.0",
            created=_now_iso(),
            state=state.value,
            workspace=str(self.workspace),
            ops=[op.to_dict() for op in self._ops],
        )
        data: Dict[str, Any] = asdict(entry)
        if progress is not None:
            data["progress"] = progress
        if error is not None:
            data["error"] = error

        # Atomares Schreiben über Temp-Datei + rename.
        fd, tmp = tempfile.mkstemp(
            suffix=".json", prefix=self.JOURNAL_FILE + ".", dir=str(self.workspace)
        )
        try:
            with open(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise
        Path(tmp).rename(self.journal_path)

    @property
    def state(self) -> JournalState:
        return self._state

    @property
    def ops(self) -> List[FileOp]:
        return list(self._ops)
