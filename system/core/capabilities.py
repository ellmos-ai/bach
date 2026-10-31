# -*- coding: utf-8 -*-
"""
Deprecated adapter: Capability-System (Forwarder to policy/governance).

Die Fachlogik lebt in system/policy/governance.py (Ocean policy-registry).
Diese Datei dient als dünner Stub fuer bestehende Aufrufer in BACH:

    from core.capabilities import capability_manager

Alle Aufrufe werden jetzt an system/policy/governance.CapabilityManager delegiert.
Altteile befinden sich in DEPRICATED.md.

Der eigentliche Modultransfer ist Teil von OCEAN-TRANSFER-PLAN.md.
GEGEN Kern-Grenze system/core/README.md A 2 + module-gate #2445 pruefen.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Importiere die Singleton-Instanz aus dem Policy-Modul (der Fachlogik)
try:
    from policy.governance import CAPABILITIES, TRUST_PROFILES, CapabilityManager, capability_manager as _policy_capability_manager
except ImportError:
    from system.policy.governance import CAPABILITIES, TRUST_PROFILES, CapabilityManager, capability_manager as _policy_capability_manager
capability_manager = _policy_capability_manager

# Alias zur gleichen Instanz – gleiche API, nahtloser Übergang

aus_as_alias = _policy_capability_manager

# Eins-zu-Eins-Aliase:
register_plugin = _policy_capability_manager.register_plugin
unregister_plugin = _policy_capability_manager.unregister_plugin
check = _policy_capability_manager.check
check_all = _policy_capability_manager.check_all
infer_setup_surfaces = _policy_capability_manager.infer_setup_surfaces
validate_setup_contract = _policy_capability_manager.validate_setup_contract
set_plugin_trust = _policy_capability_manager.set_plugin_trust
get_plugin_capabilities = _policy_capability_manager.get_plugin_capabilities
run_security_checks = _policy_capability_manager.run_security_checks
scan_security_detailed = _policy_capability_manager.scan_security_detailed
scan_tree_detailed = _policy_capability_manager.scan_tree_detailed
scan_tree = _policy_capability_manager.scan_tree
categorize_scan_findings = _policy_capability_manager.categorize_scan_findings
quarantine_path = _policy_capability_manager.quarantine_path
status = _policy_capability_manager.status
get_audit_log = _policy_capability_manager.get_audit_log
get_profiles = _policy_capability_manager.get_profiles

# CAPABILITIES imported from policy.governance
SETUP_GUARD_SURFACES = _policy_capability_manager.SETUP_GUARD_SURFACES
SETUP_CHECK_TYPES = _policy_capability_manager.SETUP_CHECK_TYPES
SETUP_SURFACE_CHECKS = _policy_capability_manager.SETUP_SURFACE_CHECKS
DEFAULT_TRUST_PROFILES = _policy_capability_manager.DEFAULT_TRUST_PROFILES

# Singleton – gleiche ID wie das Policy-Objekt
capability_manager = _policy_capability_manager

# Für bestehende Tests oder Inspektionen – gleiche Modulexposition
__all__ = [
    'capability_manager',
    'CAPABILITIES',
    'SETUP_GUARD_SURFACES',
    'SETUP_CHECK_TYPES',
    'SETUP_SURFACE_CHECKS',
    'DEFAULT_TRUST_PROFILES',
    'register_plugin',
    'unregister_plugin',
    'check',
    'check_all',
    'infer_setup_surfaces',
    'validate_setup_contract',
    'set_plugin_trust',
    'get_plugin_capabilities',
    'run_security_checks',
    'scan_security_detailed',
    'scan_tree_detailed',
    'scan_tree',
    'categorize_scan_findings',
    'quarantine_path',
    'status',
    'get_audit_log',
    'get_profiles',
]

# Expose via module-level get/set if needed (delegation)
# Keine Attribute eines CapabilityManager-Objekts, die ein einfaches Proxy nicht bereitstellt.

# Optional: Behalte den alten Klassen-Namen für Rückwärtskompatibilität (umfasst Register/Cache)
# Aber einfacher: lass einfach aus_as_alias als die neue Fachlogik-Objekt-ID existieren.

# Alles durch __getattr__ proxyen falls nötig
import sys
from types import ModuleType

class _ForwarderModule(ModuleType):
    """Dynamisches Proxy-Modul, das Attribute an CapabilityManager delegiert."""
    def __getattr__(self, name: str) -> Any:
        # Hole das Zielobjekt (Singleton)
        target = _policy_capability_manager
        # Versuche, das Attribut vom Zielobjekt zu holen
        if hasattr(target, name):
            return getattr(target, name)
        # Andernfalls Attribute vom Typ CapabilityManager selbst holen (Klassenmethoden)
        # Aber Kapazität_manager ist eine Instanzklasse; ihre Methoden sind bereits über Proxy oben vorhanden.
        # Wenn das Attribut immer noch nicht existiert, löse den Import für unbekannte Attribute auf.
        try:
            return __import__(__name__, fromlist=[name]).__dict__[name]
        except KeyError:
            raise AttributeError(f"'module {__name__}' hat kein Attribut '{name}'")

sys.modules[__name__] = _ForwarderModule(__name__)