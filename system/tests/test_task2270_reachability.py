"""Task #2270 – Reachability-Check fuer WORKSTATION-LG (192.168.9.129).

Vertrag (Task #2270; Beschluss Option B aus Task #1250):
- Zielhost muss ONLINE sein (ICMP) UND
- Option A: RDP-Creds geliefert + :3389 erreichbar, ODER
- Option B: OpenSSH-Server auf :22 aktiviert.

Diese Suite misst live: ICMP-Ping und die vier Ziel-Ports 22/445/3389/5985
(Socket-Aequivalent zu "nc -z -G3 192.168.9.129 <port>", Timeout 3 s).

Hinweis: FAILS dieser Suite sind die erwartete NEGATIV-Evidenz, solange
der Zielhost offline ist. Es wird kein Green-Flip erzwungen und keine
Evidenz erfunden.
"""
import socket
import subprocess

IP = "192.168.9.129"
PORT_ROLES = {
    22: "OpenSSH (Option B)",
    445: "SMB",
    3389: "RDP (Option A)",
    5985: "WinRM",
}


def _ping_rc(ip: str, tries: int = 3, secs: int = 5) -> int:
    """macOS-Ping: 3 Pakete, 5 s Gesamtdauer; Rückgabe Exitcode."""
    return subprocess.run(
        ["ping", "-c", str(tries), "-t", str(secs), ip],
        capture_output=True,
    ).returncode


def _port_or_fail(port: int) -> None:
    """TCP-Connect mit 3 s Timeout; im Fehlerfall Fail mit errno als Evidenz."""
    try:
        with socket.create_connection((IP, port), timeout=3):
            return  # Port offen
    except OSError as exc:
        assert False, (
            f"TCP :{port} ({PORT_ROLES[port]}) nicht erreichbar auf {IP}: "
            f"errno={exc.errno} detail={exc}"
        )


def test_icmp_host_online():
    rc = _ping_rc(IP)
    assert rc == 0, (
        f"ping {IP} rc={rc}: Host antwortet nicht auf ICMP "
        "(erwartet online lt. Vertrag)"
    )


def test_tcp_22_open():
    _port_or_fail(22)


def test_tcp_445_open():
    _port_or_fail(445)


def test_tcp_3389_open():
    _port_or_fail(3389)


def test_tcp_5985_open():
    _port_or_fail(5985)