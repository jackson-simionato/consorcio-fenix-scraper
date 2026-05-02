from __future__ import annotations

from dataclasses import dataclass

from consorcio_fenix_scraper.logging import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True)
class StopDiscoveryResult:
    source: str = "floripa-no-ponto"
    status: str = "unavailable"
    stops_found: int = 0
    message: str = "No public unauthenticated stop endpoint configured"


class FloripaNoPontoStopAdapter:
    """Placeholder adapter boundary for public stop-coordinate discovery."""

    def discover(self) -> StopDiscoveryResult:
        result = StopDiscoveryResult()
        if result.status != "success":
            logger.warning("Stop adapter %s status=%s: %s", result.source, result.status, result.message)
        return result
