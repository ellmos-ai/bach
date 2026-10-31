# SPDX-License-Identifier: MIT
"""Bounded consumer parser for the installed shared GUI page-read contract.

The caller supplies bytes captured during successful dist verification. Parsing
alone never establishes the kit pin or runtime availability.
"""
from __future__ import annotations

import hashlib
import json
import re

SCHEMA = "ellmos.gui.page-reads.v1"
MEMBER = "page-reads.v1.json"
MAX_BYTES = 2 * 1024 * 1024
METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
PAGE = re.compile(r"/(?:[A-Za-z0-9_~-]+(?:/[A-Za-z0-9_~-]+)*)?")
API = re.compile(r"/api/(?:[A-Za-z0-9_.~-]+|\{[A-Za-z_][A-Za-z0-9_]*\})(?:/(?:[A-Za-z0-9_.~-]+|\{[A-Za-z_][A-Za-z0-9_]*\}))*")


def normalize(path: str) -> str:
    return re.sub(r"\{[^{}]+\}", "{}", path)


def unavailable(reason: str = "verified_page_reads_missing") -> dict:
    return {"state": "unavailable", "schema": SCHEMA, "reason_code": reason,
            "sha256": None, "pages": {}, "declared": []}


def _unique(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key")
        out[key] = value
    return out


def _constant(_):
    raise ValueError("nonfinite constant")


def _entries(value, *, layout=False):
    if not isinstance(value, list) or len(value) > 500:
        raise ValueError("entries")
    for entry in value:
        if not isinstance(entry, dict):
            raise TypeError("entry")
        method, path = entry.get("method"), entry.get("path")
        if (not isinstance(method, str) or method not in METHODS
                or not isinstance(path, str) or len(path) > 512 or not API.fullmatch(path)
                or ".." in path or type(entry.get("required")) is not bool):
            raise ValueError("entry contract")
        if entry["required"] and (layout or method != "GET"):
            raise ValueError("required non-read")
        dynamic = entry.get("dynamic", False)
        if type(dynamic) is not bool or dynamic != ("found_in" in entry):
            raise ValueError("dynamic")
        if dynamic and (not isinstance(entry["found_in"], str)
                        or len(entry["found_in"]) > 512
                        or not re.fullmatch(r"[^#\s]+#[^#\s]+", entry["found_in"])):
            raise ValueError("found_in")
        if "query" in entry and (not isinstance(entry["query"], str) or len(entry["query"]) > 2048):
            raise ValueError("query")
    return value


def parse(raw: bytes | None) -> dict:
    """Parse verified bytes; the consumer must separately require kit.verified."""
    if raw is None:
        return unavailable()
    invalid = unavailable("page_reads_invalid")
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        return invalid
    digest = hashlib.sha256(raw).hexdigest()
    try:
        doc = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_constant)
        if (not isinstance(doc, dict) or doc.get("schema") != SCHEMA
                or not isinstance(doc.get("pages"), dict) or not 0 < len(doc["pages"]) <= 200):
            raise ValueError("schema")
        layout = _entries(doc.get("layout", []), layout=True)
        pages, declared = {}, {}
        for page, entries in doc["pages"].items():
            if not isinstance(page, str) or len(page) > 200 or not PAGE.fullmatch(page):
                raise ValueError("page")
            required, optional = {}, {}
            for entry in [*_entries(entries), *layout]:
                key = entry["method"] + " " + normalize(entry["path"])
                declared.setdefault(key, entry["method"] + " " + entry["path"])
                if entry["method"] == "GET":
                    target = required if entry["required"] else optional
                    target.setdefault(key, "GET " + entry["path"])
            pages[page] = {"required": list(required.values()),
                           "optional": [value for key, value in optional.items() if key not in required]}
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return {**invalid, "sha256": digest}
    return {"state": "available", "schema": SCHEMA, "reason_code": "verified_page_reads",
            "sha256": digest, "pages": pages, "declared": list(declared.values())}


def page_status(info: dict, registered: set[str]) -> list[dict]:
    """Only required GET routes determine configuration; writes stay separate."""
    served = {method + " " + normalize(path) for item in registered
              for method, _, path in [item.partition(" ")]}
    pages = []
    for path, reads in info.get("pages", {}).items():
        required = reads["required"]
        missing = [item for item in required if "GET " + normalize(item[4:]) not in served]
        if info.get("state") != "available":
            missing = [info.get("reason_code", "verified_page_reads_missing")]
        pages.append({"id": path.strip("/").replace("/", ".") or "home", "path": path,
                      "status": "unavailable" if missing else "configured",
                      "requires": required, "missing": missing,
                      "optional_unserved": [item for item in reads["optional"]
                                            if "GET " + normalize(item[4:]) not in served],
                      "todo": ["Runtime und Bedienung am aktiven Provider prüfen"]})
    return pages
