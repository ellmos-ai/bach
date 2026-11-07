# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
ModulesHandler - Modul-Paketmanager & Modularer Core Update-Zentrale
===================================================================

Verwaltet autarke Standalone-Module in .MODULES/, validiert Manifeste,
ermöglicht Modul-Installation, Versionierung, Updates und Hot-Wiring
ohne System-Neustart.

Operationen:
  list                 Alle installierten Module in .MODULES auflisten
  status               Modularisierungs- und Hot-Wiring-Status anzeigen
  check [name]         Integrität und Manifeste validieren
  install <path|zip>   Modul aus Verzeichnis oder ZIP installieren
  update [--dry-run]   Module aus Quellpfaden auf neueste Versionen aktualisieren
  export <name>        Modul als autarkes Paket exportieren
  wire                 Hot-Wiring für alle Standalone-Module ausführen
  help                 Hilfe anzeigen
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import zipfile
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from hub.base import BaseHandler
from hub._services.ocean_stack_bridge import (
    auto_switch_to_standalone_modules,
    detect_legacy_in_tree_services,
    invalidate_module_cache,
    ocean_modularized_services_status,
)


def parse_semver(ver: str) -> Tuple[int, int, int]:
    """Extrahiert Major, Minor, Patch aus SemVer-String."""
    clean = str(ver).strip().lstrip("v")
    parts = clean.split(".")
    nums = []
    for p in parts[:3]:
        m = re.match(r"^(\d+)", p)
        nums.append(int(m.group(1)) if m else 0)
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2])


_MODULES_UPDATE_CACHE: Dict[str, Any] = {"data": None, "timestamp": 0.0}


