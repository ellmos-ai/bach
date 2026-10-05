#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E06 – Altpfad-Stilllegung (BACH-Task #1424): Vorbereitungs-/Execution-Skript.

Zweck:
    Ersetzt die validierten Altpfad-Vorkommen "skills/_..." in genau 3 Dateien
    gemäß Stilllegungsliste aus BACH-Task #1424.

Umsetzungsfläche (Klassifikation aus #1424) – nur (a) und (c):
    (a) docs/memory_routing_mapping.md
        – Altpfad-Verweis in der Routing-Doku (1 Vorkommen, Z. 11)
    (c) Tests mit Altpfad-Hardcodes:
        – tests/test_tuev_handler.py        (6 Vorkommen, Z. 95–132)
        – tests/test_context_injector_db.py (2 Vorkommen, Z. 85–86)

    Explizit NICHT Teil der Umsetzung:
    (b) Mechanismus (Fallback-/Mapping-Logik im Code) – bleibt unverändert.
    (d) Logs sind archivierbar – sie werden nicht angetastet.
    (e) DB-Inhalte werden ignoriert (keine DB-Operationen in diesem Skript).

    WICHTIG: "skills/_services" ist KEIN Stilllegungskandidat und wird von
    diesem Skript nicht verändert.

Validierte Ersetzungen (Stand 2026-09-29, search_text "skills/_"):
    docs/memory_routing_mapping.md:
        "skills/_workflows" -> "skills/workflows"
            (erwartet 1x, Z. 11)
    tests/test_tuev_handler.py:
        "skills/_workflows/" -> "skills/workflows/"
            (erwartet 6x, Z. 95, 101, 107, 113, 127, 132)
    tests/test_context_injector_db.py:
        "skills/_experts/wikiquizzer" -> "agents/_experts/wikiquizzer"
            (erwartet 1x, Z. 85)
        "skills/_workflows/bugfix-protokoll.md" -> "skills/workflows/bugfix-protokoll.md"
            (erwartet 1x, Z. 86)

Sicherheit / Fail-Safes:
    * Default-Modus = PREVIEW: Es werden KEINE Dateien geändert, nur der
      Ersetzungsplan inkl. Zeilennummern ausgegeben.
    * "--apply" ohne zusätzliches "--confirm" wird verweigert (Exit-Code 1).
      Hintergrund: Task #1424 ist USER-gated – der Apply darf nur nach
      expliziter Nutzer-Freigabe (Briefing) laufen.
    * Trefferzahl-Validierung: Pro Datei/Muster wird die erwartete Anzahl
      geprüft (1 / 6 / 1 / 1). Bei Mismatch wird der Apply komplett
      verweigert (es wird nichts geändert).
    * Idempotenz: count(alt) == 0 und count(neu) >= erwartet
      → Muster/Datei gilt als "bereits migriert" und wird übersprungen.
    * Backup je geänderter Datei: <datei>.pre_e06.bak.<zeitstempel>
    * UTF-8 wird explizit gesetzt; Zeilenenden bleiben unverändert (newline="").
    * Nach jedem Schreibvorgang erfolgt eine Verifikation; bei Abweichung
      wird automatisch ein Rollback aus dem Backup durchgeführt (Exit-Code 2).

Nach erfolgreichem Apply empfohlen (Verifikation):
    pytest tests/test_tuev_handler.py tests/test_context_injector_db.py
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# (relativer Pfad ab Repo-Root, [(alt, neu, erwartete Trefferzahl), ...])
REPLACEMENTS = [
    (
        "docs/memory_routing_mapping.md",
        [
            ("skills/_workflows", "skills/workflows", 1),
        ],
    ),
    (
        "tests/test_tuev_handler.py",
        [
            ("skills/_workflows/", "skills/workflows/", 6),
        ],
    ),
    (
        "tests/test_context_injector_db.py",
        [
            ("skills/_experts/wikiquizzer", "agents/_experts/wikiquizzer", 1),
            (
                "skills/_workflows/bugfix-protokoll.md",
                "skills/workflows/bugfix-protokoll.md",
                1,
            ),
        ],
    ),
]

STATUS_LABEL = {
    "plan": "PLAN OK",
    "migrated": "BEREITS MIGRIERT",
    "mismatch": "MISMATCH",
    "error": "FEHLER",
}


def find_line_hits(text: str, needle: str):
    """Zeilennummern (1-basiert) aller Zeilen mit mind. 1 Vorkommen."""
    hits = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        count = line.count(needle)
        if count:
            hits.append((lineno, count))
    return hits


def analyze():
    """Liest alle Ziel-Dateien und klassifiziert jedes Muster (Fail-Safe)."""
    results = []
    for rel_path, patterns in REPLACEMENTS:
        path = REPO_ROOT / rel_path
        entry = {
            "rel": rel_path,
            "path": path,
            "exists": path.is_file(),
            "status": "error",
            "text": None,
            "patterns": [],
        }
        if not entry["exists"]:
            results.append(entry)
            continue
        with open(path, "r", encoding="utf-8", newline="") as fh:
            text = fh.read()
        entry["text"] = text
        statuses = []
        for old, new, expected in patterns:
            count_old = text.count(old)
            count_new = text.count(new)
            if count_old == expected:
                status = "plan"
            elif count_old == 0 and count_new >= expected:
                status = "migrated"
            else:
                status = "mismatch"
            statuses.append(status)
            entry["patterns"].append(
                {
                    "old": old,
                    "new": new,
                    "expected": expected,
                    "count_old": count_old,
                    "count_new": count_new,
                    "line_hits": find_line_hits(text, old),
                    "status": status,
                }
            )
        if "mismatch" in statuses:
            entry["status"] = "mismatch"
        elif statuses and all(s == "migrated" for s in statuses):
            entry["status"] = "migrated"
        else:
            entry["status"] = "plan"
        results.append(entry)
    return results


def print_report(results) -> None:
    print("=" * 72)
    print("E06 Altpfad-Stilllegung (Task #1424) – Ersetzungsplan")
    print("=" * 72)
    for idx, entry in enumerate(results, start=1):
        print()
        print(f"[{idx}/{len(results)}] Datei: {entry['rel']}")
        if not entry["exists"]:
            print("    FEHLER: Datei nicht gefunden – Apply wird verweigert.")
            continue
        for pat in entry["patterns"]:
            print(f"    Muster   : {pat['old']!r} -> {pat['new']!r}")
            print(
                f"    Erwartet : {pat['expected']} | Alt-Treffer: "
                f"{pat['count_old']} | Ziel-Treffer: {pat['count_new']}"
            )
            if pat["line_hits"]:
                detail = ", ".join(
                    f"Z.{lineno}" + (f" ({count}x)" if count > 1 else "")
                    for lineno, count in pat["line_hits"]
                )
                print(f"    Zeilen   : {detail}")
            print(f"    Status   : {STATUS_LABEL[pat['status']]}")
        print(f"    => Datei-Status: {STATUS_LABEL[entry['status']]}")


def apply_changes(results) -> int:
    """Führt die Ersetzungen durch (Backup + Verifikation je Datei)."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    changed_files = 0
    total_done = 0
    for entry in results:
        if entry["status"] == "migrated":
            print(f"  Überspringe (bereits migriert): {entry['rel']}")
            continue
        if entry["status"] != "plan":
            continue  # mismatch/error wurden vorher global verweigert
        new_text = entry["text"]
        done_for_file = 0
        for pat in entry["patterns"]:
            if pat["status"] != "plan":
                continue
            new_text = new_text.replace(pat["old"], pat["new"])
            done_for_file += pat["count_old"]
        backup_rel = f"{entry['rel']}.pre_e06.bak.{timestamp}"
        backup_path = REPO_ROOT / backup_rel
        shutil.copy2(entry["path"], backup_path)
        with open(entry["path"], "w", encoding="utf-8", newline="") as fh:
            fh.write(new_text)
        # Verifikation nach Schreibvorgang (Fail-Safe mit Rollback)
        with open(entry["path"], "r", encoding="utf-8", newline="") as fh:
            check_text = fh.read()
        ok = True
        for pat in entry["patterns"]:
            if pat["status"] != "plan":
                continue
            if check_text.count(pat["old"]) != 0:
                ok = False
                print(
                    f"  FEHLER: Altpfad {pat['old']!r} nach Apply noch in "
                    f"{entry['rel']} vorhanden!"
                )
            if check_text.count(pat["new"]) < pat["expected"]:
                ok = False
                print(
                    f"  FEHLER: Zielpfad-Trefferzahl zu gering in "
                    f"{entry['rel']} ({pat['new']!r})."
                )
        if not ok:
            shutil.copy2(backup_path, entry["path"])
            print(f"  ROLLBACK: {entry['rel']} aus {backup_rel} wiederhergestellt.")
            return 2
        changed_files += 1
        total_done += done_for_file
        print(
            f"  Geändert: {entry['rel']} – {done_for_file} Ersetzung(en) | "
            f"Backup: {backup_rel}"
        )
    print()
    print(
        f"APPLY abgeschlossen: {changed_files} Datei(en) geändert, "
        f"{total_done} Ersetzung(en) durchgeführt."
    )
    print("Backups (*.pre_e06.bak.*) liegen neben den Originaldateien.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="e06_path_deprecation_dryrun.py",
        description=(
            "E06 Altpfad-Stilllegung (BACH-Task #1424): Ersetzt validierte "
            "'skills/_...' Altpfad-Vorkommen in genau 3 Dateien. "
            "Default: PREVIEW ohne Änderungen. "
            "Apply nur nach Nutzer-Freigabe mit '--apply --confirm'."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Ersetzungen tatsächlich durchführen (erfordert zusätzlich --confirm).",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Explizite Bestätigung für --apply (Task ist USER-gated).",
    )
    args = parser.parse_args(argv)

    print(f"Repo-Root : {REPO_ROOT}")
    print(f"Modus     : {'APPLY' if args.apply else 'PREVIEW (keine Änderungen)'}")
    print()
    results = analyze()
    print_report(results)

    counts = {}
    for entry in results:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    planned_total = sum(
        pat["count_old"]
        for entry in results
        for pat in entry["patterns"]
        if pat and pat["status"] == "plan"
    )
    print()
    print("-" * 72)
    print(
        f"Datei-Status: PLAN OK {counts.get('plan', 0)} | "
        f"BEREITS MIGRIERT {counts.get('migrated', 0)} | "
        f"MISMATCH {counts.get('mismatch', 0)} | FEHLER {counts.get('error', 0)}"
    )
    print(f"Geplante Ersetzungen gesamt: {planned_total}")
    print(
        "Hinweis: skills/_services ist KEIN Stilllegungskandidat und wird "
        "von diesem Skript nicht angetastet."
    )
    print("-" * 72)

    validation_failed = bool(counts.get("mismatch", 0) or counts.get("error", 0))

    if not args.apply:
        print()
        print("PREVIEW: Es wurden KEINE Dateien geändert.")
        print("Ausführung nach Nutzer-Freigabe (Briefing) mit:")
        print(
            "    python3 tools/maintenance/e06_path_deprecation_dryrun.py "
            "--apply --confirm"
        )
        return 2 if validation_failed else 0

    if not args.confirm:
        print()
        print("ABGELEHNT: '--apply' wurde ohne zusätzliches '--confirm' angegeben.")
        print("Es wurden KEINE Dateien geändert.")
        print(
            "Hintergrund: Task #1424 ist USER-gated. Der Apply erfordert die "
            "explizite Freigabe durch den Nutzer."
        )
        print("Nach Freigabe ausführen:")
        print(
            "    python3 tools/maintenance/e06_path_deprecation_dryrun.py "
            "--apply --confirm"
        )
        return 1

    if validation_failed:
        print()
        print(
            "APPLY VERWEIGERT: Trefferzahl-Validierung fehlgeschlagen "
            "(MISMATCH/FEHLER, siehe oben)."
        )
        print("Es wurden KEINE Dateien geändert.")
        print("Trefferlage prüfen (z.B. search_text 'skills/_' auf die 3 Dateien)")
        print("und ggf. Erwartungswerte in REPLACEMENTS korrigieren.")
        return 2

    print()
    print("Starte APPLY (Backup je Datei, Verifikation nach jedem Schreibvorgang) ...")
    rc = apply_changes(results)
    if rc == 0:
        print()
        print("Empfohlener Verifikations-Lauf:")
        print(
            "    pytest tests/test_tuev_handler.py tests/test_context_injector_db.py"
        )
    return rc


if __name__ == "__main__":
    sys.exit(main())