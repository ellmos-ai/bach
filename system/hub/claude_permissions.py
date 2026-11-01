# SPDX-License-Identifier: MIT
"""
Claude Permissions Handler - Permission-Profile fuer Claude Code verwalten
==========================================================================

bach permissions list                    Alle Profile anzeigen
bach permissions show <profil>           Profil-Details anzeigen
bach permissions set <profil> <regel>    Regel hinzufuegen (z.B. allow=Bash(*))
bach permissions remove <profil> <regel> Regel entfernen
bach permissions activate <profil>       Profil in ~/.claude/settings.json schreiben
bach permissions sync                    Aktuelle settings.json in DB importieren
bach permissions reset <profil>          Profil auf Defaults zuruecksetzen

Profile:
  normal          - Standard-Permissions (fragt bei kritischen Tools)
  remote_control  - Bypass-Permissions fuer Remote Control (Mobile App)

Die Profile werden in system_config gespeichert (category=claude_permissions).
Bei Aktivierung wird ~/.claude/settings.json temporaer angepasst.
"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from .base import BaseHandler

SETTINGS_PATH = Path(os.path.expanduser("~/.claude/settings.json"))

# Kategorie in system_config
CATEGORY = "claude_permissions"

# DB-Keys
KEY_PROFILE_PREFIX = "claude.permissions.profile."
KEY_ACTIVE_PROFILE = "claude.permissions.active_profile"
KEY_BACKUP_PERMISSIONS = "claude.permissions.backup"

# Default-Profile
DEFAULT_PROFILES = {
    "normal": {
        "description": "Standard-Permissions (fragt bei kritischen Tools)",
        "allow": [],
        "deny": [],
    },
    "remote_control": {
        "description": "Bypass-Permissions fuer Remote Control (Mobile App)",
        "allow": [
            "Bash(*)",
            "Read",
            "Write",
            "Edit",
            "Glob",
            "Grep",
            "Agent",
            "WebSearch",
            "WebFetch",
            "NotebookEdit",
            "mcp__ellmos-codecommander-mcp__*",
            "mcp__ellmos-filecommander-mcp__*",
            "mcp__claude_ai_Gmail__*",
            "mcp__claude_ai_Google_Calendar__*",
            "mcp__claude_ai_Mermaid_Chart__*",
            "mcp__claude_ai_PubMed__*",
            "mcp__n8n-manager-mcp__*",
        ],
        "deny": [],
    },
}


class ClaudePermissionsHandler(BaseHandler):
    """Handler fuer bach permissions Operationen."""

    def __init__(self, base_path):
        super().__init__(base_path)
        from .bach_paths import BACH_DB
        self.db_path = BACH_DB

    @property
    def profile_name(self) -> str:
        return "permissions"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "list": "Alle Permission-Profile anzeigen",
            "show": "Profil-Details: show <profil>",
            "set": "Regel hinzufuegen: set <profil> allow=Tool oder deny=Tool",
            "remove": "Regel entfernen: remove <profil> allow=Tool oder deny=Tool",
            "activate": "Profil aktivieren: activate <profil>",
            "deactivate": "Zum Normal-Profil zurueckkehren",
            "sync": "Aktuelle settings.json in DB importieren",
            "reset": "Profil auf Defaults: reset <profil>",
            "status": "Aktuellen Status anzeigen",
            "init": "Default-Profile in DB anlegen",
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation == "list":
            return self._list()
        elif operation == "show" and args:
            return self._show(args[0])
        elif operation == "set" and len(args) >= 2:
            return self._set_rule(args[0], args[1:], dry_run)
        elif operation == "remove" and len(args) >= 2:
            return self._remove_rule(args[0], args[1:], dry_run)
        elif operation == "activate" and args:
            return self._activate(args[0], dry_run)
        elif operation == "deactivate":
            return self._deactivate(dry_run)
        elif operation == "sync":
            return self._sync(dry_run)
        elif operation == "reset" and args:
            return self._reset_profile(args[0], dry_run)
        elif operation == "status":
            return self._status()
        elif operation == "init":
            return self._init_defaults(dry_run)
        else:
            ops = self.get_operations()
            lines = ["PERMISSIONS - Claude Code Permission-Profile", "=" * 55, ""]
            for op, desc in ops.items():
                lines.append(f"  bach permissions {op:14s} {desc}")
            return True, "\n".join(lines)

    # ------------------------------------------------------------------
    # DB-Zugriff
    # ------------------------------------------------------------------

    def _get_conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _db_get(self, key: str) -> str | None:
        """Liest einen Wert aus system_config."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT value FROM system_config WHERE key = ?", (key,)
        ).fetchone()
        conn.close()
        return row["value"] if row else None

    def _db_set(self, key: str, value: str, description: str = None):
        """Schreibt einen Wert in system_config."""
        conn = self._get_conn()
        now = datetime.now().isoformat()
        existing = conn.execute(
            "SELECT key FROM system_config WHERE key = ?", (key,)
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE system_config SET value = ?, updated_at = ? WHERE key = ?",
                (value, now, key),
            )
        else:
            conn.execute(
                "INSERT INTO system_config (key, value, type, category, description, updated_at, dist_type) "
                "VALUES (?, ?, 'json', ?, ?, ?, 0)",
                (key, value, CATEGORY, description, now),
            )
        conn.commit()
        conn.close()

    def _get_profile(self, name: str) -> dict | None:
        """Liest ein Profil aus der DB."""
        raw = self._db_get(KEY_PROFILE_PREFIX + name)
        if raw:
            return json.loads(raw)
        return None

    def _save_profile(self, name: str, profile: dict):
        """Speichert ein Profil in der DB."""
        desc = profile.get("description", f"Permission-Profil: {name}")
        self._db_set(
            KEY_PROFILE_PREFIX + name,
            json.dumps(profile, ensure_ascii=False),
            desc,
        )

    def _get_profile_names(self) -> list:
        """Gibt alle Profil-Namen zurueck."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT key FROM system_config WHERE key LIKE ? AND category = ?",
            (KEY_PROFILE_PREFIX + "%", CATEGORY),
        ).fetchall()
        conn.close()
        prefix_len = len(KEY_PROFILE_PREFIX)
        return [row["key"][prefix_len:] for row in rows]

    def _get_active_profile_name(self) -> str:
        """Gibt den Namen des aktiven Profils zurueck."""
        return self._db_get(KEY_ACTIVE_PROFILE) or "normal"

    # ------------------------------------------------------------------
    # Settings.json Manipulation
    # ------------------------------------------------------------------

    def _read_settings(self) -> dict:
        """Liest ~/.claude/settings.json."""
        if SETTINGS_PATH.exists():
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return {}

    def _write_settings(self, settings: dict):
        """Schreibt ~/.claude/settings.json."""
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _apply_profile_to_settings(self, profile: dict, settings: dict) -> dict:
        """Wendet ein Profil auf die settings.json Struktur an."""
        if "permissions" not in settings:
            settings["permissions"] = {}

        perms = settings["permissions"]

        # Allow-Regeln setzen (leere Liste = keine allow-Regeln)
        allow_rules = profile.get("allow", [])
        if allow_rules:
            perms["allow"] = allow_rules
        elif "allow" in perms:
            del perms["allow"]

        # Deny-Regeln setzen
        deny_rules = profile.get("deny", [])
        if deny_rules:
            perms["deny"] = deny_rules
        elif "deny" in perms:
            del perms["deny"]

        return settings

    # ------------------------------------------------------------------
    # Operationen
    # ------------------------------------------------------------------

    def _list(self) -> tuple:
        names = self._get_profile_names()
        if not names:
            return True, (
                "Keine Profile gefunden.\n"
                "Fuehre 'bach permissions init' aus um Defaults anzulegen."
            )

        active = self._get_active_profile_name()
        lines = ["PERMISSION-PROFILE", "=" * 55, ""]

        for name in sorted(names):
            profile = self._get_profile(name)
            if not profile:
                continue
            marker = " [AKTIV]" if name == active else ""
            desc = profile.get("description", "")
            n_allow = len(profile.get("allow", []))
            n_deny = len(profile.get("deny", []))
            lines.append(f"  {name:20s} {n_allow} allow, {n_deny} deny{marker}")
            if desc:
                lines.append(f"  {'':20s} {desc}")
            lines.append("")

        return True, "\n".join(lines)

    def _show(self, name: str) -> tuple:
        profile = self._get_profile(name)
        if not profile:
            return False, f"Profil '{name}' nicht gefunden."

        active = self._get_active_profile_name()
        lines = [
            f"PROFIL: {name}" + (" [AKTIV]" if name == active else ""),
            "=" * 55,
            f"Beschreibung: {profile.get('description', '-')}",
            "",
        ]

        allow = profile.get("allow", [])
        if allow:
            lines.append("Allow-Regeln:")
            for rule in sorted(allow):
                lines.append(f"  + {rule}")
        else:
            lines.append("Allow-Regeln: (keine)")

        lines.append("")

        deny = profile.get("deny", [])
        if deny:
            lines.append("Deny-Regeln:")
            for rule in sorted(deny):
                lines.append(f"  - {rule}")
        else:
            lines.append("Deny-Regeln: (keine)")

        return True, "\n".join(lines)

    def _set_rule(self, name: str, args: list, dry_run: bool) -> tuple:
        """Regel zu einem Profil hinzufuegen. Format: allow=Tool oder deny=Tool."""
        profile = self._get_profile(name)
        if not profile:
            return False, f"Profil '{name}' nicht gefunden."

        added = []
        for arg in args:
            if "=" not in arg:
                return False, f"Ungueltiges Format: '{arg}'. Erwartet: allow=Tool oder deny=Tool"
            rule_type, tool = arg.split("=", 1)
            rule_type = rule_type.strip().lower()
            tool = tool.strip()
            if rule_type not in ("allow", "deny"):
                return False, f"Unbekannter Regel-Typ: '{rule_type}'. Erlaubt: allow, deny"
            if tool not in profile.get(rule_type, []):
                profile.setdefault(rule_type, []).append(tool)
                added.append(f"{rule_type}={tool}")

        if not added:
            return True, "Keine neuen Regeln (bereits vorhanden)."

        if dry_run:
            return True, f"[DRY-RUN] Wuerde hinzufuegen: {', '.join(added)}"

        self._save_profile(name, profile)

        # Wenn aktives Profil geaendert -> settings.json aktualisieren
        if name == self._get_active_profile_name():
            settings = self._read_settings()
            settings = self._apply_profile_to_settings(profile, settings)
            self._write_settings(settings)

        return True, f"[OK] Regeln hinzugefuegt zu '{name}': {', '.join(added)}"

    def _remove_rule(self, name: str, args: list, dry_run: bool) -> tuple:
        """Regel aus einem Profil entfernen."""
        profile = self._get_profile(name)
        if not profile:
            return False, f"Profil '{name}' nicht gefunden."

        removed = []
        for arg in args:
            if "=" not in arg:
                return False, f"Ungueltiges Format: '{arg}'."
            rule_type, tool = arg.split("=", 1)
            rule_type = rule_type.strip().lower()
            tool = tool.strip()
            if rule_type in ("allow", "deny") and tool in profile.get(rule_type, []):
                profile[rule_type].remove(tool)
                removed.append(f"{rule_type}={tool}")

        if not removed:
            return True, "Keine Regeln entfernt (nicht gefunden)."

        if dry_run:
            return True, f"[DRY-RUN] Wuerde entfernen: {', '.join(removed)}"

        self._save_profile(name, profile)

        if name == self._get_active_profile_name():
            settings = self._read_settings()
            settings = self._apply_profile_to_settings(profile, settings)
            self._write_settings(settings)

        return True, f"[OK] Regeln entfernt aus '{name}': {', '.join(removed)}"

    def _activate(self, name: str, dry_run: bool) -> tuple:
        """Profil aktivieren: Backup der aktuellen Permissions, dann Profil anwenden."""
        profile = self._get_profile(name)
        if not profile:
            return False, f"Profil '{name}' nicht gefunden."

        if dry_run:
            return True, f"[DRY-RUN] Wuerde Profil '{name}' aktivieren."

        # Aktuelle Permissions als Backup speichern
        settings = self._read_settings()
        current_perms = settings.get("permissions", {})
        self._db_set(
            KEY_BACKUP_PERMISSIONS,
            json.dumps(current_perms, ensure_ascii=False),
            "Backup der Permissions vor Profil-Wechsel",
        )

        # Profil anwenden
        settings = self._apply_profile_to_settings(profile, settings)
        self._write_settings(settings)

        # Aktives Profil merken
        self._db_set(KEY_ACTIVE_PROFILE, name, "Aktuell aktives Permission-Profil")

        n_allow = len(profile.get("allow", []))
        n_deny = len(profile.get("deny", []))
        return True, (
            f"[OK] Profil '{name}' aktiviert ({n_allow} allow, {n_deny} deny)\n"
            f"     Backup der vorherigen Permissions gespeichert."
        )

    def _deactivate(self, dry_run: bool) -> tuple:
        """Zurueck zum Normal-Profil (stellt Backup wieder her)."""
        backup_raw = self._db_get(KEY_BACKUP_PERMISSIONS)

        if dry_run:
            return True, "[DRY-RUN] Wuerde zum Normal-Profil zurueckkehren."

        settings = self._read_settings()

        if backup_raw:
            # Backup wiederherstellen
            backup_perms = json.loads(backup_raw)
            settings["permissions"] = backup_perms
        else:
            # Kein Backup -> Normal-Profil anwenden
            normal = self._get_profile("normal")
            if normal:
                settings = self._apply_profile_to_settings(normal, settings)
            elif "allow" in settings.get("permissions", {}):
                del settings["permissions"]["allow"]

        self._write_settings(settings)
        self._db_set(KEY_ACTIVE_PROFILE, "normal", "Aktuell aktives Permission-Profil")

        return True, "[OK] Zum Normal-Profil zurueckgekehrt. Permissions wiederhergestellt."

    def _sync(self, dry_run: bool) -> tuple:
        """Aktuelle settings.json als Profil in DB importieren."""
        settings = self._read_settings()
        perms = settings.get("permissions", {})

        allow = perms.get("allow", [])
        deny = perms.get("deny", [])

        active = self._get_active_profile_name()
        profile = self._get_profile(active) or {"description": f"Synchronisiert aus settings.json"}
        profile["allow"] = allow
        profile["deny"] = deny

        if dry_run:
            return True, (
                f"[DRY-RUN] Wuerde '{active}' synchronisieren:\n"
                f"  {len(allow)} allow, {len(deny)} deny Regeln"
            )

        self._save_profile(active, profile)
        return True, (
            f"[OK] Profil '{active}' aus settings.json synchronisiert:\n"
            f"     {len(allow)} allow, {len(deny)} deny Regeln"
        )

    def _reset_profile(self, name: str, dry_run: bool) -> tuple:
        """Profil auf Defaults zuruecksetzen."""
        if name not in DEFAULT_PROFILES:
            return False, (
                f"Kein Default fuer Profil '{name}'.\n"
                f"Verfuegbare Defaults: {', '.join(DEFAULT_PROFILES.keys())}"
            )

        if dry_run:
            return True, f"[DRY-RUN] Wuerde Profil '{name}' auf Defaults zuruecksetzen."

        self._save_profile(name, DEFAULT_PROFILES[name].copy())

        # Wenn aktives Profil -> auch settings.json aktualisieren
        if name == self._get_active_profile_name():
            settings = self._read_settings()
            settings = self._apply_profile_to_settings(DEFAULT_PROFILES[name], settings)
            self._write_settings(settings)

        n_allow = len(DEFAULT_PROFILES[name].get("allow", []))
        return True, f"[OK] Profil '{name}' auf Defaults zurueckgesetzt ({n_allow} allow-Regeln)"

    def _status(self) -> tuple:
        """Zeigt den aktuellen Status an."""
        active = self._get_active_profile_name()
        profile = self._get_profile(active)

        # settings.json lesen
        settings = self._read_settings()
        live_allow = settings.get("permissions", {}).get("allow", [])
        live_deny = settings.get("permissions", {}).get("deny", [])

        lines = [
            "CLAUDE PERMISSIONS STATUS",
            "=" * 55,
            f"Aktives Profil:   {active}",
            f"Settings-Datei:   {SETTINGS_PATH}",
            "",
            f"Live in settings.json:",
            f"  Allow-Regeln:   {len(live_allow)}",
            f"  Deny-Regeln:    {len(live_deny)}",
        ]

        if profile:
            db_allow = profile.get("allow", [])
            db_deny = profile.get("deny", [])
            in_sync = set(live_allow) == set(db_allow) and set(live_deny) == set(db_deny)
            lines.append("")
            lines.append(f"In BACH-DB (Profil '{active}'):")
            lines.append(f"  Allow-Regeln:   {len(db_allow)}")
            lines.append(f"  Deny-Regeln:    {len(db_deny)}")
            lines.append("")
            lines.append(f"Synchron:         {'Ja' if in_sync else 'NEIN (bach permissions sync ausfuehren)'}")

        # Backup vorhanden?
        backup = self._db_get(KEY_BACKUP_PERMISSIONS)
        if backup:
            lines.append("")
            lines.append("Backup:           Vorhanden (von vorherigem Profil-Wechsel)")

        return True, "\n".join(lines)

    def _init_defaults(self, dry_run: bool) -> tuple:
        """Default-Profile in DB anlegen (idempotent)."""
        created = []
        skipped = []

        for name, profile in DEFAULT_PROFILES.items():
            existing = self._get_profile(name)
            if existing:
                skipped.append(name)
                continue
            if not dry_run:
                self._save_profile(name, profile.copy())
            created.append(name)

        if not dry_run:
            # Aktives Profil setzen falls noch nicht vorhanden
            if not self._db_get(KEY_ACTIVE_PROFILE):
                self._db_set(KEY_ACTIVE_PROFILE, "normal", "Aktuell aktives Permission-Profil")

        lines = ["Default-Profile initialisiert:"]
        if created:
            lines.append(f"  Erstellt:    {', '.join(created)}")
        if skipped:
            lines.append(f"  Vorhanden:   {', '.join(skipped)}")

        prefix = "[DRY-RUN] " if dry_run else "[OK] "
        return True, prefix + "\n".join(lines)


# ------------------------------------------------------------------
# Programmatischer Zugriff (fuer claude_remote_control.py)
# ------------------------------------------------------------------

def activate_remote_control() -> tuple:
    """Aktiviert das Remote-Control-Profil. Gibt (success, message) zurueck."""
    import sys
    base = Path(__file__).parent.parent
    if str(base) not in sys.path:
        sys.path.insert(0, str(base))
    handler = ClaudePermissionsHandler(base)

    # Defaults anlegen falls noetig
    if not handler._get_profile("remote_control"):
        handler._init_defaults(dry_run=False)

    return handler._activate("remote_control", dry_run=False)


def deactivate_remote_control() -> tuple:
    """Deaktiviert Remote-Control, stellt Normal-Profil wieder her."""
    import sys
    base = Path(__file__).parent.parent
    if str(base) not in sys.path:
        sys.path.insert(0, str(base))
    handler = ClaudePermissionsHandler(base)
    return handler._deactivate(dry_run=False)


# ------------------------------------------------------------------
# Einheitliche Permission-Bewertung (fuer Control Center / ellmos-worker)
# ------------------------------------------------------------------

def _permission_rule_matches(rule, tool: str, target: str) -> bool:
    """Prueft, ob eine Permission-Regel (fnmatch-Muster) auf ein Werkzeug passt.

    Regeln haben das Format der Claude-Permissions, z.B. "Bash(*)", "Read",
    "mcp__ellmos-codecommander-mcp__*". Gross-/Kleinschreibung wird ignoriert.
    """
    import fnmatch

    if not isinstance(rule, str):
        return False
    pattern = rule.strip()
    if not pattern:
        return False
    pattern_lower = pattern.lower()
    tool_lower = tool.lower()
    target_lower = target.lower()

    # Exakter Tool-Name ("Read" passt auf "Read", nicht auf "ReadFile")
    if fnmatch.fnmatchcase(tool_lower, pattern_lower):
        return True
    # Komplettes Ziel inkl. Argumente ("Bash(*)" passt auf "Bash(ls -la)")
    if fnmatch.fnmatchcase(target_lower, pattern_lower):
        return True
    # Argument-Muster ohne uebergebene Argumente ("Bash(*)" passt auf "Bash")
    if pattern_lower.endswith("(*)"):
        base_pattern = pattern_lower[:-3].strip()
        if tool_lower == base_pattern:
            return True
    return False


def controlcenter_evaluate_permission(tool_name, args=None) -> str:
    """Bewertet einen Werkzeugaufruf gegen das aktive Permission-Profil.

    Diese Funktion ist der einheitliche Erlaubnis-Punkt im BACH-Kern und wird
    von der ellmos-worker-Verifikationskette (Permission-Adapter) aufgerufen.

    Rueckgabe: "allow" oder "deny".
    Fail-closed: Bei ungueltiger Eingabe, fehlendem Profil oder jedem anderen
    Fehler wird "deny" geliefert - niemals eine unbestaetigte Erlaubnis.
    """
    import sys

    try:
        # Eingabepruefung: nur nicht-leere Strings koennen erlaubt werden
        if not isinstance(tool_name, str) or not tool_name.strip():
            return "deny"
        tool = tool_name.strip()

        # Argumente fuer Muster wie "Bash(*)" normalisieren
        if isinstance(args, str):
            arg_text = args
        elif isinstance(args, (list, tuple)):
            try:
                arg_text = " ".join(str(a) for a in args)
            except Exception:
                arg_text = ""
        else:
            arg_text = ""
        target = f"{tool}({arg_text})"

        # Aktives Permission-Profil laden
        base = Path(__file__).parent.parent
        if str(base) not in sys.path:
            sys.path.insert(0, str(base))
        handler = ClaudePermissionsHandler(base)

        active = handler._db_get(KEY_ACTIVE_PROFILE)
        if not isinstance(active, str) or not active.strip():
            return "deny"
        profile = handler._get_profile(active.strip())
        if not isinstance(profile, dict):
            return "deny"

        deny_rules = profile.get("deny")
        allow_rules = profile.get("allow")
        if not isinstance(deny_rules, list):
            deny_rules = []
        if not isinstance(allow_rules, list):
            allow_rules = []

        # Deny-Regeln haben Vorrang vor Allow-Regeln
        for rule in deny_rules:
            if _permission_rule_matches(rule, tool, target):
                return "deny"
        for rule in allow_rules:
            if _permission_rule_matches(rule, tool, target):
                return "allow"

        return "deny"
    except Exception:
        # Fail-closed: Ein Fehler ist niemals eine Erlaubnis
        return "deny"
