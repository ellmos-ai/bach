from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .contracts import UndoReceipt, to_primitive
from .smart_inbox import apply_move, file_sha256, move_action_id, undo_move
from .storage_policy import StoragePlan


class ActionJournal:
    """Atomic reversible file-action journal with retry and crash reconciliation."""

    def __init__(self, path: str | Path, *, run_id: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
            raise ValueError("run_id contains unsafe characters")
        self.path = Path(path)
        self.run_id = run_id

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", dir=self.path.parent
        )
        try:
            with os.fdopen(handle, "wb") as temporary:
                temporary.write(data)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, self.path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def _load(self) -> dict[str, Any]:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("schema") != "nemofold.action-journal.v1":
            raise RuntimeError("action journal schema is invalid")
        if payload.get("run_id") != self.run_id:
            raise RuntimeError("action journal run ID mismatch")
        if not isinstance(payload.get("entries"), list):
            raise RuntimeError("action journal entries are invalid")
        return payload

    @staticmethod
    def _target_bytes(plan: StoragePlan) -> bytes:
        data = Path(plan.source).read_bytes()
        if plan.operation == "convert_copy":
            return data.decode("utf-8-sig").encode("utf-8")
        if plan.operation in {"copy", "move"}:
            return data
        raise ValueError(f"unsupported storage operation: {plan.operation}")

    @staticmethod
    def _write_target(path: Path, data: bytes) -> None:
        handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(handle, "wb") as temporary:
                temporary.write(data)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    @staticmethod
    def _planned_entries(plans: tuple[StoragePlan, ...]) -> list[dict[str, Any]]:
        if not plans:
            raise ValueError("at least one action plan is required")
        if any(not plan.allowed for plan in plans):
            raise PermissionError("all move plans must pass preflight before journaling")
        sources = [Path(plan.source).resolve() for plan in plans]
        targets = [Path(plan.target).resolve() for plan in plans]
        if len(set(sources)) != len(sources) or len(set(targets)) != len(targets):
            raise ValueError("move plans contain duplicate source or target paths")
        entries: list[dict[str, Any]] = []
        for plan, source, target in zip(plans, sources, targets, strict=True):
            if not source.is_file():
                raise FileNotFoundError(source)
            if target.exists():
                raise FileExistsError(target)
            digest = file_sha256(source)
            target_digest = hashlib.sha256(ActionJournal._target_bytes(plan)).hexdigest()
            entries.append(
                {
                    "action_id": move_action_id(plan, sha256=digest),
                    "operation": plan.operation,
                    "source": str(source),
                    "target": str(target),
                    "sha256": digest,
                    "target_sha256": target_digest,
                    "status": "planned",
                    "undo_receipt": None,
                }
            )
        return entries

    def plan(self, plans: tuple[StoragePlan, ...]) -> Path:
        entries = self._planned_entries(plans)
        payload = {
            "schema": "nemofold.action-journal.v1",
            "run_id": self.run_id,
            "entries": entries,
        }
        if self.path.exists():
            current = self._load()
            comparable = [
                {
                    key: entry.get(key)
                    for key in (
                        "action_id",
                        "operation",
                        "source",
                        "target",
                        "sha256",
                        "target_sha256",
                    )
                }
                for entry in current["entries"]
            ]
            expected = [
                {
                    key: entry.get(key)
                    for key in (
                        "action_id",
                        "operation",
                        "source",
                        "target",
                        "sha256",
                        "target_sha256",
                    )
                }
                for entry in entries
            ]
            if comparable != expected:
                raise RuntimeError("existing action journal does not match requested plans")
            return self.path
        self._write(payload)
        return self.path

    @staticmethod
    def _receipt(entry: dict[str, Any]) -> UndoReceipt:
        operation = entry.get("operation", "move")
        undo_plan = (
            {
                "action": "move",
                "source": entry["target"],
                "target": entry["source"],
            }
            if operation == "move"
            else {
                "action": "delete_generated_copy",
                "target": entry["target"],
            }
        )
        return UndoReceipt(
            action_id=entry["action_id"],
            before={"path": entry["source"], "sha256": entry["sha256"]},
            after={"path": entry["target"], "sha256": entry["target_sha256"]},
            undo_plan=undo_plan,
        )

    def execute(self, plans: tuple[StoragePlan, ...]) -> tuple[UndoReceipt, ...]:
        if not self.path.exists():
            self.plan(plans)
        payload = self._load()
        plans_by_id: dict[str, StoragePlan] = {}
        for plan in plans:
            source = Path(plan.source)
            digest = file_sha256(source) if source.is_file() else None
            if digest is not None:
                plans_by_id[move_action_id(plan, sha256=digest)] = plan
        receipts: list[UndoReceipt] = []
        for entry in payload["entries"]:
            source = Path(entry["source"])
            target = Path(entry["target"])
            expected_hash = entry["sha256"]
            expected_target_hash = entry["target_sha256"]
            operation = entry.get("operation", "move")
            if entry.get("status") == "executed":
                if not target.is_file() or file_sha256(target) != expected_target_hash:
                    raise RuntimeError(f"target changed after execution: {target}")
                if operation != "move" and (
                    not source.is_file() or file_sha256(source) != expected_hash
                ):
                    raise RuntimeError(f"source changed after execution: {source}")
                receipt_value = entry.get("undo_receipt")
                if not isinstance(receipt_value, dict):
                    raise RuntimeError("executed action is missing its undo receipt")
                receipts.append(
                    UndoReceipt(
                        action_id=receipt_value["action_id"],
                        before=receipt_value["before"],
                        after=receipt_value["after"],
                        undo_plan=receipt_value["undo_plan"],
                        status=receipt_value.get("status", "available"),
                    )
                )
                continue
            if entry.get("status") != "planned":
                raise RuntimeError("action journal contains an invalid status")
            if source.is_file():
                if file_sha256(source) != expected_hash:
                    raise RuntimeError(f"source changed after planning: {source}")
                if target.exists():
                    if (
                        operation != "move"
                        and target.is_file()
                        and file_sha256(target) == expected_target_hash
                    ):
                        receipt = self._receipt(entry)
                        entry["status"] = "executed"
                        entry["undo_receipt"] = to_primitive(receipt)
                        self._write(payload)
                        receipts.append(receipt)
                        continue
                    raise RuntimeError(f"planned target is occupied: {target}")
                matched_plan = plans_by_id.get(entry["action_id"])
                if matched_plan is None:
                    raise RuntimeError("planned action no longer matches the requested plans")
                if operation == "move":
                    receipt = apply_move(matched_plan, approved=True)
                else:
                    self._write_target(target, self._target_bytes(matched_plan))
                    receipt = self._receipt(entry)
            elif (
                operation == "move"
                and target.is_file()
                and file_sha256(target) == expected_target_hash
            ):
                receipt = self._receipt(entry)
            else:
                raise RuntimeError("planned move cannot be reconciled")
            entry["status"] = "executed"
            entry["undo_receipt"] = to_primitive(receipt)
            self._write(payload)
            receipts.append(receipt)
        return tuple(receipts)

    def controlled_paths(self) -> tuple[Path, ...]:
        payload = self._load()
        return tuple(
            Path(entry[key])
            for entry in payload["entries"]
            for key in ("source", "target")
        )

    def undo(self) -> tuple[UndoReceipt, ...]:
        payload = self._load()
        entries = payload["entries"]
        for entry in entries:
            source = Path(entry["source"])
            target = Path(entry["target"])
            expected_hash = entry["sha256"]
            expected_target_hash = entry["target_sha256"]
            operation = entry.get("operation", "move")
            status = entry.get("status")
            if status == "executed":
                if operation == "move":
                    executable = (
                        target.is_file()
                        and file_sha256(target) == expected_target_hash
                        and not source.exists()
                    )
                    reconciled = (
                        source.is_file()
                        and file_sha256(source) == expected_hash
                        and not target.exists()
                    )
                else:
                    executable = (
                        source.is_file()
                        and file_sha256(source) == expected_hash
                        and target.is_file()
                        and file_sha256(target) == expected_target_hash
                    )
                    reconciled = (
                        source.is_file()
                        and file_sha256(source) == expected_hash
                        and not target.exists()
                    )
                if not (executable or reconciled):
                    raise RuntimeError(f"undo preflight failed: {entry['action_id']}")
            elif status == "undone":
                if not source.is_file() or file_sha256(source) != expected_hash or target.exists():
                    raise RuntimeError(f"undone action state changed: {entry['action_id']}")
            else:
                raise RuntimeError("only executed actions can be undone")

        receipts: list[UndoReceipt] = []
        for entry in reversed(entries):
            receipt_value = entry.get("undo_receipt")
            if not isinstance(receipt_value, dict):
                raise RuntimeError("action is missing its undo receipt")
            receipt = UndoReceipt(
                action_id=receipt_value["action_id"],
                before=receipt_value["before"],
                after=receipt_value["after"],
                undo_plan=receipt_value["undo_plan"],
                status=receipt_value.get("status", "available"),
            )
            source = Path(entry["source"])
            target = Path(entry["target"])
            operation = entry.get("operation", "move")
            if entry["status"] == "executed" and target.is_file():
                if operation == "move":
                    receipt = undo_move(receipt, approved=True)
                else:
                    target.unlink()
                    receipt = UndoReceipt(
                        action_id=receipt.action_id,
                        before=receipt.before,
                        after=receipt.after,
                        undo_plan=receipt.undo_plan,
                        status="undone",
                    )
            else:
                receipt = UndoReceipt(
                    action_id=receipt.action_id,
                    before=receipt.before,
                    after=receipt.after,
                    undo_plan=receipt.undo_plan,
                    status="undone",
                )
            entry["status"] = "undone"
            entry["undo_receipt"] = to_primitive(receipt)
            self._write(payload)
            if not source.is_file() or target.exists():
                raise RuntimeError(f"undo verification failed: {entry['action_id']}")
            receipts.append(receipt)
        return tuple(receipts)
