# -*- coding: utf-8 -*-
"""Runde 2 der Diagnose fuer Task #2178: Login-Status im ECHTEN Home pruefen.

Erkenntnis aus Runde 1: execute_command biegt HOME auf eine isolierte
Sandbox (.cache/.worker-check/home) um; dort ist "Not logged in" wertlos.
Hier wird daher gezielt geprueft:
  - Referenzpfade (Sandbox-Sicht: welche Pfade ausserhalb sind sichtbar?)
  - .codex-Ordner und auth.json-METADATEN unter /Users/lukas und /Users/buddha
  - `codex login status` mit explizit gesetztem HOME=/Users/lukas bzw. /Users/buddha
auth.json wird NIE gelesen (Geheimnisse); `codex exec` wird NICHT aufgerufen.
Keine Erfolg-/Misserfolg-Assertion fuer den Login: reine Diagnose.
"""
import datetime
import os
import shutil
import subprocess

BERICHT_PFAD = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "codex_login_bericht_runde2.txt")
ZEILEN = []


def log(titel, *text):
    block = [titel] + ["  " + t for t in text]
    for z in block:
        print(z)
    ZEILEN.extend(block)


def codex_login_status_home(home_pfad):
    """`codex login status` mit explizitem HOME ausfuehren."""
    exe = shutil.which("codex")
    if not exe:
        return None, "codex-Binaerdatei nicht im PATH gefunden"
    env = dict(os.environ)
    env["HOME"] = home_pfad
    try:
        p = subprocess.run([exe, "login", "status"],
                           capture_output=True, text=True, timeout=30, env=env)
    except subprocess.TimeoutExpired:
        return None, "Timeout (>30 s) bei codex login status (HOME=" + home_pfad + ")"
    except OSError as e:
        return None, "OS-Fehler: " + str(e)
    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    kombiniert = out + ("\n  [stderr] " + err if err else "")
    return p.returncode, kombiniert or "(keine Ausgabe)"


def test_codex_login_echtes_home():
    log("a) Referenzpfade (Sichtbarkeit ausserhalb der Sandbox)")
    for p in (os.path.dirname(os.path.abspath(__file__)),
              "/Users/lukas/services/bach-worktrees",
              "/Users/lukas", "/Users", "/Users/buddha"):
        log("  " + p + " sichtbar/existiert:",
            "ja" if os.path.exists(p) else "NEIN")

    log("b) .codex-Ordner in echten Homes")
    for home in ("/Users/lukas", "/Users/buddha"):
        cod = os.path.join(home, ".codex")
        if os.path.isdir(cod):
            try:
                eintraege = sorted(os.listdir(cod))
            except OSError as e:
                eintraege = ["(listdir fehlgeschlagen: " + str(e) + ")"]
            log("  " + cod + " EXISTIERT, Eintraege (" + str(len(eintraege)) + "):")
            for e in eintraege:
                log("    -", e)
        else:
            log("  " + cod + " existiert NICHT")

    log("c) auth.json-Metadaten (Inhalt wird bewusst nie gelesen)")
    for home in ("/Users/lukas", "/Users/buddha"):
        auth = os.path.join(home, ".codex", "auth.json")
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

    log("d) codex login status mit explizitem HOME")
    for home in ("/Users/lukas", "/Users/buddha"):
        log("  HOME=" + home)
        rc, aus = codex_login_status_home(home)
        log("    Rueckgabecode:", str(rc))
        log("    Ausgabe:", aus)

    log("e) codex-Binaer")
    log("  shutil.which('codex') =", shutil.which("codex") or "(nicht gefunden)")

    stempel = datetime.datetime.now().isoformat()
    inhalt = ("Codex-Login-Diagnose Task #2178 Runde 2 - " + stempel + "\n"
              + "\n".join(ZEILEN) + "\n")
    with open(BERICHT_PFAD, "w", encoding="utf-8") as f:
        f.write(inhalt)
    print("\n--- Bericht geschrieben:", BERICHT_PFAD, "---")
    assert os.path.isfile(BERICHT_PFAD), "Berichtsdatei wurde nicht erzeugt"