#!/usr/bin/env python3
# coding: utf-8
# SPDX-License-Identifier: MIT
"""Stern-Lease mit Fence-Prüfung für decide/undo/append (Task #3743, D-20261012-001).

Plan-B-Modul: Der Zielcode writer.py @ bc57916 (DecisionClicker/Polarstern)
liegt außerhalb des BACH-Worktrees. Dieses Modul ist deshalb portabel
gehalten – nur Standardbibliothek (os, time, socket, uuid, pathlib), keine
hub-Imports – und kann 1:1 in den Zielzweig übernommen werden. Die
Einklinkpunkte beschreibt star_lease_INTEGRATION.md.

Funktionsweise:
- Eine Lock-Datei (Standard LOCK.txt) im Ressourcenverzeichnis sichert die
  Exklusivität über Prozessgrenzen hinweg (exklusives Anlegen mit "x").
- Jede acquire-Runde erzeugt einen neuen Fence (UUID), der in der Lock-Datei
  steht. Vor jeder Mutation verifiziert check_fence() Inhalt, Fence und TTL.
- Abgelaufene Locks werden gestohlen (Steal); vorher sichert eine
  Konfliktkopie den Fremd-Inhalt.
"""

import os
import socket
import time
import uuid
from pathlib import Path

DEFAULT_TTL = 30.0
MAX_ACQUIRE_ATTEMPTS = 3


class LeaseError(Exception):
    """Basisklasse aller Stern-Lease-Fehler."""


class LeaseDeniedError(LeaseError):
    """Lock wird von einem anderen Holder gehalten (echter Konflikt)."""


class LeaseUnavailableError(LeaseError):
    """Lock ist aktuell nicht erlangbar (I/O, Gnadenfrist, Versuchslimit)."""


class LeaseViolation(LeaseError):
    """Eigene Lease-Invariante verletzt (Fence-Bruch, Doppel-Acquire)."""


def _hostname():
    try:
        return socket.gethostname()
    except Exception:
        return "unknown-host"


