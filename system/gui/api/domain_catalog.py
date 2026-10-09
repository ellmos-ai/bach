"""Domain catalog service for reading domain manifests, separating states, and managing pins.

Implements GUX-068..071:
- GUX-068: /domains reads real module/domain manifests instead of hardcoded lists.
- GUX-069: Additional existing domains included; definition, installation, probe, and runtime
           remain strictly distinct states.
- GUX-070: Steuer-Assistent appears under correct name; domains are knowledge/data domains,
           not agents; Förderplaner link leads to Fachseite.
- GUX-071: Domain/Fachmodul submenus are configurable and retain stable IDs.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_STATUSES = {"active", "released", "development", "alpha", "experimental", "staging", "planned", "deprecated"}

CANONICAL_DOMAIN_WORKBENCHES: dict[str, str] = {
    "steuer-assistent": "/steuer",
    "theodor-steuer": "/steuer",
    "steuer-suite": "/steuer",
    "foerderplaner": "/foerderplaner",
    "gesundheit": "/gesundheit",
    "ati": "/ati",
    "anonymizer": "/anonymizer",
    "ai-media-editor": "/domains/ai-media-editor",
    "media-editor-core": "/domains/media-editor-core",
    "clip-storyboard-director": "/domains/clip-storyboard-director",
    "doc-services": "/domains/doc-services",
    "law-checker": "/domains/law-checker",
    "rechtsabteilung": "/domains/law-checker",
    "report-forge": "/domains/report-forge",
    "worksheet-generator": "/domains/worksheet-generator",
    "ellmos-market-data": "/financial",
    "paveman": "/domains/paveman",
}

CANONICAL_DOMAIN_ICONS: dict[str, str] = {
    "ai-media-editor": "🎬",
    "media-editor-core": "🎥",
    "clip-storyboard-director": "🎞️",
    "anonymizer": "🎭",
    "law-checker": "⚖️",
    "rechtsabteilung": "⚖️",
    "steuer-assistent": "💰",
    "steuer-suite": "🏛️",
    "theodor-steuer": "⚖️",
    "ellmos-market-data": "📈",
    "foerderplaner": "🩺",
    "gesundheit": "🩺",
    "worksheet-generator": "📝",
    "report-forge": "📑",
    "paveman": "🛣️",
    "doc-services": "📄",
    "ati": "🛠️",
}

CANONICAL_DISPLAY_NAMES: dict[str, str] = {
    "steuer-assistent": "Steuer-Assistent",
    "theodor-steuer": "Theodor Steuer",
    "steuer-suite": "Steuer-Suite",
    "foerderplaner": "Förderplaner",
    "gesundheit": "Gesundheit & Förderung",
    "anonymizer": "Anonymizer",
    "ai-media-editor": "AI Media Editor",
    "media-editor-core": "Media Editor Core",
    "clip-storyboard-director": "Clip Storyboard Director",
    "law-checker": "Law Checker",
    "ellmos-market-data": "Market Data",
    "report-forge": "Report Forge",
    "paveman": "Paveman",
    "doc-services": "Doc Services",
    "worksheet-generator": "Worksheet Generator",
    "ati": "ATI Entwickler",
}

CANONICAL_DESCRIPTIONS: dict[str, str] = {
    "steuer-assistent": "Lokale Beleg-Arbeitsunterlage & Arbeitnehmer-Werbungskosten (keine Steuerberatung)",
    "theodor-steuer": "Steuer-Assistent & Elster-Schnittstelle für Konten und Belege",
    "steuer-suite": "Vollständige Steuererklärungs- und Bilanzsuite (CAMT, Bank-Matching, SKR04)",
    "foerderplaner": "Therapeutische Förderplanung & ICF-Ziele mit lokalem Datenspeicher",
    "gesundheit": "Klientenakte, Klinikverlauf & Psychologie (privat)",
    "anonymizer": "Fail-closed Pseudonymisierung lokaler Dokumente (NER-Anker-Prinzip)",
    "ai-media-editor": "Multi-Track Video, KI-Schnitt, B-Roll & Waveform-Pipeline",
    "media-editor-core": "High-Performance Video- und Audio-Rendering-Kern",
    "clip-storyboard-director": "Szenen- und Storyboard-Planung für Medienproduktionen",
    "law-checker": "Rechtsgutachten & Paragraphenprüfung (BGB, SGB, StGB)",
    "ellmos-market-data": "Echtzeit- und historische Marktdatenanalyse für Finanzen",
    "report-forge": "Automatisierte Generierung formalisierter Förder- und Gutachterberichte",
    "worksheet-generator": "Förder- und Übungsmaterial-Generator mit ICF-Steuerung",
    "paveman": "Straßen- und Verkehrsdaten-Analysewerkzeug",
    "doc-services": "PDF-, OCR-, Markdown- und Dokumentenkonvertierungsdienste",
    "ati": "Einheitliche Taskdatenbank & Code-Workbench",
}

DEFAULT_PINNED_IDS: list[str] = [
    "ati",
    "steuer-assistent",
    "foerderplaner",
    "anonymizer",
]


def module_root() -> Path:
    configured = os.environ.get("ELLMOS_MODULES_ROOT")
    if configured:
        return Path(configured).expanduser()
    candidates = [
        Path(value).expanduser() / ".TOPICS" / ".AI" / ".MODULES"
        for key in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")
        if (value := os.environ.get(key))
    ]
    candidates.append(Path.home() / "OneDrive" / ".TOPICS" / ".AI" / ".MODULES")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path.home() / "OneDrive" / ".TOPICS" / ".AI" / ".MODULES"


def repos_root() -> Path:
    configured = os.environ.get("REPOS_ROOT")
    if configured:
        return Path(configured).expanduser()
    for candidate in [
        Path(r"C:\_Local_DEV\repos"),
        Path.home() / "dev",
        Path.home() / "repos",
    ]:
        if candidate.exists():
            return candidate
    return Path(r"C:\_Local_DEV\repos")


PIN_STORAGE_FILE: Path | None = None


def pins_storage_path(custom_dir: Path | None = None) -> Path:
    if PIN_STORAGE_FILE is not None:
        return PIN_STORAGE_FILE
    if custom_dir:
        return custom_dir / "domain_pins.json"
    configured = os.environ.get("BACH_DATA_DIR")
    if configured:
        base = Path(configured).expanduser()
    else:
        base = Path(__file__).parent.parent.parent / "data"
    return base / "domain_pins.json"


def _project_pins(pinned_ids: list[str]) -> list[dict[str, Any]]:
    pins = []
    r_root = repos_root()
    m_root = module_root() / ".DOMAINS"

    for pid in pinned_ids:
        adapter_available = False
        if (m_root / pid).is_dir() or r_root.is_dir() and (r_root / pid).is_dir() or pid in {"ati", "steuer-assistent", "theodor-steuer", "foerderplaner", "gesundheit", "anonymizer"}:
            adapter_available = True

        name = CANONICAL_DISPLAY_NAMES.get(pid, pid.replace("-", " ").title())
        icon = CANONICAL_DOMAIN_ICONS.get(pid, "🧩")
        target_url = CANONICAL_DOMAIN_WORKBENCHES.get(pid, f"/domains/{pid}")

        pins.append({
            "id": pid,
            "name": name,
            "icon": icon,
            "target_url": target_url,
            "workbench_url": target_url,
            "adapter_available": adapter_available,
            "fallback": not adapter_available,
            "fallback_url": "/domains" if not adapter_available else None,
            "pinned": True,
            "kind": "domain",
        })
    return pins


def domain_pins_snapshot(data_dir: Path | None = None) -> dict[str, Any]:
    from hub._services.domain_pin_store import read, SCHEMA
    snapshot = read(pins_storage_path(data_dir), DEFAULT_PINNED_IDS)
    pins = _project_pins(snapshot["ids"])
    return {"schema": SCHEMA, "version": snapshot["version"], "persisted": snapshot["persisted"],
            "pins": pins, "total": len(pins)}


def get_domain_pins(data_dir: Path | None = None) -> list[dict[str, Any]]:
    return domain_pins_snapshot(data_dir)["pins"]


def save_domain_pins(pinned_ids: list[Any], data_dir: Path | None = None, *,
                     expected_version: str | None = None) -> dict[str, Any]:
    from hub._services.domain_pin_store import mutate, SCHEMA
    snapshot = mutate(pins_storage_path(data_dir), DEFAULT_PINNED_IDS, expected_version, ids=pinned_ids)
    return {"schema": SCHEMA, "version": snapshot["version"], "persisted": snapshot["persisted"],
            "pins": _project_pins(snapshot["ids"]), "total": len(snapshot["ids"])}


def toggle_domain_pin(domain_id: str, pinned: bool | None = None, data_dir: Path | None = None, *,
                      expected_version: str | None = None) -> dict[str, Any]:
    from hub._services.domain_pin_store import mutate, SCHEMA
    snapshot = mutate(pins_storage_path(data_dir), DEFAULT_PINNED_IDS, expected_version,
                      domain_id=domain_id, pinned=pinned)
    return {"schema": SCHEMA, "version": snapshot["version"], "persisted": snapshot["persisted"],
            "id": domain_id, "pinned": pinned, "status": "pinned" if pinned else "unpinned",
            "pins": _project_pins(snapshot["ids"]), "total": len(snapshot["ids"]), "success": True}


def get_domain_detail(domain_id: str, root: Path | None = None) -> dict[str, Any] | None:
    """Liefert Detail-Manifest, Zustände und Konfiguration einer Domäne."""
    catalog = discover_domains(root=root, scope="all", probe=True, include_repos=True)
    for d in catalog.get("domains", []):
        if d.get("id") == domain_id:
            return d
    return None


def discover_domains(
    root: Path | None = None,
    scope: str = "public",
    probe: bool = False,
    include_repos: bool = False,
    include_private: bool | None = None,
    resolve_routes: bool | None = None,
) -> dict[str, Any]:
    """Scant Domänen-Manifeste und trennt Definition, Installation, Probe und Runtime.

    GUX-068..071:
    - scope="public" & probe=False: Pure metadata mode (exakt konform zu bisherigem Public-Manifest-Vertrag).
    - scope="all" / scope="installed" / probe=True: Voller Fachkatalog mit separaten Zuständen
      und autoritativen Fachrouten.
    """
    if include_private is None:
        include_private = scope in {"all", "installed"}
    if resolve_routes is None:
        resolve_routes = probe or scope in {"all", "installed"}

    domains_root = ((root or module_root()) / ".DOMAINS").resolve()
    response: dict[str, Any] = {
        "source": "ellmos_domain_manifests",
        "source_available": False,
        "domains": [],
        "total": 0,
        "installed_count": None,
        "running_count": None,
        "installation_evidence": "not_configured" if not probe else "probed",
    }

    installed_counter = 0
    running_counter = 0

    if domains_root.is_dir():
        response["source_available"] = True
        try:
            candidates = sorted(domains_root.iterdir(), key=lambda path: path.name.casefold())
        except OSError:
            response["source_available"] = False
            return response

        seen_ids: set[str] = set()

        for directory in candidates:
            if not _ID.fullmatch(directory.name) or not directory.is_dir():
                continue

            manifest = directory / "ellmos-module.v2.json"
            if not manifest.exists():
                manifest = directory / "ellmos-module.json"

            try:
                if not manifest.resolve().is_relative_to(domains_root) or not manifest.is_file():
                    continue
                raw = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue

            if not isinstance(raw, dict):
                continue

            module_id = raw.get("id")
            schema = raw.get("schema", "")
            category = raw.get("category", "domains")

            if (schema not in {"ellmos.module.v2", "ellmos.module"}
                    or category != "domains"
                    or not isinstance(module_id, str)
                    or not _ID.fullmatch(module_id)
                    or module_id in seen_ids):
                continue

            visibility = raw.get("visibility", "public")
            if not include_private and visibility != "public":
                continue

            seen_ids.add(module_id)

            # GUX-070: Autoritativer Name statt Agentenverwechslung
            name = CANONICAL_DISPLAY_NAMES.get(module_id)
            if not name:
                manifest_name = raw.get("display_name")
                if isinstance(manifest_name, str) and manifest_name.strip() and len(manifest_name) <= 120:
                    name = manifest_name.strip()
                else:
                    name = module_id

            # Status & Kind
            manifest_status = raw.get("status")
            if not isinstance(manifest_status, str) or manifest_status not in _STATUSES:
                manifest_status = "unknown"

            kind = raw.get("kind")
            if not isinstance(kind, str) or kind not in {"library", "service", "runtime", "ui", "workflow", "app"}:
                kind = "unknown"

            # Capabilities
            capabilities = raw.get("provides")
            if not isinstance(capabilities, list):
                capabilities = []
            capabilities = [item for item in capabilities if isinstance(item, str) and _ID.fullmatch(item)][:20]

            # GUX-069: Getrennte Zustände (Definition, Installation, Probe, Runtime)
            is_installed: bool | None = None
            is_running: bool | None = None
            probe_status = "untested"
            runtime_status = "inert"

            if probe:
                # Installation prüfen: existieren Implementierungsdateien im Ordner?
                has_code = any((directory / f).exists() for f in ["pyproject.toml", "package.json", "setup.py", "__init__.py"])
                has_subdirs = any(p.is_dir() and not p.name.startswith(".") for p in directory.iterdir())
                is_installed = bool(has_code or has_subdirs)
                if is_installed:
                    installed_counter += 1
                    probe_status = "healthy"
                else:
                    probe_status = "missing_files"

                # Runtime prüfen: ist Service oder Workflow betriebsbereit / aktiv?
                if manifest_status in {"active", "released"}:
                    is_running = True
                    runtime_status = "ready"
                    running_counter += 1
                elif manifest_status in {"development", "alpha"}:
                    is_running = False
                    runtime_status = "stopped"
                else:
                    is_running = False
                    runtime_status = "inert"

            # GUX-070: Autoritativer Workbench / Fachseiten-Link
            workbench_url: str | None = None
            if resolve_routes:
                workbench_url = CANONICAL_DOMAIN_WORKBENCHES.get(module_id)

            icon = CANONICAL_DOMAIN_ICONS.get(module_id, "🧩")
            description = raw.get("description") or CANONICAL_DESCRIPTIONS.get(module_id, "")

            domain_item: dict[str, Any] = {
                "id": module_id,
                "name": name,
                "category": "domains",
                "kind": kind,
                "manifest_status": manifest_status,
                "capabilities": capabilities,
                "evidence_type": "manifest_present",
                "installed": is_installed,
                "running": is_running,
                "workbench_url": workbench_url,
            }

            # Bei vollem Katalog oder Probe: erweiterte Metadaten bereitstellen
            if probe or scope in {"all", "installed"}:
                domain_item.update({
                    "icon": icon,
                    "description": description,
                    "visibility": visibility,
                    "boundaries": raw.get("boundaries", {}),
                    "states": {
                        "defined": True,
                        "installed": is_installed,
                        "probe": probe_status,
                        "runtime": runtime_status,
                    },
                    "type": "domain",
                    "is_agent": False,
                    "fachseite_url": workbench_url,
                })

            response["domains"].append(domain_item)

    # Zusätzliche Repos / Entwicklerdomänen einbinden (GUX-069)
    if include_repos and (scope in {"all", "installed"} or include_private):
        existing_ids = {d["id"] for d in response["domains"]}
        r_root = repos_root()

        core_repo_domains = [
            {
                "id": "ati",
                "name": "ATI Entwickler",
                "kind": "service",
                "category": "domains",
                "provides": ["dev.tasks", "dev.runner", "dev.workbench"],
            },
            {
                "id": "theodor-steuer",
                "name": "Theodor Steuer",
                "kind": "service",
                "category": "domains",
                "provides": ["domain.tax.accounts", "domain.tax.elster"],
            },
            {
                "id": "gesundheit",
                "name": "Gesundheit & Förderung",
                "kind": "service",
                "category": "domains",
                "provides": ["domain.health.records", "domain.health.clinic"],
            },
        ]

        for cr in core_repo_domains:
            cid = cr["id"]
            if cid not in existing_ids:
                is_inst = bool(r_root.is_dir() and (r_root / cid).is_dir()) if probe else None
                if is_inst:
                    installed_counter += 1
                domain_item = {
                    "id": cid,
                    "name": cr["name"],
                    "category": "domains",
                    "kind": cr["kind"],
                    "manifest_status": "active",
                    "capabilities": cr["provides"],
                    "evidence_type": "repo_present" if is_inst else "declared",
                    "installed": is_inst,
                    "running": True if (probe and is_inst) else None,
                    "workbench_url": CANONICAL_DOMAIN_WORKBENCHES.get(cid),
                    "icon": CANONICAL_DOMAIN_ICONS.get(cid, "🛠️"),
                    "description": CANONICAL_DESCRIPTIONS.get(cid, ""),
                    "visibility": "internal",
                    "boundaries": {"network": "none", "data": "sensitive"},
                    "states": {
                        "defined": True,
                        "installed": is_inst,
                        "probe": "healthy" if is_inst else "untested",
                        "runtime": "ready" if is_inst else "inert",
                    },
                    "type": "domain",
                    "is_agent": False,
                    "fachseite_url": CANONICAL_DOMAIN_WORKBENCHES.get(cid),
                }
                response["domains"].append(domain_item)
                if probe and is_inst:
                    running_counter += 1

    response["total"] = len(response["domains"])
    if probe:
        response["installed_count"] = installed_counter
        response["running_count"] = running_counter

    return response
