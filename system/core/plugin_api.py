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
Plugin-API - Dynamische Erweiterung von BACH zur Laufzeit
==========================================================

Ermoeglicht AI-Partnern und Scripts, BACH programmatisch zu erweitern:
- Tools registrieren (Callables als Werkzeuge)
- Hooks registrieren (Events abonnieren)
- Workflows erstellen (Markdown-Dateien)
- Handler registrieren (neue CLI-Befehle)
- Plugins laden (deklarativ via plugin.json)

Nutzung:
    from core.plugin_api import plugins

    # Imperativ
    plugins.register_tool("mein_tool", meine_funktion, "Beschreibung")
    plugins.register_hook("after_task_done", callback)
    plugins.register_handler("zeiterfassung", ZeitHandler)

    # Deklarativ
    plugins.load_plugin("path/to/plugin.json")

    # Verwaltung
    plugins.list_plugins()
    plugins.unload_plugin("mein-plugin")

Version: 1.0.0
"""

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from .capabilities import capability_manager


class PluginRegistry:
    """Zentrale Registry fuer alle dynamisch registrierten Erweiterungen."""

    def __init__(self):
        self._plugins: dict[str, dict] = {}   # name -> plugin_info
        self._tools: dict[str, dict] = {}     # name -> {fn, description, plugin}
        self._hook_refs: list[dict] = []       # [{event, name, plugin}]
        self._base_path: Optional[Path] = None

    def _get_base_path(self) -> Path:
        """Lazy base_path Ermittlung."""
        if self._base_path is None:
            self._base_path = Path(__file__).parent.parent
        return self._base_path

    # ==================================================================
    # TOOL REGISTRATION
    # ==================================================================

    def register_tool(self, name: str, handler: Callable,
                      description: str = "", plugin: str = "_runtime") -> bool:
        """Registriert eine Funktion als BACH-Tool.

        Das Tool wird in der tools-Tabelle der DB registriert und
        ist sofort ueber `bach tools search` auffindbar.

        Args:
            name: Tool-Name (z.B. "voice_processor")
            handler: Callable das aufgerufen wird
            description: Beschreibung des Tools
            plugin: Name des zugehoerigen Plugins

        Returns:
            True bei Erfolg
        """
        # Capability-Check
        allowed, reason = capability_manager.check(plugin, 'tool_register')
        if not allowed:
            return False

        self._tools[name] = {
            'handler': handler,
            'description': description,
            'plugin': plugin,
            'registered_at': datetime.now().isoformat(),
        }

        # Optional in DB registrieren
        try:
            base = self._get_base_path()
            db_path = base / "data" / "bach.db"
            if db_path.exists():
                import sqlite3
                conn = sqlite3.connect(db_path)
                now = datetime.now().isoformat()
                conn.execute("""
                    INSERT OR REPLACE INTO tools
                    (name, description, file_path, is_available, category, created_at, updated_at)
                    VALUES (?, ?, ?, 1, 'plugin', ?, ?)
                """, (name, description, f"plugin:{plugin}", now, now))
                conn.commit()
                conn.close()
        except Exception:
            pass  # DB-Registrierung ist optional

        return True

    def call_tool(self, name: str, *args, **kwargs):
        """Ruft ein registriertes Tool auf.

        Args:
            name: Tool-Name
            *args, **kwargs: Argumente fuer das Tool

        Returns:
            Ergebnis des Tool-Aufrufs

        Raises:
            KeyError: Tool nicht gefunden
        """
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' nicht registriert")
        return self._tools[name]['handler'](*args, **kwargs)

    def unregister_tool(self, name: str) -> bool:
        """Entfernt ein registriertes Tool."""
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    # ==================================================================
    # HOOK REGISTRATION (Convenience-Wrapper um core.hooks)
    # ==================================================================

    def register_hook(self, event: str, handler: Callable,
                      priority: int = 50, name: str = None,
                      plugin: str = "_runtime") -> bool:
        """Registriert einen Hook-Listener.

        Convenience-Wrapper um hooks.on() mit Plugin-Tracking.

        Args:
            event: Event-Name (z.B. 'after_task_done')
            handler: Callback-Funktion
            priority: Ausfuehrungsprioriaet (niedriger = frueher)
            name: Listener-Name
            plugin: Zugehoeriges Plugin

        Returns:
            True bei Erfolg
        """
        # Capability-Check
        allowed, reason = capability_manager.check(plugin, 'hook_listen')
        if not allowed:
            return False

        from .hooks import hooks

        listener_name = name or f"{plugin}:{getattr(handler, '__name__', 'anon')}"
        hooks.on(event, handler, priority=priority, name=listener_name)

        self._hook_refs.append({
            'event': event,
            'name': listener_name,
            'plugin': plugin,
            'registered_at': datetime.now().isoformat(),
        })
        return True

    def unregister_hooks(self, plugin: str) -> int:
        """Entfernt alle Hooks eines Plugins.

        Args:
            plugin: Plugin-Name

        Returns:
            Anzahl entfernter Hooks
        """
        from .hooks import hooks

        removed = 0
        remaining = []
        for ref in self._hook_refs:
            if ref['plugin'] == plugin:
                hooks.off(ref['event'], name=ref['name'])
                removed += 1
            else:
                remaining.append(ref)
        self._hook_refs = remaining
        return removed

    # ==================================================================
    # WORKFLOW REGISTRATION
    # ==================================================================

    def register_workflow(self, name: str, content: str,
                          description: str = "",
                          plugin: str = "_runtime") -> str:
        """Erstellt eine Workflow-Datei in _workflows/.

        Args:
            name: Workflow-Name (wird zu Dateiname)
            content: Markdown-Inhalt des Workflows
            description: Kurzbeschreibung
            plugin: Zugehoeriges Plugin

        Returns:
            Pfad zur erstellten Datei
        """
        # Capability-Check
        allowed, reason = capability_manager.check(plugin, 'workflow_create')
        if not allowed:
            return ""

        base = self._get_base_path()
        workflows_dir = base / "skills" / "_workflows"
        workflows_dir.mkdir(parents=True, exist_ok=True)

        # Dateiname normalisieren
        filename = name.replace(" ", "-").lower()
        if not filename.endswith(".md"):
            filename += ".md"

        filepath = workflows_dir / filename

        # Header hinzufuegen wenn nicht vorhanden
        if not content.startswith("---"):
            header = f"""---
