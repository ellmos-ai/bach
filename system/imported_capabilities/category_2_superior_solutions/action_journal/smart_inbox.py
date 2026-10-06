from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .contracts import UndoReceipt
from .storage_policy import PolicySet, StoragePlan, preview_storage


@dataclass(frozen=True, slots=True)
class RoutingRule:
    suffixes: tuple[str, ...]
    target_dir: Path
    category: str | None = None
    match_terms: tuple[str, ...] = ()
    min_confidence: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "suffixes",
            tuple(
                item.casefold() if item.startswith(".") else f".{item.casefold()}"
                for item in self.suffixes
            ),
        )
        object.__setattr__(self, "target_dir", Path(self.target_dir).resolve())
        if self.category is not None:
            object.__setattr__(self, "category", str(self.category).strip())
        object.__setattr__(
            self,
            "match_terms",
            tuple(str(item).strip() for item in self.match_terms if str(item).strip()),
        )
        object.__setattr__(self, "min_confidence", float(self.min_confidence))


def plan_inbox(
    sources: Iterable[str | Path],
    *,
    rules: tuple[RoutingRule, ...],
    policies: PolicySet,
    source_records: Mapping[str, Any] | None = None,
    texts: Mapping[str, str] | None = None,
    classification_policy: str = "suffix_routes",
    confidence_threshold: float = 1.0,
) -> tuple[StoragePlan, ...]:
    plans: list[StoragePlan] = []
    records = source_records or {}
    source_texts = texts or {}
    for source in sources:
        source_path = Path(source).resolve()
        record = records.get(str(source_path)) or next(
            (
                r
                for r in records.values()
                if Path(getattr(r, "path", "")).resolve() == source_path
            ),
            None,
        )
        if record is not None and getattr(record, "extraction_status", "") == "unreadable":
            plans.append(
                StoragePlan(
                    source=str(source_path),
                    target=str(source_path),
                    allowed=False,
                    reasons=(f"unreadable_input:{source_path.name}",),
                    retention_action="keep",
                    original_policy="keep",
                )
            )
            continue

        if classification_policy == "content_categories":
            record_id = getattr(record, "source_id", "") if record is not None else ""
            text = (
                source_texts.get(record_id)
                if record_id
                else source_texts.get(str(source_path), "")
            )
            if text is None or not text.strip() or "\x00" in text:
                plans.append(
                    StoragePlan(
                        source=str(source_path),
                        target=str(source_path),
                        allowed=False,
                        reasons=(f"unreadable_input:{source_path.name}",),
                        retention_action="keep",
                        original_policy="keep",
                    )
                )
                continue

            candidates: list[tuple[RoutingRule, float]] = []
            for rule in rules:
                if rule.suffixes and source_path.suffix.casefold() not in rule.suffixes:
                    continue
                if rule.match_terms:
                    matched = sum(
                        1 for term in rule.match_terms if term.casefold() in text.casefold()
                    )
                    confidence = matched / len(rule.match_terms)
                    if (
                        confidence >= min(rule.min_confidence, confidence_threshold)
                        and matched > 0
                    ):
                        candidates.append((rule, confidence))
                elif rule.category is not None:
                    candidates.append((rule, 1.0))

            if not candidates:
                plans.append(
                    StoragePlan(
                        source=str(source_path),
                        target=str(source_path),
                        allowed=False,
                        reasons=(f"unclassifiable_input:{source_path.name}",),
                        retention_action="keep",
                        original_policy="keep",
                    )
                )
                continue

            candidates.sort(key=lambda item: item[1], reverse=True)
            if len(candidates) > 1 and candidates[0][1] == candidates[1][1]:
                plans.append(
                    StoragePlan(
                        source=str(source_path),
                        target=str(source_path),
                        allowed=False,
                        reasons=(f"ambiguous_classification:{source_path.name}",),
                        retention_action="keep",
                        original_policy="keep",
                    )
                )
                continue
            route = candidates[0][0]
        else:
            fallback = next(
                (rule for rule in rules if source_path.suffix.casefold() in rule.suffixes),
                None,
            )
            if fallback is None:
                plans.append(
                    StoragePlan(
                        source=str(source_path),
                        target=str(source_path),
                        allowed=False,
                        reasons=("no_matching_route",),
                        retention_action="keep",
                        original_policy="keep",
                    )
                )
                continue
            route = fallback

        try:
            policy = policies.resolve(source_path)
        except LookupError:
            plans.append(
                StoragePlan(
                    source=str(source_path),
                    target=str(route.target_dir / source_path.name),
                    allowed=False,
                    reasons=("no_matching_policy",),
                    retention_action="keep",
                    original_policy="keep",
                    category=route.category,
                )
            )
            continue
        preview = preview_storage(source_path, route.target_dir, policy)
        if preview.conversion_target is not None:
            preview = replace(
                preview,
                allowed=False,
                reasons=preview.reasons + ("smart_inbox_conversion_unsupported",),
                category=route.category,
            )
        else:
            preview = replace(
                preview,
                operation="move",
                original_policy="move",
                category=route.category,
            )
        plans.append(preview)
    return tuple(plans)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def move_action_id(plan: StoragePlan, *, sha256: str | None = None) -> str:
    digest = sha256 or file_sha256(Path(plan.source))
    return "move_" + hashlib.sha256(
        f"{plan.operation}|{plan.source}|{plan.target}|{digest}".encode()
    ).hexdigest()[:20]


def apply_move(plan: StoragePlan, *, approved: bool) -> UndoReceipt:
    if not approved:
        raise PermissionError("move requires immediate human approval")
    if not plan.allowed:
        raise PermissionError(f"blocked storage plan: {', '.join(plan.reasons)}")
    if plan.operation != "move":
        raise ValueError("apply_move accepts only move operations")
    source = Path(plan.source)
    target = Path(plan.target)
    if not source.is_file():
        raise FileNotFoundError(source)
    if not target.parent.is_dir():
        raise FileNotFoundError(target.parent)
    if target.exists():
        raise FileExistsError(target)

    digest = file_sha256(source)
    action_id = move_action_id(plan, sha256=digest)
    source.replace(target)
    return UndoReceipt(
        action_id=action_id,
        before={"path": str(source), "sha256": digest},
        after={"path": str(target), "sha256": digest},
        undo_plan={"action": "move", "source": str(target), "target": str(source)},
    )


def undo_move(receipt: UndoReceipt, *, approved: bool) -> UndoReceipt:
    if not approved:
        raise PermissionError("undo requires immediate human approval")
    if receipt.undo_plan.get("action") != "move":
        raise ValueError("unsupported undo action")
    source = Path(str(receipt.undo_plan["source"]))
    target = Path(str(receipt.undo_plan["target"]))
    if target.exists():
        raise FileExistsError(target)
    if not source.is_file():
        raise FileNotFoundError(source)
    if file_sha256(source) != receipt.after.get("sha256"):
        raise RuntimeError("undo source changed after the original action")
    source.replace(target)
    return replace(receipt, status="undone")
