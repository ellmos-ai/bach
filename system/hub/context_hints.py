# SPDX-License-Identifier: MIT
"""Neutrale Dokumentationsverweise für manuelle Hinweise im Chat.

Die gespeicherte Regel und ihre Freigabe bleiben unverändert. Unbekannte
Befehle werden nicht umgedeutet; der vorhandene API-Filter entscheidet weiter.
"""
import re
from pathlib import Path

# Detect full option names and every Python invocation, even if its path cannot
# be parsed. A known prefix must never hide an unresolvable command later on.
CLI_PATTERN = re.compile(r'\bbach\s+\w+|--[\w-]+|\bpython(?:3)?\s+')
_REFERENCES = re.compile(
    r'\bbach\s+(?P<command>[a-zA-Z_][a-zA-Z_0-9-]*)'
    r'|--help\s+(?P<help>[a-zA-Z_][a-zA-Z_0-9-]*)'
    r'|\bpython(?:3)?\s+(?P<python>"[^"\r\n]+"|\'[^\'\r\n]+\'|[^\s"\'|;&]+)(?=$|[\s|;&])')
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
    resolved = []
    for match in matches:
        command = match['command'] or match['help']
        if command:
            target = _TOOLS.get(command, f'docs/help/{_HELP_ALIASES.get(command, command)}.txt')
            if not (root / target).is_file() and (root / f'docs/help/tools/{command}.txt').is_file():
                target = f'docs/help/tools/{command}.txt'
        else:
            target = match['python']
            if target.startswith(('"', "'")):
                target = target[1:-1]
            target = target.removeprefix('system/')
            # Validate the entire argument, including suffixes after a .py
            # prefix. A quoted prefix followed by more text is not a token.
            if not target.endswith('.py') or Path(target).is_absolute():
                return hint
        try:
            candidate = (root / target).resolve()
            valid = candidate.is_relative_to(root) and candidate.is_file()
        except (OSError, ValueError):
            return hint
        if not valid:
            return hint
        if target not in targets:
            targets.append(target)
        resolved.append((match, candidate))

    # Every marker must belong to a resolved reference, or to an option
    # documented by that exact reference in the same command segment.
    for marker in CLI_PATTERN.finditer(hint):
        if any(reference.start() <= marker.start() and marker.end() <= reference.end()
               for reference, _ in resolved):
            continue
        if not marker[0].startswith('--'):
            return hint
        owner = next(((reference, candidate) for reference, candidate in reversed(resolved)
                      if reference.end() <= marker.start()), None)
        if owner is None or re.search(r'[|;\n\r]', hint[owner[0].end():marker.start()]):
            return hint
        try:
            documentation = owner[1].read_text(encoding='utf-8')
        except (OSError, UnicodeError):
            return hint
        if not re.search(r'(?<![\w-])' + re.escape(marker[0]) + r'(?![\w-])', documentation):
            return hint
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
