# SPDX-License-Identifier: MIT
"""Host-local, process-independent admission for one local model call.

OS file locks release on process death. Local calls register process-bound
tickets; the existing inference lock remains the single model-call owner.
Queue records contain no prompts, sessions, tokens, or model results.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import psutil
from hub._services.user_config_store import _exclusive_lock

_TICKET_SCHEMA = "bach.local-inference-ticket.v1"
_QUEUE_STATE_SCHEMA = "bach.local-inference-queue-state.v1"
_MAX_CONSECUTIVE_FOREGROUND = 3
_TICKET_ID = re.compile(r"[0-9a-f]{32}")
_SHA256 = re.compile(r"[0-9a-f]{64}")

_LOG = logging.getLogger(__name__)


def _load_unload_guard():
    """Lädt den stdlib-only Speicherdruck-Wächter tolerant nach (Pfad-Fallback)."""
    try:
        from tools.maintenance import memory_pressure_unload_guard as guard
        return guard
    except Exception:
        pass
    try:
        import importlib.util
        import sys

        root = Path(__file__).resolve().parents[3]
        source = root / "tools" / "maintenance" / "memory_pressure_unload_guard.py"
        spec = importlib.util.spec_from_file_location(
            "bach_memory_pressure_unload_guard", source
        )
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules.setdefault(spec.name, module)
        return module
    except Exception:
        return None


def _release_model_locked(model, *, digest=None, timeout_seconds=0, wait=True):
    """Entlädt ein Modell und verifiziert per Poll; niemals eine Exception nach außen."""
    guard = _load_unload_guard()
    if guard is None:
        _LOG.warning("Unload-Wächter nicht verfügbar; Modell %r bleibt geladen", model)
        return False
    try:
        report = guard.unload(model, digest=digest, timeout_s=timeout_seconds, wait=wait)
    except Exception as exc:
        _LOG.warning("Unload von %r fehlgeschlagen: %s", model, exc)
        return False
    if not isinstance(report, dict) or not report.get("unloaded"):
        detail = report.get("warning") if isinstance(report, dict) else report
        _LOG.warning("Unload von %r nicht bestätigt: %s", model, detail)
        return False
    return True


class HostInferenceGate:

    def release_model_now(self, model_target, *, timeout_seconds=0):
        """API zum sofortigen Entladen eines Modells.

        Verwendet den exklusiven Inferenz-Lock ``self.root/"inference"``, ruft den
        Adapter ``_release_model_locked`` auf und liefert ein ``dict`` mit
        ``ok``/``released``/``warning``/``error``. Werft niemals eine Exception.

        Parameter
        ----------
        model_target : dict
            Modallexikon wie es ``model_target`` in ``turn()`` erwartet
            (``{"model": "…", …}``).
        timeout_seconds : int, Standard 0
            Wird akzeptiert für API-Konsistenz; hier keine Wartezeit (0 bedeutet sofortige Freigabe oder Ausfall).
        """
        result = {"ok": False, "released": False, "warning": None, "error": None}
        try:
            lock = _exclusive_lock(self.root / "inference", timeout_seconds=timeout_seconds)
            try:
                model = model_target.get("model", "")
                digest = self._target_digest(model_target) if model_target else None
                released = _release_model_locked(
                    model, digest=digest, timeout_seconds=timeout_seconds, wait=True
                )
                result["released"] = bool(released)
                result["ok"] = bool(released)
            except Exception as exc:
                result["error"] = str(exc)
                _LOG.warning("release_model_now Fehler: %s", exc)
            finally:
                lock.__exit__(None, None, None)
        except TimeoutError:
            result["warning"] = "Konnte exklusiven Lock nicht innerhalb von " + f"{timeout_seconds}s erwerben"
        except BaseException as exc:
            result["error"] = str(exc)
            _LOG.warning("release_model_now Exception: %s", exc)
        return result
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
        """Prüft, ob ein Inferenz-Record noch aktiv ist.

        Verwendet den memory-pressure-unload-guard: ein als entladen
        gemeldetes Modell gilt als nicht mehr alive; ein in list_running
        gefundenes Modell/digest als alive. Ohne Modellnachweis oder ohne
        Guard bleibt der Record erhalten (unknown is not proof).
        """
        model_target = record.get("model_target")
        guard = _load_unload_guard()
        if guard is None:
            return True

        digest = None
        model_name = None
        if isinstance(model_target, dict):
            digest = HostInferenceGate._target_digest(model_target)
            model_name = model_target.get("model")

        if digest and guard.is_unloaded(digest=digest):
            return False

        running = guard.list_running()
        for item in running:
            if digest and item.get("digest") == digest:
                return True
            if model_name and (
                item.get("model") == model_name or item.get("name") == model_name
            ):
                return True

        # Legacy-Records ohne Modellnachweis können nicht per Guard bewertet werden.
        if digest is None and model_name is None:
            return True
        return False

    @staticmethod
    def _read(path):
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise RuntimeError("Ungültiger Inferenz-Koordinationsbeleg") from None
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

    def _queue_lock_path(self):
        # _exclusive_lock adds ".lock", keeping this distinct from the JSON state.
        return self.root / "queue-state"

    def _queue_streak_locked(self):
        path = self.root / "queue-state.json"
        if path.is_symlink():
            raise RuntimeError("Ungültiger Inferenz-Koordinationsbeleg")
        record = self._read(path)
        if record is None:
            return 0
        if (
            set(record) != {"schema", "foreground_streak"}
            or record.get("schema") != _QUEUE_STATE_SCHEMA
            or type(record.get("foreground_streak")) is not int
            or not 0 <= record["foreground_streak"] <= _MAX_CONSECUTIVE_FOREGROUND
        ):
            raise RuntimeError("Ungültiger Inferenz-Koordinationsbeleg")
        return record["foreground_streak"]

    def _write_queue_streak_locked(self, foreground_streak):
        path = self.root / "queue-state.json"
        if path.is_symlink():
            raise RuntimeError("Ungültiger Inferenz-Koordinationsbeleg")
        self._write(path, {
            "schema": _QUEUE_STATE_SCHEMA,
            "foreground_streak": foreground_streak,
        })

    def _live_tickets_locked(self):
        tickets = []
        seen_sequences = set()
        expected_keys = {
            "schema", "ticket_id", "pid", "created", "priority",
            "sequence", "target_sha256",
        }
        for path in sorted(self.root.glob("ticket-*.json")):
            if path.is_symlink():
                raise RuntimeError("Ungültiger Inferenz-Koordinationsbeleg")
            ticket = self._read(path)
            if ticket is None:
                continue
            filename_id = path.name.removeprefix("ticket-").removesuffix(".json")
            if (
                set(ticket) != expected_keys
                or ticket.get("schema") != _TICKET_SCHEMA
                or not _TICKET_ID.fullmatch(filename_id)
                or ticket.get("ticket_id") != filename_id
                or type(ticket.get("pid")) is not int
                or ticket["pid"] <= 0
                or type(ticket.get("created")) not in (int, float)
                or not math.isfinite(ticket["created"])
                or ticket["created"] <= 0
                or type(ticket.get("sequence")) is not int
                or ticket["sequence"] <= 0
                or ticket.get("priority") not in {"foreground", "background"}
                or not isinstance(ticket.get("target_sha256"), str)
                or not _SHA256.fullmatch(ticket["target_sha256"])
            ):
                raise RuntimeError("Ungültiger Inferenz-Koordinationsbeleg")
            if ticket["sequence"] in seen_sequences:
                raise RuntimeError("Ungültiger Inferenz-Koordinationsbeleg")
            seen_sequences.add(ticket["sequence"])
            if self._alive(ticket):
                tickets.append((path, ticket))
            else:
                path.unlink(missing_ok=True)
        return sorted(tickets, key=lambda item: item[1]["sequence"])

    def _legacy_foreground_count_locked(self, live_ticket_ids):
        """Honor pre-queue foreground markers while older processes are alive."""
        count = 0
        legacy_keys = {"pid", "created"}
        queued_keys = legacy_keys | {"ticket_id"}
        for path in sorted(self.root.glob("foreground-*.json")):
            if path.is_symlink():
                raise RuntimeError("Ungültiger Inferenz-Koordinationsbeleg")
            record = self._read(path)
            if record is None:
                continue
            if set(record) not in (legacy_keys, queued_keys):
                raise RuntimeError("Ungültiger Inferenz-Koordinationsbeleg")
            ticket_id = record.get("ticket_id")
            if ticket_id is not None and (
                not isinstance(ticket_id, str) or not _TICKET_ID.fullmatch(ticket_id)
            ):
                raise RuntimeError("Ungültiger Inferenz-Koordinationsbeleg")
            if not self._alive(record):
                path.unlink(missing_ok=True)
            elif ticket_id not in live_ticket_ids:
                # Old-format markers have no ticket_id and remain visible to
                # both old and new workers as a foreground priority signal.
                count += 1
        return count

    def _queue_snapshot_locked(self):
        foreground_streak = self._queue_streak_locked()
        tickets = self._live_tickets_locked()
        live_ids = {ticket["ticket_id"] for _, ticket in tickets}
        legacy_foreground = self._legacy_foreground_count_locked(live_ids)
        return tickets, legacy_foreground, foreground_streak

    @staticmethod
    def _target_digest(model_target):
        binding = {"bound": model_target is not None, "model_target": model_target}
        encoded = json.dumps(
            binding, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    async def _register_ticket(self, identity, priority, model_target):
        while True:
            try:
                with _exclusive_lock(self._queue_lock_path(), timeout_seconds=0):
                    tickets, _, _ = self._queue_snapshot_locked()
                    sequence = max(
                        (ticket["sequence"] for _, ticket in tickets), default=0
                    ) + 1
                    ticket_id = uuid.uuid4().hex
                    ticket_path = self.root / f"ticket-{ticket_id}.json"
                    marker = (
                        self.root / f"foreground-{ticket_id}.json"
                        if priority == "foreground" else None
                    )
                    if marker is not None:
                        # Older workers understand this marker and will yield to it.
                        self._write(marker, {**identity, "ticket_id": ticket_id})
                    try:
                        self._write(ticket_path, {
                            "schema": _TICKET_SCHEMA,
                            "ticket_id": ticket_id,
                            **identity,
                            "priority": priority,
                            "sequence": sequence,
                            "target_sha256": self._target_digest(model_target),
                        })
                    except BaseException:
                        ticket_path.unlink(missing_ok=True)
                        if marker is not None:
                            marker.unlink(missing_ok=True)
                        raise
                    return ticket_path, marker, ticket_id
            except TimeoutError:
                await asyncio.sleep(.025)

    async def _remove_ticket(self, ticket_path, marker):
        while True:
            try:
                with _exclusive_lock(self._queue_lock_path(), timeout_seconds=0):
                    if ticket_path is not None:
                        ticket_path.unlink(missing_ok=True)
                    if marker is not None:
                        marker.unlink(missing_ok=True)
                return
            except TimeoutError:
                await asyncio.sleep(.025)

    def _admit_if_next(self, ticket_id):
        with _exclusive_lock(self._queue_lock_path(), timeout_seconds=0):
            tickets, legacy_foreground, foreground_streak = self._queue_snapshot_locked()
            own = next(
                (ticket for _, ticket in tickets if ticket["ticket_id"] == ticket_id),
                None,
            )
            if own is None:
                raise RuntimeError("Inferenz-Ticket fehlt")
            foreground = [
                ticket for _, ticket in tickets if ticket["priority"] == "foreground"
            ]
            background = [
                ticket for _, ticket in tickets if ticket["priority"] == "background"
            ]
            if legacy_foreground:
                # Let the older caller remove its own marker by acquiring the
                # existing owner lock; new tickets must not starve it.
                selected = None
            elif background and foreground_streak >= _MAX_CONSECUTIVE_FOREGROUND:
                selected = background[0]
            elif foreground:
                selected = foreground[0]
            else:
                selected = background[0] if background else None
            if selected is None or selected["ticket_id"] != ticket_id:
                return False

            if selected["priority"] == "background":
                next_streak = 0
            elif background:
                next_streak = min(
                    foreground_streak + 1, _MAX_CONSECUTIVE_FOREGROUND
                )
            else:
                next_streak = 0
            self._write_queue_streak_locked(next_streak)
            (self.root / f"ticket-{ticket_id}.json").unlink(missing_ok=True)
            if selected["priority"] == "foreground":
                (self.root / f"foreground-{ticket_id}.json").unlink(missing_ok=True)
            return True

    def _foreground_waiters(self):
        if not self.root.exists():
            return 0
        with _exclusive_lock(self._queue_lock_path(), timeout_seconds=1):
            tickets, legacy_foreground, _ = self._queue_snapshot_locked()
            return (
                sum(ticket["priority"] == "foreground" for _, ticket in tickets)
                + legacy_foreground
            )

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
    async def turn(self, chat_id: str, priority: str, *, check_ready=None, model_target=None,
                   release_model: bool = False):
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
        ticket_path = marker = None
        acquired = None
        try:
            if check_ready is not None:
                check_ready()
            ticket_path, marker, ticket_id = await self._register_ticket(
                identity, priority, model_target
            )
            while acquired is None:
                if check_ready is not None:
                    check_ready()
                candidate = _exclusive_lock(self.root / "inference", timeout_seconds=0)
                try:
                    candidate.__enter__()
                except TimeoutError:
                    await asyncio.sleep(.025)
                    continue
                try:
                    admitted = self._admit_if_next(ticket_id)
                except TimeoutError:
                    candidate.__exit__(None, None, None)
                    await asyncio.sleep(.025)
                    continue
                except BaseException:
                    candidate.__exit__(None, None, None)
                    raise
                if not admitted:
                    candidate.__exit__(None, None, None)
                    await asyncio.sleep(.025)
                    continue
                acquired = candidate
            self._write(self.root / "owner.json", {
                **identity, "chat_id": str(chat_id), "priority": priority, "started_at": time.time(),
                **({"model_target": dict(model_target)} if model_target is not None else {}),
            })
            if release_model and model_target is not None:
                try:
                    await asyncio.to_thread(_release_model_locked, model_target["model"])
                except Exception as exc:  # Aufräumarbeit darf den Turn nie beenden
                    _LOG.warning("Unload-Vorbereitung fehlgeschlagen: %s", exc)
            yield
        finally:
            try:
                if ticket_path is not None:
                    await self._remove_ticket(ticket_path, marker)
            finally:
                if acquired is not None:
                    try:
                        (self.root / "owner.json").unlink(missing_ok=True)
                    finally:
                        acquired.__exit__(None, None, None)
