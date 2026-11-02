# SPDX-License-Identifier: MIT
"""Central Ocean-Stack Consumer Seam for BACH.

Transforms BACH step-by-step into a branded partial-OS stack on top of Open Ocean:
  * Resolves canonical Ocean modules (`ocean_resources.ram_distributor`, `taskplan.lease`,
    `tools.worker_worktree_policy`, `tools.task_result_review_policy`,
    `tools.escalation_ladder`, `tools.capability_views`, `tools.governance_bridge`,
    `tools.help_projection`) from installed distributions or sibling checkouts.
  * Marks legacy BACH-internal implementations as `@deprecated_legacy_bach(...)` so they
    remain available only as compatibility fallbacks until final removal.
"""
from __future__ import annotations

import functools
import importlib
import importlib.util
import os
import sys
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

_MODULE_CACHE: dict[str, Any] = {}

CANONICAL_MODULES: tuple[str, ...] = (
    "ocean-resources",
    "task-master",
    "ellmos-worker",
    "review-policy",
    "escalation-ladder",
    "persona-routing",
    "learning-loop",
    "agent-library",
    "capability-views",
    "governance-bridge",
    "doc-keeper",
)


def deprecated_legacy_bach(replacement: str) -> Callable[[F], F]:
    """Mark a legacy BACH class or function as deprecated in favor of an Ocean module."""

    def decorator(obj: F) -> F:
        obj.__ocean_deprecated__ = True  # type: ignore[attr-defined]
        obj.__ocean_replacement__ = replacement  # type: ignore[attr-defined]
        if isinstance(obj, type):
            orig_init = obj.__init__

            @functools.wraps(orig_init)
            def wrapped_init(self: Any, *args: Any, **kwargs: Any) -> None:
                if os.environ.get("BACH_WARN_DEPRECATED") == "1":
                    warnings.warn(
                        f"{obj.__qualname__} is deprecated; use Ocean module {replacement} instead.",
                        DeprecationWarning,
                        stacklevel=2,
                    )
                orig_init(self, *args, **kwargs)

            obj.__init__ = wrapped_init  # type: ignore[misc]
            return obj

        @functools.wraps(obj)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if os.environ.get("BACH_WARN_DEPRECATED") == "1":
                warnings.warn(
                    f"{getattr(obj, '__qualname__', obj)} is deprecated; use Ocean module {replacement} instead.",
                    DeprecationWarning,
                    stacklevel=2,
                )
            return obj(*args, **kwargs)

        wrapped.__ocean_deprecated__ = True  # type: ignore[attr-defined]
        wrapped.__ocean_replacement__ = replacement  # type: ignore[attr-defined]
        return wrapped  # type: ignore[return-value]

    return decorator


def _candidate_repo_roots() -> list[Path]:
    """Return candidate parent directories where `open-ocean`, `task-master`, `ocean-resources` live."""
    bach_root = Path(__file__).resolve().parents[3]
    candidates = [
        bach_root.parent,
        Path(os.environ.get("OCEAN_REPOS_ROOT", "")) if os.environ.get("OCEAN_REPOS_ROOT") else None,
        Path("C:/_Local_DEV/repos"),
        Path("/Users/lukas/services"),
    ]
    seen: list[Path] = []
    for c in candidates:
        if c and c not in seen and c.is_dir():
            seen.append(c)
    return seen


def _load_module_from_repo(cache_key: str, import_name: str, repo_name: str, rel_file: str) -> Any:
    """Import `import_name` from environment or load `rel_file` from sibling `repo_name`."""
    if cache_key in _MODULE_CACHE:
        return _MODULE_CACHE[cache_key]

    for root in _candidate_repo_roots():
        repo_dir = root / repo_name
        target = repo_dir / rel_file
        if target.is_file():
            for p_str in (str(target.parent), str(repo_dir / "src"), str(repo_dir)):
                if p_str not in sys.path:
                    sys.path.insert(0, p_str)
            spec = importlib.util.spec_from_file_location(cache_key, target)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                sys.modules[cache_key] = mod
                try:
                    spec.loader.exec_module(mod)
                    sys.modules[import_name] = mod
                    _MODULE_CACHE[cache_key] = mod
                    return mod
                except ImportError:
                    mod = importlib.import_module(import_name)
                    _MODULE_CACHE[cache_key] = mod
                    return mod

    mod = importlib.import_module(import_name)
    _MODULE_CACHE[cache_key] = mod
    return mod


# ---------------------------------------------------------------------------
# 1. ocean-resources & RAM-Distributor (#2441, #2419)
# ---------------------------------------------------------------------------

