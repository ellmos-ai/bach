#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
BACH Gemini Starter
===================
Startet Gemini CLI (headless) oder Antigravity (GUI) mit BACH-Kontext.

Backends:
    --cli         Gemini CLI (headless, vollautomatisch)
    --gui         Antigravity (Prompt in Zwischenablage)

Modi:
    (default)     Auto-Modus mit prompts/auto.txt (nur CLI)
    --bulk        Bulk-Modus ohne Task-Limit
    --default     Interaktiv (wartet auf Anweisungen)
    --individual  Nutzt startprompt_gemini.txt
    --mode X      Nutzt prompts/X.txt (analyse, research, ...)
    --prompt "X"  Custom Prompt direkt angeben

Optionen:
    --tasks N     Anzahl Tasks im Auto-Modus (default: 2)
    --dry-run     Nur Befehl anzeigen
    --list        Verfuegbare Prompt-Vorlagen auflisten
"""

import shutil
import subprocess
import sys
from pathlib import Path

# Pfade - resolve() fuer absolute Pfade auch bei Aufruf aus anderen Verzeichnissen
# Skript liegt in tools/partner_communication/ -> 2x parent = BACH
BACH_DIR = Path(__file__).resolve().parent.parent.parent
GEMINI_DIR = BACH_DIR / "_partners" / "gemini"
PROMPTS_DIR = GEMINI_DIR / "prompts"
INDIVIDUAL_PROMPT_FILE = GEMINI_DIR / "startprompt_gemini.txt"
SKILL_FILE = BACH_DIR / "SKILL.md"


def copy_to_clipboard(text):
    """Kopiert Text in die Zwischenablage (cross-platform)."""
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except ImportError:
        pass

    import subprocess
    import shutil
    data = text.encode("utf-8")
    try:
        if sys.platform == "win32":
            process = subprocess.Popen(["clip"], stdin=subprocess.PIPE)
            process.communicate(text.encode("utf-16-le"))
            return True
        elif sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=data, capture_output=True)
            return True
        elif shutil.which("wl-copy"):
            subprocess.run(["wl-copy"], input=data, capture_output=True)
            return True
        elif shutil.which("xsel"):
            subprocess.run(["xsel", "-b", "-i"], input=data, capture_output=True)
            return True
        elif shutil.which("xclip"):
            subprocess.run(["xclip", "-selection", "clipboard"], input=data, capture_output=True)
            return True
    except (OSError, FileNotFoundError):
        pass
    return False


def list_prompt_files():
    """Listet alle verfuegbaren Prompt-Vorlagen auf."""
    print("Verfuegbare Prompt-Vorlagen:")
    print("-" * 40)
    if PROMPTS_DIR.exists():
        for f in sorted(PROMPTS_DIR.glob("*.txt")):
            name = f.stem
            # Erste Zeile als Beschreibung
            first_line = f.read_text(encoding='utf-8').split('\n')[0][:50]
            print(f"  {name:12} - {first_line}")
    print()
    print(f"Individual:    {INDIVIDUAL_PROMPT_FILE}")
    print()


def load_prompt_file(name):
    """Laedt eine Prompt-Vorlage aus prompts/."""
    pfile = PROMPTS_DIR / f"{name}.txt"
    if pfile.exists():
        content = pfile.read_text(encoding='utf-8').strip()
        # Kommentarzeilen entfernen
        lines = [l for l in content.split('\n') if not l.strip().startswith('#')]
        return '\n'.join(lines).strip()
    return None


def load_individual_prompt():
    """Laedt den individuellen User-Prompt."""
    if INDIVIDUAL_PROMPT_FILE.exists():
        content = INDIVIDUAL_PROMPT_FILE.read_text(encoding='utf-8').strip()
        # Kommentarzeilen entfernen
        lines = [l for l in content.split('\n') if not l.strip().startswith('#')]
        result = '\n'.join(lines).strip()
        if result:
            return result
    return None


def build_auto_prompt(task_count=2):
    """Baut den Auto-Modus Prompt zusammen."""
    base = load_prompt_file("auto")
    if base:
        # Task-Count einbauen falls noetig
        if task_count != 2:
            return f"{base}\n\nAnzahl Tasks: {task_count}"
        return base
    # Fallback
    return f"AUTOMATISCHER MODUS: Nutze 'python bach.py task list | grep -i gemini' um deine Tasks zu finden. Bearbeite {task_count} Tasks, markiere sie via 'bach task done <id>', dann STOPP."


def get_prompt(mode, task_count=2, custom_prompt=None):
    """Ermittelt den Prompt basierend auf Modus."""
    if custom_prompt:
        return custom_prompt, "CUSTOM"
    elif mode == "auto":
        return build_auto_prompt(task_count), f"AUTO ({task_count} Tasks)"
    elif mode == "bulk":
        prompt = load_prompt_file("bulk")
        if not prompt:
            prompt = "BULK-MODUS: Nutze 'bach task list | grep -i gemini'. Bearbeite ALLE Tasks, markiere via 'bach task done <id>'. Erstelle Reports in partners/gemini/outbox/."
        return prompt, "BULK"
    elif mode == "individual":
        prompt = load_individual_prompt()
        if not prompt:
            return None, "INDIVIDUAL"
        return prompt, "INDIVIDUAL"
    elif mode == "default":
        prompt = load_prompt_file("default")
        if not prompt:
            prompt = "Warte auf Anweisungen. Arbeitsverzeichnis ist BACH."
        return prompt, "INTERAKTIV"
    else:
        # Mode ist Dateiname in prompts/
        prompt = load_prompt_file(mode)
        if not prompt:
            return None, mode.upper()
        return prompt, mode.upper()


def start_cli(prompt, mode_display, dry_run=False):
    """Startet Gemini CLI im headless Modus."""

    # Gemini CLI finden
    executable = shutil.which("gemini")
    if not executable:
        print("[FEHLER] 'gemini' CLI nicht gefunden!")
        print("         Installation: npm install -g gemini-cli")
        print("         Auth: gemini auth login")
        return False

    # Befehl zusammenbauen
    # Hinweis: gemini CLI hat kein -b/--headless Flag
    # Stattdessen: Prompt als Argument = non-interactive
    cmd = [
        executable,
        "--yolo",   # Automatisch fortfahren ohne Nachfragen
        prompt      # Prompt als positional argument
    ]

    print("=" * 60)
    print("BACH - Gemini CLI (Headless)")
    print("=" * 60)
    print(f"Arbeitsverzeichnis: {BACH_DIR}")
    print(f"Modus:              {mode_display}")
    print(f"Backend:            Gemini CLI (--yolo)")
    print()

    if dry_run:
        print("[DRY-RUN] Befehl wuerde sein:")
        quoted_cmd = []
        for arg in cmd:
            if ' ' in arg or '&' in arg or '\n' in arg:
                # Mehrzeilige Prompts kuerzen fuer Anzeige
                if '\n' in arg:
                    arg = arg.split('\n')[0][:50] + "..."
                quoted_cmd.append(f'"{arg}"')
            else:
                quoted_cmd.append(arg)
        print(" ".join(quoted_cmd))
        return True

    print("Starte Gemini CLI...")
    print()

    try:
        # CLI starten (blocking - laeuft bis fertig)
        process = subprocess.Popen(
            cmd,
            cwd=str(BACH_DIR),
            shell=False
        )
        print(f"[OK] Gemini CLI gestartet (PID: {process.pid})")
        print("     Laeuft im Hintergrund bis Tasks fertig.")
        return True

    except FileNotFoundError:
        print("[FEHLER] 'gemini' nicht gefunden!")
        print("         Installation: npm install -g gemini-cli")
        return False
    except Exception as e:
        print(f"[FEHLER] {e}")
        return False


def start_gui(prompt, mode_display, dry_run=False):
    """Startet Antigravity und kopiert Prompt in Zwischenablage."""

    # Antigravity finden
    executable = shutil.which("antigravity") or "antigravity"

    # Befehl zusammenbauen (OHNE Prompt - der geht in Clipboard)
    cmd = [
        executable,
        str(BACH_DIR),  # Arbeitsverzeichnis
        "chat",
        "-m", "agent",
        "--maximize",
    ]

    # Kontext-Dateien hinzufuegen
    if SKILL_FILE.exists():
        cmd.extend(["--add-file", str(SKILL_FILE)])

    print("=" * 60)
    print("BACH - Antigravity (GUI)")
    print("=" * 60)
    print(f"Arbeitsverzeichnis: {BACH_DIR}")
    print(f"Modus:              {mode_display}")
    print(f"Backend:            Antigravity (GUI)")
    print(f"Kontext-Dateien:    SKILL.md")
    print()

    if dry_run:
        print("[DRY-RUN] Befehl wuerde sein:")
        quoted_cmd = []
        for arg in cmd:
            if ' ' in arg or '&' in arg:
                quoted_cmd.append(f'"{arg}"')
            else:
                quoted_cmd.append(arg)
        print(" ".join(quoted_cmd))
        print()
        print("[DRY-RUN] Prompt fuer Zwischenablage:")
        print("-" * 40)
        print(prompt[:200] + "..." if len(prompt) > 200 else prompt)
        return True

    # Prompt in Zwischenablage kopieren
    if copy_to_clipboard(prompt):
        print("[OK] Prompt in Zwischenablage kopiert!")
    else:
        print("[WARNUNG] Konnte Prompt nicht in Zwischenablage kopieren.")
        print("          Prompt manuell eingeben:")
        print("-" * 40)
        print(prompt)
        print("-" * 40)

    print()
    print("Starte Antigravity...")
    print()

    try:
        # Antigravity starten
        process = subprocess.Popen(cmd, cwd=str(BACH_DIR))

        print(f"[OK] Antigravity gestartet (PID: {process.pid})")
        print()
        print("=" * 60)
        print("  NAECHSTER SCHRITT:")
        print("  1. In Antigravity Chat-Fenster klicken")
        print("  2. Ctrl+V (Prompt einfuegen)")
        print("  3. Enter druecken")
        print("=" * 60)
        return True

    except FileNotFoundError:
        print("[FEHLER] 'antigravity' nicht gefunden!")
        print("         Ist Antigravity installiert und im PATH?")
        return False
    except Exception as e:
        print(f"[FEHLER] {e}")
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="BACH Gemini Starter - CLI oder GUI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Backends:
  --cli         Gemini CLI (headless, vollautomatisch)
  --gui         Antigravity (Prompt in Zwischenablage)

Beispiele CLI (vollautomatisch):
  python gemini_start.py --cli                # Auto-Modus (2 Tasks)
  python gemini_start.py --cli --bulk         # Alle Tasks (endless)
  python gemini_start.py --cli --mode analyse # Analyse-Modus

Beispiele GUI (Zwischenablage):
  python gemini_start.py --gui --bulk         # Bulk-Prompt in Clipboard
  python gemini_start.py --gui --default      # Interaktiv-Prompt
  python gemini_start.py --gui --mode analyse # Analyse-Prompt
"""
    )

    # Backend-Auswahl
    backend_group = parser.add_mutually_exclusive_group()
    backend_group.add_argument("--cli", action="store_true", help="Gemini CLI (headless, vollautomatisch)")
    backend_group.add_argument("--gui", action="store_true", help="Antigravity (Prompt in Zwischenablage)")

    # Modi
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--auto", action="store_true", help="Auto-Modus mit Stopper (nur CLI sinnvoll)")
    mode_group.add_argument("--bulk", action="store_true", help="Bulk-Modus ohne Task-Limit")
    mode_group.add_argument("--default", action="store_true", help="Interaktiv (wartet auf Anweisungen)")
    mode_group.add_argument("--individual", action="store_true", help="User-Prompt aus startprompt_gemini.txt")
    mode_group.add_argument("--mode", type=str, metavar="NAME", help="Prompt-Vorlage (analyse, research, ...)")
    mode_group.add_argument("--prompt", type=str, metavar="TEXT", help="Custom Prompt direkt angeben")

    # Optionen
    parser.add_argument("--tasks", type=int, default=2, help="Anzahl Tasks im Auto-Modus (default: 2)")
    parser.add_argument("--dry-run", action="store_true", help="Nur Befehl anzeigen")
    parser.add_argument("--list", action="store_true", help="Verfuegbare Prompt-Vorlagen auflisten")

    args = parser.parse_args()

    # Liste anzeigen
    if args.list:
        list_prompt_files()
        return

    # Modus bestimmen
    if args.prompt:
        mode = "custom"
        custom = args.prompt
    elif args.bulk:
        mode = "bulk"
        custom = None
    elif args.default:
        mode = "default"
        custom = None
    elif args.individual:
        mode = "individual"
        custom = None
    elif args.mode:
        mode = args.mode
        custom = None
    else:
        # Default: auto
        mode = "auto"
        custom = None

    # Prompt laden
    prompt, mode_display = get_prompt(mode, args.tasks, custom)

    if prompt is None:
        if mode == "individual":
            print("[FEHLER] Kein individueller Prompt in startprompt_gemini.txt definiert!")
        else:
            print(f"[FEHLER] Prompt-Vorlage '{mode}' nicht gefunden!")
            print(f"         Erwartet: {PROMPTS_DIR / f'{mode}.txt'}")
        print("         Nutze --list fuer verfuegbare Vorlagen.")
        sys.exit(1)

    # Backend bestimmen
    if args.gui:
        # GUI explizit angefordert
        success = start_gui(prompt, mode_display, args.dry_run)
    elif args.cli:
        # CLI explizit angefordert
        success = start_cli(prompt, mode_display, args.dry_run)
    else:
        # Default: Auto-Modus -> CLI, sonst GUI
        if mode == "auto":
            success = start_cli(prompt, mode_display, args.dry_run)
        else:
            # Frage nach Backend wenn keins angegeben
            print("Kein Backend angegeben. Nutze --cli oder --gui")
            print()
            print("  --cli  Gemini CLI (headless, vollautomatisch)")
            print("  --gui  Antigravity (Prompt in Zwischenablage)")
            sys.exit(1)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
