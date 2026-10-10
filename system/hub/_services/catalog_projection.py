"""Read-only catalog projection ``bach.catalog.v1`` (#2016).

Projects existing catalog files into one item list at request time. It stores nothing,
creates no inventory database and never returns absolute paths: sources are reported with a
symbolic ``path_label``. Missing or broken sources are ``availability: missing|error`` with
empty items, never mock data. Counts are always derived from the returned items. Architecture
(``relations``, ``basis: declared``) and measurement (``measured``, ``git``) stay separate;
git values are ``unknown`` unless a host-bound record says otherwise. A host is never derived
from a file name (OneDrive conflict copies like ``...-ASUS-GEI-2.json`` are not read).

Source locations (environment first, defaults only when the path exists):
  BACH_CATALOG_AI_ROOT          directory with .MODULES/modules.catalog.json and .BUNDLES/
  BACH_CATALOG_SKILLS_REGISTRY  skills/registry/components.json
  BACH_CATALOG_GITHUBBOT_CONFIG directory with master_satellite_catalog.json, repo_registry.json
  BACH_CATALOG_SYNC_ROOT        .SYNC directory containing <slot>/repos.json host manifests
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA = "bach.catalog.v1"
KINDS = ("module", "bundle", "skill", "satellite")
MAX_ITEMS = 5000
MAX_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class CatalogConfig:
    ai_root: Path | None = None
    skills_registry: Path | None = None
    githubbot_config: Path | None = None
    sync_root: Path | None = None


def _env_or_existing(variable: str, candidates: list[Path]) -> Path | None:
    configured = os.environ.get(variable, "").strip()
    if configured:
        return Path(os.path.expandvars(configured)).expanduser()
    return next((p for p in candidates if p.exists()), None)


def config_from_environment() -> CatalogConfig:
    home = Path.home()
    onedrive = Path(os.environ.get("OneDrive") or home / "OneDrive").expanduser()
    drive_root = Path(home.anchor or home.root or "/")
    skills_repo = os.environ.get("ELLMOS_SKILLS_REPO", "").strip()
    skill_candidates = ([Path(skills_repo) / "registry" / "components.json"] if skills_repo else []) + [
        home / "_Local_DEV" / "repos" / "skills" / "registry" / "components.json",
        drive_root / "_Local_DEV" / "repos" / "skills" / "registry" / "components.json"]
    return CatalogConfig(
        ai_root=_env_or_existing("BACH_CATALOG_AI_ROOT", [onedrive / ".TOPICS" / ".AI"]),
        skills_registry=_env_or_existing("BACH_CATALOG_SKILLS_REGISTRY", skill_candidates),
        githubbot_config=_env_or_existing("BACH_CATALOG_GITHUBBOT_CONFIG", [onedrive / ".GITHUBBOT" / "config"]),
        sync_root=_env_or_existing("BACH_CATALOG_SYNC_ROOT", [onedrive / ".SYNC"]))


def _text(value, limit=500):
    return value.strip()[:limit] if isinstance(value, str) and value.strip() else None


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def _read(path: Path):
    """Return (data, version, mtime). Raises OSError/ValueError on unreadable input."""
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError("missing")
    stat = path.stat()
    if stat.st_size > MAX_BYTES:
        raise ValueError("too_large")
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-8-sig")), hashlib.sha256(raw).hexdigest(), _iso(stat.st_mtime)


class _Source:
    """Collects one source record; a failure becomes availability, never an exception."""

    def __init__(self, source_id, kind, label, path: Path | None):
        self.record = {"id": source_id, "kind": kind, "path_label": label, "host": None, "schema": None,
                       "source_version": None, "generated_at": None, "availability": "missing", "error": None}
        self.path = path
        self.data = None

    def load(self):
        if self.path is None:
            self.record["error"] = "not_configured"
            return None
        try:
            data, version, mtime = _read(self.path)
        except FileNotFoundError:
            self.record["error"] = "file_missing"
            return None
        except (OSError, ValueError, UnicodeError) as exc:
            self.record.update(availability="error", error=type(exc).__name__)
            return None
        if not isinstance(data, dict):
            self.record.update(availability="error", error="not_an_object")
            return None
        self.record.update(availability="available", source_version=version, error=None,
                           schema=_text(data.get("schema"), 120),
                           generated_at=_text(data.get("generated_at")) or mtime)
        self.record["generated_at_basis"] = "declared" if _text(data.get("generated_at")) else "file_mtime"
        self.data = data
        return data


def _measured():
    return {"installed": None, "runtime_active": None, "connection_state": "unverified",
            "observed_at": None, "host": None, "evidence": None}


def _unknown_git():
    return {"state": "unknown", "branch": None, "last_commit": None, "observed_at": None, "host": None, "source": None}


def _item(item_id, item_type, name, source_id, **extra):
    base = {"id": item_id, "type": item_type, "aliases": [], "name": name, "description": None, "version": None,
            "category": None, "status": None, "visibility": None, "repository": None,
            "pin": {"commit": None, "content_hash": None, "source_version": None, "verified": None},
            "provides": [], "requires": [], "optional": [], "relations": [], "measured": _measured(),
            "git": _unknown_git(), "git_hosts": [], "source_ids": [source_id]}
    base.update(extra)
    return base


def _repo_full_name(url) -> str | None:
    """org/name from a git URL; the URL itself is not returned."""
    if not isinstance(url, str):
        return None
    parts = [p for p in urlsplit(url).path.removesuffix(".git").split("/") if p]
    return "/".join(parts[-2:]).lower() if len(parts) >= 2 else None


# ---------------------------------------------------------------- git (host-bound)

def _git_state(dirty):
    return "unknown" if not isinstance(dirty, bool) else ("dirty" if dirty else "clean")


def _collect_git(config: CatalogConfig, sources: list[dict]) -> dict[str, list[dict]]:
    """full_name(lower) -> per-host git records. Hosts come from file content only."""
    index: dict[str, list[dict]] = {}

    def add(full_name, entry):
        if full_name:
            index.setdefault(full_name.lower(), []).append(entry)

    registry = _Source("repo_registry", "git-hosts", "GITHUBBOT/config/repo_registry.json",
                       config.githubbot_config / "repo_registry.json" if config.githubbot_config else None)
    data = registry.load()
    if data is not None:
        registry.record["host"] = _text(data.get("generated_on_host"), 80)
        for full_name, repo in (data.get("repos") or {}).items():
            if not isinstance(repo, dict):
                continue
            for host, info in (repo.get("hosts") or {}).items():
                clones = info.get("clones") if isinstance(info, dict) else None
                if not clones or not isinstance(clones[0], dict):
                    continue
                clone = clones[0]
                add(full_name, {"state": _git_state(clone.get("dirty")), "branch": _text(clone.get("branch"), 200),
                                "last_commit": _text(clone.get("last_commit")), "host": _text(host, 80),
                                "observed_at": _text(clone.get("added_at")) or registry.record["generated_at"],
                                "source": "repo_registry"})
    sources.append(registry.record)

    if config.sync_root and config.sync_root.is_dir():
        for slot in sorted(p for p in config.sync_root.iterdir() if p.is_dir() and not p.is_symlink()):
            manifest = slot / "repos.json"
            if not manifest.is_file():
                continue
            src = _Source("repos_manifest:" + slot.name, "git-hosts", ".SYNC/" + slot.name + "/repos.json", manifest)
            body = src.load()
            if body is None or not isinstance(body.get("repos"), list):
                if body is not None:
                    src.record.update(availability="error", error="repos_missing")
                sources.append(src.record)
                continue
            host = _text(body.get("host"), 80)
            src.record["host"] = host
            for repo in body["repos"]:
                if isinstance(repo, dict):
                    add(_repo_full_name(repo.get("origin")), {
                        "state": _git_state(repo.get("dirty")), "branch": _text(repo.get("branch"), 200),
                        "last_commit": _text(repo.get("last_commit")), "host": host,
                        "observed_at": src.record["generated_at"], "source": "repos_manifest"})
            sources.append(src.record)
    elif config.sync_root is None:
        sources.append(_Source("repos_manifest", "git-hosts", ".SYNC/<slot>/repos.json", None).record)
    return index


def _apply_git(item, entries, local_host):
    best: dict[str, dict] = {}
    for entry in entries:
        key = (entry["host"] or "").lower()
        if key not in best or (entry["observed_at"] or "") > (best[key]["observed_at"] or ""):
            best[key] = entry
    item["git_hosts"] = sorted(best.values(), key=lambda e: (e["host"] or "", e["source"] or ""))
    local = best.get((local_host or "").lower())
    if local:
        item["git"] = dict(local)


# ---------------------------------------------------------------- source projections

def _modules(config, sources, repo_git, local_host):
    src = _Source("modules_catalog", "module", ".MODULES/modules.catalog.json",
                  config.ai_root / ".MODULES" / "modules.catalog.json" if config.ai_root else None)
    data = src.load()
    sources.append(src.record)
    items = []
    if data is None:
        return items
    if not isinstance(data.get("modules"), list):
        src.record.update(availability="error", error="modules_missing")
        return items
    for module in data["modules"]:
        if not isinstance(module, dict) or not _text(module.get("id"), 200):
            continue
        sot = module.get("source_of_truth") if isinstance(module.get("source_of_truth"), dict) else {}
        display = _text(module.get("display_name"), 200)
        item = _item(module["id"], "module", display or module["id"], src.record["id"],
                     description=_text(module.get("description"), 2000), version=_text(module.get("version"), 100),
                     category=_text(module.get("category"), 100), status=_text(module.get("status"), 80),
                     visibility=_text(module.get("visibility"), 80),
                     repository=_text(sot.get("repository"), 300),
                     provides=[x for x in module.get("provides", []) if isinstance(x, str)],
                     requires=[x for x in module.get("requires", []) if isinstance(x, str)],
                     optional=[x for x in module.get("optional", []) if isinstance(x, str)])
        aliases = {display, *(a for a in module.get("repo_aliases", []) if isinstance(a, str))} - {None, module["id"]}
        item["aliases"] = sorted(aliases)
        item["pin"]["commit"] = _text(module.get("commit_sha"), 80)
        item["relations"] = (
            [{"kind": "requires", "target": t, "target_type": "capability", "requirement": "required", "basis": "declared"}
             for t in item["requires"]] +
            [{"kind": "requires", "target": t, "target_type": "capability", "requirement": "optional", "basis": "declared"}
             for t in item["optional"]])
        _apply_git(item, repo_git.get(_repo_full_name(item["repository"]) or "", []), local_host)
        items.append(item)
    return items


def _bundles(config, sources):
    root = config.ai_root / ".BUNDLES" if config.ai_root else None
    src = _Source("bundles_catalog", "bundle", ".BUNDLES/bundles.catalog.v1.json",
                  root / "bundles.catalog.v1.json" if root else None)
    data = src.load()
    sources.append(src.record)
    items, problems = [], []
    if data is None:
        return items, problems
    if not isinstance(data.get("bundles"), list):
        src.record.update(availability="error", error="bundles_missing")
        return items, problems
    for entry in data["bundles"]:
        if not isinstance(entry, dict) or not _text(entry.get("id"), 200):
            continue
        item = _item(entry["id"], "bundle", entry["id"], src.record["id"],
                     category=_text(entry.get("pillar"), 100), status=_text(entry.get("status"), 80),
                     visibility=_text(entry.get("visibility"), 80))
        item["pin"]["content_hash"] = _text(entry.get("content_hash"), 100)
        manifest = root / "bundles" / entry["id"] / "bundle.v1.json"
        try:
            body, version, _ = _read(manifest)
            item["pin"]["source_version"] = version
            item["version"] = _text(body.get("version"), 100)
            item["name"] = _text(body.get("display_name"), 200) or item["name"]
            item["description"] = _text(" ".join(body["purpose"]) if isinstance(body.get("purpose"), list) else body.get("purpose"), 2000)
            for comp in body.get("components", []):
                if isinstance(comp, str):
                    comp = {"ref": comp}
                if not isinstance(comp, dict):
                    continue
                ref = comp.get("ref")
                ref = ref.get("ref") if isinstance(ref, dict) else ref
                if not _text(ref, 300):
                    continue
                requirement = comp.get("requirement")
                item["relations"].append({
                    "kind": "contains", "target": ref, "target_type": _text(comp.get("type"), 40) or "unknown",
                    "requirement": requirement if requirement in ("required", "recommended", "optional") else None,
                    "basis": "declared"})
        except (OSError, ValueError, UnicodeError, AttributeError, TypeError) as exc:
            problems.append({"source": "bundles_catalog", "reason": "manifest_" + type(exc).__name__, "item": entry["id"]})
        items.append(item)
    return items, problems


def _skills(config, sources):
    src = _Source("skills_registry", "skill", "skills/registry/components.json", config.skills_registry)
    data = src.load()
    sources.append(src.record)
    items = []
    if data is None:
        return items
    if not isinstance(data.get("components"), list):
        src.record.update(availability="error", error="components_missing")
        return items
    for comp in data["components"]:
        if not isinstance(comp, dict) or not _text(comp.get("id"), 300):
            continue
        item = _item(comp["id"], "skill", _text(comp.get("name"), 200) or comp["id"], src.record["id"],
                     description=_text(comp.get("description"), 2000), version=_text(comp.get("version"), 100),
                     category=_text(comp.get("category"), 100), status=_text(comp.get("status"), 80))
        item["languages"] = [x for x in comp.get("languages", []) if isinstance(x, str)]
        item["path_label"] = _text(comp.get("path"), 300) if isinstance(comp.get("path"), str) and ":" not in comp["path"] \
            and not comp["path"].startswith(("/", "\\")) else None
        items.append(item)
    return items


def _satellites(config, sources, repo_git, local_host):
    src = _Source("satellite_catalog", "satellite", "GITHUBBOT/config/master_satellite_catalog.json",
                  config.githubbot_config / "master_satellite_catalog.json" if config.githubbot_config else None)
    data = src.load()
    sources.append(src.record)
    items = []
    if data is None:
        return items
    if not isinstance(data.get("modules"), list):
        src.record.update(availability="error", error="modules_missing")
        return items
    for module in data["modules"]:
        if not isinstance(module, dict) or not _text(module.get("name"), 200) or not _text(module.get("org"), 100):
            continue
        full_name = module["org"] + "/" + module["name"]
        item = _item(full_name, "satellite", module["name"], src.record["id"],
                     description=_text(module.get("description"), 2000), category=_text(module.get("category"), 100),
                     visibility=_text(module.get("visibility"), 80))
        item["org"] = module["org"]
        item["provenance"] = _text(module.get("provenance"), 80)
        item["upstream"] = _text(module.get("upstream"), 200)
        # dirty/branch/last_commit of the catalog are generator defaults, not measurements: not used.
        _apply_git(item, repo_git.get(full_name.lower(), []), local_host)
        items.append(item)
    return items


# ---------------------------------------------------------------- entry point

def observe(*, kind: str | None = None, host: str | None = None, config: CatalogConfig | None = None,
            now: datetime | None = None) -> dict:
    if kind is not None and kind not in KINDS:
        raise ValueError("unsupported_kind")
    config = config or config_from_environment()
    local_host = _text(host, 80) or platform.node() or None
    sources: list[dict] = []
    errors: list[dict] = []
    repo_git = _collect_git(config, sources)
    items: list[dict] = []
    if kind in (None, "module"):
        items += _modules(config, sources, repo_git, local_host)
    if kind in (None, "bundle"):
        bundles, problems = _bundles(config, sources)
        items += bundles
        errors += problems
    if kind in (None, "skill"):
        items += _skills(config, sources)
    if kind in (None, "satellite"):
        items += _satellites(config, sources, repo_git, local_host)
    for source in sources:
        if source["availability"] == "error":
            errors.append({"source": source["id"], "reason": source["error"]})
    truncated = len(items) > MAX_ITEMS
    items = items[:MAX_ITEMS]
    counts = {name: sum(1 for i in items if i["type"] == name) for name in KINDS if kind in (None, name)}
    return {"schema": SCHEMA, "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
            "host": {"id": local_host, "source": "measured" if not host else "declared"},
            "sources": sources, "items": items, "counts": counts, "count": len(items),
            "errors": errors, "truncated": truncated}
