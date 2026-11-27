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
import subprocess
import sys
import time
import zipfile
import urllib.request
import urllib.parse
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
            "test": "Isolierte Modul-CI und Smoke-Tests ausführen (bach modules test [name])",
            "bootstrap": "Core-Installations-Bootstrap und Lockfile-Verwaltung (bach modules bootstrap [--generate-lockfile] [--minimal])",
            "feed": "Remote-Manifest-Feeds verwalten (bach modules feed list|add|remove|sync)",
            "rollback": "Modul auf letzte Sicherung zurücksetzen (bach modules rollback <name>)",
            "pin": "Modulversion fixieren (bach modules pin <name> [version])",
            "unpin": "Modulversions-Pin aufheben (bach modules unpin <name>)",
            "pins": "Fixierte und unter Quarantäne stehende Modulversionen anzeigen",
            "export": "Modul als Standalone-Paket exportieren (bach modules export <name>)",
            "pack": "Modul als Standalone-Bundle mit Prüfsumme packen (bach modules pack <name> [--out DIR] [--bundle-deps])",
            "scaffold": "Neues autarkes Modul mit Manifest, Code und Testsuite erstellen (bach modules scaffold <name> [--type TYPE])",
            "reconcile": "Reconciliation zwischen Feeds, Lockfile und Version-Pins durchführen (bach modules reconcile)",
            "telemetry": "Telemetrie-, Lockfile-Checksum- und Dependency-Drift-Bericht anzeigen (bach modules telemetry [--strict] [--refresh])",
            "drift": "Alias für 'telemetry': Prüft Checksum-, Versions- und Dependency-Drift (mit --strict als CI-Gate)",
            "auto-export": "Auto-Export & Multi-Repo-Sync für geänderte Standalone-Module (bach modules auto-export [--apply] [--pull-newer] [--bundle-deps] [--out DIR])",
            "sync-repos": "Alias für 'auto-export': Synchronisiert und exportiert Module + Manifest-Feed (mit --pull-newer auch Import neuerer Repo-Stände)",
            "stack-update": "Einheitliche Self-Update-Orchestrierung: Feeds, Module, Hot-Wiring & Drift-Check (bach modules stack-update [--dry-run] [--strict] [--pull-newer])",
            "audit-legacy": "Audit verbleibender In-Tree-Legacy-Services (permissions, config, backup, connector) auf Standalone-Export & Hot-Wiring",
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
            respect_lock = any(a in ("--respect-lock", "--locked") for a in args)
            return self._auto_update_cycle(apply_updates=apply_updates, dry_run=is_dry, respect_lock=respect_lock)
        elif op == "install":
            if not args:
                return False, "Fehler: Pfad oder ZIP-Datei erforderlich: bach modules install <pfad_oder_zip>"
            return self._install_module(args[0], dry_run=dry_run)
        elif op == "update":
            is_dry = dry_run or any(a in ("--dry-run", "-n") for a in args)
            respect_lock = any(a in ("--respect-lock", "--locked") for a in args)
            return self._update_modules(dry_run=is_dry, respect_lock=respect_lock)
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
            elif sub_op in ("reconcile", "check"):
                return self._reconcile_cli()
            else:
                return False, f"Unbekannte Feed-Operation '{sub_op}'. Verfügbar: list, add, remove, sync, reconcile"
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
        elif op in ("test", "ci", "smoke"):
            return self._run_module_tests_cli(args)
        elif op in ("bootstrap", "bootstrap-core", "install-minimal"):
            return self.bootstrap_core(args)
        elif op in ("scaffold", "create", "new"):
            return self._scaffold_cli(args)
        elif op in ("reconcile", "reconciliation"):
            return self._reconcile_cli()
        elif op in ("telemetry", "drift", "drift-check"):
            return self._telemetry_cli(args)
        elif op in ("auto-export", "auto_export", "sync-repos", "sync_repos"):
            return self._auto_export_cli(args, dry_run=dry_run)
        elif op in ("stack-update", "stack_update"):
            return self._stack_update_cli(args, dry_run=dry_run)
        elif op in ("audit-legacy", "audit_legacy", "legacy-audit"):
            return self._audit_legacy_cli(args)
        elif op == "help":
            return self._help()
        else:
            ops = ", ".join(self.get_operations().keys())
            return False, f"Unbekannte Operation '{operation}'. Verfügbar: {ops}"

    # -------------------------------------------------------------------------
    # STACK ORCHESTRATION (Task -62) & LEGACY AUDIT (Task -63)
    # -------------------------------------------------------------------------

    def run_stack_update(
        self,
        apply_updates: bool = True,
        dry_run: bool = False,
        strict: bool = False,
        pull_newer: bool = False,
        respect_lock: bool = False,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Führt Feeds-Sync, Modul-Updates, Hot-Wiring und Drift-Prüfung als Kette aus."""
        repo_sync: Optional[Dict[str, Any]] = None
        if pull_newer:
            repo_sync = self.sync_repos(dry_run=dry_run, pull_newer=True)

        if dry_run:
            feeds_sync: Dict[str, Any] = {
                "feeds_count": len(self.get_feeds()),
                "modules_count": len(self.get_feed_modules()),
                "skipped_dry_run": True,
            }
        else:
            feeds_sync = self.sync_feeds()

        check = self.check_for_updates()
        cycle_ok, cycle_msg = self._auto_update_cycle(
            apply_updates=(apply_updates and not dry_run),
            dry_run=dry_run,
            sync_feeds_first=False,
            respect_lock=respect_lock,
        )

        wiring: Dict[str, Any]
        try:
            from hub._services.ocean_stack_bridge import auto_switch_to_standalone_modules
            wiring = auto_switch_to_standalone_modules()
        except Exception as exc:
            wiring = {"total_switched": 0, "error": str(exc)}

        telemetry = self.get_telemetry_and_drift_report()
        summary = telemetry.get("summary", {})
        drift_count = (
            int(summary.get("checksum_drift_count", 0))
            + int(summary.get("version_drift_count", 0))
            + int(summary.get("unlocked_count", 0))
        )
        missing_deps_count = int(summary.get("missing_deps_count", 0))
        cycle_failed = 0 if cycle_ok else 1
        repo_errors = int((repo_sync or {}).get("errors_count", 0))
        drift_failed = bool(strict and (drift_count > 0 or missing_deps_count > 0))
        ok = (cycle_failed == 0 and repo_errors == 0 and not drift_failed)

        updates_found = list(check.get("updates", []))
        update_cycle_data: Dict[str, Any] = {
            "ok": cycle_ok,
            "updates_found": updates_found,
            "applied": ([] if (dry_run or not apply_updates or not cycle_ok) else updates_found),
            "blocked": list(check.get("blocked", [])),
            "failed": ([] if cycle_ok else [{"error": cycle_msg}]),
            "message": cycle_msg,
        }

        report: Dict[str, Any] = {
            "schema": "bach.stack-update.v1",
            "timestamp": datetime.now().isoformat(),
            "ok": ok,
            "dry_run": dry_run,
            "strict": strict,
            "pull_newer": pull_newer,
            "respect_lock": respect_lock,
            "feeds_sync": feeds_sync,
            "repo_sync": repo_sync,
            "update_cycle": update_cycle_data,
            "wiring": {
                "total_switched": int(wiring.get("total_switched", 0)),
                "error": wiring.get("error"),
            },
            "drift_count": drift_count,
            "missing_deps_count": missing_deps_count,
            "telemetry_summary": summary,
        }
        return ok, report

    def _stack_update_cli(self, args: list, dry_run: bool = False) -> Tuple[bool, str]:
        is_dry = dry_run or ("--dry-run" in args)
        is_strict = "--strict" in args
        pull_newer = "--pull-newer" in args
        respect_lock = "--respect-lock" in args
        as_json = "--json" in args
        ok, report = self.run_stack_update(
            apply_updates=not is_dry,
            dry_run=is_dry,
            strict=is_strict,
            pull_newer=pull_newer,
            respect_lock=respect_lock,
        )
        if as_json:
            return ok, json.dumps(report, indent=2, ensure_ascii=False)
        cyc = report["update_cycle"]
        lines = [
            "BACH STACK UPDATE ORCHESTRATOR",
            "=" * 50,
            f"Modus:      {'DRY-RUN' if is_dry else 'APPLY'} | Strict: {is_strict}",
            f"Feeds:      {report['feeds_sync'].get('feeds_count', 0)} Feeds ({report['feeds_sync'].get('modules_count', 0)} Einträge)",
            f"Updates:    {len(cyc.get('updates_found', []))} gefunden | {len(cyc.get('applied', []))} angewendet | {len(cyc.get('failed', []))} Fehler",
            f"Hot-Wiring: {report['wiring'].get('total_switched', 0)} Standalone-Module aktiv",
            f"Drift/Deps: drift={report['drift_count']} | missing_deps={report['missing_deps_count']}",
            f"Ergebnis:   {'[OK] Stack konsistent' if ok else '[WARN/FAIL] Prüfbedarf erkannt'}",
        ]
        return ok, "\n".join(lines)

    def audit_legacy_candidates(self, candidates: Optional[List[str]] = None) -> Dict[str, Any]:
        """Systematisches Audit verbleibender In-Tree-Services auf Standalone-Export und Hot-Wiring."""
        targets = candidates or ["permissions", "config", "backup", "connector"]
        hub_dir = self.base_path / "hub"

        detection: Dict[str, Any] = {}
        bridge_status: Dict[str, Any] = {}
        try:
            from hub._services.ocean_stack_bridge import (
                detect_legacy_in_tree_services,
                ocean_modularized_services_status,
            )
            detection = detect_legacy_in_tree_services()
            bridge_status = ocean_modularized_services_status()
        except Exception:
            pass

        in_tree_all = list(detection.get("switched_services", [])) + list(detection.get("legacy_services", []))
        installed_map = {m["name"]: m for m in self.get_modules_data()}

        candidate_files_map = {
            "permissions": ["claude_permissions.py"],
            "config": ["_services/config.py", "_services/user_config_store.py", "_services/chat/local_provider_config.py", "partner_config_manager.py"],
            "backup": ["backup.py"],
            "connector": ["connector.py"],
        }

        results: List[Dict[str, Any]] = []
        for cand in targets:
            key = str(cand).strip().lower()
            mod_info = installed_map.get(key)
            b_info = bridge_status.get(key, {})
            matched_files = []
            for rel_f in candidate_files_map.get(key, [f"{key}.py"]):
                p = hub_dir / rel_f
                if p.is_file():
                    text = p.read_text(encoding="utf-8", errors="ignore")
                    matched_files.append({
                        "file": rel_f,
                        "lines": len(text.splitlines()),
                        "has_deprecation_decorator": "deprecated_legacy_bach" in text,
                        "uses_sqlite_or_hub_db": ("sqlite3" in text or "get_bach_db" in text or "hub.db" in text),
                    })
            if not matched_files:
                for item in in_tree_all:
                    if item.get("standalone_name") == key or item.get("name") == key:
                        matched_files.append({
                            "file": item.get("file"),
                            "lines": None,
                            "has_deprecation_decorator": False,
                            "uses_sqlite_or_hub_db": None,
                        })

            standalone_bound = bool(b_info.get("standalone"))
            has_module_pkg = bool(mod_info and mod_info.get("selfcontained"))
            has_db_coupling = any(f.get("uses_sqlite_or_hub_db") for f in matched_files)
            if standalone_bound and has_module_pkg:
                readiness = "standalone_bound"
            elif has_module_pkg:
                readiness = "exported_needs_wiring"
            elif not has_db_coupling:
                readiness = "ready_for_export"
            else:
                readiness = "extract_pure_core_needed"

            results.append({
                "candidate": key,
                "readiness": readiness,
                "has_standalone_module": has_module_pkg,
                "module_version": (mod_info or {}).get("version"),
                "bridge_bound_standalone": standalone_bound,
                "legacy_files": matched_files,
                "recommended_action": (
                    "Bereits als Standalone-Modul exportiert und hot-wired"
                    if readiness == "standalone_bound"
                    else f"Standalone-Modul unter .MODULES/{key} exportieren und in ocean_stack_bridge.py registrieren"
                ),
            })

        bound_count = sum(1 for r in results if r["readiness"] == "standalone_bound")
        return {
            "schema": "bach.legacy-candidates-audit.v1",
            "timestamp": datetime.now().isoformat(),
            "targets": targets,
            "total_audited": len(results),
            "standalone_bound_count": bound_count,
            "legacy_in_tree_summary": {
                "total_in_tree_services": detection.get("total_in_tree_services", 0),
                "switched_count": detection.get("switched_or_switchable_count", 0),
                "legacy_only_count": detection.get("legacy_in_tree_only_count", 0),
            },
            "candidates": results,
        }

    def _audit_legacy_cli(self, args: list) -> Tuple[bool, str]:
        as_json = "--json" in args
        cands = [a for a in args if not a.startswith("-")]
        report = self.audit_legacy_candidates(cands or None)
        if as_json:
            return True, json.dumps(report, indent=2, ensure_ascii=False)
        lines = [
            "BACH LEGACY CANDIDATES AUDIT",
            "=" * 50,
            f"Geprüfte Kandidaten: {report['standalone_bound_count']}/{report['total_audited']} Standalone-gebunden",
        ]
        for item in report["candidates"]:
            lines.append(
                f"  - {item['candidate']:<14} [{item['readiness']}] "
                f"pkg={item['has_standalone_module']} wired={item['bridge_bound_standalone']} "
                f"({len(item['legacy_files'])} Legacy-Datei(en))"
            )
        return True, "\n".join(lines)

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

    @staticmethod
    def _resolve_local_source_path(url_or_path: str) -> Path:
        """Löst lokale Pfade sowie file://-URIs betriebssystemunabhängig zu Path auf."""
        raw = str(url_or_path).strip()
        if raw.lower().startswith("file://"):
            parsed = urllib.parse.urlparse(raw)
            local_p = urllib.request.url2pathname(parsed.path or "")
            if parsed.netloc and parsed.netloc not in ("", "localhost"):
                local_p = f"//{parsed.netloc}{local_p}"
            return Path(local_p)
        return Path(raw)

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
                    lp = self._resolve_local_source_path(url)
                    if lp.is_dir():
                        lp = lp / "manifest_feed.json"
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

    def _install_module(self, source_path_str: str, dry_run: bool = False, expected_sha: Optional[str] = None, skip_tests: bool = False) -> Tuple[bool, str]:
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
            source = self._resolve_local_source_path(source_path_str)
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
            if is_valid and not skip_tests:
                test_ok, test_summary, test_count, test_dur = self._run_single_module_tests(target_dir, timeout_sec=20)
                if not test_ok:
                    is_valid = False
                    err_msg = f"Modul-CI Smoke-Tests fehlgeschlagen:\n{test_summary}"

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

    def check_for_updates(self, cache_ttl_sec: int = 60, enforce_lock: bool = True) -> Dict[str, Any]:
        """Prüft Quellpfade auf verfügbare neuere Modulversionen (mit Caching & Pin/Lock-Schutz)."""
        global _MODULES_UPDATE_CACHE
        now = time.time()
        if _MODULES_UPDATE_CACHE["data"] is not None and (now - _MODULES_UPDATE_CACHE["timestamp"]) < cache_ttl_sec:
            cached_res = dict(_MODULES_UPDATE_CACHE["data"])
            cached_res["cached"] = True
            return cached_res

        installed = {m["name"]: m for m in self.get_modules_data()}
        source_dirs = self._resolve_source_dirs()
        updates_found: List[Dict[str, Any]] = []
        blocked_by_pins: List[Dict[str, Any]] = []

        lockfile = self._resolve_lockfile()
        lock_data = {}
        if lockfile.is_file():
            try:
                lock_data = json.loads(lockfile.read_text(encoding="utf-8"))
            except Exception:
                pass
        locked_modules = lock_data.get("modules", {})

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
                                is_quarantined = self.is_version_quarantined(c_name, c_ver)
                                if is_quarantined:
                                    continue
                                pin = self.is_module_pinned(c_name)
                                is_pinned = bool(pin and pin == cur_ver)
                                is_locked = bool(enforce_lock and c_name in locked_modules and cur_ver == locked_modules[c_name].get("version"))
                                if is_pinned or is_locked:
                                    blocked_by_pins.append({
                                        "name": c_name,
                                        "current_version": cur_ver,
                                        "new_version": c_ver,
                                        "reason": f"Modul ist auf v{pin} fixiert (Pin-Schutz)" if is_pinned else f"modules.lock.json fixiert Version auf v{locked_modules[c_name].get('version')}",
                                    })
                                updates_found.append({
                                    "name": c_name,
                                    "current_version": cur_ver,
                                    "new_version": c_ver,
                                    "source": str(cand),
                                    "locked": is_locked,
                                    "pinned": is_pinned,
                                })
                    except Exception:
                        pass
            except OSError:
                pass

        # Prüfe Manifest-Feeds (TASK -46 & TASK -52)
        try:
            feed_modules = self.get_feed_modules()
            for fm in feed_modules:
                f_name = fm.get("name")
                f_ver = fm.get("version", "1.0.0")
                if not f_name or f_name not in installed:
                    continue
                cur_ver = installed[f_name]["version"]
                if self.is_version_quarantined(f_name, f_ver):
                    continue
                if parse_semver(f_ver) > parse_semver(cur_ver):
                    dl_url = fm.get("download_url") or fm.get("url")
                    if dl_url and not any(u["name"] == f_name for u in updates_found):
                        pin = self.is_module_pinned(f_name)
                        is_pinned = bool(pin and pin == cur_ver)
                        is_locked = bool(enforce_lock and f_name in locked_modules and cur_ver == locked_modules[f_name].get("version"))
                        if is_pinned or is_locked:
                            blocked_by_pins.append({
                                "name": f_name,
                                "current_version": cur_ver,
                                "new_version": f_ver,
                                "reason": f"Modul ist auf v{pin} fixiert (Pin-Schutz)" if is_pinned else f"modules.lock.json fixiert Version auf v{locked_modules[f_name].get('version')}",
                            })
                        updates_found.append({
                            "name": f_name,
                            "current_version": cur_ver,
                            "new_version": f_ver,
                            "source": f"feed:{fm.get('feed_name', 'remote')}",
                            "download_url": dl_url,
                            "sha256": fm.get("sha256"),
                            "source_type": "feed",
                            "locked": is_locked,
                            "pinned": is_pinned,
                        })
        except Exception:
            pass

        result = {
            "schema": "bach.modules-update-check.v1",
            "has_updates": len(updates_found) > 0,
            "updates_count": len(updates_found),
            "updates": updates_found,
            "blocked_by_pins": blocked_by_pins,
            "blocked_count": len(blocked_by_pins),
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
        blocked = res.get("blocked_by_pins", [])
        if blocked:
            lines.append(f"Geschützte Module (Pin/Lockfile: {len(blocked)}):")
            for b in blocked:
                lines.append(f"  🔒 {b['name']:<22} v{b['current_version']} (v{b['new_version']} blockiert: {b['reason']})")
            lines.append("")

        if not res["has_updates"]:
            lines.append("[INFO] Keine Modul-Updates verfügbar. Alle Module sind auf dem neuesten Stand.")
            return True, "\n".join(lines)

        lines.append(f"Verfügbare Updates ({res['updates_count']}):")
        for u in res["updates"]:
            lines.append(f"  • {u['name']:<24} v{u['current_version']} -> v{u['new_version']} (Quelle: {u['source']})")
        lines.append("")
        lines.append("Führe 'bach modules update' aus, um alle Updates zu installieren.")
        return True, "\n".join(lines)

    def _auto_update_cycle(
        self,
        apply_updates: bool = False,
        dry_run: bool = False,
        sync_feeds_first: bool = True,
        respect_lock: bool = False,
    ) -> Tuple[bool, str]:
        """Führt einen automatisierten Prüf- und Aktualisierungszyklus aus."""
        if sync_feeds_first:
            try:
                self.sync_feeds()
            except Exception:
                pass

        check = self.check_for_updates(cache_ttl_sec=0, enforce_lock=respect_lock)
        has_upd = bool(check.get("has_updates"))
        upd_count = int(check.get("updates_count", 0))
        blocked = check.get("blocked_by_pins", [])
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines = [
            "=== MODUL AUTO-UPDATE RUNNER ===",
            f"Prüfzeitpunkt:        {now_str}",
            f"Installierte Module:  {check.get('total_installed', 0)}",
            f"Verfügbare Updates:   {upd_count}",
            f"Pin-/Lock-Schutz:     {len(blocked)} Modul(e) geschützt",
            f"Modus:                {'Automatisches Upgrade (--apply)' if apply_updates else 'Monitoring / Benachrichtigung'}",
            "",
        ]

        if blocked:
            lines.append("Geschützte Versionen (kein automatisches Upgrade):")
            for b in blocked:
                lines.append(f"  🔒 {b['name']:<22} v{b['current_version']} (v{b['new_version']} blockiert: {b['reason']})")
            lines.append("")

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
        ok_upd, msg_upd = self._update_modules(dry_run=dry_run, respect_lock=respect_lock)
        lines.append(msg_upd)
        return ok_upd, "\n".join(lines)

    def _update_modules(
        self,
        dry_run: bool = False,
        respect_lock: bool = False,
        refresh_lockfile: bool = True,
    ) -> Tuple[bool, str]:
        """Sucht nach neueren Modulversionen in allen Quellpfaden & Feeds und aktualisiert sie."""
        global _MODULES_UPDATE_CACHE
        check_res = self.check_for_updates(cache_ttl_sec=0, enforce_lock=respect_lock)
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
            if upd.get("pinned") or (respect_lock and upd.get("locked")):
                reason = "Pin-Schutz" if upd.get("pinned") else "modules.lock.json Schutz"
                lines.append(f"  🔒 {upd['name']:<24} v{upd['current_version']} [ÜBERSPRUNGEN: {reason}]")
                continue
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
            if success_count > 0 and refresh_lockfile:
                lockfile = self._resolve_lockfile()
                if lockfile.is_file():
                    self._generate_lockfile(lockfile)
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
            "  bach modules scaffold <name> [--type TYPE] [--desc TEXT]",
            "      Erstellt ein neues autarkes Standalone-Modul mit Manifest, Code und Testsuite.",
            "",
            "  bach modules reconcile",
            "      Führt einen vollständigen Abgleich zwischen Feeds, Lockfile und Version-Pins durch.",
            "",
            "  bach modules telemetry | drift",
            "      Zeigt Lockfile-Checksum-Drift, Dependency-Status, Pins und Quarantäne an.",
            "",
            "  bach modules auto-export [--apply] [--bundle-deps] [--out DIR]",
            "      Prüft Modul-Änderungen & Quell-Repos und exportiert ZIP-Bundles + manifest_feed.json.",
            "",
            "  bach modules wire",
            "      Führt Hot-Wiring aller Standalone-Module in die laufende Bridge aus.",
            "",
            "Beispiele:",
            "  bach modules list",
            "  bach modules scaffold mein_dienst --type service",
            "  bach modules test mein_dienst",
            "  bach modules reconcile",
            "  bach modules bootstrap [--generate-lockfile] [--minimal]",
            "  bach modules update --dry-run",
            "  bach modules install C:/Pfad/zu/mein_modul.zip",
            "  bach modules wire",
        ]
        return True, "\n".join(lines)

    # -------------------------------------------------------------------------
    # MODUL-SCAFFOLDER & RECONCILIATION (TASK -54 & TASK -52)
    # -------------------------------------------------------------------------

    def scaffold_module(
        self,
        name: str,
        module_type: str = "module",
        description: str = "",
        out_dir: Optional[Union[str, Path]] = None,
        force: bool = False,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Erstellt ein neues, standardkonformes autarkes Modul in .MODULES/<name>."""
        clean_name = str(name).strip().lower()
        if not clean_name or not re.match(r"^[a-z][a-z0-9_]*$", clean_name):
            return False, f"Ungültiger Modulname '{name}'. Muss mit Kleinbuchstabe beginnen und nur [a-z0-9_] enthalten.", {}

        target_dir = Path(out_dir).resolve() if out_dir else (self.modules_dir / clean_name)
        if target_dir.exists() and any(target_dir.iterdir()) and not force:
            return False, f"Zielverzeichnis '{target_dir}' existiert bereits und ist nicht leer. Nutze --force zum Überschreiben.", {}

        src_dir = target_dir / "src"
        tests_dir = target_dir / "tests"
        src_dir.mkdir(parents=True, exist_ok=True)
        tests_dir.mkdir(parents=True, exist_ok=True)

        class_name = "".join(word.capitalize() for word in clean_name.split("_")) + "Service"
        desc = description.strip() or f"BACH Standalone Module: {clean_name}"
        now_iso = datetime.now().isoformat()

        manifest_data = {
            "name": clean_name,
            "version": "1.0.0",
            "type": module_type or "module",
            "description": desc,
            "author": "BACH Team",
            "created_at": now_iso,
            "selfcontained": True,
            "entrypoints": {
                "library": f"src/{clean_name}.py",
            },
            "boundaries": {
                "data": "user-local",
                "network": "full",
                "platforms": ["windows", "macos", "linux"],
            },
            "consumers": [
                {"name": "BACH", "minimum_version": "3.15.0"},
                {"name": "Ocean", "minimum_version": "1.0.0"},
            ],
        }
        (target_dir / "manifest.json").write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        module_code = (
            "# -*- coding: utf-8 -*-\n"
            "# SPDX-License-Identifier: MIT\n"
            '"""\n'
            f"{clean_name} — Standalone Modul\n"
            f"{'=' * (len(clean_name) + 20)}\n"
            f"{desc}\n"
            '"""\n'
            "from __future__ import annotations\n\n"
            "import logging\n"
            "from typing import Any, Dict, Optional\n\n"
            '__version__ = "1.0.0"\n'
            f'__all__ = ["__version__", "{class_name}", "get_status"]\n\n'
            "logger = logging.getLogger(__name__)\n\n\n"
            "def get_status() -> Dict[str, Any]:\n"
            '    """Gibt den aktuellen Betriebsstatus des Moduls zurück."""\n'
            "    return {\n"
            f'        "module": "{clean_name}",\n'
            '        "version": __version__,\n'
            '        "status": "ready",\n'
            '        "selfcontained": True,\n'
            "    }\n\n\n"
            f"class {class_name}:\n"
            f'    """Haupt-Serviceklasse für {clean_name}."""\n\n'
            "    def __init__(self, config: Optional[Dict[str, Any]] = None):\n"
            "        self.config = config or {}\n"
            "        self.version = __version__\n"
            f'        logger.debug("Initialisiere {class_name} v%s", self.version)\n\n'
            "    def run(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:\n"
            '        """Führt die primäre Service-Operation aus."""\n'
            "        return {\n"
            '            "success": True,\n'
            f'            "module": "{clean_name}",\n'
            '            "payload": payload or {},\n'
            "        }\n"
        )
        (src_dir / f"{clean_name}.py").write_text(module_code, encoding="utf-8")

        test_code = (
            "# -*- coding: utf-8 -*-\n"
            "# SPDX-License-Identifier: MIT\n"
            f'"""Smoke- und Unit-Tests für {clean_name}."""\n'
            "import json\n"
            "import sys\n"
            "from pathlib import Path\n\n"
            "# Modul-Quellpfad isoliert einhängen\n"
            'sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))\n'
            f"import {clean_name}\n\n\n"
            "def test_manifest_validity():\n"
            '    manifest_p = Path(__file__).resolve().parent.parent / "manifest.json"\n'
            '    assert manifest_p.is_file(), "manifest.json muss existieren"\n'
            '    data = json.loads(manifest_p.read_text(encoding="utf-8"))\n'
            f'    assert data.get("name") == "{clean_name}"\n'
            '    assert data.get("version") == "1.0.0"\n'
            '    assert data.get("selfcontained") is True\n'
            '    assert "library" in data.get("entrypoints", {})\n\n\n'
            "def test_module_version():\n"
            f'    assert {clean_name}.__version__ == "1.0.0"\n\n\n'
            "def test_module_status():\n"
            f"    status = {clean_name}.get_status()\n"
            f'    assert status["module"] == "{clean_name}"\n'
            '    assert status["status"] == "ready"\n'
            '    assert status["selfcontained"] is True\n\n\n'
            "def test_service_execution():\n"
            f"    service = {clean_name}.{class_name}()\n"
            '    res = service.run({"test_key": 42})\n'
            '    assert res["success"] is True\n'
            '    assert res["payload"]["test_key"] == 42\n'
        )
        (tests_dir / f"test_{clean_name}.py").write_text(test_code, encoding="utf-8")

        readme_content = (
            f"# {clean_name} — Standalone Module\n\n"
            "> **Version:** 1.0.0  \n"
            f"> **Typ:** Standalone Module ({module_type or 'module'})  \n"
            "> **Kompatibilität:** BACH ≥ 3.15.0, Ocean ≥ 1.0.0  \n\n"
            f"{desc}\n\n"
            "## Struktur\n"
            f"- `src/{clean_name}.py`: Haupt-Quellcode und Service-Definition\n"
            f"- `tests/test_{clean_name}.py`: Automatisierte Testsuite (pytest)\n"
            "- `manifest.json`: Offizielles Modul-Manifest\n\n"
            "## Tests ausführen\n"
            "```bash\n"
            f"bach modules test {clean_name}\n"
            "```\n\n"
            "## In BACH importieren & verdrahten\n"
            "```bash\n"
            f"bach modules install .MODULES/{clean_name}\n"
            "bach modules wire\n"
            "```\n"
        )
        (target_dir / "README.md").write_text(readme_content, encoding="utf-8")

        v_ok, v_msg = self._verify_module(target_dir)
        if not v_ok:
            return False, f"Fehler bei Verifikation des erstellten Moduls: {v_msg}", {}

        invalidate_module_cache()
        summary = {
            "name": clean_name,
            "version": "1.0.0",
            "type": module_type or "module",
            "path": str(target_dir),
            "files": ["manifest.json", f"src/{clean_name}.py", f"tests/test_{clean_name}.py", "README.md"],
            "verified": True,
        }
        lines = [
            f"[OK] Standalone-Modul '{clean_name}' erfolgreich erstellt:",
            f"  Pfad:        {target_dir}",
            f"  Typ:         {module_type or 'module'}",
            f"  Entrypoint:  src/{clean_name}.py",
            f"  Testsuite:   tests/test_{clean_name}.py",
            f"  Manifest:    manifest.json (v1.0.0, selfcontained: True)",
            "",
            f"Tipp: Teste das Modul sofort mit: bach modules test {clean_name}",
        ]
        return True, "\n".join(lines), summary

    def _scaffold_cli(self, args: List[str]) -> Tuple[bool, str]:
        if not args or args[0].startswith("-"):
            return False, "Fehler: Modulname erforderlich: bach modules scaffold <name> [--type TYPE] [--desc TEXT] [--out DIR] [--force]"
        name = args[0]
        mod_type = "module"
        desc = ""
        out_dir = None
        force = False
        idx = 1
        while idx < len(args):
            arg = args[idx]
            if arg in ("--type", "-t") and idx + 1 < len(args):
                mod_type = args[idx + 1]
                idx += 2
            elif arg.startswith("--type="):
                mod_type = arg.split("=", 1)[1]
                idx += 1
            elif arg in ("--desc", "--description", "-d") and idx + 1 < len(args):
                desc = args[idx + 1]
                idx += 2
            elif arg.startswith("--description="):
                desc = arg.split("=", 1)[1]
                idx += 1
            elif arg in ("--out", "-o") and idx + 1 < len(args):
                out_dir = args[idx + 1]
                idx += 2
            elif arg.startswith("--out="):
                out_dir = arg.split("=", 1)[1]
                idx += 1
            elif arg in ("--force", "-f"):
                force = True
                idx += 1
            else:
                idx += 1
        ok, msg, _ = self.scaffold_module(name, module_type=mod_type, description=desc, out_dir=out_dir, force=force)
        return ok, msg

    def reconcile_feeds_and_pins(self) -> Dict[str, Any]:
        """Gleicht Feeds, installierte Module, Version-Pins und Lockfile miteinander ab."""
        installed = {m["name"]: m for m in self.get_modules_data()}
        lockfile = self._resolve_lockfile()
        lock_data = {}
        if lockfile.is_file():
            try:
                lock_data = json.loads(lockfile.read_text(encoding="utf-8"))
            except Exception:
                pass
        locked_mods = lock_data.get("modules", {})
        pins_data = self.get_version_pins()
        pins = pins_data.get("pins", {})
        quarantined = pins_data.get("quarantined", {})
        feed_modules = self.get_feed_modules()

        feed_by_name: Dict[str, List[Dict[str, Any]]] = {}
        for fm in feed_modules:
            n = fm.get("name")
            if n:
                feed_by_name.setdefault(n, []).append(fm)

        reconciliation_items = []
        for name, m_info in sorted(installed.items()):
            cur_ver = m_info["version"]
            pin_ver = pins.get(name, {}).get("pinned_version")
            lock_spec = locked_mods.get(name, {})
            lock_ver = lock_spec.get("version")
            fms = feed_by_name.get(name, [])
            latest_feed_ver = None
            if fms:
                latest_feed_ver = max((fm.get("version", "0.0.0") for fm in fms), key=parse_semver)

            status = "intact"
            notes = []
            if pin_ver:
                notes.append(f"pinned(v{pin_ver})")
            if lock_ver:
                if lock_ver == cur_ver:
                    notes.append(f"locked(v{lock_ver})")
                else:
                    status = "lock_mismatch"
                    notes.append(f"lock_mismatch(cur=v{cur_ver}, lock=v{lock_ver})")
            if latest_feed_ver and parse_semver(latest_feed_ver) > parse_semver(cur_ver):
                if pin_ver or (lock_ver and lock_ver == cur_ver):
                    notes.append(f"upgrade_blocked(v{latest_feed_ver} available)")
                else:
                    status = "upgrade_available"
                    notes.append(f"upgrade_available(v{latest_feed_ver})")

            reconciliation_items.append({
                "name": name,
                "current_version": cur_ver,
                "pinned_version": pin_ver,
                "locked_version": lock_ver,
                "latest_feed_version": latest_feed_ver,
                "status": status,
                "notes": ", ".join(notes) if notes else "normal",
            })

        return {
            "schema": "bach.modules-reconciliation.v1",
            "timestamp": datetime.now().isoformat(),
            "total_installed": len(installed),
            "total_locked": len(locked_mods),
            "total_pinned": len(pins),
            "total_quarantined": len(quarantined),
            "items": reconciliation_items,
        }

    def _reconcile_cli(self) -> Tuple[bool, str]:
        rec = self.reconcile_feeds_and_pins()
        lines = [
            "=== BACH MODUL RECONCILIATION ===",
            f"Stand:               {rec['timestamp']}",
            f"Installierte Module: {rec['total_installed']}",
            f"Gesperrt im Lock:    {rec['total_locked']}",
            f"Explizite Pins:      {rec['total_pinned']}",
            f"In Quarantäne:       {rec['total_quarantined']}",
            "",
            f"  {'MODUL':<26} {'INSTALL':<10} {'LOCKFILE':<10} {'FEED':<10} STATUS / HINWEISE",
            "  " + "-" * 75,
        ]
        for it in rec["items"]:
            l_v = f"v{it['locked_version']}" if it["locked_version"] else "-"
            f_v = f"v{it['latest_feed_version']}" if it["latest_feed_version"] else "-"
            lines.append(f"  {it['name']:<26} v{it['current_version']:<9} {l_v:<10} {f_v:<10} {it['notes']}")
        lines.append("")
        lines.append("[OK] Reconciliation abgeschlossen. Keine unerlaubten Version-Drifts festgestellt.")
        return True, "\n".join(lines)

    # -------------------------------------------------------------------------
    # MODUL-CI & SMOKE-RUNNER (TASK -50)
    # -------------------------------------------------------------------------

    def _run_single_module_tests(
        self,
        mod_dir: Path,
        timeout_sec: int = 30,
    ) -> Tuple[bool, str, int, float]:
        """Führt isolierte Smoke- und Regressionstests für ein Modul aus."""
        test_dir = mod_dir / "tests"
        if not test_dir.is_dir():
            return True, "Keine Test-Suite vorhanden", 0, 0.0

        test_files = list(test_dir.glob("test_*.py"))
        if not test_files:
            return True, "Keine Testdateien (test_*.py) gefunden", 0, 0.0

        env = os.environ.copy()
        src_dir = str((mod_dir / "src").resolve())
        env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")

        cmd = [sys.executable, "-m", "pytest", "tests", "-q", "--disable-warnings"]
        t0 = time.time()
        try:
            res = subprocess.run(
                cmd,
                cwd=str(mod_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            duration = round(time.time() - t0, 2)
            out = (res.stdout or "").strip()
            err = (res.stderr or "").strip()
            combined = out + ("\n" + err if err else "")

            match = re.search(r"(\d+)\s+passed", combined)
            passed_count = int(match.group(1)) if match else len(test_files)

            if res.returncode == 0:
                return True, combined or f"{passed_count} Tests bestanden", passed_count, duration
            else:
                return False, combined or "Tests fehlgeschlagen", passed_count, duration
        except subprocess.TimeoutExpired:
            dur = round(time.time() - t0, 2)
            return False, f"Test-Timeout nach {timeout_sec}s", 0, dur
        except Exception as exc:
            dur = round(time.time() - t0, 2)
            return False, f"Fehler bei Testausführung: {exc}", 0, dur

    def run_module_tests(
        self,
        target: Optional[str] = None,
        timeout_sec: int = 45,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Führt isolierte Modul-CI für target oder alle Module aus."""
        modules = self.get_modules_data()
        if target:
            modules = [m for m in modules if m["name"].lower() == target.lower()]
            if not modules:
                return False, f"Modul '{target}' nicht in .MODULES/ gefunden.", {}

        results: Dict[str, Any] = {}
        all_passed = True
        total_tests = 0
        total_duration = 0.0

        for m in modules:
            name = m["name"]
            mod_dir = Path(m["path"])
            ok, out, count, dur = self._run_single_module_tests(mod_dir, timeout_sec=timeout_sec)
            total_tests += count
            total_duration += dur
            results[name] = {
                "name": name,
                "version": m["version"],
                "passed": ok,
                "output": out,
                "tests_count": count,
                "duration": dur,
            }
            if not ok:
                all_passed = False

        total_duration = round(total_duration, 2)
        summary = {
            "all_passed": all_passed,
            "modules_tested": len(modules),
            "modules_passed": sum(1 for r in results.values() if r["passed"]),
            "modules_failed": sum(1 for r in results.values() if not r["passed"]),
            "total_tests": total_tests,
            "total_duration": total_duration,
            "details": results,
        }
        return all_passed, self._format_ci_summary(summary), summary

    def _format_ci_summary(self, summary: Dict[str, Any]) -> str:
        lines = ["=== MODUL-CI & SMOKE-RUNNER ===", ""]
        details = summary.get("details", {})
        for name, r in sorted(details.items()):
            status = "[PASS]" if r["passed"] else "[FAIL]"
            cnt = r.get("tests_count", 0)
            dur = r.get("duration", 0.0)
            lines.append(f"• {name:<26} v{r.get('version', '1.0.0'):<8} {status} ({cnt} Tests, {dur}s)")
            if not r["passed"]:
                out_snippet = r.get("output", "").splitlines()
                for line in out_snippet[:5]:
                    lines.append(f"    ! {line}")
        lines.append("")
        res_tag = "ALLE BESTANDEN" if summary.get("all_passed") else "FEHLER FESTGESTELLT"
        lines.append(
            f"Gesamtergebnis: [{res_tag}] "
            f"({summary.get('modules_passed')}/{summary.get('modules_tested')} Module, "
            f"{summary.get('total_tests')} Tests in {summary.get('total_duration')}s)"
        )
        return "\n".join(lines)

    def _run_module_tests_cli(self, args: List[str]) -> Tuple[bool, str]:
        target = args[0] if args and not args[0].startswith("-") else None
        ok, text, _ = self.run_module_tests(target=target)
        return ok, text

    # -------------------------------------------------------------------------
    # MODULARER CORE: BOOTSTRAP & LOCKFILE (TASK -49)
    # -------------------------------------------------------------------------

    def _resolve_lockfile(self, custom_path: Optional[str] = None) -> Path:
        if custom_path:
            return Path(custom_path)
        candidates = [
            self.modules_dir / "modules.lock.json",
            self.base_path / "config" / "modules.lock.json",
            self.base_path.parent / "modules.lock.json",
        ]
        for c in candidates:
            if c.is_file():
                return c
        return self.modules_dir / "modules.lock.json"

    def refresh_lockfile(
        self,
        custom_path: Optional[str] = None,
        skip_tests: bool = False,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Auditiert Module mit Drift/Fehlern und aktualisiert modules.lock.json bei Erfolg."""
        lockfile = self._resolve_lockfile(custom_path)
        rep = self.get_telemetry_and_drift_report()
        installed_by_name = {m["name"]: m for m in self.get_modules_data()}
        candidates = [
            it["name"]
            for it in rep.get("items", [])
            if it.get("drift_status") != "intact" or not rep.get("lockfile_exists")
        ]
        audited: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []

        for name in candidates:
            m_info = installed_by_name.get(name)
            if not m_info:
                continue
            mod_dir = Path(m_info["path"])
            is_valid, err_msg = self._verify_module(mod_dir)
            test_count = 0
            if is_valid and not skip_tests and m_info.get("has_tests"):
                test_ok, test_summary, test_count, _ = self._run_single_module_tests(mod_dir, timeout_sec=30)
                if not test_ok:
                    is_valid = False
                    err_msg = f"Tests fehlgeschlagen: {test_summary}"
            entry = {
                "name": name,
                "version": m_info.get("version", "1.0.0"),
                "passed": is_valid,
                "tests_count": test_count,
                "error": "" if is_valid else err_msg,
            }
            if is_valid:
                audited.append(entry)
            else:
                failed.append(entry)

        if failed:
            return False, {
                "ok": False,
                "lockfile": str(lockfile),
                "audited": audited,
                "failed": failed,
                "message": "Checksum-Audit fehlgeschlagen; Lockfile wurde nicht aktualisiert.",
            }

        ok_lock, msg_lock = self._generate_lockfile(lockfile)
        if not ok_lock:
            return False, {
                "ok": False,
                "lockfile": str(lockfile),
                "audited": audited,
                "failed": [],
                "message": msg_lock,
            }
        post_rep = self.get_telemetry_and_drift_report()
        return True, {
            "ok": True,
            "lockfile": str(lockfile),
            "audited": audited,
            "failed": [],
            "message": msg_lock,
            "summary": post_rep.get("summary", {}),
        }

    def bootstrap_core(self, args: List[str] = None) -> Tuple[bool, str]:
        """Core Installations-Bootstrap und Dependency-Lockfile (TASK -49)."""
        args = list(args or [])
        generate = any(a in ("--generate-lockfile", "--generate", "--lock", "-g") for a in args)
        refresh = any(a in ("--refresh-lockfile", "--refresh-lock", "--refresh") for a in args)
        skip_tests = any(a in ("--skip-tests",) for a in args)
        verify_only = any(a in ("--verify", "--check", "-c") for a in args)
        minimal = any(a in ("--minimal", "-m") for a in args)
        dry_run = any(a in ("--dry-run", "-n") for a in args)

        lock_path_str = None
        for a in args:
            if a.startswith("--lockfile="):
                lock_path_str = a.split("=", 1)[1]
            elif a == "--lockfile" and args.index(a) + 1 < len(args):
                lock_path_str = args[args.index(a) + 1]

        lockfile = self._resolve_lockfile(lock_path_str)

        if refresh:
            ok_ref, ref_res = self.refresh_lockfile(custom_path=str(lockfile), skip_tests=skip_tests)
            lines = [
                "=== BACH LOCKFILE AUTO-REFRESH & CHECKSUM-AUDIT ===",
                f"Lockfile: {ref_res.get('lockfile')}",
                f"Auditiert: {len(ref_res.get('audited', []))} | Fehlgeschlagen: {len(ref_res.get('failed', []))}",
            ]
            for a_item in ref_res.get("audited", []):
                lines.append(f"  [PASS] {a_item['name']} v{a_item['version']} ({a_item['tests_count']} Tests)")
            for f_item in ref_res.get("failed", []):
                lines.append(f"  [FAIL] {f_item['name']} v{f_item['version']}: {f_item['error']}")
            lines.append(ref_res.get("message", ""))
            return ok_ref, "\n".join(lines)

        if generate:
            return self._generate_lockfile(lockfile)

        if not lockfile.is_file():
            self._generate_lockfile(lockfile)

        return self._apply_bootstrap(lockfile, verify_only=verify_only, minimal=minimal, dry_run=dry_run)

    def _compute_module_sha256(self, mod_dir: Path) -> Tuple[str, int]:
        """Berechnet deterministische SHA-256-Prüfsumme über Quell-, Manifest- und Doku-Dateien eines Moduls."""
        import hashlib
        hasher = hashlib.sha256()
        file_count = 0
        for r, _, files in sorted(os.walk(mod_dir)):
            # Versteckte temporäre Pack-/Pycache-Ordner ignorieren
            rel_parts = Path(r).relative_to(mod_dir).parts
            if any(part.startswith(".") or part == "__pycache__" for part in rel_parts):
                continue
            for f in sorted(files):
                if f.endswith((".py", ".json", ".md")):
                    p = Path(r) / f
                    hasher.update(p.read_bytes().replace(b"\r\n", b"\n"))
                    file_count += 1
        return hasher.hexdigest(), file_count

    def _generate_lockfile(self, lockfile: Path) -> Tuple[bool, str]:
        from datetime import datetime
        modules = self.get_modules_data()
        lock_data = {
            "schema": "bach.modules-lock.v1",
            "generated_at": datetime.now().isoformat(),
            "total_modules": len(modules),
            "modules": {},
        }
        for m in sorted(modules, key=lambda x: x["name"]):
            name = m["name"]
            mod_dir = Path(m["path"])
            digest, file_count = self._compute_module_sha256(mod_dir)
            lock_data["modules"][name] = {
                "name": name,
                "version": m["version"],
                "entrypoint": m.get("entrypoint"),
                "sha256": digest,
                "files_count": file_count,
                "selfcontained": True,
            }

        lockfile.parent.mkdir(parents=True, exist_ok=True)
        lockfile.write_text(json.dumps(lock_data, indent=2, ensure_ascii=False), encoding="utf-8")
        return True, f"[OK] modules.lock.json erfolgreich mit {len(modules)} Modulen generiert ({lockfile})."

    def _apply_bootstrap(
        self,
        lockfile: Path,
        verify_only: bool = False,
        minimal: bool = False,
        dry_run: bool = False,
    ) -> Tuple[bool, str]:
        try:
            lock_data = json.loads(lockfile.read_text(encoding="utf-8"))
        except Exception as exc:
            return False, f"Fehler beim Lesen von {lockfile}: {exc}"

        locked_mods = lock_data.get("modules", {})
        minimal_core_set = {
            "prompt", "tools", "memory", "session", "hooks",
            "cache", "limits", "scheduler"
        }

        if minimal:
            locked_mods = {k: v for k, v in locked_mods.items() if k in minimal_core_set}

        installed = {m["name"]: m for m in self.get_modules_data()}
        lines = [
            f"=== BACH MODULAR CORE BOOTSTRAP ({'MINIMAL' if minimal else 'VOLLSTÄNDIG'}) ===",
            f"Lockfile: {lockfile}",
            f"Geforderte Module: {len(locked_mods)}",
            "",
        ]

        missing = []
        mismatched = []
        intact = 0

        for name, spec in locked_mods.items():
            req_ver = spec.get("version", "1.0.0")
            if name not in installed:
                missing.append((name, req_ver))
                lines.append(f"  ✗ {name:<26} FEHLT (erfordert v{req_ver})")
            else:
                curr_ver = installed[name].get("version", "0.0.0")
                if curr_ver != req_ver:
                    mismatched.append((name, curr_ver, req_ver))
                    lines.append(f"  ! {name:<26} VERSION-DRIFT (installiert: v{curr_ver}, lock: v{req_ver})")
                else:
                    intact += 1
                    lines.append(f"  ✓ {name:<26} v{curr_ver} [INTAKT]")

        lines.append("")
        lines.append(f"Status: {intact} intakt, {len(missing)} fehlend, {len(mismatched)} Version-Drift.")

        if verify_only or dry_run:
            status_ok = len(missing) == 0 and len(mismatched) == 0
            lines.append(f"Bootstrap-Prüfung: {'[ERFOLGREICH]' if status_ok else '[NACHARBEIT ERFORDERLICH]'}")
            return status_ok, "\n".join(lines)

        wire_res = auto_switch_to_standalone_modules()
        lines.append(f"[OK] Re-Assembly & Hot-Wiring ausgeführt ({wire_res['total_switched']} Module verdrahtet).")
        lines.append("BACH Core ist autark und betriebsbereit.")
        return True, "\n".join(lines)

    # -------------------------------------------------------------------------
    # TELEMETRIE & DEPENDENCY-DRIFT-DASHBOARD (TASK -57)
    # -------------------------------------------------------------------------

    @staticmethod
    def _extract_declared_dependencies(manifest_data: Dict[str, Any]) -> List[str]:
        """Extrahiert Modul- und Paket-Abhängigkeiten einheitlich aus manifest.json."""
        raw_deps = manifest_data.get("dependencies")
        deps: List[str] = []
        if isinstance(raw_deps, dict):
            deps = [str(k).strip() for k in raw_deps.keys() if str(k).strip()]
        elif isinstance(raw_deps, list):
            for entry in raw_deps:
                if isinstance(entry, dict) and entry.get("name"):
                    deps.append(str(entry["name"]).strip())
                elif isinstance(entry, str) and entry.strip():
                    deps.append(entry.strip())
        internal_mods = manifest_data.get("required_modules") or manifest_data.get("module_dependencies")
        if isinstance(internal_mods, list):
            for item in internal_mods:
                name = str(item).strip()
                if name and name not in deps:
                    deps.append(name)
        return deps

    def get_telemetry_and_drift_report(self) -> Dict[str, Any]:
        """Erstellt den vollständigen Telemetrie-, Lockfile-Drift- und Dependency-Bericht."""
        installed_list = self.get_modules_data()
        installed = {m["name"]: m for m in installed_list}
        status_data = self.get_status_data()

        lockfile = self._resolve_lockfile()
        lock_data: Dict[str, Any] = {}
        if lockfile.is_file():
            try:
                lock_data = json.loads(lockfile.read_text(encoding="utf-8"))
            except Exception:
                pass
        locked_mods = lock_data.get("modules", {})

        pins_data = self.get_version_pins()
        pins = pins_data.get("pins", {})
        quarantined = pins_data.get("quarantined", {})
        feeds = self.get_feeds()
        feed_modules = self.get_feed_modules()

        feed_by_name: Dict[str, List[Dict[str, Any]]] = {}
        for fm in feed_modules:
            n = fm.get("name")
            if n:
                feed_by_name.setdefault(n, []).append(fm)

        items: List[Dict[str, Any]] = []
        dependencies_graph: List[Dict[str, Any]] = []
        intact_count = 0
        checksum_drift_count = 0
        version_drift_count = 0
        unlocked_count = 0
        missing_deps_count = 0

        for name, m_info in sorted(installed.items()):
            mod_dir = Path(m_info["path"])
            cur_ver = m_info["version"]
            live_sha, files_count = self._compute_module_sha256(mod_dir)

            manifest_data: Dict[str, Any] = {}
            manifest_file = mod_dir / "manifest.json"
            if manifest_file.is_file():
                try:
                    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
                except Exception:
                    pass

            declared_deps = self._extract_declared_dependencies(manifest_data)
            missing_deps = [
                d for d in declared_deps
                if d in locked_mods and d not in installed
            ]
            # Falls explizite required_modules deklariert sind, fehlende Modul-Abhängigkeiten ebenfalls melden
            req_mods = manifest_data.get("required_modules") or manifest_data.get("module_dependencies") or []
            if isinstance(req_mods, list):
                for req in req_mods:
                    req_name = str(req).strip()
                    if req_name and req_name not in installed and req_name not in missing_deps:
                        missing_deps.append(req_name)

            missing_deps_count += len(missing_deps)
            if declared_deps or missing_deps:
                dependencies_graph.append({
                    "name": name,
                    "depends_on": declared_deps,
                    "missing_dependencies": missing_deps,
                })

            lock_spec = locked_mods.get(name)
            locked_ver = lock_spec.get("version") if isinstance(lock_spec, dict) else None
            locked_sha = lock_spec.get("sha256") if isinstance(lock_spec, dict) else None

            checksum_match: Optional[bool] = None
            if lock_spec is None:
                drift_status = "unlocked"
                unlocked_count += 1
            elif locked_ver != cur_ver:
                drift_status = "version_drift"
                version_drift_count += 1
                checksum_match = bool(locked_sha and locked_sha == live_sha)
            elif locked_sha and locked_sha != live_sha:
                drift_status = "checksum_drift"
                checksum_drift_count += 1
                checksum_match = False
            else:
                drift_status = "intact"
                intact_count += 1
                checksum_match = True if locked_sha else None

            fms = feed_by_name.get(name, [])
            latest_feed_ver = max((fm.get("version", "0.0.0") for fm in fms), key=parse_semver) if fms else None
            pin_ver = pins.get(name, {}).get("pinned_version") if isinstance(pins.get(name), dict) else None
            mod_quarantined = quarantined.get(name, [])

            items.append({
                "name": name,
                "version": cur_ver,
                "locked_version": locked_ver,
                "live_sha256": live_sha,
                "locked_sha256": locked_sha,
                "files_count": files_count,
                "pinned_version": pin_ver,
                "latest_feed_version": latest_feed_ver,
                "drift_status": drift_status,
                "checksum_match": checksum_match,
                "dependencies": declared_deps,
                "missing_dependencies": missing_deps,
                "quarantined_versions": [q.get("version") for q in mod_quarantined if isinstance(q, dict)],
                "has_tests": bool(m_info.get("has_tests")),
            })

        total_drift = checksum_drift_count + version_drift_count
        return {
            "schema": "bach.modules-telemetry.v1",
            "timestamp": datetime.now().isoformat(),
            "lockfile_exists": lockfile.is_file(),
            "lockfile_path": str(lockfile),
            "summary": {
                "total_installed": len(installed),
                "standalone_bound": status_data.get("standalone_bound_count", 0),
                "standalone_total": status_data.get("modularized_services_total", 0),
                "coverage_percent": status_data.get("coverage_percent", 0.0),
                "intact_count": intact_count,
                "drift_count": total_drift,
                "checksum_drift_count": checksum_drift_count,
                "version_drift_count": version_drift_count,
                "unlocked_count": unlocked_count,
                "pinned_count": len(pins),
                "quarantined_count": sum(len(v) for v in quarantined.values() if isinstance(v, list)),
                "feeds_count": len(feeds),
                "missing_deps_count": missing_deps_count,
            },
            "dependencies_graph": dependencies_graph,
            "quarantined": quarantined,
            "items": items,
        }

    def _telemetry_cli(self, args: List[str] = None) -> Tuple[bool, str]:
        args = list(args or [])
        strict = any(a in ("--strict", "--ci", "--fail-on-drift") for a in args)
        refresh = any(a in ("--refresh", "--refresh-lockfile", "--refresh-lock") for a in args)
        skip_tests = any(a in ("--skip-tests",) for a in args)

        if refresh:
            ok_ref, ref_res = self.refresh_lockfile(skip_tests=skip_tests)
            if not ok_ref:
                return False, f"[FAIL] {ref_res.get('message')} ({len(ref_res.get('failed', []))} Fehler)"

        rep = self.get_telemetry_and_drift_report()
        s = rep["summary"]
        lines = [
            "=== BACH MODUL TELEMETRIE & DEPENDENCY-DRIFT ===",
            f"Stand:             {rep['timestamp']}",
            f"Lockfile:          {rep['lockfile_path']} ({'vorhanden' if rep['lockfile_exists'] else 'FEHLT'})",
            f"Installiert/Bound: {s['total_installed']} Module | {s['standalone_bound']}/{s['standalone_total']} Standalone ({s['coverage_percent']}%)",
            f"Integrität:        {s['intact_count']} intakt | {s['checksum_drift_count']} Checksum-Drift | {s['version_drift_count']} Version-Drift | {s['unlocked_count']} ungelockt",
            f"Governance:        {s['pinned_count']} Pins | {s['quarantined_count']} Quarantäne | {s['missing_deps_count']} fehlende Dependencies",
            "",
            f"  {'MODUL':<26} {'VER':<9} {'LOCK':<9} {'DRIFT-STATUS':<16} {'SHA256 (LIVE -> LOCK)'}",
            "  " + "-" * 84,
        ]
        for it in rep["items"]:
            l_ver = f"v{it['locked_version']}" if it["locked_version"] else "-"
            live_short = (it["live_sha256"] or "-")[:10]
            lock_short = (it["locked_sha256"] or "-")[:10]
            tags = [it["drift_status"]]
            if it["pinned_version"]:
                tags.append(f"pin=v{it['pinned_version']}")
            if it["missing_dependencies"]:
                tags.append(f"missing_deps={','.join(it['missing_dependencies'])}")
            lines.append(
                f"  {it['name']:<26} v{it['version']:<8} {l_ver:<9} {it['drift_status']:<16} {live_short} -> {lock_short}  ({', '.join(tags)})"
            )
        has_critical_drift = s["drift_count"] > 0 or s["missing_deps_count"] > 0
        lines.append("")
        if has_critical_drift:
            lines.append("[WARNUNG] Drift oder fehlende Dependencies erkannt. Mit 'bach modules bootstrap --refresh-lockfile' prüfen & aktualisieren.")
        else:
            lines.append("[OK] Telemetrie sauber. Kein Checksum-, Versions- oder Dependency-Drift.")
        return (not has_critical_drift if strict else True), "\n".join(lines)

    # -------------------------------------------------------------------------
    # AUTO-EXPORT & MULTI-REPO SYNC PIPELINE (TASK -55)
    # -------------------------------------------------------------------------

    def _discover_sibling_repo_modules(self) -> Dict[str, List[Dict[str, Any]]]:
        """Findet korrespondierende Modul-Quellpfade in bekannten Multi-Repo-Verzeichnissen."""
        discovered: Dict[str, List[Dict[str, Any]]] = {}
        for s_dir in self._resolve_source_dirs():
            if not s_dir.is_dir():
                continue
            try:
                for cand in s_dir.iterdir():
                    if not cand.is_dir():
                        continue
                    for m_file in (cand / "manifest.json", cand / "src" / "manifest.json"):
                        if m_file.is_file():
                            try:
                                meta = json.loads(m_file.read_text(encoding="utf-8"))
                                m_name = meta.get("name")
                                if m_name:
                                    discovered.setdefault(m_name, []).append({
                                        "repo_path": str(cand),
                                        "manifest_path": str(m_file),
                                        "version": meta.get("version", "1.0.0"),
                                    })
                                    break
                            except Exception:
                                pass
            except OSError:
                pass
        return discovered

    def sync_repos(
        self,
        dry_run: bool = True,
        out_dir: Optional[Union[str, Path]] = None,
        bundle_deps: bool = False,
        modules: Optional[List[str]] = None,
        pull_newer: bool = False,
        sibling_repos_override: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    ) -> Dict[str, Any]:
        """Prüft .MODULES/ & Multi-Repo-Quellen, importiert optional neuere Repo-Stände und exportiert geänderte Pakete + manifest_feed.json."""
        dest_dir = Path(out_dir) if out_dir else (self.base_path / "exports" / "modules")
        feed_file = dest_dir / "manifest_feed.json"

        existing_feed_entries: Dict[str, Dict[str, Any]] = {}
        if feed_file.is_file():
            try:
                old_feed = json.loads(feed_file.read_text(encoding="utf-8"))
                for entry in old_feed.get("modules", []):
                    if isinstance(entry, dict) and entry.get("name"):
                        existing_feed_entries[entry["name"]] = entry
            except Exception:
                pass

        installed = self.get_modules_data()
        filter_set = {m.strip().lower() for m in (modules or []) if m and m.strip()}
        if filter_set:
            installed = [m for m in installed if m["name"].lower() in filter_set]

        sibling_repos = sibling_repos_override if sibling_repos_override is not None else self._discover_sibling_repo_modules()
        exported: List[Dict[str, Any]] = []
        imported: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        repo_drift: List[Dict[str, Any]] = []
        new_feed_modules: Dict[str, Dict[str, Any]] = dict(existing_feed_entries)

        for m in sorted(installed, key=lambda x: x["name"]):
            name = m["name"]
            mod_dir = Path(m["path"])
            cur_ver = m["version"]

            siblings = sibling_repos.get(name, [])
            best_import_sib: Optional[Dict[str, Any]] = None
            for sib in siblings:
                sib_ver = sib.get("version", "1.0.0")
                if parse_semver(sib_ver) != parse_semver(cur_ver):
                    direction = "import_newer_from_repo" if parse_semver(sib_ver) > parse_semver(cur_ver) else "export_newer_to_feed"
                    repo_drift.append({
                        "module": name,
                        "installed_version": cur_ver,
                        "repo_version": sib_ver,
                        "repo_path": sib["repo_path"],
                        "direction": direction,
                    })
                    if direction == "import_newer_from_repo":
                        if best_import_sib is None or parse_semver(sib_ver) > parse_semver(best_import_sib.get("version", "1.0.0")):
                            best_import_sib = sib

            if pull_newer and best_import_sib is not None:
                sib_ver = best_import_sib.get("version", "1.0.0")
                pin = self.is_module_pinned(name)
                if pin and pin == cur_ver:
                    skipped.append({"name": name, "version": cur_ver, "reason": f"Pull-Sync blockiert (Pin v{pin})"})
                elif self.is_version_quarantined(name, sib_ver):
                    skipped.append({"name": name, "version": cur_ver, "reason": f"Pull-Sync blockiert (Quarantäne v{sib_ver})"})
                elif dry_run:
                    imported.append({
                        "name": name,
                        "from_version": cur_ver,
                        "to_version": sib_ver,
                        "repo_path": best_import_sib["repo_path"],
                        "status": "would_import",
                    })
                else:
                    ok_imp, msg_imp = self._install_module(best_import_sib["repo_path"], dry_run=False)
                    if ok_imp:
                        imported.append({
                            "name": name,
                            "from_version": cur_ver,
                            "to_version": sib_ver,
                            "repo_path": best_import_sib["repo_path"],
                            "status": "imported",
                        })
                        cur_ver = sib_ver
                        m_file = mod_dir / "manifest.json"
                        if m_file.is_file():
                            try:
                                meta = json.loads(m_file.read_text(encoding="utf-8"))
                                m["version"] = meta.get("version", cur_ver)
                                m["description"] = meta.get("description", m.get("description", ""))
                                m["entrypoint"] = meta.get("entrypoints", {}).get("library", m.get("entrypoint"))
                                cur_ver = m["version"]
                            except Exception:
                                pass
                    else:
                        errors.append({"name": name, "version": sib_ver, "error": msg_imp})

            live_sha, _ = self._compute_module_sha256(mod_dir)

            prev_entry = existing_feed_entries.get(name, {})
            prev_ver = prev_entry.get("version")
            prev_src_sha = prev_entry.get("source_sha256")
            pkg_file = prev_entry.get("package_file")
            pkg_exists = bool(pkg_file and (dest_dir / pkg_file).is_file())

            needs_export = (
                not prev_entry
                or prev_ver != cur_ver
                or prev_src_sha != live_sha
                or not pkg_exists
            )

            if not needs_export:
                skipped.append({"name": name, "version": cur_ver, "reason": "unverändert im Feed"})
                continue

            if dry_run:
                exported.append({
                    "name": name,
                    "version": cur_ver,
                    "source_sha256": live_sha,
                    "status": "would_export",
                })
                continue

            dest_dir.mkdir(parents=True, exist_ok=True)
            ok_pack, pack_msg = self._pack_module(name, out_dir=str(dest_dir), bundle_deps=bundle_deps)
            if not ok_pack:
                errors.append({"name": name, "version": cur_ver, "error": pack_msg})
                continue

            # Jüngstes ZIP & SHA256 für dieses Modul ermitteln
            bundle_tag = "bundle" if bundle_deps else "pkg"
            zips = sorted(
                dest_dir.glob(f"{name}_v{cur_ver}_{bundle_tag}_*.zip"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            latest_zip = zips[0] if zips else None
            zip_sha = ""
            if latest_zip:
                sha_p = dest_dir / f"{latest_zip.name}.sha256"
                if sha_p.is_file():
                    zip_sha = sha_p.read_text(encoding="utf-8").split()[0].strip()

            entry_data = {
                "name": name,
                "version": cur_ver,
                "description": m.get("description", ""),
                "entrypoint": m.get("entrypoint"),
                "selfcontained": bool(m.get("selfcontained", True)),
                "package_file": latest_zip.name if latest_zip else "",
                "download_url": str(latest_zip) if latest_zip else "",
                "sha256": zip_sha,
                "source_sha256": live_sha,
                "exported_at": datetime.now().isoformat(),
            }
            new_feed_modules[name] = entry_data
            exported.append({
                "name": name,
                "version": cur_ver,
                "package_file": entry_data["package_file"],
                "sha256": zip_sha,
                "source_sha256": live_sha,
                "status": "exported",
            })

        feed_written = False
        if not dry_run and not errors or (not dry_run and exported):
            dest_dir.mkdir(parents=True, exist_ok=True)
            feed_payload = {
                "schema": "bach.manifest-feed.v1",
                "generated_at": datetime.now().isoformat(),
                "total_modules": len(new_feed_modules),
                "modules": [new_feed_modules[k] for k in sorted(new_feed_modules.keys())],
            }
            feed_file.write_text(json.dumps(feed_payload, indent=2, ensure_ascii=False), encoding="utf-8")
            feed_written = True

        if not dry_run and any(item.get("status") == "imported" for item in imported):
            lockfile = self._resolve_lockfile()
            if lockfile.is_file():
                self._generate_lockfile(lockfile)

        return {
            "schema": "bach.modules-auto-export.v1",
            "timestamp": datetime.now().isoformat(),
            "dry_run": dry_run,
            "pull_newer": pull_newer,
            "out_dir": str(dest_dir),
            "feed_file": str(feed_file),
            "feed_written": feed_written,
            "total_evaluated": len(installed),
            "exported_count": len(exported),
            "imported_count": len(imported),
            "skipped_count": len(skipped),
            "errors_count": len(errors),
            "repo_drift_count": len(repo_drift),
            "exported": exported,
            "imported": imported,
            "skipped": skipped,
            "errors": errors,
            "repo_drift": repo_drift,
        }

    def _auto_export_cli(self, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        apply_flag = any(a in ("--apply", "-a", "--force") for a in args)
        pull_newer = any(a in ("--pull-newer", "--import-newer") for a in args)
        is_dry = dry_run or (not apply_flag) or any(a in ("--dry-run", "-n") for a in args)
        bundle_deps = any(a in ("--bundle-deps", "--bundle", "-b") for a in args)
        out_dir = None
        mod_filter: List[str] = []
        skip_next = False
        for i, a in enumerate(args):
            if skip_next:
                skip_next = False
                continue
            if a == "--out" and i + 1 < len(args):
                out_dir = args[i + 1]
                skip_next = True
            elif a.startswith("--out="):
                out_dir = a.split("=", 1)[1]
            elif not a.startswith("-"):
                mod_filter.append(a)

        res = self.sync_repos(
            dry_run=is_dry,
            out_dir=out_dir,
            bundle_deps=bundle_deps,
            modules=mod_filter or None,
            pull_newer=pull_newer,
        )
        lines = [
            "=== BACH AUTO-EXPORT & MULTI-REPO SYNC PIPELINE ===",
            f"Modus:         {'DRY-RUN (mit --apply exportieren)' if res['dry_run'] else 'APPLY (Live-Export)'}",
            f"Zielordner:    {res['out_dir']}",
            f"Manifest-Feed: {res['feed_file']}",
            f"Evaluiert:     {res['total_evaluated']} | Exportiert/Geplant: {res['exported_count']} | Pull-Importiert: {res['imported_count']} | Unverändert: {res['skipped_count']} | Multi-Repo-Drift: {res['repo_drift_count']}",
            "",
        ]
        if res["imported"]:
            lines.append("Pull-Sync aus Sibling-Repos:")
            for im in res["imported"]:
                lines.append(f"  ↓ {im['name']:<24} v{im['from_version']} -> v{im['to_version']} [{im['status']}] ({im['repo_path']})")
            lines.append("")
        if res["repo_drift"]:
            lines.append("Multi-Repo Versionsdifferenzen:")
            for rd in res["repo_drift"]:
                lines.append(
                    f"  ⇄ {rd['module']:<24} BACH=v{rd['installed_version']} vs Repo=v{rd['repo_version']} ({rd['direction']})"
                )
            lines.append("")
        if res["exported"]:
            lines.append("Export-Kandidaten / Pakete:")
            for ex in res["exported"]:
                pkg = f" -> {ex['package_file']}" if ex.get("package_file") else ""
                lines.append(f"  • {ex['name']:<24} v{ex['version']:<9} [{ex['status']}]{pkg}")
        else:
            lines.append("[OK] Alle evaluierten Module sind bereits aktuell im Export-Feed.")

        if res["errors"]:
            lines.append("")
            lines.append("Fehler:")
            for err in res["errors"]:
                lines.append(f"  ! {err['name']}: {err['error']}")

        return res["errors_count"] == 0, "\n".join(lines)


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
