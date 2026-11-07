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
            "export": "Modul als Standalone-Paket exportieren (bach modules export <name>)",
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
        elif op in ("wire", "hotwire", "hot-wire"):
            return self._wire_modules()
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

    def _install_module(self, source_path_str: str, dry_run: bool = False) -> Tuple[bool, str]:
        source = Path(source_path_str)
        if not source.exists():
            return False, f"Quelldatei oder -verzeichnis existiert nicht: {source}"

        tmp_extract_dir: Optional[Path] = None
        inspect_dir = source

        if source.is_file() and source.suffix.lower() == ".zip":
            tmp_extract_dir = self.modules_dir / f".tmp_extract_{int(time.time())}"
            tmp_extract_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(source, "r") as zf:
                zf.extractall(tmp_extract_dir)
            # Finde Wurzel mit manifest.json
            found = list(tmp_extract_dir.glob("**/manifest.json"))
            if not found:
                shutil.rmtree(tmp_extract_dir, ignore_errors=True)
                return False, f"Ungültiges Modul-ZIP: kein manifest.json gefunden in {source}"
            inspect_dir = found[0].parent

        manifest_file = inspect_dir / "manifest.json"
        if not manifest_file.is_file():
            if tmp_extract_dir:
                shutil.rmtree(tmp_extract_dir, ignore_errors=True)
            return False, f"manifest.json nicht gefunden in {inspect_dir}"

        try:
            meta = json.loads(manifest_file.read_text(encoding="utf-8"))
        except Exception as exc:
            if tmp_extract_dir:
                shutil.rmtree(tmp_extract_dir, ignore_errors=True)
            return False, f"manifest.json konnte nicht geparst werden: {exc}"

        name = meta.get("name")
        version = meta.get("version", "1.0.0")
        if not name:
            if tmp_extract_dir:
                shutil.rmtree(tmp_extract_dir, ignore_errors=True)
            return False, "Fehlender 'name' im Manifest."

        target_dir = self.modules_dir / name

        if dry_run:
            if tmp_extract_dir:
                shutil.rmtree(tmp_extract_dir, ignore_errors=True)
            return True, f"[DRY-RUN] Modul '{name}' v{version} würde nach {target_dir} installiert."

        # Backup erstellen falls existent
        if target_dir.is_dir():
            backup_dir = self.modules_dir / ".backup" / f"{name}_{int(time.time())}"
            backup_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(target_dir, backup_dir)

        # Installation durchführen
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.copytree(inspect_dir, target_dir)

        if tmp_extract_dir:
            shutil.rmtree(tmp_extract_dir, ignore_errors=True)

        invalidate_module_cache()
        wire_report = auto_switch_to_standalone_modules()

        return True, (
            f"[OK] Modul '{name}' v{version} erfolgreich installiert nach {target_dir}.\n"
            f"Hot-Wiring ausgeführt ({wire_report['total_switched']} Module verdrahtet)."
        )

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
        """Sucht nach neueren Modulversionen in allen Quellpfaden und aktualisiert sie."""
        installed = {m["name"]: m for m in self.get_modules_data()}
        source_dirs = self._resolve_source_dirs()

        lines = [
            "=== MODUL-UPDATE-SCAN ===",
            f"Prüfe {len(installed)} installierte Module gegen {len(source_dirs)} Quellen...",
            "",
        ]

        updates_found: List[Dict[str, Any]] = []

        for s_dir in source_dirs:
            if not s_dir.is_dir():
                continue
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
                                "source_path": cand,
                                "target_path": self.modules_dir / c_name,
                            })
                except Exception:
                    pass

        if not updates_found:
            lines.append("[INFO] Alle installierten Module sind auf dem aktuellen Stand.")
            return True, "\n".join(lines)

        lines.append(f"Verfügbare Updates: {len(updates_found)}")
        for upd in updates_found:
            status_text = "[DRY-RUN] Würde aktualisieren" if dry_run else "[AKTUALISIERT]"
            lines.append(f"  • {upd['name']:<24} v{upd['current_version']} -> v{upd['new_version']} {status_text}")
            if not dry_run:
                # Backup and copy
                tgt = upd["target_path"]
                if tgt.exists():
                    backup_dir = self.modules_dir / ".backup" / f"{upd['name']}_{int(time.time())}"
                    backup_dir.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(tgt, backup_dir)
                    shutil.rmtree(tgt)
                shutil.copytree(upd["source_path"], tgt)

        if not dry_run:
            global _MODULES_UPDATE_CACHE
            _MODULES_UPDATE_CACHE = {"data": None, "timestamp": 0.0}
            invalidate_module_cache()
            wire_res = auto_switch_to_standalone_modules()
            lines.append("")
            lines.append(f"[OK] {len(updates_found)} Modul(e) erfolgreich aktualisiert und hot-wired ({wire_res['total_switched']} aktiv).")
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
