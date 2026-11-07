# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Standalone Agents Module
Autarker Agenten-Manager und Delegation-Router für BACH und Ocean.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class AgentMetadata:
    name: str
    role: str = "general_assistant"
    tier: str = "worker"  # thinker_reviewer, worker, light_worker
    model: str = "default"
    description: str = ""
    category: str = "general"
    tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    is_boss: bool = False
    status: str = "idle"  # idle, busy, paused, offline
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


class AgentRegistry:
    """Autarke Agenten-Verwaltung und Task-Router für BACH und Ocean."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentMetadata] = {}

    def register_agent(
        self,
        name: str,
        role: str = "general_assistant",
        tier: str = "worker",
        model: str = "default",
        description: str = "",
        category: str = "general",
        tools: Optional[list[str]] = None,
        skills: Optional[list[str]] = None,
        is_boss: bool = False,
        enabled: bool = True,
    ) -> bool:
        """Registriert einen Agenten oder Fachexperten."""
        if not name or not name.strip():
            return False

        meta = AgentMetadata(
            name=name.strip(),
            role=role,
            tier=tier,
            model=model,
            description=description,
            category=category,
            tools=tools or [],
            skills=skills or [],
            is_boss=is_boss,
            enabled=enabled,
        )
        self._agents[meta.name] = meta
        return True

    def get_agent(self, name: str) -> Optional[AgentMetadata]:
        return self._agents.get(name)

    def list_agents(
        self,
        is_boss: Optional[bool] = None,
        tier: Optional[str] = None,
        category: Optional[str] = None,
        enabled_only: bool = False,
    ) -> list[AgentMetadata]:
        res = list(self._agents.values())
        if is_boss is not None:
            res = [a for a in res if a.is_boss == is_boss]
        if tier:
            res = [a for a in res if a.tier.lower() == tier.lower()]
        if category:
            res = [a for a in res if a.category.lower() == category.lower()]
        if enabled_only:
            res = [a for a in res if a.enabled]
        return res

    def route_task(
        self,
        task_description: str,
        category: Optional[str] = None,
        required_tier: Optional[str] = None,
    ) -> Optional[AgentMetadata]:
        """Findet den am besten geeigneten Agenten/Experten für einen Auftrag."""
        candidates = [a for a in self._agents.values() if a.enabled and a.status != "offline"]
        if not candidates:
            return None

        if required_tier:
            tier_matches = [a for a in candidates if a.tier.lower() == required_tier.lower()]
            if tier_matches:
                candidates = tier_matches

        if category:
            cat_matches = [a for a in candidates if a.category.lower() == category.lower()]
            if cat_matches:
                candidates = cat_matches

        # Score basierend auf Schlüsselwörtern in Rolle und Beschreibung
        desc_lower = task_description.lower()
        scored: list[tuple[int, AgentMetadata]] = []

        for agent in candidates:
            score = 0
            if agent.name.lower() in desc_lower:
                score += 10
            if agent.role.lower() in desc_lower:
                score += 5
            for sk in agent.skills:
                if sk.lower() in desc_lower:
                    score += 3
            for tool in agent.tools:
                if tool.lower() in desc_lower:
                    score += 2
            scored.append((score, agent))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    def update_agent_status(self, name: str, status: str) -> bool:
        if name in self._agents:
            self._agents[name].status = status
            return True
        return False

    def get_status_summary(self) -> dict[str, Any]:
        return {
            "total_agents": len(self._agents),
            "bosses": sum(1 for a in self._agents.values() if a.is_boss),
            "experts": sum(1 for a in self._agents.values() if not a.is_boss),
            "by_status": {
                "idle": sum(1 for a in self._agents.values() if a.status == "idle"),
                "busy": sum(1 for a in self._agents.values() if a.status == "busy"),
                "paused": sum(1 for a in self._agents.values() if a.status == "paused"),
                "offline": sum(1 for a in self._agents.values() if a.status == "offline"),
            },
        }
