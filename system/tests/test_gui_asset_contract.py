"""Ablage-Pruefer fuer echte GUI-Screenshots (Bildvertrag v1).

Deckt system/tools/gui_asset_contract.py ab: fehlende Belege, falsche
Abmessungen, ungueltige PNG-Signatur, unvollstaendige Hash-Protokolle und
abweichendes Versionssiegel. Der Pruefer selbst erzeugt keine Bilder.
"""
import json
import struct
from pathlib import Path

from tools.gui_asset_contract import (
    EXPECTED_SIZE,
    MINIMUM_PAGES,
    REQUIRED_ROUTES,
    check_foreign_version,
    main,
    read_png_size,
    screenshot_filename,
    verify_asset_dir,
)


def png_bytes(width: int = EXPECTED_SIZE[0], height: int = EXPECTED_SIZE[1]) -> bytes:
    """Minimaler PNG-Kopf: Signatur, IHDR-Laenge, Chunkname, Breite/Hoehe."""
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0d" + b"IHDR" + struct.pack(">II", width, height)


def protocol_bytes(routes=REQUIRED_ROUTES) -> bytes:
    record = {"version": "0.2.29", "sha256": "a" * 64, "responses": {r: {"status": 200} for r in routes}}
    return json.dumps(record).encode("utf-8")


def vollstaendig(tmp_path: Path) -> Path:
    for page in MINIMUM_PAGES:
        (tmp_path / screenshot_filename(page)).write_bytes(png_bytes())
        (tmp_path / f"{page}.json").write_bytes(protocol_bytes())
    return tmp_path


def test_leere_ablage_meldet_fehlende_belege(tmp_path):
    findings = verify_asset_dir(tmp_path)
    assert len(findings) == 2 * len(MINIMUM_PAGES)
    assert all(f.startswith(("FEHLT PNG", "FEHLT PROTOKOLL")) for f in findings)


def test_fehlendes_verzeichnis_wird_gemeldet(tmp_path):
    assert verify_asset_dir(tmp_path / "gibtesnicht") == ["VERZEICHNIS FEHLT: " + str(tmp_path / "gibtesnicht")]


def test_vertragskonforme_ablage_ist_befundfrei(tmp_path):
    assert verify_asset_dir(vollstaendig(tmp_path)) == []


def test_falsche_abmessung_wird_gemeldet(tmp_path):
    vollstaendig(tmp_path)
    (tmp_path / screenshot_filename("ki-center")).write_bytes(png_bytes(1280, 800))
    findings = verify_asset_dir(tmp_path)
    assert len(findings) == 1
    assert findings[0].startswith("FALSCHE ABMESSUNG")
    assert "1280x800" in findings[0]


def test_datei_ohne_png_signatur_wird_gemeldet(tmp_path):
    vollstaendig(tmp_path)
    (tmp_path / screenshot_filename("token-dashboard")).write_bytes(b"kein bild")
    findings = verify_asset_dir(tmp_path)
    assert len(findings) == 1 and findings[0].startswith("KEIN PNG")


def test_unlesbares_protokoll_wird_gemeldet(tmp_path):
    vollstaendig(tmp_path)
    (tmp_path / "unified_dashboard.json").write_bytes(b"{kaputt")
    findings = verify_asset_dir(tmp_path)
    assert len(findings) == 1 and findings[0].startswith("PROTOKOLL UNLESBAR")


def test_fehlende_kernroute_wird_gemeldet(tmp_path):
    vollstaendig(tmp_path)
    (tmp_path / "ki-center.json").write_bytes(protocol_bytes(REQUIRED_ROUTES[:-1]))
    findings = verify_asset_dir(tmp_path)
    assert len(findings) == 1
    assert findings[0].startswith("KERNROUTE FEHLT")
    assert REQUIRED_ROUTES[-1] in findings[0]


def test_abweichendes_versionssiegel_wird_gemeldet(tmp_path):
    vollstaendig(tmp_path)
    fremd = tmp_path / "v0.2.28-unified_dashboard.png"
    fremd.write_bytes(png_bytes())
    assert check_foreign_version(tmp_path, "0.2.29") == [
        "VERSIONSSIEGEL: v0.2.28-unified_dashboard.png folgt nicht dem Schema v0.2.29-<seitenname>.png"
    ]
    assert any(f.startswith("VERSIONSSIEGEL") for f in verify_asset_dir(tmp_path))


def test_read_png_size_liest_ihdr_und_meldet_fehlende_datei(tmp_path):
    gueltig = tmp_path / "bild.png"
    gueltig.write_bytes(png_bytes(1440, 900))
    assert read_png_size(gueltig) == (1440, 900)
    assert read_png_size(tmp_path / "weg.png") is None
    assert read_png_size(tmp_path) is None


def test_main_exit_codes(tmp_path, capsys):
    assert main(["--dir", str(tmp_path)]) == 1
    assert "BEFUNDE" in capsys.readouterr().out
    assert main(["--dir", str(vollstaendig(tmp_path))]) == 0
    assert "OK:" in capsys.readouterr().out
