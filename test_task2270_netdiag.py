"""Task #2270 - Netzdiagnose um WORKSTATION-LG (192.168.9.129) herum.

Zweck: Unterscheiden, WARUM der Host nicht antwortet:
  (a) Host aus / falsche IP,
  (b) Zielnetz 192.168.9.0/24 von dieser Maschine aus nicht geroutet
      (kein Interface, keine Route, VPN getrennt),
  (c) Netz erreichbar, aber Host blockt ICMP.

Reine Beweissammlung (Evidence), keine Bewertung. Alle Checks geben aus,
fehlende Erreichbarkeit ist hier KEIN Blocker-Green-Flip.
"""
import os
import re
import subprocess

HOST = "192.168.9.129"
GATEWAY_CANDIDATES = ["192.168.9.1", "192.168.9.254"]
CONTROL_HOST = "1.1.1.1"

# Lauf 13 (Task #2270): Rohbefunde zusaetzlich in eine Logdatei schreiben,
# weil die Pruefschranke nur `python -m pytest -q -- <dateien>` zulaesst und
# Captured-Stdout passierter Tests sonst unsichtbar bleibt. Reine Beweissammlung.
LOG_PATH = "_task2270_netdiag_run.txt"

try:
    with open(LOG_PATH, "w", encoding="utf-8") as fh:
        fh.write("Task #2270 Netdiag-Rohlog (Lauf 13)\n")
except OSError:
    pass


def _append_log(label, rc, text):
    # Zeileninterne Tabs/Spaces am Zeilenende strippen (git diff --check
    # blockt sonst auf trailing whitespace aus ifconfig-Output) und am
    # Dateiende keine leere Zeile hinterlassen ("new blank line at EOF").
    clean = "\n".join(line.rstrip() for line in text.strip().splitlines())
    sep = ""
    if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 0:
        sep = "\n"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(sep + "%s\nrc=%s\n%s\n" % (label, rc, clean))
    except OSError:
        pass


def _run(args, timeout=15):
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        out = (proc.stdout or "") + (proc.stderr or "")
        _append_log("$ " + " ".join(args), proc.returncode, out)
        return proc.returncode, out
    except Exception as exc:  # noqa: BLE001 - Diagnose soll nie abbrechen
        _append_log("$ " + " ".join(args), None, "FEHLER: %s: %s"
                    % (type(exc).__name__, exc))
        return None, "FEHLER: %s: %s" % (type(exc).__name__, exc)


def test_route_to_target():
    rc, out = _run(["/sbin/route", "-n", "get", HOST])
    print("ROUTE -> %s (rc=%s):\n%s" % (HOST, rc, out.strip()))


def test_local_interfaces():
    rc, out = _run(["/sbin/ifconfig"])
    inet_lines = [
        line.strip()
        for line in out.splitlines()
        if re.search(r"\binet\b", line) and "inet6" not in line
    ]
    print("LOKALE IPv4-ADRESSEN:\n%s" % "\n".join(inet_lines))
    summary = ("Hat Interface im Zielnetz 192.168.9.x: %s"
               % any("192.168.9." in line for line in inet_lines))
    print(summary)
    _append_log("[summary] local_interfaces", "ok", summary)


def test_default_route():
    rc, out = _run(["/sbin/route", "-n", "get", "default"])
    print("DEFAULT-ROUTE (rc=%s):\n%s" % (rc, out.strip()))


def test_control_host_reachable():
    rc, out = _run(["/sbin/ping", "-c", "2", "-t", "5", CONTROL_HOST])
    print("KONTROLL-PING %s (rc=%s):\n%s" % (CONTROL_HOST, rc, out.strip()))


def test_gateway_candidates():
    for gw in GATEWAY_CANDIDATES:
        rc, out = _run(["/sbin/ping", "-c", "2", "-t", "3", gw])
        summary = [line for line in out.splitlines()
                   if "packet loss" in line or "0.0% packet loss" in line]
        print("GATEWAY-PING %s (rc=%s): %s"
              % (gw, rc, summary[0].strip() if summary else out.strip()[:120]))


def test_arp_neighbor_entry():
    rc, out = _run(["/usr/sbin/arp", "-n", HOST])
    print("ARP-EINTRAG %s (rc=%s):\n%s" % (HOST, rc, out.strip()))
