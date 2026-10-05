#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_workstation_1250.py — Re-Verifizierung der Erreichbarkeit von WORKSTATION-LG
BACH-Task #1250 | Prüfdatum: 2026-09-29 | Vorausgegangene Verifikation: 2026-09-13

Laufzeitkontext:
    Host:   mac-studio (macOS 26.4.1) — BACH läuft hier.
    Ziel:   WORKSTATION-LG (Windows-Zielrechner, BACH-Transfer09 / Gate 2)
    Grund: Task #1250 blockiert, weil WORKSTATION-LG laut Stand 2026-09-13
           vom BACH-Host nicht erreichbar ist (kein SSH/known_hosts/Connector).
    Runbook:  docs/architecture/OPERATOR-RUNBOOK-WORKSTATION-LG-TRANSFER09-GATE2.md
    Handboff: Task #1253 (Operator; PowerShell-Anweisungen + Evidenz-Vorlage)

Methode (Shell-Netzwerktools hier nicht verfügbar; ping/arp blockiert):
    A) Lokale IPs des mac-studio (Kontext: in welchem Netz wird geprüft?)
       - socket.gethostname() + System-Resolver
       - Default-Route-Quell-IP via UDP-Connect-Trick (sendet KEINE Pakete)
    B) Namensauflösung von WORKSTATION-LG und WORKSTATION-LG.local
       über getaddrinfo (macOS-Resolver: DNS + /etc/hosts + mDNS/Bonjour),
       IPv4 und IPv6.
    C) Bei Auflösungserfolg: TCP-Connect-Tests auf Ports 22, 135, 445, 3389
       (SSH / RPC-EndpointMapper / SMB / RDP), je 2s Timeout.

