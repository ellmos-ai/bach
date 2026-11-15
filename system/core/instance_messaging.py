# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

"""
Inter-Instance Messaging - File-basiertes Message-Passing zwischen BACH-Instanzen
==================================================================================

Nachrichten sind JSON-Dateien in einem Shared Directory:

    data/messages/pending/<to_instance>/<timestamp>_<from>_<event>.json
    data/messages/archive/<date>/<timestamp>_<from>_<event>.json

Nachrichtenformat:
    {
        "id": "msg-1709300000-abc123",
        "from_instance": "DESKTOP-ABC-12345",
        "to_instance": "DESKTOP-ABC-67890" | "*",
        "event": "after_task_done",
        "context": { ... },
        "created_at": "2026-03-01T10:00:00.123456",
        "ttl_seconds": 300
    }

Design-Entscheidungen:
    - Kein Netzwerk noetig (nur Filesystem)
    - OneDrive-kompatibel (kein File-Locking, atomic writes)
    - TTL fuer automatische Bereinigung alter Nachrichten
    - Empfaenger-Ordner (pending/<instance_id>/) fuer schnelles Polling
    - Broadcast via "*"-Ordner (alle lesen)

Version: 1.0.0
"""

import json
import os
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Maximales Alter fuer Nachrichten (Standard: 5 Minuten)
DEFAULT_TTL_SECONDS = 300

# Maximale Anzahl Nachrichten im Archive pro Tag (Guard gegen Massen-Aufrufe)
MAX_ARCHIVE_PER_DAY = 1000


