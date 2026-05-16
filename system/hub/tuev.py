# SPDX-License-Identifier: MIT
"""
TUeV Handler - Workflow-Qualitaetssicherung
============================================

Subcommands:
  bach tuev status                   TUeV-Status aller Workflows
  bach tuev check <workflow>         Einzelnen Workflow pruefen
  bach tuev run                      Alle faelligen Pruefungen
  bach tuev renew <workflow>         TUeV erneuern nach Pruefung

  bach usecase add <workflow>        Neuen Testfall hinzufuegen
  bach usecase list [workflow]       Testfaelle anzeigen
  bach usecase run <id>              Testfall ausfuehren
  bach usecase run-all <workflow>    Alle Testfaelle eines Workflows

v1.1.83: Initial Implementation (WF-TUEV-02)
"""
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from .base import BaseHandler


class TuevHandler(BaseHandler):
    """Handler fuer bach tuev - Workflow-TUeV"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = self._canonical_db
        self.workflows_dir = base_path / "skills" / "_workflows"

    @property
    def profile_name(self) -> str:
        return "tuev"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "status": "TUeV-Status aller Workflows",
            "check": "Einzelnen Workflow pruefen",
            "run": "Alle faelligen Pruefungen",
            "renew": "TUeV erneuern nach Pruefung",
            "init": "Workflows in DB registrieren"
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation == "status" or not operation:
            return self._status()

        elif operation == "check":
            if not args:
                return False, "Usage: bach tuev check <workflow-name>"
            return self._check(args[0])

        elif operation == "run":
            return self._run_all()

        elif operation == "renew":
            if not args:
                return False, "Usage: bach tuev renew <workflow-name>"
            return self._renew(args[0])

        elif operation == "init":
            return self._init_workflows()

        else:
            return False, f"Unbekannte Operation: {operation}\nNutze: bach tuev status"

    def _get_conn(self) -> sqlite3.Connection:
        """Datenbankverbindung holen."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _status(self) -> Tuple[bool, str]:
        """Zeigt TUeV-Status aller Workflows."""
        conn = self._get_conn()

        # Workflows aus DB laden
        rows = conn.execute("""
            SELECT workflow_name, workflow_path, tuev_status,
                   tuev_valid_until, avg_score, test_count, pass_count
            FROM workflow_tuev
            ORDER BY tuev_valid_until ASC
        """).fetchall()
        conn.close()

        if not rows:
            return True, "[TUeV] Keine Workflows registriert.\nNutze: bach tuev init"

        lines = ["[WORKFLOW-TUeV] Status-Uebersicht", ""]

        # Gruppen: Abgelaufen, Bald faellig, OK
        expired = []
        soon = []
        ok = []
        now = datetime.now()

        for r in rows:
            valid_until = r["tuev_valid_until"]
            if valid_until:
                try:
                    valid_dt = datetime.fromisoformat(valid_until)
                    days_left = (valid_dt - now).days
                    if days_left < 0:
                        expired.append((r, days_left))
                    elif days_left < 14:
                        soon.append((r, days_left))
                    else:
                        ok.append((r, days_left))
                except (ValueError, TypeError):
                    ok.append((r, 999))
            else:
                expired.append((r, -999))

        # Abgelaufene
        if expired:
            lines.append("ABGELAUFEN (sofort pruefen!):")
            for r, days in expired:
                status = r["tuev_status"] or "pending"
                score = r["avg_score"] or 0
                name = r["workflow_name"]
                lines.append(f"  [!] {name:<30} Score: {score:3.0f}% | Status: {status}")

        # Bald faellig
        if soon:
            lines.append("")
            lines.append("BALD FAELLIG (< 14 Tage):")
            for r, days in soon:
                score = r["avg_score"] or 0
                name = r["workflow_name"]
                lines.append(f"  [~] {name:<30} Score: {score:3.0f}% | {days}d")

        # OK
        if ok:
            lines.append("")
            lines.append("OK:")
            for r, days in ok[:5]:  # Max 5 anzeigen
                score = r["avg_score"] or 0
                name = r["workflow_name"]
                status_str = f"{days}d" if days < 999 else "?"
                lines.append(f"  [✓] {name:<30} Score: {score:3.0f}% | {status_str}")
            if len(ok) > 5:
                lines.append(f"  ... und {len(ok) - 5} weitere")

        lines.append("")
        lines.append(f"Gesamt: {len(rows)} Workflows | Abgelaufen: {len(expired)} | Bald: {len(soon)} | OK: {len(ok)}")

        return True, "\n".join(lines)

    def _check(self, workflow_name: str) -> Tuple[bool, str]:
        """Prueft einzelnen Workflow."""
        conn = self._get_conn()

        # Workflow finden
        row = conn.execute("""
            SELECT * FROM workflow_tuev WHERE workflow_name = ? OR workflow_path LIKE ?
        """, (workflow_name, f"%{workflow_name}%")).fetchone()

        if not row:
            conn.close()
            return False, f"[TUeV] Workflow '{workflow_name}' nicht gefunden"

        # Usecases fuer diesen Workflow laden
        usecases = conn.execute("""
            SELECT * FROM usecases WHERE workflow_name = ? OR workflow_path = ?
        """, (row["workflow_name"], row["workflow_path"])).fetchall()
        conn.close()

        lines = [f"[TUeV] Pruefung: {row['workflow_name']}", ""]
        lines.append(f"Pfad: {row['workflow_path']}")
        lines.append(f"Status: {row['tuev_status'] or 'pending'}")
        lines.append(f"Letzter TUeV: {row['last_tuev_date'] or 'nie'}")
        lines.append(f"Gueltig bis: {row['tuev_valid_until'] or 'abgelaufen'}")
        lines.append(f"Score: {row['avg_score'] or 0:.0f}%")
        lines.append("")

        if not usecases:
            lines.append("[WARN] Keine Usecases definiert!")
            lines.append("Nutze: bach usecase add " + row["workflow_name"])
        else:
            lines.append(f"Usecases: {len(usecases)}")
            for uc in usecases:
                result = uc["test_result"] or "?"
                symbol = "✓" if result == "pass" else ("✗" if result == "fail" else "?")
                lines.append(f"  [{symbol}] {uc['title']} ({result})")

        return True, "\n".join(lines)

    def _run_all(self) -> Tuple[bool, str]:
        """Fuehrt alle faelligen TUeV-Pruefungen aus."""
        conn = self._get_conn()

        # Abgelaufene Workflows finden
        now = datetime.now().isoformat()
        rows = conn.execute("""
            SELECT workflow_name, workflow_path FROM workflow_tuev
            WHERE tuev_valid_until IS NULL OR tuev_valid_until < ?
            ORDER BY tuev_valid_until ASC
        """, (now,)).fetchall()
        conn.close()

        if not rows:
            return True, "[TUeV] Keine faelligen Pruefungen"

        lines = ["[TUeV] Faellige Pruefungen", ""]

        for r in rows:
            lines.append(f"  - {r['workflow_name']}")
            # Hier wuerde der eigentliche Test laufen
            # Fuer jetzt: Nur Hinweis

        lines.append("")
        lines.append(f"Gesamt: {len(rows)} Workflows zur Pruefung faellig")
        lines.append("")
        lines.append("Naechste Schritte:")
        lines.append("  1. bach tuev check <workflow>  (Details)")
        lines.append("  2. bach usecase run-all <workflow>  (Tests)")
        lines.append("  3. bach tuev renew <workflow>  (Bei Erfolg)")

        return True, "\n".join(lines)

    def _renew(self, workflow_name: str) -> Tuple[bool, str]:
        """Erneuert TUeV nach erfolgreicher Pruefung."""
        conn = self._get_conn()

        # Workflow finden
        row = conn.execute("""
            SELECT * FROM workflow_tuev WHERE workflow_name = ? OR workflow_path LIKE ?
        """, (workflow_name, f"%{workflow_name}%")).fetchone()

        if not row:
            conn.close()
            return False, f"[TUeV] Workflow '{workflow_name}' nicht gefunden"

        # TUeV erneuern (90 Tage Gueltigkeit)
        now = datetime.now()
        new_valid = (now + timedelta(days=90)).isoformat()

        conn.execute("""
            UPDATE workflow_tuev
            SET last_tuev_date = ?,
                tuev_valid_until = ?,
                tuev_status = 'passed'
            WHERE id = ?
        """, (now.isoformat(), new_valid, row["id"]))
        conn.commit()
        conn.close()

        return True, f"[TUeV] {row['workflow_name']} erneuert\n  Gueltig bis: {new_valid[:10]}"

    def _init_workflows(self) -> Tuple[bool, str]:
        """Initialisiert Workflows aus skills/workflows/ in DB."""
        if not self.workflows_dir.exists():
            return False, f"[TUeV] Workflows-Verzeichnis nicht gefunden: {self.workflows_dir}"

        conn = self._get_conn()

        # Alle .md Dateien im Workflows-Verzeichnis
        workflows = list(self.workflows_dir.glob("*.md"))
        added = 0
        skipped = 0

        for wf in workflows:
            wf_name = wf.stem  # z.B. "bugfix-protokoll"
            wf_path = str(wf.relative_to(self.base_path))

            # Pruefen ob schon in DB
            existing = conn.execute(
                "SELECT id FROM workflow_tuev WHERE workflow_path = ?",
                (wf_path,)
            ).fetchone()

            if existing:
                skipped += 1
                continue

            # In DB einfuegen
            conn.execute("""
                INSERT INTO workflow_tuev (workflow_path, workflow_name, tuev_status)
                VALUES (?, ?, 'pending')
            """, (wf_path, wf_name))
            added += 1

        conn.commit()
        conn.close()

        return True, f"[TUeV] Workflows initialisiert\n  Hinzugefuegt: {added}\n  Uebersprungen: {skipped}"


