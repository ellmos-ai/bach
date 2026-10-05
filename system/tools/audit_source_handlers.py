#!/usr/bin/env python3
"""Inspect BACH's handler registry without importing or executing BACH.

The BACH registry discovers ``system/hub/*.py`` classes derived from
``BaseHandler`` and adds the mappings from ``system/core/aliases.py``.  This
tool mirrors that identity layer with Python's AST so a parity baseline can be
updated without booting the personal runtime or touching its data.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
from typing import Any


def _base_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _literal_string_return(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    for child in ast.walk(node):
        if isinstance(child, ast.Return):
            try:
                value = ast.literal_eval(child.value)
            except (ValueError, TypeError):
                continue
            if isinstance(value, str):
                return value
    return None


def _profile_name(node: ast.ClassDef) -> str:
    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == "profile_name":
            value = _literal_string_return(child)
            if value:
                return value

    for child in ast.walk(node):
        if isinstance(child, (ast.Assign, ast.AnnAssign)):
            targets = child.targets if isinstance(child, ast.Assign) else [child.target]
            value_node = child.value
            for target in targets:
                is_profile = (
                    isinstance(target, ast.Name) and target.id == "_profile_name"
                ) or (
                    isinstance(target, ast.Attribute) and target.attr == "_profile_name"
                )
                if is_profile:
                    try:
                        value = ast.literal_eval(value_node)
                    except (ValueError, TypeError):
                        continue
                    if isinstance(value, str):
                        return value

    name = node.name
    return (name[:-7] if name.endswith("Handler") else name).lower()


def _operation_names(node: ast.ClassDef) -> list[str]:
    names: set[str] = set()
    for child in node.body:
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if child.name == "get_operations":
            for returned in (n for n in ast.walk(child) if isinstance(n, ast.Return)):
                if isinstance(returned.value, ast.Dict):
                    for key in returned.value.keys:
                        try:
                            value = ast.literal_eval(key)
                        except (ValueError, TypeError):
                            continue
                        if isinstance(value, str):
                            names.add(value)
        if child.name != "handle":
            continue
        for comparison in (n for n in ast.walk(child) if isinstance(n, ast.Compare)):
            left_is_operation = isinstance(comparison.left, ast.Name) and comparison.left.id in {
                "operation",
                "action",
                "sub_cmd",
            }
            if not left_is_operation:
                continue
            for comparator in comparison.comparators:
                candidates = comparator.elts if isinstance(comparator, (ast.List, ast.Tuple, ast.Set)) else [comparator]
                for candidate in candidates:
                    try:
                        value = ast.literal_eval(candidate)
                    except (ValueError, TypeError):
                        continue
                    if isinstance(value, str):
                        names.add(value)
    return sorted(names)


def _read_aliases(path: Path) -> dict[str, str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        target_name: str | None = None
        value_node: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target_name = node.targets[0].id
            value_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_name = node.target.id
            value_node = node.value
        if target_name != "COMMAND_ALIASES" or value_node is None:
            continue
        value = ast.literal_eval(value_node)
        if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
            raise ValueError(f"COMMAND_ALIASES in {path} is not a string mapping")
        return dict(sorted(value.items()))
    raise ValueError(f"COMMAND_ALIASES not found in {path}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit(bach_root: Path, module_catalog: Path | None = None) -> dict[str, Any]:
    hub = bach_root / "system" / "hub"
    aliases_path = bach_root / "system" / "core" / "aliases.py"
    if not hub.is_dir():
        raise FileNotFoundError(f"BACH hub not found: {hub}")
    if not aliases_path.is_file():
        raise FileNotFoundError(f"BACH alias table not found: {aliases_path}")

    parsed: list[tuple[Path, ast.ClassDef, list[str]]] = []
    known_bases: dict[str, list[str]] = {}
    class_nodes: dict[str, ast.ClassDef] = {}
    parse_errors: list[dict[str, str]] = []
    for path in sorted(hub.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            parse_errors.append({"file": path.name, "error": str(exc)})
            continue
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            bases = [name for base in node.bases if (name := _base_name(base))]
            parsed.append((path, node, bases))
            known_bases[node.name] = bases
            class_nodes[node.name] = node

    def derives_from_base(name: str, trail: frozenset[str] = frozenset()) -> bool:
        if name == "BaseHandler":
            return True
        if name in trail:
            return False
        return any(derives_from_base(base, trail | {name}) for base in known_bases.get(name, []))

    def concrete_members(name: str, trail: frozenset[str] = frozenset()) -> set[str]:
        if name == "BaseHandler" or name in trail:
            return set()
        node = class_nodes.get(name)
        if node is None:
            return set()
        members: set[str] = set()
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                members.add(child.name)
            elif isinstance(child, ast.Assign):
                members.update(target.id for target in child.targets if isinstance(target, ast.Name))
            elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                members.add(child.target.id)
        for base in known_bases.get(name, []):
            members.update(concrete_members(base, trail | {name}))
        return members

    handlers: list[dict[str, Any]] = []
    abstract_handler_classes: list[str] = []
    required_members = {"profile_name", "target_file", "get_operations", "handle"}
    for path, node, bases in parsed:
        if node.name == "BaseHandler" or not any(derives_from_base(base) for base in bases):
            continue
        if not required_members.issubset(concrete_members(node.name)):
            abstract_handler_classes.append(f"{path.name}:{node.name}")
            continue
        handlers.append(
            {
                "profile": _profile_name(node),
                "class": node.name,
                "source": path.name,
                "operations": _operation_names(node),
            }
        )

    handlers.sort(key=lambda item: (item["profile"], item["source"], item["class"]))
    profiles = [item["profile"] for item in handlers]
    duplicate_profiles = sorted({name for name in profiles if profiles.count(name) > 1})
    aliases = _read_aliases(aliases_path)
    canonical_profiles = sorted(set(profiles))
    dangling_aliases = {alias: target for alias, target in aliases.items() if target not in canonical_profiles}
    effective_aliases = {
        alias: target
        for alias, target in aliases.items()
        if target in canonical_profiles and alias not in canonical_profiles
    }
    registered_names = sorted(set(canonical_profiles) | set(effective_aliases))

    result: dict[str, Any] = {
        "schema": "ellmos.bach-handler-audit.v1",
        "method": "static-ast; non-recursive system/hub/*.py; BaseHandler descendants plus COMMAND_ALIASES",
        "counts": {
            "handler_classes": len(handlers),
            "canonical_profiles": len(canonical_profiles),
            "aliases_declared": len(aliases),
            "aliases_effective": len(effective_aliases),
            "registered_names": len(registered_names),
        },
        "canonical_profiles": canonical_profiles,
        "aliases": aliases,
        "effective_aliases": effective_aliases,
        "registered_names": registered_names,
        "handlers": handlers,
        "diagnostics": {
            "duplicate_profiles": duplicate_profiles,
            "dangling_aliases": dangling_aliases,
            "abstract_handler_classes": sorted(abstract_handler_classes),
            "parse_errors": parse_errors,
        },
    }

    if module_catalog is not None:
        catalog = json.loads(module_catalog.read_text(encoding="utf-8"))
        modules = catalog.get("modules", [])
        result["module_catalog"] = {
            "schema": catalog.get("schema"),
            "module_count": catalog.get("module_count", len(modules)),
            "parsed_module_count": len(modules),
            "sha256": _sha256(module_catalog),
        }
    return result


def compare_baseline(result: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    expected = baseline.get("source_audit", {})
    problems: list[str] = []
    for key in ("handler_classes", "canonical_profiles", "aliases_declared", "aliases_effective", "registered_names"):
        if key in expected.get("counts", {}) and result["counts"].get(key) != expected["counts"][key]:
            problems.append(f"count {key}: expected {expected['counts'][key]}, got {result['counts'].get(key)}")

    def names_hash(names: list[str]) -> str:
        return hashlib.sha256(("\n".join(names) + "\n").encode("utf-8")).hexdigest()

    checks = {
        "canonical_profiles_sha256": names_hash(result["canonical_profiles"]),
        "registered_names_sha256": names_hash(result["registered_names"]),
    }
    for key, actual in checks.items():
        if key in expected and actual != expected[key]:
            problems.append(f"{key}: expected {expected[key]}, got {actual}")

    if "registered_name_set" in expected:
        old_names = set(expected["registered_name_set"])
        new_names = set(result["registered_names"])
        if old_names != new_names:
            problems.append(
                f"registered names changed: added={sorted(new_names - old_names)}, "
                f"removed={sorted(old_names - new_names)}"
            )

    expected_dangling = expected.get("known_dangling_aliases", {})
    if result["diagnostics"]["dangling_aliases"] != expected_dangling:
        problems.append(
            "dangling aliases changed: expected "
            f"{expected_dangling}, got {result['diagnostics']['dangling_aliases']}"
        )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bach-root", type=Path, required=True, help="Path to the BACH repository")
    parser.add_argument("--module-catalog", type=Path, help="Optional modules.catalog.json to fingerprint")
    parser.add_argument("--baseline", type=Path, help="Optional parity baseline to compare")
    parser.add_argument("--expect-registered", type=int, help="Fail if the registered-name count differs")
    parser.add_argument("--output", type=Path, help="Write JSON to this file instead of stdout")
    parser.add_argument("--summary", action="store_true", help="Print only counts, diagnostics and drift")
    args = parser.parse_args()

    result = audit(args.bach_root.resolve(), args.module_catalog.resolve() if args.module_catalog else None)
    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline else None
    baseline_drift = compare_baseline(result, baseline) if baseline else []
    if baseline is not None:
        result["baseline_drift"] = baseline_drift
    printable = result
    if args.summary:
        printable = {
            "schema": result["schema"],
            "counts": result["counts"],
            "diagnostics": result["diagnostics"],
            "module_catalog": result.get("module_catalog"),
            "baseline_drift": result.get("baseline_drift"),
        }
    payload = json.dumps(printable, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")

    diagnostics = result["diagnostics"]
    if diagnostics["duplicate_profiles"] or diagnostics["parse_errors"]:
        return 2
    if baseline_drift:
        return 3
    if diagnostics["dangling_aliases"] and baseline is None:
        return 2
    if args.expect_registered is not None and result["counts"]["registered_names"] != args.expect_registered:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
