#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI entry point for BACH self-test."""
from tools.self_test.e_tests import generate_prompt, PROFILES
import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="BACH Self-Test: LLM-Selbsterfahrungsprotokoll"
    )
    parser.add_argument(
        "profile", nargs="?", default="standard",
        choices=["quick", "standard", "full"],
        help="Testprofil (quick=4, standard=7, full=10 Tests)"
    )
    parser.add_argument(
        "--output", "-o", type=str,
        help="Prompt in Datei schreiben (sonst stdout)"
    )
    parser.add_argument(
        "--list", action="store_true",
        help="Verfuegbare Tests und Profile auflisten"
    )

    args = parser.parse_args()

    if args.list:
        from tools.self_test.e_tests import E_TESTS
        print("Verfuegbare E-Tests:")
        print("-" * 60)
        for t in E_TESTS:
            print(f"  {t['id']}  {t['title']:<35} [{t['category']}]")
        print()
        print("Profile:")
        for name, ids in PROFILES.items():
            print(f"  {name:<10} {len(ids)} Tests: {', '.join(ids)}")
        return

    prompt = generate_prompt(profile=args.profile)

    if args.output:
        Path(args.output).write_text(prompt, encoding="utf-8")
        print(f"Prompt geschrieben: {args.output} ({len(prompt)} Zeichen)")
    else:
        print(prompt)


if __name__ == "__main__":
    main()
