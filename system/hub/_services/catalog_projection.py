"""Read-only catalog projection ``bach.catalog.v1`` (#2016).

Projects existing catalog files into one item list at request time. It stores nothing,
creates no inventory database and never returns absolute paths: sources are reported with a
symbolic ``path_label`` and every output string is path-redacted (``<pfad>``). Missing or broken
sources are ``availability: missing|error`` with empty items, never mock data, and one broken
source never stops the others (no HTTP 500). Counts are always derived from the returned items.
Architecture (``relations``, ``basis: declared``) and measurement (``measured``, ``git``) stay
separate; git values are ``unknown`` unless a host-bound record says otherwise. A host is never
derived from a file name (OneDrive conflict copies like ``...-ASUS-GEI-2.json`` are not read).

Item types: module, bundle, stack, skill, satellite. Stack ids are namespaced by their source
family because ``homebase-stack`` exists in both: ``systems/<id>`` (``.SYSTEMS/stacks/*.json``,
deployment projections) and ``stacks/<id>`` (``.STACKS/<dir>/stack.v2.json``, module stacks);
the bare id is kept as an alias. ``aliases`` are NOT unique keys (``homebase-stack`` is an alias of
two different stacks); the only unique key of an item is ``type`` + ``id``.

``host`` parameter: selects WHICH host's git record is shown as ``git`` for each item. It does
NOT filter items; ``git_hosts`` always lists every host-bound record.

Time values: tz-aware values are normalised to UTC. A value without time zone is NOT presented
as UTC: the field is ``null``, the original is kept in ``<field>_raw`` and ``<field>_basis`` is
``no_timezone`` (``unparsable`` for garbage, ``absent`` when not provided). ``observed_at`` of a
git record is only ever the observation time of the manifest that carries it (``repos.json``
``generated_at``); a registry clone's ``added_at`` is not an observation time.

Path safety: ids taken from catalogs and used in paths must be one safe segment
(``[A-Za-z0-9._-]``, not ``.``/``..``); every component below the configured root must be neither
a symlink nor a reparse point (Windows junctions/symlinks; cloud-file placeholders are exempt) -
this is only a pre-filter. The authoritative check is "open, then verify": the file is opened
read-only, the FINAL path of the open handle is determined (Windows ``GetFinalPathNameByHandleW``,
macOS ``F_GETPATH``, Linux ``/proc/self/fd``) and must lie inside the real root; content is read
only from that handle. A platform without a way to determine the final path fails closed (the
source becomes ``error``).

Source locations (environment first, defaults only when the path exists):
  BACH_CATALOG_AI_ROOT          directory with .MODULES/modules.catalog.json, .BUNDLES/, .SYSTEMS/, .STACKS/
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
import stat
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA = "bach.catalog.v1"
KINDS = ("module", "bundle", "stack", "skill", "satellite")
MAX_ITEMS = 5000
MAX_BYTES = 32 * 1024 * 1024
SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]{1,200}$")


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


# ---------------------------------------------------------------- helpers

def _text(value, limit=500):
    return value.strip()[:limit] if isinstance(value, str) and value.strip() else None


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _strings(value) -> list[str]:
    return [x for x in value if isinstance(x, str)] if isinstance(value, list) else []


def _list(value) -> list:
    return value if isinstance(value, list) else []


_REPARSE_FLAG = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _is_cloud_placeholder(tag: int) -> bool:
    """OneDrive/cloud-files placeholders are reparse points with tags 0x9000?01A; they are not links."""
    return (tag & 0xFFFF0FFF) == 0x9000001A


def _is_link(path: Path) -> bool:
    """Symlink, or on Windows any reparse point (junction, symlink, mount point) except cloud placeholders.

    Uses lstat attributes, which exist on every supported Python version (>= 3.5), not os.path.isjunction.
    """
    if path.is_symlink():
        return True
    try:
        info = os.lstat(path)
    except OSError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    if attributes & _REPARSE_FLAG:
        return not _is_cloud_placeholder(getattr(info, "st_reparse_tag", 0))
    return False


def _final_path(fd: int) -> str | None:
    """Final (link-resolved) path of an open file descriptor, or None when the platform cannot tell."""
    try:
        if sys.platform == "win32":
            import ctypes
            import msvcrt
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
            kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
            handle = msvcrt.get_osfhandle(fd)
            size = 1024
            buffer = ctypes.create_unicode_buffer(size)
            length = kernel32.GetFinalPathNameByHandleW(handle, buffer, size, 0)
            if length >= size:
                size = length + 1
                buffer = ctypes.create_unicode_buffer(size)
                length = kernel32.GetFinalPathNameByHandleW(handle, buffer, size, 0)
            if length == 0 or length >= size:
                return None
            path = buffer.value
            if path.startswith("\\\\?\\UNC\\"):
                return "\\\\" + path[8:]
            return path[4:] if path.startswith("\\\\?\\") else path
        if sys.platform == "darwin":
            import fcntl
            raw = fcntl.fcntl(fd, fcntl.F_GETPATH, b"\0" * 1024)
            return os.fsdecode(raw.split(b"\0", 1)[0]) or None
        if sys.platform.startswith("linux"):
            return os.readlink(f"/proc/self/fd/{fd}")
    except (OSError, ImportError, AttributeError, ValueError):
        return None
    return None


def _inside(path: str, root: Path) -> bool:
    candidate = os.path.normcase(os.path.realpath(path))
    base = os.path.normcase(os.path.realpath(root))
    return candidate == base or candidate.startswith(base.rstrip(os.sep) + os.sep)


def _open_inside(path: Path, root: Path) -> int:
    """Open read-only, then verify the final path of THIS handle lies inside the root (no check-then-open gap)."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(path, flags)
    try:
        final = _final_path(fd)
        if final is None:
            raise PermissionError("final_path_unavailable")
        if not _inside(final, root):
            raise PermissionError("outside_root")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _safe_child(root: Path | None, *segments: str) -> Path | None:
    """Path below ``root`` or None. One safe segment each, no link in any component, stays inside root."""
    if root is None:
        return None
    try:
        for segment in segments:
            if not isinstance(segment, str) or segment in (".", "..") or not SAFE_SEGMENT.fullmatch(segment):
                return None
        current = root
        for segment in segments:
            current = current / segment
            if _is_link(current):
                return None
        if not current.resolve().is_relative_to(root.resolve()):
            return None
        return current
    except (OSError, ValueError, RuntimeError):
        return None


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def _time(raw) -> tuple[str | None, str, str | None]:
    """(utc_iso | None, basis, raw_when_not_normalised). No time zone => never presented as UTC."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None, "absent", None
    if not isinstance(raw, str):
        return None, "unparsable", None
    candidate = raw.strip()
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return None, "unparsable", candidate[:80]
    if parsed.tzinfo is None:
        return None, "no_timezone", candidate[:80]
    return parsed.astimezone(timezone.utc).isoformat(), "declared", None


def _read(path: Path, root: Path):
    """Return (data, version, mtime_iso). Reads only from a handle verified to be inside ``root``."""
    if _is_link(path):
        raise PermissionError("link")
    fd = _open_inside(path, root)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise FileNotFoundError("missing")
        if info.st_size > MAX_BYTES:
            raise ValueError("too_large")
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("too_large")
    return json.loads(raw.decode("utf-8-sig")), hashlib.sha256(raw).hexdigest(), _iso(info.st_mtime)


class _Source:
    """One source record; a failure becomes availability, never an exception."""

    def __init__(self, source_id, kind, label, path: Path | None, root: Path | None = None):
        self.record = {"id": source_id, "kind": kind, "path_label": label, "host": None, "schema": None,
                       "source_version": None, "generated_at": None, "generated_at_basis": "absent",
                       "generated_at_raw": None, "modified_at": None, "availability": "missing", "error": None}
        self.path = path
        self.root = root

    def fail(self, reason):
        self.record.update(availability="error", error=reason)

    def load(self):
        if self.path is None:
            self.record["error"] = "not_configured"
            return None
        try:
            data, version, mtime = _read(self.path, self.root or self.path.parent)
        except FileNotFoundError:
            self.record["error"] = "file_missing"
            return None
        except (OSError, ValueError, UnicodeError) as exc:
            self.fail(type(exc).__name__)
            return None
        if not isinstance(data, dict):
            self.fail("not_an_object")
            return None
        generated, basis, raw = _time(data.get("generated_at"))
        self.record.update(availability="available", source_version=version, error=None, modified_at=mtime,
                           schema=_text(data.get("schema"), 120), generated_at=generated,
                           generated_at_basis=basis, generated_at_raw=raw)
        if basis == "absent":  # nothing declared: the file's own modification time is the honest fallback
            self.record.update(generated_at=mtime, generated_at_basis="file_mtime")
        return data


def _collect_dir(source_id, label, base: Path | None, members, root: Path | None):
    """A directory of manifests: version is the hash over the member hashes."""
    record = _Source(source_id, "stack", label, None).record
    found, problems = [], []
    if base is None or not base.is_dir() or _is_link(base):
        record["error"] = "directory_missing"
        return record, found, problems
    digest, newest = hashlib.sha256(), 0.0
    for name, member in members(base):
        try:
            data, version, _ = _read(member, root)
            if not isinstance(data, dict):
                raise ValueError("not_an_object")
            digest.update(version.encode())
            newest = max(newest, member.stat().st_mtime)
            found.append((name, data))
        except (OSError, ValueError, UnicodeError) as exc:
            problems.append({"source": source_id, "reason": type(exc).__name__, "item": name})
    record.update(availability="available", error=None, source_version=digest.hexdigest() if found else None)
    if newest:
        record.update(modified_at=_iso(newest), generated_at=_iso(newest), generated_at_basis="file_mtime")
    return record, found, problems


def _measured():
    return {"installed": None, "runtime_active": None, "connection_state": "unverified",
            "observed_at": None, "host": None, "evidence": None}


def _unknown_git():
    return {"state": "unknown", "branch": None, "last_commit": None, "last_commit_raw": None, "observed_at": None,
            "observed_at_basis": "absent", "observed_at_raw": None, "host": None, "source": None}


def _item(item_id, item_type, name, source_id, **extra):
    base = {"id": item_id, "type": item_type, "aliases": [], "name": name, "description": None, "version": None,
            "category": None, "status": None, "visibility": None, "repository": None,
            "pin": {"commit": None, "content_hash": None, "source_version": None, "verified": None},
            "provides": [], "requires": [], "optional": [], "relations": [], "measured": _measured(),
            "git": _unknown_git(), "git_hosts": [], "source_ids": [source_id]}
    base.update(extra)
    return base


def _repo_full_name(url) -> str | None:
    if not isinstance(url, str):
        return None
    parts = [p for p in urlsplit(url).path.removesuffix(".git").split("/") if p]
    return "/".join(parts[-2:]).lower() if len(parts) >= 2 else None


# ---------------------------------------------------------------- path redaction (all output strings)

_TAIL = r"[^\s\"'<>|,;)]*"
_PATH_PATTERNS = [
    re.compile(r"file://[^\s\"'<>|,;)]+"),                              # file:// URLs with a path
    re.compile(r"(?<!\w)[A-Za-z]:[\\/]" + _TAIL),                         # C:\x or C:/x (also after ":")
    re.compile(r"\\\\[^\s\"'<>|,;)]+"),                                  # \\server\share
    re.compile(r"(?<!\w)~[\\/]" + _TAIL),                                # ~/x
    re.compile(r"%[A-Za-z_]+%[\\/]" + _TAIL),                            # %USERPROFILE%\x
    # absolute POSIX path with at least TWO segments ("/a/b"), starting a token (text start, whitespace, quote,
    # opening bracket, "=", ":", "," or ";" before it). Single segments ("/bugsweep", "/tmp") are slash commands or
    # reveal nothing and stay. Not part of a word, glob or URL ("//host/..."); "/api/..." routes stay;
    # works after ":" too ("ref:/home/x/y").
    re.compile(r"(?<![^\s\"'(=\[:,;])/(?!api/)[^\s/\"'<>|,;)]+/[^\s\"'<>|,;)]+"),
]
REDACTED = "<pfad>"


def _redact(node, counter):
    if isinstance(node, str):
        for pattern in _PATH_PATTERNS:
            node, n = pattern.subn(REDACTED, node)
            counter[0] += n
        return node
    if isinstance(node, list):
        return [_redact(x, counter) for x in node]
    if isinstance(node, dict):
        return {k: _redact(v, counter) for k, v in node.items()}
    return node


# ---------------------------------------------------------------- git (host-bound)

def _git_state(dirty):
    return "unknown" if not isinstance(dirty, bool) else ("dirty" if dirty else "clean")


def _git_entry(state, branch, last_commit, host, observed_raw, source):
    commit, _, commit_raw = _time(last_commit)
    observed, observed_basis, observed_kept = _time(observed_raw)
    return {"state": state, "branch": _text(branch, 200), "last_commit": commit, "last_commit_raw": commit_raw,
            "observed_at": observed, "observed_at_basis": observed_basis, "observed_at_raw": observed_kept,
            "host": _text(host, 80), "source": source}


def _collect_git(config: CatalogConfig, sources: list[dict]) -> dict[str, list[dict]]:
    """full_name(lower) -> per-host git records. Hosts come from file content only."""
    index: dict[str, list[dict]] = {}

    registry = _Source("repo_registry", "git-hosts", "GITHUBBOT/config/repo_registry.json",
                       _safe_child(config.githubbot_config, "repo_registry.json"), config.githubbot_config)
    data = registry.load()
    if data is not None:
        try:
            staged = []
            registry.record["host"] = _text(data.get("generated_on_host"), 80)
            repos = data.get("repos")
            if repos is not None and not isinstance(repos, dict):
                raise TypeError("repos")
            for full_name, repo in (repos or {}).items():
                # a wrong type at repo / hosts / host / clones level makes the whole source "error" (not silently skipped)
                if not isinstance(repo, dict):
                    raise TypeError("repo")
                hosts = repo.get("hosts")
                if hosts is not None and not isinstance(hosts, dict):
                    raise TypeError("hosts")
                for host, info in (hosts or {}).items():
                    if not isinstance(info, dict):
                        raise TypeError("host")
                    clones = info.get("clones")
                    if clones is None:
                        continue
                    if not isinstance(clones, list) or any(not isinstance(c, dict) for c in clones):
                        raise TypeError("clones")
                    if not clones:
                        continue
                    clone = clones[0]
                    # added_at is when the clone was registered, not when git was observed: no observed_at here.
                    staged.append((str(full_name).lower(), _git_entry(
                        _git_state(clone.get("dirty")), clone.get("branch"), clone.get("last_commit"), host, None,
                        "repo_registry")))
            for full_name, entry in staged:
                index.setdefault(full_name, []).append(entry)
        except (TypeError, AttributeError, ValueError):
            registry.fail("invalid_structure")
    sources.append(registry.record)

    if config.sync_root is not None and config.sync_root.is_dir() and not _is_link(config.sync_root):
        for slot in sorted(p for p in config.sync_root.iterdir() if p.is_dir()):
            manifest = _safe_child(config.sync_root, slot.name, "repos.json")
            if manifest is None or not manifest.is_file():
                continue
            src = _Source("repos_manifest:" + slot.name, "git-hosts", ".SYNC/" + slot.name + "/repos.json", manifest, config.sync_root)
            body = src.load()
            if body is not None:
                try:
                    if not isinstance(body.get("repos"), list):
                        raise TypeError("repos")
                    host = _text(body.get("host"), 80)
                    src.record["host"] = host
                    staged = []
                    for repo in body["repos"]:
                        if isinstance(repo, dict):
                            staged.append((_repo_full_name(repo.get("origin")), _git_entry(
                                _git_state(repo.get("dirty")), repo.get("branch"), repo.get("last_commit"), host,
                                body.get("generated_at"), "repos_manifest")))
                    for full_name, entry in staged:
                        if full_name:
                            index.setdefault(full_name, []).append(entry)
                except (TypeError, AttributeError, ValueError):
                    src.fail("invalid_structure")
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
                  _safe_child(config.ai_root, ".MODULES", "modules.catalog.json"), config.ai_root)
    data = src.load()
    sources.append(src.record)
    if data is None:
        return []
    if not isinstance(data.get("modules"), list):
        src.fail("modules_missing")
        return []
    items = []
    for module in data["modules"]:
        if not isinstance(module, dict) or not _text(module.get("id"), 200):
            continue
        sot = _dict(module.get("source_of_truth"))
        display = _text(module.get("display_name"), 200)
        item = _item(module["id"], "module", display or module["id"], src.record["id"],
                     description=_text(module.get("description"), 2000), version=_text(module.get("version"), 100),
                     category=_text(module.get("category"), 100), status=_text(module.get("status"), 80),
                     visibility=_text(module.get("visibility"), 80), repository=_text(sot.get("repository"), 300),
                     provides=_strings(module.get("provides")), requires=_strings(module.get("requires")),
                     optional=_strings(module.get("optional")))
        item["aliases"] = sorted({display, *_strings(module.get("repo_aliases"))} - {None, module["id"]})
        item["pin"]["commit"] = _text(module.get("commit_sha"), 80)
        item["relations"] = (
            [{"kind": "requires", "target": t, "target_type": "capability", "requirement": "required", "basis": "declared"}
             for t in item["requires"]] +
            [{"kind": "requires", "target": t, "target_type": "capability", "requirement": "optional", "basis": "declared"}
             for t in item["optional"]])
        _apply_git(item, repo_git.get(_repo_full_name(item["repository"]) or "", []), local_host)
        items.append(item)
    return items


def _requirement(value):
    return value if value in ("required", "recommended", "optional") else None


def _ref(value):
    return _text(value.get("ref") if isinstance(value, dict) else value, 300)


def _bundles(config, sources):
    src = _Source("bundles_catalog", "bundle", ".BUNDLES/bundles.catalog.v1.json",
                  _safe_child(config.ai_root, ".BUNDLES", "bundles.catalog.v1.json"), config.ai_root)
    data = src.load()
    sources.append(src.record)
    items, problems = [], []
    if data is None:
        return items, problems
    if not isinstance(data.get("bundles"), list):
        src.fail("bundles_missing")
        return items, problems
    for entry in data["bundles"]:
        if not isinstance(entry, dict) or not _text(entry.get("id"), 200):
            continue
        item = _item(entry["id"], "bundle", entry["id"], src.record["id"],
                     category=_text(entry.get("pillar"), 100), status=_text(entry.get("status"), 80),
                     visibility=_text(entry.get("visibility"), 80))
        item["pin"]["content_hash"] = _text(entry.get("content_hash"), 100)
        items.append(item)
        manifest = _safe_child(config.ai_root, ".BUNDLES", "bundles", entry["id"], "bundle.v1.json")
        if manifest is None:
            problems.append({"source": "bundles_catalog", "reason": "unsafe_id", "item": entry["id"]})
            continue
        try:
            body, version, _ = _read(manifest, config.ai_root)
            if not isinstance(body, dict):
                raise ValueError("not_an_object")
            item["pin"]["source_version"] = version
            item["version"] = _text(body.get("version"), 100)
            item["name"] = _text(body.get("display_name"), 200) or item["name"]
            purpose = body.get("purpose")
            item["description"] = _text(" ".join(_strings(purpose)) if isinstance(purpose, list) else purpose, 2000)
            for comp in _list(body.get("components")):
                comp = {"ref": comp} if isinstance(comp, str) else comp
                if not isinstance(comp, dict) or not _ref(comp.get("ref")):
                    continue
                item["relations"].append({
                    "kind": "contains", "target": _ref(comp.get("ref")), "target_type": _text(comp.get("type"), 40) or "unknown",
                    "requirement": _requirement(comp.get("requirement")), "basis": "declared"})
        except (OSError, ValueError, UnicodeError) as exc:
            problems.append({"source": "bundles_catalog", "reason": "manifest_" + type(exc).__name__, "item": entry["id"]})
    return items, problems


def _stack_relations(body):
    relations = []
    for key, requirement in (("bundle_refs", "required"), ("optional_bundle_refs", "optional")):
        for ref in _list(body.get(key)):
            if _ref(ref):
                relations.append({"kind": "contains", "target": _ref(ref), "target_type": "bundle",
                                  "requirement": requirement, "basis": "declared"})
    for comp in _list(body.get("components")):
        target = _ref(comp.get("id") if isinstance(comp, dict) else comp)
        if target:
            relations.append({"kind": "contains", "target": target, "target_type": "module", "requirement": "required",
                              "basis": "declared"})
    for comp in _list(body.get("external_components")):
        target = _ref(_dict(comp).get("id"))
        if target:
            relations.append({"kind": "contains", "target": target,
                              "target_type": _text(_dict(comp).get("kind"), 40) or "external",
                              "requirement": None, "basis": "declared"})
    for nested in _list(body.get("nested_stacks")):
        if _ref(nested):
            relations.append({"kind": "contains", "target": _ref(nested), "target_type": "stack", "requirement": None,
                              "basis": "declared"})
    return relations


def _stack_family(config, sources, errors, source_id, label, namespace, category, parts):
    def members(directory):
        if namespace == "systems":
            for path in sorted(directory.glob("*.json")):
                if _safe_child(config.ai_root, *parts, path.name) is not None:
                    yield path.name, path
        else:
            for folder in sorted(p for p in directory.iterdir() if p.is_dir()):
                member = _safe_child(config.ai_root, *parts, folder.name, "stack.v2.json")
                if member is not None and member.is_file():
                    yield folder.name, member

    record, found, problems = _collect_dir(source_id, label, _safe_child(config.ai_root, *parts), members, config.ai_root)
    sources.append(record)
    items = []
    try:
        errors += problems
        for name, body in found:
            fallback = name.removesuffix(".json").split(".v")[0] if namespace == "systems" else name
            stack_id = _text(body.get("id"), 200) or fallback
            item = _item(namespace + "/" + stack_id, "stack", stack_id, source_id,
                         description=_text(body.get("purpose"), 2000), version=_text(body.get("version"), 100),
                         category=category, status=_text(body.get("status"), 80), visibility=_text(body.get("visibility"), 80))
            item["aliases"] = [stack_id]
            item["pin"]["content_hash"] = _text(body.get("content_hash"), 100)
            item["relations"] = _stack_relations(body)
            items.append(item)
    except Exception:  # noqa: BLE001 - one malformed stack family must not stop the others
        record.update(availability="error", error="invalid_structure")
        return []
    return items


def _stacks(config, sources, errors):
    return (_stack_family(config, sources, errors, "stacks_systems", ".SYSTEMS/stacks/*.json", "systems",
                          "deployment-projection", (".SYSTEMS", "stacks")) +
            _stack_family(config, sources, errors, "stacks_modules", ".STACKS/*/stack.v2.json", "stacks",
                          "module-stack", (".STACKS",)))


def _skills(config, sources):
    src = _Source("skills_registry", "skill", "skills/registry/components.json", config.skills_registry)
    data = src.load()
    sources.append(src.record)
    if data is None:
        return []
    if not isinstance(data.get("components"), list):
        src.fail("components_missing")
        return []
    items = []
    for comp in data["components"]:
        if not isinstance(comp, dict) or not _text(comp.get("id"), 300):
            continue
        item = _item(comp["id"], "skill", _text(comp.get("name"), 200) or comp["id"], src.record["id"],
                     description=_text(comp.get("description"), 2000), version=_text(comp.get("version"), 100),
                     category=_text(comp.get("category"), 100), status=_text(comp.get("status"), 80))
        item["languages"] = _strings(comp.get("languages"))
        path = comp.get("path")
        safe = (isinstance(path, str) and ":" not in path and not path.startswith(("/", "\\"))
                and ".." not in path.replace("\\", "/").split("/"))
        item["path_label"] = _text(path, 300) if safe else None
        items.append(item)
    return items


def _satellites(config, sources, repo_git, local_host):
    src = _Source("satellite_catalog", "satellite", "GITHUBBOT/config/master_satellite_catalog.json",
                  _safe_child(config.githubbot_config, "master_satellite_catalog.json"), config.githubbot_config)
    data = src.load()
    sources.append(src.record)
    if data is None:
        return []
    if not isinstance(data.get("modules"), list):
        src.fail("modules_missing")
        return []
    items = []
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

def _guard(sources, source_id, fn, default):
    """Run one projection; an unexpected shape error marks only that source as error."""
    try:
        return fn()
    except Exception:  # noqa: BLE001
        for record in sources:
            if record["id"] == source_id:
                record.update(availability="error", error="invalid_structure")
                return default
        record = _Source(source_id, "unknown", source_id, None).record
        record.update(availability="error", error="invalid_structure")
        sources.append(record)
        return default


def observe(*, kind: str | None = None, host: str | None = None, config: CatalogConfig | None = None,
            now: datetime | None = None) -> dict:
    if kind is not None and kind not in KINDS:
        raise ValueError("unsupported_kind")
    config = config or config_from_environment()
    local_host = _text(host, 80) or platform.node() or None
    sources: list[dict] = []
    errors: list[dict] = []
    repo_git = _guard(sources, "git_hosts", lambda: _collect_git(config, sources), {})
    items: list[dict] = []
    if kind in (None, "module"):
        items += _guard(sources, "modules_catalog", lambda: _modules(config, sources, repo_git, local_host), [])
    if kind in (None, "bundle"):
        bundles, problems = _guard(sources, "bundles_catalog", lambda: _bundles(config, sources), ([], []))
        items += bundles
        errors += problems
    if kind in (None, "stack"):
        items += _guard(sources, "stacks_modules", lambda: _stacks(config, sources, errors), [])
    if kind in (None, "skill"):
        items += _guard(sources, "skills_registry", lambda: _skills(config, sources), [])
    if kind in (None, "satellite"):
        items += _guard(sources, "satellite_catalog", lambda: _satellites(config, sources, repo_git, local_host), [])
    for source in sources:
        if source["availability"] == "error":
            errors.append({"source": source["id"], "reason": source["error"], "item": None})
    for error in errors:
        error.setdefault("item", None)
    truncated = len(items) > MAX_ITEMS
    items = items[:MAX_ITEMS]
    counts = {name: sum(1 for i in items if i["type"] == name) for name in KINDS if kind in (None, name)}
    result = {"schema": SCHEMA, "generated_at": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
              "host": {"id": local_host, "source": "measured" if not host else "declared"},
              "sources": sources, "items": items, "counts": counts, "count": len(items),
              "errors": errors, "truncated": truncated}
    counter = [0]
    result = _redact(result, counter)
    result["redactions"] = counter[0]
    return result
