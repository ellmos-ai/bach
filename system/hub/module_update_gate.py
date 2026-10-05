# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
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
Gate fuer unabhaengige Modulupdates (BACH20-10)
===============================================

Die konsumierten Ocean-Module werden unabhaengig voneinander aktualisiert:
Jedes Update ist an einen Pin (Commit und Version) und den Manifest-Hash
gebunden (BACH20-10 §1), laeuft gestaffelt ueber die Stufen stage, gate und
activate (BACH20-10 §2) und sichert vor dem Aktivieren drei getrennte
Rollback-Nachweise (BACH20-10 §3). Dieses Gate entscheidet fail-closed:
Nur ein vollstaendig intakter Nachweis und ein sauberes Journal lassen
eine Anfrage durch.

Vertrag, nummeriert (definierend):

    1. Fail-Closed: Eine Anfrage wird nur erlaubt, wenn alle Nachweise
       intakt sind und das Journal keinen Konflikt zeigt. Im Zweifel gilt
       die Absage; bei einer Absage schreibt das Gate niemals.

    2. Der Nachweis folgt BACH20-06 §3: fuenf Gates gruen, keine offenen
       Hostlaeufe. Er liegt als Datei unter evidence/<modul>/<stufe>.json.
       Zusaetzlich muessen pin und manifest_hash stimmen (BACH20-10 §1)
       fuer die Stufen stage und activate.

    3. Statt eines Rollback-Schalters (BACH20-08 Punkt 3) gilt hier die
       Pin/Hash-Sicherung (BACH20-10 §1): pin im Format '<commit>/vX.Y.Z',
       manifest_hash 64 Klein-Hex (SHA-256).

    4. Stufenfolge pro Modul ist stage -> gate -> activate (BACH20-10 §2),
       single-writer: Der letzte offene Journal-Eintrag einer Kombination
       blockiert ALLE Module, nicht nur das eigene.

    5. Unbekannte Module oder Stufen sind Programmierfehler und werfen
       ValueError, keine Absage.

Und wie bei jedem Schalter des Systems (MODE-CONTRACT.md):

    Schalter nicht gesetzt  =>  klare Absage mit Begruendung.
    NIEMALS still durchlassen, niemals halb schreiben.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

BACH_ROOT = Path(__file__).resolve().parents[2]

#: Wo die Nachweise liegen (BACH20-06 §3): evidence/<modul>/<stufe>.json.
DEFAULT_EVIDENCE_DIR = BACH_ROOT / "data" / "state" / "modul-update-gate" / "evidence"

#: Append-only Journal des Gates (offen/gruen je Modul und Stufe).
DEFAULT_JOURNAL_PATH = BACH_ROOT / "data" / "state" / "modul-update-gate" / "journal.jsonl"

#: Pflichtmenge der V4-Whitelist (Vorlage SOT_MODULES).
UPDATE_MODULES = {
    "scheduler",
    "explorer",
    "memoryhooks",
    "workflowhooks",
    "transitsync",
    "agent_registry",
}

#: Stufenfolge des Updates (BACH20-10 §2). stage zuerst.
UPDATE_STAGES = ("stage", "gate", "activate")

#: pin-Format (BACH20-10 §1): <commit>/vX.Y.Z.
_PIN_PATTERN = re.compile(r"^[0-9a-f]{8,40}/v\d+\.\d+\.\d+$")

#: manifest_hash (BACH20-10 §1): SHA-256 als 64 Klein-Hex.
_HASH64_PATTERN = re.compile(r"^[0-9a-f]{64}$")

#: Die drei Rollback-Nachweise (BACH20-10 §3).
_ROLLBACK_FILES = ("rollback_code", "rollback_manifest", "rollback_daten")

#: Die fuenf Gates des Nachweises (BACH20-06 §3).
_GATE_KEYS = tuple("gate_{}".format(i) for i in range(1, 6))

#: Gueltige Statuswerte im Journal. Alles andere blockiert (Punkt 1).
_JOURNAL_STATUSES = ("offen", "gruen")


@dataclass
class ModuleUpdateProbe:
    """Ergebnis einer Anfrage ans Gate. reasons ist leer genau dann, wenn allowed."""

    allowed: bool
    modul: str
    stufe: str
    reasons: tuple


