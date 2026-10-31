# -*- coding: utf-8 -*-
"""Diagnose-Test fuer Task #2178: Codex-Login-Status pruefen.

Sammelt Fakten (HOME, .codex-Verzeichnisse, auth.json-METADATEN,
codex-Binaer, `codex login status`, `codex --version`) und schreibt sie
in codex_login_bericht.txt neben dieser Datei; alles wird zusaetzlich
per print ausgegeben (pytest -s).

Bewusst KEINE Erfolg-/Misserfolg-Assertion fuer den Login: reine Diagnose.
auth.json wird NIEMALS gelesen (enthaelt Zugangsdaten); nur Existenz,
Groesse und mtime. `codex exec` wird NICHT aufgerufen (kein Modellstart).
"""
import datetime
import getpass
import os
import shutil
import subprocess

BERICHT_PFAD = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "codex_login_bericht.txt")
ZEILEN = []


def log(titel, *text):
    """Zeile(n) auf Konsole und in den Berichtspuffer schreiben."""
    block = [titel] + ["  " + t for t in text]
    for z in block:
        print(z)
    ZEILEN.extend(block)


def codex_subprocess(args):
    """Fuehrt `codex <args>` aus; liefert (Rueckgabecode, kombinierte Ausgabe)."""
    exe = shutil.which("codex")
    if not exe:
        return None, "codex-Binaerdatei nicht im PATH gefunden"
    try:
        p = subprocess.run([exe] + list(args),
                           capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return None, "Timeout (>30 s) bei Aufruf: codex " + " ".join(args)
    except OSError as e:
        return None, "OS-Fehler bei Aufruf: " + str(e)
    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    kombiniert = out + ("\n  [stderr] " + err if err else "")
    return p.returncode, kombiniert or "(keine Ausgabe)"


def test_codex_login_diagnose():
    # a) HOME
    home = os.path.expanduser("~")
    log("a) HOME")
    log("  HOME =", home)
    log("  os.environ['HOME'] =", os.environ.get("HOME", "(nicht gesetzt)"))
    log("  Aktueller Benutzer =", getpass.getuser())

    # b) .codex-Verzeichnisse (mehrere Kandidaten, nur Namen, nie Inhalte)
    kandidaten = [os.path.join(home, ".codex"), "/Users/buddha/.codex"]
    log("b) .codex-Verzeichnisse")
    for kand in kandidaten:
        if os.path.isdir(kand):
            try:
                eintraege = sorted(os.listdir(kand))
            except OSError as e:
                eintraege = ["(listdir fehlgeschlagen: " + str(e) + ")"]
            log("  " + kand + " EXISTIERT, Eintraege (" + str(len(eintraege)) + "):")
            for e in eintraege:
                log("    -", e)
        else:
            log("  " + kand + " existiert NICHT")

    # c) auth.json nur Metadaten – Inhalt wird bewusst nie gelesen (Geheimnisse)
    log("c) auth.json-Metadaten (keine Inhaltsausgabe)")
    for kand in kandidaten:
        auth = os.path.join(kand, "auth.json")
        if os.path.exists(auth):
            try:
                st = os.stat(auth)
                mtime = datetime.datetime.fromtimestamp(st.st_mtime).isoformat()
                log("  " + auth + ": EXISTIERT, Groesse=" + str(st.st_size)
                    + " Bytes, mtime=" + mtime)
            except OSError as e:
                log("  " + auth + ": EXISTIERT, stat fehlgeschlagen: " + str(e))
        else:
            log("  " + auth + ": existiert NICHT")

    # d) codex-Binaerdatei
    log("d) codex-Binaerdatei")
    log("  shutil.which('codex') =", shutil.which("codex") or "(nicht gefunden)")
    for p in ("/usr/local/bin/codex", "/opt/homebrew/bin/codex",
              os.path.join(home, ".local/bin/codex")):
        log("  Vorhanden: " + p + " ->", "ja" if os.path.exists(p) else "nein")

    # e) codex login status und codex --version
    log("e) codex login status")
    rc, aus = codex_subprocess(["login", "status"])
    log("  Rueckgabecode:", str(rc))
    log("  Ausgabe:", aus)

    log("e2) codex --version")
    rc2, aus2 = codex_subprocess(["--version"])
    log("  Rueckgabecode:", str(rc2))
    log("  Ausgabe:", aus2)

    # f) Bericht schreiben; einzige Assertion: Berichtsdatei existiert
    stempel = datetime.datetime.now().isoformat()
    inhalt = ("Codex-Login-Diagnose Task #2178 - " + stempel + "\n"
              + "\n".join(ZEILEN) + "\n")
    with open(BERICHT_PFAD, "w", encoding="utf-8") as f:
        f.write(inhalt)
    print("\n--- Bericht geschrieben:", BERICHT_PFAD, "---")
    assert os.path.isfile(BERICHT_PFAD), "Berichtsdatei wurde nicht erzeugt"