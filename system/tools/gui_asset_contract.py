#!/usr/bin/env python3
"""Prueft die Ablage echter GUI-Screenshots gegen den Bildvertrag v1.

Abgrenzung zu D2 (DECISION-20261030 Lukas): Dieses Werkzeug enthaelt bewusst
KEINEN Screenshot-Code. Es startet keine GUI, oeffnet keinen Browser, nutzt
kein Netzwerk und veraendert keine Bilder. Es prueft ausschliesslich, ob die
nach assets/gui/README.md abzulegenden Dateien vertragskonform vorliegen und
macht damit das dort formulierte Abnahmekriterium maschinell nachvollziehbar.

Vertragsquelle: assets/gui/README.md (Namensschema, Mindestumfang,
Abnahmekriterium) sowie system/gui/gui-consumer.v1.json:12-17 (Kernrouten,
"A pin alone does not prove a live installation.").

Nutzung:
    python -m tools.gui_asset_contract --dir assets/gui
    python -m tools.gui_asset_contract --dir assets/gui --version 0.2.29

Exit-Codes: 0 = vertragskonform, 1 = Befunde, 2 = Aufruffehler.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path
from typing import Iterable, Sequence

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# Bildvertrag, Abschnitt "Mindestumfang" (assets/gui/README.md:13-19).
MINIMUM_PAGES: tuple[str, ...] = (
    "unified_dashboard",
    "ki-center",
    "token-dashboard",
)

# Bildvertrag, Pflichtanforderungen 1 und 6 (assets/gui/README.md:47, :52).
EXPECTED_SIZE: tuple[int, int] = (1440, 900)

# Kernrouten, die laut Pflichtanforderung 3 im JSON-Protokoll stehen muessen.
REQUIRED_ROUTES: tuple[str, ...] = (
    "/api/gui/brand",
    "/api/gui/backend-origin",
    "/api/gui/capabilities",
)


def screenshot_filename(page: str, version: str = "0.2.29") -> str:
    """Liefert den vertragskonformen Dateinamen fuer eine GUI-Seite."""
    return f"v{version}-{page}.png"


def protocol_filename(page: str) -> str:
    """Liefert den Namen des Hash-Protokolls zu einer GUI-Seite."""
    return f"{page}.json"


def read_png_size(path: Path) -> tuple[int, int] | None:
    """Liest Breite/Hoehe aus dem IHDR-Chunk; None wenn keine PNG-Datei."""
    try:
        with path.open("rb") as handle:
            header = handle.read(24)
    except OSError:
        return None
    if len(header) < 24 or header[:8] != PNG_SIGNATURE or header[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", header[16:24])
    return width, height


def _collect_json_keys(payload: object, out: set[str]) -> None:
    """Sammelt Schluesselnamen rekursiv, unabhaengig von der Verschachtelung."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            out.add(str(key))
            _collect_json_keys(value, out)
    elif isinstance(payload, list):
        for item in payload:
            _collect_json_keys(item, out)


def check_page(
    directory: Path,
    page: str,
    version: str = "0.2.29",
    expected_size: tuple[int, int] = EXPECTED_SIZE,
) -> list[str]:
    """Prueft eine einzelne GUI-Seite auf PNG und Hash-Protokoll."""
    findings: list[str] = []
    png_path = directory / screenshot_filename(page, version)
    json_path = directory / protocol_filename(page)

    if not png_path.is_file():
        findings.append(f"FEHLT PNG: {png_path.name} (Seite {page!r} nicht bildlich belegt)")
    else:
        size = read_png_size(png_path)
        if size is None:
            findings.append(f"KEIN PNG: {png_path.name} traegt keine gueltige PNG-Signatur/IHDR")
        elif size != expected_size:
            findings.append(
                f"FALSCHE ABMESSUNG: {png_path.name} ist {size[0]}x{size[1]}, "
                f"erwartet {expected_size[0]}x{expected_size[1]}"
            )

    if not json_path.is_file():
        findings.append(
            f"FEHLT PROTOKOLL: {json_path.name} (Live-Nachweis der Kernrouten nicht belegt)"
        )
    else:
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            findings.append(f"PROTOKOLL UNLESBAR: {json_path.name} ({exc})")
        else:
            keys: set[str] = set()
            _collect_json_keys(payload, keys)
            for route in REQUIRED_ROUTES:
                if route not in keys:
                    findings.append(
                        f"KERNROUTE FEHLT: {json_path.name} enthaelt keinen Eintrag zu {route}"
                    )
    return findings


def check_foreign_version(directory: Path, version: str = "0.2.29") -> list[str]:
    """Meldet PNGs, die nicht dem Versionssiegel des Laufs folgen."""
    findings: list[str] = []
    if not directory.is_dir():
        return findings
    prefix = f"v{version}-"
    for path in sorted(directory.glob("v*-*.png")):
        if not path.name.startswith(prefix):
            findings.append(
                f"VERSIONSSIEGEL: {path.name} folgt nicht dem Schema v{version}-<seitenname>.png"
            )
    return findings


def verify_asset_dir(
    directory: str | Path,
    version: str = "0.2.29",
    pages: Sequence[str] = MINIMUM_PAGES,
    expected_size: tuple[int, int] = EXPECTED_SIZE,
) -> list[str]:
    """Prueft das gesamte Ablageverzeichnis; leere Liste bedeutet vertragskonform."""
    target = Path(directory)
    if not target.is_dir():
        return [f"VERZEICHNIS FEHLT: {target}"]
    findings: list[str] = []
    for page in pages:
        findings.extend(check_page(target, page, version, expected_size))
    findings.extend(check_foreign_version(target, version))
    return findings


def _parse_args(argv: Iterable[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prueft die Ablage echter GUI-Screenshots gegen den Bildvertrag v1 "
        "(kein Screenshot-Code, kein Netzwerk).",
    )
    parser.add_argument("--dir", default="assets/gui", help="Ablageverzeichnis (Standard: assets/gui)")
    parser.add_argument("--version", default="0.2.29", help="erwartete GUI-Version (Standard: 0.2.29)")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    findings = verify_asset_dir(args.dir, args.version)
    if not findings:
        print(f"OK: Ablage {args.dir} erfuellt den Bildvertrag v{args.version}.")
        return 0
    print(f"BEFUNDE ({len(findings)}) in {args.dir}:")
    for finding in findings:
        print(f"  - {finding}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
