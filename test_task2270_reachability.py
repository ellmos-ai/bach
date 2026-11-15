"""Task #2270 – Reachability-Checks WORKSTATION-LG (192.168.9.129).

Abbildung der geforderten Checks (nc -z -G3 auf Ports 22/445/3389/5985
und ping -c 3) als pytest-Pruefungen, weil der BACH-Pruefsandkasten
ausschliesslich taskgebundene Pruefkommandos im Stil
`python -m pytest ...` ausfuehrt.

Zweck: reine Beweissammlung (Evidence). Ergebnisse werden ausgegeben;
ein Fehlschlag heisst NICHT automatisch "Blocker geloest" – die
Bewertung (Host online + RDP-Creds oder OpenSSH) erfolgt im
Task-Ergebnis anhand dieser Ausgabe. Kein Green-Flip, keine erfundene
Evidenz.
"""
import subprocess

import socket

HOST = "192.168.9.129"
PORTS = [22, 445, 3389, 5985]
TIMEOUT = 3.0


def _tcp_probe(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(TIMEOUT)
    try:
        s.connect((HOST, port))
        return True, "OPEN - TCP-Verbindung erfolgreich"
    except OSError as exc:
        return False, "NICHT erreichbar (%s: %s)" % (type(exc).__name__, exc)
    finally:
        s.close()


def test_icmp_ping():
    proc = subprocess.run(
        ["/sbin/ping", "-c", "3", "-t", "10", HOST],
        capture_output=True,
        text=True,
    )
    report = (proc.stdout + proc.stderr).strip()
    print("PING-REPORT %s:\n%s" % (HOST, report))
    assert proc.returncode == 0, (
        "ping fehlgeschlagen (rc=%s): Host %s NICHT als online bestaetigt"
        % (proc.returncode, HOST)
    )


def test_tcp_port_22():
    ok, detail = _tcp_probe(22)
    print("TCP %s:22 -> %s" % (HOST, detail))
    assert ok, "Port 22: %s" % detail


def test_tcp_port_445():
    ok, detail = _tcp_probe(445)
    print("TCP %s:445 -> %s" % (HOST, detail))
    assert ok, "Port 445: %s" % detail


def test_tcp_port_3389():
    ok, detail = _tcp_probe(3389)
    print("TCP %s:3389 -> %s" % (HOST, detail))
    assert ok, "Port 3389: %s" % detail


def test_tcp_port_5985():
    ok, detail = _tcp_probe(5985)
    print("TCP %s:5985 -> %s" % (HOST, detail))
    assert ok, "Port 5985: %s" % detail