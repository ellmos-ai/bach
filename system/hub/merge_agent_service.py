"""Merge-Agent: getrennte GitHub-Identität mit commitgebundener Freigabe.

Task #2039: Der Merge-Agent wertet Pull-Request-Preflights nach einer harten
Regelliste aus. Kern ist die commitgebundene Review-Freigabe: eine Freigabe
gilt ausschließlich für den exakten Head-Commit, für den sie erteilt wurde;
jeder neue Head verfällt (approval_stale_new_head). Autor-Approvals zählen
nicht (kein Self-Approval), Admin-/Force-Bypass ist nicht vorgesehen, Drafts
und Stacks werden abgelehnt.

Kredential-Disziplin: Die Merge-Agent-Identität besteht aus einem Principal
(z. B. merge-agent@bach.local) plus reiner Secret-Provider-Referenz
(Provider + Key). Geheimniswerte werden nirgends entgegengenommen, gelesen,
gehalten oder ausgegeben; Konstruktoren und Methoden weisen
Credential-Kwargs mit TypeError ab.

Historie: Der Ursprungs-Commit 1e610f14 erreichte origin/main nie; dieser
Stand ist nachhaltig neu aufgebaut, ohne auf den alten Hash zu verweisen.

Audit: Jede Bewertung erzeugt ein Audit-Event (merge_agent.preflight) über
hub.audit_logger.log_audit_event fail-soft oder über einen injizierten
Auditor-Callback.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

MERGE_AGENT_PROFILE_NAME = "merge_agent"
MERGE_AGENT_ROLE_KEY = "role_merge_agent"
MERGE_AGENT_API_PREFIX = "/api/system/core-agents"
MERGE_AGENT_PREFLIGHT_PATH = "/merge-agent/preflight"
MERGE_AGENT_AUDIT_EVENT = "merge_agent.preflight"
PROTECTED_HEAD_BRANCHES = ("main", "master", "release", "production")
DEFAULT_ALLOWED_BASE_BRANCHES = ("main",)

ROLE_MERGE_AGENT_BLUEPRINT: Dict[str, Any] = {
    "role": "merge_agent",
    "display_name": "Merge-Agent",
    "category": "core_agent",
    "profile_name": MERGE_AGENT_PROFILE_NAME,
    "api": {
        "prefix": MERGE_AGENT_API_PREFIX,
        "preflight_path": MERGE_AGENT_PREFLIGHT_PATH,
        "route": MERGE_AGENT_API_PREFIX + MERGE_AGENT_PREFLIGHT_PATH,
        "method": "POST",
    },
    "identity": {
        "separate_from_user_principals": True,
        "principal": "merge-agent@bach.local",
        "secret_provider_reference": {
            "kind": "reference_only",
            "fields": ["provider_name", "secret_key"],
            "policy": (
                "Nur Provider und Key referenzieren; Geheimniswerte werden "
                "nie gelesen, gespeichert, geloggt oder ausgegeben."
            ),
        },
    },
    "permissions": [
        "merge_agent.preflight.evaluate",
        "merge_agent.merge.execute_after_exact_head_approval",
    ],
    "forbidden": [
        "self_approval",
        "admin_bypass",
        "credential_read",
        "credential_output",
        "credential_value_storage",
    ],
    "approval_model": {
        "type": "exact_head_commit",
        "expires_on_new_head": True,
        "revocable": True,
        "author_approval_does_not_count": True,
    },
    "preflight_rules": [
        "identity_not_pr_author",
        "no_bypass",
        "no_draft",
        "no_stack",
        "allowed_base_branch",
        "unprotected_head_branch",
        "ci_all_success",
        "exact_head_user_approval",
    ],
    "audit": {
        "event_prefix": "merge_agent",
        "preflight_event": MERGE_AGENT_AUDIT_EVENT,
    },
}


def role_merge_agent_seed() -> dict:
    """Frische Tiefenkopie des Rollen-Blueprints (Seed für Rollenspeicher)."""
    return copy.deepcopy(ROLE_MERGE_AGENT_BLUEPRINT)


_CREDENTIAL_KWARGS = (
    "credential",
    "credentials",
    "secret_value",
    "secret",
    "token",
    "access_token",
    "api_key",
    "password",
    "github_token",
)


def _reject_credential_kwargs(kwargs: Dict[str, Any]) -> None:
    """Weist Credential-Material und unbekannte Extra-Parameter ab."""
    for name in _CREDENTIAL_KWARGS:
        if name in kwargs and kwargs[name] is not None:
            raise TypeError(
                f"Parameter '{name}' ist Credential-Material: Der Merge-Agent "
                "nimmt nur Secret-Provider-Referenzen, nie Geheimniswerte."
            )
    unknown = [k for k in kwargs if k not in _CREDENTIAL_KWARGS]
    if unknown:
        raise TypeError(
            "Unbekannte Extra-Parameter abgelehnt: " + ", ".join(sorted(str(k) for k in unknown))
        )


def _normalize_principal(value: Any) -> str:
    return str(value).strip().lower()


def _normalize_sha(value: Any) -> str:
    return str(value).strip().lower()


def _normalize_branch(value: Any) -> str:
    return str(value).strip().lower()


@dataclass(frozen=True)
class SecretProviderReference:
    """Reine Referenz auf ein Geheimnis bei einem Provider — ohne Wert."""

    provider_name: str
    secret_key: str

    def as_reference(self) -> Dict[str, str]:
        return {
            "provider_name": str(self.provider_name).strip(),
            "secret_key": str(self.secret_key).strip(),
        }

    def describe(self) -> Dict[str, str]:
        return self.as_reference()


@dataclass(frozen=True)
class MergeAgentIdentity:
    """Getrennte Merge-Agent-Identität: Principal plus Referenz, kein Secret."""

    principal: str
    secret: SecretProviderReference

    def describe(self) -> Dict[str, Any]:
        return {
            "principal": _normalize_principal(self.principal),
            "separate_from_user_principals": True,
            "secret_provider_reference": self.secret.describe(),
        }

    def is_same_principal(self, other: Any) -> bool:
        try:
            return _normalize_principal(other) == _normalize_principal(self.principal)
        except Exception:
            return False


@dataclass(frozen=True, repr=False)
class MergeApproval:
    """Review-Freigabe, strikt an einen Head-Commit gebunden.

    Zustandspriorität: stale (fremder Head) vor revoked vor expired; sonst
    covered.
    """

    approver: str
    commit_sha: str
    expires_at: Optional[datetime] = None
    revoked: bool = False

    def approval_state(self, head_sha: str, now: Optional[datetime] = None) -> str:
        if _normalize_sha(head_sha) != _normalize_sha(self.commit_sha):
            return "stale"
        if self.revoked:
            return "revoked"
        if self.expires_at is not None:
            expires = self.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            moment = now or datetime.now(timezone.utc)
            if moment > expires:
                return "expired"
        return "covered"

    def covers(self, head_sha: str, now: Optional[datetime] = None) -> bool:
        return self.approval_state(head_sha, now) == "covered"


@dataclass
class PullRequestContext:
    """Normalisierter PR-Kontext für die Preflight-Bewertung."""

    repository: str
    pr_number: int
    author_principal: str
    head_branch: str
    base_branch: str
    head_sha: str
    is_draft: bool = False
    stacked: bool = False
    stacked_pr_numbers: List[int] = field(default_factory=list)
    ci_check_states: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PreflightViolation:
    """Eine Regelverletzung mit stabilem Code und lesbarer Diagnose."""

    code: str
    detail: str

    def to_dict(self) -> Dict[str, str]:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class PreflightResult:
    """JSON-serialisierbares Ergebnis eines Preflight-Laufs."""

    ok: bool
    checks: Dict[str, bool] = field(default_factory=dict)
    violations: List[PreflightViolation] = field(default_factory=list)
    role: str = MERGE_AGENT_ROLE_KEY
    principal: str = ""
    repository: str = ""
    pr_number: int = 0
    head_sha: str = ""
    identity: Dict[str, Any] = field(default_factory=dict)
    audit_event: str = MERGE_AGENT_AUDIT_EVENT
    approved_by: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": dict(self.checks),
            "violations": [v.to_dict() for v in self.violations],
            "role": self.role,
            "principal": self.principal,
            "repository": self.repository,
            "pr_number": self.pr_number,
            "head_sha": self.head_sha,
            "identity": self.identity,
            "audit_event": self.audit_event,
            "approved_by": list(self.approved_by),
        }


class MergeAgentService:
    """Bewertet PR-Kontexte gegen die Merge-Agent-Regeln.

    Bewusste Design-Entscheidung: kein hub.base.BaseHandler-Erbe — der
    Preflight ist ein reiner Auswertungsdienst ohne Datei-/Operationsfläche
    und nimmt nur Secret-Provider-Referenzen, nie Credential-Werte.
    """

    def __init__(
        self,
        identity: MergeAgentIdentity,
        *,
        allowed_base_branches: Iterable[str] = DEFAULT_ALLOWED_BASE_BRANCHES,
        protected_head_branches: Iterable[str] = PROTECTED_HEAD_BRANCHES,
        auditor: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        **kwargs: Any,
    ) -> None:
        _reject_credential_kwargs(kwargs)
        self.identity = identity
        self.allowed_base_branches = tuple(
            _normalize_branch(b) for b in allowed_base_branches
        )
        self.protected_head_branches = tuple(
            _normalize_branch(b) for b in protected_head_branches
        )
        self.auditor = auditor

    def evaluate_preflight(
        self,
        pr: PullRequestContext,
        *,
        approvals: Iterable[MergeApproval] = (),
        now: Optional[datetime] = None,
        bypass: Optional[str] = None,
    ) -> PreflightResult:
        """Bewertet den PR und liefert ein Prüfprotokoll (inkl. Audit)."""
        checks: Dict[str, bool] = {}
        violations: List[PreflightViolation] = []

        def add(code: str, detail: str) -> None:
            violations.append(PreflightViolation(code=code, detail=detail))

        same_principal = self.identity.is_same_principal(pr.author_principal)
        checks["identity_not_pr_author"] = not same_principal
        if same_principal:
            add(
                "identity_not_pr_author",
                "Merge-Agent-Identität darf nicht der PR-Autor sein (kein Self-Approval).",
            )

        bypass_used = bool(bypass)
        checks["no_bypass"] = not bypass_used
        if bypass_used:
            add(
                "no_bypass",
                f"Admin-/Force-Bypass ({bypass!r}) ist nicht vorgesehen; Freigabepflicht bleibt bestehen.",
            )

        checks["no_draft"] = not pr.is_draft
        if pr.is_draft:
            add(
                "no_draft",
                "PR ist ein Draft; Merge erst nach Markierung 'ready for review'.",
            )

        stacked = bool(pr.stacked) or len(pr.stacked_pr_numbers) > 0
        checks["no_stack"] = not stacked
        if stacked:
            add(
                "no_stack",
                "PR ist Teil eines Stacks (stacked bzw. gestapelte PRs vorhanden); Separat-Merge erforderlich.",
            )

        base_ok = _normalize_branch(pr.base_branch) in self.allowed_base_branches
        checks["allowed_base_branch"] = base_ok
        if not base_ok:
            add(
                "allowed_base_branch",
                f"Base-Branch {pr.base_branch!r} ist nicht freigegeben; erlaubt: "
                + (", ".join(self.allowed_base_branches) or "-")
                + ".",
            )

        head_ok = _normalize_branch(pr.head_branch) not in self.protected_head_branches
        checks["unprotected_head_branch"] = head_ok
        if not head_ok:
            add(
                "unprotected_head_branch",
                f"Head-Branch {pr.head_branch!r} ist geschützt; der Merge-Agent mergt nur von Feature-Branches.",
            )

        ci_ok = True
        if not pr.ci_check_states:
            ci_ok = False
            add(
                "ci_all_success",
                "CI-Checks fehlen bzw. sind nicht gestartet; Erfolge abwarten.",
            )
        else:
            for name in sorted(pr.ci_check_states):
                state = str(pr.ci_check_states[name]).strip().lower()
                if state != "success":
                    ci_ok = False
                    add(
                        "ci_all_success",
                        f"CI-Check {name!r} ist {pr.ci_check_states[name]!r}; nur 'success' zulässig.",
                    )
        checks["ci_all_success"] = ci_ok

        author_key = _normalize_principal(pr.author_principal)
        agent_key = _normalize_principal(self.identity.principal)
        eligible: List[MergeApproval] = []
        author_only_approval = False
        for approval in approvals:
            approver_key = _normalize_principal(approval.approver)
            if approver_key == author_key or approver_key == agent_key:
                author_only_approval = author_only_approval or approver_key == author_key
                continue
            eligible.append(approval)

        approved_by: List[str] = []
        covered = [a for a in eligible if a.approval_state(pr.head_sha, now) == "covered"]
        if covered:
            checks["exact_head_user_approval"] = True
            approved_by = sorted({_normalize_principal(a.approver) for a in covered})
        else:
            checks["exact_head_user_approval"] = False
            if author_only_approval and not eligible:
                add(
                    "approval_ignored_from_author",
                    "Nur der PR-Autor hat freigegeben; Autor-Approvals zählen nicht (kein Self-Approval).",
                )
            else:
                states = [a.approval_state(pr.head_sha, now) for a in eligible]
                if "revoked" in states:
                    add(
                        "approval_revoked",
                        "Passende Freigabe wurde widerrufen; Neu-Review erforderlich.",
                    )
                elif "expired" in states:
                    add(
                        "approval_expired",
                        "Freigabe ist abgelaufen; Neu-Review erforderlich.",
                    )
                elif "stale" in states:
                    add(
                        "approval_stale_new_head",
                        "Freigabe galt für einen anderen Head-Commit; Freigaben verfallen mit neuem Head.",
                    )
                else:
                    add(
                        "approval_missing_exact_head",
                        "Keine gültige Freigabe für den exakten Head-Commit vorhanden.",
                    )

        result = PreflightResult(
            ok=not violations,
            checks=checks,
            violations=violations,
            principal=agent_key,
            repository=str(pr.repository),
            pr_number=int(pr.pr_number),
            head_sha=str(pr.head_sha),
            identity=self.identity.describe(),
            approved_by=approved_by,
        )
        self._audit(result)
        return result

    def preflight_dict(
        self,
        pr: PullRequestContext,
        *,
        approvals: Iterable[MergeApproval] = (),
        now: Optional[datetime] = None,
        bypass: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Convenience: evaluate_preflight(...).to_dict()."""
        return self.evaluate_preflight(
            pr,
            approvals=approvals,
            now=now,
            bypass=bypass,
        ).to_dict()

    def _audit(self, result: PreflightResult) -> None:
        payload = result.to_dict()
        event = MERGE_AGENT_AUDIT_EVENT
        if self.auditor is not None:
            try:
                self.auditor(event, payload)
            except Exception:
                pass
            return
        try:
            from .audit_logger import log_audit_event

            log_audit_event(
                "merge_agent",
                "preflight",
                status="ok" if result.ok else "blocked",
                details=payload,
            )
        except Exception:
            pass


__all__ = [
    "DEFAULT_ALLOWED_BASE_BRANCHES",
    "MERGE_AGENT_API_PREFIX",
    "MERGE_AGENT_AUDIT_EVENT",
    "MERGE_AGENT_PREFLIGHT_PATH",
    "MERGE_AGENT_PROFILE_NAME",
    "MERGE_AGENT_ROLE_KEY",
    "PROTECTED_HEAD_BRANCHES",
    "ROLE_MERGE_AGENT_BLUEPRINT",
    "MergeAgentIdentity",
    "MergeAgentService",
    "MergeApproval",
    "PreflightResult",
    "PreflightViolation",
    "PullRequestContext",
    "SecretProviderReference",
    "role_merge_agent_seed",
]
