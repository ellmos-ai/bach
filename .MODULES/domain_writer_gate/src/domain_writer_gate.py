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
Gate fuer Domaenen, die BACH nicht mehr besitzt
===============================================

MediPlaner V5 und Routinika sind ratifizierte Kanons. BACH liest ihre
Faelligkeiten ueber read-only Projektionen (sqlite-transit-sync) und schreibt
ausschliesslich noch seinen eigenen Reminder-/Zustellstatus. Was es NICHT mehr
tut: Medikamente und Routinen selbst anlegen oder aendern -- das waere ein
zweiter Datenkanon neben dem der App, und zwei Kanons driften.

Der Code dafuer ist trotzdem noch da, und er ist nicht nutzlos: fuer eine
einmalige Altbestandsuebernahme braucht man ihn. Deshalb wird er nicht geloescht,
sondern GEGATET -- ausdruecklich ausserhalb des Normalbetriebs (Auftrag
T-20260822-624075478, Punkt 3).

Vertrag, wie bei den Provider-Seams (MODE-CONTRACT.md):

    Schalter nicht gesetzt  =>  klare Absage mit Begruendung.
    NIEMALS still durchlassen, niemals halb schreiben.

Der Schalter ist bewusst eine Umgebungsvariable und keine Konfigurationsdatei:
Eine Legacy-Migration ist ein einzelner, bewusster Lauf, kein Zustand, den eine
Installation dauerhaft traegt. Wer ihn setzt, tut das fuer einen Aufruf.

    BACH_LEGACY_DOMAIN_WRITES=1 python bach.py mediplaner import --file …

Benutzung an einer Schreibstelle:

    reason = blocked_reason("medication", "gesundheit add-med")
    if reason:
        return False, reason
"""

import os
from typing import Optional

#: Opt-in fuer den einmaligen Altbestands-Import. Absichtlich nicht in der
#: Konfiguration -- siehe Modul-Doku.
LEGACY_WRITE_ENV = "BACH_LEGACY_DOMAIN_WRITES"

_TRUE_VALUES = {"1", "true", "yes", "on"}

#: Domaene -> (Kanon, wo der Bestand wirklich lebt, woher BACH ihn liest)
_DOMAINS = {
    "medication": (
        "MediPlaner V5",
        "Medikamente, Einnahmeplaene und Arztkontakte",
        "org.ellmos.mediplaner.reminder-projection",
    ),
    "routine": (
        "Routinika",
        "Routinen und ihre Abschluesse",
        "org.ellmos.routinika.reminder-projection",
    ),
}


def legacy_domain_writes_enabled(environ: Optional[dict] = None) -> bool:
    """True, wenn dieser Lauf ausdruecklich als Altbestands-Migration laeuft."""
    source = os.environ if environ is None else environ
    return (source.get(LEGACY_WRITE_ENV) or "").strip().lower() in _TRUE_VALUES


def blocked_reason(
    domain: str, operation: str, environ: Optional[dict] = None
) -> Optional[str]:
    """Gibt die Absage-Begruendung zurueck -- oder None, wenn geschrieben werden darf.

    `domain` muss eine bekannte Domaene sein. Ein Tippfehler darf nicht dazu
    fuehren, dass ein Schreibpfad ungewollt offen ist, deshalb ist ein
    unbekannter Name ein Fehler und kein stilles "erlaubt".
    """
    if domain not in _DOMAINS:
        raise ValueError(
            f"Unbekannte Domaene {domain!r} -- bekannt: {', '.join(sorted(_DOMAINS))}"
        )
    if legacy_domain_writes_enabled(environ):
        return None

    owner, what, contract = _DOMAINS[domain]
    return (
        f"[GESPERRT] '{operation}' schreibt {what} -- diese Domaene gehoert "
        f"{owner}, nicht BACH.\n"
        f"BACH konsumiert sie read-only ueber die Projektion {contract}; "
        f"selbst zu schreiben erzeugt einen zweiten Datenkanon.\n"
        f"Fuer eine einmalige Altbestandsuebernahme ausserhalb des Normalbetriebs:\n"
        f"  {LEGACY_WRITE_ENV}=1 <befehl>\n"
        f"(Auftrag T-20260822-624075478, Punkt 3)"
    )


def known_domains() -> tuple[str, ...]:
    """Die gegateten Domaenen -- fuer Tests und Selbstauskunft."""
    return tuple(sorted(_DOMAINS))
