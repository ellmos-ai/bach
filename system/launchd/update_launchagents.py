#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Sicheres Aktualisieren und Neustarten der Mac-LaunchAgents (T-20260926-537523074).

Fuehrt die in docs/operations/MAC-CHAT-LAUNCHAGENTS.md vorgeschriebenen Schritte
atomar aus:
1. Installierte Plist unter ~/Library/LaunchAgents sichern (.bak-YYYYMMDD-HHMMSS)
2. EnvironmentVariables gezielt aktualisieren (ohne hostspezifische Keys zu verlieren)
3. plutil -lint pruefen
4. Optional (oder mit --reload): launchctl bootout -> bootstrap -> sofort kickstart -k
5. Laufzustand (state = running, pid) und gesetzte Env-Variablen per launchctl print pruefen
"""
from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

DEFAULT_LABELS = (
    "com.bach.chat-tray",
    "com.bach.telegram-bot",
    "com.bach.gui-server",
)


def update_plist_env(plist_path: Path, env_updates: dict[str, str]) -> Path:
    """Sichert ``plist_path``, aktualisiert ``EnvironmentVariables`` und prueft ``plutil -lint``."""
    if not plist_path.is_file():
        raise FileNotFoundError(f"LaunchAgent-Plist fehlt: {plist_path}")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = plist_path.with_name(f"{plist_path.name}.bak-{stamp}")
    shutil.copy2(plist_path, backup_path)

    with plist_path.open("rb") as fh:
        data = plistlib.load(fh)
    env = dict(data.get("EnvironmentVariables") or {})
    env.update(env_updates)
    data["EnvironmentVariables"] = env
    with plist_path.open("wb") as fh:
        plistlib.dump(data, fh, sort_keys=True)

    subprocess.run(["plutil", "-lint", str(plist_path)], check=True, capture_output=True, text=True)
    return backup_path


def reload_launchagent(label: str, plist_path: Path, uid: int | None = None) -> dict[str, str]:
    """bootout -> bootstrap -> sofort kickstart -k -> launchctl print Readback."""
    uid = os.getuid() if uid is None else uid
    domain = f"gui/{uid}"
    service = f"{domain}/{label}"

    subprocess.run(["launchctl", "bootout", service], capture_output=True, text=True)
    time.sleep(0.5)
    boot = subprocess.run(["launchctl", "bootstrap", domain, str(plist_path)], capture_output=True, text=True)
    if boot.returncode != 0:
        time.sleep(0.5)
        subprocess.run(["launchctl", "bootstrap", domain, str(plist_path)], capture_output=True, text=True)

    subprocess.run(["launchctl", "kickstart", "-k", service], check=True, capture_output=True, text=True)
    time.sleep(1.0)
    info = subprocess.run(["launchctl", "print", service], check=True, capture_output=True, text=True).stdout

    state = "unknown"
    pid = ""
    for line in info.splitlines():
        stripped = line.strip()
        if stripped.startswith("state ="):
            state = stripped.split("=", 1)[1].strip()
        elif stripped.startswith("pid ="):
            pid = stripped.split("=", 1)[1].strip()
    return {"label": label, "state": state, "pid": pid, "raw": info}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Update and kickstart Mac BACH LaunchAgents safely.")
    parser.add_argument("--label", action="append", dest="labels", help="LaunchAgent label (default: all 3 BACH services)")
    parser.add_argument("--set", action="append", dest="env_pairs", default=[], metavar="KEY=VALUE",
                        help="Environment variable to set in EnvironmentVariables")
    parser.add_argument("--reload", action="store_true", help="Reload via bootout + bootstrap + kickstart -k")
    parser.add_argument("--launchagents-dir", type=Path, default=Path.home() / "Library" / "LaunchAgents")
    args = parser.parse_args(argv)

    labels = tuple(args.labels) if args.labels else DEFAULT_LABELS
    updates: dict[str, str] = {}
    for pair in args.env_pairs:
        if "=" not in pair:
            raise SystemExit(f"Ungueltiges --set Format (erwartet KEY=VALUE): {pair}")
        k, v = pair.split("=", 1)
        updates[k.strip()] = v.strip()

    for k, v in updates.items():
        subprocess.run(["launchctl", "setenv", k, v], check=False)

    for label in labels:
        plist_path = args.launchagents_dir / f"{label}.plist"
        if updates:
            bak = update_plist_env(plist_path, updates)
            print(f"[OK] {label}: Plist aktualisiert (Backup: {bak.name})")
        if args.reload:
            status = reload_launchagent(label, plist_path)
            print(f"[OK] {label}: state={status['state']} pid={status['pid']}")
            for k, v in updates.items():
                if f"{k} => {v}" not in status["raw"]:
                    raise SystemExit(f"[FEHLER] {label}: {k} => {v} fehlt in launchctl print")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
