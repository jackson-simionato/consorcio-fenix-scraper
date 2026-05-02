from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StopDiscoveryResult:
    source: str = "floripa-no-ponto"
    status: str = "unavailable"
    stops_found: int = 0
    message: str = "No public unauthenticated stop endpoint configured"


class FloripaNoPontoStopAdapter:
    """Placeholder adapter boundary for public stop-coordinate discovery."""

    def discover(self) -> StopDiscoveryResult:
        return StopDiscoveryResult()