class InstanceMessaging:
    """File-basiertes Inter-Instanz-Messaging (JSON-Dateien, nach dem Lesen ins Archiv).

    Altteil (BACH #4147): nie aktiviert, App.enable_messaging hat keinen Aufrufer; DEPRICATED.md."""
    __ocean_deprecated__ = True  # Marker wie @deprecated_legacy_bach, ohne hub-Import (~0,8 s)
    __ocean_replacement__ = "memoryhooker.inbox / ticket-master host receipts"

    def __init__(self, data_dir: Path, instance_id: str):
        """Initialisiert das Messaging-System.

        Args:
            data_dir: Pfad zum data/ Verzeichnis
            instance_id: ID dieser Instanz (z.B. "DESKTOP-ABC-12345")
        """
        self.messages_dir = data_dir / "messages"
        self.pending_dir = self.messages_dir / "pending"
        self.archive_dir = self.messages_dir / "archive"
        self.instance_id = instance_id

        # Verzeichnisse erstellen
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

        # Eigenen Posteingang erstellen
        self._my_inbox = self.pending_dir / self.instance_id
        self._my_inbox.mkdir(exist_ok=True)

        # Broadcast-Verzeichnis
        self._broadcast_dir = self.pending_dir / "_broadcast"
        self._broadcast_dir.mkdir(exist_ok=True)

    def send(self, to_instance: str, event: str,
             context: dict = None, ttl: int = DEFAULT_TTL_SECONDS) -> bool:
        """Sendet eine Nachricht an eine bestimmte Instanz.

        Args:
            to_instance: Ziel-Instanz-ID
            event: Event-Name (z.B. "after_task_done")
            context: Event-Kontext (beliebiges Dict)
            ttl: Time-To-Live in Sekunden (Standard: 300)

        Returns:
            True wenn erfolgreich geschrieben
        """
        msg = self._create_message(to_instance, event, context, ttl)

        # Ziel-Verzeichnis erstellen falls noetig
        target_dir = self.pending_dir / to_instance
        target_dir.mkdir(exist_ok=True)

        filename = self._message_filename(msg)
        target_file = target_dir / filename

        return self._safe_write_json(target_file, msg)

    def broadcast(self, event: str, context: dict = None,
                  ttl: int = DEFAULT_TTL_SECONDS,
                  registry=None) -> int:
        """Sendet Nachricht an ALLE anderen aktiven Instanzen.

        Zwei Strategien:
        1. Wenn Registry verfuegbar: Direkt an jeden einzeln
        2. Ohne Registry: In _broadcast/ ablegen (alle lesen dort)

        Args:
            event: Event-Name
            context: Event-Kontext
            ttl: Time-To-Live
            registry: Optional InstanceRegistry fuer gezielte Zustellung

        Returns:
            Anzahl gesendeter Nachrichten
        """
        sent = 0

        if registry:
            # Strategie 1: Gezielte Zustellung
            others = registry.list_other_instances()
            for inst in others:
                target_id = inst.get("instance_id")
                if target_id and self.send(target_id, event, context, ttl):
                    sent += 1
        else:
            # Strategie 2: Broadcast-Verzeichnis
            msg = self._create_message("*", event, context, ttl)
            filename = self._message_filename(msg)
            target_file = self._broadcast_dir / filename

            if self._safe_write_json(target_file, msg):
                sent = 1

        return sent

    def receive(self, include_broadcast: bool = True) -> list[dict]:
        """Liest und archiviert ausstehende Nachrichten fuer diese Instanz.

        Nachrichten werden nach dem Lesen ins Archiv verschoben.
        Abgelaufene Nachrichten (TTL ueberschritten) werden verworfen.

        Args:
            include_broadcast: Auch Broadcast-Nachrichten lesen (default: True)

        Returns:
            Liste von Nachricht-Dicts (nur gueltige, nicht-abgelaufene)
        """
        messages = []

        # 1. Eigenen Posteingang lesen
        messages.extend(self._read_from_dir(self._my_inbox))

        # 2. Broadcast-Verzeichnis lesen
        if include_broadcast:
            messages.extend(self._read_from_dir(self._broadcast_dir, is_broadcast=True))

        # Nach Zeitstempel sortieren (aelteste zuerst)
        messages.sort(key=lambda m: m.get("created_at", ""))

        return messages

    def process_incoming(self, hooks_registry) -> int:
        """Liest ausstehende Nachrichten und emittiert sie als lokale Hook-Events.

        Dies ist die Bruecke zwischen Messaging und dem Hook-System:
        Eingehende Nachrichten werden als lokale Events gefeuert.

        Args:
            hooks_registry: HookRegistry-Instanz (core.hooks.hooks)

        Returns:
            Anzahl verarbeiteter Nachrichten
        """
        messages = self.receive()
        processed = 0

        for msg in messages:
            event = msg.get("event")
            context = msg.get("context", {})

            if not event:
                continue

            # Metadaten hinzufuegen
            context["_remote"] = True
            context["_from_instance"] = msg.get("from_instance", "unknown")
            context["_message_id"] = msg.get("id", "unknown")

            # Als lokales Event emittieren (OHNE broadcast, um Loops zu vermeiden!)
            try:
                hooks_registry.emit(event, context)
                processed += 1
            except Exception:
                # Fehler beim Verarbeiten -- Nachricht ist schon archiviert
                pass

        return processed

    def pending_count(self) -> int:
        """Zaehlt ausstehende Nachrichten fuer diese Instanz.

        Returns:
            Anzahl ausstehender Nachrichten
        """
        count = 0

        if self._my_inbox.exists():
            count += len(list(self._my_inbox.glob("*.json")))

        if self._broadcast_dir.exists():
            for f in self._broadcast_dir.glob("*.json"):
                msg = self._safe_read_json(f)
                if msg and msg.get("from_instance") != self.instance_id:
                    count += 1

        return count

    def cleanup_expired(self) -> int:
        """Raeumt abgelaufene Nachrichten in allen Verzeichnissen auf.

        Returns:
            Anzahl aufgeraeumter Nachrichten
        """
        removed = 0
        now = datetime.now()

        # Alle pending-Unterverzeichnisse durchgehen
        if not self.pending_dir.exists():
            return 0

        for subdir in self.pending_dir.iterdir():
            if not subdir.is_dir():
                continue
            for f in subdir.glob("*.json"):
                msg = self._safe_read_json(f)
                if msg and self._is_expired(msg, now):
                    self._safe_remove(f)
                    removed += 1

        return removed

    def status(self) -> str:
        """Gibt formatierten Messaging-Status zurueck."""
        pending = self.pending_count()
        lines = [
            "INSTANCE MESSAGING STATUS",
            "=" * 50,
            f"Instanz: {self.instance_id}",
            f"Pending Nachrichten: {pending}",
            f"Pending-Dir: {self.pending_dir}",
            f"Archive-Dir: {self.archive_dir}",
        ]

        # Pending-Nachrichten auflisten (ohne zu konsumieren)
        if self._my_inbox.exists():
            inbox_files = list(self._my_inbox.glob("*.json"))
            if inbox_files:
                lines.append(f"\nDirekte Nachrichten ({len(inbox_files)}):")
                for f in inbox_files[:10]:  # Max 10 anzeigen
                    msg = self._safe_read_json(f)
                    if msg:
                        lines.append(
                            f"  [{msg.get('created_at', '?')[:19]}] "
                            f"{msg.get('event', '?')} von {msg.get('from_instance', '?')}"
                        )

        return "\n".join(lines)

    # ─── Private Hilfsmethoden ──────────────────────────────────────

    def _create_message(self, to_instance: str, event: str,
                        context: dict = None, ttl: int = DEFAULT_TTL_SECONDS) -> dict:
        """Erstellt ein Nachrichten-Dict."""
        now = datetime.now()
        msg_id = f"msg-{int(now.timestamp())}-{uuid.uuid4().hex[:8]}"

        return {
            "id": msg_id,
            "from_instance": self.instance_id,
            "to_instance": to_instance,
            "event": event,
            "context": context or {},
            "created_at": now.isoformat(),
            "ttl_seconds": ttl,
        }

    @staticmethod
    def _message_filename(msg: dict) -> str:
        """Erzeugt einen Dateinamen fuer eine Nachricht."""
        ts = msg.get("created_at", "").replace(":", "-").replace(".", "-")
        event = msg.get("event", "unknown")
        msg_id = msg.get("id", "unknown")
        # Kurzformat: Nur die letzten 8 Zeichen der ID
        short_id = msg_id[-8:] if len(msg_id) > 8 else msg_id
        return f"{ts}_{event}_{short_id}.json"

    def _read_from_dir(self, directory: Path, is_broadcast: bool = False) -> list[dict]:
        """Liest Nachrichten aus einem Verzeichnis und archiviert sie.

        Args:
            directory: Verzeichnis zum Lesen
            is_broadcast: True wenn Broadcast-Verzeichnis (eigene Nachrichten skippen)

        Returns:
            Liste von gueltigen Nachrichten
        """
        messages = []
        now = datetime.now()

        if not directory.exists():
            return messages

        for f in directory.glob("*.json"):
            msg = self._safe_read_json(f)
            if msg is None:
                self._safe_remove(f)
                continue

            # Eigene Broadcasts skippen
            if is_broadcast and msg.get("from_instance") == self.instance_id:
                continue

            # Abgelaufene Nachrichten verwerfen
            if self._is_expired(msg, now):
                self._safe_remove(f)
                continue

            # Nachricht archivieren (bei Broadcast: nicht loeschen, andere muessen auch lesen)
            if is_broadcast:
                # Broadcast-Nachrichten markieren wir als gelesen fuer diese Instanz
                # indem wir eine .read-Marker-Datei erstellen
                read_marker = f.with_suffix(f".read-{self.instance_id}")
                if read_marker.exists():
                    # Schon gelesen -- skip
                    continue
                try:
                    read_marker.touch()
                except OSError:
                    pass
            else:
                # Direkte Nachrichten: ins Archiv verschieben
                self._archive_message(f, msg)

            messages.append(msg)

        return messages

    def _archive_message(self, source_file: Path, msg: dict):
        """Verschiebt eine Nachricht ins Archiv.

        Args:
            source_file: Quell-Datei
            msg: Nachricht-Dict
        """
        date_str = datetime.now().strftime("%Y-%m-%d")
        day_archive = self.archive_dir / date_str
        day_archive.mkdir(exist_ok=True)

        # Guard: Nicht zu viele Archiv-Dateien pro Tag
        existing = len(list(day_archive.glob("*.json")))
        if existing >= MAX_ARCHIVE_PER_DAY:
            # Einfach loeschen statt archivieren
            self._safe_remove(source_file)
            return

        target = day_archive / source_file.name
        try:
            # Verschieben (atomic auf gleichem Filesystem)
            os.replace(str(source_file), str(target))
        except OSError:
            # Fallback: Kopieren und loeschen
            self._safe_write_json(target, msg)
            self._safe_remove(source_file)

    @staticmethod
    def _is_expired(msg: dict, now: datetime) -> bool:
        """Prueft ob eine Nachricht abgelaufen ist."""
        ttl = msg.get("ttl_seconds", DEFAULT_TTL_SECONDS)
        created_str = msg.get("created_at", "")

        try:
            created = datetime.fromisoformat(created_str)
            return (now - created) > timedelta(seconds=ttl)
        except (ValueError, TypeError):
            # Kann nicht geparst werden -- als abgelaufen betrachten
            return True

    @staticmethod
    def _safe_write_json(path: Path, data: dict) -> bool:
        """Schreibt JSON-Datei atomar.

        Returns:
            True wenn erfolgreich
        """
        tmp_path = path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(str(tmp_path), str(path))
            return True
        except OSError:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            # Fallback: Direkt schreiben
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                return True
            except OSError:
                return False

    @staticmethod
    def _safe_read_json(path: Path) -> Optional[dict]:
        """Liest JSON-Datei sicher."""
        for attempt in range(3):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                if attempt < 2:
                    time.sleep(0.1)
        return None

    @staticmethod
    def _safe_remove(path: Path):
        """Loescht Datei sicher."""
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
