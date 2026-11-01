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

from typing import Any

try:
    import policy.governance as _gov
    from policy.governance import (
        CAPABILITIES,
        DEFAULT_TRUST_PROFILES,
        SETUP_CHECK_TYPES,
        SETUP_GUARD_SURFACES,
        SETUP_SURFACE_CHECKS,
        TRUST_PROFILES,
        CapabilityManager,
        capability_manager as _policy_capability_manager,
    )
except ImportError:
    import system.policy.governance as _gov
    from system.policy.governance import (
        CAPABILITIES,
        DEFAULT_TRUST_PROFILES,
        SETUP_CHECK_TYPES,
        SETUP_GUARD_SURFACES,
        SETUP_SURFACE_CHECKS,
        TRUST_PROFILES,
        CapabilityManager,
        capability_manager as _policy_capability_manager,
    )

capability_manager = _policy_capability_manager
aus_as_alias = _policy_capability_manager

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

__all__ = [
    "CapabilityManager",
    "capability_manager",
    "CAPABILITIES",
    "SETUP_GUARD_SURFACES",
    "SETUP_CHECK_TYPES",
    "SETUP_SURFACE_CHECKS",
    "DEFAULT_TRUST_PROFILES",
    "TRUST_PROFILES",
    "register_plugin",
    "unregister_plugin",
    "check",
    "check_all",
    "infer_setup_surfaces",
    "validate_setup_contract",
    "set_plugin_trust",
    "get_plugin_capabilities",
    "run_security_checks",
    "scan_security_detailed",
    "scan_tree_detailed",
    "scan_tree",
    "categorize_scan_findings",
    "quarantine_path",
    "status",
    "get_audit_log",
    "get_profiles",
]


def __getattr__(name: str) -> Any:
    if hasattr(_policy_capability_manager, name):
        return getattr(_policy_capability_manager, name)
    if hasattr(_gov, name):
        return getattr(_gov, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
