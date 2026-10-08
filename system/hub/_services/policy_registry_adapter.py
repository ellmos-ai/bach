"""Read-only canonical governance provider; no bundled-policy fallback."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
import importlib.util
from importlib import metadata
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

PIN = "08add2bb598e9d301d225221ebef5721a7a0e833"
VERSION = "0.2.3"
REPOSITORY = "https://github.com/ellmos-ai/policy-registry"


class PolicyProviderUnavailable(RuntimeError):
    pass


class PolicySnapshotChanged(RuntimeError):
    pass


def _provider():
    if os.environ.get("BACH_POLICY_REGISTRY_ENABLED") != "1":
        raise PolicyProviderUnavailable("policy_provider_not_configured")
    try:
        dist = metadata.distribution("policy-registry")
        direct = json.loads(dist.read_text("direct_url.json") or "{}")
        url = urlsplit(direct.get("url", ""))
        vcs = direct.get("vcs_info", {})
        if (url.scheme != "https" or url.netloc != "github.com" or url.query or url.fragment
                or url.path.removesuffix(".git") != "/ellmos-ai/policy-registry"
                or vcs.get("vcs") != "git" or vcs.get("commit_id") != PIN or dist.version != VERSION):
            raise PolicyProviderUnavailable("policy_provider_provenance_mismatch")
        spec = importlib.util.find_spec("policy_registry")
        expected = Path(dist.locate_file("policy_registry/__init__.py")).resolve()
        if not spec or not spec.origin or Path(spec.origin).resolve() != expected or not expected.is_file():
            raise PolicyProviderUnavailable("policy_provider_import_mismatch")
        from hub.canonical_seam import CanonicalSeam, require_canonical
        cls = require_canonical(CanonicalSeam("policy_registry", "PolicyRegistry", "policy-registry",
            "github.com/ellmos-ai/policy-registry", ("path",), ("load", "search", "resolve", "verify"),
            "BACH_POLICY_REGISTRY_ENABLED", "1", "0", PolicyProviderUnavailable))
        return cls()
    except PolicyProviderUnavailable:
        raise
    except Exception as exc:
        raise PolicyProviderUnavailable("policy_provider_unavailable") from exc


def pointer(entry, checks):
    """Project allowlisted metadata; local locations and policy text stay private."""
    fields = ("id", "kind", "title", "scope", "version", "privacy", "status", "adoption",
              "priority", "precedence", "valid_from", "valid_until", "supersedes", "superseded_by")
    item = {key: entry[key] for key in fields if key in entry}
    check = checks.get(entry["id"], {"state": "unchecked"})
    uri = str(entry.get("source", {}).get("uri", ""))
    # No arbitrary source fields, full texts, credentials, or absolute local paths.
    item["source"] = {"type": "remote-pointer" if "://" in uri else "local-pointer",
                      "label": entry["id"]}
    declared_hash = entry.get("hash") or {}
    item["source_sha256"] = declared_hash.get("value") or None
    item["source_state"] = check["state"]
    item["source_verified"] = check["state"] == "ok" and bool(item["source_sha256"])
    item["enforcement_verified"] = False
    return item


def observe(*, scope=None, consumer=None, query="", kind=None, effective=False):
    registry = _provider()
    path = Path(registry.path)
    try:
        if not path.is_file():
            raise PolicyProviderUnavailable("policy_registry_missing")
        if path.stat().st_size > 16 * 1024 * 1024:
            raise PolicyProviderUnavailable("policy_registry_too_large")
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        entries = registry.search(query=query, scope=scope, consumer=consumer, kind=kind)
        verification = registry.verify()
        checks = {item["id"]: item for item in verification["checks"]}
        resolved = registry.resolve(scope=scope, consumer=consumer, query=query) if effective else None
        if before != hashlib.sha256(path.read_bytes()).hexdigest():
            raise PolicySnapshotChanged("policy_registry_changed_during_read")
        result = {"schema": "bach.policy-registry.v1", "availability": "available",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "source": "policy-registry", "provider": {"id": "policy-registry", "version": VERSION,
                "source_commit": PIN, "repository": REPOSITORY, "verified": True},
            "registry_version": before, "read_only": True, "enforcement_verified": False,
            "entries": [pointer(entry, checks) for entry in entries], "count": len(entries),
            "source_verification_complete": bool(entries) and all(
                checks.get(e["id"], {}).get("state") == "ok" and bool((e.get("hash") or {}).get("value"))
                for e in entries),
            "decision_writer": {"id": "decision-clicker", "available": False,
                                "reason": "separate_explicit_adoption_required"}}
        if resolved is not None:
            selected = resolved.get("selected")
            result["effective"] = {"status": resolved["status"], "reason": resolved["reason"],
                "selected": pointer(selected, checks) if selected else None,
                "candidate_ids": [entry["id"] for entry in resolved.get("candidates", [])],
                "interaction_mode": resolved.get("interaction_mode"),
                "interaction_source": resolved.get("interaction_source"),
                "governance_binding": resolved.get("governance_binding"),
                "external_effect_gates": resolved.get("external_effect_gates")}
        return result
    except (PolicyProviderUnavailable, PolicySnapshotChanged):
        raise
    except Exception as exc:
        raise PolicyProviderUnavailable("policy_registry_read_failed") from exc


def provider_status():
    try:
        registry = _provider()
        if not Path(registry.path).is_file():
            raise PolicyProviderUnavailable("policy_registry_missing")
        return {"id": "policy-registry", "version": VERSION, "source_commit": PIN,
                "repository": REPOSITORY, "verified": True, "runtime_verified": False,
                "reason": "provider_identity_verified_registry_not_probed"}
    except PolicyProviderUnavailable as exc:
        return {"id": "policy-registry", "verified": False, "runtime_verified": False, "reason": str(exc)}