def _validate(modul, stufe):
    """Unbekannte Module/Stufen sind Programmierfehler (Punkt 5)."""
    if modul not in UPDATE_MODULES:
        raise ValueError(
            "Unbekanntes Update-Modul {!r}. Bekannte Module: {}".format(
                modul, ", ".join(sorted(UPDATE_MODULES))
            )
        )
    if stufe not in UPDATE_STAGES:
        raise ValueError(
            "Unbekannte Stufe {!r}. Bekannte Stufen: {}".format(
                stufe, ", ".join(UPDATE_STAGES)
            )
        )


def _gate_reasons(path, key, gate):
    """Gruende, warum ein einzelnes Gate des Nachweises nicht gruen ist."""
    if gate is None:
        return ["Nachweis {}: {} fehlt".format(path, key)]
    if not isinstance(gate, dict):
        return ["Nachweis {}: {} ist kein Objekt".format(path, key)]
    reasons = []
    status = gate.get("status")
    if status != "gruen":
        reasons.append(
            "Nachweis {}: {} status ist {!r}, erwartet 'gruen' (BACH20-06 §3)".format(
                path, key, status
            )
        )
    for feld in ("host", "timestamp"):
        value = gate.get(feld)
        if not isinstance(value, str) or not value.strip():
            reasons.append(
                "Nachweis {}: {} {} ist {!r}, keine nicht-leere Zeichenkette".format(
                    path, key, feld, value
                )
            )
    exit_code = gate.get("exit_code")
    # bool ist eine Subklasse von int -- deshalb der bool-Test zuerst.
    if isinstance(exit_code, bool):
        reasons.append(
            "Nachweis {}: {} exit_code ist ein Boolean ({!r}), keine Ganzzahl".format(
                path, key, exit_code
            )
        )
    elif not isinstance(exit_code, int):
        reasons.append(
            "Nachweis {}: {} exit_code ist {!r}, keine Ganzzahl".format(
                path, key, exit_code
            )
        )
    elif exit_code != 0:
        reasons.append(
            "Nachweis {}: {} exit_code ist {} statt 0".format(path, key, exit_code)
        )
    return reasons


def _pin_hash_reasons(path, doc):
    """Gruende, warum pin/manifest_hash nicht stimmen (BACH20-10 §1, Punkt 3)."""
    reasons = []
    pin = doc.get("pin")
    if not isinstance(pin, str) or not _PIN_PATTERN.match(pin):
        reasons.append(
            "Nachweis {}: pin ist {!r}, erwartet Format '<commit>/vX.Y.Z' "
            "(BACH20-10 §1)".format(path, pin)
        )
    h = doc.get("manifest_hash")
    if not isinstance(h, str) or not _HASH64_PATTERN.match(h):
        reasons.append(
            "Nachweis {}: manifest_hash ist {!r}, erwartet 64 Klein-Hex "
            "(SHA-256)".format(path, h)
        )
    return reasons


def _evidence_reasons(modul, stufe, evidence_dir):
    """Gruende, warum der Nachweis fuer (modul, stufe) nicht gruen ist (Punkt 2)."""
    path = evidence_dir / modul / (stufe + ".json")
    if not path.exists():
        return ["Nachweis fehlt: {}".format(path)]
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except ValueError:
        return ["Nachweis {} ist kein gueltiges JSON".format(path)]
    if not isinstance(doc, dict):
        return ["Nachweis {} ist kein JSON-Objekt".format(path)]
    reasons = []
    if doc.get("modul") != modul:
        reasons.append(
            "Nachweis {}: modul ist {!r}, erwartet {!r}".format(
                path, doc.get("modul"), modul
            )
        )
    if doc.get("stufe") != stufe:
        reasons.append(
            "Nachweis {}: stufe ist {!r}, erwartet {!r}".format(
                path, doc.get("stufe"), stufe
            )
        )
    laeufe = doc.get("offene_hostlaeufe")
    if not isinstance(laeufe, list):
        reasons.append(
            "Nachweis {}: offene_hostlaeufe ist {!r}, keine Liste".format(path, laeufe)
        )
    elif laeufe:
        reasons.append(
            "Nachweis {}: offene_hostlaeufe nicht leer ({}): offene Hostlaeufe "
            "heissen nach BACH20-06 §3 nicht gruen".format(path, laeufe)
        )
    gates = doc.get("gates")
    if not isinstance(gates, dict):
        reasons.append("Nachweis {}: gates ist {!r}, kein Objekt".format(path, gates))
    else:
        if set(gates) != set(_GATE_KEYS):
            reasons.append(
                "Nachweis {}: gates enthaelt {} statt {}".format(
                    path, sorted(gates), list(_GATE_KEYS)
                )
            )
        for key in _GATE_KEYS:
            reasons.extend(_gate_reasons(path, key, gates.get(key)))
    if stufe in ("stage", "activate"):
        reasons.extend(_pin_hash_reasons(path, doc))
    return reasons


