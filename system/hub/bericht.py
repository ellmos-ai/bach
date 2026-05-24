# SPDX-License-Identifier: MIT
"""
bericht.py - Foerderbericht-Handler
=====================================

CLI-Integration fuer den Report Generator.

Verwendung:
    bach bericht generate <klient-ordner> [-p passwort] [-t vorlage] [-o output]
    bach bericht export <klient-ordner> -p <passwort>
    bach bericht archive [name]
    bach bericht list
    bach bericht help

Version: 1.0.0
Erstellt: 2026-01-27
"""

import sys
from pathlib import Path
from typing import List, Tuple

from .base import BaseHandler


class BerichtHandler(BaseHandler):
    """Handler fuer Foerderbericht-Operationen."""

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.foerderplanung_dir = base_path / "user" / "documents" / "foerderplaner"
        self.klienten_dir = self.foerderplanung_dir / "klienten"
        self.templates_dir = base_path / "skills" / "_templates"
        self.generator_dir = base_path / "agents" / "_experts" / "report_generator"

    @property
    def profile_name(self) -> str:
        return "bericht"

    @property
    def target_file(self) -> Path:
        return self.foerderplanung_dir

    def get_operations(self) -> dict:
        return {
            "generate": "Bericht aus JSON generieren (fill template)",
            "export": "Bericht exportieren (de-anonymisieren)",
            "archive": "Exportierten Bericht archivieren",
            "extract": "Quelltexte aus Klienten-Ordner extrahieren",
            "prompt": "LLM-Prompt erstellen",
            "pipeline": "End-to-End Pipeline: data_roh -> fertiger Bericht",
            "list": "Klienten-Ordner auflisten",
            "status": "Status der Pipeline anzeigen",
            "help": "Hilfe anzeigen",
        }

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        """Haupteinstiegspunkt."""
        if operation == "generate":
            return self._generate(args)
        elif operation == "export":
            return self._export(args)
        elif operation == "archive":
            return self._archive(args)
        elif operation == "extract":
            return self._extract(args)
        elif operation == "prompt":
            return self._prompt(args)
        elif operation == "pipeline":
            return self._pipeline(args)
        elif operation == "list":
            return self._list(args)
        elif operation == "status":
            return self._status()
        elif operation in ("", "help"):
            return self._help()
        else:
            return False, f"Unbekannte Operation: {operation}\nNutze 'bach bericht help' fuer Hilfe."

    # ─── Operationen ───────────────────────────────────────

    def _generate(self, args: List[str]) -> Tuple[bool, str]:
        """Bericht aus JSON-Datei generieren (Word-Vorlage fuellen)."""
        if not args:
            return False, (
                "Usage: bach bericht generate <json-datei> [-t vorlage] [-o output]\n"
                "  json-datei: Pfad zur bericht_data.json\n"
                "  -t: Word-Vorlage (optional, Standard: Berichtsvorlage Geiger universal.docx)\n"
                "  -o: Ausgabedatei (erforderlich)"
            )

        json_path = args[0]
        template = None
        output = None

        i = 1
        while i < len(args):
            if args[i] in ("-t", "--template") and i + 1 < len(args):
                template = args[i + 1]
                i += 2
            elif args[i] in ("-o", "--output") and i + 1 < len(args):
                output = args[i + 1]
                i += 2
            else:
                i += 1

        if not output:
            return False, "Fehler: -o <output> ist erforderlich."

        try:
            sys.path.insert(0, str(self.base_path))
            from agents._experts.report_generator.generator import ReportGenerator

            gen = ReportGenerator()
            result = gen.generate_from_json(
                json_path=json_path,
                template_path=template,
                output_path=output
            )

            if result.success:
                return True, f"Bericht erstellt: {result.output_path}"
            else:
                return False, f"Fehler: {'; '.join(result.errors)}"
        except Exception as e:
            return False, f"Fehler bei Generierung: {e}"

    def _export(self, args: List[str]) -> Tuple[bool, str]:
        """Bericht exportieren (de-anonymisieren)."""
        if not args:
            return False, (
                "Usage: bach bericht export <klient-ordner> -p <passwort>\n"
                "  klient-ordner: z.B. klienten/K_0042\n"
                "  -p: Schluessel-Passwort"
            )

        client_folder = args[0]
        password = None

        i = 1
        while i < len(args):
            if args[i] in ("-p", "--password") and i + 1 < len(args):
                password = args[i + 1]
                i += 2
            else:
                i += 1

        if not password:
            return False, "Fehler: -p <passwort> ist erforderlich."

        try:
            sys.path.insert(0, str(self.base_path))
            from agents._experts.report_generator.generator import ExportPipeline

            pipeline = ExportPipeline(str(self.foerderplanung_dir))
            result = pipeline.export(
                client_folder=client_folder,
                password=password
            )

            if result.success:
                lines = [
                    f"Export erfolgreich!",
                    f"  Name: {result.real_name}",
                    f"  Ordner: {result.output_folder}",
                    f"  Dateien: {result.files_processed}",
                    f"  Ersetzungen: {result.replacements}",
                ]
                if result.errors:
                    lines.append(f"  Warnungen: {'; '.join(result.errors)}")
                return True, "\n".join(lines)
            else:
                return False, f"Export fehlgeschlagen: {'; '.join(result.errors)}"
        except Exception as e:
            return False, f"Fehler beim Export: {e}"

    def _archive(self, args: List[str]) -> Tuple[bool, str]:
        """Exportierten Bericht archivieren."""
        name = args[0] if args else None

        try:
            sys.path.insert(0, str(self.base_path))
            from agents._experts.report_generator.generator import ExportPipeline

            pipeline = ExportPipeline(str(self.foerderplanung_dir))
            success = pipeline.archive(client_folder="", ready_name=name)

            if success:
                return True, "Archivierung erfolgreich."
            else:
                return False, "Archivierung fehlgeschlagen (Ordner nicht gefunden?)."
        except Exception as e:
            return False, f"Fehler bei Archivierung: {e}"

    def _extract(self, args: List[str]) -> Tuple[bool, str]:
        """Quelltexte aus Klienten-Ordner extrahieren."""
        if not args:
            return False, (
                "Usage: bach bericht extract <klient-ordner> [-o output]\n"
                "  Extrahiert Text aus .docx, .txt, .pdf im Ordner."
            )

        folder = args[0]
        output = None

        i = 1
        while i < len(args):
            if args[i] in ("-o", "--output") and i + 1 < len(args):
                output = args[i + 1]
                i += 2
            else:
                i += 1

        try:
            sys.path.insert(0, str(self.base_path))
            from agents._experts.report_generator.generator import ReportGenerator

            gen = ReportGenerator()
            text = gen.extract_sources(folder)

            if output:
                Path(output).write_text(text, encoding="utf-8")
                return True, f"Extrahiert: {len(text)} Zeichen -> {output}"
            else:
                return True, f"Extrahiert: {len(text)} Zeichen\n\n{text[:500]}..."
        except Exception as e:
            return False, f"Fehler bei Extraktion: {e}"

    def _prompt(self, args: List[str]) -> Tuple[bool, str]:
        """LLM-Prompt erstellen."""
        if not args:
            return False, (
                "Usage: bach bericht prompt <klient-ordner> [-o output]\n"
                "  Erstellt den vollstaendigen LLM-Prompt."
            )

        folder = args[0]
        output = None

        i = 1
        while i < len(args):
            if args[i] in ("-o", "--output") and i + 1 < len(args):
                output = args[i + 1]
                i += 2
            else:
                i += 1

        try:
            sys.path.insert(0, str(self.base_path))
            from agents._experts.report_generator.generator import ReportGenerator

            gen = ReportGenerator()
            text = gen.extract_sources(folder)
            prompt = gen.build_prompt(text)

            if output:
                Path(output).write_text(prompt, encoding="utf-8")
                return True, f"Prompt: {len(prompt)} Zeichen -> {output}"
            else:
                return True, f"Prompt: {len(prompt)} Zeichen\n\n{prompt[:500]}..."
        except Exception as e:
            return False, f"Fehler bei Prompt-Erstellung: {e}"

    def _pipeline(self, args: List[str]) -> Tuple[bool, str]:
        """End-to-End Pipeline: data_roh -> fertiger Bericht."""
        # Name und Geburtsdatum sind jetzt optional (Auto-Detect aus Ordnername)
        client_name = None
        geburtsdatum = None
        zeitraum = "01.01.2025 - 31.12.2025"
        backend = "claude_code"
        model = "claude-sonnet-4-6"
        eltern = []
        adresse = None
        cleanup = True

        # Positionale Args: [name] [geburtsdatum] -- beide optional
        positional = []
        i = 0
        while i < len(args):
            if args[i].startswith("--"):
                if args[i] == "--zeitraum" and i + 1 < len(args):
                    zeitraum = args[i + 1]
                    i += 2
                elif args[i] == "--backend" and i + 1 < len(args):
                    backend = args[i + 1]
                    i += 2
                elif args[i] == "--model" and i + 1 < len(args):
                    model = args[i + 1]
                    i += 2
                elif args[i] == "--eltern":
                    i += 1
                    while i < len(args) and not args[i].startswith("--"):
                        eltern.append(args[i])
                        i += 1
                elif args[i] == "--adresse" and i + 1 < len(args):
                    adresse = args[i + 1]
                    i += 2
                elif args[i] == "--no-cleanup":
                    cleanup = False
                    i += 1
                else:
                    i += 1
            else:
                positional.append(args[i])
                i += 1

        if len(positional) >= 1:
            client_name = positional[0]
        if len(positional) >= 2:
            geburtsdatum = positional[1]
        # client_name und geburtsdatum bleiben None -> Auto-Detect in Pipeline

        try:
            sys.path.insert(0, str(self.base_path))
            from hub._services.document.foerderbericht_pipeline import FoerderberichtPipeline

            pipeline = FoerderberichtPipeline()
            result = pipeline.run_full_pipeline(
                client_name=client_name,
                geburtsdatum=geburtsdatum,
                berichtszeitraum=zeitraum,
                parent_names=eltern or None,
                client_address=adresse,
                llm_backend=backend,
                model=model,
                auto_cleanup=cleanup,
            )

            if result.success:
                lines = [
                    f"Pipeline erfolgreich!",
                    f"  Bericht: erstellt",
                    f"  Tarnname: {result.tarnname}",
                    f"  Dauer: {result.duration_s:.1f}s",
                    "",
                    "  Schritte:",
                ]
                for step in result.steps_completed:
                    lines.append(f"    - {step}")
                return True, "\n".join(lines)
            else:
                return False, f"Pipeline fehlgeschlagen: {result.error}"
        except Exception as e:
            return False, f"Fehler bei Pipeline: {e}"

    def _list(self, args: List[str]) -> Tuple[bool, str]:
        """Klienten-Ordner und Pipeline-Status auflisten."""
        lines = ["Klienten-Ordner:"]

        if self.klienten_dir.exists():
            for d in sorted(self.klienten_dir.iterdir()):
                if d.is_dir() and not d.name.startswith("."):
                    output_dir = d / "output"
                    has_json = any(output_dir.glob("*.json")) if output_dir.exists() else False
                    has_docx = any(output_dir.glob("*.docx")) if output_dir.exists() else False
                    status_parts = []
                    if has_json:
                        status_parts.append("JSON")
                    if has_docx:
                        status_parts.append("DOCX")
                    status = f" [{', '.join(status_parts)}]" if status_parts else ""
                    lines.append(f"  {d.name}{status}")
        else:
            lines.append("  (keine)")

        return True, "\n".join(lines)

    def _status(self) -> Tuple[bool, str]:
        """Status der gesamten Pipeline anzeigen."""
        lines = ["=== Foerderbericht Pipeline Status ===", ""]

        # Quarantine
        q_dir = self.foerderplanung_dir / "_incoming_quarantine"
        q_count = len([d for d in q_dir.iterdir() if d.is_dir()]) if q_dir.exists() else 0
        lines.append(f"Quarantine:     {q_count} Ordner")

        # Klienten
        k_count = len([d for d in self.klienten_dir.iterdir()
                       if d.is_dir() and not d.name.startswith(".")] ) if self.klienten_dir.exists() else 0
        lines.append(f"Klienten:       {k_count} Ordner")

        # Prepare
        p_dir = self.foerderplanung_dir / "_prepare_for_export"
        p_count = len([d for d in p_dir.iterdir() if d.is_dir()]) if p_dir.exists() else 0
        lines.append(f"Prepare:        {p_count} in Bearbeitung")

        # Ready
        r_dir = self.foerderplanung_dir / "_ready_for_export"
        r_count = len([d for d in r_dir.iterdir() if d.is_dir()]) if r_dir.exists() else 0
        lines.append(f"Ready:          {r_count} bereit")
        if r_count > 0:
            for d in r_dir.iterdir():
                if d.is_dir():
                    files = list(d.iterdir())
                    lines.append(f"  -> {d.name} ({len(files)} Dateien)")

        # Archive
        a_dir = self.foerderplanung_dir / "_archive"
        a_count = len([d for d in a_dir.iterdir() if d.is_dir()]) if a_dir.exists() else 0
        lines.append(f"Archiv:         {a_count} abgeschlossen")

        return True, "\n".join(lines)

    def _help(self) -> Tuple[bool, str]:
        """Hilfe anzeigen."""
        lines = [
            "BACH Foerderbericht CLI",
            "=======================",
            "",
            "Verwendung: bach bericht <operation> [args]",
            "",
            "Operationen:",
        ]
        for op, desc in self.get_operations().items():
            lines.append(f"  {op:12s}  {desc}")
        lines.extend([
            "",
            "Beispiele:",
            "  bach bericht pipeline                              # Auto-Detect (empfohlen)",
            "  bach bericht pipeline --zeitraum \"01.07.2025 - 30.06.2026\"",
            "  bach bericht pipeline \"Max Mustermann\" \"15.03.2016\"  # Explizit",
            "  bach bericht list",
            "  bach bericht status",
            "  bach bericht generate output/bericht_data.json -o output/bericht.docx",
            "  bach bericht export klienten/K_0042 -p meinpasswort",
            "",
            "Standardwege: Chat/Subagent, Desktop-.bat, llmauto Chain, CLI",
            "Name + Geburtsdatum werden automatisch aus data_roh/ erkannt.",
        ])
        return True, "\n".join(lines)
