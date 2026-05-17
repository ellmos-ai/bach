#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Generiert releasebezogene Sprach-Artefakte aus bach.db."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SYSTEM_ROOT = Path(__file__).resolve().parents[1]
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.lang import LangHandler


def export_release_languages(system_path: Path | None = None, db_path: Path | None = None) -> dict:
    """Schreibt Sprach-Artefakte aus der aktuellen Datenbank in system/exports/translations."""
    base_path = system_path or SYSTEM_ROOT
    handler = LangHandler(base_path)
    if db_path is not None:
        handler.db_path = db_path

    conn = handler._get_db()
    try:
        export_dir = handler._write_release_exports(conn)
    finally:
        conn.close()

    manifest_path = export_dir / "manifest.release.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "export_dir": str(export_dir),
        "manifest_path": str(manifest_path),
        "manifest": manifest,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialisiert releasebezogene Sprachdateien aus bach.db.")
    parser.add_argument("--system-path", type=Path, default=SYSTEM_ROOT, help="Pfad zum system/-Ordner")
    parser.add_argument("--db-path", type=Path, default=None, help="Optionaler expliziter DB-Pfad")
    args = parser.parse_args(argv)

    result = export_release_languages(system_path=args.system_path, db_path=args.db_path)
    manifest = result["manifest"]
    print(f"Export-Verzeichnis: {result['export_dir']}")
    print(f"Manifest: {result['manifest_path']}")
    print(
        "Sprachen: "
        + ", ".join(sorted(manifest.get("locales", {}).keys()))
    )
    print(
        "Counts: "
        f"{manifest['counts'].get('translations', 0)} translations, "
        f"{manifest['counts'].get('dictionary_entries', 0)} dictionary"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