def load_ocean_ram_distributor_module() -> Any:
    try:
        return _load_module_from_repo(
            "ocean_resources_ram_distributor",
            "ocean_resources.ram_distributor",
            "ocean-resources",
            "ocean_resources/ram_distributor.py",
        )
    except ImportError:
        return _load_module_from_repo(
            "ocean_resources_ram_distributor",
            "ocean_resources.ram_distributor",
            "open-ocean",
            "ocean_resources/ram_distributor.py",
        )


def get_ocean_ram_distributor(
    *,
    total_ram_bytes: int = 64 * 1024**3,
    tendency: str = "balanced",
) -> Any:
    mod = load_ocean_ram_distributor_module()
    return mod.RAMDistributor(
        total_ram_bytes=total_ram_bytes,
        tendency=tendency,
    )


# ---------------------------------------------------------------------------
# 2. task-master `taskplan.lease` (#2124, #2327)
# ---------------------------------------------------------------------------

def load_taskplan_lease_module() -> Any:
    return _load_module_from_repo(
        "taskplan_lease_kernel",
        "taskplan.lease",
        "task-master",
        "taskplan/lease.py",
    )


def get_ocean_task_lease_manager(db_path: str | Path | None = None) -> Any:
    from hub._services.taskplan_bridge import resolve_taskplan_db

    mod = load_taskplan_lease_module()
    resolved = resolve_taskplan_db(db_path)
    return mod.TaskLeaseManager(resolved)


# ---------------------------------------------------------------------------
# 3. Multi-Repo Worker Worktree Policy (#2577, #2330, #3682-#3697)
# ---------------------------------------------------------------------------

def load_worker_worktree_policy_module() -> Any:
    return _load_module_from_repo(
        "ocean_worker_worktree_policy",
        "tools.worker_worktree_policy",
        "open-ocean",
        "tools/worker_worktree_policy.py",
    )


