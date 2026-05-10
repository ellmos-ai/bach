#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

"""
Connector Setup Wizard
======================

Interaktiver Wizard zum Erstellen neuer Connectors aus Templates.

Verwendung:
    python -m connectors.templates.setup_wizard

    # Oder via BACH CLI:
    bach connector setup-wizard

Features:
    - Template-basierte Connector-Erstellung
    - Interaktive Konfiguration
    - Automatische Code-Generierung
    - Validierung der Eingaben
    - Registrierung in der Datenbank
"""

import os
import sys
import json
import yaml
import sqlite3
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

# UTF-8 Encoding fix
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


class SetupWizard:
    """Interaktiver Setup-Wizard fuer neue Connectors."""

    def __init__(self, base_path: Path = None):
        self.base_path = base_path or Path(__file__).parent.parent.parent
        self.templates_dir = self.base_path / "connectors" / "templates"
        self.connectors_dir = self.base_path / "connectors"
        self.db_path = self.base_path / "data" / "bach.db"

    def run(self):
        """Hauptschleife des Wizards."""
        print("=" * 60)
        print("BACH Connector Setup Wizard")
        print("=" * 60)
        print()

        # Schritt 1: Template auswaehlen
        template = self.select_template()
        if not template:
            print("\n[Abbruch] Kein Template ausgewaehlt.")
            return

        # Schritt 2: Template laden
        config = self.load_template(template)
        if not config:
            print(f"\n[Fehler] Template '{template}' konnte nicht geladen werden.")
            return

        print(f"\n Template: {config.get('connector_display_name', template)}")
        print(f" Beschreibung: {config.get('connector_description', 'N/A').strip()}")
        print()

        # Schritt 3: Benutzereingaben sammeln
        user_config = self.gather_configuration(config)
        if not user_config:
            print("\n[Abbruch] Konfiguration abgebrochen.")
            return

        # Schritt 4: Connector-Datei generieren
        connector_file = self.generate_connector(config, user_config)
        if not connector_file:
            print("\n[Fehler] Connector-Datei konnte nicht generiert werden.")
            return

        print(f"\n[OK] Connector-Datei erstellt: {connector_file}")

        # Schritt 5: In Datenbank registrieren
        if self.confirm("Connector in Datenbank registrieren?"):
            success = self.register_connector(config, user_config)
            if success:
                print(f"\n[OK] Connector '{user_config['instance_name']}' registriert!")
                print(f"\nNaechste Schritte:")
                print(f"  1. Connector testen: bach connector poll {user_config['instance_name']}")
                print(f"  2. Daemon-Jobs einrichten: bach connector setup-daemon")
            else:
                print("\n[Fehler] Registrierung fehlgeschlagen.")
        else:
            print("\n[Info] Connector nicht in Datenbank registriert.")
            print(f"Manuelle Registrierung: bach connector add {config['connector_type']} {user_config['instance_name']}")

        print("\n" + "=" * 60)
        print("Setup abgeschlossen!")
        print("=" * 60)

    def select_template(self) -> Optional[str]:
        """Template auswaehlen."""
        templates = self.list_templates()
        if not templates:
            print("[Fehler] Keine Templates gefunden.")
            return None

        print("Verfuegbare Templates:")
        print()
        for i, tmpl in enumerate(templates, 1):
            print(f"  {i}. {tmpl}")
        print()

        while True:
            choice = input("Template waehlen (Nummer oder Name): ").strip()
            if not choice:
                return None

            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(templates):
                    return templates[idx]
            elif choice in templates:
                return choice

            print("[Fehler] Ungueltige Auswahl. Bitte erneut versuchen.")

    def list_templates(self) -> List[str]:
        """Alle verfuegbaren Templates auflisten."""
        if not self.templates_dir.exists():
            return []

        templates = []
        for f in self.templates_dir.glob("*_template.yaml"):
            templates.append(f.stem.replace("_template", ""))

        return sorted(templates)

    def load_template(self, template_name: str) -> Optional[Dict[str, Any]]:
        """Template-Konfiguration laden."""
        template_file = self.templates_dir / f"{template_name}_template.yaml"
        if not template_file.exists():
            return None

        try:
            with open(template_file, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        except Exception as e:
            print(f"[Fehler] Template konnte nicht geladen werden: {e}")
            return None

    def gather_configuration(self, template: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Benutzereingaben sammeln."""
        print("\nKonfiguration:")
        print("-" * 60)

        user_config = {
            "auth_config": {},
            "options": {},
            "instance_name": "",
        }

        # Instanz-Name
        print()
        instance_name = input(f"Instanz-Name (z.B. {template.get('connector_instance_name', 'main')}): ").strip()
        if not instance_name:
            instance_name = template.get('connector_instance_name', f"{template['connector_type']}_main")
        user_config["instance_name"] = instance_name

        # Setup-Fragen durchgehen
        questions = template.get("setup_questions", [])
        for q in questions:
            name = q["name"]
            prompt = q["prompt"]
            qtype = q.get("type", "text")
            required = q.get("required", False)
            storage = q.get("storage", "options")
            default = q.get("default", "")

            print()
            if qtype == "secret":
                print(f"{prompt} (wird nicht angezeigt):")
                value = self.input_secret()
            elif qtype == "choice":
                choices = q.get("choices", [])
                print(f"{prompt}")
                for i, choice in enumerate(choices, 1):
                    marker = " (default)" if choice == default else ""
                    print(f"  {i}. {choice}{marker}")
                value = self.input_choice(choices, default)
            else:
                default_text = f" (default: {default})" if default else ""
                value = input(f"{prompt}{default_text}: ").strip() or default

            if required and not value:
                print("[Fehler] Pflichtfeld darf nicht leer sein.")
                return None

            # In richtigen Storage speichern
            if storage == "auth_config":
                user_config["auth_config"][name] = value
                # ENT-44: Secret-Felder merken fuer spaetere Trennung
                if qtype == "secret":
                    user_config.setdefault("secret_fields", []).append(name)
            else:
                user_config["options"][name] = value

        print()
        print("-" * 60)
        print("Konfiguration abgeschlossen.")

        return user_config

    def generate_connector(self, template: Dict[str, Any], user_config: Dict[str, Any]) -> Optional[Path]:
        """Connector-Datei aus Template generieren."""
        # Template-Datei laden
        template_file = self.templates_dir / "connector_template.py"
        if not template_file.exists():
            print("[Fehler] connector_template.py nicht gefunden.")
            return None

        try:
            with open(template_file, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            print(f"[Fehler] Template-Datei konnte nicht gelesen werden: {e}")
            return None

        # Platzhalter ersetzen
        replacements = {
            "{{CONNECTOR_NAME}}": template["connector_name"],
            "{{CONNECTOR_TYPE}}": template["connector_type"],
            "{{CONNECTOR_DISPLAY_NAME}}": template["connector_display_name"],
            "{{CONNECTOR_DESCRIPTION}}": template["connector_description"],
            "{{CONNECTOR_MODULE}}": template["connector_module"],
            "{{CONNECTOR_INSTANCE_NAME}}": user_config["instance_name"],
            "{{RECIPIENT_EXAMPLE}}": template.get("recipient_example", "recipient_id"),
            "{{AUTH_TYPE}}": template.get("auth_type", "api_key"),
            "{{AUTH_CONFIG_EXAMPLE}}": template.get("auth_config_example", "{}"),
            "{{OPTIONS_EXAMPLE}}": template.get("options_example", "{}"),
            "{{API_BASE_COMMENT}}": template.get("api_base_comment", ""),
            "{{API_BASE_URL}}": template.get("api_base_url", ""),
            "{{INIT_VARIABLES}}": self._indent(template.get("init_variables", ""), 8),
            "{{CONNECT_VALIDATION}}": self._indent(template.get("connect_validation", "pass"), 8),
            "{{CONNECT_IMPLEMENTATION}}": self._indent(template.get("connect_implementation", "pass"), 12),
            "{{SEND_MESSAGE_IMPLEMENTATION}}": self._indent(template.get("send_message_implementation", "pass"), 12),
            "{{GET_MESSAGES_IMPLEMENTATION}}": self._indent(template.get("get_messages_implementation", "pass"), 12),
            "{{PARSE_MESSAGES_IMPLEMENTATION}}": self._indent(template.get("parse_messages_implementation", "pass"), 12),
            "{{HELPER_METHODS}}": self._indent(template.get("helper_methods", "pass"), 4),
        }

        for placeholder, value in replacements.items():
            content = content.replace(placeholder, value)

        # Datei schreiben
        output_file = self.connectors_dir / template["connector_module"]
        if not output_file.name.endswith(".py"):
            output_file = self.connectors_dir / f"{template['connector_module']}.py"

        try:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(content)
            return output_file
        except Exception as e:
            print(f"[Fehler] Datei konnte nicht geschrieben werden: {e}")
            return None

    def register_connector(self, template: Dict[str, Any], user_config: Dict[str, Any]) -> bool:
        """Connector in Datenbank registrieren."""
        if not self.db_path.exists():
            print(f"[Fehler] Datenbank nicht gefunden: {self.db_path}")
            return False

        conn = sqlite3.connect(str(self.db_path))
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # ENT-44: Secrets aus auth_config in secrets-Tabelle auslagern
            auth_data = dict(user_config["auth_config"])
            secret_fields = user_config.get("secret_fields", [])
            secret_refs = {}
            extracted_secrets = {}  # fuer SecretsHandler-Sync

            for field_name in secret_fields:
                if field_name in auth_data and auth_data[field_name]:
                    secret_key = f"{user_config['instance_name']}_{field_name}"
                    secret_value = auth_data.pop(field_name)
                    extracted_secrets[secret_key] = secret_value
                    conn.execute(
                        "INSERT OR REPLACE INTO secrets (key, value, description, category, updated_at)"
                        " VALUES (?, ?, ?, 'api', ?)",
                        (secret_key, secret_value,
                         f"{template.get('connector_display_name', '')} {field_name}", now)
                    )
                    secret_refs[field_name] = secret_key

            if secret_refs:
                auth_data["_secret_refs"] = secret_refs

            auth_config_json = json.dumps(auth_data, ensure_ascii=False)

            # Pruefen ob Connector bereits existiert
            existing = conn.execute(
                "SELECT id FROM connections WHERE name = ? AND category = 'connector'",
                (user_config["instance_name"],)
            ).fetchone()

            if existing:
                print(f"[Warnung] Connector '{user_config['instance_name']}' existiert bereits.")
                if not self.confirm("Ueberschreiben?"):
                    return False

                # Update
                conn.execute("""
                    UPDATE connections
                    SET type = ?, auth_type = ?, auth_config = ?, updated_at = ?
                    WHERE name = ? AND category = 'connector'
                """, (template["connector_type"], template.get("auth_type", "api_key"),
                      auth_config_json, now, user_config["instance_name"]))
            else:
                # Insert
                conn.execute("""
                    INSERT INTO connections
                        (name, type, category, auth_type, auth_config, is_active, created_at, updated_at)
                    VALUES (?, ?, 'connector', ?, ?, 1, ?, ?)
                """, (user_config["instance_name"], template["connector_type"],
                      template.get("auth_type", "api_key"), auth_config_json, now, now))

            conn.commit()

            # ENT-44: Auch in bach_secrets.json schreiben (primaere Quelle)
            if extracted_secrets:
                try:
                    sys.path.insert(0, str(self.base_path))
                    from hub.secrets_handler import SecretsHandler
                    sh = SecretsHandler()
                    for sk, sv in extracted_secrets.items():
                        sh.set_secret(
                            sk, sv,
                            f"{template.get('connector_display_name', '')} token",
                            "api"
                        )
                    print(f"  Token auch in bach_secrets.json gespeichert.")
                except Exception as _e:
                    print(f"  [WARN] bach_secrets.json nicht aktualisiert: {_e}")

            return True
        except Exception as e:
            print(f"[Fehler] Datenbank-Fehler: {e}")
            return False
        finally:
            conn.close()

    # Helper Methods

    def _indent(self, text: str, spaces: int) -> str:
        """Text einruecken."""
        if not text:
            return ""
        indent = " " * spaces
        lines = text.strip().split("\n")
        return "\n".join(indent + line if line.strip() else "" for line in lines)

    def input_secret(self) -> str:
        """Geheime Eingabe (ohne Echo)."""
        try:
            import getpass
            return getpass.getpass("  > ")
        except Exception:
            return input("  > ")

    def input_choice(self, choices: List[str], default: str = "") -> str:
        """Auswahl aus Optionen."""
        while True:
            choice = input("  Auswahl (Nummer oder Text): ").strip()
            if not choice and default:
                return default

            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(choices):
                    return choices[idx]
            elif choice in choices:
                return choice

            print("  [Fehler] Ungueltige Auswahl.")

    def confirm(self, prompt: str, default: bool = True) -> bool:
        """Ja/Nein-Bestaetigung."""
        suffix = " [J/n]" if default else " [j/N]"
        while True:
            answer = input(prompt + suffix + ": ").strip().lower()
            if not answer:
                return default
            if answer in ("j", "ja", "y", "yes"):
                return True
            if answer in ("n", "nein", "no"):
                return False
            print("[Fehler] Bitte 'j' oder 'n' eingeben.")


def main():
    """Hauptfunktion."""
    wizard = SetupWizard()
    try:
        wizard.run()
    except KeyboardInterrupt:
        print("\n\n[Abbruch] Setup abgebrochen.")
        sys.exit(1)
    except Exception as e:
        print(f"\n[Fehler] Unerwarteter Fehler: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
