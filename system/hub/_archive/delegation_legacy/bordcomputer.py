#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bordcomputer Health-Monitor - Circuit-Breaker & Overkill-Erkennung
==================================================================

Überwacht die Gesundheit der LLM-Provider:
- Circuit-Breaker pro Provider (Fehler-Schwelle, Cooldown, Auto-Recovery)
- Overkill-Erkennung (Opus für Simple-Tasks flaggen)
- Token-Explosions-Alerts (>3x Budget)

Einhängepunkte: partner.py, tokens.py, monitor_processes

Teil der clutch-bridge (BACH Task [1077]).
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class CircuitState(Enum):
    """Circuit-Breaker Zustände."""
    CLOSED = "closed"         # Normal, alles fließt
    OPEN = "open"             # Gesperrt, Fehler-Schwelle erreicht
    HALF_OPEN = "half_open"   # Testphase nach Cooldown


@dataclass
class ProviderCircuit:
    """Circuit-Breaker für einen einzelnen Provider."""
    name: str
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    total_requests: int = 0
    total_failures: int = 0

    # Konfiguration
    failure_threshold: int = 3       # Fehler bis OPEN
    cooldown_seconds: float = 60.0   # Sekunden bis HALF_OPEN
    recovery_successes: int = 2      # Erfolge in HALF_OPEN bis CLOSED

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "total_requests": self.total_requests,
            "total_failures": self.total_failures,
            "failure_rate": round(self.total_failures / max(1, self.total_requests) * 100, 1),
        }


@dataclass
class OverkillAlert:
    """Alert wenn Opus für einfache Tasks verwendet wird."""
    timestamp: float
    task_beschreibung: str
    strecken_typ: str
    strecken_schwierigkeit: int
    gewaehltes_modell: str
    empfohlenes_modell: str

    def to_dict(self) -> dict:
        return {
            "task": self.task_beschreibung[:80],
            "strecke": self.strecken_typ,
            "schwierigkeit": self.strecken_schwierigkeit,
            "gewaehlt": self.gewaehltes_modell,
            "empfohlen": self.empfohlenes_modell,
        }


@dataclass
class TokenExplosionAlert:
    """Alert bei Token-Verbrauch > 3x Budget."""
    timestamp: float
    provider: str
    tokens_used: int
    tokens_expected: int
    factor: float

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "tokens_used": self.tokens_used,
            "tokens_expected": self.tokens_expected,
            "factor": round(self.factor, 1),
        }