class UsecaseHandler(BaseHandler):
    """Handler fuer bach usecase - Testfaelle"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = self._canonical_db

    @property
    def profile_name(self) -> str:
        return "usecase"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "add": "Neuen Testfall hinzufuegen",
            "list": "Testfaelle anzeigen",
            "run": "Testfall ausfuehren",
            "run-all": "Alle Testfaelle eines Workflows",
            "show": "Testfall-Details anzeigen"
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation == "list" or not operation:
            workflow = args[0] if args else None
            return self._list(workflow)

        elif operation == "add":
            if not args:
                return False, "Usage: bach usecase add <workflow-name>"
            return self._add_interactive(args[0])

        elif operation == "run":
            if not args:
                return False, "Usage: bach usecase run <id>"
            return self._run(args[0])

        elif operation == "run-all":
            if not args:
                return False, "Usage: bach usecase run-all <workflow-name>"
            return self._run_all(args[0])

        elif operation == "show":
            if not args:
                return False, "Usage: bach usecase show <id>"
            return self._show(args[0])

        else:
            return False, f"Unbekannte Operation: {operation}\nNutze: bach usecase list"

    def _get_conn(self) -> sqlite3.Connection:
        """Datenbankverbindung holen."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _workflow_candidates(self, row: sqlite3.Row, conn: sqlite3.Connection) -> List[Path]:
        """Leitet moegliche Workflow-Dateipfade fuer einen Usecase her.

        Historische Usecases enthalten teils nur Kategorienamen wie `SOFTWARE`
        statt eines konkreten `workflow_path`. Der Runner darf daran nicht
        scheitern, sondern versucht zuerst sinnvolle Kandidaten aufloesen.
        """
        candidates: List[Path] = []
        seen = set()

        def add_candidate(raw_value: Optional[str]):
            if not raw_value:
                return

            value = str(raw_value).strip().replace("\\", "/")
            if not value:
                return

            variants = [Path(value)]
            if not value.endswith(".md"):
                variants.append(Path(f"{value}.md"))

            if not value.startswith("skills/"):
                variants.extend([
                    Path("skills/workflows") / value,
                    Path("skills/_workflows") / value,
                ])
                if not value.endswith(".md"):
                    variants.extend([
                        Path("skills/workflows") / f"{value}.md",
                        Path("skills/_workflows") / f"{value}.md",
                    ])

            for variant in variants:
                normalized = variant.as_posix()
                if normalized in seen:
                    continue
                seen.add(normalized)
                candidates.append(self.base_path / variant)

        add_candidate(row["workflow_path"])

        workflow_name = (row["workflow_name"] or "").strip()
        if workflow_name:
            normalized_names = {
                workflow_name,
                workflow_name.lower(),
                workflow_name.lower().replace(" ", "-"),
                workflow_name.lower().replace("_", "-"),
                workflow_name.lower().replace(" ", "_"),
            }
            for name in sorted(normalized_names):
                add_candidate(name)

            tuev_rows = conn.execute(
                """
                SELECT workflow_path
                FROM workflow_tuev
                WHERE lower(workflow_name) = lower(?)
                ORDER BY workflow_path
                """,
                (workflow_name,),
            ).fetchall()
            for tuev_row in tuev_rows:
                add_candidate(tuev_row["workflow_path"])

        return candidates

    def _resolve_workflow_path(
        self, row: sqlite3.Row, conn: sqlite3.Connection
    ) -> Tuple[Optional[Path], List[Path]]:
        """Findet den ersten existierenden Workflow-Pfad fuer einen Usecase."""
        checked_paths: List[Path] = []
        for candidate in self._workflow_candidates(row, conn):
            checked_paths.append(candidate)
            if candidate.exists():
                return candidate, checked_paths
        return None, checked_paths

    def _list(self, workflow: str = None) -> Tuple[bool, str]:
        """Listet Testfaelle auf."""
        conn = self._get_conn()

        if workflow:
            rows = conn.execute("""
                SELECT * FROM usecases
                WHERE workflow_name = ? OR workflow_path LIKE ?
                ORDER BY id
            """, (workflow, f"%{workflow}%")).fetchall()
        else:
            rows = conn.execute("SELECT * FROM usecases ORDER BY workflow_name, id").fetchall()

        conn.close()

        if not rows:
            msg = f"[USECASES] Keine Testfaelle"
            if workflow:
                msg += f" fuer '{workflow}'"
            msg += "\nNutze: bach usecase add <workflow>"
            return True, msg

        lines = ["[USECASES] Testfaelle", ""]

        current_wf = None
        for r in rows:
            if r["workflow_name"] != current_wf:
                current_wf = r["workflow_name"]
                lines.append(f"\n{current_wf}:")

            result = r["test_result"] or "?"
            symbol = "✓" if result == "pass" else ("✗" if result == "fail" else "?")
            score = r["test_score"] or 0
            lines.append(f"  [{r['id']:3}] [{symbol}] {r['title']:<40} Score: {score}%")

        lines.append("")
        lines.append(f"Gesamt: {len(rows)} Testfaelle")

        return True, "\n".join(lines)

    def _add_interactive(self, workflow: str) -> Tuple[bool, str]:
        """Zeigt Hinweise zum Hinzufuegen eines Testfalls."""
        # Da wir kein interaktives CLI haben, geben wir SQL-Template aus
        return True, f"""[USECASE] Testfall hinzufuegen fuer: {workflow}

SQL zum Einfuegen:
------------------
INSERT INTO usecases (title, description, workflow_name, test_input, expected_output, created_by)
VALUES (
    'Testfall-Titel',
    'Beschreibung des Testfalls',
    '{workflow}',
    '{{"input_key": "input_value"}}',
    '{{"expected_key": "expected_value"}}',
    'user'
);

Oder via GUI: /usecases

Beispiel:
---------
bach db query "INSERT INTO usecases (title, workflow_name, test_input, expected_output, created_by) VALUES ('Einfacher Test', '{workflow}', '{{}}', '{{}}', 'user')"
"""

    def _show(self, usecase_id: str) -> Tuple[bool, str]:
        """Zeigt Testfall-Details."""
        conn = self._get_conn()

        row = conn.execute("SELECT * FROM usecases WHERE id = ?", (usecase_id,)).fetchone()
        conn.close()

        if not row:
            return False, f"[USECASE] Testfall {usecase_id} nicht gefunden"

        lines = [f"[USECASE] #{row['id']}: {row['title']}", ""]
        lines.append(f"Workflow: {row['workflow_name']}")
        lines.append(f"Pfad: {row['workflow_path'] or '-'}")
        lines.append(f"Beschreibung: {row['description'] or '-'}")
        lines.append("")
        lines.append("Test-Input:")
        lines.append(f"  {row['test_input'] or '{}'}")
        lines.append("")
        lines.append("Expected Output:")
        lines.append(f"  {row['expected_output'] or '{}'}")
        lines.append("")
        lines.append(f"Letzter Test: {row['last_tested'] or 'nie'}")
        lines.append(f"Ergebnis: {row['test_result'] or '-'}")
        lines.append(f"Score: {row['test_score'] or 0}%")
        lines.append(f"Erstellt von: {row['created_by'] or '-'}")

        return True, "\n".join(lines)

    @staticmethod
    def _parse_usecase_payload(raw_value):
        """Parst JSON-Felder rueckwaertskompatibel und faellt auf Klartext zurueck."""
        if raw_value is None:
            return {}

        if not isinstance(raw_value, str):
            return raw_value

        text = raw_value.strip()
        if not text:
            return {}

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    @staticmethod
    def _format_usecase_payload(value) -> str:
        """Formatiert Testdaten fuer die CLI-Ausgabe."""
        if isinstance(value, (dict, list)):
            return json.dumps(value, indent=2, ensure_ascii=False)
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    def _run(self, usecase_id: str) -> Tuple[bool, str]:
        """Fuehrt einen Testfall aus."""
        conn = self._get_conn()

        row = conn.execute("SELECT * FROM usecases WHERE id = ?", (usecase_id,)).fetchone()

        if not row:
            conn.close()
            return False, f"[USECASE] Testfall {usecase_id} nicht gefunden"

        # Test-Daten parsen
        try:
            test_input = self._parse_usecase_payload(row["test_input"])
            expected_output = self._parse_usecase_payload(row["expected_output"])
        except Exception as e:
            conn.close()
            return False, f"[USECASE] JSON-Fehler: {e}"

        wf_path, checked_paths = self._resolve_workflow_path(row, conn)

        lines = [f"[USECASE] Test #{row['id']}: {row['title']}", ""]
        workflow_label = row["workflow_path"] or row["workflow_name"] or "-"
        if wf_path is not None:
            try:
                relative = wf_path.relative_to(self.base_path)
            except ValueError:
                relative = wf_path
            lines.append(f"Workflow: {wf_path.name}")
            lines.append(f"Pfad: {relative}")
        else:
            lines.append(f"Workflow: {workflow_label}")
            lines.append("[WARN] Keine verknuepfte Workflow-Datei gefunden. Der Usecase kann trotzdem manuell geprueft werden.")
            if checked_paths:
                preview = ", ".join(
                    str(path.relative_to(self.base_path)) if path.is_relative_to(self.base_path) else str(path)
                    for path in checked_paths[:3]
                )
                lines.append(f"Gepruefte Pfade: {preview}")
        lines.append("")

        # Hier wuerde der eigentliche Test laufen
        # Da Workflows Markdown-Dateien sind, ist ein automatischer Test komplex
        # Wir markieren den Test als "durchgefuehrt" und erwarten manuelle Bewertung

        lines.append("Test-Input:")
        lines.append(f"  {self._format_usecase_payload(test_input)}")
        lines.append("")
        lines.append("Expected Output:")
        lines.append(f"  {self._format_usecase_payload(expected_output)}")
        lines.append("")
        lines.append("[INFO] Automatische Tests fuer Markdown-Workflows werden noch entwickelt.")
        lines.append("")
        lines.append("Manuelle Pruefung:")
        lines.append("  1. Workflow-Datei lesen")
        lines.append("  2. Test-Input gedanklich durchspielen")
        lines.append("  3. Mit Expected Output vergleichen")
        lines.append("")
        lines.append("Ergebnis eintragen:")
        lines.append(f'  bach db query "UPDATE usecases SET test_result=\'pass\', test_score=90, last_tested=datetime(\'now\') WHERE id={usecase_id}"')

        # Test als durchgefuehrt markieren
        conn.execute("""
            UPDATE usecases SET last_tested = datetime('now') WHERE id = ?
        """, (usecase_id,))
        conn.commit()
        conn.close()

        return True, "\n".join(lines)

    def _run_all(self, workflow: str) -> Tuple[bool, str]:
        """Fuehrt alle Testfaelle eines Workflows aus."""
        conn = self._get_conn()

        rows = conn.execute("""
            SELECT * FROM usecases
            WHERE workflow_name = ? OR workflow_path LIKE ?
            ORDER BY id
        """, (workflow, f"%{workflow}%")).fetchall()
        conn.close()

        if not rows:
            return True, f"[USECASE] Keine Testfaelle fuer '{workflow}'"

        lines = [f"[USECASE] Teste alle fuer: {workflow}", ""]

        for r in rows:
            lines.append(f"  [{r['id']}] {r['title']}")
            # Hier wuerde jeder Test laufen

        lines.append("")
        lines.append(f"Gesamt: {len(rows)} Testfaelle")
        lines.append("")
        lines.append("[INFO] Manuelle Pruefung erforderlich.")
        lines.append("       Nutze: bach usecase run <id>  fuer Details")

        return True, "\n".join(lines)
