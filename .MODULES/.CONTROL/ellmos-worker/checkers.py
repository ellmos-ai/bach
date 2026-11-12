# MODUL-ZUORDNUNG: Inhaltsschutz vor Werkzeugaufrufen
# SPDX-License-Identifier: MIT
# Herkunft: SentinelFleet (AGPL-3.0, commit e7f9c748); durch alleinigen
# Rechteinhaber Lukas unter MIT neu lizenziert; siehe NOTICE im Modulordner.

"""Prüf-Checker der ellmos-worker-Prüfkette.

QuarantineChecker: nur explizit freigegebene Werkzeuge dürfen passieren.
ScopeChecker: Werkzeug muss einem erlaubten Scope zugeordnet sein.
ContentGuardChecker: Argumenttexte dürfen keine blockierten Muster enthalten.
PermissionAdapter: externe Erlaubnis-Entscheidung ("allow"/"deny"), strikt
fail-closed bei fehlendem Evaluator, Ausnahmen oder anderem Ergebnis.
"""

from __future__ import annotations

import json
import re
from collections import namedtuple

CheckOutcome = namedtuple("CheckOutcome", ["ok", "detail"])

DEFAULT_PATTERNS = [
    ("rm-rf", r"\brm\s+-[a-zA-Z]*(?:r[a-zA-Z]*f|f[a-zA-Z]*r)"),
    ("sudo", r"\bsudo\b"),
    ("eval", r"\beval\b"),
    ("exec", r"\bexec\b"),
    ("base64-decode", r"\bbase64\s+(?:-[a-zA-Z]*d|--decode)\b"),
    ("shutdown", r"\bshutdown\b"),
    ("chmod-777", r"\bchmod\s+777\b"),
    ("etc-passwd", r"/etc/passwd"),
    ("curl-pipe-shell", r"\bcurl[^\n]{0,200}\|\s*(?:ba|z|da)?sh\b"),
]


class Checker:
    """Basisklasse einer Prüfstufe."""

    def check(self, tool_name, args):
        raise NotImplementedError("Checker.check muss implementiert werden")


class QuarantineChecker(Checker):
    """Prüfstufe 1: Werkzeug-Freigabeliste (Whitelist)."""

    def __init__(self, allowed_tools):
        self.allowed_tools = {str(t).strip().lower() for t in allowed_tools}

    def check(self, tool_name, args):
        if not isinstance(tool_name, str) or not tool_name.strip():
            return CheckOutcome(False, "quarantine: ungültiger Werkzeugname")
        if tool_name.strip().lower() in self.allowed_tools:
            return CheckOutcome(True, None)
        return CheckOutcome(False, "quarantine: Werkzeug '%s' nicht freigegeben" % tool_name.strip())


class ScopeChecker(Checker):
    """Prüfstufe 2: Werkzeug gehört einem erlaubten Scope an."""

    def __init__(self, scope_map, allowed_scopes):
        self.scope_map = {str(k).strip().lower(): str(v) for k, v in scope_map.items()}
        self.allowed_scopes = {str(s).strip().lower() for s in allowed_scopes}

    def check(self, tool_name, args):
        key = str(tool_name).strip().lower()
        scope = self.scope_map.get(key, "default")
        if str(scope).strip().lower() in self.allowed_scopes:
            return CheckOutcome(True, None)
        return CheckOutcome(False, "scope: Werkzeug '%s' gehört Scope '%s', der nicht freigegeben ist" % (key, scope))


class ContentGuardChecker(Checker):
    """Prüfstufe 3: Argumenttexte gegen blockierte Muster."""

    def __init__(self, patterns=None):
        quelle = DEFAULT_PATTERNS if patterns is None else patterns
        self.patterns = [(label, re.compile(regex, re.IGNORECASE)) for label, regex in quelle]

    def _scan_text(self, args):
        if isinstance(args, str):
            return args
        try:
            return json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return str(args)

    def check(self, tool_name, args):
        text = self._scan_text(args)
        for label, muster in self.patterns:
            if muster.search(text):
                return CheckOutcome(False, "content-guard: blockiertes Muster '%s' erkannt" % label)
        return CheckOutcome(True, None)


class PermissionAdapter(Checker):
    """Prüfstufe 4: externe Erlaubnis-Entscheidung, fail-closed."""

    def __init__(self, evaluate):
        self.evaluate = evaluate

    def check(self, tool_name, args):
        if self.evaluate is None:
            return CheckOutcome(False, "permission: kein Erlaubnis-Evaluator konfiguriert")
        try:
            decision = self.evaluate(tool_name, args)
        except Exception as exc:
            return CheckOutcome(False, "permission: Evaluator-Ausnahme: %r" % exc)
        if isinstance(decision, str) and decision.strip().lower() == "allow":
            return CheckOutcome(True, None)
        return CheckOutcome(False, "permission: Entscheidung %r != 'allow'" % decision)