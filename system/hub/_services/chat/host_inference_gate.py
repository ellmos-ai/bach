# SPDX-License-Identifier: MIT
"""Host-local, process-independent arbitration for one local model call.

OS file locks release on process death. Foreground requests carry a PID and
process creation time, so abandoned requests do not block Always-On forever.
No sessions, tokens, prompts or model results are written here.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import time
import uuid

import psutil

from hub._services.user_config_store import _exclusive_lock


class HostInferenceGate:
    def __init__(self, root: Path | None = None):
        runtime = Path(os.environ.get("BACH_RUNTIME_DIR") or Path.home() / ".bach" / "runtime")
        self.root = (root or runtime / "local-inference").expanduser().resolve()
        if any(part.lower().startswith("onedrive") for part in self.root.parts):
            raise RuntimeError("Lokale Inferenzkoordination darf nicht in OneDrive liegen")

    @staticmethod
    def _identity():
        return {"pid": os.getpid(), "created": psutil.Process().create_time()}

    @staticmethod
    def _alive(record):
        pid, created = record.get("pid"), record.get("created")
        if type(pid) is not int or pid <= 0 or type(created) not in (int, float):
            raise RuntimeError("Ungültiger Inferenz-Koordinationsbeleg")
        try:
            process = psutil.Process(pid)
            return (
                process.is_running()
                and process.status() != psutil.STATUS_ZOMBIE
                and abs(process.create_time() - created) < .001
            )
        except psutil.NoSuchProcess:
            return False
        except psutil.AccessDenied:
            return True  # Unknown is not proof that a request is abandoned.

    @staticmethod
    def _read(path):
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if not isinstance(result, dict):
            raise RuntimeError("Ungültiger Inferenz-Koordinationsbeleg")
        return result

    @staticmethod
    def _write(path, record):
        temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                json.dump(record, handle, ensure_ascii=False)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _foreground_waiters(self):
        count = 0
        for path in self.root.glob("foreground-*.json"):
            record = self._read(path)
            if record is None:
                continue
            if self._alive(record):
                count += 1
            else:
                path.unlink(missing_ok=True)
        return count

    def status(self):
        record = self._read(self.root / "owner.json")
        active = bool(record and self._alive(record))
        return {
            "active": active,
            "holder": "BACH" if active else None,
            "chat_id": record.get("chat_id") if active else None,
            "priority": record.get("priority") if active else None,
            "started_at": record.get("started_at") if active else None,
            "foreground_waiters": self._foreground_waiters(),
            "model_target": record.get("model_target") if active else None,
        }

    @asynccontextmanager
    async def turn(self, chat_id: str, priority: str, *, check_ready=None, model_target=None):
        if priority not in {"foreground", "background"}:
            raise ValueError("Ungültige Inferenzpriorität")
        if model_target is not None:
            fields = {"socket_id", "binding_id", "agent_id", "backend", "model"}
            if (not isinstance(model_target, dict) or set(model_target) != fields
                    or any(not isinstance(value, str) or not value or len(value) > 192
                           for value in model_target.values())):
                raise ValueError("Ungültiger Modellzielnachweis")
        self.root.mkdir(parents=True, exist_ok=True)
        identity = self._identity()
        marker = self.root / f"foreground-{uuid.uuid4().hex}.json" if priority == "foreground" else None
        acquired = None
        try:
            if marker:
                self._write(marker, identity)
            while acquired is None:
                if check_ready is not None:
                    check_ready()
                if priority == "background" and self._foreground_waiters():
                    await asyncio.sleep(.025)
                    continue
                candidate = _exclusive_lock(self.root / "inference", timeout_seconds=0)
                try:
                    candidate.__enter__()
                except TimeoutError:
                    await asyncio.sleep(.025)
                    continue
                # Check again after taking the lock: the foreground may have
                # registered while this background caller was acquiring it.
                try:
                    waiting = priority == "background" and self._foreground_waiters()
                except BaseException:
                    candidate.__exit__(None, None, None)
                    raise
                if waiting:
                    candidate.__exit__(None, None, None)
                    await asyncio.sleep(.025)
                    continue
                acquired = candidate
            self._write(self.root / "owner.json", {
                **identity, "chat_id": str(chat_id), "priority": priority, "started_at": time.time(),
                **({"model_target": dict(model_target)} if model_target is not None else {}),
            })
            if marker:
                marker.unlink(missing_ok=True)
            yield
        finally:
            try:
                if marker:
                    marker.unlink(missing_ok=True)
                if acquired is not None:
                    (self.root / "owner.json").unlink(missing_ok=True)
            finally:
                if acquired is not None:
                    acquired.__exit__(None, None, None)
