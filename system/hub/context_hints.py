# SPDX-License-Identifier: MIT
"""Neutrale Dokumentationsverweise für manuelle Hinweise im Chat.

Die gespeicherte Regel und ihre Freigabe bleiben unverändert. Unbekannte
Befehle werden nicht umgedeutet; der vorhandene API-Filter entscheidet weiter.
"""
import re
from pathlib import Path

CLI_PATTERN = re.compile(r'bach\s+\w+|--\w+|\bpython(?:3)?\s+["\']?[^\s"\']+\.py\b')
_REFERENCES = re.compile(
    r'\bbach\s+(?P<command>[a-zA-Z_][a-zA-Z_0-9-]*)'
    r'|--help\s+(?P<help>[a-zA-Z_][a-zA-Z_0-9-]*)'
    r'|\bpython\s+(?P<python>[a-zA-Z_0-9./-]+\.py)')
_TOOLS = {
    'c_encoding_fixer': 'tools/file_ops/encoding_fixer.py',
}
_HELP_ALIASES = {'dirs': 'bach_paths', 'practices': 'lessons'}


def neutral_manual_hint(hint: str, system_root: Path) -> str:
    """Ersetzt bekannte CLI-Verweise durch vorhandene lokale Dokumente.

    Nur relative Pfade innerhalb des Systems sind gültige Ziele. Bei einem
    unbekannten oder fehlenden Ziel bleibt der gesamte Hinweis unverändert.
    """
    matches = list(_REFERENCES.finditer(hint))
    if not matches:
        return hint
    root = Path(system_root).resolve()
    targets = []
    for match in matches:
        command = match['command'] or match['help']
        if command:
            target = _TOOLS.get(command, f'docs/help/{_HELP_ALIASES.get(command, command)}.txt')
            if not (root / target).is_file() and (root / f'docs/help/tools/{command}.txt').is_file():
                target = f'docs/help/tools/{command}.txt'
        else:
            target = match['python']
            target = target.removeprefix('system/')
        candidate = (root / target).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            return hint
        if target not in targets:
            targets.append(target)
    label = hint[:matches[0].start()].strip().rstrip(':|').strip()
    if CLI_PATTERN.search(label):
        return hint
    return (label + ' – ' if label else '') + 'Dokumentation: ' + ' | '.join(targets)


class ChatTriggerBackend:
    """Pro Aufruf eigener Adapter, ohne veränderlichen Modus am Backend."""

    def __init__(self, backend, system_root: Path):
        self.backend = backend
        self.system_root = system_root

    def __getattr__(self, name):
        return getattr(self.backend, name)

    def triggers(self, sources, agent_id='default'):
        from dataclasses import replace
        return [replace(rule, hint=neutral_manual_hint(rule.hint, self.system_root))
                if rule.source == 'manual' else rule
                for rule in self.backend.triggers(sources, agent_id=agent_id)]
