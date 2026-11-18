# SPDX-License-Identifier: MIT
"""Read-only Hybrid-C projection. Ocean owns catalogue, sensors and planning rules.

No BACH database, task claim, queue, model call, scheduler or arbiter is opened here.
The optional provider must be an exact canonical VCS installation, not a name match.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from hub._services.ocean_resources_provider import (
    REPOSITORY,
    VERSION,
    PipelineProviderUnavailable,
    load_verified,
    pin,
)

__all__ = ["OPERATIONS", "PIN", "REPOSITORY", "VERSION", "PipelineProviderUnavailable", "observe"]

PIN = pin()["commit"]
OPERATIONS = frozenset({"resources", "catalog", "host", "capacity", "shadow"})


def _provider():
    if os.environ.get("BACH_PIPELINE_COORDINATION_ENABLED") != "1":
        raise PipelineProviderUnavailable("pipeline_coordination_disabled")
    return load_verified(("ocean_resources", "ocean_resources.host", "ocean_resources.capacity",
                          "ocean_resources.pipelines", "ocean_resources.__main__"))


def _read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError("nonfinite JSON")

    with Path(path).open("rb") as stream:
        raw = stream.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("projection too large")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=nonfinite)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("invalid explicit pipeline arguments")


def observe(operation: str, args=()) -> tuple[bool, dict]:
    """Same structured, read-only result for handler, CLI and bach_api."""
    envelope = {
        "schema": "bach.ocean-pipeline-observation.v1", "read_only": True,
        "start_authorized": False, "provider": {"id": "ocean-resources", "source_commit": PIN},
    }
    if operation not in OPERATIONS:
        return False, {**envelope, "state": "HOLD", "reason": "unknown_read_only_operation"}
    try:
        if operation not in {"shadow", "capacity"} and args:
            raise ValueError("operation takes no arguments")
        options = None
        if operation == "shadow":
            parser = _Parser(add_help=False, allow_abbrev=False)
            parser.add_argument("--jobs", required=True)
            parser.add_argument("--catalog")
            parser.add_argument("--reserve-ram-bytes", required=True, type=int)
            parser.add_argument("--reserve-disk-bytes", required=True, type=int)
            options = parser.parse_args(list(args))
        elif operation == "capacity":
            parser = _Parser(add_help=False, allow_abbrev=False)
            parser.add_argument("--reserve-ram-bytes", required=True, type=int)
            parser.add_argument("--reserve-cpu-units", required=True, type=int)
            parser.add_argument("--reserve-disk-bytes", required=True, type=int)
            parser.add_argument("--capacity-directory", required=True)
            parser.add_argument("--sample-seconds", type=float, default=0.25)
            options = parser.parse_args(list(args))
        modules = _provider()
        host = modules["ocean_resources.host"]
        pipelines = modules["ocean_resources.pipelines"]
        if operation == "resources":
            report = modules["ocean_resources.__main__"].manifest()
        elif operation == "catalog":
            report = pipelines.catalog_document()
        elif operation == "host":
            report = host.sample_host().to_dict()
        elif operation == "capacity":
            capacity = modules["ocean_resources.capacity"]
            policy = capacity.CapacityPolicy(options.reserve_ram_bytes, options.reserve_cpu_units,
                                             options.reserve_disk_bytes, Path(options.capacity_directory),
                                             sample_seconds=options.sample_seconds)
            report = capacity.NativeCapacitySensor(policy).observe()
        else:
            budget = pipelines.ResourceBudget(options.reserve_ram_bytes, options.reserve_disk_bytes)
            jobs = _read_json(options.jobs)
            catalog = pipelines.load_catalog(_read_json(options.catalog)) if options.catalog else pipelines.load_catalog()
            report = pipelines.shadow_plan(jobs, host.sample_host(), budget, now=time.time(), catalog=catalog)
        return True, {**envelope, "state": "OBSERVED", "data": report}
    except PipelineProviderUnavailable as exc:
        return False, {**envelope, "state": "HOLD", "reason": str(exc)}
    except Exception:  # noqa: BLE001 - provider/input failures must not leak private paths or bypass HOLD
        # Keep local paths, job content and package-internal errors out of output.
        return False, {**envelope, "state": "HOLD", "reason": "invalid_or_unavailable_observation_input"}
