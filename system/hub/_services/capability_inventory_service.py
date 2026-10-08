# SPDX-License-Identifier: MIT
"""Bounded, read-only inventories from actual host files.

Configuration and code presence do not prove a connected MCP session, an
active client plugin or an installed application. Secrets and launch arguments
are excluded from every projection.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from itertools import islice
from pathlib import Path
from urllib.parse import urlsplit

MAX_DOCUMENT_BYTES = 2_000_000
MAX_ITEMS = 500
SKIP = {"cache", "marketplaces", ".git", ".venv", "node_modules", "dist", "build",
        "_archive", "archive", "__pycache__"}


def _text(value, limit=300):
    return value[:limit] if isinstance(value, str) and "\x00" not in value else ""


def _roots(variable: str, defaults: list[Path]) -> list[Path]:
    if variable not in os.environ:
        return defaults
    values = json.loads(os.environ[variable])
    if (not isinstance(values, list) or len(values) > 20
            or any(not isinstance(p, str) or not p for p in values)):
        raise ValueError(variable + " benötigt eine Liste absoluter Pfade")
    paths = [Path(p).expanduser() for p in values]
    if any(not p.is_absolute() for p in paths):
        raise ValueError(variable + " benötigt absolute Pfade")
    return list(dict.fromkeys(paths))


def _document(path: Path):
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ValueError("Quelldatei fehlt oder überschreitet die Lesegrenze")
    raw = path.read_bytes()
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ValueError("Quelldatei überschreitet die Lesegrenze")
    if path.suffix == ".toml":
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib
        data = tomllib.loads(raw.decode("utf-8"))
    else:
        data = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("Quelldatei benötigt ein Objekt")
    return data, hashlib.sha256(raw).hexdigest()


def _metadata(folder: Path) -> tuple[dict, str | None]:
    for relative in ("ellmos-module.v2.json", "ellmos-module.json",
                     ".claude-plugin/plugin.json", ".codex-plugin/plugin.json",
                     "gemini-extension.json", "plugin.json", "package.json", "pyproject.toml"):
        candidate = folder / relative
        if not candidate.is_file():
            continue
        if candidate.is_symlink() or not candidate.resolve().is_relative_to(folder.resolve()):
            continue
        try:
            data, revision = _document(candidate)
            if relative == "pyproject.toml":
                data = data.get("project") or {}
            return data if isinstance(data, dict) else {}, revision
        except (OSError, UnicodeError, ValueError):
            continue
    return {}, None


def _base(kind: str, roots: list[Path]):
    return {"schema": "bach.capability-inventory.v1", "kind": kind, "items": [],
            "sources": [{"path": str(p), "available": p.is_dir()} for p in roots],
            "errors": [], "truncated": False}


def plugin_inventory(roots: list[Path] | None = None) -> dict:
    home = Path.home()
    roots = roots if roots is not None else _roots("BACH_PLUGIN_ROOTS", [
        home / "OneDrive/.TOPICS/.AI/.PLUGINS", home / ".gemini/config/plugins",
        home / ".gemini/extensions", home / ".claude/plugins", home / ".codex/plugins"])
    result = _base("plugins", roots)
    entries = {}
    enabled = {}
    codex_enabled = {}
    try:
        settings, _ = _document(home / ".claude/settings.json")
        enabled = settings.get("enabledPlugins") or {}
        if not isinstance(enabled, dict):
            enabled = {}
    except (OSError, UnicodeError, ValueError):
        pass
    try:
        settings, _ = _document(home / ".codex/config.toml")
        configured = settings.get("plugins", {})
        if isinstance(configured, dict):
            codex_enabled = {name: value.get("enabled") for name, value in configured.items()
                             if isinstance(value, dict) and type(value.get("enabled")) is bool}
    except (OSError, UnicodeError, ValueError):
        pass

    def add(name, folder, consumer, evidence, enabled_value=None):
        if not isinstance(name, str) or not name or "\x00" in name:
            return
        key = consumer + ":" + name + ":" + hashlib.sha256(str(folder).encode("utf-8")).hexdigest()[:12]
        if key in entries:
            return
        if len(entries) >= MAX_ITEMS:
            result["truncated"] = True
            return
        present = folder is not None and folder.is_dir() and not folder.is_symlink()
        meta, revision = _metadata(folder) if present else ({}, None)
        entries[key] = {"id": key, "name": _text(meta.get("name")) or name[:180],
                        "description": _text(meta.get("description")),
                        "version": _text(meta.get("version"), 100) or None,
                        "source_version": revision, "consumer": consumer,
                        "code_present": present, "evidence": evidence,
                        "enabled_in_client": enabled_value if type(enabled_value) is bool else None,
                        "runtime_active": None, "connection_state": "unverified",
                        "path": str(folder) if folder else None}

    cache_directories = 0

    def cache_children(path):
        nonlocal cache_directories
        if path.is_symlink() or not path.is_dir() or cache_directories >= 4096:
            if cache_directories >= 4096:
                result["truncated"] = True
            return []
        cache_directories += 1
        children = sorted(islice(path.iterdir(), MAX_ITEMS + 1), key=lambda p: p.name)
        if len(children) > MAX_ITEMS:
            result["truncated"] = True
        return [p for p in children[:MAX_ITEMS] if p.is_dir() and not p.is_symlink() and not p.name.startswith(".")]

    for root in roots:
        if not root.is_dir() or root.is_symlink():
            continue
        registry = root / "installed_plugins.json"
        if registry.is_file():
            try:
                data, _ = _document(registry)
                plugins = data.get("plugins") or {}
                if not isinstance(plugins, dict) or len(plugins) > MAX_ITEMS:
                    raise ValueError("Pluginregister überschreitet die Lesegrenze")
                for name, installs in plugins.items():
                    for entry in installs if isinstance(installs, list) else [installs]:
                        if not isinstance(entry, dict):
                            continue
                        raw = entry.get("installPath")
                        folder = Path(raw).expanduser() if isinstance(raw, str) and raw else None
                        if folder and not folder.is_absolute():
                            folder = root / folder
                        add(name, folder, "Claude", "installed_plugins.json", enabled.get(name))
            except (OSError, UnicodeError, ValueError) as exc:
                result["errors"].append({"source": str(registry), "reason": type(exc).__name__})
        try:
            if ".codex" in root.parts:
                for marketplace in cache_children(root / "cache"):
                    for plugin in cache_children(marketplace):
                        for version in cache_children(plugin):
                            if len(entries) >= MAX_ITEMS:
                                result["truncated"] = True
                                break
                            _, revision = _metadata(version)
                            if revision is not None:
                                key = plugin.name + "@" + marketplace.name
                                add(key, version, "Codex", "cached_plugin_manifest", codex_enabled.get(key))
            children = sorted(islice(root.iterdir(), MAX_ITEMS + 1), key=lambda p: p.name)
            if len(children) > MAX_ITEMS:
                result["truncated"] = True
            for folder in children[:MAX_ITEMS]:
                if not folder.is_dir() or folder.is_symlink() or folder.name in SKIP or folder.name.startswith("."):
                    continue
                meta, revision = _metadata(folder)
                if revision is not None:
                    consumer = "Gemini" if ".gemini" in folder.parts else "Codex" if ".codex" in folder.parts else "Host-Bibliothek"
                    add(folder.name, folder, consumer, "manifest_present")
        except OSError as exc:
            result["errors"].append({"source": str(root), "reason": type(exc).__name__})
    result["items"] = sorted(entries.values(), key=lambda x: (x["consumer"], x["name"].casefold()))
    result["count"] = len(result["items"])
    return result


def mcp_inventory(configs: list[Path] | None = None) -> dict:
    home = Path.home()
    configs = configs if configs is not None else _roots("BACH_MCP_CONFIGS", [
        home / ".codex/config.toml", home / ".claude.json", home / ".gemini/settings.json",
        home / ".gemini/antigravity-cli/settings.json"])
    result = {"schema": "bach.capability-inventory.v1", "kind": "mcp", "items": [],
              "sources": [], "errors": [], "truncated": False,
              "runtime_source": None, "active_connection_count": None}
    for path in configs:
        result["sources"].append({"path": str(path), "available": path.is_file()})
        if not path.is_file():
            continue
        try:
            data, revision = _document(path)
            catalogs = [("global", data.get("mcp_servers", data.get("mcpServers", {})))]
            projects = data.get("projects", {})
            if isinstance(projects, dict):
                if len(projects) > MAX_ITEMS:
                    raise ValueError("MCP-Projektregister überschreitet die Lesegrenze")
                catalogs.extend((scope, project["mcpServers"]) for scope, project in projects.items()
                                if isinstance(project, dict) and "mcpServers" in project)
            client = "Codex" if ".codex" in path.parts else "Claude" if path.name == ".claude.json" else "Gemini" if ".gemini" in path.parts else "Host-Konfiguration"
            for scope, servers in catalogs:
                if not isinstance(servers, dict) or len(servers) > MAX_ITEMS:
                    raise ValueError("MCP-Register überschreitet die Lesegrenze")
                for name, config in servers.items():
                    if len(result["items"]) >= MAX_ITEMS:
                        result["truncated"] = True
                        break
                    if not isinstance(name, str) or not isinstance(config, dict):
                        continue
                    command = config.get("command")
                    executable = (command if isinstance(command, str)
                                  and re.fullmatch(r"[^\s\x00=\"';&|<>`$]+", command) else "")
                    basename = executable.replace("\\", "/").rsplit("/", 1)[-1]
                    command_name = basename if re.fullmatch(r"[A-Za-z0-9._+-]{1,100}", basename) else None
                    address = config.get("url")
                    hostname = None
                    if isinstance(address, str):
                        try:
                            parsed = urlsplit(address)
                            hostname = parsed.hostname if parsed.scheme in {"https", "http"} else None
                        except ValueError:
                            pass
                    flag = config.get("enabled")
                    if type(flag) is not bool and type(config.get("disabled")) is bool:
                        flag = not config["disabled"]
                    location = hashlib.sha256((str(path) + ":" + scope).encode("utf-8")).hexdigest()[:12]
                    result["items"].append({
                        "id": client + ":" + name + ":" + location, "name": _text(name, 180), "consumer": client,
                        "scope": scope,
                        "transport": "stdio" if isinstance(command, str) else "http" if isinstance(address, str) else "unknown",
                        "command_name": command_name, "hostname": hostname,
                        "enabled_in_client": flag if type(flag) is bool else None,
                        "connection_state": "configured", "runtime_connected": None,
                        "source_version": revision, "source": str(path),
                        "authorization_configured": bool(config.get("headers") or config.get("env") or config.get("env_vars")),
                    })
        except (OSError, UnicodeError, ValueError) as exc:
            result["errors"].append({"source": str(path), "reason": type(exc).__name__})
    result["count"] = len(result["items"])
    return result


def software_inventory(roots: list[Path] | None = None) -> dict:
    home = Path.home()
    if "BACH_REPOSITORIES_ROOT" in os.environ and not os.environ["BACH_REPOSITORIES_ROOT"].strip():
        raise ValueError("BACH_REPOSITORIES_ROOT darf nicht leer sein")
    repository_roots = ([Path(os.environ["BACH_REPOSITORIES_ROOT"]).expanduser()]
                        if "BACH_REPOSITORIES_ROOT" in os.environ else
                        [home / "services", home / "_Local_DEV/repos"])
    legacy = Path("C:/_Local_DEV/repos")
    if "BACH_REPOSITORIES_ROOT" not in os.environ and legacy.is_dir():
        repository_roots.append(legacy)
    roots = roots if roots is not None else _roots("BACH_SOFTWARE_ROOTS", repository_roots)
    if any(not p.is_absolute() for p in roots):
        raise ValueError("Software-Wurzeln müssen absolut sein")
    result = _base("software", roots)
    seen = set()
    for root in roots:
        if not root.is_dir() or root.is_symlink():
            continue
        try:
            children = sorted(islice(root.iterdir(), MAX_ITEMS + 1), key=lambda p: p.name)
            if len(children) > MAX_ITEMS:
                result["truncated"] = True
            for folder in children[:MAX_ITEMS]:
                if len(result["items"]) >= MAX_ITEMS:
                    result["truncated"] = True
                    break
                if not folder.is_dir() or folder.is_symlink() or folder.name in SKIP or folder.name.startswith("."):
                    continue
                resolved = str(folder.resolve())
                if resolved in seen:
                    continue
                meta, revision = _metadata(folder)
                is_repository = (folder / ".git").exists()
                if revision is None and not is_repository:
                    continue
                seen.add(resolved)
                result["items"].append({
                    "id": folder.name, "name": _text(meta.get("display_name") or meta.get("name")) or folder.name,
                    "description": _text(meta.get("description")),
                    "version": _text(meta.get("version"), 100) or None,
                    "source_version": revision, "code_present": True, "installed": None,
                    "runtime_active": None, "evidence": "manifest_present" if revision else "repository_present",
                    "path": str(folder)})
        except OSError as exc:
            result["errors"].append({"source": str(root), "reason": type(exc).__name__})
    result["count"] = len(result["items"])
    return result