class ModulesHandler(BaseHandler):
    """Handler für Modul-Paketverwaltung und Modularer Core Lifecycle."""

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self.modules_dir = self._resolve_modules_dir()

    @property
    def profile_name(self) -> str:
        return "modules"

    @property
    def target_file(self) -> Path:
        return self.modules_dir

    def _resolve_modules_dir(self) -> Path:
        """Findet das kanonische .MODULES-Verzeichnis."""
        candidates = [
            self.base_path.parent / ".MODULES",
            self.base_path / ".MODULES",
            Path("C:/_Local_DEV/repos/bach/.MODULES"),
        ]
        for c in candidates:
            if c.is_dir():
                return c
        # Fallback: parent/.MODULES anlegen
        target = self.base_path.parent / ".MODULES"
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _resolve_source_dirs(self) -> List[Path]:
        """Ermittelt Quellverzeichnisse für Modul-Updates."""
        dirs: List[Path] = []
        cands = [
            self.base_path / "exports" / "modules",
            self.base_path / "system" / "exports" / "modules",
            self.base_path.parent / "system" / "exports" / "modules",
            Path("C:/_Local_DEV/repos"),
            Path("C:/_Local_DEV/repos/bach/system/exports/modules"),
        ]
        for c in cands:
            if c.is_dir() and c not in dirs:
                dirs.append(c)
        return dirs

    def get_operations(self) -> dict:
        return {
            "list": "Alle installierten Module in .MODULES auflisten",
            "status": "Modularisierungs- und Hot-Wiring-Status anzeigen",
            "check": "Integrität und Manifeste validieren (bach modules check [name])",
            "check-updates": "Auf verfügbare neuere Modulversionen prüfen",
            "auto-update": "Hintergrund-Zyklus zur automatisierten Modul-Aktualisierung (bach modules auto-update [--apply] [--dry-run])",
            "install": "Modul aus Pfad oder ZIP installieren (bach modules install <path|zip>)",
            "update": "Module auf neueste Versionen aktualisieren (bach modules update [--dry-run])",
            "feed": "Remote-Manifest-Feeds verwalten (bach modules feed list|add|remove|sync)",
            "rollback": "Modul auf letzte Sicherung zurücksetzen (bach modules rollback <name>)",
            "pin": "Modulversion fixieren (bach modules pin <name> [version])",
            "unpin": "Modulversions-Pin aufheben (bach modules unpin <name>)",
            "pins": "Fixierte und unter Quarantäne stehende Modulversionen anzeigen",
            "export": "Modul als Standalone-Paket exportieren (bach modules export <name>)",
            "pack": "Modul als Standalone-Bundle mit Prüfsumme packen (bach modules pack <name> [--out DIR] [--bundle-deps])",
            "schedule": "Auto-Update-Job im Daemon Scheduler registrieren/konfigurieren (bach modules schedule [--interval-hours N])",
            "wire": "Hot-Wiring für alle Standalone-Module ausführen",
            "help": "Hilfe anzeigen",
        }

    def handle(self, operation: str, args: List[str] = None, dry_run: bool = False) -> Tuple[bool, str]:
        args = list(args or [])
        op = (operation or "status").lower().strip()

        if op == "list":
            return self._list_modules()
        elif op == "status":
            return self._status()
        elif op == "check":
            target = args[0] if args else None
            return self._check_modules(target)
        elif op in ("check-updates", "update-check", "check_updates"):
            return self._check_updates_cli()
        elif op in ("auto-update", "auto_update"):
            apply_updates = any(a in ("--apply", "-a", "--force") for a in args)
            is_dry = dry_run or any(a in ("--dry-run", "-n") for a in args)
            return self._auto_update_cycle(apply_updates=apply_updates, dry_run=is_dry)
        elif op == "install":
            if not args:
                return False, "Fehler: Pfad oder ZIP-Datei erforderlich: bach modules install <pfad_oder_zip>"
            return self._install_module(args[0], dry_run=dry_run)
        elif op == "update":
            is_dry = dry_run or any(a in ("--dry-run", "-n") for a in args)
            return self._update_modules(dry_run=is_dry)
        elif op == "export":
            if not args:
                return False, "Fehler: Modulname erforderlich: bach modules export <name>"
            out_dir = None
            if "--out" in args:
                idx = args.index("--out")
                if idx + 1 < len(args):
                    out_dir = args[idx + 1]
            return self._export_module(args[0], out_dir=out_dir)
        elif op == "pack":
            if not args:
                return False, "Fehler: Modulname erforderlich: bach modules pack <name> [--out DIR] [--bundle-deps]"
            name = args[0]
            bundle_deps = any(a in ("--bundle-deps", "--bundle", "-b") for a in args)
            out_dir = None
            if "--out" in args:
                idx = args.index("--out")
                if idx + 1 < len(args):
                    out_dir = args[idx + 1]
            return self._pack_module(name, out_dir=out_dir, bundle_deps=bundle_deps)
        elif op in ("schedule", "scheduler-sync", "daemon-sync"):
            interval = 6
            for a in args:
                if a.isdigit():
                    interval = int(a)
                elif a.startswith("--interval-hours="):
                    interval = int(a.split("=")[1])
            res = ensure_scheduler_auto_update_job(interval_hours=interval)
            stat = "angelegt" if res["created"] else "aktualisiert"
            return True, f"[OK] Scheduler-Job '{res['name']}' erfolgreich {stat} (Intervall: {res['schedule']})."
        elif op in ("wire", "hotwire", "hot-wire"):
            return self._wire_modules()
        elif op == "feed":
            sub_op = args[0].lower() if args else "list"
            sub_args = args[1:] if len(args) > 1 else []
            if sub_op == "list":
                return self._list_feeds_cli()
            elif sub_op == "add":
                if not sub_args:
                    return False, "Fehler: URL oder Pfad erforderlich: bach modules feed add <url|pfad> [--name NAME]"
                name = None
                if "--name" in sub_args:
                    n_idx = sub_args.index("--name")
                    if n_idx + 1 < len(sub_args):
                        name = sub_args[n_idx + 1]
                return self.add_feed(sub_args[0], name=name)
            elif sub_op in ("remove", "rm", "del"):
                if not sub_args:
                    return False, "Fehler: Feed-ID oder URL erforderlich: bach modules feed remove <id|url>"
                return self.remove_feed(sub_args[0])
            elif sub_op in ("sync", "update"):
                res = self.sync_feeds()
                return True, f"[OK] {res['feeds_count']} Feeds synchronisiert ({res['modules_count']} Moduldefinitionen im Cache)."
            else:
                return False, f"Unbekannte Feed-Operation '{sub_op}'. Verfügbar: list, add, remove, sync"
        elif op == "rollback":
            if not args:
                return False, "Fehler: Modulname erforderlich: bach modules rollback <name>"
            return self._rollback_module(args[0])
        elif op == "pin":
            if not args:
                return False, "Fehler: Modulname erforderlich: bach modules pin <name> [version] [--reason TEXT]"
            mod_name = args[0]
            ver = None
            reason = ""
            for a in args[1:]:
                if a.startswith("--reason="):
                    reason = a.split("=", 1)[1]
                elif not a.startswith("-") and not ver:
                    ver = a
            return self.pin_version(mod_name, version=ver, reason=reason)
        elif op == "unpin":
            if not args:
                return False, "Fehler: Modulname erforderlich: bach modules unpin <name>"
            return self.unpin_version(args[0])
        elif op in ("pins", "quarantined"):
            return self._list_pins_cli()
        elif op == "help":
            return self._help()
        else:
            ops = ", ".join(self.get_operations().keys())
            return False, f"Unbekannte Operation '{operation}'. Verfügbar: {ops}"

    # -------------------------------------------------------------------------
    # DATA API (für Web-GUI & programmatic access)
    # -------------------------------------------------------------------------

    def get_modules_data(self) -> List[Dict[str, Any]]:
        """Gibt strukturierte Daten aller Module in .MODULES/ zurück."""
        modules = []
        if not self.modules_dir.exists():
            return modules

        for item in sorted(self.modules_dir.iterdir()):
            if not item.is_dir() or item.name.startswith("."):
                continue
            manifest_file = item / "manifest.json"
            meta: Dict[str, Any] = {
                "name": item.name,
                "version": "0.0.0",
                "has_manifest": False,
                "selfcontained": False,
                "path": str(item),
                "description": "",
                "entrypoint": None,
                "has_tests": False,
            }
            if manifest_file.is_file():
                try:
                    data = json.loads(manifest_file.read_text(encoding="utf-8"))
                    meta["has_manifest"] = True
                    meta["name"] = data.get("name", item.name)
                    meta["version"] = data.get("version", "1.0.0")
                    meta["selfcontained"] = bool(data.get("selfcontained", False))
                    meta["description"] = data.get("description", "")
                    entrypoints = data.get("entrypoints", {})
                    meta["entrypoint"] = entrypoints.get("library")
                except Exception:
                    meta["has_manifest"] = False

            test_dir = item / "tests"
            if test_dir.is_dir() and any(test_dir.glob("test_*.py")):
                meta["has_tests"] = True

            modules.append(meta)
        return modules

    def get_status_data(self) -> Dict[str, Any]:
        """Gibt detaillierte Modularisierungsstatistiken zurück."""
        status_map = ocean_modularized_services_status()
        detection = detect_legacy_in_tree_services()
        installed = self.get_modules_data()

        total_services = len(status_map)
        standalone_bound = sum(1 for v in status_map.values() if v.get("standalone"))
        bound_count = sum(1 for v in status_map.values() if v.get("bound"))

        return {
            "schema": "bach.modules-status.v1",
            "modules_dir": str(self.modules_dir),
            "installed_modules_count": len(installed),
            "modularized_services_total": total_services,
            "standalone_bound_count": standalone_bound,
            "bound_count": bound_count,
            "coverage_percent": round((standalone_bound / total_services * 100.0) if total_services > 0 else 0.0, 1),
            "in_tree_detection": {
                "total_in_tree": detection.get("total_in_tree_services", 0),
                "switched": detection.get("switched_or_switchable_count", 0),
                "legacy_only": detection.get("legacy_in_tree_only_count", 0),
            },
            "services": status_map,
        }

    # -------------------------------------------------------------------------
    # CLI ACTIONS
    # -------------------------------------------------------------------------

    def _list_modules(self) -> Tuple[bool, str]:
        modules = self.get_modules_data()
        lines = [
            "=== BACH STANDALONE MODULES (.MODULES) ===",
            f"Verzeichnis: {self.modules_dir}",
            f"Gefundene Module: {len(modules)}",
            "",
            f"  {'MODUL':<28} {'VERSION':<10} {'MANIFEST':<10} {'TESTS':<8} BESCHREIBUNG",
            "  " + "-" * 76,
        ]
        for m in modules:
            man_str = "[OK]" if m["has_manifest"] else "[FEHLT]"
            test_str = "[OK]" if m["has_tests"] else "[-]"
            desc = m["description"][:30] + ("..." if len(m["description"]) > 30 else "")
            lines.append(f"  {m['name']:<28} {m['version']:<10} {man_str:<10} {test_str:<8} {desc}")

        lines.append("")
        lines.append("Verwende 'bach modules check [name]' zur Detailprüfung.")
        return True, "\n".join(lines)

    def _status(self) -> Tuple[bool, str]:
        st = self.get_status_data()
        lines = [
            "=== MODULARER CORE & UPDATE-ZENTRALE STATUS ===",
            f"Speicherort:               {st['modules_dir']}",
            f"Installierte Module:       {st['installed_modules_count']}",
            f"Modularisierte Dienste:    {st['modularized_services_total']}",
            f"Gebunden als Standalone:   {st['standalone_bound_count']} / {st['modularized_services_total']} ({st['coverage_percent']}%)",
            "",
            "Status der gebundenen Kern-Dienste:",
            f"  {'DIENST':<28} {'TYP':<14} STATUS",
            "  " + "-" * 55,
        ]
        for s_name, s_info in sorted(st["services"].items()):
            stat_type = "Standalone" if s_info.get("standalone") else "Legacy Hub"
            stat_flag = "[BOUND]" if s_info.get("bound") else "[FEHLER]"
            lines.append(f"  {s_name:<28} {stat_type:<14} {stat_flag}")

        lines.append("")
        lines.append("Befehle:")
        lines.append("  bach modules update [--dry-run]   Module aus Quell-Repositories aktualisieren")
        lines.append("  bach modules wire                 Hot-Wiring ausführen")
        return True, "\n".join(lines)

    def _check_modules(self, target: Optional[str] = None) -> Tuple[bool, str]:
        modules = self.get_modules_data()
        if target:
            modules = [m for m in modules if m["name"].lower() == target.lower()]
            if not modules:
                return False, f"Modul '{target}' nicht in .MODULES/ gefunden."

        lines = ["=== MODUL-INTEGRITAETSPRÜFUNG ===", ""]
        all_ok = True

        for m in modules:
            mod_dir = Path(m["path"])
            issues: List[str] = []

            if not m["has_manifest"]:
                issues.append("manifest.json fehlt oder ist ungültig")
            else:
                entrypoint = m.get("entrypoint")
                if entrypoint:
                    ep_path = mod_dir / entrypoint
                    if not ep_path.is_file():
                        issues.append(f"Entrypoint '{entrypoint}' existiert nicht")
                else:
                    issues.append("Kein entrypoints.library im Manifest definiert")

            if not m["has_tests"]:
                issues.append("Keine Testdateien (tests/test_*.py) gefunden")

            status = "[OK]" if not issues else "[WARNUNG]"
            if issues:
                all_ok = False
            lines.append(f"• {m['name']} v{m['version']}: {status}")
            for iss in issues:
                lines.append(f"    - {iss}")

        lines.append("")
        lines.append(f"Gesamtergebnis: {'Alle Module intakt.' if all_ok else 'Warnungen bei einigen Modulen festgestellt.'}")
        return all_ok, "\n".join(lines)

    # -------------------------------------------------------------------------
    # MANIFEST-FEEDS & REMOTE REGISTRY (TASK -46)
    # -------------------------------------------------------------------------

    def _resolve_feeds_file(self) -> Path:
        return self.modules_dir / ".feeds.json"

    def _resolve_feed_cache_file(self) -> Path:
        return self.modules_dir / ".feed_cache.json"

    def get_feeds(self) -> List[Dict[str, Any]]:
        feeds_file = self._resolve_feeds_file()
        feeds: List[Dict[str, Any]] = []
        if feeds_file.is_file():
            try:
                data = json.loads(feeds_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    feeds = data
                elif isinstance(data, dict):
                    feeds = data.get("feeds", [])
            except Exception:
                feeds = []

        env_feed = os.environ.get("BACH_MODULES_FEED")
        if env_feed and not any(f.get("url") == env_feed for f in feeds):
            feeds.append({
                "id": "env_default",
                "name": "Environment Feed",
                "url": env_feed,
                "enabled": True,
                "type": "remote" if env_feed.startswith("http") else "local",
            })
        local_default = self.base_path / "exports" / "modules" / "manifest_feed.json"
        if local_default.is_file() and not any(f.get("url") == str(local_default) for f in feeds):
            feeds.append({
                "id": "local_default",
                "name": "Local Default Feed",
                "url": str(local_default),
                "enabled": True,
                "type": "local",
            })
        return feeds

    def save_feeds(self, feeds: List[Dict[str, Any]]) -> None:
        feeds_file = self._resolve_feeds_file()
        feeds_file.parent.mkdir(parents=True, exist_ok=True)
        feeds_file.write_text(json.dumps(feeds, indent=2, ensure_ascii=False), encoding="utf-8")

    def add_feed(self, url_or_path: str, name: Optional[str] = None) -> Tuple[bool, str]:
        feeds = self.get_feeds()
        norm_url = url_or_path.strip()
        if any(f.get("url") == norm_url for f in feeds):
            return False, f"Feed '{norm_url}' ist bereits registriert."
        feed_id = f"feed_{int(time.time())}_{len(feeds)+1}"
        feed_name = name or Path(norm_url).stem or f"Feed-{len(feeds)+1}"
        is_remote = norm_url.startswith("http://") or norm_url.startswith("https://")
        new_feed = {
            "id": feed_id,
            "name": feed_name,
            "url": norm_url,
            "enabled": True,
            "type": "remote" if is_remote else "local",
            "added_at": datetime.now().isoformat(),
            "last_synced": None,
        }
        feeds.append(new_feed)
        self.save_feeds(feeds)
        return True, f"[OK] Feed '{feed_name}' ({norm_url}) erfolgreich registriert."

    def remove_feed(self, feed_id_or_url: str) -> Tuple[bool, str]:
        feeds = self.get_feeds()
        initial_len = len(feeds)
        feeds = [f for f in feeds if f.get("id") != feed_id_or_url and f.get("url") != feed_id_or_url]
        if len(feeds) == initial_len:
            return False, f"Feed '{feed_id_or_url}' nicht gefunden."
        self.save_feeds(feeds)
        return True, f"[OK] Feed '{feed_id_or_url}' entfernt."

    def sync_feeds(self, force: bool = False) -> Dict[str, Any]:
        """Holt Manifest-Feeds ab und speichert die Moduldefinitionen im Feed-Cache."""
        feeds = self.get_feeds()
        aggregated_modules: Dict[str, Dict[str, Any]] = {}
        sync_results: List[Dict[str, Any]] = []

        for f in feeds:
            if not f.get("enabled", True):
                continue
            url = f.get("url", "")
            feed_name = f.get("name", url)
            payload = None
            err = None
            try:
                if url.startswith("http://") or url.startswith("https://"):
                    req = urllib.request.Request(
                        url,
                        headers={"User-Agent": "BACH-ModularCore/1.0", "Accept": "application/json"}
                    )
                    with urllib.request.urlopen(req, timeout=5.0) as resp:
                        if resp.status == 200:
                            payload = json.loads(resp.read().decode("utf-8"))
                        else:
                            err = f"HTTP {resp.status}"
                else:
                    lp = Path(url)
                    if lp.is_file():
                        payload = json.loads(lp.read_text(encoding="utf-8"))
                    else:
                        err = f"Lokale Datei nicht gefunden: {lp}"
            except Exception as exc:
                err = str(exc)

            modules_count = 0
            if isinstance(payload, dict):
                m_list = payload.get("modules") or []
                for m in m_list:
                    if isinstance(m, dict) and m.get("name") and m.get("version"):
                        m_entry = dict(m)
                        m_entry["feed_id"] = f.get("id")
                        m_entry["feed_name"] = feed_name
                        m_key = f"{m['name']}@{m['version']}"
                        aggregated_modules[m_key] = m_entry
                        modules_count += 1
            elif isinstance(payload, list):
                for m in payload:
                    if isinstance(m, dict) and m.get("name") and m.get("version"):
                        m_entry = dict(m)
                        m_entry["feed_id"] = f.get("id")
                        m_entry["feed_name"] = feed_name
                        m_key = f"{m['name']}@{m['version']}"
                        aggregated_modules[m_key] = m_entry
                        modules_count += 1

            sync_results.append({
                "feed_id": f.get("id"),
                "name": feed_name,
                "url": url,
                "success": payload is not None,
                "error": err,
                "modules_count": modules_count,
            })
            f["last_synced"] = datetime.now().isoformat()
            if err:
                f["last_error"] = err
            else:
                f.pop("last_error", None)

        self.save_feeds(feeds)

        cache_data = {
            "schema": "bach.modules-feed-cache.v1",
            "synced_at": datetime.now().isoformat(),
            "modules": list(aggregated_modules.values()),
            "feeds_count": len(feeds),
            "modules_count": len(aggregated_modules),
            "results": sync_results,
        }
        cache_file = self._resolve_feed_cache_file()
        cache_file.write_text(json.dumps(cache_data, indent=2, ensure_ascii=False), encoding="utf-8")
        return cache_data

    def get_feed_modules(self) -> List[Dict[str, Any]]:
        cache_file = self._resolve_feed_cache_file()
        if cache_file.is_file():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                return data.get("modules", [])
            except Exception:
                pass
        cache = self.sync_feeds()
        return cache.get("modules", [])

    def _list_feeds_cli(self) -> Tuple[bool, str]:
        feeds = self.get_feeds()
        lines = [
            "=== BACH MODUL MANIFEST-FEEDS ===",
            f"Registrierte Feeds: {len(feeds)}",
            "",
            f"  {'ID':<16} {'NAME':<20} {'TYP':<8} URL",
            "  " + "-" * 70,
        ]
        for f in feeds:
            lines.append(f"  {f.get('id', ''):<16} {f.get('name', ''):<20} {f.get('type', ''):<8} {f.get('url', '')}")
        lines.append("")
        lines.append("Verwende 'bach modules feed sync' zum Aktualisieren der Feeds.")
        return True, "\n".join(lines)

    # -------------------------------------------------------------------------
    # VERSION-PINS & AUTO-HEAL ROLLBACK (TASK -48)
    # -------------------------------------------------------------------------

    def _resolve_pins_file(self) -> Path:
        return self.modules_dir / ".version_pins.json"

    def get_version_pins(self) -> Dict[str, Any]:
        pins_file = self._resolve_pins_file()
        if pins_file.is_file():
            try:
                data = json.loads(pins_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {
            "schema": "bach.version-pins.v1",
            "pins": {},
            "quarantined": {},
            "history": [],
        }

    def save_version_pins(self, data: Dict[str, Any]) -> None:
        pins_file = self._resolve_pins_file()
        pins_file.parent.mkdir(parents=True, exist_ok=True)
        pins_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def pin_version(self, module_name: str, version: Optional[str] = None, reason: str = "") -> Tuple[bool, str]:
        pins_data = self.get_version_pins()
        target_dir = self.modules_dir / module_name
        if not version:
            if not target_dir.is_dir():
                return False, f"Modul '{module_name}' ist nicht installiert; Version muss explizit angegeben werden."
            m_file = target_dir / "manifest.json"
            if m_file.is_file():
                try:
                    version = json.loads(m_file.read_text(encoding="utf-8")).get("version", "1.0.0")
                except Exception:
                    version = "1.0.0"
            else:
                version = "1.0.0"

        pins_data.setdefault("pins", {})[module_name] = {
            "pinned_version": version,
            "pinned_at": datetime.now().isoformat(),
            "reason": reason or "Manuell fixiert",
        }
        pins_data.setdefault("history", []).append({
            "module": module_name,
            "action": "pin",
            "version": version,
            "timestamp": datetime.now().isoformat(),
            "reason": reason,
        })
        self.save_version_pins(pins_data)
        return True, f"[OK] Modul '{module_name}' auf Version v{version} fixiert (keine automatischen Upgrades)."

    def unpin_version(self, module_name: str) -> Tuple[bool, str]:
        pins_data = self.get_version_pins()
        pins = pins_data.get("pins", {})
        if module_name not in pins:
            return False, f"Modul '{module_name}' war nicht fixiert."
        removed = pins.pop(module_name)
        pins_data.setdefault("history", []).append({
            "module": module_name,
            "action": "unpin",
            "previous_version": removed.get("pinned_version"),
            "timestamp": datetime.now().isoformat(),
        })
        self.save_version_pins(pins_data)
        return True, f"[OK] Versions-Pin für Modul '{module_name}' aufgehoben."

    def quarantine_version(self, module_name: str, version: str, reason: str, source: str = "") -> None:
        pins_data = self.get_version_pins()
        q_list = pins_data.setdefault("quarantined", {}).setdefault(module_name, [])
        if not any(item.get("version") == version for item in q_list):
            q_list.append({
                "version": version,
                "quarantined_at": datetime.now().isoformat(),
                "reason": reason,
                "source": source,
            })
        pins_data.setdefault("history", []).append({
            "module": module_name,
            "action": "quarantine",
            "version": version,
            "timestamp": datetime.now().isoformat(),
            "reason": reason,
        })
        self.save_version_pins(pins_data)

    def is_version_quarantined(self, module_name: str, version: str) -> bool:
        pins_data = self.get_version_pins()
        q_list = pins_data.get("quarantined", {}).get(module_name, [])
        return any(item.get("version") == version for item in q_list)

    def is_module_pinned(self, module_name: str) -> Optional[str]:
        pins_data = self.get_version_pins()
        pin = pins_data.get("pins", {}).get(module_name)
        if pin and isinstance(pin, dict):
            return pin.get("pinned_version")
        return None

    def _verify_module(self, module_dir: Path) -> Tuple[bool, str]:
        """Prüft Syntax aller Python-Dateien und Manifest-Vollständigkeit."""
        manifest_file = module_dir / "manifest.json"
        if not manifest_file.is_file():
            return False, "manifest.json fehlt im Modul-Wurzelverzeichnis"

        try:
            meta = json.loads(manifest_file.read_text(encoding="utf-8"))
        except Exception as exc:
            return False, f"manifest.json ist kein gültiges JSON: {exc}"

        if not meta.get("name"):
            return False, "Feld 'name' fehlt im Manifest"
        if not meta.get("version"):
            return False, "Feld 'version' fehlt im Manifest"

        entrypoints = meta.get("entrypoints", {})
        lib_ep = entrypoints.get("library")
        if lib_ep:
            ep_file = module_dir / lib_ep
            if not ep_file.is_file():
                return False, f"Deklarierter Entrypoint '{lib_ep}' nicht gefunden"

        syntax_errors = []
        for root, _, files in os.walk(module_dir):
            for f in files:
                if f.endswith(".py"):
                    py_path = Path(root) / f
                    try:
                        code = py_path.read_text(encoding="utf-8", errors="replace")
                        compile(code, str(py_path), "exec")
                    except Exception as err:
                        syntax_errors.append(f"{py_path.name}: {err}")

        if syntax_errors:
            return False, "Syntax-Fehler in Modul-Code: " + "; ".join(syntax_errors)

        return True, "Validierung erfolgreich"

    def _rollback_module(
        self,
        name: str,
        auto_heal: bool = False,
        reason: str = "",
        failed_version: str = "",
    ) -> Tuple[bool, str]:
        """Setzt ein Modul auf die jüngste Sicherung aus .MODULES/.backup zurück."""
        backup_parent = self.modules_dir / ".backup"
        if not backup_parent.is_dir():
            return False, f"Kein Backup-Verzeichnis für Modul '{name}' vorhanden."

        candidates = sorted(
            [d for d in backup_parent.iterdir() if d.is_dir() and d.name.startswith(f"{name}_")],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            return False, f"Keine Sicherung für Modul '{name}' gefunden."

        latest_backup = candidates[0]
        target_dir = self.modules_dir / name

        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.copytree(latest_backup, target_dir)

        restored_ver = "unbekannt"
        m_file = target_dir / "manifest.json"
        if m_file.is_file():
            try:
                restored_ver = json.loads(m_file.read_text(encoding="utf-8")).get("version", "1.0.0")
            except Exception:
                pass

        if auto_heal and failed_version:
            self.quarantine_version(
                name,
                failed_version,
                reason=reason or "Automatischer Rollback nach fehlgeschlagener Validierung",
            )

        invalidate_module_cache()
        auto_switch_to_standalone_modules()

        action_tag = "[AUTO-HEAL]" if auto_heal else "[ROLLBACK]"
        msg = (
            f"{action_tag} Modul '{name}' erfolgreich auf Stand aus {latest_backup.name} "
            f"(Version v{restored_ver}) zurückgesetzt."
        )
        if auto_heal:
            msg += f"\nFehlerhafte Version v{failed_version} wurde unter Quarantäne gestellt."
        return True, msg

    def _list_pins_cli(self) -> Tuple[bool, str]:
        data = self.get_version_pins()
        pins = data.get("pins", {})
        quarantined = data.get("quarantined", {})
        lines = [
            "=== BACH MODUL-VERSION-PINS & QUARANTÄNE ===",
            "",
            "Fixierte Versionen (Pins):",
        ]
        if not pins:
            lines.append("  (Keine Module fixiert)")
        else:
            for m, p in pins.items():
                lines.append(f"  • {m:<20} v{p.get('pinned_version')} (seit {p.get('pinned_at')}) Grund: {p.get('reason')}")

        lines.append("")
        lines.append("Unter Quarantäne stehende Versionen:")
        if not quarantined:
            lines.append("  (Keine Versionen in Quarantäne)")
        else:
            for m, q_list in quarantined.items():
                lines.append(f"  • {m}:")
                for q in q_list:
                    lines.append(f"      - v{q.get('version')} ({q.get('quarantined_at')}): {q.get('reason')}")

        return True, "\n".join(lines)

    def _install_module(self, source_path_str: str, dry_run: bool = False, expected_sha: Optional[str] = None) -> Tuple[bool, str]:
        download_tmp: Optional[Path] = None
        if source_path_str.startswith("http://") or source_path_str.startswith("https://"):
            dl_dir = self.modules_dir / ".tmp_downloads"
            dl_dir.mkdir(parents=True, exist_ok=True)
            download_tmp = dl_dir / f"mod_dl_{int(time.time())}_{int(time.time()*1000)%1000}.zip"
            try:
                req = urllib.request.Request(source_path_str, headers={"User-Agent": "BACH-ModularCore/1.0"})
                with urllib.request.urlopen(req, timeout=15.0) as resp, open(download_tmp, "wb") as out_f:
                    shutil.copyfileobj(resp, out_f)
                source = download_tmp
            except Exception as dl_err:
                if download_tmp and download_tmp.exists():
                    download_tmp.unlink(missing_ok=True)
                return False, f"Fehler beim Herunterladen von {source_path_str}: {dl_err}"
        else:
            source = Path(source_path_str)
            if not source.exists():
                return False, f"Quelldatei oder -verzeichnis existiert nicht: {source}"

        tmp_extract_dir: Optional[Path] = None
        inspect_dir = source

        try:
            if source.is_file() and source.suffix.lower() == ".zip":
                # Optional: SHA-256 Prüfsummenvalidierung
                sha_candidate = source.with_suffix(".zip.sha256")
                if not sha_candidate.is_file():
                    sha_candidate = Path(str(source) + ".sha256")
                exp_sha = expected_sha
                if not exp_sha and sha_candidate.is_file():
                    exp_sha = sha_candidate.read_text(encoding="utf-8").split()[0].strip()
                if exp_sha:
                    import hashlib
                    hasher = hashlib.sha256()
                    with open(source, "rb") as f:
                        while chunk := f.read(65536):
                            hasher.update(chunk)
                    if hasher.hexdigest().lower() != exp_sha.lower():
                        return False, f"Prüfsummen-Fehler bei {source.name}: Erwartet {exp_sha}, berechnet {hasher.hexdigest()}"

                tmp_extract_dir = self.modules_dir / f".tmp_extract_{int(time.time())}"
                tmp_extract_dir.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(source, "r") as zf:
                    zf.extractall(tmp_extract_dir)
                found = list(tmp_extract_dir.glob("**/manifest.json"))
                if not found:
                    return False, f"Ungültiges Modul-ZIP: kein manifest.json gefunden in {source}"
                inspect_dir = found[0].parent

            manifest_file = inspect_dir / "manifest.json"
            if not manifest_file.is_file():
                return False, f"manifest.json nicht gefunden in {inspect_dir}"

            try:
                meta = json.loads(manifest_file.read_text(encoding="utf-8"))
            except Exception as exc:
                return False, f"manifest.json konnte nicht geparst werden: {exc}"

            name = meta.get("name")
            version = meta.get("version", "1.0.0")
            if not name:
                return False, "Fehlender 'name' im Manifest."

            target_dir = self.modules_dir / name

            if dry_run:
                return True, f"[DRY-RUN] Modul '{name}' v{version} würde nach {target_dir} installiert."

            # Backup erstellen falls existent
            backup_dir = None
            if target_dir.is_dir():
                backup_dir = self.modules_dir / ".backup" / f"{name}_{int(time.time())}"
                backup_dir.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(target_dir, backup_dir)

            # Installation durchführen
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(inspect_dir, target_dir)

            # AUTO-HEAL: Validierung nach Installation
            is_valid, err_msg = self._verify_module(target_dir)
            if not is_valid:
                if backup_dir and backup_dir.is_dir():
                    self._rollback_module(name, auto_heal=True, reason=err_msg, failed_version=version)
                    return False, (
                        f"[AUTO-HEAL] Validierung von Modul '{name}' v{version} fehlgeschlagen:\n"
                        f"  {err_msg}\n"
                        f"Automatisches Rollback auf vorherigen Stand erfolgreich durchgeführt. Version v{version} unter Quarantäne gestellt."
                    )
                else:
                    return False, f"Validierung von Modul '{name}' v{version} fehlgeschlagen: {err_msg}"

            invalidate_module_cache()
            wire_report = auto_switch_to_standalone_modules()

            return True, (
                f"[OK] Modul '{name}' v{version} erfolgreich installiert nach {target_dir}.\n"
                f"Hot-Wiring ausgeführt ({wire_report['total_switched']} Module verdrahtet)."
            )
        finally:
            if tmp_extract_dir:
                shutil.rmtree(tmp_extract_dir, ignore_errors=True)
            if download_tmp and download_tmp.exists():
                download_tmp.unlink(missing_ok=True)

    def check_for_updates(self, cache_ttl_sec: int = 60) -> Dict[str, Any]:
        """Prüft Quellpfade auf verfügbare neuere Modulversionen (mit Caching)."""
        global _MODULES_UPDATE_CACHE
        now = time.time()
        if _MODULES_UPDATE_CACHE["data"] is not None and (now - _MODULES_UPDATE_CACHE["timestamp"]) < cache_ttl_sec:
            cached_res = dict(_MODULES_UPDATE_CACHE["data"])
            cached_res["cached"] = True
            return cached_res

        installed = {m["name"]: m for m in self.get_modules_data()}
        source_dirs = self._resolve_source_dirs()
        updates_found: List[Dict[str, Any]] = []

        for s_dir in source_dirs:
            if not s_dir.is_dir():
                continue
            try:
                for cand in s_dir.iterdir():
                    if not cand.is_dir():
                        continue
                    m_file = cand / "manifest.json"
                    if not m_file.is_file():
                        continue
                    try:
                        meta = json.loads(m_file.read_text(encoding="utf-8"))
                        c_name = meta.get("name")
                        c_ver = meta.get("version", "1.0.0")
                        if c_name in installed:
                            cur_ver = installed[c_name]["version"]
                            if parse_semver(c_ver) > parse_semver(cur_ver):
                                updates_found.append({
                                    "name": c_name,
                                    "current_version": cur_ver,
                                    "new_version": c_ver,
                                    "source": str(cand),
                                })
                    except Exception:
                        pass
            except OSError:
                pass

        # Prüfe Manifest-Feeds (TASK -46)
        try:
            feed_modules = self.get_feed_modules()
            for fm in feed_modules:
                f_name = fm.get("name")
                f_ver = fm.get("version", "1.0.0")
                if not f_name or f_name not in installed:
                    continue
                cur_ver = installed[f_name]["version"]
                pin = self.is_module_pinned(f_name)
                if pin and pin == cur_ver:
                    continue
                if self.is_version_quarantined(f_name, f_ver):
                    continue
                if parse_semver(f_ver) > parse_semver(cur_ver):
                    dl_url = fm.get("download_url") or fm.get("url")
                    if dl_url and not any(u["name"] == f_name for u in updates_found):
                        updates_found.append({
                            "name": f_name,
                            "current_version": cur_ver,
                            "new_version": f_ver,
                            "source": f"feed:{fm.get('feed_name', 'remote')}",
                            "download_url": dl_url,
                            "sha256": fm.get("sha256"),
                            "source_type": "feed",
                        })
        except Exception:
            pass

        result = {
            "schema": "bach.modules-update-check.v1",
            "has_updates": len(updates_found) > 0,
            "updates_count": len(updates_found),
            "updates": updates_found,
            "checked_sources": [str(d) for d in source_dirs],
            "total_installed": len(installed),
            "timestamp": now,
            "cached": False,
        }
        _MODULES_UPDATE_CACHE["data"] = result
        _MODULES_UPDATE_CACHE["timestamp"] = now
        return result

    def _check_updates_cli(self) -> Tuple[bool, str]:
        res = self.check_for_updates(cache_ttl_sec=0)
        lines = [
            "=== MODUL-UPDATE-CHECK ===",
            f"Installierte Module: {res['total_installed']}",
            f"Geprüfte Quellen:   {len(res['checked_sources'])}",
            "",
        ]
        if not res["has_updates"]:
            lines.append("[INFO] Keine Modul-Updates verfügbar. Alle Module sind auf dem neuesten Stand.")
            return True, "\n".join(lines)

        lines.append(f"Verfügbare Updates ({res['updates_count']}):")
        for u in res["updates"]:
            lines.append(f"  • {u['name']:<24} v{u['current_version']} -> v{u['new_version']} (Quelle: {u['source']})")
        lines.append("")
        lines.append("Führe 'bach modules update' aus, um alle Updates zu installieren.")
        return True, "\n".join(lines)

    def _auto_update_cycle(self, apply_updates: bool = False, dry_run: bool = False) -> Tuple[bool, str]:
        """Führt einen automatisierten Prüf- und Aktualisierungszyklus aus."""
        check = self.check_for_updates(cache_ttl_sec=0)
        has_upd = bool(check.get("has_updates"))
        upd_count = int(check.get("updates_count", 0))
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines = [
            "=== MODUL AUTO-UPDATE RUNNER ===",
            f"Prüfzeitpunkt:        {now_str}",
            f"Installierte Module:  {check.get('total_installed', 0)}",
            f"Verfügbare Updates:   {upd_count}",
            f"Modus:                {'Automatisches Upgrade (--apply)' if apply_updates else 'Monitoring / Benachrichtigung'}",
            "",
        ]

        if not has_upd:
            lines.append("[OK] Alle Module sind aktuell. Keine Hintergrund-Aktion erforderlich.")
            return True, "\n".join(lines)

        for u in check.get("updates", []):
            lines.append(f"  • {u['name']:<24} v{u['current_version']} -> v{u['new_version']} ({u['source']})")

        if not apply_updates:
            lines.append("")
            lines.append(f"[HINWEIS] {upd_count} Modul-Update(s) erkannt. Führe 'bach modules auto-update --apply' oder 'bach modules update' aus.")
            return True, "\n".join(lines)

        lines.append("")
        lines.append("Starte automatisches Modul-Update...")
        ok_upd, msg_upd = self._update_modules(dry_run=dry_run)
        lines.append(msg_upd)
        return ok_upd, "\n".join(lines)

    def _update_modules(self, dry_run: bool = False) -> Tuple[bool, str]:
        """Sucht nach neueren Modulversionen in allen Quellpfaden & Feeds und aktualisiert sie."""
        global _MODULES_UPDATE_CACHE
        check_res = self.check_for_updates(cache_ttl_sec=0)
        updates_found: List[Dict[str, Any]] = check_res.get("updates", [])

        lines = [
            "=== MODUL-UPDATE-SCAN ===",
            f"Prüfe {check_res.get('total_installed', 0)} installierte Module gegen {len(check_res.get('checked_sources', []))} Quellen...",
            "",
        ]

        if not updates_found:
            lines.append("[INFO] Alle installierten Module sind auf dem aktuellen Stand.")
            return True, "\n".join(lines)

        lines.append(f"Verfügbare Updates: {len(updates_found)}")
        success_count = 0
        for upd in updates_found:
            status_text = "[DRY-RUN] Würde aktualisieren" if dry_run else "[AKTUALISIERT]"
            lines.append(f"  • {upd['name']:<24} v{upd['current_version']} -> v{upd['new_version']} {status_text}")
            if not dry_run:
                src_to_install = upd.get("download_url") if upd.get("source_type") == "feed" else upd.get("source_path") or upd.get("source")
                if src_to_install:
                    ok_ins, msg_ins = self._install_module(str(src_to_install), dry_run=False, expected_sha=upd.get("sha256"))
                    if ok_ins:
                        success_count += 1
                    else:
                        lines.append(f"    [WARNUNG] {msg_ins}")

        if not dry_run:
            _MODULES_UPDATE_CACHE = {"data": None, "timestamp": 0.0}
            invalidate_module_cache()
            wire_res = auto_switch_to_standalone_modules()
            lines.append("")
            lines.append(f"[OK] {success_count} von {len(updates_found)} Modul(en) erfolgreich aktualisiert und hot-wired ({wire_res['total_switched']} aktiv).")
        else:
            lines.append("")
            lines.append("Hinweis: Führe 'bach modules update' ohne --dry-run aus, um die Updates anzuwenden.")

        return True, "\n".join(lines)

    def _export_module(self, name: str, out_dir: Optional[str] = None) -> Tuple[bool, str]:
        """Exportiert ein Modul aus .MODULES/ als ZIP-Archiv."""
        target_dir = self.modules_dir / name
        if not target_dir.is_dir():
            return False, f"Modul '{name}' nicht in .MODULES/ gefunden."

        dest_dir = Path(out_dir) if out_dir else (self.base_path / "exports" / "modules")
        dest_dir.mkdir(parents=True, exist_ok=True)

        manifest_file = target_dir / "manifest.json"
        version = "1.0.0"
        if manifest_file.is_file():
            try:
                meta = json.loads(manifest_file.read_text(encoding="utf-8"))
                version = meta.get("version", "1.0.0")
            except Exception:
                pass

        zip_name = f"{name}_v{version}_{time.strftime('%Y%m%d_%H%M%S')}.zip"
        zip_path = dest_dir / zip_name

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(target_dir):
                for f in files:
                    full_p = Path(root) / f
                    rel_p = full_p.relative_to(target_dir)
                    zf.write(full_p, rel_p)

        return True, f"[OK] Modul '{name}' v{version} exportiert nach:\n  {zip_path}"

    def _pack_module(
        self,
        name: str,
        out_dir: Optional[str] = None,
        bundle_deps: bool = False,
    ) -> Tuple[bool, str]:
        """Erstellt ein autarkes, verteilbares Bundle-Paket eines Moduls mit Prüfsumme und optionaler Vendor-Isolation."""
        target_dir = self.modules_dir / name
        if not target_dir.is_dir():
            return False, f"Modul '{name}' nicht in .MODULES/ gefunden."

        manifest_file = target_dir / "manifest.json"
        if not manifest_file.is_file():
            return False, f"Modul '{name}' besitzt kein manifest.json."

        try:
            meta = json.loads(manifest_file.read_text(encoding="utf-8"))
        except Exception as exc:
            return False, f"Manifest konnte nicht gelesen werden: {exc}"

        version = meta.get("version", "1.0.0")
        entrypoints = meta.get("entrypoints", {})
        deps = meta.get("dependencies", {})

        dest_dir = Path(out_dir) if out_dir else (self.base_path / "exports" / "modules")
        dest_dir.mkdir(parents=True, exist_ok=True)

        bundle_tag = "bundle" if bundle_deps else "pkg"
        zip_name = f"{name}_v{version}_{bundle_tag}_{time.strftime('%Y%m%d_%H%M%S')}.zip"
        zip_path = dest_dir / zip_name

        stage_dir = self.modules_dir / f".tmp_pack_{name}_{int(time.time())}"
        stage_dir.mkdir(parents=True, exist_ok=True)

        try:
            shutil.copytree(target_dir, stage_dir / name)
            mod_stage = stage_dir / name

            receipt_meta = {
                "name": name,
                "version": version,
                "entrypoints": entrypoints,
                "bundled_dependencies": bundle_deps,
                "dependencies": deps,
                "selfcontained": True,
                "packaged_at": datetime.now().isoformat(),
                "packaged_by": "bach.modules.pack.v1",
            }

            if bundle_deps:
                vendor_dir = mod_stage / "vendor"
                vendor_dir.mkdir(parents=True, exist_ok=True)
                v_loader = vendor_dir / "__init__.py"
                if not v_loader.exists():
                    v_loader.write_text(
                        "# -*- coding: utf-8 -*-\n"
                        "import sys\n"
                        "from pathlib import Path\n"
                        "_v_dir = Path(__file__).parent\n"
                        "if str(_v_dir) not in sys.path:\n"
                        "    sys.path.insert(0, str(_v_dir))\n",
                        encoding="utf-8"
                    )
                receipt_meta["vendor_dir"] = "vendor"

            receipt_file = mod_stage / "package_receipt.json"
            receipt_file.write_text(json.dumps(receipt_meta, indent=2, ensure_ascii=False), encoding="utf-8")

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(mod_stage):
                    for f in files:
                        full_p = Path(root) / f
                        rel_p = full_p.relative_to(mod_stage)
                        zf.write(full_p, rel_p)

            import hashlib
            hasher = hashlib.sha256()
            with open(zip_path, "rb") as f:
                while chunk := f.read(65536):
                    hasher.update(chunk)
            digest = hasher.hexdigest()
            sha_path = dest_dir / f"{zip_name}.sha256"
            sha_path.write_text(f"{digest}  {zip_name}\n", encoding="utf-8")

        finally:
            shutil.rmtree(stage_dir, ignore_errors=True)

        lines = [
            f"[OK] Modul '{name}' v{version} erfolgreich gepackt:",
            f"  Archiv:      {zip_path}",
            f"  Prüfsumme:   {digest[:16]}... ({sha_path.name})",
            f"  Bundle-Deps: {'Ja (vendor-isolated)' if bundle_deps else 'Nein'}",
        ]
        return True, "\n".join(lines)

    def pack_module(
        self,
        name: str,
        out_dir: Optional[Union[str, Path]] = None,
        bundle_deps: bool = False,
    ) -> Tuple[bool, str]:
        """Programmatischer Aufruf für Modulpaketierung."""
        return self._pack_module(name, out_dir=str(out_dir) if out_dir else None, bundle_deps=bundle_deps)

    def _wire_modules(self) -> Tuple[bool, str]:
        invalidate_module_cache()
        report = auto_switch_to_standalone_modules()
        lines = [
            "=== HOT-WIRING STANDALONE-MODULE ===",
            f"Erfolgreich verdrahtet: {report['total_switched']} Module",
            "",
            f"  {'MODUL':<28} {'STATUS':<14} DATEI",
            "  " + "-" * 60,
        ]
        for name, item in sorted(report.get("modules", {}).items()):
            stat = "Standalone" if item.get("switched") else "Legacy Hub"
            f_p = item.get("file", "")
            lines.append(f"  {name:<28} {stat:<14} {f_p}")
        return True, "\n".join(lines)

    def _help(self) -> Tuple[bool, str]:
        lines = [
            "BACH MODUL-PAKETMANAGER (bach modules)",
            "=" * 45,
            "",
            "Befehle:",
            "  bach modules list",
            "      Listet alle installierten autarken Standalone-Module in .MODULES/ auf.",
            "",
            "  bach modules status",
            "      Zeigt den aktuellen Modularisierungsgrad, gebundene Dienste und Coverage an.",
            "",
            "  bach modules check [name]",
            "      Prüft Manifest-Validität, Entrypoints und Testsuiten.",
            "",
            "  bach modules install <pfad_oder_zip>",
            "      Installiert oder aktualisiert ein Modul aus einem Verzeichnis oder ZIP-Archiv.",
            "",
            "  bach modules update [--dry-run]",
            "      Sucht nach neueren Versionen in Quell-Repos und aktualisiert installierte Module.",
            "",
            "  bach modules export <name> [--out DIR]",
            "      Erstellt ein autarkes, verteilbares ZIP-Archiv eines Moduls.",
            "",
            "  bach modules wire",
            "      Führt Hot-Wiring aller Standalone-Module in die laufende Bridge aus.",
            "",
            "Beispiele:",
            "  bach modules list",
            "  bach modules update --dry-run",
            "  bach modules install C:/Pfad/zu/mein_modul.zip",
            "  bach modules wire",
        ]
        return True, "\n".join(lines)


def run_modules_auto_update_runner(
    base_dir: Optional[Union[str, Path]] = None,
    apply_updates: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Programmatischer Einstiegspunkt für den Scheduler / Daemon-Runner."""
    handler = ModulesHandler(base_dir)
    ok, msg = handler._auto_update_cycle(apply_updates=apply_updates, dry_run=dry_run)
    check = handler.check_for_updates(cache_ttl_sec=0)
    return {
        "success": ok,
        "message": msg,
        "has_updates": check.get("has_updates", False),
        "updates_count": check.get("updates_count", 0),
        "applied": apply_updates and not dry_run,
        "timestamp": time.time(),
    }


def ensure_scheduler_auto_update_job(
    conn_or_db_path: Optional[Any] = None,
    interval_hours: int = 6,
    active: bool = True,
) -> Dict[str, Any]:
    """Registriert oder aktualisiert den periodischen Modul-Auto-Update-Job im Daemon Scheduler."""
    import sqlite3
    from hub.bach_paths import BACH_DB

    db_path = conn_or_db_path if isinstance(conn_or_db_path, (str, Path)) else BACH_DB
    job_name = "Modular Core Auto-Update"
    schedule_str = f"{max(1, interval_hours)}h"
    command_str = "python bach.py modules auto-update --apply"

    conn = sqlite3.connect(str(db_path)) if not hasattr(conn_or_db_path, "execute") else conn_or_db_path
    conn.row_factory = sqlite3.Row
    created = False
    job_id = None
    try:
        cur = conn.execute("SELECT id, is_active, schedule FROM scheduler_jobs WHERE name = ?", (job_name,))
        row = cur.fetchone()
        if row:
            job_id = row["id"]
            conn.execute(
                "UPDATE scheduler_jobs SET schedule = ?, is_active = ?, command = ? WHERE id = ?",
                (schedule_str, 1 if active else 0, command_str, job_id)
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO scheduler_jobs 
                (name, description, job_type, schedule, command, is_active, timeout_seconds, retry_on_fail, max_retries)
                VALUES (?, ?, 'interval', ?, ?, ?, 300, 1, 2)
                """,
                (
                    job_name,
                    "Prüft Quell-Repositories periodisch auf neuere Modulversionen und aktualisiert Standalone-Module in .MODULES/",
                    schedule_str,
                    command_str,
                    1 if active else 0,
                )
            )
            job_id = cur.lastrowid
            created = True
        if hasattr(conn, "commit"):
            conn.commit()
    finally:
        if not hasattr(conn_or_db_path, "execute"):
            conn.close()

    return {
        "job_id": job_id,
        "name": job_name,
        "schedule": schedule_str,
        "created": created,
        "active": active,
    }
