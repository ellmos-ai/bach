"""Test-Ausgabe-Recorder für die Task-Lease-CLI-Tests (Task 2617).

Weil execute_command stdout nicht bestätigt, schreibt dieser Hook die
Testergebnisse in eine Datei, die anschließend lesbar ist.
"""
import json
import os

_RECEIPT_PATH = os.environ.get("TEST2617_RECEIPT",
                               os.path.join(os.getcwd(), "test2617_receipt.json"))
_RESULTS = []

# Marker: conftest wurde geladen
try:
    with open(_RECEIPT_PATH + ".loaded", "w") as _fh:
        _fh.write("loaded\n")
except Exception:
    pass


def pytest_runtest_logreport(report):
    _RESULTS.append({
        "nodeid": report.nodeid,
        "outcome": report.outcome,
        "longrepr": str(report.longrepr) if report.longrepr else "",
    })


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    data = {
        "exitstatus": exitstatus,
        "results": _RESULTS,
        "passed": sum(1 for r in _RESULTS if r["outcome"] == "passed"),
        "failed": sum(1 for r in _RESULTS if r["outcome"] == "failed"),
        "total": len(_RESULTS),
    }
    for path in (_RECEIPT_PATH, "/tmp/test2617_receipt.json"):
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            break
        except Exception:
            continue
