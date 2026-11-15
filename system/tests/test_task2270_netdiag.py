"""Task #2270 – Netzwerk-Diagnose: Umgebungskontrollen + Rohlog.

Misst Kontroll-Ziele (Internet 1.1.1.1, Gateways 192.168.9.1/.254),
probiert lokale Netzwerk-Binaries (route/ifconfig/arp) und schreibt das
Rohlog _task2270_netdiag_run.txt in den Worktree-Root. Der [summary]-Block
klassifiziert Artefakte ehrlich (fehlende Binaries = keine belastbare
Evidenz). Keine erfundene Evidenz; FAILS wären Umgebungsprobleme.
"""
import re
import subprocess
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[2]
LOG = BASE / "_task2270_netdiag_run.txt"

TARGET = "192.168.9.129"
GW_GOOD = "192.168.9.1"
GW_ALT = "192.168.9.254"
NET_CTRL = "1.1.1.1"
NET_LABEL = "192.168.9.x"

STATE = {
    "pings": {},
    "route": None,
    "ifconfig": None,
    "arp": None,
    "summary": [],
}
_LINES: list = []


def _ping(ip: str, tries: int = 3, secs: int = 5) -> dict:
    try:
        proc = subprocess.run(
            ["ping", "-c", str(tries), "-t", str(secs), ip],
            capture_output=True,
        )
    except FileNotFoundError as exc:
        return {"ip": ip, "rc": None, "loss": None, "avg_rtt": None,
                "detail": f"FileNotFoundError: {exc}"}
    out = proc.stdout.decode(errors="replace")
    m = re.search(r"(\d+(?:\.\d+)?)% packet loss", out)
    rtt = re.search(r"round-trip.*?=\s*[\d.]+/([\d.]+)/", out)
    return {
        "ip": ip,
        "rc": proc.returncode,
        "loss": float(m.group(1)) if m else None,
        "avg_rtt": float(rtt.group(1)) if rtt else None,
        "detail": out.strip().splitlines()[-1] if out.strip() else "",
    }


def _probe_binary(name: str, args: list) -> dict:
    try:
        proc = subprocess.run([name] + args, capture_output=True)
    except FileNotFoundError as exc:
        return {"name": name, "ok": False, "detail": f"FileNotFoundError: {exc}"}
    return {
        "name": name,
        "ok": proc.returncode == 0,
        "rc": proc.returncode,
        "detail": proc.stdout.decode(errors="replace").strip()[:2000],
    }


@pytest.fixture(scope="module", autouse=True)
def _diag_run():
    STATE["pings"] = {
        ip: _ping(ip) for ip in (NET_CTRL, GW_GOOD, GW_ALT, TARGET)
    }
    STATE["route"] = _probe_binary("route", ["get", TARGET])
    STATE["ifconfig"] = _probe_binary("ifconfig", [])
    STATE["arp"] = _probe_binary("arp", ["-a"])

    for res in STATE["pings"].values():
        _LINES.append(
            f"[ping] {res['ip']}: rc={res['rc']} loss={res['loss']}% "
            f"avg_rtt={res['avg_rtt']} ms | {res['detail']}"
        )
    for key in ("route", "ifconfig", "arp"):
        res = STATE[key]
        _LINES.append(
            f"[{key}] ok={res['ok']} rc={res.get('rc')} "
            f"detail={res['detail']!r:.200}"
        )

    summary = []
    ifcfg_ok = STATE["ifconfig"]["ok"]
    if ifcfg_ok:
        in_net = bool(re.search(r"\b192\.168\.9\.\d", STATE["ifconfig"]["detail"]))
        summary.append(
            f"local_interfaces: Hat Interface im Zielnetz {NET_LABEL}: {in_net}"
        )
    else:
        summary.append(
            f'local_interfaces: "Hat Interface im Zielnetz {NET_LABEL}: False" '
            "(ARTEFAKT-HINWEIS: ifconfig fehlgeschlagen – "
            "keine belastbare Evidenz fuer/ gegen lokale Interface-Zugehoerigkeit)"
        )
    for ip, res in STATE["pings"].items():
        summary.append(
            f"ping {ip}: rc={res['rc']} loss={res['loss']}% avg_rtt={res['avg_rtt']} ms"
        )
    STATE["summary"] = summary

    LOG.write_text("\n".join(_LINES + ["[summary]"] + summary) + "\n")
    yield


def test_internet_control_ping():
    res = STATE["pings"][NET_CTRL]
    assert res["rc"] == 0 and res["loss"] == 0.0, (
        f"Kontroll-Ping {NET_CTRL} gescheitert: {res} (Umgebung ohne Internet?)"
    )


def test_gateway_192_168_9_1_ping():
    res = STATE["pings"][GW_GOOD]
    assert res["rc"] == 0 and res["loss"] == 0.0, (
        f"Gateway {GW_GOOD} reagiert nicht: {res}"
    )


def test_gateway_192_168_9_254_offline():
    res = STATE["pings"][GW_ALT]
    assert res["rc"] != 0, (
        f"Gateway {GW_ALT} ist erreichbar (in früheren Läufen offline): {res}"
    )


def test_route_probe_recorded():
    res = STATE["route"]
    assert res is not None and res["name"] == "route", "route-Probe nicht durchgefuehrt"
    assert res["ok"] or "FileNotFoundError" in res["detail"], (
        f"route-Probe weder erfolgreich noch als Artefakt klassifiziert: {res}"
    )


def test_local_interfaces_summary_honest():
    line = next(s for s in STATE["summary"] if s.startswith("local_interfaces:"))
    ifcfg_ok = STATE["ifconfig"]["ok"]
    if ifcfg_ok:
        assert "ARTEFAKT-HINWEIS" not in line, line
    else:
        assert "ARTEFAKT-HINWEIS" in line and ": False" in line, line


def test_rohlog_written_with_summary():
    assert LOG.exists(), f"Rohlog {LOG} nicht geschrieben"
    content = LOG.read_text()
    assert "[summary]" in content, "Rohlog ohne [summary]-Block"