#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""MediPlanerHandler - Austausch zwischen BACH und MediPlaner."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, List, Tuple

from hub.base import BaseHandler


SCHEMA_VERSION = "mediplaner-export-v1"


def _write_private_text(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)


class MediPlanerHandler(BaseHandler):
    """Importiert und exportiert MediPlaner-v1-JSON aus BACH heraus."""

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.user_db_path = self._canonical_db

    @property
    def profile_name(self) -> str:
        return "mediplaner"

    @property
    def target_file(self) -> Path:
        return self.user_db_path

    def get_operations(self) -> dict:
        return {
            "export": "BACH-Gesundheitsdaten als mediplaner-export-v1.json exportieren",
            "import": "mediplaner-export-v1.json in BACH-Gesundheitstabellen importieren",
            "help": "Hilfe anzeigen",
        }

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        op = operation.lower().replace("_", "-")
        if op == "export":
            return self._export(args)
        if op == "import":
            return self._import(args, dry_run=dry_run)
        if op in ("", "help"):
            return self._help()
        return False, f"Unbekannte Operation: {operation}\nNutze: bach mediplaner help"

    def _get_db(self):
        conn = sqlite3.connect(str(self.user_db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _export(self, args: List[str]) -> Tuple[bool, str]:
        output_file = self._get_arg(args, "--file") or self._get_arg(args, "-o")
        client_first = self._get_arg(args, "--client-first") or "BACH"
        client_last = self._get_arg(args, "--client-last") or "Import"
        birthdate = self._get_arg(args, "--birthdate") or "01.01.1900"

        conn = self._get_db()
        try:
            payload = self._build_payload(conn, client_first, client_last, birthdate)
        finally:
            conn.close()

        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if output_file:
            path = Path(output_file)
            tmp = path.with_suffix(path.suffix + ".tmp")
            _write_private_text(tmp, text)
            tmp.replace(path)
            return True, f"[MEDIPLANER] Export geschrieben: {path}"
        return True, text

    def _build_payload(self, conn: sqlite3.Connection, first: str, last: str, birthdate: str) -> dict[str, Any]:
        doctors = [dict(row) for row in conn.execute(
            """
            SELECT id, name, specialty, institution, phone, email, address, notes,
                   is_active, created_at, updated_at
            FROM health_contacts
            WHERE is_active = 1
            ORDER BY specialty COLLATE NOCASE, name COLLATE NOCASE
            """
        ).fetchall()]

        meds = conn.execute(
            """
            SELECT hm.*, hd.doctor_id
            FROM health_medications hm
            LEFT JOIN health_diagnoses hd ON hm.diagnosis_id = hd.id
            ORDER BY hm.name COLLATE NOCASE, hm.id
            """
        ).fetchall()

        clients = []
        medications = []
        if meds:
            clients.append({"id": 1, "first_name": first, "last_name": last, "birthdate": birthdate})
            for med in meds:
                schedule = (med["schedule"] or "").lower()
                medications.append({
                    "id": med["id"],
                    "client_id": 1,
                    "doctor_id": med["doctor_id"],
                    "name": med["name"],
                    "purpose": None,
                    "effect": med["active_ingredient"],
                    "side_effects": med["side_effects"],
                    "dose_value": med["dosage"],
                    "dose_unit": "",
                    "aktiv": 1 if med["status"] == "aktiv" else 0,
                    "option_flag": 1 if "bedarf" in schedule else 0,
                    "archiv": 1 if med["status"] == "beendet" else 0,
                    "morgens": 1 if "morgen" in schedule else 0,
                    "mittags": 1 if "mittag" in schedule else 0,
                    "nachmittags": 1 if "nachmittag" in schedule else 0,
                    "abends": 1 if "abend" in schedule else 0,
                    "nachts": 1 if "nacht" in schedule else 0,
                    "bedarf": 1 if "bedarf" in schedule else 0,
                    "woechentlich": 1 if "wöchentlich" in schedule or "woechentlich" in schedule else 0,
                    "monatlich": 1 if "monatlich" in schedule else 0,
                    "art_tablette": 0,
                    "art_hilfsmittel": 0,
                    "art_flussigkeit": 0,
                    "art_saft": 0,
                    "enabled": 1,
                })

        return {
            "schema_version": SCHEMA_VERSION,
            "metadata": {
                "app": "BACH",
                "source": "bach-gesundheit",
                "generated_at": datetime.now().isoformat(timespec="seconds"),
            },
            "clients": clients,
            "doctor_contacts": doctors,
            "medications": medications,
            "inventory": [],
            "settings": [],
        }

    def _import(self, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        input_file = self._get_arg(args, "--file") or self._get_arg(args, "-i") or self._first_path_arg(args)
        if not input_file:
            return False, "Usage: bach mediplaner import --file mediplaner-export-v1.json"
        payload = json.loads(Path(input_file).read_text(encoding="utf-8"))
        if payload.get("schema_version") != SCHEMA_VERSION:
            return False, f"Ungültige schema_version: {payload.get('schema_version')!r}"

        conn = self._get_db()
        try:
            stats = self._import_payload(conn, payload, dry_run=dry_run)
        finally:
            conn.close()
        return True, "[MEDIPLANER] Import abgeschlossen: " + ", ".join(f"{k}={v}" for k, v in stats.items())

    def _import_payload(self, conn: sqlite3.Connection, payload: dict[str, Any], dry_run: bool = False) -> dict[str, int]:
        stats = {"contacts_inserted": 0, "contacts_skipped": 0, "meds_inserted": 0, "meds_skipped": 0}
        doctor_map: dict[int, int] = {}
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for item in payload.get("doctor_contacts", []):
            name = (item.get("name") or "").strip()
            if not name:
                stats["contacts_skipped"] += 1
                continue
            row = conn.execute(
                """
                SELECT id FROM health_contacts
                WHERE name=? AND COALESCE(specialty, '')=COALESCE(?, '')
                  AND COALESCE(institution, '')=COALESCE(?, '')
                """,
                (name, item.get("specialty"), item.get("institution")),
            ).fetchone()
            if row:
                new_id = row["id"]
                stats["contacts_skipped"] += 1
            else:
                if dry_run:
                    new_id = int(item.get("id") or 0)
                else:
                    cur = conn.execute(
                        """
                        INSERT INTO health_contacts
                        (name, institution, specialty, phone, email, address, notes, is_active, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            name,
                            item.get("institution"),
                            item.get("specialty"),
                            item.get("phone"),
                            item.get("email"),
                            item.get("address"),
                            item.get("notes"),
                            int(item.get("is_active", 1)),
                            item.get("created_at") or now,
                            item.get("updated_at") or now,
                        ),
                    )
                    new_id = cur.lastrowid
                stats["contacts_inserted"] += 1
            if item.get("id") is not None:
                doctor_map[int(item["id"])] = int(new_id)

        for item in payload.get("medications", []):
            name = (item.get("name") or "").strip()
            if not name:
                stats["meds_skipped"] += 1
                continue
            duplicate = conn.execute(
                """
                SELECT id FROM health_medications
                WHERE name=? AND COALESCE(dosage, '')=COALESCE(?, '')
                """,
                (name, item.get("dose_value")),
            ).fetchone()
            if duplicate:
                stats["meds_skipped"] += 1
                continue
            if not dry_run:
                conn.execute(
                    """
                    INSERT INTO health_medications
                    (name, active_ingredient, dosage, schedule, status, notes, side_effects)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        item.get("effect"),
                        item.get("dose_value"),
                        self._schedule_from_entry(item),
                        "aktiv" if int(item.get("aktiv") or 0) else "pausiert",
                        item.get("purpose"),
                        item.get("side_effects"),
                    ),
                )
            stats["meds_inserted"] += 1

        if not dry_run:
            conn.commit()
        return stats

    def _schedule_from_entry(self, item: dict[str, Any]) -> str:
        labels = [
            ("morgens", "morgens"),
            ("mittags", "mittags"),
            ("nachmittags", "nachmittags"),
            ("abends", "abends"),
            ("nachts", "nachts"),
            ("bedarf", "bei Bedarf"),
            ("woechentlich", "wöchentlich"),
            ("monatlich", "monatlich"),
        ]
        return ", ".join(label for key, label in labels if int(item.get(key) or 0))

    def _help(self) -> Tuple[bool, str]:
        return True, """MEDIPLANER - BACH/MediPlaner Austausch
====================================

BEFEHLE:
  bach mediplaner export --file mediplaner-export-v1.json
  bach mediplaner export --client-first Max --client-last Mustermann --birthdate 01.01.1970
  bach mediplaner import --file mediplaner-export-v1.json

FORMAT:
  mediplaner-export-v1.json mit clients, doctor_contacts, medications,
  inventory und settings."""

    def _get_arg(self, args: List[str], flag: str):
        for i, arg in enumerate(args):
            if arg == flag and i + 1 < len(args):
                return args[i + 1]
            if arg.startswith(flag + "="):
                return arg[len(flag) + 1:]
        return None

    def _first_path_arg(self, args: List[str]):
        for arg in args:
            if not arg.startswith("-"):
                return arg
        return None