class BordcomputerMonitor:
    """Health-Monitor für LLM-Provider mit Circuit-Breaker."""

    MAX_ALERTS = 50  # Maximale Anzahl gespeicherter Alerts

    def __init__(self):
        self._circuits: Dict[str, ProviderCircuit] = {}
        self._overkill_alerts: List[OverkillAlert] = []
        self._token_alerts: List[TokenExplosionAlert] = []

    # ─── Circuit-Breaker ────────────────────────────────────────

    def get_circuit(self, provider: str) -> ProviderCircuit:
        """Gibt Circuit für Provider zurück, erstellt bei Bedarf."""
        if provider not in self._circuits:
            self._circuits[provider] = ProviderCircuit(name=provider)
        return self._circuits[provider]

    def is_available(self, provider: str) -> bool:
        """Prüft ob Provider verfügbar ist (Circuit nicht OPEN)."""
        circuit = self.get_circuit(provider)

        if circuit.state == CircuitState.CLOSED:
            return True

        if circuit.state == CircuitState.OPEN:
            # Prüfe ob Cooldown abgelaufen → HALF_OPEN
            elapsed = time.time() - circuit.last_failure_time
            if elapsed >= circuit.cooldown_seconds:
                circuit.state = CircuitState.HALF_OPEN
                circuit.success_count = 0
                return True
            return False

        # HALF_OPEN: Erlaubt (Test-Request)
        return True

    def record_success(self, provider: str) -> None:
        """Registriert erfolgreiche Anfrage."""
        circuit = self.get_circuit(provider)
        circuit.total_requests += 1
        circuit.last_success_time = time.time()

        if circuit.state == CircuitState.HALF_OPEN:
            circuit.success_count += 1
            if circuit.success_count >= circuit.recovery_successes:
                circuit.state = CircuitState.CLOSED
                circuit.failure_count = 0
                circuit.success_count = 0
        elif circuit.state == CircuitState.CLOSED:
            # Reset failure count bei Erfolg
            circuit.failure_count = 0

    def record_failure(self, provider: str) -> CircuitState:
        """Registriert fehlgeschlagene Anfrage. Gibt neuen State zurück."""
        circuit = self.get_circuit(provider)
        circuit.total_requests += 1
        circuit.total_failures += 1
        circuit.failure_count += 1
        circuit.last_failure_time = time.time()

        if circuit.state == CircuitState.HALF_OPEN:
            # Sofort zurück zu OPEN
            circuit.state = CircuitState.OPEN
            circuit.success_count = 0
        elif circuit.state == CircuitState.CLOSED:
            if circuit.failure_count >= circuit.failure_threshold:
                circuit.state = CircuitState.OPEN
                circuit.success_count = 0

        return circuit.state

    # ─── Overkill-Erkennung ─────────────────────────────────────

    def check_overkill(
        self,
        task_beschreibung: str,
        gewaehltes_modell: str,
        strecken_typ: str = "",
        strecken_schwierigkeit: int = 0,
        empfohlener_gang: str = "",
    ) -> Optional[OverkillAlert]:
        """
        Prüft ob ein zu mächtiges Modell für einen einfachen Task
        verwendet wird.

        Returns:
            OverkillAlert wenn Overkill erkannt, sonst None
        """
        modell_rang = {"haiku": 1, "sonnet": 2, "opus": 3}
        gewaehlt = modell_rang.get(gewaehltes_modell, 0)
        empfohlen = modell_rang.get(empfohlener_gang, 0)

        # Overkill: gewähltes Modell ≥ 2 Stufen über Empfehlung
        if gewaehlt > 0 and empfohlen > 0 and (gewaehlt - empfohlen) >= 2:
            alert = OverkillAlert(
                timestamp=time.time(),
                task_beschreibung=task_beschreibung,
                strecken_typ=strecken_typ,
                strecken_schwierigkeit=strecken_schwierigkeit,
                gewaehltes_modell=gewaehltes_modell,
                empfohlenes_modell=empfohlener_gang,
            )
            self._overkill_alerts.append(alert)
            if len(self._overkill_alerts) > self.MAX_ALERTS:
                self._overkill_alerts = self._overkill_alerts[-self.MAX_ALERTS:]
            return alert

        return None

    # ─── Token-Explosions-Erkennung ─────────────────────────────

    def check_token_explosion(
        self,
        provider: str,
        tokens_used: int,
        tokens_expected: int,
    ) -> Optional[TokenExplosionAlert]:
        """
        Prüft ob der Token-Verbrauch > 3x Budget ist.

        Returns:
            TokenExplosionAlert wenn Explosion erkannt, sonst None
        """
        if tokens_expected <= 0:
            return None

        factor = tokens_used / tokens_expected
        if factor > 3.0:
            alert = TokenExplosionAlert(
                timestamp=time.time(),
                provider=provider,
                tokens_used=tokens_used,
                tokens_expected=tokens_expected,
                factor=factor,
            )
            self._token_alerts.append(alert)
            if len(self._token_alerts) > self.MAX_ALERTS:
                self._token_alerts = self._token_alerts[-self.MAX_ALERTS:]
            return alert

        return None

    # ─── Status & Reporting ─────────────────────────────────────

    def status(self) -> dict:
        """Gibt Gesamtstatus aller Provider und Alerts zurück."""
        circuits = {}
        for name, circuit in self._circuits.items():
            # Aktualisiere OPEN→HALF_OPEN wenn Cooldown abgelaufen
            if circuit.state == CircuitState.OPEN:
                elapsed = time.time() - circuit.last_failure_time
                if elapsed >= circuit.cooldown_seconds:
                    circuit.state = CircuitState.HALF_OPEN
                    circuit.success_count = 0
            circuits[name] = circuit.to_dict()

        return {
            "circuits": circuits,
            "overkill_alerts": len(self._overkill_alerts),
            "token_alerts": len(self._token_alerts),
            "recent_overkill": [
                a.to_dict() for a in self._overkill_alerts[-5:]
            ],
            "recent_token_alerts": [
                a.to_dict() for a in self._token_alerts[-5:]
            ],
        }

    def format_status(self) -> str:
        """Gibt formatierten Status-String zurück."""
        s = self.status()
        lines = ["[BORDCOMPUTER] Health-Monitor Status", "=" * 50]

        if not s["circuits"]:
            lines.append("  Keine Provider registriert.")
        else:
            lines.append("\n  Provider-Status:")
            for name, info in s["circuits"].items():
                state_icon = {
                    "closed": "✓", "half_open": "~", "open": "✗"
                }.get(info["state"], "?")
                lines.append(
                    f"    [{state_icon}] {name}: {info['state']} "
                    f"(Fehler: {info['failure_count']}, "
                    f"Rate: {info['failure_rate']}%)"
                )

        if s["overkill_alerts"] > 0:
            lines.append(f"\n  Overkill-Alerts: {s['overkill_alerts']}")
            for a in s["recent_overkill"]:
                lines.append(
                    f"    ! {a['strecke']}: {a['gewaehlt']} statt {a['empfohlen']}"
                )

        if s["token_alerts"] > 0:
            lines.append(f"\n  Token-Explosions: {s['token_alerts']}")
            for a in s["recent_token_alerts"]:
                lines.append(
                    f"    ! {a['provider']}: {a['factor']}x Budget "
                    f"({a['tokens_used']}/{a['tokens_expected']})"
                )

        return "\n".join(lines)


# ─── Singleton ──────────────────────────────────────────────────────

_monitor_instance: Optional[BordcomputerMonitor] = None


def get_bordcomputer() -> BordcomputerMonitor:
    """Gibt Singleton-Instanz zurück."""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = BordcomputerMonitor()
    return _monitor_instance
