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
Gate fuer Source-of-Truth-Wechsel (BACH20-08)
============================================

BACH traegt pro Modul genau einen Source of Truth. Ab BACH20 wandern Module
in die externen Apps -- die sechs Schalter der V4-Whitelist sind die
Pflichtmenge, die fuenf Module des Auftrags sind die Teilmenge. Ein
Wechsel ist der schwerste Eingriff, den das System kennt. Deshalb gibt es
dieses Gate: Es entscheidet den Wechsel nicht, es verweigert ihn, solange
auch nur ein Stein im Fundament wackelt.

Vertrag, nummeriert (definierend):

    (1) Fail-Closed. Ohne vollstaendigen gruenen Nachweis gibt es kein
        erlaubtes Wechseln. Fehlende Dateien, defekte Zeilen, leere
        Schalter -- alles blockiert, nichts wird geratet.

    (2) Der Nachweis folgt BACH20-06 §3: fuenf Gates gruen, keine offenen
        Hostlaeufe. Er liegt als Datei unter evidence/<modul>/<stufe>.json.

    (3) Der Rollback-Schalter des Moduls (MODULRUECKTRANSFER-PLAN §4
        Regel 1) wird bei jedem Aufruf live gelesen, niemals gecacht.
        Ist er abwesend oder steht er auf Aus (0/false/no/off), blockiert
        das Gate.

    (4) Stufenfolge pro Modul ist P0 -> P2 -> P3 -> P4 (BACH20-06 §4),
        single-writer: Der letzte offene Journal-Eintrag einer Kombination
        blockiert ALLE Module, nicht nur das eigene.

    (5) Tippfehler in Modul oder Stufe fuhren zu ValueError -- ein
        unbekannter Name ist keine Meinung, sondern ein Fehler.

Und wie bei jedem Schalter des Systems (MODE-CONTRACT.md):

    Schalter nicht gesetzt  =>  klare Absage mit Begruendung.
    NIEMALS still durchlassen, niemals halb schreiben.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

BACH_ROOT = Path(__file__).resolve().parents[2]

#: Wo die Nachweise liegen (BACH20-06 §3): evidence/<modul>/<stufe>.json.
DEFAULT_EVIDENCE_DIR = BACH_ROOT / "data" / "state" / "sot-gate" / "evidence"

#: Append-only Journal des Gates (offen/gruen je Modul und Stufe).
DEFAULT_JOURNAL_PATH = BACH_ROOT / "data" / "state" / "sot-gate" / "journal.jsonl"

#: Modul -> Rollback-Schalter (MODULRUECKTRANSFER-PLAN §4 Regel 1).
#: Sechs Eintraege: die Pflichtmenge der V4-Whitelist. Die fuenf Module
#: des BACH20-Auftrags sind die Teilmenge, agent_registry kommt dazu.
SOT_MODULES = {
    "scheduler": "BACH_USE_EXTERNAL_SCHEDULER",
    "explorer": "BACH_USE_EXTERNAL_EXPLORER",
    "memoryhooks": "BACH_USE_EXTERNAL_MEMORYHOOKS",
    "workflowhooks": "BACH_USE_EXTERNAL_WORKFLOWHOOKS",
    "transitsync": "BACH_USE_EXTERNAL_TRANSITSYNC",
    "agent_registry": "BACH_USE_EXTERNAL_AGENT_REGISTRY",
}

#: Stufenfolge des Wechsels, analog der BACH20-06 §4-Matrix. P0 zuerst.
SOT_STAGES = ("P0", "P2", "P3", "P4")

#: Werte, die den Rollback erzwungen bedeuten (kleingeschrieben geprueft).
_ROLLBACK_OFF_VALUES = {"0", "false", "no", "off"}

#: Die fuenf Gates des Nachweises (BACH20-06 §3).
_GATE_KEYS = tuple("gate_{}".format(i) for i in range(1, 6))