Exit-Code ist immer 0; das Ergebnis wird textuell ausgewertet.
"""

import socket
import sys
import platform
from datetime import datetime

HOSTNAMES = ["WORKSTATION-LG", "WORKSTATION-LG.local"]
PORTS = [22, 135, 445, 3389]  # SSH, RPC/EndpointMapper, SMB, RDP
TIMEOUT = 2.0

FAMNAME = {socket.AF_INET: "IPv4", socket.AF_INET6: "IPv6"}


def rule(ch="=", n=72):
    return ch * n


def tcp_connect(ip, port, timeout=TIMEOUT):
    """TCP-Connect-Test; liefert (erfolgreich, fehlermeldung)."""
    fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
    s = socket.socket(fam, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        return True, None
    except OSError as e:
        return False, "{0}: {1}".format(type(e).__name__, e)
    finally:
        s.close()


def section_a_local_context():
    print(rule("="))
    print("A. LOKALER KONTEXT — von welchem Host/Netz wird geprüft?")
    print(rule("="))
    print("Zeitstempel : {0}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    print("Plattform   : {0} {1} (python {2})".format(
        platform.system(), platform.release(), sys.version.split()[0]))
    hostname = socket.gethostname()
    print("Hostname    : {0}".format(hostname))

    # Resolver-Ergebnis für den eigenen Hostnamen
    try:
        infos = socket.getaddrinfo(hostname, None, 0, socket.SOCK_STREAM)
        own = []
        for fam, _typ, _proto, _canon, sockaddr in infos:
            ip = sockaddr[0]
            tag = FAMNAME.get(fam, "fam{0}".format(fam))
            if (ip, tag) not in own:
                own.append((ip, tag))
        for ip, tag in own:
            print("Eigene IP   : {0} ({1})".format(ip, tag))
        if not own:
            print("Eigene IP   : (keine via Resolver)")
    except socket.gaierror as e:
        print("Eigene IP   : Resolver-Fehler für eigenen Hostnamen: {0}".format(e))

    # Default-Route-Quell-IP via UDP-Connect (kein Paketversand)
    for label, addr, fam in (
        ("Default-IPv4-Quell-IP (UDP-Trick)", ("192.0.2.1", 80), socket.AF_INET),
        ("Default-IPv6-Quell-IP (UDP-Trick)", ("2001:db8::1", 80), socket.AF_INET6),
    ):
        try:
            s = socket.socket(fam, socket.SOCK_DGRAM)
            try:
                s.settimeout(TIMEOUT)
                s.connect(addr)
                print("{0:<38}: {1}".format(label, s.getsockname()[0]))
            finally:
                s.close()
        except OSError as e:
            print("{0:<38}: nicht ermittelbar ({1})".format(label, e))


def section_b_resolve():
    print()
    print(rule("="))
    print("B. NAMENSAUFLÖSUNG (getaddrinfo: DNS + /etc/hosts + mDNS)")
    print(rule("="))
    resolved = {}  # hostname -> [(ip, familiename)]
    for name in HOSTNAMES:
        try:
            infos = socket.getaddrinfo(name, None, 0, socket.SOCK_STREAM)
        except socket.gaierror as e:
            print("{0:<24} -> NICHT AUFLÖSBAR  (gaierror: {1})".format(name, e))
            resolved[name] = []
            continue
        ips = []
        for fam, _typ, _proto, _canon, sockaddr in infos:
            ip = sockaddr[0]
            tag = FAMNAME.get(fam, "fam{0}".format(fam))
            if (ip, tag) not in ips:
                ips.append((ip, tag))
        resolved[name] = ips
        if ips:
            for ip, tag in ips:
                print("{0:<24} -> {1} ({2})  AUFGELÖST".format(name, ip, tag))
        else:
            print("{0:<24} -> leere Resolver-Antwort".format(name))
    return resolved


def section_c_tcp(resolved):
    print()
    print(rule("="))
    print("C. TCP-CONNECT-TESTS (Ports {0}, je {1}s Timeout)".format(
        "/".join(str(p) for p in PORTS), int(TIMEOUT)))
    print(rule("="))
    any_open = False
    tested_any = False
    for name, ips in sorted(resolved.items()):
        for ip, tag in ips:
            for port in PORTS:
                tested_any = True
                ok, err = tcp_connect(ip, port)
                status = "OFFEN" if ok else "NICHT ERREICHBAR ({0})".format(err)
                print("{0} [{1}] :{2:<5} -> {3}".format(ip, tag, port, status))
                if ok:
                    any_open = True
    if not tested_any:
        print("(kein Test möglich — keine Ziel-IP aufgelöst)")
    return tested_any, any_open


def verdict(resolved, any_open):
    print()
    print(rule("="))
    print("ERGEBNIS / URTEIL (für Task #1250)")
    print(rule("="))
    today = datetime.now().strftime("%Y-%m-%d")
    n_resolved = sum(1 for v in resolved.values() if v)
    if not n_resolved:
        print("BLOCKER BESTÄTIGT (Stand {0}):".format(today))
        print("  WORKSTATION-LG ist vom mac-studio (BACH-Host) NICHT auflösbar —")
        print("  weder 'WORKSTATION-LG' noch 'WORKSTATION-LG.local' (IPv4+IPv6,")
        print("  System-Resolver inkl. DNS/hosts/mDNS). TCP-Tests entfielen.")
        print("  => Task #1250 bleibt blockiert; Verifikationsstand nun {0}.".format(today))
        print("  => Nächster sinnvoller Schritt bleibt Operator-Handboff #1253")
        print("     (PowerShell-Checks auf Windows-Seite, Evidenz-Vorlage).")
    elif not any_open:
        print("TEILERGEBNIS (Stand {0}):".format(today))
        print("  {0} von {1} Hostnamen-Varianten auflösbar, aber KEIN geprüfter".format(
            n_resolved, len(HOSTNAMES)))
        print("  Port (22/135/445/3389) erreichbar — Host offline, Dienste")
        print("  gestoppt oder Firewall-Filter. Keine nutzbare Konnektivität")
        print("  für BACH vom mac-studio aus.")
        print("  => Blocker für BACH praktisch bestätigt (Stand {0});".format(today))
        print("     Differenzierung offline vs. gefiltert nur Windows-seitig (#1253).")
    else:
        print("ÄNDERUNG ZU 2026-09-13: WORKSTATION-LG ist jetzt (teilweise) erreichbar!")
        print("  => Blocker-Zustand von #1250 ist entkräftet bzw. zu präzisieren;")
        print("     Task-Beschreibung anpassen, Handboff-Optionen prüfen.")
    print()
    print("Hinweis: Ohne Operator-Zugriff auf WORKSTATION-LG (Windows-Seite)")
    print("ist kein lokaler Abschluss von #1250 möglich (Operatoren-Task).")


def main():
    print("check_workstation_1250.py — Erreichbarkeits-Re-Verifizierung WORKSTATION-LG")
    print("BACH-Task #1250 | Prüfmethode: getaddrinfo + TCP-Connect (kein ping/arp moeglich)")
    print()
    section_a_local_context()
    resolved = section_b_resolve()
    tested_any, any_open = section_c_tcp(resolved)
    verdict(resolved, any_open)
    return 0


if __name__ == "__main__":
    sys.exit(main())