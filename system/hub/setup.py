# SPDX-License-Identifier: MIT
"""
Setup Handler - System-Konfiguration und Installationshilfe
============================================================

bach setup mcp              MCP-Server global installieren und Claude Code konfigurieren
bach setup n8n              n8n-manager-mcp optional installieren und konfigurieren
bach setup hooks            Claude Code Hooks installieren (DB-Schutz etc.)
bach setup check             Pruefe ob alle Abhaengigkeiten konfiguriert sind
bach setup secrets           Secrets-Datei initialisieren / synchen
bach setup user              USER.md pruefen, personalisieren und mit DB synchronisieren
bach setup preflight         Pre-Flight-Checks vor Installation (Python, npm, Speicher)
bach setup prosync            Multi-System-Sync konfigurieren (ProSync)
bach setup full-install      Vollstaendige BACH-Installation in einem Durchlauf

Teil von PEANUT Release: MCP-Server aus Repo entfernt, stattdessen via npm installieren.
B37: Optionale MCP-Server (n8n-manager-mcp) separat installierbar.
"""
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import shutil
import sys
from datetime import datetime
from pathlib import Path
from .base import BaseHandler


class SetupHandler(BaseHandler):
    """Handler fuer System-Setup und Konfiguration."""

    MCP_PACKAGE_PATTERN = re.compile(r"^(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$")

    CORE_MCP_PACKAGES = [
        "ellmos-codecommander-mcp",
        "ellmos-filecommander-mcp",
    ]

    CORE_MCP_SERVER_CONFIGS = {
        "bach-codecommander": {
            "command": "npx",
            "args": ["ellmos-codecommander-mcp"]
        },
        "bach-filecommander": {
            "command": "npx",
            "args": ["ellmos-filecommander-mcp"]
        },
    }

    MCP_PACKAGE_ALLOWLIST = {
        "ellmos-codecommander-mcp",
        "ellmos-filecommander-mcp",
        "n8n-manager-mcp",
    }

    MCP_LOCAL_SCAN_SUFFIXES = (
        ".py", ".js", ".ts", ".mjs", ".cjs",
        ".sh", ".ps1", ".json", ".md", ".txt", ".yaml", ".yml",
    )

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self._npm_global_root_cache: Path | None | bool = False

    @property
    def profile_name(self) -> str:
        return "setup"

    @property
    def target_file(self) -> Path:
        return self.base_path / "hub" / "setup.py"

    # Optionale MCP-Server (nicht im Kern-Setup, separat installierbar)
    OPTIONAL_MCP_PACKAGES = {
        "n8n-manager-mcp": {
            "name": "n8n-manager",
            "config": {
                "command": "npx",
                "args": ["n8n-manager-mcp"]
            },
            "description": "n8n Workflow Manager MCP-Server",
        },
    }

    # Claude Code Hooks die bei Installation eingerichtet werden
    CLAUDE_HOOKS = {
        "PreToolUse": [
            {
                "matcher": "Bash",
                "hooks": [
                    {
                        "type": "command",
                        "command": "bash ~/.claude/hooks/bach-db-guard.sh",
                        "timeout": 5000,
                        "statusMessage": "BACH DB-Schutz prueft...",
                    }
                ],
            }
        ],
    }

    # Hook-Dateien die kopiert werden (relativ zu system/)
    HOOK_FILES = [
        "hooks/bach-db-guard.sh",
    ]

    def get_operations(self) -> dict:
        return {
            "mcp": "MCP-Server global installieren und Claude Code konfigurieren",
            "n8n": "n8n-manager-mcp optional installieren und konfigurieren",
            "hooks": "Claude Code Hooks installieren (DB-Schutz etc.)",
            "hooks-remove": "Claude Code Hooks entfernen (reversibel)",
            "check": "Pruefe ob alle Abhaengigkeiten konfiguriert sind",
            "secrets": "Secrets-Datei initialisieren / synchen",
            "user": "USER.md pruefen, personalisieren und mit DB synchronisieren",
            "prosync": "Multi-System-Sync konfigurieren (--multi-system / --single-system)",
            "preflight": "Pre-Flight-Checks vor Installation (Python, npm, Speicher)",
            "full-install": "Vollstaendige BACH-Installation in einem Durchlauf",
            "lang": "Root-Dokumente auf Sprache umschalten (de/en) [TOWER_OF_BABEL]",
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation == "mcp":
            return self._setup_mcp(dry_run)
        elif operation == "n8n":
            return self._setup_n8n(dry_run)
        elif operation == "hooks":
            return self._setup_hooks(dry_run)
        elif operation == "hooks-remove":
            return self._remove_hooks(dry_run)
        elif operation == "check":
            return self._check()
        elif operation == "secrets":
            return self._setup_secrets()
        elif operation == "user":
            return self._setup_user()
        elif operation == "prosync":
            return self._setup_prosync(args)
        elif operation == "preflight":
            return self._preflight(args)
        elif operation == "full-install":
            return self._full_install(args)
        elif operation == "lang":
            lang = args[0] if args else None
            return self._swap_doc_language(lang)
        elif operation is None or operation == "":
            return self._check()
        else:
            ops = ", ".join(self.get_operations().keys())
            return False, f"Unbekannte Operation: {operation}\n\nVerfuegbar: {ops}"

    def _setup_mcp(self, dry_run: bool = False) -> tuple:
        """Installiert MCP-Server via npm und konfiguriert Claude Code."""
        results = []
        errors = []

        # 1. Pruefen ob npm verfuegbar ist
        npm_path = self._resolve_npm_executable()
        if not npm_path:
            return False, (
                "npm nicht gefunden. Bitte Node.js installieren:\n"
                "  https://nodejs.org/\n"
                "Nach der Installation Terminal neu starten und erneut ausfuehren."
            )

        # 2. MCP-Server installieren
        packages = list(self.CORE_MCP_PACKAGES)
        ok, validation_errors = self._validate_mcp_install_plan(
            packages,
            self.CORE_MCP_SERVER_CONFIGS,
        )
        if not ok:
            return False, self._format_mcp_validation_error(validation_errors)

        results.append("=== MCP-Server Installation ===\n")

        for pkg in packages:
            if dry_run:
                results.append(f"  [DRY-RUN] npm install -g {pkg}")
                continue

            results.append(f"  Installiere {pkg}...")
            try:
                proc = subprocess.run(
                    [npm_path, "install", "-g", pkg],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120
                )
                if proc.returncode == 0:
                    results.append(f"  [OK] {pkg} installiert")
                else:
                    errors.append(f"  [FEHLER] {pkg}: {proc.stderr.strip()}")
            except subprocess.TimeoutExpired:
                errors.append(f"  [TIMEOUT] {pkg}: Installation dauerte zu lange")
            except Exception as e:
                errors.append(f"  [FEHLER] {pkg}: {e}")

        # 3. Claude Code MCP-Config aktualisieren
        results.append("\n=== Claude Code Konfiguration ===\n")
        config_ok, config_result = self._configure_claude_mcp(packages, dry_run)
        results.append(config_result)
        if not config_ok:
            errors.append(config_result)

        # Hinweis auf optionale MCP-Server
        if self.OPTIONAL_MCP_PACKAGES:
            results.append("\n=== Optionale MCP-Server ===\n")
            for pkg, info in self.OPTIONAL_MCP_PACKAGES.items():
                installed = self._is_npm_package_installed(pkg)
                status_str = "[OK] installiert" if installed else "[--] nicht installiert"
                results.append(f"  {pkg}: {status_str}")
            results.append(f"\n  Installieren mit: bach setup n8n")

        # Ergebnis
        output = "\n".join(results)
        if errors:
            output += "\n\nFehler:\n" + "\n".join(errors)
            return False, output

        return True, output

    def _configure_claude_mcp(self, packages: list, dry_run: bool) -> tuple:
        """Aktualisiert die Claude Code MCP-Konfiguration."""
        # Claude Code config: ~/.claude.json oder ~/.claude/mcp.json
        claude_config = Path.home() / ".claude.json"

        if not claude_config.exists():
            # Alternativ: ~/.claude/mcp.json
            alt_config = Path.home() / ".claude" / "mcp.json"
            if alt_config.exists():
                claude_config = alt_config
            else:
                return True, (
                    "  Claude Code Config nicht gefunden.\n"
                    "  Manuell konfigurieren mit:\n"
                    "    claude mcp add --scope user bach-codecommander -- npx ellmos-codecommander-mcp\n"
                    "    claude mcp add --scope user bach-filecommander -- npx ellmos-filecommander-mcp"
                )

        if dry_run:
            return True, f"  [DRY-RUN] Wuerde {claude_config} aktualisieren"

        ok, config, error = self._load_json_object_config(
            claude_config,
            "Claude Code Config",
            allow_missing=True,
        )
        if not ok:
            return False, error

        # mcpServers-Sektion sicherstellen
        if "mcpServers" not in config:
            config["mcpServers"] = {}
        elif not isinstance(config["mcpServers"], dict):
            return False, "Claude Code Config blockiert: 'mcpServers' muss ein Objekt sein."

        # Server-Eintraege hinzufuegen/aktualisieren
        server_configs = self.CORE_MCP_SERVER_CONFIGS
        scan_configs = dict(config["mcpServers"])
        scan_configs.update(server_configs)
        scan_ok, blocking_findings, warning_findings = self._scan_mcp_config_paths(scan_configs)
        if not scan_ok:
            return False, self._format_mcp_scan_error(blocking_findings)

        updated = []
        for name, conf in server_configs.items():
            if name not in config["mcpServers"]:
                config["mcpServers"][name] = conf
                updated.append(f"  [NEU] {name} hinzugefuegt")
            else:
                updated.append(f"  [OK] {name} bereits konfiguriert")

        # Config speichern
        claude_config.write_text(
            json.dumps(config, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

        if warning_findings:
            updated.append(f"  Scan-Warnungen: {len(warning_findings)}")
            for warning in warning_findings[:5]:
                updated.append(f"    - {warning}")

        return True, "\n".join(updated) + f"\n  Config: {claude_config}"

    def _check(self) -> tuple:
        """Prueft ob alle Abhaengigkeiten konfiguriert sind."""
        checks = []
        all_ok = True

        # 1. npm
        npm_path = self._resolve_npm_executable()
        if npm_path:
            checks.append("[OK] npm verfuegbar")
        else:
            checks.append("[!!] npm nicht gefunden")
            all_ok = False

        # 2. MCP-Server
        npm_root = self._get_npm_global_root()
        for pkg in self.CORE_MCP_PACKAGES:
            package_path = self._get_npm_package_path(pkg)
            local_repo_path = self._get_local_mcp_repo_path(pkg)
            if package_path and package_path.exists():
                checks.append(f"[OK] {pkg} installiert")
            elif local_repo_path:
                checks.append(f"[OK] {pkg} lokale Arbeitskopie erkannt")
            elif npm_root is None:
                checks.append(f"[??] {pkg} konnte nicht geprueft werden")
                all_ok = False
            else:
                checks.append(f"[!!] {pkg} nicht installiert")
                all_ok = False

        # 3. Secrets-Datei
        secrets_file = Path.home() / ".bach" / "bach_secrets.json"
        if secrets_file.exists():
            try:
                data = json.loads(secrets_file.read_text(encoding="utf-8"))
                count = len(data.get("secrets", {}))
                checks.append(f"[OK] Secrets-Datei vorhanden ({count} Keys)")
            except Exception:
                checks.append("[!!] Secrets-Datei defekt")
                all_ok = False
        else:
            checks.append("[!!] Secrets-Datei fehlt (~/.bach/bach_secrets.json)")
            all_ok = False

        # 4. bach.db
        db_path = self._canonical_db
        if db_path.exists():
            checks.append("[OK] bach.db vorhanden")
        else:
            checks.append("[!!] bach.db fehlt")
            all_ok = False

        # 5. Python-Runtime
        if importlib.util.find_spec("psutil") is not None:
            checks.append("[OK] Python-Modul psutil verfuegbar")
        else:
            checks.append("[!!] Python-Modul psutil fehlt (Scheduler-/GUI-Runtime unvollstaendig; pip install -r requirements.txt)")
            all_ok = False

        # 6. Optionale MCP-Server (nur Info, kein Fehler wenn nicht installiert)
        for pkg, info in self.OPTIONAL_MCP_PACKAGES.items():
            package_path = self._get_npm_package_path(pkg)
            local_repo_path = self._get_local_mcp_repo_path(pkg)
            if package_path and package_path.exists():
                checks.append(f"[OK] {pkg} installiert (optional)")
            elif local_repo_path:
                checks.append(f"[OK] {pkg} lokale Arbeitskopie erkannt (optional)")
            else:
                checks.append(f"[--] {pkg} nicht installiert (optional, bach setup n8n)")

        # 7. USER.md
        user_md = self.base_path.parent / "USER.md"
        if user_md.exists():
            content = user_md.read_text(encoding="utf-8")
            if "TEMPLATE" in content:
                checks.append("[!!] USER.md existiert, aber noch nicht personalisiert (TEMPLATE)")
                all_ok = False
            else:
                checks.append("[OK] USER.md vorhanden und personalisiert")
        else:
            checks.append("[!!] USER.md fehlt")
            all_ok = False

        status = "Alles OK" if all_ok else "Einige Checks fehlgeschlagen"
        output = f"=== BACH Setup Check ===\n\n" + "\n".join(checks) + f"\n\nStatus: {status}"

        return all_ok, output

    # =========================================================================
    # Non-interaktiver Installer (preflight + full-install)
    # =========================================================================

    def _preflight(self, args):
        """Pre-Flight-Checks vor Installation."""
        import sys
        import os
        checks = []

        # Python-Version
        py_ok = sys.version_info >= (3, 10)
        checks.append((
            "Python >= 3.10", py_ok,
            f"{sys.version_info.major}.{sys.version_info.minor}"
        ))

        # npm verfuegbar
        npm_path = shutil.which("npm")
        checks.append((
            "npm verfuegbar", npm_path is not None,
            str(npm_path or "nicht gefunden")
        ))

        # DB-Verzeichnis beschreibbar
        db_dir = self.base_path / "data"
        db_dir.mkdir(parents=True, exist_ok=True)
        db_writable = os.access(str(db_dir), os.W_OK)
        checks.append(("data/ beschreibbar", db_writable, str(db_dir)))

        # Speicherplatz (>100MB frei)
        usage = shutil.disk_usage(str(self.base_path))
        free_mb = usage.free / (1024 * 1024)
        checks.append((
            "Speicher > 100MB", free_mb > 100,
            f"{free_mb:.0f} MB frei"
        ))

        out = ["Pre-Flight Checks:"]
        all_ok = True
        for name, ok, detail in checks:
            status = "OK" if ok else "FAIL"
            out.append(f"  [{status}] {name}: {detail}")
            if not ok:
                all_ok = False

        return all_ok, "\n".join(out)

    # =========================================================================
    # Claude Code Hooks Setup
    # =========================================================================

    def _setup_hooks(self, dry_run: bool = False) -> tuple:
        """Installiert Claude Code Hooks (DB-Schutz etc.) in ~/.claude/.

        - Kopiert Hook-Scripts nach ~/.claude/hooks/
        - Merged Hook-Konfiguration in ~/.claude/settings.json
        - Nicht-destruktiv: bestehende Hooks bleiben erhalten
        """
        import os
        import stat

        settings_path = Path(os.path.expanduser("~/.claude/settings.json"))
        hooks_dir = Path(os.path.expanduser("~/.claude/hooks"))
        out = []
        ok, settings, error = self._load_json_object_config(
            settings_path,
            "Claude Hook settings",
            allow_missing=True,
        )
        if not ok:
            return False, error
        if "hooks" in settings and not isinstance(settings["hooks"], dict):
            return False, "Claude Hook settings blockiert: 'hooks' muss ein Objekt sein."

        # --- 1. Hook-Scripts kopieren ---
        hooks_dir.mkdir(parents=True, exist_ok=True)
        source_dir = self.base_path / "hooks"

        for hook_file in self.HOOK_FILES:
            src = self.base_path / hook_file
            dst = hooks_dir / Path(hook_file).name

            if not src.exists():
                out.append(f"  [SKIP] {hook_file} nicht gefunden in {source_dir}")
                continue

            if dry_run:
                out.append(f"  [DRY] Wuerde kopieren: {src} -> {dst}")
                continue

            # Kopieren (ueberschreibt bei Update)
            shutil.copy2(str(src), str(dst))
            # Ausfuehrbar machen
            dst.chmod(dst.stat().st_mode | stat.S_IEXEC)
            out.append(f"  [OK] {dst.name} installiert")

        # --- 2. Hook-Config in settings.json mergen ---
        if dry_run:
            out.append("  [DRY] Wuerde Hooks in settings.json mergen")
            return True, "\n".join(["Claude Code Hooks (dry-run):"] + out)

        # Hooks mergen (nicht ueberschreiben, nur fehlende hinzufuegen)
        if "hooks" not in settings:
            settings["hooks"] = {}

        hooks_config = settings["hooks"]
        added = 0

        for event_name, event_hooks in self.CLAUDE_HOOKS.items():
            if event_name not in hooks_config:
                hooks_config[event_name] = event_hooks
                added += len(event_hooks)
                out.append(f"  [OK] {event_name}: {len(event_hooks)} Hook(s) hinzugefuegt")
            else:
                # Pruefen ob unser Hook schon drin ist (nach command-String)
                existing_commands = set()
                for matcher_block in hooks_config[event_name]:
                    for h in matcher_block.get("hooks", []):
                        cmd = h.get("command", "")
                        if cmd:
                            existing_commands.add(cmd)

                for new_block in event_hooks:
                    for h in new_block.get("hooks", []):
                        cmd = h.get("command", "")
                        if cmd and cmd not in existing_commands:
                            hooks_config[event_name].append(new_block)
                            added += 1
                            out.append(f"  [OK] {event_name}: Hook hinzugefuegt")
                            break
                    else:
                        out.append(f"  [SKIP] {event_name}: Hook bereits vorhanden")

        # Settings schreiben
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        summary = f"Claude Code Hooks: {added} neu installiert"
        return True, "\n".join([summary] + out)

    def _remove_hooks(self, dry_run: bool = False) -> tuple:
        """Entfernt BACH Claude Code Hooks aus ~/.claude/ (reversibel).

        - Loescht Hook-Scripts aus ~/.claude/hooks/
        - Entfernt BACH-Hook-Eintraege aus ~/.claude/settings.json
        - Laesst andere (nicht-BACH) Hooks unangetastet
        """
        import os

        settings_path = Path(os.path.expanduser("~/.claude/settings.json"))
        hooks_dir = Path(os.path.expanduser("~/.claude/hooks"))
        out = []

        # --- 1. Hook-Scripts entfernen ---
        removed_files = 0
        for hook_file in self.HOOK_FILES:
            dst = hooks_dir / Path(hook_file).name
            if dst.exists():
                if dry_run:
                    out.append(f"  [DRY] Wuerde loeschen: {dst}")
                else:
                    dst.unlink()
                    out.append(f"  [OK] {dst.name} entfernt")
                removed_files += 1
            else:
                out.append(f"  [SKIP] {dst.name} nicht vorhanden")

        # --- 2. Hook-Config aus settings.json entfernen ---
        removed_hooks = 0
        if settings_path.exists():
            ok, settings, error = self._load_json_object_config(
                settings_path,
                "Claude Hook settings",
                allow_missing=True,
            )
            if not ok:
                return False, error
            if "hooks" in settings and not isinstance(settings["hooks"], dict):
                return False, "Claude Hook settings blockiert: 'hooks' muss ein Objekt sein."

            hooks_config = settings.get("hooks", {})

            # BACH-Hook-Commands sammeln
            bach_commands = set()
            for event_hooks in self.CLAUDE_HOOKS.values():
                for block in event_hooks:
                    for h in block.get("hooks", []):
                        cmd = h.get("command", "")
                        if cmd:
                            bach_commands.add(cmd)

            # Aus settings entfernen
            for event_name in list(hooks_config.keys()):
                original_len = len(hooks_config[event_name])
                hooks_config[event_name] = [
                    block for block in hooks_config[event_name]
                    if not any(
                        h.get("command", "") in bach_commands
                        for h in block.get("hooks", [])
                    )
                ]
                diff = original_len - len(hooks_config[event_name])
                if diff > 0:
                    removed_hooks += diff
                    out.append(f"  [OK] {event_name}: {diff} BACH-Hook(s) entfernt")

                # Leere Event-Listen aufraeumen
                if not hooks_config[event_name]:
                    del hooks_config[event_name]

            if not hooks_config:
                settings.pop("hooks", None)

            if not dry_run:
                settings_path.write_text(
                    json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )

        summary = f"Claude Code Hooks entfernt: {removed_files} Dateien, {removed_hooks} Config-Eintraege"
        return True, "\n".join([summary] + out)

    def _full_install(self, args):
        """Vollstaendige BACH-Installation in einem Durchlauf.

        Options:
            --config <file>   JSON config file
            --lang <code>     Set system language (de/en/es/ru/ja/zh)
            --with-n8n        Install n8n integration
        """
        config = {}
        # --config flag parsen
        if "--config" in args:
            idx = args.index("--config")
            if idx + 1 < len(args):
                config_path = Path(args[idx + 1])
                if config_path.exists():
                    config = json.loads(config_path.read_text(encoding="utf-8"))
                else:
                    return False, f"Config-Datei nicht gefunden: {config_path}"

        # --lang flag parsen
        install_lang = config.get("language", None)
        if "--lang" in args:
            idx = args.index("--lang")
            if idx + 1 < len(args):
                install_lang = args[idx + 1].strip().lower()

        results = []
        steps = [
            ("Pre-Flight Check", self._preflight),
            ("ProSync", lambda a, _a=list(args): self._setup_prosync(_a, config=config)),
            ("MCP-Server", lambda a: self._setup_mcp()),
            ("Claude Code Hooks", lambda a: self._setup_hooks()),
            ("Secrets", lambda a: self._setup_secrets()),
            ("User-Profil", lambda a: self._setup_user()),
        ]

        # Optional: Language
        if install_lang:
            steps.append(("Sprache", lambda a, _l=install_lang: self._swap_doc_language(_l)))
            steps.append(("Help-Docs", lambda a, _l=install_lang: self._generate_help_docs(_l)))

        # Optional: n8n
        if config.get("install_n8n", False) or "--with-n8n" in args:
            steps.insert(2, ("n8n Manager", lambda a: self._setup_n8n()))

        out = []
        out.append("=== BACH Full Install ===\n")

        for name, step_fn in steps:
            out.append(f"[...] {name}")
            try:
                ok, msg = step_fn([])
                status = "OK" if ok else "FEHLER"
                results.append((name, ok, msg))
                out.append(f"  [{status}] {name}: {msg[:100]}")
            except Exception as e:
                results.append((name, False, str(e)))
                out.append(f"  [FEHLER] {name}: {e}")

        # Abschluss-Check
        ok_check, msg_check = self._check()
        results.append(("Validierung", ok_check, msg_check))

        # Report
        passed = sum(1 for _, ok, _ in results if ok)
        total = len(results)
        out.append(f"\n=== Ergebnis: {passed}/{total} Schritte erfolgreich ===")

        if passed < total:
            failed = [name for name, ok, _ in results if not ok]
            out.append(f"Fehlgeschlagen: {', '.join(failed)}")

        return passed == total, "\n".join(out)

    # =========================================================================
    # ProSync Setup (Multi-System DB-Sync)
    # =========================================================================

    def _setup_prosync(self, args=None, config=None) -> tuple:
        """Konfiguriert ProSync fuer Multi-System-Nutzung.

        Flags:
            --multi-system    Aktiviert DB-Sync (BACH auf mehreren Rechnern)
            --single-system   Deaktiviert DB-Sync (BACH nur auf diesem Rechner)
        Config JSON:
            "multi_system": true/false
        Ohne Angabe: Prüft bestehende Konfiguration, Default = single-system.
        """
        if args is None:
            args = []
        if config is None:
            config = {}

        flag_file = self.base_path / "data" / "config" / "db_sync_enabled"
        currently_enabled = flag_file.exists()
        out = ["=== ProSync Setup ===\n"]

        explicit_multi = "--multi-system" in args or config.get("multi_system") is True
        explicit_single = "--single-system" in args or config.get("multi_system") is False

        if explicit_multi:
            flag_file.parent.mkdir(parents=True, exist_ok=True)
            flag_file.write_text("enabled", encoding="utf-8")
            out.append("  [OK] ProSync aktiviert (Multi-System-Modus)")
            out.append("  DB-Sync wird bei nächstem Start wirksam.")
            out.append("  Nutze 'bach db sync' für manuellen Sync.")
            return True, "\n".join(out)

        if explicit_single:
            if currently_enabled:
                flag_file.unlink()
                out.append("  [OK] ProSync deaktiviert (Single-System-Modus)")
            else:
                out.append("  [OK] ProSync war bereits deaktiviert")
            out.append("  Keine DB-Synchronisation zwischen Systemen.")
            return True, "\n".join(out)

        if currently_enabled:
            out.append("  ProSync ist aktiv (Multi-System-Modus)")
            out.append("  Ändern: bach setup prosync --single-system")
        else:
            out.append("  ProSync ist nicht aktiv (Single-System-Modus)")
            out.append("  Nutzt du BACH auf mehreren Rechnern?")
            out.append("  Aktivieren: bach setup prosync --multi-system")

        return True, "\n".join(out)

    # =========================================================================
    # USER.md Setup (B34)
    # =========================================================================

    def _setup_user(self) -> tuple:
        """Prueft USER.md, personalisiert aus DB oder synct zurueck in DB.

        Logik:
          1. USER.md existiert nicht -> Fehler mit Hinweis
          2. USER.md ist noch TEMPLATE (enthaelt "TEMPLATE" Marker):
             -> Lese DB (assistant_user_profile), fuelle USER.md mit echten Daten
          3. USER.md ist bereits personalisiert (kein TEMPLATE Marker):
             -> Parse USER.md und sync relevante Felder in die DB
        """
        user_md = self.base_path.parent / "USER.md"
        db_path = self._canonical_db
        results = ["=== USER.md Setup ===\n"]

        # 1. Existenz-Check
        if not user_md.exists():
            return False, (
                "USER.md nicht gefunden.\n"
                f"Erwartet: {user_md}\n"
                "Bitte USER.md aus dem Template wiederherstellen."
            )

        content = user_md.read_text(encoding="utf-8")
        is_template = "TEMPLATE" in content

        if is_template:
            # --- TEMPLATE -> Personalisieren aus DB ---
            results.append("  USER.md ist noch ein Template. Personalisiere aus DB...\n")

            if not db_path.exists():
                results.append("  [WARN] bach.db nicht gefunden - kann nicht aus DB personalisieren.")
                return False, "\n".join(results)

            # DB-Profil laden
            db_data = self._load_user_profile_from_db(db_path)

            if not db_data:
                results.append("  [WARN] Keine Profil-Daten in DB gefunden.")
                results.append("  USER.md bleibt als Template. Nutze 'bach profile edit' um Daten zu setzen.")
                return True, "\n".join(results)

            # USER.md mit DB-Daten fuellen
            new_content = self._personalize_user_md(content, db_data)
            user_md.write_text(new_content, encoding="utf-8")

            count = sum(len(v) if isinstance(v, (dict, list)) else 1 for v in db_data.values())
            results.append(f"  [OK] USER.md personalisiert ({count} Felder aus DB)")
            results.append("  TEMPLATE-Marker entfernt.")

        else:
            # --- Personalisiert -> Sync zurueck in DB ---
            results.append("  USER.md ist bereits personalisiert. Sync in DB...\n")

            if not db_path.exists():
                results.append("  [WARN] bach.db nicht gefunden - kann nicht in DB synchen.")
                return False, "\n".join(results)

            # USER.md parsen und in DB schreiben
            parsed = self._parse_user_md(content)
            synced = self._sync_user_md_to_db(parsed, db_path)

            results.append(f"  [OK] {synced} Eintraege in DB synchronisiert")

        # Sync-Timestamp in USER.md aktualisieren
        try:
            current_content = user_md.read_text(encoding="utf-8")
            today = datetime.now().strftime("%Y-%m-%d")
            direction = "DB -> USER.md" if is_template else "USER.md -> DB"
            updated = re.sub(
                r"\*\*Last Updated:\*\*.*",
                f"**Last Updated:** {today}",
                current_content,
            )
            updated = re.sub(
                r"\*\*Sync Source:\*\*.*",
                f"**Sync Source:** {direction} (setup user)",
                updated,
            )
            user_md.write_text(updated, encoding="utf-8")
            results.append(f"  Sync-Timestamp aktualisiert: {today}")
        except Exception as e:
            results.append(f"  [WARN] Timestamp-Update fehlgeschlagen: {e}")

        # Templates zu echten Dateien kopieren (falls .md fehlt)
        init_results = self._init_from_templates()
        if init_results:
            results.append("")
            results.extend(init_results)

        # Template-Dateien aufraeumen (nach Personalisierung)
        cleanup_results = self._cleanup_templates()
        if cleanup_results:
            results.append("")
            results.extend(cleanup_results)

        return True, "\n".join(results)

    def _init_from_templates(self) -> list:
        """Erstellt fehlende .md Dateien aus .template.md Vorlagen.

        Wird vor _cleanup_templates() aufgerufen. Kopiert nur wenn die
        echte .md noch nicht existiert (erster Start nach git clone).
        Handles both *.template.md (EN) and *.template.de.md (DE).
        """
        import shutil
        root = self.base_path.parent  # BACH/
        created = []

        for template in root.glob("*.template.md"):
            real_file = root / template.name.replace(".template.md", ".md")
            if not real_file.exists():
                try:
                    shutil.copy2(template, real_file)
                    created.append(f"  [INIT] {real_file.name} aus Template erstellt")
                except OSError:
                    created.append(f"  [WARN] Konnte {real_file.name} nicht erstellen")

        return created

    def _cleanup_templates(self) -> list:
        """Loescht .template.md und .template.de.md Dateien wenn die echte .md existiert.

        Templates bleiben in Git getrackt (fuer neue Installationen), werden
        aber lokal geloescht sobald die personalisierten Dateien existieren.
        """
        root = self.base_path.parent  # BACH/
        cleaned = []

        for template in root.glob("*.template*.md"):
            name = template.name
            if ".template.de.md" in name:
                real_file = root / name.replace(".template.de.md", ".md")
            elif ".template.md" in name:
                real_file = root / name.replace(".template.md", ".md")
            else:
                continue
            if real_file.exists():
                try:
                    template.unlink()
                    cleaned.append(f"  [OK] Template entfernt: {template.name}")
                except OSError:
                    cleaned.append(f"  [WARN] Konnte {template.name} nicht entfernen")

        return cleaned

    def _load_user_profile_from_db(self, db_path: Path) -> dict:
        """Laedt Profildaten aus assistant_user_profile fuer USER.md-Personalisierung.

        Returns:
            Dict mit Kategorien: {
                'stats': {key: value, ...},
                'traits': {key: value, ...},
                'values': [value, ...],
                'preferences': {key: value, ...},
                'goals': {key: value, ...},
            }
        """
        conn = None
        try:
            conn = sqlite3.connect(str(db_path))
            rows = conn.execute(
                "SELECT category, key, value FROM assistant_user_profile ORDER BY category, key"
            ).fetchall()
        except Exception:
            return {}
        finally:
            if conn:
                conn.close()

        data = {
            "stats": {},
            "traits": {},
            "values": [],
            "preferences": {},
            "goals": {},
        }

        for category, key, value in rows:
            if category == "stat":
                data["stats"][key] = value
            elif category == "trait":
                data["traits"][key] = value
            elif category == "value":
                data["values"].append(value)
            elif category == "preference":
                data["preferences"][key] = value
            elif category == "goal":
                data["goals"][key] = value

        return data

    def _personalize_user_md(self, template: str, db_data: dict) -> str:
        """Ersetzt Template-Platzhalter in USER.md mit echten DB-Daten.

        Strategie: Gezielte Ersetzungen in den bekannten Sektionen.
        Entfernt den TEMPLATE-Marker am Ende.
        """
        content = template
        stats = db_data.get("stats", {})
        traits = db_data.get("traits", {})
        values = db_data.get("values", [])
        goals = db_data.get("goals", {})

        # Basic Information
        if stats.get("name"):
            content = re.sub(
                r"\*\*Name:\*\*\s*.*",
                f"**Name:** {stats['name']}",
                content,
            )
        if stats.get("role"):
            content = re.sub(
                r"\*\*Role:\*\*\s*.*",
                f"**Role:** {stats['role']}",
                content,
            )
        if stats.get("language"):
            # Nur im Basic-Info-Block (erste Occurrence)
            content = re.sub(
                r"(\*\*Language:\*\*)\s*\w+",
                rf"\1 {stats['language']}",
                content,
                count=1,
            )
        if stats.get("timezone"):
            content = re.sub(
                r"\*\*Timezone:\*\*\s*.*",
                f"**Timezone:** {stats['timezone']}",
                content,
            )
        if stats.get("os"):
            content = re.sub(
                r"\*\*Operating System:\*\*\s*.*",
                f"**Operating System:** {stats['os']}",
                content,
            )

        # Communication Traits
        if traits.get("communication_style"):
            content = re.sub(
                r"\*\*Communication Style:\*\*\s*.*",
                f"**Communication Style:** {traits['communication_style']}",
                content,
            )
        if traits.get("detail_preference"):
            content = re.sub(
                r"\*\*Detail Preference:\*\*\s*.*",
                f"**Detail Preference:** {traits['detail_preference']}",
                content,
            )
        if traits.get("technical_depth"):
            content = re.sub(
                r"\*\*Technical Depth:\*\*\s*.*",
                f"**Technical Depth:** {traits['technical_depth']}",
                content,
            )

        # Core Values - ersetze die bestehende Liste
        if values:
            values_section = "\n".join(f"- {v}" for v in values)
            content = re.sub(
                r"(## .* Core Values\n\n)((?:- .*\n?)*)",
                rf"\g<1>{values_section}\n",
                content,
            )

        # Goals - short_term und long_term
        short_goals = [v for k, v in sorted(goals.items()) if k.startswith("short_term")]
        long_goals = [v for k, v in sorted(goals.items()) if k.startswith("long_term")]

        if short_goals:
            short_section = "\n".join(f"- {g}" for g in short_goals)
            content = re.sub(
                r"(### Short-term\n)((?:- .*\n?)*)",
                rf"\g<1>{short_section}\n",
                content,
            )
        if long_goals:
            long_section = "\n".join(f"- {g}" for g in long_goals)
            content = re.sub(
                r"(### Long-term\n)((?:- .*\n?)*)",
                rf"\g<1>{long_section}\n",
                content,
            )

        # TEMPLATE-Marker entfernen
        content = content.replace(
            "<!-- BACH-INTERNAL-MARKER: dist_type=1 TEMPLATE -->",
            "<!-- BACH-INTERNAL-MARKER: dist_type=1 PERSONALIZED -->",
        )
        content = re.sub(
            r"> \*\*Type:\*\* TEMPLATE.*",
            "> **Type:** PERSONALIZED (dist_type=1) -- customized from DB.",
            content,
        )

        return content

    def _parse_user_md(self, content: str) -> dict:
        """Parst eine personalisierte USER.md und extrahiert Profil-Daten.

        Returns:
            Dict mit Kategorien analog zu _load_user_profile_from_db()
        """
        data = {
            "stats": {},
            "traits": {},
            "values": [],
            "preferences": {},
            "goals_short": [],
            "goals_long": [],
        }

        # Basic Information
        m = re.search(r"\*\*Name:\*\*\s*(.+)", content)
        if m and m.group(1).strip() != "User":
            data["stats"]["name"] = m.group(1).strip()

        m = re.search(r"\*\*Role:\*\*\s*(.+)", content)
        if m:
            data["stats"]["role"] = m.group(1).strip()

        # Language im Basic-Info-Block (nicht im Coding-Block)
        m = re.search(r"Basic Information.*?\*\*Language:\*\*\s*(\w+)", content, re.DOTALL)
        if m:
            data["stats"]["language"] = m.group(1).strip()

        m = re.search(r"\*\*Timezone:\*\*\s*(.+)", content)
        if m:
            data["stats"]["timezone"] = m.group(1).strip()

        m = re.search(r"\*\*Operating System:\*\*\s*(.+)", content)
        if m:
            data["stats"]["os"] = m.group(1).strip()

        # Communication Traits
        m = re.search(r"\*\*Communication Style:\*\*\s*(.+)", content)
        if m:
            data["traits"]["communication_style"] = m.group(1).strip()

        m = re.search(r"\*\*Detail Preference:\*\*\s*(.+)", content)
        if m:
            data["traits"]["detail_preference"] = m.group(1).strip()

        m = re.search(r"\*\*Technical Depth:\*\*\s*(.+)", content)
        if m:
            data["traits"]["technical_depth"] = m.group(1).strip()

        # Core Values (Bullets nach "Core Values" Heading)
        values_match = re.search(
            r"## .* Core Values\n\n((?:- .+\n?)+)", content
        )
        if values_match:
            for line in values_match.group(1).strip().split("\n"):
                val = line.lstrip("- ").strip()
                if val:
                    data["values"].append(val)

        # Goals
        short_match = re.search(r"### Short-term\n((?:- .+\n?)+)", content)
        if short_match:
            for line in short_match.group(1).strip().split("\n"):
                g = line.lstrip("- ").strip()
                if g:
                    data["goals_short"].append(g)

        long_match = re.search(r"### Long-term\n((?:- .+\n?)+)", content)
        if long_match:
            for line in long_match.group(1).strip().split("\n"):
                g = line.lstrip("- ").strip()
                if g:
                    data["goals_long"].append(g)

        return data

    def _sync_user_md_to_db(self, parsed: dict, db_path: Path) -> int:
        """Schreibt geparste USER.md-Daten in assistant_user_profile.

        Nur sync-Eintraege werden ueberschrieben (manuell gelernte bleiben).

        Returns:
            Anzahl synchronisierter Eintraege
        """
        synced = 0
        conn = None
        try:
            conn = sqlite3.connect(str(db_path))
            now = datetime.now().isoformat()

            # Stats
            for key, value in parsed.get("stats", {}).items():
                if self._upsert_sync_row(conn, "stat", key, value, now):
                    synced += 1

            # Traits
            for key, value in parsed.get("traits", {}).items():
                if self._upsert_sync_row(conn, "trait", key, value, now):
                    synced += 1

            # Values
            for i, value in enumerate(parsed.get("values", [])):
                if self._upsert_sync_row(conn, "value", f"value_{i}", value, now):
                    synced += 1

            # Goals
            for i, goal in enumerate(parsed.get("goals_short", [])):
                if self._upsert_sync_row(conn, "goal", f"short_term_{i}", goal, now):
                    synced += 1

            for i, goal in enumerate(parsed.get("goals_long", [])):
                if self._upsert_sync_row(conn, "goal", f"long_term_{i}", goal, now):
                    synced += 1

            conn.commit()
        except Exception as e:
            print(f"[WARN] USER.md -> DB sync fehlgeschlagen: {e}")
        finally:
            if conn:
                conn.close()

        return synced

    def _upsert_sync_row(self, conn: sqlite3.Connection, category: str,
                         key: str, value: str, now: str) -> bool:
        """Insert/Update einer Zeile, aber nur wenn nicht manuell gelernt.

        Returns:
            True wenn geschrieben, False wenn uebersprungen
        """
        existing = conn.execute(
            "SELECT learned_from FROM assistant_user_profile WHERE category=? AND key=?",
            (category, key),
        ).fetchone()

        if existing and existing[0] not in ("sync", "setup-user"):
            return False

        conn.execute("""
            INSERT INTO assistant_user_profile (category, key, value, confidence, learned_from, created_at, updated_at)
            VALUES (?, ?, ?, 'hoch', 'setup-user', ?, ?)
            ON CONFLICT(category, key) DO UPDATE SET
                value = excluded.value,
                confidence = excluded.confidence,
                learned_from = excluded.learned_from,
                updated_at = excluded.updated_at
        """, (category, key, value, now, now))
        return True

    # =========================================================================
    # Language Swap (TOWER_OF_BABEL v3.7.1)
    # =========================================================================

    # Dokumente die sprachspezifische Varianten haben
    _LANG_DOCS = ["README", "QUICKSTART", "SKILLS"]

    def _swap_doc_language(self, lang: str = None) -> tuple:
        """Schaltet Root-Dokumente auf die gewaehlte Sprache um.

        Bei lang=de: README.md wird deutsch, README.en.md als EN-Backup
        Bei lang=en: README.md wird englisch (Default), README.de.md als DE-Backup
        Bei anderen bekannten Sprachen wird nur die Systemsprache gesetzt.

        Args:
            lang: Zielsprache (z.B. 'de', 'en', 'es', 'ru', 'ja', 'zh')
        """
        from .lang import KNOWN_LANGUAGE_LABELS, set_lang

        if lang:
            lang = lang.strip().lower()

        if lang not in KNOWN_LANGUAGE_LABELS:
            known = "|".join(sorted(KNOWN_LANGUAGE_LABELS))
            return False, f"Usage: bach setup lang <{known}>"

        root = self.base_path.parent  # BACH/
        results = [f"=== Dokument-Sprache: {lang.upper()} ===\n"]

        if lang in ("de", "en"):
            for doc_name in self._LANG_DOCS:
                main_file = root / f"{doc_name}.md"
                de_file = root / f"{doc_name}.de.md"
                en_file = root / f"{doc_name}.en.md"

                if lang == "de":
                    # README.md soll deutsch werden
                    if de_file.exists():
                        # Aktuelle README.md (englisch) sichern als README.en.md
                        if main_file.exists() and not en_file.exists():
                            main_file.rename(en_file)
                            results.append(f"  [OK] {doc_name}.md -> {doc_name}.en.md (EN-Backup)")
                        elif main_file.exists():
                            main_file.unlink()
                        # Deutsche Version wird Hauptdatei
                        shutil.copy2(str(de_file), str(main_file))
                        results.append(f"  [OK] {doc_name}.de.md -> {doc_name}.md (DE aktiv)")
                    else:
                        results.append(f"  [--] {doc_name}.de.md nicht vorhanden, uebersprungen")

                else:  # lang == "en"
                    # README.md soll englisch sein (Default)
                    if en_file.exists():
                        # EN-Backup zurueck als Hauptdatei
                        if main_file.exists():
                            # Aktuelle (deutsche) Version als .de.md sichern
                            if not de_file.exists():
                                shutil.copy2(str(main_file), str(de_file))
                            main_file.unlink()
                        en_file.rename(main_file)
                        results.append(f"  [OK] {doc_name}.en.md -> {doc_name}.md (EN aktiv)")
                    elif main_file.exists():
                        results.append(f"  [OK] {doc_name}.md bereits vorhanden (EN assumed)")
                    else:
                        results.append(f"  [--] Keine {doc_name}-Datei vorhanden")
        else:
            results.append(
                f"  [INFO] Keine Root-Dokumentvarianten fuer {KNOWN_LANGUAGE_LABELS[lang]} vorhanden. "
                "Es wird nur die Systemsprache gesetzt."
            )

        # Systemsprache setzen
        try:
            set_lang(lang)

            db_path = self._canonical_db
            if db_path.exists():
                conn = sqlite3.connect(str(db_path))
                try:
                    conn.execute(
                        "UPDATE languages_config SET default_language = ?, updated_at = ?",
                        (lang, datetime.now().isoformat())
                    )
                    columns = {row[1] for row in conn.execute("PRAGMA table_info(languages_config)").fetchall()}
                    if "enabled_languages" in columns:
                        row = conn.execute("SELECT enabled_languages FROM languages_config LIMIT 1").fetchone()
                        current_langs = []
                        if row and row[0]:
                            try:
                                current_langs = json.loads(row[0])
                            except json.JSONDecodeError:
                                current_langs = []
                        if lang not in current_langs:
                            current_langs.append(lang)
                            conn.execute(
                                "UPDATE languages_config SET enabled_languages = ?, updated_at = ?",
                                (json.dumps(current_langs, ensure_ascii=False), datetime.now().isoformat())
                            )
                    conn.commit()
                    results.append(f"\n  Systemsprache auf '{lang}' gesetzt.")
                finally:
                    conn.close()
        except Exception as e:
            results.append(f"\n  [WARN] Systemsprache konnte nicht gesetzt werden: {e}")

        return True, "\n".join(results)

    def _generate_help_docs(self, lang: str) -> tuple:
        """Generiert Help-Dateien aus der DB für die gewählte Sprache."""
        try:
            sys.path.insert(0, str(self.base_path))
            from tools.help_docs_generator import generate, stats as help_stats

            st = help_stats()
            if not st or lang not in st:
                return True, f"Keine Help-Docs für Sprache '{lang}' in der DB vorhanden (übersprungen)."

            result = generate(lang=lang)
            if result["errors"]:
                return False, (
                    f"Help-Docs generiert: {result['generated']} Dateien, "
                    f"aber {len(result['errors'])} Fehler:\n"
                    + "\n".join(f"  - {e}" for e in result["errors"])
                )
            return True, f"Help-Docs generiert: {result['generated']} Dateien für '{lang}'."
        except Exception as e:
            return True, f"Help-Docs-Generator nicht verfügbar: {e} (übersprungen)"

    # =========================================================================
    # Secrets Setup
    # =========================================================================

    def _setup_secrets(self) -> tuple:
        """Initialisiert oder syncht die Secrets-Datei."""
        try:
            import sys
            sys.path.insert(0, str(self.base_path))
            from hub.secrets_handler import SecretsHandler
            handler = SecretsHandler()
            handler.sync_from_file(enforce_authority=False)
            return True, "Secrets-Sync abgeschlossen."
        except Exception as e:
            return False, f"Fehler beim Secrets-Sync: {e}"

    # --- Hilfsmethoden ---

    def _is_npm_package_installed(self, package: str) -> bool:
        """Prueft ob ein npm-Paket global installiert ist."""
        package_path = self._get_npm_package_path(package)
        return bool(package_path and package_path.exists())

    def _resolve_npm_executable(self) -> str | None:
        """Resolve the platform-specific npm executable usable by subprocess."""
        for candidate in ("npm.cmd", "npm.exe", "npm"):
            npm_path = shutil.which(candidate)
            if npm_path:
                return npm_path
        return None

    def _get_npm_global_root(self) -> Path | None:
        """Ermittelt das globale npm node_modules-Verzeichnis einmal pro Handler."""
        if self._npm_global_root_cache is not False:
            return self._npm_global_root_cache

        npm_path = self._resolve_npm_executable()
        if not npm_path:
            self._npm_global_root_cache = None
            return None

        try:
            proc = subprocess.run(
                [npm_path, "root", "-g"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
        except Exception:
            self._npm_global_root_cache = None
            return None

        if proc.returncode != 0:
            self._npm_global_root_cache = None
            return None

        root = proc.stdout.strip()
        self._npm_global_root_cache = Path(root) if root else None
        return self._npm_global_root_cache

    def _get_npm_package_path(self, package: str) -> Path | None:
        """Liefert den erwarteten globalen Installationspfad eines npm-Pakets."""
        root = self._get_npm_global_root()
        if root is None:
            return None
        return root.joinpath(*package.split("/"))

    def _candidate_local_mcp_roots(self) -> list[Path]:
        """Sammelt moegliche lokale MCP-Workspace-Wurzeln fuer BACH-Entwicklungsumgebungen."""
        roots = []
        seen = set()

        def add_root(path: Path) -> None:
            key = str(path)
            if key in seen:
                return
            seen.add(key)
            if path.exists():
                roots.append(path)

        for raw_root in os.environ.get("BACH_LOCAL_MCP_ROOTS", "").split(os.pathsep):
            raw_root = raw_root.strip()
            if raw_root:
                add_root(Path(raw_root).expanduser())

        try:
            base = self.base_path.resolve()
        except OSError:
            base = self.base_path

        for parent in [base, *base.parents]:
            add_root(parent / ".MCP")

        return roots

    def _get_local_mcp_repo_path(self, package: str) -> Path | None:
        """Findet eine lokale MCP-Arbeitskopie mit passender package.json."""
        for root in self._candidate_local_mcp_roots():
            candidate = root / package
            package_json = candidate / "package.json"
            if not candidate.is_dir() or not package_json.exists():
                continue

            try:
                meta = json.loads(package_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

            if meta.get("name") != package:
                continue

            if not ((candidate / "dist").exists() or (candidate / "server.json").exists()):
                continue

            return candidate

        return None

    def _validate_mcp_install_plan(self, packages: list,
                                   server_configs: dict | None = None) -> tuple:
        """Validiert MCP-Installationsplaene fail-closed vor npm/config-Zugriff."""
        errors = []

        if not packages:
            errors.append("Keine MCP-Pakete angegeben")

        for package in packages:
            if not isinstance(package, str) or not package:
                errors.append("Leerer oder ungueltiger MCP-Paketname")
                continue
            if not self.MCP_PACKAGE_PATTERN.match(package):
                errors.append(f"Ungueltiger MCP-Paketname: {package}")
            if package not in self.MCP_PACKAGE_ALLOWLIST:
                errors.append(f"MCP-Paket nicht in Allowlist: {package}")

        for server_name, config in (server_configs or {}).items():
            if not isinstance(config, dict):
                errors.append(f"MCP-Config fuer {server_name} ist kein Objekt")
                continue

            command = config.get("command")
            args = config.get("args", [])
            if command != "npx":
                errors.append(f"MCP-Config {server_name}: command muss 'npx' sein")
            if not isinstance(args, list) or len(args) != 1:
                errors.append(f"MCP-Config {server_name}: args muss genau ein Paket enthalten")
                continue

            package = args[0]
            if package not in packages:
                errors.append(f"MCP-Config {server_name}: Paket nicht im Installationsplan: {package}")
            if package not in self.MCP_PACKAGE_ALLOWLIST:
                errors.append(f"MCP-Config {server_name}: Paket nicht in Allowlist: {package}")
            if not isinstance(package, str) or not self.MCP_PACKAGE_PATTERN.match(package):
                errors.append(f"MCP-Config {server_name}: ungueltiger Paketname: {package}")

        return len(errors) == 0, errors

    def _format_mcp_validation_error(self, errors: list) -> str:
        """Formatiert blockierende MCP-Setup-Validierungsfehler."""
        lines = [
            "MCP-Setup blockiert: fail-closed Sicherheitspruefung fehlgeschlagen.",
            "Bitte Paketnamen und MCP-Konfiguration vor Installation pruefen.",
        ]
        for error in errors[:10]:
            lines.append(f"  - {error}")
        if len(errors) > 10:
            lines.append(f"  - ... und {len(errors) - 10} weitere")
        return "\n".join(lines)

    def _candidate_mcp_local_paths(self, value: str) -> list[Path]:
        """Gibt existierende lokale Pfade aus einem MCP command/args-Wert zurueck."""
        if not isinstance(value, str):
            return []

        raw = value.strip().strip("\"'")
        if not raw or raw.startswith("-"):
            return []
        if raw in {"npx", "npm", "node", "python", "python3", "python.exe"}:
            return []
        if raw in self.MCP_PACKAGE_ALLOWLIST:
            return []

        candidates = [Path(raw).expanduser()]
        if not candidates[0].is_absolute():
            candidates.extend([
                self.base_path / raw,
                self.base_path.parent / raw,
            ])

        found = []
        seen = set()
        for candidate in candidates:
            try:
                if not candidate.exists():
                    continue
                resolved = candidate.resolve()
            except (OSError, RuntimeError):
                continue
            if resolved not in seen:
                found.append(resolved)
                seen.add(resolved)

        return found

    def _scan_mcp_config_paths(self, server_configs: dict) -> tuple:
        """Scannt lokale MCP-Serverpfade aus command/args vor Config-Aktivierung."""
        from core.capabilities import capability_manager

        blocking = []
        warnings = []

        for server_name, config in (server_configs or {}).items():
            if not isinstance(config, dict):
                continue

            values = [config.get("command")]
            args = config.get("args", [])
            if isinstance(args, list):
                values.extend(args)

            for value in values:
                for path in self._candidate_mcp_local_paths(value):
                    findings_by_file = {}
                    if path.is_dir():
                        findings_by_file = capability_manager.scan_tree(
                            path,
                            suffixes=self.MCP_LOCAL_SCAN_SUFFIXES,
                        )
                    elif path.suffix.lower() in self.MCP_LOCAL_SCAN_SUFFIXES:
                        findings = capability_manager.run_security_checks(str(path))
                        if findings:
                            findings_by_file[str(path)] = findings

                    for file_path, findings in findings_by_file.items():
                        label = f"{server_name}/{Path(file_path).name}"
                        for finding in findings:
                            line = f"{label}: {finding}"
                            if finding.startswith("[CODE_INJECTION]"):
                                blocking.append(line)
                            else:
                                warnings.append(line)
                    if any(
                        finding.startswith("[CODE_INJECTION]")
                        for findings in findings_by_file.values()
                        for finding in findings
                    ):
                        quarantine_dir = capability_manager.quarantine_path(
                            path,
                            self.base_path,
                            "mcp",
                            findings_by_file,
                            f"MCP config blocked: {server_name}",
                            metadata={"server": server_name},
                        )
                        blocking.append(f"{server_name}: Quarantaene erstellt: {quarantine_dir}")

        return len(blocking) == 0, blocking, warnings

    def _format_mcp_scan_error(self, findings: list) -> str:
        """Formatiert blockierende MCP-Importpfad-Scanfehler."""
        lines = [
            "MCP-Config blockiert: lokaler MCP-Importpfad ist unsicher.",
            "Quarantaene wurde fuer blockierte lokale Pfade erstellt.",
        ]
        for finding in findings[:10]:
            lines.append(f"  - {finding}")
        if len(findings) > 10:
            lines.append(f"  - ... und {len(findings) - 10} weitere")
        return "\n".join(lines)

    def _load_json_object_config(self, path: Path, label: str,
                                 allow_missing: bool = False) -> tuple:
        """Laedt eine JSON-Konfiguration fail-closed als Objekt."""
        if not path.exists():
            if allow_missing:
                return True, {}, ""
            return False, None, f"{label} nicht gefunden: {path}"

        if path.is_dir():
            return False, None, f"{label} blockiert: {path} ist ein Verzeichnis."
        if path.is_symlink():
            return False, None, (
                f"{label} blockiert: Symbolic-Link-Ziele werden nicht automatisch "
                f"beschrieben ({path})."
            )

        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as e:
            return False, None, f"{label} blockiert: Datei nicht lesbar ({e})."

        if not raw.strip():
            return True, {}, ""

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            return False, None, (
                f"{label} blockiert: JSON ungueltig "
                f"(Zeile {e.lineno}, Spalte {e.colno}: {e.msg})."
            )

        if not isinstance(data, dict):
            return False, None, f"{label} blockiert: oberstes JSON-Element muss ein Objekt sein."

        return True, data, ""

    def _find_claude_config(self) -> Path | None:
        """Findet die Claude Code MCP-Config-Datei."""
        claude_config = Path.home() / ".claude.json"
        if claude_config.exists():
            return claude_config
        alt_config = Path.home() / ".claude" / "mcp.json"
        if alt_config.exists():
            return alt_config
        return None

    def _setup_n8n(self, dry_run: bool = False) -> tuple:
        """Installiert n8n-manager-mcp und konfiguriert Claude Code. (B37)"""
        results = []
        errors = []
        pkg = "n8n-manager-mcp"
        info = self.OPTIONAL_MCP_PACKAGES[pkg]
        ok, validation_errors = self._validate_mcp_install_plan(
            [pkg],
            {info["name"]: info["config"]},
        )
        if not ok:
            return False, self._format_mcp_validation_error(validation_errors)

        # 1. npm pruefen
        npm_path = self._resolve_npm_executable()
        if not npm_path:
            return False, (
                "npm nicht gefunden. Bitte Node.js installieren:\n"
                "  https://nodejs.org/\n"
                "Nach der Installation Terminal neu starten und erneut ausfuehren."
            )

        # 2. Paket installieren
        results.append("=== n8n-manager-mcp Installation ===\n")

        if self._is_npm_package_installed(pkg):
            results.append(f"  [OK] {pkg} bereits installiert")
        elif dry_run:
            results.append(f"  [DRY-RUN] npm install -g {pkg}")
        else:
            results.append(f"  Installiere {pkg}...")
            try:
                proc = subprocess.run(
                    [npm_path, "install", "-g", pkg],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120
                )
                if proc.returncode == 0:
                    results.append(f"  [OK] {pkg} installiert")
                else:
                    errors.append(f"  [FEHLER] {pkg}: {proc.stderr.strip()}")
            except subprocess.TimeoutExpired:
                errors.append(f"  [TIMEOUT] {pkg}: Installation dauerte zu lange")
            except Exception as e:
                errors.append(f"  [FEHLER] {pkg}: {e}")

        # 3. Claude Code MCP-Config aktualisieren
        results.append("\n=== Claude Code Konfiguration ===\n")
        claude_config = self._find_claude_config()

        if not claude_config:
            results.append(
                "  Claude Code Config nicht gefunden.\n"
                "  Manuell konfigurieren mit:\n"
                f"    claude mcp add --scope user {info['name']} -- npx {pkg}"
            )
        elif dry_run:
            results.append(f"  [DRY-RUN] Wuerde {claude_config} aktualisieren")
        else:
            ok, config, error = self._load_json_object_config(
                claude_config,
                "Claude Code Config",
                allow_missing=True,
            )
            if not ok:
                return False, error

            if "mcpServers" not in config:
                config["mcpServers"] = {}
            elif not isinstance(config["mcpServers"], dict):
                return False, "Claude Code Config blockiert: 'mcpServers' muss ein Objekt sein."

            server_name = info["name"]
            scan_configs = dict(config["mcpServers"])
            scan_configs[server_name] = info["config"]
            scan_ok, blocking_findings, warning_findings = self._scan_mcp_config_paths(scan_configs)
            if not scan_ok:
                return False, self._format_mcp_scan_error(blocking_findings)

            if server_name not in config["mcpServers"]:
                config["mcpServers"][server_name] = info["config"]
                results.append(f"  [NEU] {server_name} hinzugefuegt")
            else:
                results.append(f"  [OK] {server_name} bereits konfiguriert")

            claude_config.write_text(
                json.dumps(config, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            results.append(f"  Config: {claude_config}")
            if warning_findings:
                results.append(f"  Scan-Warnungen: {len(warning_findings)}")
                for warning in warning_findings[:5]:
                    results.append(f"    - {warning}")

        # Ergebnis
        output = "\n".join(results)
        if errors:
            output += "\n\nFehler:\n" + "\n".join(errors)
            return False, output

        return True, output