#: Gueltige Statuswerte im Journal. Alles andere blockiert (Punkt 1).
_JOURNAL_STATUSES = ("offen", "gruen")


@dataclass(frozen=True)
class SotSwitchProbe:
    """Ergebnis einer Anfrage ans Gate. reasons ist leer genau dann, wenn allowed."""

    allowed: bool
    modul: str
    stufe: str
    reasons: tuple[str, ...]


def _validate(modul: str, stufe: str) -> None:
    """Punkt (5): Unbekannte Namen raisen, statt still falsch zu entscheiden."""
    if modul not in SOT_MODULES:
        raise ValueError(
            "Unbekanntes SoT-Modul {!r}. Bekannte Module: {}".format(
                modul, ", ".join(sorted(SOT_MODULES))
            )
        )
    if stufe not in SOT_STAGES:
        raise ValueError(
            "Unbekannte Stufe {!r}. Bekannte Stufen: {}".format(
                stufe, ", ".join(SOT_STAGES)
            )
        )


def _rollback_reasons(modul: str, environ: dict) -> list[str]:
    """Punkt (3): Rollback-Schalter live lesen, fail-closed bewerten."""
    var = SOT_MODULES[modul]
    raw = environ.get(var)
    if raw is None:
        return [
            "Rollback-Schalter {} ist nicht gesetzt: kein Wechsel moeglich "
            "(MODULRUECKTRANSFER-PLAN §4 Regel 1)".format(var)
        ]
    value = raw.strip().lower()
    if value == "":
        return [
            "Rollback-Schalter {} ist leer gesetzt: kein Wechsel moeglich "
            "(Fail-Closed)".format(var)
        ]
    if value in _ROLLBACK_OFF_VALUES:
        return [
            "Rollback-Schalter {} steht auf Aus ({!r}): Ruecktransfer "
            "erzwungen, kein Wechsel moeglich".format(var, raw)
        ]
    return []


