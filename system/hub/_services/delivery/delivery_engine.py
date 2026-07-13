#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
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
BACH Delivery Engine v1.0.0
============================
Zentrale Zustellungs-Engine für Dossiers, Analysen, Berichte

Unterstützt:
- User-Folder (Standard-Ablage)
- Browser-Preview (PDF auto-open)
- Email (Gmail via Email-Driver)
- Telegram (via Connector-Driver)
- Cloud-Local (OneDrive, Google Drive, Dropbox - lokale Ordner)
- System-Inbox (für externe Abholung)

Modes:
- parallel: Alle konfigurierten Methoden parallel
- only: Nur angegebene Methode(n)

Usage:
    from hub._services.delivery.delivery_engine import DeliveryEngine

    engine = DeliveryEngine()
    result = engine.deliver(
        content="# Mein Report\\n\\nInhalt...",
        title="Steuer-Analyse 2024",
        format="pdf",
        skill="steuer-agent"
    )
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

# Encoding Fix
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


class DeliveryEngine:
    """Zentrale Delivery-Engine für BACH"""

    def __init__(self, base_path: Path = None):
        if base_path is None:
            # Auto-detect: Diese Datei liegt in system/hub/_services/delivery/
            base_path = Path(__file__).parent.parent.parent.parent

        self.base_path = base_path
        self.config_file = base_path / "data" / "config" / "delivery_preferences.json"
        self.config = self._load_config()
        try:
            from hub.bach_paths import BACH_DB
            self.db_path = BACH_DB
        except ImportError:
            self.db_path = BACH_DB

    def _load_config(self) -> dict:
        """Lädt Delivery-Preferences Config"""
        if not self.config_file.exists():
            return self._get_default_config()

        try:
            return json.loads(self.config_file.read_text(encoding='utf-8'))
        except Exception as e:
            print(f"[WARN] Config-Load fehlgeschlagen: {e}, nutze Defaults")
            return self._get_default_config()

    def _get_default_config(self) -> dict:
        """Default-Config wenn keine Datei vorhanden"""
        return {
            "default_delivery": {
                "mode": "parallel",
                "methods": ["user_folder"]
            },
            "delivery_methods": {
                "user_folder": {
                    "enabled": True,
                    "base_path": "user/"
                }
            }
        }

    def deliver(
        self,
        content: str,
        title: str,
        format: str = "md",
        skill: Optional[str] = None,
        agent: Optional[str] = None,
        metadata: Optional[Dict] = None,
        delivery_override: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Haupt-Delivery-Funktion

        Args:
            content: Inhalt (Markdown, Text, JSON etc.)
            title: Titel des Deliverables
            format: Zielformat (pdf, md, txt, json, html)
            skill: Skill-Name (für Overrides)
            agent: Agent-Name (für Overrides)
            metadata: Zusätzliche Metadaten
            delivery_override: Manuelle Delivery-Präferenzen

        Returns:
            Dict mit Delivery-Ergebnissen
        """
        start_time = datetime.now()

        # Metadaten vorbereiten
        if metadata is None:
            metadata = {}
        metadata.update({
            "title": title,
            "format": format,
            "skill": skill or "unknown",
            "agent": agent or "unknown",
            "timestamp": start_time.isoformat()
        })

        # Delivery-Preferences ermitteln
        preferences = self._get_preferences(skill, agent, delivery_override)

        # Datei vorbereiten
        file_result = self._prepare_file(content, title, format, metadata)
        if not file_result["success"]:
            return {
                "success": False,
                "error": file_result["error"],
                "delivered_to": []
            }

        file_path = file_result["path"]

        # Delivery durchführen
        results = []
        mode = preferences.get("mode", "parallel")
        methods = preferences.get("methods", ["user_folder"])

        for method in methods:
            method_config = self.config["delivery_methods"].get(method, {})

            if not method_config.get("enabled", False):
                continue

            # Format-Check
            supported = method_config.get("supported_formats", [format])
            if format not in supported:
                continue

            result = self._deliver_via_method(method, file_path, metadata, method_config)
            results.append({
                "method": method,
                "success": result["success"],
                "details": result.get("details", ""),
                "error": result.get("error")
            })

        duration = (datetime.now() - start_time).total_seconds()

        return {
            "success": all(r["success"] for r in results),
            "file": str(file_path),
            "delivered_to": [r["method"] for r in results if r["success"]],
            "failures": [r for r in results if not r["success"]],
            "duration_seconds": duration,
            "metadata": metadata
        }

    def _get_preferences(
        self,
        skill: Optional[str],
        agent: Optional[str],
        override: Optional[Dict]
    ) -> Dict:
        """Ermittelt Delivery-Preferences (Skill > Agent > Default)"""
        if override:
            return override

        # Skill-Override?
        if skill and skill in self.config.get("skill_overrides", {}):
            return self.config["skill_overrides"][skill]

        # Agent-Override?
        if agent and agent in self.config.get("agent_overrides", {}):
            return self.config["agent_overrides"][agent]

        # Default
        return self.config.get("default_delivery", {
            "mode": "parallel",
            "methods": ["user_folder"]
        })

    def _prepare_file(
        self,
        content: str,
        title: str,
        format: str,
        metadata: Dict
    ) -> Dict[str, Any]:
        """Bereitet Datei vor (ggf. PDF-Kompilierung)"""

        # Temporärer Speicherort
        temp_dir = self.base_path / "data" / "temp" / "delivery"
        temp_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
        safe_title = safe_title.replace(' ', '_')[:50]

        filename = f"{safe_title}_{timestamp}.{format}"
        file_path = temp_dir / filename

        try:
            if format == "pdf":
                # PDF-Kompilierung via Markdown
                md_file = temp_dir / f"{safe_title}_{timestamp}.md"
                md_file.write_text(content, encoding='utf-8')

                # PDF via c_md_to_pdf Tool kompilieren
                pdf_file = temp_dir / f"{safe_title}_{timestamp}.pdf"

                try:
                    cmd = [
                        sys.executable,
                        str(self.base_path / "tools" / "c_md_to_pdf.py"),
                        str(md_file),
                        "-o", str(pdf_file)
                    ]
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        errors='replace',
                        cwd=str(self.base_path)
                    )

                    if result.returncode == 0 and pdf_file.exists():
                        file_path = pdf_file
                    else:
                        # Fallback auf Markdown wenn PDF-Kompilierung fehlschlägt
                        file_path = md_file
                except Exception:
                    # Fallback auf Markdown bei Fehler
                    file_path = md_file

            elif format in ("md", "txt", "html"):
                file_path.write_text(content, encoding='utf-8')

            elif format == "json":
                if isinstance(content, str):
                    # Wenn Content bereits JSON-String
                    file_path.write_text(content, encoding='utf-8')
                else:
                    # Wenn Content Python-Objekt
                    file_path.write_text(
                        json.dumps(content, indent=2, ensure_ascii=False),
                        encoding='utf-8'
                    )

            else:
                return {
                    "success": False,
                    "error": f"Unsupported format: {format}"
                }

            return {
                "success": True,
                "path": file_path,
                "filename": filename
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"File preparation failed: {e}"
            }

    def _deliver_via_method(
        self,
        method: str,
        file_path: Path,
        metadata: Dict,
        config: Dict
    ) -> Dict[str, Any]:
        """Delivery via spezifischer Methode"""

        handlers = {
            "user_folder": self._deliver_user_folder,
            "browser_preview": self._deliver_browser_preview,
            "email": self._deliver_email,
            "telegram": self._deliver_telegram,
            "cloud_local": self._deliver_cloud_local,
            "system_inbox": self._deliver_system_inbox
        }

        handler = handlers.get(method)
        if not handler:
            return {
                "success": False,
                "error": f"Unknown delivery method: {method}"
            }

        try:
            return handler(file_path, metadata, config)
        except Exception as e:
            return {
                "success": False,
                "error": f"{method} delivery failed: {e}"
            }

    def _deliver_user_folder(
        self,
        file_path: Path,
        metadata: Dict,
        config: Dict
    ) -> Dict[str, Any]:
        """Ablage im User-Ordner"""
        import shutil

        base = self.base_path / config.get("base_path", "user/")

        # Subdir-Pattern?
        if config.get("create_subdirs", True):
            pattern = config.get("subdir_pattern", "{skill}/{date}")
            subdir = pattern.format(
                skill=metadata.get("skill", "unknown"),
                agent=metadata.get("agent", "unknown"),
                date=datetime.now().strftime("%Y-%m-%d")
            )
            target_dir = base / subdir
        else:
            target_dir = base

        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / file_path.name

        shutil.copy2(file_path, target_file)

        return {
            "success": True,
            "details": f"Saved to {target_file.relative_to(self.base_path)}"
        }

    def _deliver_browser_preview(
        self,
        file_path: Path,
        metadata: Dict,
        config: Dict
    ) -> Dict[str, Any]:
        """PDF im Browser öffnen"""

        browser_name = config.get("browser", "edge")
        browser_paths = config.get("browser_paths", {})
        browser_exe = browser_paths.get(browser_name)

        if not browser_exe or not Path(browser_exe).exists():
            return {
                "success": False,
                "error": f"Browser not found: {browser_name}"
            }

        try:
            subprocess.Popen(
                [browser_exe, str(file_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return {
                "success": True,
                "details": f"Opened in {browser_name}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Browser open failed: {e}"
            }

    def _deliver_email(
        self,
        file_path: Path,
        metadata: Dict,
        config: Dict
    ) -> Dict[str, Any]:
        """E-Mail-Zustellung via Email-Driver"""

        # TODO: Email-Driver Integration
        # bach email send <to> --subject "..." --body "..." --attach <file>

        recipient = config.get("self_address", "your-email@example.com")
        subject = config.get("subject_template", "BACH Delivery: {title}").format(**metadata)
        body = config.get("body_template", "Auto-Delivery").format(**metadata)

        try:
            cmd = [
                sys.executable,
                str(self.base_path / "bach.py"),
                "email", "send", recipient,
                "--subject", subject,
                "--body", body,
                "--attach", str(file_path)
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                cwd=str(self.base_path)
            )

            if result.returncode == 0:
                return {
                    "success": True,
                    "details": f"Email draft created for {recipient}"
                }
            else:
                return {
                    "success": False,
                    "error": f"Email command failed: {result.stderr}"
                }

        except Exception as e:
            return {
                "success": False,
                "error": f"Email delivery failed: {e}"
            }

    def _deliver_telegram(
        self,
        file_path: Path,
        metadata: Dict,
        config: Dict
    ) -> Dict[str, Any]:
        """Telegram-Zustellung via Connector"""

        connector_name = config.get("connector_name", "telegram")
        user_id = config.get("user_id", "self")
        caption = config.get("caption_template", "{title}").format(**metadata)

        try:
            cmd = [
                sys.executable,
                str(self.base_path / "bach.py"),
                "connector", "send", connector_name, user_id,
                "--file", str(file_path),
                "--caption", caption
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                cwd=str(self.base_path)
            )

            if result.returncode == 0:
                return {
                    "success": True,
                    "details": f"Sent via {connector_name} to {user_id}"
                }
            else:
                return {
                    "success": False,
                    "error": f"Telegram command failed: {result.stderr}"
                }

        except Exception as e:
            return {
                "success": False,
                "error": f"Telegram delivery failed: {e}"
            }

    def _deliver_cloud_local(
        self,
        file_path: Path,
        metadata: Dict,
        config: Dict
    ) -> Dict[str, Any]:
        """Lokale Cloud-Ordner Ablage"""
        import shutil

        active_clouds = config.get("active_clouds", [])
        paths = config.get("paths", {})

        delivered = []
        errors = []

        for cloud_name in active_clouds:
            cloud_path = paths.get(cloud_name)
            if not cloud_path:
                continue

            cloud_base = Path(cloud_path).expanduser()

            # Subdir-Pattern?
            if config.get("create_subdirs", True):
                pattern = config.get("subdir_pattern", "{skill}/{date}")
                subdir = pattern.format(
                    skill=metadata.get("skill", "unknown"),
                    date=datetime.now().strftime("%Y-%m-%d")
                )
                target_dir = cloud_base / subdir
            else:
                target_dir = cloud_base

            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                target_file = target_dir / file_path.name
                shutil.copy2(file_path, target_file)
                delivered.append(cloud_name)
            except Exception as e:
                errors.append(f"{cloud_name}: {e}")

        if delivered:
            return {
                "success": True,
                "details": f"Delivered to clouds: {', '.join(delivered)}"
            }
        else:
            return {
                "success": False,
                "error": f"Cloud delivery failed: {'; '.join(errors)}"
            }

    def _deliver_system_inbox(
        self,
        file_path: Path,
        metadata: Dict,
        config: Dict
    ) -> Dict[str, Any]:
        """System-Inbox für externe Abholung"""
        import shutil

        inbox_path = self.base_path / config.get("inbox_path", "data/inbox/")
        inbox_path.mkdir(parents=True, exist_ok=True)

        target_file = inbox_path / file_path.name
        shutil.copy2(file_path, target_file)

        return {
            "success": True,
            "details": f"Placed in inbox: {target_file.name}"
        }


# CLI Entry Point
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="BACH Delivery Engine v1.0.0")
    parser.add_argument("--content", type=str, help="Content to deliver")
    parser.add_argument("--title", type=str, required=True, help="Delivery title")
    parser.add_argument("--format", type=str, default="md", help="Format (pdf, md, txt, json)")
    parser.add_argument("--skill", type=str, help="Skill name")
    parser.add_argument("--agent", type=str, help="Agent name")

    args = parser.parse_args()

    engine = DeliveryEngine()
    result = engine.deliver(
        content=args.content or "# Test Delivery\n\nThis is a test.",
        title=args.title,
        format=args.format,
        skill=args.skill,
        agent=args.agent
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))
