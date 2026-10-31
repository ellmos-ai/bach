# SPDX-License-Identifier: MIT
"""Optional on-demand RAM consumers (Colima, n8n) for the Ocean/BACH RAM-Distributor.

Stopped optional consumers (Colima VM, n8n container/daemon) reserve 0 bytes in
the static host admission budget so large local models (such as Buddha 27B MLX)
are never blocked by idle background services. When an optional consumer is
started on demand or detected as active, its configured budget is accounted for
and an idle monitor can stop it cleanly after the configured inactivity window.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GIB = 1024**3
MIB = 1024**2
_CONSUMER_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_KNOWN_KINDS = frozenset({"colima", "n8n", "process"})

DEFAULT_OPTIONAL_CONSUMERS: dict[str, dict[str, Any]] = {
    "colima": {
        "kind": "colima",
        "ram_budget_bytes": 2 * GIB,
        "idle_timeout_seconds": 1800,
        "autostart": False,
        "start_mode": "on_demand",
    },
    "n8n": {
        "kind": "n8n",
        "ram_budget_bytes": 1 * GIB,
        "idle_timeout_seconds": 1800,
        "autostart": False,
        "start_mode": "on_demand",
        "depends_on": "colima",
        "compose_dir": "/Users/lukas/services/n8n",
    },
}


def _int_bounds(value: Any, low: int, high: int, label: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"invalid {label}")
    return value


def validate_optional_consumers(raw: Any) -> dict[str, dict[str, Any]]:
    """Validate the optional_consumers policy map fail-closed."""
    if not isinstance(raw, dict) or len(raw) > 32:
        raise ValueError("invalid optional_consumers map")
    validated: dict[str, dict[str, Any]] = {}
    allowed_fields = {
        "kind",
        "ram_budget_bytes",
        "idle_timeout_seconds",
        "autostart",
        "start_mode",
        "depends_on",
        "compose_dir",
        "match_pattern",
    }
    for name, spec in raw.items():
        if not isinstance(name, str) or not _CONSUMER_ID.fullmatch(name):
            raise ValueError("invalid optional consumer id")
        required = {"kind", "ram_budget_bytes", "idle_timeout_seconds", "autostart", "start_mode"}
        if not isinstance(spec, dict) or not required <= set(spec) <= allowed_fields:
            raise ValueError("invalid optional consumer fields")
        if spec["kind"] not in _KNOWN_KINDS:
            raise ValueError("invalid optional consumer kind")
        _int_bounds(spec["ram_budget_bytes"], 64 * MIB, 128 * GIB, "ram_budget_bytes")
        _int_bounds(spec["idle_timeout_seconds"], 60, 86_400, "idle_timeout_seconds")
        if spec["autostart"] is not False:
            raise ValueError("optional consumers must have autostart=False")
        if spec["start_mode"] != "on_demand":
            raise ValueError("optional consumers must use start_mode='on_demand'")
        if "depends_on" in spec and (
            not isinstance(spec["depends_on"], str) or not _CONSUMER_ID.fullmatch(spec["depends_on"])
        ):
            raise ValueError("invalid optional consumer dependency")
        if "compose_dir" in spec and (
            not isinstance(spec["compose_dir"], str) or not spec["compose_dir"].strip()
        ):
            raise ValueError("invalid compose_dir")
        if "match_pattern" in spec and (
            not isinstance(spec["match_pattern"], str) or not 1 <= len(spec["match_pattern"]) <= 128
        ):
            raise ValueError("invalid match_pattern")
        validated[name] = dict(spec)
    return validated


def detect_consumer_running(
    name: str,
    spec: Mapping[str, Any],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> bool:
    """Return True only when the optional consumer is currently active on the host."""
    run = runner or subprocess.run
    kind = spec.get("kind", name)
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "")
    try:
        if kind == "colima":
            res = run(
                ["colima", "status"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
                env=env,
            )
            return res.returncode == 0
        if kind == "n8n":
            res = run(
                ["docker", "ps", "--filter", "name=n8n", "--filter", "status=running", "--format", "{{.Names}}"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
                env=env,
            )
            if res.returncode == 0 and any("n8n" in line.lower() for line in res.stdout.splitlines()):
                return True
            pgrep = run(
                ["pgrep", "-f", "n8n"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
                env=env,
            )
            return pgrep.returncode == 0 and bool(pgrep.stdout.strip())
        pattern = str(spec.get("match_pattern") or name)
        pgrep = run(
            ["pgrep", "-f", pattern],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            env=env,
        )
        return pgrep.returncode == 0 and bool(pgrep.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return False


def evaluate_optional_consumers(
    consumers: Mapping[str, Mapping[str, Any]] | None,
    *,
    detector: Callable[[str, Mapping[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    """Compute RAM pool state for optional consumers.

    Stopped consumers contribute 0 bytes to active_ram_bytes. Running consumers
    report their configured ram_budget_bytes.
    """
    if not consumers:
        return {
            "configured": False,
            "active_ram_bytes": 0,
            "standby_ram_bytes": 0,
            "consumers": {},
        }
    validated = validate_optional_consumers(dict(consumers))
    check = detector or detect_consumer_running
    active_bytes = 0
    standby_bytes = 0
    report: dict[str, dict[str, Any]] = {}
    for name, spec in validated.items():
        running = bool(check(name, spec))
        budget = int(spec["ram_budget_bytes"])
        if running:
            active_bytes += budget
        else:
            standby_bytes += budget
        report[name] = {
            "kind": spec["kind"],
            "running": running,
            "ram_budget_bytes": budget,
            "accounted_ram_bytes": budget if running else 0,
            "idle_timeout_seconds": int(spec["idle_timeout_seconds"]),
            "start_mode": spec["start_mode"],
        }
    return {
        "configured": True,
        "active_ram_bytes": active_bytes,
        "standby_ram_bytes": standby_bytes,
        "consumers": report,
    }


@dataclass(frozen=True)
class OnDemandController:
    """Manage on-demand start, stop and idle shutdown of Colima and n8n."""

    state_dir: Path
    consumers: dict[str, dict[str, Any]]

    def _state_file(self, name: str) -> Path:
        return self.state_dir / f"{name}.activity.json"

    def record_activity(self, name: str, *, now: float | None = None) -> dict[str, Any]:
        if name not in self.consumers:
            raise ValueError(f"unknown optional consumer: {name}")
        ts = float(time.time() if now is None else now)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "consumer": name,
            "last_active_epoch": ts,
            "updated_at": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
        }
        self._state_file(name).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    def last_activity(self, name: str) -> float | None:
        path = self._state_file(name)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            val = data.get("last_active_epoch")
            return float(val) if isinstance(val, (int, float)) else None
        except (OSError, ValueError, TypeError):
            return None

    def start_consumer(
        self,
        name: str,
        *,
        available_ram_bytes: int,
        reserve_ram_bytes: int,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        detector: Callable[[str, Mapping[str, Any]], bool] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Start an optional consumer on demand if host RAM reserve permits."""
        if name not in self.consumers:
            raise ValueError(f"unknown optional consumer: {name}")
        spec = self.consumers[name]
        check = detector or detect_consumer_running
        run = runner or subprocess.run
        if check(name, spec):
            self.record_activity(name, now=now)
            return {"consumer": name, "state": "already_running", "started": False}

        dep = spec.get("depends_on")
        required_bytes = int(spec["ram_budget_bytes"])
        if dep and dep in self.consumers and not check(dep, self.consumers[dep]):
            required_bytes += int(self.consumers[dep]["ram_budget_bytes"])

        if available_ram_bytes < reserve_ram_bytes + required_bytes:
            return {
                "consumer": name,
                "state": "waiting_memory_reserve",
                "started": False,
                "available_ram_bytes": available_ram_bytes,
                "required_ram_bytes": reserve_ram_bytes + required_bytes,
            }

        env = os.environ.copy()
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "")
        if dep and dep in self.consumers and not check(dep, self.consumers[dep]):
            dep_res = self._invoke_start(dep, self.consumers[dep], run, env)
            if dep_res.returncode != 0:
                return {"consumer": name, "state": "dependency_start_failed", "started": False, "dependency": dep}
            self.record_activity(dep, now=now)

        res = self._invoke_start(name, spec, run, env)
        if res.returncode != 0:
            return {"consumer": name, "state": "start_failed", "started": False}
        self.record_activity(name, now=now)
        return {"consumer": name, "state": "started", "started": True, "required_ram_bytes": required_bytes}

    @staticmethod
    def _invoke_start(
        name: str,
        spec: Mapping[str, Any],
        run: Callable[..., subprocess.CompletedProcess[str]],
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        kind = spec.get("kind", name)
        if kind == "colima":
            mem_gib = max(1, int(spec["ram_budget_bytes"]) // GIB)
            return run(
                ["colima", "start", "--cpu", "2", "--memory", str(mem_gib)],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
                env=env,
            )
        if kind == "n8n":
            compose_dir = str(spec.get("compose_dir") or "/Users/lukas/services/n8n")
            return run(
                ["docker", "compose", "up", "-d"],
                cwd=compose_dir,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
                env=env,
            )
        raise ValueError(f"unsupported on-demand start kind: {kind}")

    @staticmethod
    def _invoke_stop(
        name: str,
        spec: Mapping[str, Any],
        run: Callable[..., subprocess.CompletedProcess[str]],
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        kind = spec.get("kind", name)
        if kind == "colima":
            return run(
                ["colima", "stop"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
                env=env,
            )
        if kind == "n8n":
            compose_dir = str(spec.get("compose_dir") or "/Users/lukas/services/n8n")
            return run(
                ["docker", "compose", "stop"],
                cwd=compose_dir,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
                env=env,
            )
        raise ValueError(f"unsupported on-demand stop kind: {kind}")

    def stop_consumer(
        self,
        name: str,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        detector: Callable[[str, Mapping[str, Any]], bool] | None = None,
    ) -> dict[str, Any]:
        if name not in self.consumers:
            raise ValueError(f"unknown optional consumer: {name}")
        spec = self.consumers[name]
        check = detector or detect_consumer_running
        run = runner or subprocess.run
        if not check(name, spec):
            return {"consumer": name, "state": "already_stopped", "stopped": False}
        env = os.environ.copy()
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "")
        res = self._invoke_stop(name, spec, run, env)
        if res.returncode != 0:
            return {"consumer": name, "state": "stop_failed", "stopped": False}
        return {"consumer": name, "state": "stopped", "stopped": True}

    def stop_idle_consumers(
        self,
        *,
        now: float | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        detector: Callable[[str, Mapping[str, Any]], bool] | None = None,
    ) -> list[dict[str, Any]]:
        """Stop running optional consumers that have exceeded their idle_timeout_seconds."""
        current = float(time.time() if now is None else now)
        check = detector or detect_consumer_running
        results: list[dict[str, Any]] = []
        # Stop dependents (like n8n) before their base runtime (like colima)
        ordered = sorted(self.consumers, key=lambda k: 0 if self.consumers[k].get("depends_on") else 1)
        for name in ordered:
            spec = self.consumers[name]
            if not check(name, spec):
                continue
            last = self.last_activity(name)
            if last is None:
                self.record_activity(name, now=current)
                continue
            if current - last >= int(spec["idle_timeout_seconds"]):
                results.append(self.stop_consumer(name, runner=runner, detector=check))
        return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage optional on-demand RAM consumers (Colima, n8n).")
    parser.add_argument("action", choices=["status", "start", "stop", "touch", "idle-check"])
    parser.add_argument("consumer", nargs="?", choices=["colima", "n8n"])
    parser.add_argument(
        "--state-dir",
        default=str(Path.home() / ".bach/runtime/local-inference/optional-consumers"),
    )
    args = parser.parse_args(argv)
    consumers = validate_optional_consumers(DEFAULT_OPTIONAL_CONSUMERS)
    controller = OnDemandController(state_dir=Path(args.state_dir).expanduser().resolve(), consumers=consumers)

    if args.action == "status":
        print(json.dumps(evaluate_optional_consumers(consumers), indent=2))
        return 0
    if args.action == "idle-check":
        print(json.dumps({"stopped": controller.stop_idle_consumers()}, indent=2))
        return 0
    if not args.consumer:
        parser.error("consumer name ('colima' or 'n8n') is required for start/stop/touch")
    if args.action == "touch":
        print(json.dumps(controller.record_activity(args.consumer), indent=2))
        return 0
    if args.action == "stop":
        res = controller.stop_consumer(args.consumer)
        print(json.dumps(res, indent=2))
        return 0 if res.get("stopped") or res.get("state") == "already_stopped" else 1

    import psutil
    mem = psutil.virtual_memory()
    res = controller.start_consumer(
        args.consumer,
        available_ram_bytes=int(mem.available),
        reserve_ram_bytes=2 * GIB,
    )
    print(json.dumps(res, indent=2))
    return 0 if res.get("started") or res.get("state") == "already_running" else 1


if __name__ == "__main__":
    sys.exit(main())