def _rollback_evidence_reasons(modul, evidence_dir):
    """Gruende, warum die drei Rollback-Nachweise (BACH20-10 §3) nicht gruen sind."""
    ev_dir = evidence_dir / modul
    reasons = []
    for name in _ROLLBACK_FILES:
        path = ev_dir / (name + ".json")
        if not path.exists():
            reasons.append("Rollback-Nachweis fehlt: {}".format(path))
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except ValueError:
            reasons.append(
                "Rollback-Nachweis {} ist kein gueltiges JSON".format(path)
            )
            continue
        if not isinstance(doc, dict):
            reasons.append("Rollback-Nachweis {} ist kein JSON-Objekt".format(path))
            continue
        if doc.get("modul") != modul:
            reasons.append(
                "Rollback-Nachweis {}: modul ist {!r}, erwartet {!r}".format(
                    path, doc.get("modul"), modul
                )
            )
        if doc.get("status") != "gruen":
            reasons.append(
                "Rollback-Nachweis {}: status ist {!r}, erwartet 'gruen' "
                "(BACH20-10 §3)".format(path, doc.get("status"))
            )
        for feld in ("host", "timestamp"):
            if not isinstance(doc.get(feld), str) or not doc.get(feld).strip():
                reasons.append(
                    "Rollback-Nachweis {}: {} ist {!r}, keine nicht-leere "
                    "Zeichenkette".format(path, feld, doc.get(feld))
                )
    return reasons


def _read_journal(journal_path):
    """Journal lesen. Gibt (reasons, entries, exists) zurueck."""
    if not journal_path.exists():
        return [], [], False
    reasons = []
    entries = []
    with open(journal_path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                reasons.append(
                    "Journal Zeile {}: leere Zeile ist ungueltig".format(lineno)
                )
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                reasons.append(
                    "Journal Zeile {}: kein gueltiges JSON".format(lineno)
                )
                continue
            if not isinstance(entry, dict):
                reasons.append("Journal Zeile {}: kein JSON-Objekt".format(lineno))
                continue
            modul = entry.get("modul")
            stufe = entry.get("stufe")
            status = entry.get("status")
            if modul not in UPDATE_MODULES:
                reasons.append(
                    "Journal Zeile {}: modul {!r} ist kein bekanntes "
                    "Update-Modul".format(lineno, modul)
                )
                continue
            if stufe not in UPDATE_STAGES:
                reasons.append(
                    "Journal Zeile {}: stufe {!r} ist keine bekannte "
                    "Stufe".format(lineno, stufe)
                )
                continue
            if status not in _JOURNAL_STATUSES:
                reasons.append(
                    "Journal Zeile {}: status {!r} ist weder 'offen' noch "
                    "'gruen'".format(lineno, status)
                )
                continue
            entries.append((modul, stufe, status))
    return reasons, entries, True


def _last_statuses(entries):
    """Letzter Status je (modul, stufe). Spaetere Eintraege gewinnen."""
    last = {}
    for modul, stufe, status in entries:
        last[(modul, stufe)] = status
    return last


def _append_journal(modul, stufe, status, *, host, timestamp, journal_path):
    """Einen Eintrag ans Journal anhaengen (append-only)."""
    record = {
        "modul": modul,
        "stufe": stufe,
        "status": status,
        "host": host,
        "timestamp": timestamp,
    }
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    with open(journal_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def probe_module_update(modul, stufe, *, evidence_dir=None, journal_path=None):
    """Anfrage ans Gate: Darf <modul> die Stufe <stufe> betreten?

    Prueft den Nachweis (Punkte 2 und 3) und das Journal (Punkt 4).
    Schreibt NIEMALS.
    """
    _validate(modul, stufe)
    ev_dir = Path(evidence_dir) if evidence_dir is not None else DEFAULT_EVIDENCE_DIR
    j_path = Path(journal_path) if journal_path is not None else DEFAULT_JOURNAL_PATH
    reasons = list(_evidence_reasons(modul, stufe, ev_dir))
    journal_reasons, entries, exists = _read_journal(j_path)
    reasons.extend(journal_reasons)
    if not exists:
        # Ohne Journal kann kein Eintrag blockieren (Punkt 4) -- aber es gibt
        # auch keinen gruenen Vorgaenger, also ist nur der Einstieg moeglich.
        if stufe != UPDATE_STAGES[0]:
            reasons.append(
                "Journal fehlt: ohne Journal ist nur die erste Stufe {} "
                "moeglich".format(UPDATE_STAGES[0])
            )
    else:
        last = _last_statuses(entries)
        for (m, s), status in sorted(
            last.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))
        ):
            if status == "offen":
                reasons.append(
                    "Offener Wechsel fuer {}/{} im Journal blockiert ALLE Module "
                    "(single-writer, BACH20-10 §2)".format(m, s)
                )
        stufe_index = UPDATE_STAGES.index(stufe)
        for vorgaenger in UPDATE_STAGES[:stufe_index]:
            if last.get((modul, vorgaenger)) != "gruen":
                reasons.append(
                    "Vorgaenger-Stufe {} fuer {} ist im Journal nicht gruen "
                    "(BACH20-10 §2 Stufenfolge)".format(vorgaenger, modul)
                )
    return ModuleUpdateProbe(
        allowed=not reasons, modul=modul, stufe=stufe, reasons=tuple(reasons)
    )