def _gate_reasons(path: Path, key: str, gate: object) -> list[str]:
    """Ein einzelnes Gate des Nachweises pruefen (BACH20-06 §3)."""
    if gate is None:
        return ["Nachweis {}: {} fehlt".format(path, key)]
    if not isinstance(gate, dict):
        return ["Nachweis {}: {} ist kein Objekt".format(path, key)]
    reasons: list[str] = []
    if gate.get("status") != "gruen":
        reasons.append(
            "Nachweis {}: {} status ist {!r}, erwartet 'gruen' "
            "(BACH20-06 §3)".format(path, key, gate.get("status"))
        )
    for field in ("host", "timestamp"):
        value = gate.get(field)
        if not isinstance(value, str) or not value.strip():
            reasons.append(
                "Nachweis {}: {} {} ist {!r}, keine nicht-leere "
                "Zeichenkette".format(path, key, field, value)
            )
    exit_code = gate.get("exit_code")
    if isinstance(exit_code, bool):
        # bool ist eine Subklasse von int -- deshalb der bool-Test zuerst.
        reasons.append(
            "Nachweis {}: {} exit_code ist ein Boolean ({!r}), keine "
            "Ganzzahl".format(path, key, exit_code)
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


def _evidence_reasons(modul: str, stufe: str, evidence_dir: Path) -> list[str]:
    """Punkt (2): Nachweis nach BACH20-06 §3 lesen und vollstaendig pruefen."""
    path = evidence_dir / modul / (stufe + ".json")
    if not path.is_file():
        return ["Nachweis fehlt: {}".format(path)]
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except ValueError:
        return ["Nachweis {} ist kein gueltiges JSON".format(path)]
    if not isinstance(doc, dict):
        return ["Nachweis {} ist kein JSON-Objekt".format(path)]

    reasons: list[str] = []
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
    if laeufe is None:
        reasons.append("Nachweis {}: offene_hostlaeufe fehlt".format(path))
    elif not isinstance(laeufe, list):
        reasons.append("Nachweis {}: offene_hostlaeufe ist keine Liste".format(path))
    elif laeufe:
        reasons.append(
            "Nachweis {}: offene_hostlaeufe nicht leer ({}): offene Hostlaeufe "
            "heissen nach BACH20-06 §3 nicht gruen".format(path, laeufe)
        )

    gates = doc.get("gates")
    if gates is None:
        reasons.append("Nachweis {}: gates fehlt".format(path))
    elif not isinstance(gates, dict):
        reasons.append("Nachweis {}: gates ist kein Objekt".format(path))
    else:
        if set(gates) != set(_GATE_KEYS):
            reasons.append(
                "Nachweis {}: gates enthaelt {} statt {}".format(
                    path, sorted(gates), list(_GATE_KEYS)
                )
            )
        for key in _GATE_KEYS:
            reasons.extend(_gate_reasons(path, key, gates.get(key)))
    return reasons


def _read_journal(
    journal_path: Path,
) -> tuple[list[str], list[tuple[str, str, str]], bool]:
    """Journal lesen. Ungueltige Zeilen werden zu Gruenden (Punkt 1).

    Rueckgabe: (reasons, entries, exists). entries enthaelt nur gueltige
    Zeilen als (modul, stufe, status). Das Journal ist append-only, also
    zaehlt bei der Auswertung der LETZTE Eintrag einer Kombination.
    """
    if not journal_path.is_file():
        return [], [], False
    reasons: list[str] = []
    entries: list[tuple[str, str, str]] = []
    with open(journal_path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            text = line.strip()
            if not text:
                reasons.append(
                    "Journal Zeile {}: leere Zeile ist ungueltig".format(lineno)
                )
                continue
            try:
                doc = json.loads(text)
            except ValueError:
                reasons.append("Journal Zeile {}: kein gueltiges JSON".format(lineno))
                continue
            if not isinstance(doc, dict):
                reasons.append("Journal Zeile {}: kein JSON-Objekt".format(lineno))
                continue
            modul = doc.get("modul")
            stufe = doc.get("stufe")
            status = doc.get("status")
            if modul not in SOT_MODULES:
                reasons.append(
                    "Journal Zeile {}: unbekanntes Modul {!r}".format(lineno, modul)
                )
                continue
            if stufe not in SOT_STAGES:
                reasons.append(
                    "Journal Zeile {}: unbekannte Stufe {!r}".format(lineno, stufe)
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


def _last_statuses(
    entries: list[tuple[str, str, str]],
) -> dict[tuple[str, str], str]:
    """Letzter Status je (modul, stufe). Spaetere Eintraege gewinnen."""
    last: dict[tuple[str, str], str] = {}
    for modul, stufe, status in entries:
        last[(modul, stufe)] = status
    return last


def _append_journal(
    modul: str,
    stufe: str,
    status: str,
    *,
    host: str,
    timestamp: str,
    journal_path: Path,
) -> None:
    """Einen Eintrag ans Journal anhaengen (append-only, sortierte Keys)."""
    path = Path(journal_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "modul": modul,
        "stufe": stufe,
        "status": status,
        "host": host,
        "timestamp": timestamp,
    }
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def probe_sot_switch(
    modul: str,
    stufe: str,
    *,
    environ: dict | None = None,
    evidence_dir: Path | str | None = None,
    journal_path: Path | str | None = None,
) -> SotSwitchProbe:
    """Anfrage: Darf <modul> auf Stufe <stufe> nach extern wechseln?

    Erlaubt nur, wenn der Rollback-Schalter des Moduls gesetzt und an ist,
    der Nachweis vollstaendig gruen ist, das Journal keine offenen
    Eintraege kennt und alle Vorgaenger-Stufen des Moduls gruen sind.
    Jeder Verstoss gegen eine dieser Bedingungen liefert allowed=False
    samt Grund.
    """
    _validate(modul, stufe)
    env = os.environ if environ is None else environ
    ev_dir = Path(evidence_dir) if evidence_dir is not None else DEFAULT_EVIDENCE_DIR
    j_path = Path(journal_path) if journal_path is not None else DEFAULT_JOURNAL_PATH

    reasons: list[str] = []
    reasons.extend(_rollback_reasons(modul, env))
    reasons.extend(_evidence_reasons(modul, stufe, ev_dir))

    journal_reasons, entries, exists = _read_journal(j_path)
    reasons.extend(journal_reasons)

    if not exists:
        # Ohne Journal ist nur die erste Stufe moeglich -- die Stufenfolge
        # aus Punkt (4) braucht einen dokumentierten Anfang.
        if stufe != SOT_STAGES[0]:
            reasons.append(
                "Journal fehlt: ohne Journal ist nur die erste Stufe {} "
                "moeglich".format(SOT_STAGES[0])
            )
    else:
        last = _last_statuses(entries)
        for (m, s), status in sorted(
            last.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))
        ):
            if status != "gruen":
                reasons.append(
                    "Offener Wechsel fuer {}/{} im Journal blockiert ALLE "
                    "Module (single-writer, BACH20-08)".format(m, s)
                )
        stufe_index = SOT_STAGES.index(stufe)
        for vorgaenger in SOT_STAGES[:stufe_index]:
            if last.get((modul, vorgaenger)) != "gruen":
                reasons.append(
                    "Vorgaenger-Stufe {} fuer {} ist im Journal nicht gruen "
                    "(BACH20-06 §4 Stufenfolge)".format(vorgaenger, modul)
                )

    return SotSwitchProbe(
        allowed=not reasons, modul=modul, stufe=stufe, reasons=tuple(reasons)
    )


def record_switch(
    modul: str,
    stufe: str,
    *,
    host: str,
    timestamp: str,
    journal_path: Path | str | None = None,
    evidence_dir: Path | str | None = None,
    environ: dict | None = None,
) -> SotSwitchProbe:
    """Wechsel als offen ins Journal schreiben -- nur wenn die Probe erlaubt.

    Die Rueckgabe IST die Probe: allowed=True heisst, der offen-Eintrag
    steht jetzt im Journal. allowed=False heisst, es wurde nichts
    geschrieben.
    """
    _validate(modul, stufe)
    j_path = Path(journal_path) if journal_path is not None else DEFAULT_JOURNAL_PATH
    probe = probe_sot_switch(
        modul,
        stufe,
        environ=environ,
        evidence_dir=evidence_dir,
        journal_path=j_path,
    )
    if probe.allowed:
        _append_journal(
            modul, stufe, "offen", host=host, timestamp=timestamp, journal_path=j_path
        )
    return probe


def confirm_green(
    modul: str,
    stufe: str,
    *,
    host: str,
    timestamp: str,
    journal_path: Path | str | None = None,
    evidence_dir: Path | str | None = None,
) -> SotSwitchProbe:
    """Offenen Eintrag gruen faerben -- nur mit intaktem Nachweis.

    Ohne environ-Parameter: Das Bestaetigen ist Verwaltung, kein Wechsel;
    der Rollback-Schalter gehoert zur Wechsel-Anfrage, nicht hierher.
    Erlaubt nur, wenn der Nachweis vollstaendig gruen ist und der letzte
    Status von (modul, stufe) im Journal 'offen' ist.
    """
    _validate(modul, stufe)
    ev_dir = Path(evidence_dir) if evidence_dir is not None else DEFAULT_EVIDENCE_DIR
    j_path = Path(journal_path) if journal_path is not None else DEFAULT_JOURNAL_PATH

    reasons: list[str] = list(_evidence_reasons(modul, stufe, ev_dir))
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
        _append_journal(
            modul, stufe, "gruen", host=host, timestamp=timestamp, journal_path=j_path
        )
    return SotSwitchProbe(
        allowed=not reasons, modul=modul, stufe=stufe, reasons=tuple(reasons)
    )