def check_worker_worktree_access(
    *,
    worker_id: str,
    repo_name: str,
    branch: str,
    write_scope: str = "ocean",
    in_isolated_worktree: bool = True,
    repo_locked: bool = False,
    has_active_lease: bool = True,
    allowed_repos: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    mod = load_worker_worktree_policy_module()
    kwargs: dict[str, Any] = {"worker_id": worker_id, "write_scope": write_scope}
    if allowed_repos is not None:
        kwargs["allowed_repos"] = tuple(allowed_repos)
    cfg = mod.WorkerWorktreeConfig(**kwargs)
    return mod.evaluate_worker_write_access(
        cfg,
        repo_name=repo_name,
        branch=branch,
        in_isolated_worktree=in_isolated_worktree,
        repo_locked=repo_locked,
        has_active_lease=has_active_lease,
    )


# ---------------------------------------------------------------------------
# 4. Configurable Result Review Policy (#2210)
# ---------------------------------------------------------------------------

def load_task_result_review_policy_module() -> Any:
    return _load_module_from_repo(
        "ocean_task_result_review_policy",
        "tools.task_result_review_policy",
        "open-ocean",
        "tools/task_result_review_policy.py",
    )


def evaluate_ocean_configurable_review(
    *,
    policy_mode: str = "any_fresh_run",
    producer_model: str,
    producer_provider: str,
    producer_generation: str,
    reviewer_model: str,
    reviewer_provider: str,
    reviewer_generation: str,
    allowed_models: list[str] | tuple[str, ...] = (),
    has_code_scope: bool = True,
    result_text_present: bool = True,
) -> dict[str, Any]:
    mod = load_task_result_review_policy_module()
    return mod.evaluate_configurable_review_policy(
        policy_mode=policy_mode,
        producer_model=producer_model,
        producer_provider=producer_provider,
        producer_generation=producer_generation,
        reviewer_model=reviewer_model,
        reviewer_provider=reviewer_provider,
        reviewer_generation=reviewer_generation,
        allowed_models=allowed_models,
        has_code_scope=has_code_scope,
        result_text_present=result_text_present,
    )


# ---------------------------------------------------------------------------
# 5. Identity, Escalation Ladder, Persona-Routing v2, Learning-Loop & Library
# ---------------------------------------------------------------------------

def load_escalation_ladder_module() -> Any:
    return _load_module_from_repo(
        "ocean_escalation_ladder",
        "tools.escalation_ladder",
        "open-ocean",
        "tools/escalation_ladder.py",
    )


def check_authority_escalation(
    actor_level: str,
    action_class: str,
    *,
    target_locked: bool = False,
    has_user_gate: bool = False,
) -> dict[str, Any]:
    mod = load_escalation_ladder_module()
    return mod.evaluate_escalation(
        actor_level,
        action_class,
        target_locked=target_locked,
        has_user_gate=has_user_gate,
    )


def check_capability_permission(
    capability_key: str,
    permissions: dict[str, bool] | None = None,
    *,
    has_user_gate: bool = False,
) -> dict[str, Any]:
    mod = load_escalation_ladder_module()
    return mod.evaluate_capability_permission(
        capability_key,
        permissions=permissions,
        has_user_gate=has_user_gate,
    )



def load_persona_routing_module() -> Any:
    return _load_module_from_repo(
        "ocean_persona_routing",
        "tools.persona_routing",
        "open-ocean",
        "tools/persona_routing.py",
    )


def load_learning_loop_module() -> Any:
    return _load_module_from_repo(
        "ocean_learning_loop",
        "tools.learning_loop",
        "open-ocean",
        "tools/learning_loop.py",
    )


def load_agent_library_module() -> Any:
    load_persona_routing_module()
    return _load_module_from_repo(
        "ocean_agent_library",
        "tools.agent_library",
        "open-ocean",
        "tools/agent_library.py",
    )


def load_capability_views_module() -> Any:
    return _load_module_from_repo(
        "ocean_capability_views",
        "tools.capability_views",
        "open-ocean",
        "tools/capability_views.py",
    )


def load_governance_bridge_module() -> Any:
    return _load_module_from_repo(
        "ocean_governance_bridge",
        "tools.governance_bridge",
        "open-ocean",
        "tools/governance_bridge.py",
    )


def validate_module_persona_routing(manifest: dict[str, Any]) -> dict[str, Any]:
    mod = load_persona_routing_module()
    return mod.validate_persona_routing_manifest(manifest)


def validate_skill_learning_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    mod = load_learning_loop_module()
    return mod.validate_learning_candidate(candidate)


def project_agent_library(
    *,
    templates: list[dict[str, Any]],
    prompt_agents: list[dict[str, Any]],
    chains: list[dict[str, Any]],
) -> dict[str, Any]:
    mod = load_agent_library_module()
    return mod.project_agent_library_catalog(
        templates=templates,
        prompt_agents=prompt_agents,
        chains=chains,
    )


def get_ocean_role_routing_catalog() -> dict[str, Any]:
    """Return the canonical BACH-to-Ocean Coordinator & Expert role catalog with flexible provider sockets."""
    mod = load_persona_routing_module()
    return mod.get_ocean_role_routing_catalog()


def discover_ocean_agent_library_templates(repos_root: str | Path | None = None) -> dict[str, Any]:
    """Build the full 3-tab Agent-Library catalog combining BACH Coordinator/Expert roles and module `roles[]`."""
    mod = load_agent_library_module()
    return mod.build_full_agent_library_catalog(repos_root=repos_root)


# ---------------------------------------------------------------------------
# 6. Ocean GUI API Adapter Delegation (#2075, #2094, #2097, #2098)
# ---------------------------------------------------------------------------

def load_doc_keeper_module() -> Any:
    """Load the standalone `doc-keeper` module (`doc_keeper.extractor` / `doc_keeper.classifier`)."""
    return _load_module_from_repo(
        "ellmos_doc_keeper_extractor",
        "doc_keeper.extractor",
        "doc-keeper",
        "src/doc_keeper/extractor.py",
    )


def audit_repository_with_doc_keeper(
    repo_root: str | Path,
    *,
    config_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the reusable 3-Cause Documentation Audit (`doc-keeper`) against any repository."""
    mod = load_doc_keeper_module()
    return mod.audit_repository(
        Path(repo_root),
        config_override=config_override,
    )


def ocean_software_inventory(releases_path: Path) -> dict[str, Any]:
    cap_mod = load_capability_views_module()
    return cap_mod.software_inventory(releases_path=Path(releases_path))


def ocean_governance_audit(bach_db_path: Path | None = None, limit: int = 100) -> dict[str, Any]:
    gov_mod = load_governance_bridge_module()
    return gov_mod.task_history_audit(bach_db_path, limit=limit)


def ocean_task_assignees(config_path: Path) -> dict[str, Any]:
    gov_mod = load_governance_bridge_module()
    return gov_mod.task_assignees_view(Path(config_path))


def ocean_task_result(task_id: int, bach_db_path: Path | None = None) -> dict[str, Any]:
    gov_mod = load_governance_bridge_module()
    return gov_mod.task_result_view(bach_db_path, task_id)


def load_voice_io_module() -> Any:
    return _load_module_from_repo(
        "ellmos_voice_io_service",
        "ellmos_voice_io.service",
        "ellmos-voice-io",
        "src/ellmos_voice_io/service.py",
    )


def load_talk_module() -> Any:
    return _load_module_from_repo(
        "ellmos_talk_engine",
        "ellmos_talk.engine",
        "ellmos-talk",
        "src/ellmos_talk/engine.py",
    )


def load_sensation_module() -> Any:
    return _load_module_from_repo(
        "ellmos_sensation_sensor_hub",
        "ellmos_sensation.sensor_hub",
        "ellmos-sensation",
        "src/ellmos_sensation/sensor_hub.py",
    )


def load_homecontrol_module() -> Any:
    return _load_module_from_repo(
        "ellmos_homecontrol_hub",
        "ellmos_homecontrol.hub",
        "ellmos-homecontrol",
        "src/ellmos_homecontrol/hub.py",
    )


def load_robotics_module() -> Any:
    return _load_module_from_repo(
        "ellmos_robotics_mcp_standard",
        "ellmos_robotics.mcp_standard",
        "ellmos-robotics",
        "src/ellmos_robotics/mcp_standard.py",
    )


def load_universal_gui_module() -> Any:
    return _load_module_from_repo(
        "ellmos_universal_gui_app",
        "ellmos_universal_gui.app",
        "ellmos-universal-gui",
        "src/ellmos_universal_gui/app.py",
    )


def ocean_capability_extensions_status() -> dict[str, Any]:
    """Return status of the multimodal/embodied & universal-GUI Ocean capability modules (#3763-#3767, GUX-002)."""
    ext_modules = {
        "ellmos-voice-io": ("ellmos_voice_io.service", load_voice_io_module),
        "ellmos-talk": ("ellmos_talk.engine", load_talk_module),
        "ellmos-sensation": ("ellmos_sensation.sensor_hub", load_sensation_module),
        "ellmos-homecontrol": ("ellmos_homecontrol.hub", load_homecontrol_module),
        "ellmos-robotics": ("ellmos_robotics.mcp_standard", load_robotics_module),
        "ellmos-universal-gui": ("ellmos_universal_gui.app", load_universal_gui_module),
    }
    bound: dict[str, Any] = {}
    for name, (mod_id, loader) in ext_modules.items():
        try:
            m = loader()
            bound[name] = {
                "bound": True,
                "module": mod_id,
                "file": getattr(m, "__file__", None),
            }
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            bound[name] = {
                "bound": False,
                "module": mod_id,
                "error": str(exc),
            }
    return bound


def ocean_stack_status() -> dict[str, Any]:
    """Return status of all 11 canonical Ocean modules bound into BACH."""
    modules = {
        "ocean-resources": ("ocean_resources.ram_distributor", load_ocean_ram_distributor_module),
        "task-master": ("taskplan.lease", load_taskplan_lease_module),
        "ellmos-worker": ("tools.worker_worktree_policy", load_worker_worktree_policy_module),
        "review-policy": ("tools.task_result_review_policy", load_task_result_review_policy_module),
        "escalation-ladder": ("tools.escalation_ladder", load_escalation_ladder_module),
        "persona-routing": ("tools.persona_routing", load_persona_routing_module),
        "learning-loop": ("tools.learning_loop", load_learning_loop_module),
        "agent-library": ("tools.agent_library", load_agent_library_module),
        "capability-views": ("tools.capability_views", load_capability_views_module),
        "governance-bridge": ("tools.governance_bridge", load_governance_bridge_module),
        "doc-keeper": ("doc_keeper", load_doc_keeper_module),
    }
    bound: dict[str, Any] = {}
    for name, (mod_id, loader) in modules.items():
        try:
            m = loader()
            bound[name] = {
                "bound": True,
                "module": mod_id,
                "file": getattr(m, "__file__", None),
            }
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            bound[name] = {
                "bound": False,
                "module": mod_id,
                "error": str(exc),
            }
    extensions = ocean_capability_extensions_status()
    return {
        "schema": "bach.ocean-stack-bindings.v1",
        "stack_role": "branded-partial-os-stack-of-ocean",
        "legacy_mode": "deprecated-fallback-only",
        "modules": bound,
        "capability_extensions": extensions,
        "capability_extensions_bound_count": sum(1 for item in extensions.values() if item["bound"]),
    }
