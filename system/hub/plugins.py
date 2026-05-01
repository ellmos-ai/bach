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
Plugins Handler - Plugin-Verwaltung fuer BACH
==============================================

bach plugins list              Alle geladenen Plugins anzeigen
bach plugins inspect <pfad>    Manifest-Metadaten ohne Runtime-Load pruefen
bach plugins load <pfad>       Plugin aus plugin.json laden
bach plugins unload <name>     Plugin entladen
bach plugins tools             Alle Plugin-Tools anzeigen
bach plugins info <name>       Details zu einem Plugin
bach plugins create <name>     Plugin-Manifest erstellen (Scaffolding)
bach plugins caps              Capability-Profile aller Plugins
bach plugins trust <name> <l>  Trust-Level eines Plugins aendern
bach plugins audit             Letzte Capability-Pruefungen anzeigen
"""
from pathlib import Path
from .base import BaseHandler


class PluginsHandler(BaseHandler):
    """Handler fuer bach plugins ..."""

    def __init__(self, base_path: Path):
        super().__init__(base_path)

    @property
    def profile_name(self) -> str:
        return "plugins"

    @property
    def target_file(self) -> Path:
        return self.base_path / "core" / "plugin_api.py"

    def get_operations(self) -> dict:
        return {
            "list": "Alle geladenen Plugins anzeigen",
            "inspect": "Manifest-Metadaten ohne Runtime-Load pruefen",
            "load": "Plugin aus plugin.json laden",
            "unload": "Plugin entladen",
            "tools": "Alle Plugin-Tools anzeigen",
            "info": "Details zu einem Plugin",
            "create": "Plugin-Manifest erstellen (Scaffolding)",
            "caps": "Capability-Profile aller Plugins anzeigen",
            "trust": "Trust-Level eines Plugins aendern",
            "audit": "Letzte Capability-Pruefungen anzeigen",
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        from core.plugin_api import plugins

        if operation == "list" or not operation:
            return True, plugins.list_plugins()

        elif operation == "inspect" and args:
            manifest_path = args[0]
            p = Path(manifest_path)
            if not p.is_absolute():
                p = self.base_path / p
            return plugins.inspect_plugin(str(p))

        elif operation == "load" and args:
            manifest_path = args[0]
            # Relative Pfade aufloesen
            p = Path(manifest_path)
            if not p.is_absolute():
                p = self.base_path / p
            return plugins.load_plugin(str(p))

        elif operation == "unload" and args:
            return plugins.unload_plugin(args[0])

        elif operation == "tools":
            return self._list_tools(plugins)

        elif operation == "info" and args:
            return self._plugin_info(plugins, args[0])

        elif operation == "create":
            name = args[0] if args else "my-plugin"
            return self._create_manifest(name, dry_run)

        elif operation == "caps":
            return self._show_caps()

        elif operation == "trust" and len(args) >= 2:
            return self._change_trust(args[0], args[1])

        elif operation == "audit":
            limit = int(args[0]) if args else 20
            return self._show_audit(limit)

        else:
            return False, (
                "Usage: bach plugins [list|inspect|load|unload|tools|info|create|caps|trust|audit]\n"
                "  bach plugins inspect <pfad>    Manifest ohne Runtime-Load pruefen\n"
                "  bach plugins caps              Capability-Profile anzeigen\n"
                "  bach plugins trust <name> <l>  Trust-Level aendern\n"
                "  bach plugins audit [limit]     Audit-Log anzeigen"
            )

    def _list_tools(self, plugins) -> tuple:
        """Zeigt alle ueber Plugin-API registrierten Tools."""
        if not plugins.tool_names:
            return True, "Keine Plugin-Tools registriert.\n\nTools registrieren:\n  from core.plugin_api import plugins\n  plugins.register_tool('name', funktion, 'Beschreibung')"

        lines = ["PLUGIN-TOOLS", "=" * 50]
        for name in plugins.tool_names:
            info = plugins._tools[name]
            desc = info.get('description', '')[:40]
            plugin = info.get('plugin', '?')
            lines.append(f"  {name:<25} [{plugin}] {desc}")

        lines.append(f"\nGesamt: {len(plugins.tool_names)} Tools")
        return True, "\n".join(lines)

    def _plugin_info(self, plugins, name: str) -> tuple:
        """Zeigt Details zu einem Plugin."""
        if name not in plugins._plugins:
            return False, f"Plugin '{name}' nicht gefunden.\nGeladene: {', '.join(plugins.plugin_names) or 'keine'}"

        info = plugins._plugins[name]
        lines = [
            f"PLUGIN: {name}",
            "=" * 50,
            f"  Version:     {info.get('version', '?')}",
            f"  Beschreibung: {info.get('description', '-')}",
            f"  Autor:       {info.get('author', '?')}",
            f"  Geladen:     {info.get('loaded_at', '?')[:19]}",
        ]

        if info.get('manifest_path'):
            lines.append(f"  Manifest:    {info['manifest_path']}")

        activation = info.get('activation')
        if activation:
            if isinstance(activation, dict):
                mode = activation.get('mode', 'manual')
                enabled = activation.get('enabled', True)
                lines.append(f"  Aktivierung: {mode} (enabled={enabled})")
            else:
                lines.append(f"  Aktivierung: {activation}")

        providers = info.get('providers', [])
        models = info.get('models', [])
        if providers:
            lines.append(f"  Provider:    {len(providers)} manifest-backed")
        if models:
            lines.append(f"  Modelle:     {len(models)} manifest-backed")

        hooks = info.get('hooks', [])
        if hooks:
            lines.append(f"\n  Hooks ({len(hooks)}):")
            for h in hooks:
                lines.append(f"    - {h}")

        handlers = info.get('handlers', [])
        if handlers:
            lines.append(f"\n  Handler ({len(handlers)}):")
            for h in handlers:
                lines.append(f"    - bach {h}")

        workflows = info.get('workflows', [])
        if workflows:
            lines.append(f"\n  Workflows ({len(workflows)}):")
            for w in workflows:
                lines.append(f"    - {w}")

        return True, "\n".join(lines)

    def _show_caps(self) -> tuple:
        """Zeigt Capability-Profile und Plugin-Zuordnungen."""
        from core.capabilities import capability_manager
        return True, capability_manager.get_profiles() + "\n\n" + capability_manager.status()

    def _change_trust(self, name: str, level: str) -> tuple:
        """Aendert das Trust-Level eines Plugins."""
        from core.capabilities import capability_manager
        return capability_manager.set_plugin_trust(name, level)

    def _show_audit(self, limit: int = 20) -> tuple:
        """Zeigt letzte Capability-Pruefungen."""
        from core.capabilities import capability_manager
        return True, capability_manager.get_audit_log(limit)

    def _create_manifest(self, name: str, dry_run: bool) -> tuple:
        """Erstellt ein plugin.json Scaffolding."""
        import json

        plugin_dir = self.base_path / "plugins" / name
        manifest_path = plugin_dir / "plugin.json"

        if manifest_path.exists():
            return False, f"Plugin '{name}' existiert bereits: {manifest_path}"

        manifest = {
            "name": name,
            "manifest_version": "1.1",
            "version": "0.1.0",
            "description": f"BACH Plugin: {name}",
            "author": "claude",
            "source": "goldstandard",
            "capabilities": ["db_read", "hook_listen"],
            "activation": {
                "mode": "manual",
                "enabled": True
            },
            "providers": [],
            "models": [],
            "setup": {
                "requires": [],
                "env": [],
                "notes": ""
            },
            "hooks": [
                {
                    "event": "after_startup",
                    "module": "handlers.py",
                    "handler": "on_startup",
                    "priority": 50
                }
            ],
            "handlers": [],
            "workflows": []
        }

        handler_template = '''"""
Plugin-Handler fuer {name}
"""

def on_startup(context):
    """Wird nach jedem Startup aufgerufen."""
    partner = context.get('partner', 'unknown')
    print(f"[{name}] Startup erkannt: {{partner}}")
    return None
'''.format(name=name)

        if dry_run:
            return True, f"[DRY-RUN] Wuerde erstellen:\n  {manifest_path}\n  {plugin_dir / 'handlers.py'}"

        plugin_dir.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )
        (plugin_dir / "handlers.py").write_text(handler_template, encoding='utf-8')

        return True, (
            f"[OK] Plugin-Manifest erstellt: {manifest_path}\n"
            f"  Naechste Schritte:\n"
            f"  1. {manifest_path} bearbeiten (Hooks/Handler konfigurieren)\n"
            f"  2. handlers.py implementieren\n"
            f"  3. bach plugins load plugins/{name}/plugin.json"
        )
