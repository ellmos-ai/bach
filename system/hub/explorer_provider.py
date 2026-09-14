"""Provider seam for the system-explorer extraction (MODULRUECKTRANSFER Stufe 5).

BACH keeps its own native system audits (ports, zombies, locks) in
``hub/system_audit.py`` - those run WITHOUT this module. The external
``system-explorer`` contributes evidence-based installation topology
scans (files, skills, manifests, registries) for:

  * ``bach setup preflight``  - topology evidence before install/upgrade
  * ``bach upgrade --check``   - topology evidence incl. drift vs. last scan

Rollback rule (MODULRUECKTRANSFER-PLAN section 4, rule 1): setting the
environment variable ``BACH_USE_EXTERNAL_EXPLORER=0`` forces BACH back to
the legacy behaviour (no topology scan, native audits only) immediately,
even when the external module is importable.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

EXTERNAL_MODULE = "system_explorer"
EXTERNAL_DIST = "system-explorer"
ROLLBACK_ENV_VAR = "BACH_USE_EXTERNAL_EXPLORER"
BUDGET_ENV_VAR = "BACH_EXPLORER_SCAN_BUDGET"
DEFAULT_BUDGET_SECONDS = 10.0
STATE_DIR_NAME = "explorer_state"
STATE_FILE_NAME = "last_topology.json"

_ROLLBACK_OFF_VALUES = {"0", "false", "no", "off"}

# Scan-Root-Konfiguration: bewusst schmal (Doku/Manifest-Dateien, kein Code,
# keine DBs, keine Logs), max_depth 3 deckt system/skills/<skill>/SKILL.md ab.
SCAN_INCLUDE = ["*.md", "*.json", "*.toml", "*.yaml", "*.yml"]
SCAN_EXCLUDE_DIRS = [
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".pytest_cache", "dist", "build", "_archive", "_trash",
    "logs", "messages", "mail_attachments", "explorer_state", "data",
]
SCAN_MAX_DEPTH = 3

CONTRACT_SYMBOLS = {
    "scanner": ("scan",),
    "store": ("Store",),
    "config": ("DEFAULT_CONFIG",),
}


@dataclass(frozen=True)
class ExplorerProvider:
    name: str
    external: bool
    module: str | None
    reason: str


def _rollback_forced() -> bool:
    return os.environ.get(ROLLBACK_ENV_VAR, "").strip().lower() in _ROLLBACK_OFF_VALUES


def _scan_budget() -> float:
    raw = os.environ.get(BUDGET_ENV_VAR, "").strip()
    if not raw:
        return DEFAULT_BUDGET_SECONDS
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_BUDGET_SECONDS


def probe_explorer_provider() -> ExplorerProvider:
    """Describe the available provider without importing it (find_spec only)."""
    if _rollback_forced():
        return ExplorerProvider(
            name="bach-legacy",
            external=False,
            module=None,
            reason=f"rollback switch {ROLLBACK_ENV_VAR}=0 forces the internal path",
        )
    if importlib.util.find_spec(EXTERNAL_MODULE) is not None:
        return ExplorerProvider(
            name="ellmos system-explorer",
            external=True,
            module=EXTERNAL_MODULE,
            reason="independent module is importable",
        )
    return ExplorerProvider(
        name="bach-legacy",
        external=False,
        module=None,
        reason=f"{EXTERNAL_DIST} is not installed in this environment",
    )


def load_external_explorer() -> Any:
    """Import the independent module explicitly (no silent fallback)."""
    return importlib.import_module(EXTERNAL_MODULE)


def create_external_topology_scanner(
    root: Path,
    time_budget_seconds: float | None = None,
) -> "TopologyScannerAdapter":
    """Build the BACH-facing topology scanner from the external module.

    Fails closed with a clear contract error if the installed module does
    not expose the scan contract (scanner.scan, store.Store,
    config.DEFAULT_CONFIG) required by MODULRUECKTRANSFER Stufe 5.
    """
    module = load_external_explorer()
    missing: list[str] = []
    submodule_symbols = {}
    for submodule, symbols in CONTRACT_SYMBOLS.items():
        try:
            loaded = importlib.import_module(f"{EXTERNAL_MODULE}.{submodule}")
        except ImportError as exc:
            raise AttributeError(
                f"{EXTERNAL_DIST} contract violation: submodule "
                f"'{EXTERNAL_MODULE}.{submodule}' is missing ({exc})"
            ) from exc
        for symbol in symbols:
            if not hasattr(loaded, symbol):
                missing.append(f"{submodule}.{symbol}")
        submodule_symbols[submodule] = loaded
    if missing:
        raise AttributeError(
            f"{EXTERNAL_DIST} contract violation: missing {', '.join(missing)}; "
            "system-explorer >= 0.4 with the scan contract is required"
        )
    return TopologyScannerAdapter(
        root=Path(root),
        scanner=submodule_symbols["scanner"],
        store_cls=submodule_symbols["store"].Store,
        default_config=dict(submodule_symbols["config"].DEFAULT_CONFIG),
        time_budget_seconds=(
            _scan_budget() if time_budget_seconds is None else time_budget_seconds
        ),
    )


class TopologyScannerAdapter:
    """BACH-seitiger Adapter um system_explorer.scanner.scan().

    Fuehrt einen begrenzten Topologie-Scan des BACH-Roots in einen temporaeren
    Evidence-Store aus, extrahiert die Knotenzahl je Typ und raeumt den Store
    anschliessend immer auf (kein Schreibzugriff auf Produktivdaten).
    """

    def __init__(
        self,
        root: Path,
        scanner: Any,
        store_cls: Any,
        default_config: dict,
        time_budget_seconds: float,
    ):
        self.root = root
        self._scanner = scanner
        self._store_cls = store_cls
        self._default_config = default_config
        self.time_budget_seconds = time_budget_seconds

    def _build_config(self, store_path: Path) -> dict:
        config = json.loads(json.dumps(self._default_config))
        config.update({
            "_base": str(self.root),
            "database": str(store_path),
            "roots": [{
                "id": "bach-root",
                "path": str(self.root),
                "max_depth": SCAN_MAX_DEPTH,
                "include": list(SCAN_INCLUDE),
                "exclude_dirs": list(SCAN_EXCLUDE_DIRS),
            }],
        })
        return config

    def scan(self) -> dict:
        """Fuehrt den begrenzten Scan aus und liefert den BACH-Report."""
        started = time.monotonic()
        fd, store_name = tempfile.mkstemp(prefix="bach_topology_", suffix=".db")
        os.close(fd)
        store_path = Path(store_name)
        try:
            config = self._build_config(store_path)
            with self._store_cls(store_path) as store:
                stats = self._scanner.scan(
                    config,
                    store,
                    time_budget_seconds=self.time_budget_seconds,
                )
                node_counts = {
                    row["node_type"]: row["count"]
                    for row in store.db.execute(
                        "SELECT node_type, COUNT(*) AS count FROM nodes "
                        "GROUP BY node_type ORDER BY count DESC"
                    ).fetchall()
                }
            return {
                "adapter": EXTERNAL_DIST,
                "version": _module_version(),
                "root": str(self.root),
                "duration_seconds": round(time.monotonic() - started, 2),
                "budget_seconds": self.time_budget_seconds,
                "stats": dict(stats),
                "nodes": node_counts,
            }
        finally:
            try:
                store_path.unlink()
            except OSError:
                pass


def render_topology_evidence_lines(evidence: dict) -> list[str]:
    """Rendert die topology_evidence()-Payload als CLI-Zeilen (fail-soft).

    Konsumenten: hub/setup.py (preflight) und hub/upgrade.py (--check).
    Evidenz ist nie fatal: deaktiviert -> INFO, Fehler -> WARN.
    """
    if not evidence.get("enabled"):
        return [f"  [INFO] Topologie-Scan: deaktiviert ({evidence.get('reason', 'unbekannt')})"]
    if evidence.get("error"):
        return [f"  [WARN] Topologie-Scan: {evidence['error']}"]
    report = evidence.get("report", {})
    version = report.get("version", "unknown")
    stats = report.get("stats", {})
    nodes = report.get("nodes", {})
    duration = report.get("duration_seconds", "?")
    parts = []
    if "files" in stats:
        parts.append(f"{stats['files']} Dateien")
    for node_type in ("skill", "system", "registry", "database", "server"):
        if nodes.get(node_type):
            parts.append(f"{nodes[node_type]} {node_type if node_type != 'skill' else 'Skills'}")
    detail = ", ".join(parts[:4]) if parts else "keine Knoten gefunden"
    lines = [
        f"  [OK] Topologie-Scan (system-explorer v{version}): "
        f"{detail} ({duration}s)"
    ]
    drift = evidence.get("drift")
    if drift:
        lines.append("  [WARN] Topologie-Drift seit letztem Check:")
        for change in drift[:6]:
            lines.append(f"    - {change}")
        if len(drift) > 6:
            lines.append(f"    ... +{len(drift) - 6} weitere")
    return lines


def _module_version() -> str:
    try:
        from importlib import metadata
        return metadata.version(EXTERNAL_DIST)
    except Exception:
        return "unknown"


def topology_evidence(
    base_path: Path,
    state_dir: Path | None = None,
    persist_state: bool = False,
    time_budget_seconds: float | None = None,
) -> dict:
    """Topologie-Evidenz fuer preflight/upgrade check (fail-soft, nie fatal).

    Rueckgabe-Vertrag:
      {"enabled": False, "reason": "..."}                - deaktiviert/fehlend
      {"enabled": True, "report": {...}, "drift": [...]} - Scan erfolgreich
      {"enabled": True, "error": "..."}                  - Scan fehlgeschlagen
    """
    provider = probe_explorer_provider()
    if not provider.external:
        return {"enabled": False, "reason": provider.reason}

    try:
        scanner = create_external_topology_scanner(
            root=Path(base_path), time_budget_seconds=time_budget_seconds
        )
    except (ImportError, AttributeError) as exc:
        return {"enabled": True, "error": f"adapter contract failed: {exc}"}

    try:
        report = scanner.scan()
    except Exception as exc:  # Budget, Rechte, Store-Fehler -> nur Evidenzverlust
        return {"enabled": True, "error": f"scan failed: {exc}"}

    payload: dict = {"enabled": True, "report": report}

    drift = _compare_and_persist(report, state_dir, persist_state)
    if drift is not None:
        payload["drift"] = drift
    return payload


def _state_file(state_dir: Path | None) -> Path | None:
    if state_dir is None:
        try:
            from .bach_paths import DATA_DIR
            state_dir = DATA_DIR / STATE_DIR_NAME
        except Exception:
            return None
    return Path(state_dir) / STATE_FILE_NAME


def _compare_and_persist(
    report: dict, state_dir: Path | None, persist_state: bool
) -> list[str] | None:
    """Vergleicht den Report mit dem letzten gespeicherten Stand.

    Liefert Drift-Zeilen ("skills: 23 -> 25") oder None, wenn kein frueherer
    Stand existiert / verglichen werden kann. Speichert den Report nur bei
    ``persist_state=True`` (upgrade check); preflight bleibt lese-/beweisend.
    """
    state_file = _state_file(state_dir)
    if state_file is None:
        return None

    previous = None
    try:
        if state_file.exists():
            previous = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = None

    drift: list[str] | None = None
    if isinstance(previous, dict) and isinstance(previous.get("report"), dict):
        drift = _diff_reports(previous["report"], report)

    if persist_state:
        try:
            state_file.parent.mkdir(parents=True, exist_ok=True)
            state_file.write_text(
                json.dumps(
                    {"generated_at": datetime.now().isoformat(), "report": report},
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass
    return drift


def _diff_reports(previous: dict, current: dict) -> list[str]:
    """Vergleicht Datei-/Knoten-Zaehler zweier Reports."""
    lines: list[str] = []
    prev_nodes = previous.get("nodes", {})
    curr_nodes = current.get("nodes", {})
    for key in ["files", "directories", "evidence", "errors"]:
        prev_value = int(previous.get("stats", {}).get(key, 0))
        curr_value = int(current.get("stats", {}).get(key, 0))
        if prev_value != curr_value:
            lines.append(f"{key}: {prev_value} -> {curr_value}")
    for node_type in sorted(set(prev_nodes) | set(curr_nodes)):
        prev_value = int(prev_nodes.get(node_type, 0))
        curr_value = int(curr_nodes.get(node_type, 0))
        if prev_value != curr_value:
            lines.append(f"nodes.{node_type}: {prev_value} -> {curr_value}")
    return lines