#!/usr/bin/env python3
"""Check the K9 data contract without booting or importing BACH.

The source side is inspected with AST and hashes only. The carrier side runs on
the repository's anonymized SQLite fixtures in a temporary directory. Passing
this check is contract and carrier evidence, not BACH runtime equivalence.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_head(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def extract_operations(path: Path, profile: str) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        profile_name: str | None = None
        operations: list[str] | None = None
        for member in node.body:
            if not isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if member.name == "profile_name":
                for returned in (item for item in ast.walk(member) if isinstance(item, ast.Return)):
                    try:
                        value = ast.literal_eval(returned.value)
                    except (ValueError, TypeError):
                        continue
                    if isinstance(value, str):
                        profile_name = value
            elif member.name == "get_operations":
                for returned in (item for item in ast.walk(member) if isinstance(item, ast.Return)):
                    try:
                        value = ast.literal_eval(returned.value)
                    except (ValueError, TypeError):
                        continue
                    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
                        operations = sorted(value)
        if profile_name == profile and operations is not None:
            return operations
    raise ValueError(f"Profile {profile!r} with a literal get_operations() not found in {path}")


def validate_contract(contract: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if contract.get("schema") != "ellmos.open-ocean-bach-k9-data-contract.v1":
        problems.append("unexpected contract schema")
    profiles = contract.get("profiles", {})
    for profile, expected_count in (("dbsync", 9), ("snapshot", 4)):
        operations = profiles.get(profile, {}).get("operations", [])
        names = [item.get("name") for item in operations]
        if len(operations) != expected_count or len(set(names)) != expected_count:
            problems.append(f"{profile}: expected {expected_count} unique operations")
        if any(item.get("parity") == "accepted" for item in operations):
            problems.append(f"{profile}: contract baseline must not claim accepted parity")
    snapshot = profiles.get("snapshot", {})
    if snapshot.get("database_transit_fit") != "wrong-carrier":
        problems.append("snapshot must remain outside the database-transit carrier")
    if snapshot.get("carrier_fit") != "correct-carrier-selected":
        problems.append("snapshot must bind the selected session-checkpoint carrier")
    for source_name in ("bach", "carrier", "session_checkpoint_carrier"):
        commit = contract.get("sources", {}).get(source_name, {}).get("commit", "")
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            problems.append(f"{source_name}: expected a pinned 40-character commit")
    return problems


def validate_specs(contract: dict[str, Any], repo_root: Path) -> list[str]:
    problems: list[str] = []
    dbsync_path = repo_root / contract["profiles"]["dbsync"]["adapter_spec"]
    checkpoint_path = repo_root / contract["profiles"]["snapshot"]["capability_spec"]
    try:
        dbsync = json.loads(dbsync_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        problems.append(f"dbsync adapter spec unreadable: {error}")
        dbsync = {}
    try:
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        problems.append(f"session-checkpoint capability spec unreadable: {error}")
        checkpoint = {}

    if dbsync.get("schema") != "ellmos.open-ocean-bach-k9-dbsync-adapter.v1":
        problems.append("unexpected dbsync adapter schema")
    if checkpoint.get("schema") != "ellmos.open-ocean-session-checkpoint-capability.v1":
        problems.append("unexpected session-checkpoint capability schema")
    expected_dbsync = sorted(
        item["name"] for item in contract["profiles"]["dbsync"]["operations"]
    )
    actual_dbsync = sorted(item.get("name") for item in dbsync.get("operations", []))
    if actual_dbsync != expected_dbsync:
        problems.append(
            f"dbsync adapter operations drift: expected {expected_dbsync}, got {actual_dbsync}"
        )
    expected_snapshot = sorted(
        item["name"] for item in contract["profiles"]["snapshot"]["operations"]
    )
    actual_snapshot = sorted(
        item.get("bach_operation") for item in checkpoint.get("operation_mapping", [])
    )
    if actual_snapshot != expected_snapshot:
        problems.append(
            f"session-checkpoint operations drift: expected {expected_snapshot}, "
            f"got {actual_snapshot}"
        )
    if dbsync.get("sources", {}).get("carrier", {}).get("commit") != contract["sources"][
        "carrier"
    ]["commit"]:
        problems.append("dbsync adapter carrier pin differs from the K9 data contract")
    if checkpoint.get("carrier", {}).get("commit") != contract["sources"][
        "session_checkpoint_carrier"
    ]["commit"]:
        problems.append("session-checkpoint carrier pin differs from the K9 data contract")
    expected_bach = contract["sources"]["bach"]
    dbsync_source = dbsync.get("sources", {}).get("bach", {})
    expected_dbsync = expected_bach["handler_files"]["dbsync"]
    if dbsync_source.get("commit") != expected_bach["commit"]:
        problems.append("dbsync adapter BACH commit differs from the K9 data contract")
    if dbsync_source.get("handler") != expected_dbsync["path"]:
        problems.append("dbsync adapter BACH handler differs from the K9 data contract")
    if dbsync_source.get("sha256") != expected_dbsync["sha256"]:
        problems.append("dbsync adapter BACH hash differs from the K9 data contract")
    payload_fields = checkpoint.get("application_adapter", {}).get("payload_fields", {})
    expected_payload_fields = {
        "session_id",
        "open_tasks",
        "recent_memory",
        "active_files",
        "token_usage",
        "created_at",
    }
    if set(payload_fields) != expected_payload_fields:
        problems.append("session-checkpoint payload fields drift from the six-field contract")
    load_mapping = next(
        (item for item in checkpoint.get("operation_mapping", []) if item.get("bach_operation") == "load"),
        {},
    )
    if "No Ocean restore adapter is implemented." not in load_mapping.get("adapter_work", ""):
        problems.append("session-checkpoint load mapping must retain the missing-adapter boundary")
    return problems


def inspect_bach(contract: dict[str, Any], bach_root: Path) -> dict[str, Any]:
    expected = contract["sources"]["bach"]
    result: dict[str, Any] = {"head": git_head(bach_root), "profiles": {}, "problems": []}
    if result["head"] != expected["commit"]:
        result["problems"].append(
            f"BACH commit drift: expected {expected['commit']}, got {result['head']}"
        )
    for profile, relative in expected["handler_files"].items():
        path = bach_root / relative["path"]
        actual_hash = sha256(path)
        actual_operations = extract_operations(path, profile)
        expected_operations = sorted(
            item["name"] for item in contract["profiles"][profile]["operations"]
        )
        result["profiles"][profile] = {
            "sha256": actual_hash,
            "operations": actual_operations,
        }
        if actual_hash != relative["sha256"]:
            result["problems"].append(f"{profile}: source hash drift")
        if actual_operations != expected_operations:
            result["problems"].append(
                f"{profile}: operations drift: expected {expected_operations}, got {actual_operations}"
            )
    return result


def create_database(path: Path, sql_path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(sql_path.read_text(encoding="utf-8"))
        connection.commit()
    finally:
        connection.close()


def query(path: Path, sql: str) -> list[list[Any]]:
    connection = sqlite3.connect(path)
    try:
        return [list(row) for row in connection.execute(sql).fetchall()]
    finally:
        connection.close()


def run_carrier_fixture(
    contract: dict[str, Any],
    repo_root: Path,
    carrier_root: Path,
) -> dict[str, Any]:
    expected_source = contract["sources"]["carrier"]
    result: dict[str, Any] = {
        "head": git_head(carrier_root),
        "module": None,
        "observed": {},
        "problems": [],
    }
    if result["head"] != expected_source["commit"]:
        result["problems"].append(
            f"carrier commit drift: expected {expected_source['commit']}, got {result['head']}"
        )

    sys.path.insert(0, str(carrier_root))
    try:
        module = importlib.import_module("sqlite_transit_sync")
        module_path = Path(module.__file__).resolve()
        if not module_path.is_relative_to(carrier_root.resolve()):
            result["problems"].append(f"carrier import escaped requested root: {module_path}")
            return result
        result["module"] = str(module_path)
        SyncConfig = module.SyncConfig
        TransitSync = module.TransitSync

        fixture = contract["fixtures"]
        source_sql = repo_root / fixture["source_sql"]
        target_sql = repo_root / fixture["target_sql"]
        expected = json.loads((repo_root / fixture["expected"]).read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as temp_name:
            temp = Path(temp_name)
            transit = temp / "transit"
            source_db = temp / "source.sqlite"
            target_db = temp / "target.sqlite"
            create_database(source_db, source_sql)
            create_database(target_db, target_sql)
            source = TransitSync(
                SyncConfig(source_db, transit, temp / "source-state.json", "node-a", "fixture")
            )
            target = TransitSync(
                SyncConfig(target_db, transit, temp / "target-state.json", "node-b", "fixture")
            )
            snapshot = source.push()
            reports = target.pull()
            cleanup = source.cleanup(keep_days=0, keep_per_node=0)
            observed = {
                "source_snapshot_secret_rows": query(
                    snapshot.path, "SELECT COUNT(*) FROM secrets"
                )[0][0],
                "target_secret_rows": query(target_db, "SELECT COUNT(*) FROM secrets")[0][0],
                "target_items": query(target_db, "SELECT id, value FROM items ORDER BY id"),
                "merge_inserted": sum(report.inserted for report in reports),
                "merge_updated": sum(report.updated for report in reports),
                "cleanup_dry_run": cleanup["dry_run"],
                "cleanup_scope": cleanup["scope"],
                "cleanup_eligible": len(cleanup["eligible"]),
            }
            result["observed"] = observed
            for key, expected_value in expected.items():
                if key == "schema":
                    continue
                if observed.get(key) != expected_value:
                    result["problems"].append(
                        f"fixture {key}: expected {expected_value!r}, got {observed.get(key)!r}"
                    )
    finally:
        sys.path.pop(0)
    return result


def run_session_checkpoint_fixture(
    contract: dict[str, Any],
    repo_root: Path,
    carrier_root: Path,
) -> dict[str, Any]:
    expected_source = contract["sources"]["session_checkpoint_carrier"]
    result: dict[str, Any] = {
        "head": git_head(carrier_root),
        "module": None,
        "observed": {},
        "problems": [],
    }
    if result["head"] != expected_source["commit"]:
        result["problems"].append(
            "session-checkpoint carrier commit drift: "
            f"expected {expected_source['commit']}, got {result['head']}"
        )
    manifest_path = carrier_root / "ellmos-module.v2.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        result["problems"].append(f"session-checkpoint manifest unreadable: {error}")
        manifest = {}
    if manifest.get("id") != expected_source["id"]:
        result["problems"].append("session-checkpoint manifest id drift")
    if "session.checkpoint" not in manifest.get("provides", []):
        result["problems"].append("session-checkpoint manifest lacks session.checkpoint")
    if manifest.get("boundaries", {}).get("network") != "none":
        result["problems"].append("session-checkpoint carrier must remain network-free")

    sys.path.insert(0, str(carrier_root))
    try:
        module = importlib.import_module("session_checkpoint")
        module_path = Path(module.__file__).resolve()
        if not module_path.is_relative_to(carrier_root.resolve()):
            result["problems"].append(
                f"session-checkpoint import escaped requested root: {module_path}"
            )
            return result
        result["module"] = str(module_path)
        fixture = contract["fixtures"]
        fixture_document = json.loads(
            (repo_root / fixture["session_checkpoint_input"]).read_text(encoding="utf-8")
        )
        expected = json.loads(
            (repo_root / fixture["session_checkpoint_expected"]).read_text(encoding="utf-8")
        )
        payload = fixture_document["payload"]

        with tempfile.TemporaryDirectory() as temp_name:
            temp = Path(temp_name)
            source = module.CheckpointStore(temp / "source-checkpoints.sqlite")
            created = source.create(
                namespace="bach",
                session_id=payload["session_id"],
                name="checkpoint-fixture",
                kind="manual",
                payload=payload,
                created_at="2026-08-08T07:00:00Z",
                source_ref="bach-session_snapshots:1",
            )
            listed = source.list(namespace="bach", limit=20)
            loaded = source.get(created.id, namespace="bach")
            source.delete(created.id, namespace="bach")
            delete_dry_run_preserved = source.get(created.id, namespace="bach").id == created.id
            bundle = source.export_bundle(namespace="bach")
            source.delete(created.id, namespace="bach", dry_run=False)

            target = module.CheckpointStore(temp / "target-checkpoints.sqlite")
            import_plan = target.import_bundle(bundle)
            target_after_plan = len(target.list(namespace="bach"))
            import_apply = target.import_bundle(bundle, dry_run=False)
            roundtrip = target.get(created.id, namespace="bach")

            bounded = module.CheckpointStore(
                temp / "bounded-checkpoints.sqlite",
                max_import_checkpoints=1,
            )
            oversized_bundle = {
                **bundle,
                "checkpoints": bundle["checkpoints"] + bundle["checkpoints"],
            }
            try:
                bounded.import_bundle(oversized_bundle, dry_run=False)
            except module.CheckpointValidationError:
                import_record_limit_enforced = not bounded.list(namespace="bach")
            else:
                import_record_limit_enforced = False

            observed = {
                "created_id": created.id,
                "list_ids": [item.id for item in listed],
                "payload_sha256": created.payload_sha256,
                "loaded_payload": loaded.payload,
                "delete_dry_run_preserved": delete_dry_run_preserved,
                "source_after_delete": len(source.list(namespace="bach")),
                "import_plan_inserted": import_plan["inserted"],
                "target_after_plan": target_after_plan,
                "import_apply_inserted": import_apply["inserted"],
                "roundtrip_source_ref": roundtrip.source_ref,
                "roundtrip_payload_matches": roundtrip.payload == payload,
                "payload_fields": sorted(payload),
                "default_max_import_checkpoints": module.DEFAULT_MAX_IMPORT_CHECKPOINTS,
                "default_max_import_payload_bytes": module.DEFAULT_MAX_IMPORT_PAYLOAD_BYTES,
                "import_record_limit_enforced": import_record_limit_enforced,
            }
            result["observed"] = observed
            for key, expected_value in expected.items():
                if key == "schema":
                    continue
                if observed.get(key) != expected_value:
                    result["problems"].append(
                        f"session-checkpoint fixture {key}: expected {expected_value!r}, "
                        f"got {observed.get(key)!r}"
                    )
    finally:
        sys.path.pop(0)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--bach-root", type=Path, required=True)
    parser.add_argument("--carrier-root", type=Path, required=True)
    parser.add_argument("--session-checkpoint-root", type=Path, required=True)
    args = parser.parse_args()

    contract_path = args.contract.resolve()
    repo_root = contract_path.parent.parent
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract_problems = validate_contract(contract)
    spec_problems = validate_specs(contract, repo_root)
    bach = inspect_bach(contract, args.bach_root.resolve())
    carrier = run_carrier_fixture(contract, repo_root, args.carrier_root.resolve())
    session_checkpoint = run_session_checkpoint_fixture(
        contract, repo_root, args.session_checkpoint_root.resolve()
    )
    problems = (
        contract_problems
        + spec_problems
        + bach["problems"]
        + carrier["problems"]
        + session_checkpoint["problems"]
    )
    output = {
        "schema": "ellmos.open-ocean-k9-data-check.v1",
        "status": (
            "pass-contract-adapter-and-two-carrier-fixtures-not-equivalence"
            if not problems
            else "fail"
        ),
        "contract": str(contract_path),
        "bach": bach,
        "carrier": carrier,
        "session_checkpoint_carrier": session_checkpoint,
        "problems": problems,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
