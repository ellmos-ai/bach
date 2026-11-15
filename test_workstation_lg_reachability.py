import socket
import datetime

IP = "192.168.9.129"


def _tcp(port, timeout=3.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((IP, port))
        return "OPEN"
    except Exception as e:
        return "CLOSED(%s:%s)" % (type(e).__name__, e)
    finally:
        s.close()


def test_reachability_snapshot():
    lines = ["Zeit: %s  Host: %s" % (datetime.datetime.now().isoformat(), IP)]
    for p in (22, 445, 3389, 5985):
        lines.append("  Port %d: %s" % (p, _tcp(p)))
    report = "\n".join(lines)
    with open("reachability_snapshot.txt", "w") as f:
        f.write(report + "\n")
    print(report)


def test_openssh_port_22_open():
    state = _tcp(22)
    assert state == "OPEN", "Port 22 (OpenSSH) auf %s NICHT offen -> %s. Host offline/kein SSH." % (IP, state)
