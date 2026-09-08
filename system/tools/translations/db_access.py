#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Gemeinsame DB-Aufloesung fuer Translation-QA-Tools."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


SYSTEM_ROOT = Path(__file__).resolve().parents[2]
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))


def build_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Optionaler DB-Pfad; Default ist hub.bach_paths.BACH_DB.",
    )
    return parser


def resolve_db_path(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit.expanduser()
    try:
        from hub.bach_paths import BACH_DB

        return Path(BACH_DB)
    except ImportError:
        return Path.home() / ".bach" / "bach.db"


def connect(explicit: Path | None = None) -> tuple[Path, sqlite3.Connection]:
    db_path = resolve_db_path(explicit)
    if not db_path.exists():
        raise SystemExit(f"BACH DB nicht gefunden: {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return db_path, conn
