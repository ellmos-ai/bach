"""Zero-Trust Sovereign Gateway & Interceptor."""

import asyncio
from typing import Any, Callable, Dict, Optional
from sentinel_fleet.core.identity import AgentIdentity, AgentStatus
from sentinel_fleet.core.permissions import PermissionRegistry, PermissionAction
from sentinel_fleet.core.model_armor import ModelArmor
from sentinel_fleet.core.policies import PolicyEngine
from sentinel_fleet.core.telemetry import telemetry
from sentinel_fleet.core.errors import SecurityViolationError, QuarantineLockError
from sentinel_fleet.core.access import RequestPrincipal


class GatewayExecutionResult:
    def __init__(
        self,
        success: bool,
        output: Any = None,
        error: Optional[str] = None,
        requires_approval: bool = False,
        approval_payload: Optional[Dict[str, Any]] = None
    ):
        self.success = success
        self.output = output
        self.error = error
        self.requires_approval = requires_approval
        self.approval_payload = approval_payload


class SovereignGateway:
    def __init__(
        self,
        permission_registry: Optional[PermissionRegistry] = None,
        model_armor: Optional[ModelArmor] = None,
        policy_engine: Optional[PolicyEngine] = None,
    ):
        self.permissions = permission_registry or PermissionRegistry()
        self.model_armor = model_armor or ModelArmor()
        self.policy_engine = policy_engine or PolicyEngine()
        self._agent_locks: Dict[str, asyncio.Lock] = {}
        self._master_lock = asyncio.Lock()

    async def _get_agent_lock(self, agent_id: str) -> asyncio.Lock:
        async with self._master_lock:
            if agent_id not in self._agent_locks:
                self._agent_locks[agent_id] = asyncio.Lock()
            return self._agent_locks[agent_id]

    async def execute_tool_call(
        self,
        agent: AgentIdentity,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_func: Callable,
        *,
        principal: Optional[RequestPrincipal] = None,
    ) -> GatewayExecutionResult:
        """Zero-Trust Interceptor for all agent actions with concurrency locks and async armor."""
        span = telemetry.start_span(
            f"tool_call:{tool_name}",
            agent.agent_id,
            {"tool": tool_name},
            principal=principal,
        )
        agent_lock = await self._get_agent_lock(agent.agent_id)

        async with agent_lock:
            # Everything below runs "under" this span, including the tool body: a domain module
            # can record its own verdict on this row via telemetry.record_on_active_span().
            span_token = telemetry.bind_active_span(span)
            try:
                # 1. Identity & Quarantine Check
                if agent.status == AgentStatus.QUARANTINED:
                    error_msg = f"Agent {agent.agent_id} is in QUARANTINE: {agent.quarantine_reason}"
                    telemetry.end_span(span, status="BLOCKED", error=error_msg)
                    raise QuarantineLockError(agent.agent_id, agent.quarantine_reason)

                # 2. Scoped Capability Check (PoLP)
                if not agent.is_tool_scoped(tool_name):
                    is_public_demo_workspace = bool(
                        principal
                        and principal.data_owner_id.startswith("workspace:")
                        and not principal.authenticated
                    )
                    if not is_public_demo_workspace:
                        agent.status = AgentStatus.QUARANTINED
                        agent.quarantine_reason = (
                            f"Attempted unauthorized tool execution: {tool_name}"
                        )
                    error_msg = f"Security Violation: Agent '{agent.agent_id}' is not scoped for tool '{tool_name}'"
                    telemetry.end_span(span, status="SECURITY_VIOLATION", error=error_msg)
                    raise SecurityViolationError(
                        agent.agent_id, tool_name, "Tool is outside the agent's least-privilege scope."
                    )

                # 3. Model Armor Inspection (Anti-Injection & PII Redaction Async Offloaded)
                sanitized_args = await self.model_armor.sanitize_arguments_async(tool_args)
                inspection = await asyncio.to_thread(self.model_armor.inspect_arguments, sanitized_args)
                if not inspection.is_safe:
                    error_msg = (
                        f"Model Armor refused tool arguments for '{tool_name}': "
                        f"{', '.join(inspection.blocked_patterns)}"
                    )
                    telemetry.end_span(span, status="BLOCKED", error=error_msg)
                    raise SecurityViolationError(
                        agent.agent_id,
                        tool_name,
                        "Tool arguments contain a prompt-injection pattern.",
                    )
                telemetry.add_event(span, "model_armor_sanitized", {"redactions": "completed"})

                # 4. Permission Registry Check (allow / deny / ask)
                perm_action = self.permissions.evaluate(tool_name)
                if perm_action == PermissionAction.DENY:
                    error_msg = f"Access Denied: Tool '{tool_name}' is strictly forbidden by policy"
                    telemetry.end_span(span, status="DENIED", error=error_msg)
                    raise SecurityViolationError(
                        agent.agent_id, tool_name, "Tool is denied by the permission registry."
                    )

                if perm_action == PermissionAction.ASK:
                    # A pending decision belongs to the scoped ticket, not to a process-global
                    # agent identity. Mutating the shared fleet row here would let one tenant's
                    # ticket falsify the lifecycle shown to every other tenant. Task/ticket state
                    # and the scoped telemetry span carry the wait state instead.
                    telemetry.end_span(span, status="WAITING_FOR_USER_APPROVAL")
                    return GatewayExecutionResult(
                        success=True,
                        requires_approval=True,
                        approval_payload={
                            "agent_id": agent.agent_id,
                            "tool_name": tool_name,
                            "arguments": sanitized_args,
                            "reason": "Action has external impact and requires human signoff"
                        }
                    )

                # 5. Execute Tool with Active Span
                agent.consecutive_steps += 1
                result = await tool_func(**sanitized_args)
                telemetry.end_span(span, status="OK")
                return GatewayExecutionResult(success=True, output=result)

            except (SecurityViolationError, QuarantineLockError):
                # Security verdicts must surface as errors, not be flattened into a result object
                raise

            except Exception as e:
                error_msg = str(e)
                telemetry.end_span(span, status="ERROR", error=error_msg)
                return GatewayExecutionResult(success=False, error=error_msg)

            finally:
                telemetry.release_active_span(span_token)


gateway = SovereignGateway()
