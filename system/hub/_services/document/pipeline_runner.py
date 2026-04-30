#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone CLI-Runner fuer die Foerderbericht-Pipeline.

Verwendung:
    python pipeline_runner.py                                    # Auto-Detect (empfohlen)
    python pipeline_runner.py --zeitraum "01.01.2025 - 31.12.2025"
    python pipeline_runner.py "Max Mustermann" "15.03.2016"      # Explizite Angabe
    python pipeline_runner.py --no-cleanup                       # Zwischenordner behalten

Version: 1.0.0
Erstellt: 2026-03-11
"""
import sys
import os
import argparse
from pathlib import Path

# Windows Encoding Fix
os.environ["PYTHONIOENCODING"] = "utf-8"

# BACH system/ zum sys.path hinzufuegen
_bach_system = Path(__file__).resolve().parent.parent.parent.parent
if str(_bach_system) not in sys.path:
    sys.path.insert(0, str(_bach_system))


def main():
    parser = argparse.ArgumentParser(
        description="Foerderbericht End-to-End Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  python pipeline_runner.py                                          # Auto-Detect (empfohlen)
  python pipeline_runner.py --zeitraum "01.07.2025 - 30.06.2026"    # Anderer Zeitraum
  python pipeline_runner.py "Max Mustermann" "15.03.2016"            # Explizit
  python pipeline_runner.py --eltern "Maria M." "Hans M."            # Eltern anonymisieren
  python pipeline_runner.py --no-cleanup                              # Debug: Zwischenordner behalten

Vor dem Start: Aktenordner in data_roh/ ablegen (Format: "Nachname, Vorname").
Name + Geburtsdatum werden automatisch erkannt.
        """
    )
    parser.add_argument("client_name", nargs="?", default=None,
                        help="Name des Klienten (optional, wird aus Ordnername ermittelt)")
    parser.add_argument("geburtsdatum", nargs="?", default=None,
                        help="Geburtsdatum TT.MM.JJJJ (optional, wird aus Akte ermittelt)")
    parser.add_argument(
        "--zeitraum", default="01.01.2025 - 31.12.2025",
        help="Berichtszeitraum (Default: 01.01.2025 - 31.12.2025)"
    )
    parser.add_argument(
        "--backend", default="claude_code",
        choices=["claude_code", "anthropic_sdk", "llmauto"],
        help="LLM-Backend (Default: claude_code)"
    )
    parser.add_argument(
        "--model", default="claude-sonnet-4-6",
        help="LLM-Modell (Default: claude-sonnet-4-6)"
    )
    parser.add_argument(
        "--eltern", nargs="*",
        help="Elternnamen (werden anonymisiert)"
    )
    parser.add_argument(
        "--adresse",
        help="Klienten-Adresse (wird anonymisiert)"
    )
    parser.add_argument(
        "--no-cleanup", action="store_true",
        help="Zwischenordner nicht leeren nach Durchlauf"
    )
    parser.add_argument(
        "--base-path",
        help="Alternativer Basis-Ordner (Default: aus bach_paths)"
    )
    args = parser.parse_args()

    from hub._services.document.foerderbericht_pipeline import FoerderberichtPipeline

    print(f"[PIPELINE] Starte fuer: {args.client_name or 'Auto-Detect'}")
    print(f"[PIPELINE] Geburtsdatum: {args.geburtsdatum or 'Auto-Detect'}")
    print(f"[PIPELINE] Zeitraum: {args.zeitraum}")
    print(f"[PIPELINE] Backend: {args.backend} / {args.model}")
    print()

    pipeline = FoerderberichtPipeline(base_path=args.base_path)
    result = pipeline.run_full_pipeline(
        client_name=args.client_name,
        geburtsdatum=args.geburtsdatum,
        berichtszeitraum=args.zeitraum,
        parent_names=args.eltern,
        client_address=args.adresse,
        llm_backend=args.backend,
        model=args.model,
        auto_cleanup=not args.no_cleanup,
    )

    print()
    if result.success:
        print(f"[OK] Bericht erstellt: {result.output_path}")
        print(f"     Tarnname war: {result.tarnname}")
        print(f"     Dauer: {result.duration_s:.1f}s")
        print()
        for step in result.steps_completed:
            print(f"     - {step}")
    else:
        print(f"[FEHLER] {result.error}")
        if result.steps_completed:
            print()
            print("     Abgeschlossene Schritte:")
            for step in result.steps_completed:
                print(f"     - {step}")
        sys.exit(1)


if __name__ == "__main__":
    main()