class StarLease:
    """Prozessübergreifende Lock-Datei mit Fence-Token, TTL und Steal."""

    def __init__(self, resource_dir=None, lock_name="LOCK.txt", warn=None, corrupt_grace=None):
        self._resource_dir = Path(resource_dir) if resource_dir is not None else None
        self._lock_name = lock_name
        self._warn_cb = warn
        self._corrupt_grace = corrupt_grace
        self._acquired = False
        self._holder = None
        self._fence = None
        self._expiry_epoch = None
        self._lock_text = None

    # ------------------------------------------------------------------
    # Eigenschaften
    # ------------------------------------------------------------------

    @property
    def lock_path(self):
        return self._resolve_dir(None) / self._lock_name

    @property
    def is_held(self):
        return bool(self._acquired)

    @property
    def fence(self):
        return self._fence

    @property
    def holder(self):
        return self._holder

    # ------------------------------------------------------------------
    # Kontextmanager
    # ------------------------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False

    # ------------------------------------------------------------------
    # Interne Helfer
    # ------------------------------------------------------------------

    def _resolve_dir(self, arg):
        if arg is not None:
            return Path(arg)
        if self._resource_dir is not None:
            return self._resource_dir
        raise LeaseError("kein resource_dir gesetzt und keines übergeben")

    @staticmethod
    def _render_payload(holder, expiry_epoch, fence):
        lines = [
            "star-lease: 1",
            "host: %s" % _hostname(),
            "pid: %d" % os.getpid(),
            "holder: %s" % holder,
            "expiry: %s" % time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(expiry_epoch)),
            "expiry_epoch: %r" % expiry_epoch,
            "fence: %s" % fence,
        ]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _parse(raw):
        parsed = {}
        for line in raw.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                parsed[key.strip()] = value.strip()
        return parsed

    @staticmethod
    def _read_lock_text(path):
        try:
            with open(str(path), "r", encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return None

    def _warn(self, message):
        cb = self._warn_cb
        if callable(cb):
            try:
                cb(message)
            except Exception:
                pass

    def _save_conflict_copy(self, directory, reason, raw):
        stem = Path(self._lock_name).stem
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        token = uuid.uuid4().hex[:8]
        target = directory / ("%s-Konflikt-%s-%s.txt" % (stem, stamp, token))
        raw_text = raw if raw is not None else ""
        if raw_text and not raw_text.endswith("\n"):
            raw_text += "\n"
        text = "# Konfliktkopie (star-lease)\n"
        text += "# Grund: %s\n" % reason
        text += "# Quelle: %s\n" % self._lock_name
        text += raw_text
        try:
            with open(str(target), "x", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
        except OSError:
            return None
        return target

    def _steal_lock(self, directory, lock, raw, reason):
        self._warn("Steal abgelaufenes Lock %s (%s)" % (lock, reason))
        self._save_conflict_copy(directory, "Steal (%s)" % reason, raw)
        try:
            os.remove(str(lock))
        except FileNotFoundError:
            pass

    def _handle_existing_lock(self, directory, lock, ttl):
        raw = self._read_lock_text(lock)
        parsed = self._parse(raw) if raw is not None else {}
        their_expiry = None
        if raw is not None and "expiry_epoch" in parsed:
            try:
                their_expiry = float(parsed["expiry_epoch"])
            except ValueError:
                their_expiry = None
        now = time.time()
        if their_expiry is None:
            # Korrupt: kein lesbares expiry_epoch -> Gnadenfrist über mtime.
            try:
                mtime = os.path.getmtime(str(lock))
            except OSError:
                mtime = now
            grace = self._corrupt_grace if self._corrupt_grace else ttl
            if now - mtime >= grace:
                self._steal_lock(
                    directory,
                    lock,
                    raw,
                    "korrupt, kein expiry_epoch lesbar (mtime-Fallback)",
                )
                return
            raise LeaseUnavailableError(
                "[UNAVAILABLE] Lock %s korrupt, aber noch zu frisch für einen "
                "Steal (Gnadenfrist %.1fs)" % (lock, grace)
            )
        if now >= their_expiry:
            self._steal_lock(
                directory,
                lock,
                raw,
                "abgelaufen (expiry_epoch=%s)" % parsed["expiry_epoch"],
            )
            return
        raise LeaseDeniedError(
            "[CONFLICT] Lock %s wird gehalten von holder=%s host=%s pid=%s bis %s"
            % (
                lock,
                parsed.get("holder"),
                parsed.get("host"),
                parsed.get("pid"),
                parsed.get("expiry") or parsed.get("expiry_epoch"),
            )
        )

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def acquire(self, resource_dir=None, holder=None, ttl=DEFAULT_TTL):
        if self._acquired:
            raise LeaseViolation(
                "[VIOLATION] Lease bereits gehalten (holder=%s, fence=%s)"
                % (self._holder, self._fence)
            )
        directory = self._resolve_dir(resource_dir)
        holder_text = holder if holder else "pid-%d" % os.getpid()
        fence = str(uuid.uuid4())
        lock = directory / self._lock_name
        for _attempt in range(MAX_ACQUIRE_ATTEMPTS):
            expiry_epoch = time.time() + ttl
            payload = self._render_payload(holder_text, expiry_epoch, fence)
            try:
                with open(str(lock), "x", encoding="utf-8") as fh:
                    fh.write(payload)
                    fh.flush()
                    os.fsync(fh.fileno())
            except FileExistsError:
                self._handle_existing_lock(directory, lock, ttl)
                continue
            except OSError as exc:
                raise LeaseUnavailableError(
                    "[UNAVAILABLE] Lock %s nicht anlegbar: %s" % (lock, exc)
                )
            raw = self._read_lock_text(lock)
            if raw != payload:
                self._save_conflict_copy(
                    directory, "Readback weicht vom eigenen Payload ab", raw
                )
                raise LeaseUnavailableError(
                    "[UNAVAILABLE] Readback weicht vom eigenen Payload ab "
                    "(Lock %s wird nicht gelöscht)" % lock
                )
            self._acquired = True
            self._holder = holder_text
            self._fence = fence
            self._expiry_epoch = expiry_epoch
            self._lock_text = payload
            self._resource_dir = directory
            return True
        raise LeaseUnavailableError(
            "[UNAVAILABLE] Lock %s nach %d Versuchen nicht erlangt"
            % (lock, MAX_ACQUIRE_ATTEMPTS)
        )

    def check_fence(self):
        if not self._acquired:
            raise LeaseViolation(
                "[VIOLATION] kein Lease gehalten (check_fence vor acquire?)"
            )
        lock = self.lock_path
        if not lock.exists():
            raise LeaseViolation("[VIOLATION] Lock fehlt: %s" % lock)
        raw = self._read_lock_text(lock)
        if raw is None:
            raise LeaseViolation("[VIOLATION] Lock unlesbar: %s" % lock)
        if raw != self._lock_text:
            raise LeaseViolation("[VIOLATION] Lock-Inhalt verändert: %s" % lock)
        parsed = self._parse(raw)
        if parsed.get("fence") != self._fence:
            raise LeaseViolation(
                "[VIOLATION] Fence passt nicht (erwartet=%s, gefunden=%s)"
                % (self._fence, parsed.get("fence"))
            )
        now = time.time()
        if now >= self._expiry_epoch:
            raise LeaseViolation(
                "[VIOLATION] Lease abgelaufen (expiry_epoch=%s)" % self._expiry_epoch
            )
        return True

    def renew(self, ttl=None):
        if ttl is None:
            ttl = DEFAULT_TTL
        self.check_fence()
        lock = self.lock_path
        directory = lock.parent
        expiry_epoch = time.time() + ttl
        payload = self._render_payload(self._holder, expiry_epoch, self._fence)
        tmp = directory / (
            "%s.tmp-%s" % (Path(self._lock_name).stem, uuid.uuid4().hex[:8])
        )
        try:
            with open(str(tmp), "x", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(str(tmp), str(lock))
        except OSError as exc:
            try:
                os.remove(str(tmp))
            except OSError:
                pass
            raise LeaseUnavailableError(
                "[UNAVAILABLE] Renew von Lock %s fehlgeschlagen: %s" % (lock, exc)
            )
        raw = self._read_lock_text(lock)
        if raw != payload:
            self._save_conflict_copy(
                directory, "Renew-Readback weicht vom eigenen Payload ab", raw
            )
            self._acquired = False
            raise LeaseViolation(
                "[VIOLATION] Renew-Readback weicht vom eigenen Payload ab: %s" % lock
            )
        self._expiry_epoch = expiry_epoch
        self._lock_text = payload
        return True

    def release(self):
        if not self._acquired:
            return False
        lock = self.lock_path
        if not lock.exists():
            self._acquired = False
            raise LeaseViolation("[VIOLATION] Lock fehlt beim Release: %s" % lock)
        raw = self._read_lock_text(lock)
        if raw != self._lock_text:
            self._save_conflict_copy(
                lock.parent, "Release bei verändertem Lock-Inhalt", raw
            )
            raise LeaseViolation(
                "[VIOLATION] Lock-Inhalt verändert beim Release: %s" % lock
            )
        try:
            os.remove(str(lock))
        except FileNotFoundError:
            self._acquired = False
            raise LeaseViolation("[VIOLATION] Lock fehlt beim Entfernen: %s" % lock)
        self._acquired = False
        self._holder = None
        self._fence = None
        self._expiry_epoch = None
        self._lock_text = None
        return True

    def status(self, resource_dir=None):
        lock = self._resolve_dir(resource_dir) / self._lock_name
        info = {
            "held": self._acquired,
            "path": str(lock),
            "exists": False,
            "host": None,
            "pid": None,
            "holder": None,
            "expiry_epoch": None,
            "fence": None,
            "expired": None,
            "corrupt": False,
        }
        if not lock.exists():
            return info
        info["exists"] = True
        raw = self._read_lock_text(lock)
        if raw is None:
            info["corrupt"] = True
            return info
        parsed = self._parse(raw)
        info["host"] = parsed.get("host")
        info["holder"] = parsed.get("holder")
        info["fence"] = parsed.get("fence")
        pid_text = parsed.get("pid")
        if pid_text is not None:
            try:
                info["pid"] = int(pid_text)
            except ValueError:
                info["pid"] = None
        expiry_text = parsed.get("expiry_epoch")
        if expiry_text is None:
            info["corrupt"] = True
            return info
        try:
            expiry_epoch = float(expiry_text)
        except ValueError:
            info["corrupt"] = True
            return info
        info["expiry_epoch"] = expiry_epoch
        info["expired"] = time.time() >= expiry_epoch
        return info