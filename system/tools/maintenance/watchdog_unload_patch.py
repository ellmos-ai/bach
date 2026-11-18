#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Prepare a reviewed watchdog unload patch without installing or executing it.

Only the known direct-unload function is replaced. The operator must verify the
complete source preimage again when deploying the prepared artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import sys

MAX_SOURCE_BYTES = 1024 * 1024
REVIEWED_FUNCTION_SHA256 = "221c4222400f44b51c0784bdc709f418acf6d77d01dca52d245d743250e6f117"


def _operator_path(value: str) -> str:
    if not isinstance(value, str) or not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("invalid_operator_path")
    path = PurePosixPath(value)
    if not path.is_absolute() or value.startswith("//") or ".." in path.parts:
        raise ValueError("invalid_operator_path")
    return shlex.quote(value)


def prepare_patch(source: bytes, *, expected_sha256: str,
                  python_path: str, helper_path: str) -> bytes:
    """Return a staged source image; never mutate a file or contact a service."""
    if (not isinstance(source, bytes) or len(source) > MAX_SOURCE_BYTES
            or not isinstance(expected_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None):
        raise ValueError("invalid_source_contract")
    if hashlib.sha256(source).hexdigest() != expected_sha256:
        raise ValueError("source_changed")
    python = _operator_path(python_path)
    helper = _operator_path(helper_path)
    starts = list(re.finditer(br"(?m)^do_ollama_unload_all\(\) \{\n", source))
    if len(starts) != 1:
        raise ValueError("unsupported_unload_function")
    start = starts[0].start()
    end = source.find(b"\nundo_ollama_unload_all()", start)
    if end < 0 or hashlib.sha256(source[start:end]).hexdigest() != REVIEWED_FUNCTION_SHA256:
        raise ValueError("unsupported_unload_function")
    replacement = (
        "do_ollama_unload_all() {\n"
        "    # Shared host inference ownership; never fall back to a direct POST.\n"
        '    local inference_root="${BACH_RUNTIME_DIR:-$HOME/.bach/runtime}/local-inference"\n'
        f"    {python} -I -B {helper} \\\n"
        '        --inference-root "$inference_root" \\\n'
        '        --session-flag "$SESSION_FLAG" --metric-mode "$METRIC_MODE" \\\n'
        '        --warn-level "$PRESSURE_WARN_LEVEL" \\\n'
        '        --emergency-pages "$FREE_EMERGENCY_PAGES" \\\n'
        '        --free-threshold "${free_threshold:-$FREE_PAGES_MIN}" >> "$LOG" 2>&1\n'
        "}\n"
    ).encode("utf-8")
    return source[:start] + replacement + source[end:]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--python", dest="python_path", required=True)
    parser.add_argument("--helper", dest="helper_path", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.source.is_symlink() or not args.source.is_file():
            raise ValueError("invalid_source_path")
        with args.source.open("rb") as handle:
            source = handle.read(MAX_SOURCE_BYTES + 1)
        result = prepare_patch(source, expected_sha256=args.expected_sha256,
            python_path=args.python_path, helper_path=args.helper_path)
        # Exclusive creation also rejects an existing or dangling output link.
        # This command deliberately has no in-place write or apply mode.
        with args.output.open("xb") as handle:
            handle.write(result)
            handle.flush()
            os.fsync(handle.fileno())
    except (OSError, ValueError) as error:
        code = str(error) if isinstance(error, ValueError) else "artifact_write_or_read_failed"
        print("watchdog_patch_rejected:" + code, file=sys.stderr)
        return 2
    print(json.dumps({
        "schema": "bach.watchdog-unload-patch.v1",
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "prepared_sha256": hashlib.sha256(result).hexdigest(),
        "python_path": args.python_path,
        "helper_path": args.helper_path,
        "applied": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