name: {name}
version: 1.0.0
type: workflow
author: {plugin}
created: {datetime.now().strftime('%Y-%m-%d')}
description: >
  {description or name}
---

"""
            content = header + content

        filepath.write_text(content, encoding='utf-8')

        # Plugin-Tracking
        if plugin not in self._plugins:
            self._plugins[plugin] = self._make_plugin_info(plugin)
        self._plugins[plugin].setdefault('workflows', []).append(str(filepath))

        return str(filepath)

    # ==================================================================
    # HANDLER REGISTRATION
    # ==================================================================

    def register_handler(self, name: str, handler_class=None,
                          handler_file: str = None,
                          plugin: str = "_runtime") -> bool:
        """Registriert einen neuen CLI-Handler zur Laufzeit.

        Zwei Modi:
        1. handler_class direkt uebergeben (fuer programmatische Registrierung)
        2. handler_file angeben (wird importiert)

        Args:
            name: Handler-Name (wird zum CLI-Befehl)
            handler_class: BaseHandler-Subklasse (optional)
            handler_file: Pfad zur .py-Datei (optional)
            plugin: Zugehoeriges Plugin

        Returns:
            True bei Erfolg
        """
        # Capability-Check
        allowed, reason = capability_manager.check(plugin, 'handler_register')
        if not allowed:
            return False

        if handler_file and not handler_class:
            handler_class = self._import_handler_class(handler_file)
            if not handler_class:
                return False

        if not handler_class:
            return False

        # In Registry eintragen
        try:
            from bach_api import get_app
            app = get_app()
            app.registry.register(name, handler_class,
                                  module_name=f"plugin.{plugin}.{name}",
                                  file=handler_file)

            # Plugin-Tracking
            if plugin not in self._plugins:
                self._plugins[plugin] = self._make_plugin_info(plugin)
            self._plugins[plugin].setdefault('handlers', []).append(name)

            return True
        except Exception:
            return False

    def _import_handler_class(self, filepath: str):
        """Importiert eine Handler-Klasse aus einer Datei."""
        try:
            path = Path(filepath)
            if not path.exists():
                return None

            spec = importlib.util.spec_from_file_location(
                f"plugin_handler_{path.stem}", path
            )
            if not spec or not spec.loader:
                return None

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # BaseHandler-Subklasse finden
            from hub.base import BaseHandler
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type)
                        and issubclass(attr, BaseHandler)
                        and attr is not BaseHandler):
                    return attr
        except Exception:
            pass
        return None

    # ==================================================================
    # PLUGIN MANAGEMENT (Deklarativ via plugin.json)
    # ==================================================================

    def load_plugin(self, manifest_path: str) -> tuple:
        """Laedt ein Plugin aus einer plugin.json Manifest-Datei.

        Manifest-Format:
        {
            "name": "mein-plugin",
            "version": "1.0.0",
            "description": "Was das Plugin tut",
            "author": "claude",
            "hooks": [
                {"event": "after_task_done", "handler": "on_done", "module": "handlers.py"}
            ],
            "handlers": [
                {"name": "mein_cmd", "file": "mein_handler.py"}
            ],
            "workflows": [
                {"name": "mein-workflow", "file": "workflow.md"}
            ]
        }

        Args:
            manifest_path: Pfad zur plugin.json

        Returns:
            (success: bool, message: str)
        """
        path = Path(manifest_path)
        if not path.exists():
            return False, f"Manifest nicht gefunden: {manifest_path}"

        try:
            manifest = json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as e:
            return False, f"Ungültiges JSON: {e}"

        name = manifest.get('name', path.parent.name)
        plugin_dir = path.parent

        if name in self._plugins and self._plugins[name].get('loaded'):
            return False, f"Plugin '{name}' bereits geladen"

        scan_report = capability_manager.scan_tree(plugin_dir)
        blocking_findings, warning_findings = capability_manager.categorize_scan_findings(scan_report)
        if blocking_findings:
            lines = [
                f"Plugin '{name}' blockiert: statischer Sicherheits-Scan fehlgeschlagen",
                "Quarantaene empfohlen. Bitte pruefe das Plugin vor einer Trust-Freigabe.",
            ]
            for finding in blocking_findings[:10]:
                lines.append(f"  - {finding}")
            if len(blocking_findings) > 10:
                lines.append(f"  - ... und {len(blocking_findings) - 10} weitere")
            return False, "\n".join(lines)

        # Capability-System: Plugin registrieren und Rechte pruefen
        source = manifest.get('source', 'untrusted')
        requested_caps = manifest.get('capabilities', [])
        capability_manager.register_plugin(name, source, requested_caps)

        denied = capability_manager.check_all(name, requested_caps)
        if denied:
            capability_manager.unregister_plugin(name)
            return False, (
                f"Plugin '{name}' verweigert: Capabilities {denied} "
                f"nicht erlaubt fuer source='{source}'"
            )

        # Plugin-Info erstellen
        info = {
            'name': name,
            'version': manifest.get('version', '0.0.0'),
            'description': manifest.get('description', ''),
            'author': manifest.get('author', 'unknown'),
            'manifest_path': str(path),
            'loaded': True,
            'loaded_at': datetime.now().isoformat(),
            'hooks': [],
            'handlers': [],
            'workflows': [],
            'tools': [],
        }

        errors = []

        # Hooks laden
        for hook_def in manifest.get('hooks', []):
            event = hook_def.get('event')
            module_file = hook_def.get('module')
            handler_name = hook_def.get('handler', 'handle')
            priority = hook_def.get('priority', 50)

            if not event:
                continue

            if module_file:
                # Handler aus Modul laden
                fn = self._load_function(plugin_dir / module_file, handler_name)
                if fn:
                    self.register_hook(event, fn, priority=priority,
                                       name=f"{name}:{handler_name}", plugin=name)
                    info['hooks'].append(event)
                else:
                    errors.append(f"Hook-Handler nicht gefunden: {module_file}:{handler_name}")

        # Handler laden
        for handler_def in manifest.get('handlers', []):
            h_name = handler_def.get('name')
            h_file = handler_def.get('file')
            if h_name and h_file:
                filepath = plugin_dir / h_file
                if self.register_handler(h_name, handler_file=str(filepath), plugin=name):
                    info['handlers'].append(h_name)
                else:
                    errors.append(f"Handler nicht ladbar: {h_file}")

        # Workflows laden
        for wf_def in manifest.get('workflows', []):
            wf_name = wf_def.get('name')
            wf_file = wf_def.get('file')
            if wf_name and wf_file:
                filepath = plugin_dir / wf_file
                if filepath.exists():
                    content = filepath.read_text(encoding='utf-8')
                    self.register_workflow(wf_name, content, plugin=name)
                    info['workflows'].append(wf_name)
                else:
                    errors.append(f"Workflow nicht gefunden: {wf_file}")

        self._plugins[name] = info

        # Emit hook
        try:
            from .hooks import hooks
            hooks.emit('after_plugin_load', {
                'name': name, 'version': info['version'],
                'hooks': len(info['hooks']),
                'handlers': len(info['handlers']),
            })
        except Exception:
            pass

        parts = [f"Plugin '{name}' v{info['version']} geladen"]
        if info['hooks']:
            parts.append(f"  Hooks: {len(info['hooks'])}")
        if info['handlers']:
            parts.append(f"  Handler: {', '.join(info['handlers'])}")
        if info['workflows']:
            parts.append(f"  Workflows: {len(info['workflows'])}")
        if warning_findings:
            parts.append(f"  Scan-Warnungen: {len(warning_findings)}")
            for warning in warning_findings[:5]:
                parts.append(f"    - {warning}")
        if errors:
            parts.append(f"  Warnungen: {len(errors)}")
            for e in errors:
                parts.append(f"    - {e}")

        return True, "\n".join(parts)

    def unload_plugin(self, name: str) -> tuple:
        """Entlaedt ein Plugin und entfernt alle Registrierungen.

        Args:
            name: Plugin-Name

        Returns:
            (success: bool, message: str)
        """
        if name not in self._plugins:
            return False, f"Plugin '{name}' nicht gefunden"

        info = self._plugins[name]
        removed_hooks = self.unregister_hooks(name)

        # Tools entfernen
        removed_tools = 0
        for tool_name in list(self._tools.keys()):
            if self._tools[tool_name].get('plugin') == name:
                del self._tools[tool_name]
                removed_tools += 1

        del self._plugins[name]

        # Capability-System aufraumen
        capability_manager.unregister_plugin(name)

        return True, (
            f"Plugin '{name}' entladen: "
            f"{removed_hooks} Hooks, {removed_tools} Tools entfernt"
        )

    def list_plugins(self) -> str:
        """Gibt formatierte Liste aller Plugins zurueck."""
        if not self._plugins:
            return "Keine Plugins geladen."

        lines = ["PLUGIN-REGISTRY", "=" * 50]
        for name, info in sorted(self._plugins.items()):
            version = info.get('version', '?')
            desc = info.get('description', '')[:40]
            lines.append(f"\n  [{name}] v{version}")
            if desc:
                lines.append(f"    {desc}")

            hooks = info.get('hooks', [])
            handlers = info.get('handlers', [])
            workflows = info.get('workflows', [])
            tools = info.get('tools', [])

            parts = []
            if hooks:
                parts.append(f"{len(hooks)} Hooks")
            if handlers:
                parts.append(f"{len(handlers)} Handler")
            if workflows:
                parts.append(f"{len(workflows)} Workflows")
            if tools:
                parts.append(f"{len(tools)} Tools")
            if parts:
                lines.append(f"    Registriert: {', '.join(parts)}")

        lines.append(f"\nGesamt: {len(self._plugins)} Plugin(s)")
        return "\n".join(lines)

    # ==================================================================
    # HELPER
    # ==================================================================

    def _make_plugin_info(self, name: str) -> dict:
        """Erstellt minimale Plugin-Info fuer Runtime-Registrierungen."""
        return {
            'name': name,
            'version': '0.0.0',
            'description': 'Runtime-registriert',
            'loaded': True,
            'loaded_at': datetime.now().isoformat(),
            'hooks': [],
            'handlers': [],
            'workflows': [],
            'tools': [],
        }

    def _load_function(self, filepath: Path, func_name: str) -> Optional[Callable]:
        """Laedt eine Funktion aus einer Python-Datei."""
        try:
            if not filepath.exists():
                return None

            spec = importlib.util.spec_from_file_location(
                f"plugin_mod_{filepath.stem}", filepath
            )
            if not spec or not spec.loader:
                return None

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            return getattr(module, func_name, None)
        except Exception:
            return None

    @property
    def tool_names(self) -> list:
        """Alle registrierten Tool-Namen."""
        return sorted(self._tools.keys())

    @property
    def plugin_names(self) -> list:
        """Alle geladenen Plugin-Namen."""
        return sorted(self._plugins.keys())


# Singleton-Instanz
plugins = PluginRegistry()