def record_update(modul, stufe, *, host, timestamp, journal_path=None, evidence_dir=None):
    """Update als offen ins Journal schreiben -- nur wenn die Probe erlaubt.

    Die Rueckgabe IST die Probe: allowed=True heisst, der offen-Eintrag steht
    jetzt im Journal. allowed=False heisst, es wurde nichts geschrieben.
    """
    _validate(modul, stufe)
    j_path = Path(journal_path) if journal_path is not None else DEFAULT_JOURNAL_PATH
    probe = probe_module_update(
        modul, stufe, evidence_dir=evidence_dir, journal_path=j_path
    )
    if probe.allowed:
        _append_journal(
            modul, stufe, "offen", host=host, timestamp=timestamp, journal_path=j_path
        )
    return probe


def confirm_green(modul, stufe, *, evidence_dir=None, journal_path=None):
    """Offenen Eintrag gruen faerben -- nur mit intaktem Nachweis.

    Erlaubt nur, wenn der Nachweis vollstaendig gruen ist und der letzte
    Status von (modul, stufe) im Journal 'offen' ist.
    """
    _validate(modul, stufe)
    ev_dir = Path(evidence_dir) if evidence_dir is not None else DEFAULT_EVIDENCE_DIR
    j_path = Path(journal_path) if journal_path is not None else DEFAULT_JOURNAL_PATH
    reasons = list(_evidence_reasons(modul, stufe, ev_dir))
    journal_reasons, entries, exists = _read_journal(j_path)
    reasons.extend(journal_reasons)
    if not exists:
        reasons.append(
            "Journal fehlt: kein offener Eintrag fuer {}/{} zu "
            "bestaetigen".format(modul, stufe)
        )
    else:
        last = _last_statuses(entries)
        if last.get((modul, stufe)) != "offen":
            reasons.append(
                "Kein offener Eintrag fuer {}/{} im Journal: nichts zu "
                "bestaetigen".format(modul, stufe)
            )
    if not reasons:
        # Host und Zeitpunkt stehen im Nachweis: Das Bestaetigen ist
        # Verwaltung, es startet keinen eigenen Lauf.
        with open(ev_dir / modul / (stufe + ".json"), encoding="utf-8") as fh:
            lauf = json.load(fh)["gates"]["gate_1"]
        _append_journal(
            modul,
            stufe,
            "gruen",
            host=lauf["host"],
            timestamp=lauf["timestamp"],
            journal_path=j_path,
        )
    return ModuleUpdateProbe(
        allowed=not reasons, modul=modul, stufe=stufe, reasons=tuple(reasons)
    )


def rollback_module(modul, *, host, timestamp, evidence_dir=None):
    """Rollback-Verfuegbarkeit pruefen -- schreibt NIEMALS.

    Erlaubt nur, wenn alle drei Rollback-Nachweise (BACH20-10 §3) fuer <modul>
    intakt und gruen sind. host und timestamp sind Teil der Signatur nur der
    Form halber; es wird kein Journal-Eintrag geschrieben.
    """
    _validate(modul, "activate")
    ev_dir = Path(evidence_dir) if evidence_dir is not None else DEFAULT_EVIDENCE_DIR
    reasons = list(_rollback_evidence_reasons(modul, ev_dir))
    return ModuleUpdateProbe(
        allowed=not reasons, modul=modul, stufe="activate", reasons=tuple(reasons)
    )
