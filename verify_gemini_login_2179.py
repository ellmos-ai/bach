#!/usr/bin/env python3
"""BACH-Task #2179: Gemini-Login am Google-Konto verifizieren und belegen.

Akzeptanz: `gemini -p "Antworte nur mit OK"` gibt OK aus.

Aufruf (im GUI-Terminal des Macs, gleich ob eingeloggt oder nicht):

    cd /Users/lukas/services/bach-worktrees/task-2179
    python3 verify_gemini_login_2179.py

Ergebnis landet zusaetzlich in gemini_2179_report.txt (neben diesem Skript).
Exitcode 0 == Akzeptanz erfuellt, 1 == nicht erfuellt (Details im Report).

Vorher einmalig interaktiv anmelden (OAuth im Browser):

    gemini          # Login-Flow durchlaufen, danach mit /quit beenden

Bei reinem SSH ohne Browser: NO_BROWSER=true gemini  -> Login-URL aus dem
Terminal im lokalen Browser oeffnen und den Code zurueckkopieren.
"""
import datetime
import os
import platform
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPORT = os.path.join(HERE, "gemini_2179_report.txt")
PROMPT = "Antworte nur mit OK"


def run(cmd, timeout, env=None):
    """Befehl ausfuehren und (rc, stdout, stderr, fehler) zurueckgeben."""
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=env
        )
        return p.returncode, p.stdout or "", p.stderr or "", None
    except FileNotFoundError:
        return None, "", "", "Befehl nicht gefunden: %r" % (cmd[0],)
    except subprocess.TimeoutExpired as e:
        out = e.stdout or ""
        err = e.stderr or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        return None, out, err, "Timeout nach %ss" % timeout
    except Exception as e:  # pragma: no cover - Diagnosefall
        return None, "", "", "%s: %s" % (type(e).__name__, e)


def main():
    env = os.environ.copy()
    env["NO_BROWSER"] = "true"
    lines = []
    add = lines.append

    add("BACH Task #2179 - Gemini-Login-Verifikation")
    add("Zeit:     %s" % datetime.datetime.now().isoformat(timespec="seconds"))
    add("Host:     %s (%s)" % (platform.node(), platform.platform()))
    add("Python:   %s" % sys.version.split()[0])
    add("Worktree: %s" % HERE)
    add("")

    gemini = shutil.which("gemini")
    add("gemini im PATH: %s" % (gemini or "NICHT GEFUNDEN"))
    add("")

    version_ok = False
    ping_ok = False

    if not gemini:
        add("ERGEBNIS: FAIL - gemini CLI nicht installiert oder nicht im PATH.")
    else:
        rc, out, err, fault = run(["gemini", "--version"], timeout=30, env=env)
        add("[1] gemini --version  rc=%r fehler=%r" % (rc, fault))
        add("    stdout: %s" % out.strip())
        add("    stderr: %s" % err.strip())
        version_ok = rc == 0
        add("    -> %s" % ("OK" if version_ok else "FEHLGESCHLAGEN"))
        add("")

        rc, out, err, fault = run(
            ["gemini", "-p", PROMPT], timeout=120, env=env
        )
        add('[2] gemini -p "%s"  rc=%r fehler=%r' % (PROMPT, rc, fault))
        add("    stdout: %s" % out.strip())
        add("    stderr: %s" % err.strip())
        if rc is None:
            add("    -> FEHLGESCHLAGEN (kein rc; bei Timeout meist offener OAuth-Login,")
            add("       Login-URL/Codemeldung oben in stderr pruefen)")
        else:
            kombinier = (out + "\n" + err).strip()
            ping_ok = rc == 0 and "OK" in kombinier
            add("    -> %s" % ("OK enthalten, rc==0" if ping_ok else "FEHLGESCHLAGEN"))

    add("")
    passed = bool(gemini) and version_ok and ping_ok
    add("ERGEBNIS: %s" % ("PASS - Akzeptanz Task #2179 erfuellt (gemini antwortet OK)"
                          if passed else "FAIL - Akzeptanz Task #2179 NICHT erfuellt"))
    add("Naechster Schritt bei FAIL: interaktiv `gemini` starten, Google-Login im")
    add("Browser abschliessen, mit /quit beenden, dieses Skript erneut ausfuehren.")

    text = "\n".join(lines) + "\n"
    print(text)
    try:
        with open(REPORT, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("Report geschrieben: %s" % REPORT)
    except OSError as e:
        print("WARNUNG: Report nicht schreibbar: %s" % e)

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
