# coding: utf-8
"""Ocean-Modul ocean-resources: RAM-Distributor und Modell-Runtime (#2441).
Versionierter Vertrag (ellmos.ocean-resources.v1) für:
- Anschluss und Fähigkeitsmeldung
- RAM-Antrag / Zuspruch mit geschützter Systemreserve
- Prioritätsklassen (fackel_holder > interactive > background > batch)
- Fallback-Hinweis und Freigabebestätigung (Release-Receipt)
- Ablösung von fackel.py, compute_lock (inkl. Telegram-Compute-Lock),
  host_inference_gate, local_resource_reserve und buddha_cold_start hinter Adapter.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

PRIORITY_RANK: dict[str, int] = {
    "fackel_holder": 40,
    "interactive": 30,
    "background": 20,
    "batch": 10,
}


@dataclass
class OceanRamDistributor:
    total_ram_gb: float = 64.0
    protected_reserve_gb: float = 12.0
    active_grants: dict[str, dict[str, Any]] = field(default_factory=dict)
    fence: int = 0

    @property
    def allocatable_ram_gb(self) -> float:
        used = sum(float(g["granted_ram_gb"]) for g in self.active_grants.values())
        return max(0.0, round(self.total_ram_gb - self.protected_reserve_gb - used, 2))

    def request_admission(
        self,
        *,
        consumer_id: str,
        model: str,
        requested_ram_gb: float,
        priority: str = "background",
        fallback_target: str | None = "cloud_or_queue",
    ) -> dict[str, Any]:
        if priority not in PRIORITY_RANK:
            raise ValueError(f"Ungültige Prioritätsklasse: {priority}")
        req = float(requested_ram_gb)
        self.fence += 1
        if req <= self.allocatable_ram_gb:
            grant = {
                "schema": "ellmos.ocean-resources.v1",
                "admitted": True,
                "consumer_id": consumer_id,
                "model": model,
                "granted_ram_gb": req,
                "priority": priority,
                "fence": self.fence,
                "fallback_notice": None,
            }
            self.active_grants[consumer_id] = grant
            return grant

        return {
            "schema": "ellmos.ocean-resources.v1",
            "admitted": False,
            "consumer_id": consumer_id,
            "model": model,
            "granted_ram_gb": 0.0,
            "priority": priority,
            "fence": self.fence,
            "available_allocatable_gb": self.allocatable_ram_gb,
            "fallback_notice": f"RAM-Reserve geschützt ({self.protected_reserve_gb} GB); bitte '{fallback_target}' nutzen.",
        }

    def release_grant(self, consumer_id: str, *, expected_fence: int | None = None) -> dict[str, Any]:
        grant = self.active_grants.get(consumer_id)
        if grant is None:
            return {"released": False, "consumer_id": consumer_id}
        if expected_fence is not None and grant["fence"] != expected_fence:
            raise RuntimeError("Fence-Konflikt bei RAM-Freigabe")
        del self.active_grants[consumer_id]
        self.fence += 1
        return {
            "schema": "ellmos.ocean-resources.v1",
            "released": True,
            "consumer_id": consumer_id,
            "freed_ram_gb": grant["granted_ram_gb"],
            "release_fence": self.fence,
            "available_allocatable_gb": self.allocatable_ram_gb,
        }
