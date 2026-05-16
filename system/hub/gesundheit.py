#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
GesundheitHandler - Gesundheitsassistent CLI

Operationen:
  status            Gesundheits-Dashboard (Zusammenfassung)
  contacts          Arzt-Kontakte anzeigen
  diagnoses         Diagnosen verwalten
  meds              Medikamente anzeigen
  labs              Laborwerte anzeigen
  docs              Gesundheitsdokumente anzeigen
  appointments      Arzttermine anzeigen
  vorsorge          Vorsorgeuntersuchungen anzeigen
  vorsorge-faellig  Faellige Vorsorgeuntersuchungen
  add-diagnosis     Diagnose hinzufuegen
  add-med           Medikament hinzufuegen
  add-lab           Laborwert hinzufuegen
  add-doc           Dokument registrieren
  add-appointment   Arzttermin anlegen
  add-vorsorge      Vorsorgeuntersuchung hinzufuegen
  vorsorge-done     Vorsorgeuntersuchung als erledigt markieren
  show <id>         Detail-Ansicht (Typ wird automatisch erkannt)
  help              Hilfe anzeigen

Nutzt: bach.db / health_* Tabellen (Unified DB seit v1.1.84)
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
from hub.base import BaseHandler
from hub.lang import t


class GesundheitHandler(BaseHandler):

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.user_db_path = self._canonical_db

    @property
    def profile_name(self) -> str:
        return "gesundheit"

    @property
    def target_file(self) -> Path:
        return self.user_db_path

    def get_operations(self) -> dict:
        return {
            "status": "Gesundheits-Dashboard",
            "contacts": "Arzt-Kontakte",
            "diagnoses": "Diagnosen",
            "meds": "Medikamente",
            "labs": "Laborwerte",
            "docs": "Dokumente",
            "appointments": "Arzttermine",
            "vorsorge": "Vorsorgeuntersuchungen",
            "vorsorge-faellig": "Faellige Vorsorgeuntersuchungen",
            "add-diagnosis": "Diagnose hinzufuegen",
            "add-med": "Medikament hinzufuegen",
            "add-lab": "Laborwert hinzufuegen",
            "add-doc": "Dokument registrieren",
            "add-appointment": "Arzttermin anlegen",
            "add-vorsorge": "Vorsorgeuntersuchung hinzufuegen",
            "vorsorge-done": "Vorsorge als erledigt markieren",
            "show": "Detail-Ansicht",
            "reminders": "Proaktive Erinnerungen (Medikamente, Vorsorge, Termine)",
            "interactions": "Wechselwirkungs-Check aktiver Medikamente",
            "export": "Arzt-Kontakte exportieren (CSV/Text/vCard)",
            "help": "Hilfe",
        }

    def _get_db(self):
        conn = sqlite3.connect(str(self.user_db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        op = operation.lower().replace("_", "-")
        if op == "status":
            return self._status(args)
        elif op == "contacts":
            return self._contacts(args)
        elif op == "diagnoses":
            return self._diagnoses(args)
        elif op == "meds":
            return self._meds(args)
        elif op == "labs":
            return self._labs(args)
        elif op == "docs":
            return self._docs(args)
        elif op == "appointments":
            return self._appointments(args)
        elif op == "add-diagnosis":
            return self._add_diagnosis(args)
        elif op == "add-med":
            return self._add_med(args)
        elif op == "add-lab":
            return self._add_lab(args)
        elif op == "add-doc":
            return self._add_doc(args)
        elif op == "add-appointment":
            return self._add_appointment(args)
        elif op == "vorsorge":
            return self._vorsorge(args)
        elif op == "vorsorge-faellig":
            return self._vorsorge_faellig(args)
        elif op == "add-vorsorge":
            return self._add_vorsorge(args)
        elif op == "vorsorge-done":
            return self._vorsorge_done(args)
        elif op == "show":
            return self._show(args)
        elif op == "reminders":
            return self._reminders(args)
        elif op in ("interactions", "wechselwirkungen"):
            return self._interactions(args)
        elif op == "export":
            return self._export(args)
        elif op in ("", "help"):
            return self._help()
        else:
            return False, f"Unbekannte Operation: {operation}\nNutze: bach gesundheit help"

    # ------------------------------------------------------------------
    # STATUS - Dashboard
    # ------------------------------------------------------------------
    def _status(self, args: List[str]) -> Tuple[bool, str]:
        conn = self._get_db()
        try:
            contacts_count = conn.execute("SELECT COUNT(*) FROM health_contacts WHERE is_active = 1").fetchone()[0]
            diag_active = conn.execute("SELECT COUNT(*) FROM health_diagnoses WHERE status = 'aktiv'").fetchone()[0]
            diag_abkl = conn.execute("SELECT COUNT(*) FROM health_diagnoses WHERE status = 'in_abklaerung'").fetchone()[0]
            meds_active = conn.execute("SELECT COUNT(*) FROM health_medications WHERE status = 'aktiv'").fetchone()[0]
            labs_total = conn.execute("SELECT COUNT(*) FROM health_lab_values").fetchone()[0]
            labs_abnormal = conn.execute("SELECT COUNT(*) FROM health_lab_values WHERE is_abnormal = 1").fetchone()[0]
            docs_total = conn.execute("SELECT COUNT(*) FROM health_documents").fetchone()[0]

            # Naechste Termine
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            upcoming = conn.execute("""
                SELECT ha.*, hc.name as doctor_name
                FROM health_appointments ha
                LEFT JOIN health_contacts hc ON ha.doctor_id = hc.id
                WHERE ha.appointment_date >= ? AND ha.status IN ('geplant', 'bestaetigt')
                ORDER BY ha.appointment_date ASC LIMIT 3
            """, (now,)).fetchall()

            # Letzte abnormale Laborwerte
            abnormal_labs = conn.execute("""
                SELECT test_name, value, unit, test_date
                FROM health_lab_values
                WHERE is_abnormal = 1
                ORDER BY test_date DESC LIMIT 5
            """).fetchall()

            lines = [
                "=== GESUNDHEITS-DASHBOARD ===",
                "",
                f"  Arzt-Kontakte:    {contacts_count}",
                f"  Diagnosen aktiv:  {diag_active} ({diag_abkl} in Abklaerung)",
                f"  Medikamente:      {meds_active} aktiv",
                f"  Laborwerte:       {labs_total} gesamt ({labs_abnormal} auffaellig)",
                f"  Dokumente:        {docs_total}",
                "",
            ]

            if upcoming:
                lines.append("  NAECHSTE TERMINE:")
                for a in upcoming:
                    date_str = a["appointment_date"][:16] if a["appointment_date"] else "---"
                    doctor = a["doctor_name"] or "---"
                    lines.append(f"    {date_str}  {a['title']}  ({doctor})")
                lines.append("")

            if abnormal_labs:
                lines.append("  AUFFAELLIGE LABORWERTE (letzte):")
                for l in abnormal_labs:
                    lines.append(f"    {l['test_date']}  {l['test_name']}: {l['value']} {l['unit'] or ''}")
                lines.append("")

            if not upcoming and not abnormal_labs:
                lines.append("  Keine anstehenden Termine oder auffaelligen Werte.")
                lines.append("")

            lines.append("  Befehle: bach gesundheit contacts | diagnoses | meds | labs | docs | appointments")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # CONTACTS - Arzt-Kontakte
    # ------------------------------------------------------------------
    def _contacts(self, args: List[str]) -> Tuple[bool, str]:
        specialty_filter = self._get_arg(args, "--specialty") or self._get_arg(args, "-s")
        search_term = self._get_arg(args, "--search") or self._get_arg(args, "-q")

        conn = self._get_db()
        try:
            query = "SELECT * FROM health_contacts WHERE is_active = 1"
            params = []

            if specialty_filter:
                query += " AND specialty LIKE ?"
                params.append(f"%{specialty_filter}%")

            if search_term:
                query += " AND (name LIKE ? OR institution LIKE ? OR specialty LIKE ?)"
                like = f"%{search_term}%"
                params.extend([like, like, like])

            query += " ORDER BY specialty ASC, name ASC"
            rows = conn.execute(query, params).fetchall()

            if not rows:
                return True, "[GESUNDHEIT] Keine Arzt-Kontakte gefunden."

            lines = [f"[GESUNDHEIT] {len(rows)} Arzt-Kontakt(e):\n"]
            current_spec = None

            for r in rows:
                spec = r["specialty"] or "Sonstige"
                if spec != current_spec:
                    current_spec = spec
                    lines.append(f"  [{spec.upper()}]")

                institution = f" ({r['institution']})" if r["institution"] else ""
                phone = r["phone"] or ""
                lines.append(f"    [{r['id']:>3}] {r['name']:<35}{institution}  {phone}")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # DIAGNOSES
    # ------------------------------------------------------------------
    def _diagnoses(self, args: List[str]) -> Tuple[bool, str]:
        show_all = "--all" in args
        status_filter = self._get_arg(args, "--status")

        conn = self._get_db()
        try:
            query = """
                SELECT hd.*, hc.name as doctor_name
                FROM health_diagnoses hd
                LEFT JOIN health_contacts hc ON hd.doctor_id = hc.id
            """
            params = []
            conditions = []

            if not show_all and not status_filter:
                conditions.append("hd.status IN ('aktiv', 'in_abklaerung', 'hypothese')")
            elif status_filter:
                conditions.append("hd.status = ?")
                params.append(status_filter)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY hd.diagnosis_date DESC"
            rows = conn.execute(query, params).fetchall()

            if not rows:
                return True, "[GESUNDHEIT] Keine Diagnosen gefunden.\nNutze: bach gesundheit add-diagnosis \"Name\" --icd F32.1"

            lines = [f"[GESUNDHEIT] {len(rows)} Diagnose(n):\n"]
            for r in rows:
                status_map = {"aktiv": "AKT", "in_abklaerung": "ABK", "hypothese": "HYP", "widerlegt": "WID", "geheilt": "GEH"}
                status = status_map.get(r["status"], r["status"] or "?")
                icd = f" [{r['icd_code']}]" if r["icd_code"] else ""
                date = (r["diagnosis_date"] or "---")[:10]
                doctor = f" ({r['doctor_name']})" if r["doctor_name"] else ""
                severity = f" [{r['severity']}]" if r["severity"] else ""

                lines.append(f"  [{r['id']:>3}] {status} {r['diagnosis_name']}{icd}{severity}  {date}{doctor}")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # MEDS - Medikamente
    # ------------------------------------------------------------------
    def _meds(self, args: List[str]) -> Tuple[bool, str]:
        show_all = "--all" in args

        conn = self._get_db()
        try:
            query = """
                SELECT hm.*, hd.diagnosis_name
                FROM health_medications hm
                LEFT JOIN health_diagnoses hd ON hm.diagnosis_id = hd.id
            """
            if not show_all:
                query += " WHERE hm.status = 'aktiv'"
            query += " ORDER BY hm.name ASC"
            rows = conn.execute(query).fetchall()

            if not rows:
                return True, "[GESUNDHEIT] Keine Medikamente gefunden.\nNutze: bach gesundheit add-med \"Name\" --dosage 100mg --schedule morgens"

            lines = [f"[GESUNDHEIT] {len(rows)} Medikament(e):\n"]
            for r in rows:
                status_mark = "+" if r["status"] == "aktiv" else "-"
                dosage = r["dosage"] or ""
                schedule = r["schedule"] or ""
                diag = f" (fuer: {r['diagnosis_name']})" if r["diagnosis_name"] else ""
                lines.append(f"  {status_mark} [{r['id']:>3}] {r['name']:<25} {dosage:<10} {schedule}{diag}")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # LABS - Laborwerte
    # ------------------------------------------------------------------
    def _labs(self, args: List[str]) -> Tuple[bool, str]:
        test_filter = self._get_arg(args, "--test") or self._get_arg(args, "-t")
        only_abnormal = "--abnormal" in args
        limit = 50

        for a in args:
            try:
                limit = int(a)
                break
            except ValueError:
                pass

        conn = self._get_db()
        try:
            query = "SELECT * FROM health_lab_values"
            params = []
            conditions = []

            if test_filter:
                conditions.append("test_name LIKE ?")
                params.append(f"%{test_filter}%")

            if only_abnormal:
                conditions.append("is_abnormal = 1")

            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += f" ORDER BY test_date DESC, test_name ASC LIMIT {limit}"
            rows = conn.execute(query, params).fetchall()

            if not rows:
                return True, "[GESUNDHEIT] Keine Laborwerte gefunden.\nNutze: bach gesundheit add-lab \"TSH\" --value 2.5 --unit mU/L --date 28.01.2026"

            lines = [f"[GESUNDHEIT] {len(rows)} Laborwert(e):\n"]
            lines.append(f"  {'Datum':<12} {'Test':<25} {'Wert':>8} {'Einheit':<10} {'Ref.':>8}-{'':<8} {'Status'}")
            lines.append("  " + "-" * 85)

            for r in rows:
                date = (r["test_date"] or "---")[:10]
                ref_min = f"{r['reference_min']}" if r["reference_min"] is not None else ""
                ref_max = f"{r['reference_max']}" if r["reference_max"] is not None else ""
                ref_range = f"{ref_min}-{ref_max}" if ref_min or ref_max else "---"
                abnormal = "!!!" if r["is_abnormal"] else "ok"
                lines.append(
                    f"  {date:<12} {r['test_name']:<25} {r['value'] or '':>8} {(r['unit'] or ''):<10} {ref_range:<17} {abnormal}"
                )

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # DOCS - Gesundheitsdokumente
    # ------------------------------------------------------------------
    def _docs(self, args: List[str]) -> Tuple[bool, str]:
        type_filter = self._get_arg(args, "--type")
        search_term = self._get_arg(args, "--search") or self._get_arg(args, "-q")

        conn = self._get_db()
        try:
            query = """
                SELECT hd.*, hc.name as doctor_name
                FROM health_documents hd
                LEFT JOIN health_contacts hc ON hd.doctor_id = hc.id
            """
            params = []
            conditions = []

            if type_filter:
                conditions.append("hd.doc_type = ?")
                params.append(type_filter)

            if search_term:
                conditions.append("(hd.title LIKE ? OR hd.content_summary LIKE ?)")
                like = f"%{search_term}%"
                params.extend([like, like])

            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY hd.document_date DESC"
            rows = conn.execute(query, params).fetchall()

            if not rows:
                return True, "[GESUNDHEIT] Keine Dokumente gefunden.\nNutze: bach gesundheit add-doc \"Titel\" --type befund --date 28.01.2026"

            lines = [f"[GESUNDHEIT] {len(rows)} Dokument(e):\n"]
            for r in rows:
                date = (r["document_date"] or "---")[:10]
                doc_type = (r["doc_type"] or "---")[:10]
                doctor = f" ({r['doctor_name']})" if r["doctor_name"] else ""
                has_file = " [F]" if r["file_path"] else ""
                lines.append(f"  [{r['id']:>3}] {date} [{doc_type:<10}] {r['title']}{doctor}{has_file}")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # APPOINTMENTS - Arzttermine
    # ------------------------------------------------------------------
    def _appointments(self, args: List[str]) -> Tuple[bool, str]:
        show_all = "--all" in args
        show_past = "--past" in args

        conn = self._get_db()
        try:
            query = """
                SELECT ha.*, hc.name as doctor_name
                FROM health_appointments ha
                LEFT JOIN health_contacts hc ON ha.doctor_id = hc.id
            """
            params = []
            conditions = []

            if not show_all and not show_past:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                conditions.append("ha.appointment_date >= ?")
                params.append(now)

            if show_past:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                conditions.append("ha.appointment_date < ?")
                params.append(now)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            if show_past:
                query += " ORDER BY ha.appointment_date DESC LIMIT 20"
            else:
                query += " ORDER BY ha.appointment_date ASC"
            rows = conn.execute(query, params).fetchall()

            if not rows:
                label = "vergangene" if show_past else "kommende"
                return True, f"[GESUNDHEIT] Keine {label} Arzttermine.\nNutze: bach gesundheit add-appointment \"Kontrolle\" --doctor 1 --date 15.02.2026 --time 09:00"

            label = "vergangene" if show_past else "kommende"
            lines = [f"[GESUNDHEIT] {len(rows)} {label} Arzttermin(e):\n"]
            for r in rows:
                date = r["appointment_date"][:16] if r["appointment_date"] else "---"
                doctor = r["doctor_name"] or "---"
                status = r["status"] or "?"
                apt_type = f" [{r['appointment_type']}]" if r["appointment_type"] else ""
                lines.append(f"  [{r['id']:>3}] {date}  {r['title']}{apt_type}  ({doctor})  [{status}]")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # VORSORGE - Vorsorgeuntersuchungen
    # ------------------------------------------------------------------
    def _vorsorge(self, args: List[str]) -> Tuple[bool, str]:
        show_all = "--all" in args
        kategorie = self._get_arg(args, "--kategorie") or self._get_arg(args, "-k")

        conn = self._get_db()
        try:
            query = """
                SELECT vc.*, hc.name as doctor_name
                FROM vorsorge_checks vc
                LEFT JOIN health_contacts hc ON vc.doctor_id = hc.id
            """
            params = []
            conditions = []

            if not show_all:
                conditions.append("vc.is_active = 1")

            if kategorie:
                conditions.append("vc.kategorie LIKE ?")
                params.append(f"%{kategorie}%")

            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY vc.naechster_termin ASC NULLS LAST, vc.untersuchung ASC"
            rows = conn.execute(query, params).fetchall()

            if not rows:
                return True, "[VORSORGE] Keine Vorsorgeuntersuchungen gefunden.\nNutze: bach gesundheit add-vorsorge \"Darmspiegelung\" --turnus 120 --kategorie Krebs"

            lines = [f"[VORSORGE] {len(rows)} Vorsorgeuntersuchung(en):\n"]
            lines.append(f"  {'ID':>4} {'Untersuchung':<30} {'Turnus':<10} {'Zuletzt':<12} {'Naechster':<12} {'Arzt'}")
            lines.append("  " + "-" * 90)

            today = datetime.now().date()
            for r in rows:
                turnus = f"{r['turnus_monate']}M" if r['turnus_monate'] else "---"
                zuletzt = (r["zuletzt"] or "---")[:10]
                naechster = (r["naechster_termin"] or "---")[:10]
                doctor = (r["doctor_name"] or "---")[:20]

                # Markiere faellige
                faellig_marker = ""
                if r["naechster_termin"]:
                    try:
                        naechster_date = datetime.strptime(r["naechster_termin"][:10], "%Y-%m-%d").date()
                        if naechster_date <= today:
                            faellig_marker = " !!!"
                    except ValueError:
                        pass

                lines.append(f"  {r['id']:>4} {r['untersuchung']:<30} {turnus:<10} {zuletzt:<12} {naechster:<12} {doctor}{faellig_marker}")

            return True, "\n".join(lines)
        finally:
            conn.close()

    def _vorsorge_faellig(self, args: List[str]) -> Tuple[bool, str]:
        """Zeigt alle faelligen Vorsorgeuntersuchungen."""
        conn = self._get_db()
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            rows = conn.execute("""
                SELECT vc.*, hc.name as doctor_name
                FROM vorsorge_checks vc
                LEFT JOIN health_contacts hc ON vc.doctor_id = hc.id
                WHERE vc.is_active = 1
                  AND (vc.naechster_termin IS NULL OR vc.naechster_termin <= ?)
                ORDER BY vc.naechster_termin ASC NULLS FIRST
            """, (today,)).fetchall()

            if not rows:
                return True, "[VORSORGE] Keine faelligen Vorsorgeuntersuchungen. Gut so!"

            lines = [f"[VORSORGE] {len(rows)} FAELLIGE Untersuchung(en):\n"]
            for r in rows:
                naechster = (r["naechster_termin"] or "noch nie")[:10]
                doctor = f" ({r['doctor_name']})" if r["doctor_name"] else ""
                kat = f" [{r['kategorie']}]" if r["kategorie"] else ""
                lines.append(f"  [{r['id']:>3}] {r['untersuchung']}{kat} - faellig: {naechster}{doctor}")

            lines.append("\n  --> bach gesundheit vorsorge-done <id> zum Markieren als erledigt")
            return True, "\n".join(lines)
        finally:
            conn.close()

    def _add_vorsorge(self, args: List[str]) -> Tuple[bool, str]:
        if not args:
            return False, (
                "Usage: bach gesundheit add-vorsorge \"Name\" [Optionen]\n\n"
                "Optionen:\n"
                "  --turnus, -t    Turnus in Monaten (z.B. 12=jaehrlich, 24=alle 2 Jahre)\n"
                "  --kategorie,-k  Kategorie (Krebs, Herz, Zahn, Impfung, Allgemein)\n"
                "  --doctor        Arzt-ID\n"
                "  --zuletzt       Letzter Termin (DD.MM.YYYY)\n"
                "  --ab-alter      Ab welchem Alter relevant\n"
                "  --bis-alter     Bis zu welchem Alter relevant\n"
                "  --geschlecht    m|w|alle (Default: alle)\n"
                "  --note          Notiz"
            )

        name = self._get_first_arg(args)
        if not name:
            return False, "Kein Name angegeben."

        turnus_str = self._get_arg(args, "--turnus") or self._get_arg(args, "-t") or "12"
        kategorie = self._get_arg(args, "--kategorie") or self._get_arg(args, "-k")
        doctor_id = self._get_arg(args, "--doctor")
        zuletzt_str = self._get_arg(args, "--zuletzt")
        ab_alter = self._get_arg(args, "--ab-alter")
        bis_alter = self._get_arg(args, "--bis-alter")
        geschlecht = self._get_arg(args, "--geschlecht") or "alle"
        note = self._get_arg(args, "--note")

        try:
            turnus = int(turnus_str)
        except ValueError:
            return False, f"Ungueltiger Turnus: {turnus_str} (Zahl in Monaten erwartet)"

        zuletzt = self._parse_date(zuletzt_str) if zuletzt_str else None

        # Berechne naechsten Termin
        naechster = None
        if zuletzt and turnus:
            try:
                zuletzt_date = datetime.strptime(zuletzt, "%Y-%m-%d")
                naechster_date = zuletzt_date + timedelta(days=turnus * 30)
                naechster = naechster_date.strftime("%Y-%m-%d")
            except ValueError:
                pass

        conn = self._get_db()
        try:
            cursor = conn.execute("""
                INSERT INTO vorsorge_checks
                (untersuchung, turnus_monate, zuletzt, naechster_termin, doctor_id,
                 ab_alter, bis_alter, geschlecht, kategorie, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, turnus, zuletzt, naechster,
                  int(doctor_id) if doctor_id else None,
                  int(ab_alter) if ab_alter else None,
                  int(bis_alter) if bis_alter else None,
                  geschlecht, kategorie, note))
            conn.commit()
            naechster_info = f", naechster Termin: {naechster}" if naechster else ""
            return True, f"[OK] Vorsorge #{cursor.lastrowid}: {name} (alle {turnus} Monate){naechster_info}"
        finally:
            conn.close()

    def _vorsorge_done(self, args: List[str]) -> Tuple[bool, str]:
        """Markiert eine Vorsorgeuntersuchung als erledigt und berechnet naechsten Termin."""
        if not args:
            return False, (
                "Usage: bach gesundheit vorsorge-done <id> [--date DD.MM.YYYY]\n\n"
                "Markiert Vorsorge als erledigt und berechnet naechsten Termin.\n"
                "Ohne --date wird das heutige Datum verwendet."
            )

        try:
            vorsorge_id = int(args[0])
        except (IndexError, ValueError):
            return False, "Ungueltige Vorsorge-ID."

        date_str = self._get_arg(args, "--date") or self._get_arg(args, "-d")
        done_date = self._parse_date(date_str) if date_str else datetime.now().strftime("%Y-%m-%d")

        if date_str and not done_date:
            return False, f"Ungueltiges Datum: {date_str}"

        conn = self._get_db()
        try:
            row = conn.execute("SELECT * FROM vorsorge_checks WHERE id = ?", (vorsorge_id,)).fetchone()
            if not row:
                return False, f"Vorsorge {vorsorge_id} nicht gefunden."

            turnus = row["turnus_monate"] or 12
            done_dt = datetime.strptime(done_date, "%Y-%m-%d")
            naechster_date = done_dt + timedelta(days=turnus * 30)
            naechster = naechster_date.strftime("%Y-%m-%d")

            conn.execute("""
                UPDATE vorsorge_checks
                SET zuletzt = ?, naechster_termin = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (done_date, naechster, vorsorge_id))
            conn.commit()

            return True, f"[OK] Vorsorge '{row['untersuchung']}' erledigt am {done_date}. Naechster Termin: {naechster}"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # ADD - Diagnose
    # ------------------------------------------------------------------
    def _add_diagnosis(self, args: List[str]) -> Tuple[bool, str]:
        if not args:
            return False, (
                "Usage: bach gesundheit add-diagnosis \"Name\" [Optionen]\n\n"
                "Optionen:\n"
                "  --icd           ICD-10 Code (z.B. F32.1)\n"
                "  --date, -d      Diagnosedatum (DD.MM.YYYY)\n"
                "  --status        aktiv|in_abklaerung|hypothese|widerlegt|geheilt\n"
                "  --severity      leicht|mittel|schwer\n"
                "  --doctor        Arzt-ID (aus health_contacts)\n"
                "  --note          Notiz"
            )

        name = self._get_first_arg(args)
        if not name:
            return False, "Kein Diagnosename angegeben."

        icd = self._get_arg(args, "--icd")
        date_str = self._get_arg(args, "--date") or self._get_arg(args, "-d")
        status = self._get_arg(args, "--status") or "aktiv"
        severity = self._get_arg(args, "--severity")
        doctor_id = self._get_arg(args, "--doctor")
        note = self._get_arg(args, "--note")

        diagnosis_date = self._parse_date(date_str) if date_str else datetime.now().strftime("%Y-%m-%d")

        if date_str and not diagnosis_date:
            return False, f"Ungueltiges Datum: {date_str}"

        conn = self._get_db()
        try:
            cursor = conn.execute("""
                INSERT INTO health_diagnoses
                (diagnosis_name, icd_code, diagnosis_date, status, severity, doctor_id, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, icd, diagnosis_date, status, severity,
                  int(doctor_id) if doctor_id else None, note))
            conn.commit()
            return True, f"[OK] Diagnose #{cursor.lastrowid} erstellt: {name} ({status})"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # ADD - Medikament
    # ------------------------------------------------------------------
    def _add_med(self, args: List[str]) -> Tuple[bool, str]:
        if not args:
            return False, (
                "Usage: bach gesundheit add-med \"Name\" [Optionen]\n\n"
                "Optionen:\n"
                "  --ingredient    Wirkstoff\n"
                "  --dosage        Dosierung (z.B. 100mg)\n"
                "  --schedule      Einnahmeplan (z.B. morgens,abends)\n"
                "  --diagnosis     Diagnose-ID\n"
                "  --start         Startdatum (DD.MM.YYYY)\n"
                "  --note          Notiz\n"
                "  --side-effects  Nebenwirkungen"
            )

        name = self._get_first_arg(args)
        if not name:
            return False, "Kein Medikamentenname angegeben."

        ingredient = self._get_arg(args, "--ingredient")
        dosage = self._get_arg(args, "--dosage")
        schedule = self._get_arg(args, "--schedule")
        diagnosis_id = self._get_arg(args, "--diagnosis")
        start_str = self._get_arg(args, "--start")
        note = self._get_arg(args, "--note")
        side_effects = self._get_arg(args, "--side-effects")

        start_date = self._parse_date(start_str) if start_str else datetime.now().strftime("%Y-%m-%d")

        conn = self._get_db()
        try:
            cursor = conn.execute("""
                INSERT INTO health_medications
                (name, active_ingredient, dosage, schedule, diagnosis_id, start_date, status, notes, side_effects)
                VALUES (?, ?, ?, ?, ?, ?, 'aktiv', ?, ?)
            """, (name, ingredient, dosage, schedule,
                  int(diagnosis_id) if diagnosis_id else None,
                  start_date, note, side_effects))
            conn.commit()
            return True, f"[OK] Medikament #{cursor.lastrowid} erstellt: {name} ({dosage or '---'})"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # ADD - Laborwert
    # ------------------------------------------------------------------
    def _add_lab(self, args: List[str]) -> Tuple[bool, str]:
        if not args:
            return False, (
                "Usage: bach gesundheit add-lab \"Testname\" [Optionen]\n\n"
                "Optionen:\n"
                "  --value, -v     Messwert\n"
                "  --unit, -u      Einheit (z.B. mU/L, mg/dL)\n"
                "  --ref-min       Referenz Minimum\n"
                "  --ref-max       Referenz Maximum\n"
                "  --date, -d      Datum (DD.MM.YYYY)\n"
                "  --abnormal      Als auffaellig markieren\n"
                "  --doctor        Arzt-ID\n"
                "  --note          Notiz"
            )

        name = self._get_first_arg(args)
        if not name:
            return False, "Kein Testname angegeben."

        value_str = self._get_arg(args, "--value") or self._get_arg(args, "-v")
        unit = self._get_arg(args, "--unit") or self._get_arg(args, "-u")
        ref_min_str = self._get_arg(args, "--ref-min")
        ref_max_str = self._get_arg(args, "--ref-max")
        date_str = self._get_arg(args, "--date") or self._get_arg(args, "-d")
        is_abnormal = "--abnormal" in args
        doctor_id = self._get_arg(args, "--doctor")
        note = self._get_arg(args, "--note")

        value = float(value_str) if value_str else None
        ref_min = float(ref_min_str) if ref_min_str else None
        ref_max = float(ref_max_str) if ref_max_str else None
        test_date = self._parse_date(date_str) if date_str else datetime.now().strftime("%Y-%m-%d")

        # Auto-detect abnormal if reference range given
        if value is not None and not is_abnormal:
            if ref_min is not None and value < ref_min:
                is_abnormal = True
            if ref_max is not None and value > ref_max:
                is_abnormal = True

        conn = self._get_db()
        try:
            cursor = conn.execute("""
                INSERT INTO health_lab_values
                (test_name, value, unit, reference_min, reference_max, test_date, is_abnormal, doctor_id, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, value, unit, ref_min, ref_max, test_date,
                  1 if is_abnormal else 0,
                  int(doctor_id) if doctor_id else None, note))
            conn.commit()
            abnormal_text = " [AUFFAELLIG]" if is_abnormal else ""
            return True, f"[OK] Laborwert #{cursor.lastrowid}: {name} = {value} {unit or ''}{abnormal_text}"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # ADD - Dokument
    # ------------------------------------------------------------------
    def _add_doc(self, args: List[str]) -> Tuple[bool, str]:
        if not args:
            return False, (
                "Usage: bach gesundheit add-doc \"Titel\" [Optionen]\n\n"
                "Optionen:\n"
                "  --type          befund|arztbrief|labor|rezept|studie|sonstiges\n"
                "  --file          Dateipfad\n"
                "  --summary       Zusammenfassung\n"
                "  --date, -d      Dokumentdatum (DD.MM.YYYY)\n"
                "  --doctor        Arzt-ID\n"
                "  --diagnosis     Diagnose-ID"
            )

        title = self._get_first_arg(args)
        if not title:
            return False, "Kein Titel angegeben."

        doc_type = self._get_arg(args, "--type") or "sonstiges"
        file_path = self._get_arg(args, "--file")
        summary = self._get_arg(args, "--summary")
        date_str = self._get_arg(args, "--date") or self._get_arg(args, "-d")
        doctor_id = self._get_arg(args, "--doctor")
        diagnosis_id = self._get_arg(args, "--diagnosis")

        doc_date = self._parse_date(date_str) if date_str else datetime.now().strftime("%Y-%m-%d")

        conn = self._get_db()
        try:
            cursor = conn.execute("""
                INSERT INTO health_documents
                (title, doc_type, file_path, content_summary, document_date, doctor_id, diagnosis_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (title, doc_type, file_path, summary, doc_date,
                  int(doctor_id) if doctor_id else None,
                  int(diagnosis_id) if diagnosis_id else None))
            conn.commit()
            return True, f"[OK] Dokument #{cursor.lastrowid}: {title} ({doc_type})"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # ADD - Arzttermin
    # ------------------------------------------------------------------
    def _add_appointment(self, args: List[str]) -> Tuple[bool, str]:
        if not args:
            return False, (
                "Usage: bach gesundheit add-appointment \"Titel\" [Optionen]\n\n"
                "Optionen:\n"
                "  --doctor        Arzt-ID (aus health_contacts)\n"
                "  --date, -d      Datum (DD.MM.YYYY)\n"
                "  --time, -t      Uhrzeit (HH:MM)\n"
                "  --duration      Dauer in Minuten (Default: 30)\n"
                "  --type          Vorsorge|Kontrolle|Akut\n"
                "  --note          Notiz"
            )

        title = self._get_first_arg(args)
        if not title:
            return False, "Kein Titel angegeben."

        doctor_id = self._get_arg(args, "--doctor")
        date_str = self._get_arg(args, "--date") or self._get_arg(args, "-d")
        time_str = self._get_arg(args, "--time") or self._get_arg(args, "-t") or "09:00"
        duration = self._get_arg(args, "--duration") or "30"
        apt_type = self._get_arg(args, "--type")
        note = self._get_arg(args, "--note")

        if not date_str:
            return False, "Datum ist erforderlich. --date DD.MM.YYYY"

        apt_date = self._parse_date(date_str)
        if not apt_date:
            return False, f"Ungueltiges Datum: {date_str}"

        apt_datetime = f"{apt_date} {time_str}:00"

        conn = self._get_db()
        try:
            cursor = conn.execute("""
                INSERT INTO health_appointments
                (title, doctor_id, appointment_date, duration_minutes, appointment_type, notes)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (title, int(doctor_id) if doctor_id else None,
                  apt_datetime, int(duration), apt_type, note))
            conn.commit()
            return True, f"[OK] Termin #{cursor.lastrowid}: {title} am {apt_date} um {time_str}"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # SHOW - Detail
    # ------------------------------------------------------------------
    def _show(self, args: List[str]) -> Tuple[bool, str]:
        if not args:
            return False, (
                "Usage: bach gesundheit show <typ> <id>\n\n"
                "Typen: contact, diagnosis, med, lab, doc, appointment\n"
                "Beispiel: bach gesundheit show contact 1"
            )

        # Parse type and ID
        show_type = args[0] if args else None
        show_id = None
        if len(args) >= 2:
            try:
                show_id = int(args[1])
            except ValueError:
                return False, f"Ungueltige ID: {args[1]}"

        if not show_type or show_id is None:
            return False, "Typ und ID angeben. Beispiel: bach gesundheit show contact 1"

        conn = self._get_db()
        try:
            if show_type in ("contact", "contacts", "arzt"):
                row = conn.execute("SELECT * FROM health_contacts WHERE id = ?", (show_id,)).fetchone()
                if not row:
                    return False, f"Arzt-Kontakt {show_id} nicht gefunden."
                lines = [
                    f"=== ARZT-KONTAKT {row['id']} ===",
                    f"Name:         {row['name']}",
                    f"Institution:  {row['institution'] or '---'}",
                    f"Fachgebiet:   {row['specialty'] or '---'}",
                    f"Telefon:      {row['phone'] or '---'}",
                    f"E-Mail:       {row['email'] or '---'}",
                    f"Adresse:      {row['address'] or '---'}",
                    f"Aktiv:        {'Ja' if row['is_active'] else 'Nein'}",
                ]
                if row["notes"]:
                    lines.append(f"\nNotizen:\n{row['notes']}")
                return True, "\n".join(lines)

            elif show_type in ("diagnosis", "diagnose"):
                row = conn.execute("""
                    SELECT hd.*, hc.name as doctor_name
                    FROM health_diagnoses hd
                    LEFT JOIN health_contacts hc ON hd.doctor_id = hc.id
                    WHERE hd.id = ?
                """, (show_id,)).fetchone()
                if not row:
                    return False, f"Diagnose {show_id} nicht gefunden."
                lines = [
                    f"=== DIAGNOSE {row['id']} ===",
                    f"Name:         {row['diagnosis_name']}",
                    f"ICD-Code:     {row['icd_code'] or '---'}",
                    f"Datum:        {(row['diagnosis_date'] or '---')[:10]}",
                    f"Status:       {row['status']}",
                    f"Schweregrad:  {row['severity'] or '---'}",
                    f"Arzt:         {row.get('doctor_name') or '---'}",
                ]
                if row["notes"]:
                    lines.append(f"\nNotizen:\n{row['notes']}")

                # Zugehoerige Medikamente
                meds = conn.execute("SELECT name, dosage, status FROM health_medications WHERE diagnosis_id = ?", (show_id,)).fetchall()
                if meds:
                    lines.append(f"\nMedikamente ({len(meds)}):")
                    for m in meds:
                        lines.append(f"  - {m['name']} ({m['dosage'] or '---'}) [{m['status']}]")
                return True, "\n".join(lines)

            elif show_type in ("med", "medication", "medikament"):
                row = conn.execute("""
                    SELECT hm.*, hd.diagnosis_name
                    FROM health_medications hm
                    LEFT JOIN health_diagnoses hd ON hm.diagnosis_id = hd.id
                    WHERE hm.id = ?
                """, (show_id,)).fetchone()
                if not row:
                    return False, f"Medikament {show_id} nicht gefunden."
                lines = [
                    f"=== MEDIKAMENT {row['id']} ===",
                    f"Name:          {row['name']}",
                    f"Wirkstoff:     {row['active_ingredient'] or '---'}",
                    f"Dosierung:     {row['dosage'] or '---'}",
                    f"Einnahmeplan:  {row['schedule'] or '---'}",
                    f"Status:        {row['status']}",
                    f"Start:         {(row['start_date'] or '---')[:10]}",
                    f"Ende:          {(row['end_date'] or '---')[:10] if row['end_date'] else '---'}",
                    f"Diagnose:      {row.get('diagnosis_name') or '---'}",
                ]
                if row["notes"]:
                    lines.append(f"\nNotizen:\n{row['notes']}")
                if row["side_effects"]:
                    lines.append(f"\nNebenwirkungen:\n{row['side_effects']}")
                return True, "\n".join(lines)

            elif show_type in ("lab", "laborwert"):
                row = conn.execute("SELECT * FROM health_lab_values WHERE id = ?", (show_id,)).fetchone()
                if not row:
                    return False, f"Laborwert {show_id} nicht gefunden."
                abnormal = "JA" if row["is_abnormal"] else "Nein"
                lines = [
                    f"=== LABORWERT {row['id']} ===",
                    f"Test:      {row['test_name']}",
                    f"Wert:      {row['value']} {row['unit'] or ''}",
                    f"Referenz:  {row['reference_min'] or '?'} - {row['reference_max'] or '?'}",
                    f"Datum:     {(row['test_date'] or '---')[:10]}",
                    f"Auffaellig: {abnormal}",
                ]
                if row["notes"]:
                    lines.append(f"\nNotizen:\n{row['notes']}")
                return True, "\n".join(lines)

            elif show_type in ("doc", "dokument"):
                row = conn.execute("""
                    SELECT hd.*, hc.name as doctor_name
                    FROM health_documents hd
                    LEFT JOIN health_contacts hc ON hd.doctor_id = hc.id
                    WHERE hd.id = ?
                """, (show_id,)).fetchone()
                if not row:
                    return False, f"Dokument {show_id} nicht gefunden."
                lines = [
                    f"=== GESUNDHEITSDOKUMENT {row['id']} ===",
                    f"Titel:    {row['title']}",
                    f"Typ:      {row['doc_type'] or '---'}",
                    f"Datum:    {(row['document_date'] or '---')[:10]}",
                    f"Arzt:     {row.get('doctor_name') or '---'}",
                    f"Datei:    {row['file_path'] or '---'}",
                ]
                if row["content_summary"]:
                    lines.append(f"\nZusammenfassung:\n{row['content_summary']}")
                return True, "\n".join(lines)

            elif show_type in ("appointment", "termin"):
                row = conn.execute("""
                    SELECT ha.*, hc.name as doctor_name
                    FROM health_appointments ha
                    LEFT JOIN health_contacts hc ON ha.doctor_id = hc.id
                    WHERE ha.id = ?
                """, (show_id,)).fetchone()
                if not row:
                    return False, f"Termin {show_id} nicht gefunden."
                lines = [
                    f"=== ARZTTERMIN {row['id']} ===",
                    f"Titel:    {row['title']}",
                    f"Arzt:     {row.get('doctor_name') or '---'}",
                    f"Datum:    {row['appointment_date'][:16] if row['appointment_date'] else '---'}",
                    f"Dauer:    {row['duration_minutes']} Min.",
                    f"Typ:      {row['appointment_type'] or '---'}",
                    f"Status:   {row['status']}",
                ]
                if row["notes"]:
                    lines.append(f"\nNotizen:\n{row['notes']}")
                return True, "\n".join(lines)

            elif show_type in ("vorsorge", "checkup"):
                row = conn.execute("""
                    SELECT vc.*, hc.name as doctor_name
                    FROM vorsorge_checks vc
                    LEFT JOIN health_contacts hc ON vc.doctor_id = hc.id
                    WHERE vc.id = ?
                """, (show_id,)).fetchone()
                if not row:
                    return False, f"Vorsorge {show_id} nicht gefunden."
                lines = [
                    f"=== VORSORGEUNTERSUCHUNG {row['id']} ===",
                    f"Untersuchung:   {row['untersuchung']}",
                    f"Turnus:         {row['turnus_monate']} Monate",
                    f"Kategorie:      {row['kategorie'] or '---'}",
                    f"Zuletzt:        {(row['zuletzt'] or '---')[:10]}",
                    f"Naechster:      {(row['naechster_termin'] or '---')[:10]}",
                    f"Arzt:           {row.get('doctor_name') or '---'}",
                    f"Ab Alter:       {row['ab_alter'] or '---'}",
                    f"Bis Alter:      {row['bis_alter'] or '---'}",
                    f"Geschlecht:     {row['geschlecht'] or 'alle'}",
                    f"Aktiv:          {'Ja' if row['is_active'] else 'Nein'}",
                ]
                if row["notes"]:
                    lines.append(f"\nNotizen:\n{row['notes']}")
                return True, "\n".join(lines)

            else:
                return False, f"Unbekannter Typ: {show_type}\nVerfuegbar: contact, diagnosis, med, lab, doc, appointment, vorsorge"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # EXPORT - Arzt-Kontakte exportieren
    # ------------------------------------------------------------------
    def _export(self, args: List[str]) -> Tuple[bool, str]:
        """
        Exportiert Gesundheitsdaten als CSV, Text oder vCard 3.0.

        Optionen:
            --entity <typ>          contacts|diagnoses|meds|labs|all (default: contacts)
            --specialty <fach>      Nur bestimmtes Fachgebiet (fuer contacts)
            --format csv|txt|vcard  Exportformat (default: txt)
            --file <pfad>           Speichern in Datei
        """
        entity = self._get_arg(args, "--entity") or self._get_arg(args, "-e") or "contacts"
        specialty_filter = self._get_arg(args, "--specialty") or self._get_arg(args, "-s")
        export_format = self._get_arg(args, "--format") or self._get_arg(args, "-f") or "txt"
        output_file = self._get_arg(args, "--file") or self._get_arg(args, "-o")

        entity = entity.lower()
        valid_entities = ("contacts", "diagnoses", "meds", "labs", "all")
        if entity not in valid_entities:
            return False, f"Ungueltiger Entity-Typ: {entity}\nGueltig: {', '.join(valid_entities)}"

        conn = self._get_db()
        try:
            if entity == "all":
                output = self._format_gesundheitspass(conn)
            elif entity == "contacts":
                output = self._export_contacts(conn, specialty_filter, export_format)
            elif entity == "diagnoses":
                output = self._export_diagnoses(conn, export_format)
            elif entity == "meds":
                output = self._export_meds(conn, export_format)
            elif entity == "labs":
                output = self._export_labs(conn, export_format)
            else:
                return False, f"Unbekannter Entity-Typ: {entity}"

            if not output:
                return True, f"[EXPORT] Keine Daten gefunden fuer: {entity}"

            # In Datei speichern oder ausgeben
            if output_file:
                try:
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(output)
                    return True, f"[EXPORT] {entity} exportiert nach: {output_file}"
                except Exception as e:
                    return False, f"[ERROR] Schreiben fehlgeschlagen: {e}"
            else:
                header = f"[EXPORT] {entity.upper()} ({export_format.upper()}):\n"
                return True, header + "\n" + output

        finally:
            conn.close()

    def _export_contacts(self, conn, specialty_filter: Optional[str], fmt: str) -> str:
        """Exportiert Arzt-Kontakte."""
        query = "SELECT * FROM health_contacts WHERE is_active = 1"
        params = []
        if specialty_filter:
            query += " AND specialty LIKE ?"
            params.append(f"%{specialty_filter}%")
        query += " ORDER BY specialty ASC, name ASC"
        rows = conn.execute(query, params).fetchall()
        if not rows:
            return ""
        if fmt.lower() == "vcard":
            return self._format_contacts_vcard(rows)
        elif fmt.lower() == "csv":
            return self._format_contacts_csv(rows)
        else:
            return self._format_contacts_text(rows)

    def _export_diagnoses(self, conn, fmt: str) -> str:
        """Exportiert Diagnosen."""
        rows = conn.execute("""
            SELECT hd.*, hc.name as doctor_name
            FROM health_diagnoses hd
            LEFT JOIN health_contacts hc ON hd.doctor_id = hc.id
            ORDER BY hd.diagnosis_date DESC
        """).fetchall()
        if not rows:
            return ""
        if fmt.lower() == "csv":
            lines = ["Diagnose;ICD-Code;Status;Schweregrad;Datum;Arzt"]
            for r in rows:
                line = ";".join([
                    r["diagnosis_name"] or "",
                    r["icd_code"] or "",
                    r["status"] or "",
                    r["severity"] or "",
                    (r["diagnosis_date"] or "")[:10],
                    r["doctor_name"] or "",
                ])
                lines.append(line)
            return "\n".join(lines)
        else:
            lines = []
            for r in rows:
                icd = f" [{r['icd_code']}]" if r["icd_code"] else ""
                status = r["status"] or "?"
                severity = f" ({r['severity']})" if r["severity"] else ""
                date = (r["diagnosis_date"] or "---")[:10]
                doctor = f" - Arzt: {r['doctor_name']}" if r["doctor_name"] else ""
                lines.append(f"  {r['diagnosis_name']}{icd} [{status}]{severity}  {date}{doctor}")
            return "\n".join(lines)

    def _export_meds(self, conn, fmt: str) -> str:
        """Exportiert Medikamente."""
        rows = conn.execute("""
            SELECT hm.*, hd.diagnosis_name
            FROM health_medications hm
            LEFT JOIN health_diagnoses hd ON hm.diagnosis_id = hd.id
            ORDER BY hm.status DESC, hm.name ASC
        """).fetchall()
        if not rows:
            return ""
        if fmt.lower() == "csv":
            lines = ["Name;Wirkstoff;Dosierung;Einnahmeplan;Status;Diagnose"]
            for r in rows:
                line = ";".join([
                    r["name"] or "",
                    r["active_ingredient"] or "",
                    r["dosage"] or "",
                    r["schedule"] or "",
                    r["status"] or "",
                    r["diagnosis_name"] or "",
                ])
                lines.append(line)
            return "\n".join(lines)
        else:
            lines = []
            for r in rows:
                status_mark = "+" if r["status"] == "aktiv" else "-"
                dosage = r["dosage"] or "---"
                schedule = r["schedule"] or "---"
                ingredient = f" ({r['active_ingredient']})" if r["active_ingredient"] else ""
                diag = f" -> {r['diagnosis_name']}" if r["diagnosis_name"] else ""
                lines.append(f"  {status_mark} {r['name']}{ingredient}  {dosage}  {schedule}{diag}")
            return "\n".join(lines)

    def _export_labs(self, conn, fmt: str) -> str:
        """Exportiert Laborwerte."""
        rows = conn.execute("""
            SELECT * FROM health_lab_values
            ORDER BY test_date DESC, test_name ASC
        """).fetchall()
        if not rows:
            return ""
        if fmt.lower() == "csv":
            lines = ["Test;Wert;Einheit;Ref-Min;Ref-Max;Datum;Auffaellig"]
            for r in rows:
                line = ";".join([
                    r["test_name"] or "",
                    str(r["value"]) if r["value"] is not None else "",
                    r["unit"] or "",
                    str(r["reference_min"]) if r["reference_min"] is not None else "",
                    str(r["reference_max"]) if r["reference_max"] is not None else "",
                    (r["test_date"] or "")[:10],
                    "JA" if r["is_abnormal"] else "Nein",
                ])
                lines.append(line)
            return "\n".join(lines)
        else:
            lines = []
            for r in rows:
                date = (r["test_date"] or "---")[:10]
                abnormal = " [!!!]" if r["is_abnormal"] else ""
                ref = ""
                if r["reference_min"] is not None or r["reference_max"] is not None:
                    ref = f" (Ref: {r['reference_min'] or '?'}-{r['reference_max'] or '?'})"
                lines.append(f"  {date}  {r['test_name']:<25} {r['value'] or '?':>8} {(r['unit'] or ''):<8}{ref}{abnormal}")
            return "\n".join(lines)

    def _format_gesundheitspass(self, conn) -> str:
        """Erstellt einen umfassenden Gesundheitspass (Textformat)."""
        lines = []
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        lines.append("=" * 60)
        lines.append("           GESUNDHEITSPASS")
        lines.append(f"           Erstellt: {now}")
        lines.append("=" * 60)

        # 1. Aktive Diagnosen mit ICD-Codes
        diagnoses = conn.execute("""
            SELECT hd.*, hc.name as doctor_name
            FROM health_diagnoses hd
            LEFT JOIN health_contacts hc ON hd.doctor_id = hc.id
            WHERE hd.status IN ('aktiv', 'in_abklaerung')
            ORDER BY hd.diagnosis_date DESC
        """).fetchall()
        lines.append("")
        lines.append("--- AKTIVE DIAGNOSEN ---")
        if diagnoses:
            for d in diagnoses:
                icd = f" [{d['icd_code']}]" if d["icd_code"] else ""
                severity = f" ({d['severity']})" if d["severity"] else ""
                status = "ABK" if d["status"] == "in_abklaerung" else "AKT"
                date = (d["diagnosis_date"] or "---")[:10]
                doctor = f"  Arzt: {d['doctor_name']}" if d["doctor_name"] else ""
                lines.append(f"  [{status}] {d['diagnosis_name']}{icd}{severity}  seit {date}{doctor}")
        else:
            lines.append("  Keine aktiven Diagnosen.")

        # 2. Aktuelle Medikamente mit Dosierung
        meds = conn.execute("""
            SELECT hm.*, hd.diagnosis_name
            FROM health_medications hm
            LEFT JOIN health_diagnoses hd ON hm.diagnosis_id = hd.id
            WHERE hm.status = 'aktiv'
            ORDER BY hm.name ASC
        """).fetchall()
        lines.append("")
        lines.append("--- AKTUELLE MEDIKATION ---")
        if meds:
            for m in meds:
                dosage = m["dosage"] or "---"
                schedule = m["schedule"] or "---"
                ingredient = f" ({m['active_ingredient']})" if m["active_ingredient"] else ""
                diag = f"  -> {m['diagnosis_name']}" if m["diagnosis_name"] else ""
                lines.append(f"  {m['name']}{ingredient}")
                lines.append(f"    Dosierung: {dosage}, Einnahme: {schedule}{diag}")
        else:
            lines.append("  Keine aktiven Medikamente.")

        # 3. Auffaellige Laborwerte
        labs = conn.execute("""
            SELECT * FROM health_lab_values
            WHERE is_abnormal = 1
            ORDER BY test_date DESC
        """).fetchall()
        lines.append("")
        lines.append("--- AUFFAELLIGE LABORWERTE ---")
        if labs:
            for l in labs:
                date = (l["test_date"] or "---")[:10]
                ref = ""
                if l["reference_min"] is not None or l["reference_max"] is not None:
                    ref = f" (Ref: {l['reference_min'] or '?'}-{l['reference_max'] or '?'})"
                lines.append(f"  {date}  {l['test_name']:<25} {l['value'] or '?':>8} {(l['unit'] or ''):<8}{ref}")
        else:
            lines.append("  Keine auffaelligen Laborwerte.")

        # 4. Arzt-Kontakte
        contacts = conn.execute("""
            SELECT * FROM health_contacts
            WHERE is_active = 1
            ORDER BY specialty ASC, name ASC
        """).fetchall()
        lines.append("")
        lines.append("--- ARZT-KONTAKTE ---")
        if contacts:
            current_spec = None
            for c in contacts:
                spec = c["specialty"] or "Sonstige"
                if spec != current_spec:
                    current_spec = spec
                    lines.append(f"  [{spec}]")
                phone = f"  Tel: {c['phone']}" if c["phone"] else ""
                institution = f" ({c['institution']})" if c["institution"] else ""
                lines.append(f"    {c['name']}{institution}{phone}")
        else:
            lines.append("  Keine Arzt-Kontakte.")

        lines.append("")
        lines.append("=" * 60)
        lines.append("  Ende Gesundheitspass")
        lines.append("=" * 60)
        return "\n".join(lines)

    def _format_contacts_csv(self, rows) -> str:
        """Formatiert Arzt-Kontakte als CSV."""
        lines = ["Name;Fachgebiet;Institution;Telefon;Email;Adresse;Notiz"]
        for r in rows:
            line = ";".join([
                r["name"] or "",
                r["specialty"] or "",
                r["institution"] or "",
                r["phone"] or "",
                r["email"] or "",
                (r["address"] or "").replace("\n", " "),
                (r["notes"] or "").replace("\n", " ").replace(";", ",")
            ])
            lines.append(line)
        return "\n".join(lines)

    def _format_contacts_text(self, rows) -> str:
        """Formatiert Arzt-Kontakte als lesbaren Text."""
        lines = []
        current_spec = None

        for r in rows:
            spec = r["specialty"] or "Sonstige"
            if spec != current_spec:
                current_spec = spec
                lines.append(f"\n=== {spec.upper()} ===")

            lines.append(f"\n{r['name']}")
            if r["institution"]:
                lines.append(f"  Institution: {r['institution']}")
            if r["phone"]:
                lines.append(f"  Telefon:     {r['phone']}")
            if r["email"]:
                lines.append(f"  Email:       {r['email']}")
            if r["address"]:
                addr = r["address"].replace("\n", ", ")
                lines.append(f"  Adresse:     {addr}")
            if r["notes"]:
                note = r["notes"][:100] + "..." if len(r["notes"] or "") > 100 else r["notes"]
                lines.append(f"  Notiz:       {note}")

        return "\n".join(lines)

    def _format_contacts_vcard(self, rows) -> str:
        """Formatiert Arzt-Kontakte als vCard 3.0."""
        vcards = []

        for r in rows:
            lines = []
            lines.append("BEGIN:VCARD")
            lines.append("VERSION:3.0")

            # Name splitten (Vorname Nachname)
            name = r["name"] or ""
            parts = name.strip().split(None, 1)
            if len(parts) == 2:
                first, last = parts[0], parts[1]
            elif len(parts) == 1:
                first, last = parts[0], ""
            else:
                first, last = "", ""

            lines.append("N:" + self._vcard_escape(last) + ";" + self._vcard_escape(first) + ";;;")
            lines.append("FN:" + self._vcard_escape(name))

            if r["institution"]:
                lines.append("ORG:" + self._vcard_escape(r["institution"]))

            if r["specialty"]:
                lines.append("TITLE:" + self._vcard_escape(r["specialty"]))

            if r["phone"]:
                lines.append("TEL;TYPE=WORK:" + self._vcard_escape(r["phone"]))

            if r["email"]:
                lines.append("EMAIL;TYPE=WORK:" + self._vcard_escape(r["email"]))

            if r["address"]:
                lines.append("ADR;TYPE=WORK:;;" + self._vcard_escape(r["address"]) + ";;;;")

            if r["notes"]:
                lines.append("NOTE:" + self._vcard_escape(r["notes"]))

            lines.append("END:VCARD")
            vcards.append("\n".join(lines))

        return "\n".join(vcards)

    @staticmethod
    def _vcard_escape(value: str) -> str:
        """Escapt Sonderzeichen fuer vCard 3.0."""
        if not value:
            return ""
        # vCard 3.0 escaping: backslash, semicolon, comma, newline
        value = value.replace("\\", "\\\\")
        value = value.replace(";", "\\;")
        value = value.replace(",", "\\,")
        value = value.replace("\n", "\\n")
        value = value.replace("\r", "")
        return value

    # ------------------------------------------------------------------
    # REMINDERS - Proaktive Erinnerungen (LifeAssistant)
    # ------------------------------------------------------------------
    def _reminders(self, args: List[str]) -> Tuple[bool, str]:
        """Proaktive Erinnerungen: Medikamente, faellige Vorsorge, anstehende Termine."""
        conn = self._get_db()
        try:
            lines = ["GESUNDHEITS-ERINNERUNGEN", "=" * 50, ""]
            has_reminders = False
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")

            # 1. Aktive Medikamente (taeglich relevant)
            meds = conn.execute("""
                SELECT name, dosage, schedule FROM health_medications
                WHERE status = 'aktiv' ORDER BY name
            """).fetchall()
            if meds:
                has_reminders = True
                lines.append(f"  MEDIKAMENTE ({len(meds)} aktiv):")
                for m in meds:
                    schedule = m["schedule"] or "keine Angabe"
                    dosage = m["dosage"] or ""
                    lines.append(f"    - {m['name']} {dosage} ({schedule})")
                lines.append("")

            # 2. Faellige Vorsorgeuntersuchungen
            try:
                vorsorge = conn.execute("""
                    SELECT untersuchung, naechster_termin, turnus_monate, kategorie
                    FROM vorsorge_checks
                    WHERE naechster_termin <= ? OR naechster_termin IS NULL
                    ORDER BY naechster_termin ASC
                """, (today,)).fetchall()
                if vorsorge:
                    has_reminders = True
                    lines.append(f"  FAELLIGE VORSORGE ({len(vorsorge)}):")
                    for v in vorsorge:
                        termin = v["naechster_termin"] or "ueberfaellig"
                        lines.append(f"    [!] {v['untersuchung']} - faellig: {termin}")
                    lines.append("")
            except Exception as e:
                lines.append(f"  [Vorsorge-Abfrage fehlgeschlagen: {e}]")
                lines.append("")

            # 3. Anstehende Arzttermine (naechste 14 Tage)
            try:
                in_14_days = (now + timedelta(days=14)).strftime("%Y-%m-%d")
                appointments = conn.execute("""
                    SELECT hc.name as arzt,
                           date(ha.appointment_date) as termin_date,
                           time(ha.appointment_date) as termin_time,
                           ha.title, ha.status
                    FROM health_appointments ha
                    LEFT JOIN health_contacts hc ON ha.doctor_id = hc.id
                    WHERE date(ha.appointment_date) BETWEEN ? AND ?
                      AND ha.status != 'abgesagt'
                    ORDER BY ha.appointment_date
                """, (today, in_14_days)).fetchall()
                if appointments:
                    has_reminders = True
                    lines.append(f"  ANSTEHENDE TERMINE ({len(appointments)}, naechste 14 Tage):")
                    for a in appointments:
                        arzt = a["arzt"] or "?"
                        zeit = a["termin_time"] or ""
                        lines.append(f"    {a['termin_date']} {zeit} - {arzt}: {a['title'] or '-'}")
                    lines.append("")
            except Exception as e:
                lines.append(f"  [Termin-Abfrage fehlgeschlagen: {e}]")
                lines.append("")

            if not has_reminders:
                lines.append("  Keine aktiven Erinnerungen.")
                lines.append("  Nutze: bach gesundheit add-med, add-appointment, add-vorsorge")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # INTERACTIONS - Wechselwirkungs-Check
    # ------------------------------------------------------------------
    def _interactions(self, args: List[str]) -> Tuple[bool, str]:
        """Prueft bekannte Wechselwirkungen zwischen aktiven Medikamenten."""

        # Bekannte Wechselwirkungen (Basis-Datenbank)
        # Format: (med_a, med_b, severity, description)
        KNOWN_INTERACTIONS = [
            ("ibuprofen", "aspirin", "hoch", "Erhoehtes Blutungsrisiko, verminderte Aspirin-Wirkung"),
            ("ibuprofen", "blutverdünner", "hoch", "Stark erhoehtes Blutungsrisiko"),
            ("paracetamol", "alkohol", "hoch", "Leberschaeden moeglich"),
            ("metformin", "alkohol", "mittel", "Erhoehtes Laktatazidose-Risiko"),
            ("simvastatin", "grapefruit", "mittel", "Erhoehte Statin-Spiegel, Muskelschmerzen"),
            ("warfarin", "aspirin", "hoch", "Stark erhoehtes Blutungsrisiko"),
            ("ssri", "tramadol", "hoch", "Serotonin-Syndrom moeglich"),
            ("ace-hemmer", "kalium", "mittel", "Hyperkalaemie-Risiko"),
            ("metoprolol", "verapamil", "hoch", "Bradykardie, AV-Block"),
            ("lithium", "ibuprofen", "hoch", "Erhoehte Lithium-Spiegel"),
            ("ciprofloxacin", "magnesium", "mittel", "Verminderte Antibiotika-Aufnahme"),
            ("omeprazol", "clopidogrel", "mittel", "Verminderte Clopidogrel-Wirkung"),
        ]

        conn = self._get_db()
        try:
            meds = conn.execute("""
                SELECT id, name, dosage FROM health_medications
                WHERE status = 'aktiv'
            """).fetchall()

            if len(meds) < 2:
                return True, (
                    "[GESUNDHEIT] Wechselwirkungs-Check\n"
                    f"  Aktive Medikamente: {len(meds)}\n"
                    "  Mindestens 2 Medikamente noetig fuer Interaktions-Check."
                )

            med_names = [(m["id"], m["name"].lower(), m["dosage"]) for m in meds]
            warnings = []

            # Paarweise pruefen
            for i in range(len(med_names)):
                for j in range(i + 1, len(med_names)):
                    name_a = med_names[i][1]
                    name_b = med_names[j][1]

                    for ia, ib, severity, desc in KNOWN_INTERACTIONS:
                        if (ia in name_a and ib in name_b) or \
                           (ib in name_a and ia in name_b):
                            warnings.append({
                                "med_a": med_names[i][1],
                                "med_b": med_names[j][1],
                                "severity": severity,
                                "description": desc,
                            })

            lines = [
                "[GESUNDHEIT] Wechselwirkungs-Check",
                "=" * 50,
                f"  Aktive Medikamente: {len(meds)}",
                f"  Geprueft: {len(med_names) * (len(med_names)-1) // 2} Kombinationen",
                f"  Bekannte Interaktionen: {len(KNOWN_INTERACTIONS)} in Datenbank",
                "",
            ]

            if warnings:
                lines.append(f"  [!] {len(warnings)} WECHSELWIRKUNGEN GEFUNDEN:\n")
                for w in warnings:
                    icon = "[!!!]" if w["severity"] == "hoch" else "[!!]"
                    lines.append(f"  {icon} {w['med_a']} + {w['med_b']} ({w['severity']})")
                    lines.append(f"       {w['description']}")
                    lines.append("")
                lines.append("  HINWEIS: Dies ersetzt KEINE aerztliche Beratung!")
                lines.append("  Bitte Wechselwirkungen mit Arzt/Apotheker besprechen.")
            else:
                lines.append("  Keine bekannten Wechselwirkungen gefunden.")
                lines.append("  HINWEIS: Datenbank ist nicht vollstaendig.")
                lines.append("  Bei Unsicherheit Arzt/Apotheker konsultieren.")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # HELP
    # ------------------------------------------------------------------
    def _help(self) -> Tuple[bool, str]:
        return True, """GESUNDHEIT - Gesundheitsassistent
=================================

BEFEHLE:
  bach gesundheit status           Dashboard (Zusammenfassung)
  bach gesundheit contacts         Arzt-Kontakte anzeigen
  bach gesundheit contacts -s Immunologie  Nach Fachgebiet filtern
  bach gesundheit diagnoses        Aktive Diagnosen
  bach gesundheit diagnoses --all  Alle Diagnosen
  bach gesundheit meds             Aktive Medikamente
  bach gesundheit labs             Laborwerte (letzte 50)
  bach gesundheit labs --abnormal  Nur auffaellige Werte
  bach gesundheit labs -t TSH      Nach Test filtern
  bach gesundheit docs             Gesundheitsdokumente
  bach gesundheit docs --type befund  Nach Typ filtern
  bach gesundheit appointments     Kommende Termine
  bach gesundheit appointments --past  Vergangene Termine

VORSORGE:
  bach gesundheit vorsorge             Alle Vorsorgeuntersuchungen
  bach gesundheit vorsorge-faellig     Faellige Untersuchungen
  bach gesundheit add-vorsorge "Darmspiegelung" --turnus 120 --kategorie Krebs
  bach gesundheit add-vorsorge "Hautkrebsscreening" --turnus 24 --ab-alter 35
  bach gesundheit vorsorge-done 1      Als erledigt markieren (heute)
  bach gesundheit vorsorge-done 1 --date 15.01.2026  Mit Datum

EXPORT:
  bach gesundheit export                              Arzt-Kontakte (default)
  bach gesundheit export --entity diagnoses           Diagnosen exportieren
  bach gesundheit export --entity meds                Medikamente exportieren
  bach gesundheit export --entity labs                Laborwerte exportieren
  bach gesundheit export --entity all                 Gesundheitspass (alles)
  bach gesundheit export -s Immunologie               Nur ein Fachgebiet
  bach gesundheit export --format csv                 Als CSV
  bach gesundheit export --format vcard               Als vCard 3.0
  bach gesundheit export --entity all --file pass.txt In Datei speichern

HINZUFUEGEN:
  bach gesundheit add-diagnosis "Hypothyreose" --icd E03.9 --status aktiv
  bach gesundheit add-med "L-Thyroxin" --dosage 75mcg --schedule morgens
  bach gesundheit add-lab "TSH" --value 2.5 --unit mU/L --ref-min 0.4 --ref-max 4.0 --date 28.01.2026
  bach gesundheit add-doc "Blutwerte Jan 2026" --type labor --file /pfad/zur/datei.pdf
  bach gesundheit add-appointment "Kontrolle" --doctor 1 --date 15.02.2026 --time 10:00

DETAILS:
  bach gesundheit show contact 1
  bach gesundheit show diagnosis 1
  bach gesundheit show med 1
  bach gesundheit show lab 1
  bach gesundheit show vorsorge 1

DATENBANK: bach.db / health_contacts, health_diagnoses, health_medications,
           health_lab_values, health_documents, health_appointments,
           vorsorge_checks (Unified DB seit v1.1.84)"""

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------
    def _parse_ids(self, args: List[str]) -> Tuple[List[int], List[str]]:
        ids = []
        rest = []
        for arg in args:
            try:
                ids.append(int(arg))
            except ValueError:
                rest.append(arg)
        return ids, rest

    def _get_arg(self, args: List[str], flag: str) -> Optional[str]:
        for i, a in enumerate(args):
            if a == flag and i + 1 < len(args):
                return args[i + 1]
            if a.startswith(flag + "="):
                return a[len(flag) + 1:]
        return None

    def _get_first_arg(self, args: List[str]) -> Optional[str]:
        """Returns first non-flag argument."""
        for a in args:
            if not a.startswith("-"):
                return a
        return None

    def _parse_date(self, date_str: str) -> Optional[str]:
        """Parse DD.MM.YYYY oder YYYY-MM-DD zu YYYY-MM-DD."""
        for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        return None
