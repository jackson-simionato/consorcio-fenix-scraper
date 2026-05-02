from __future__ import annotations

import re
import unicodedata

from consorcio_fenix_scraper.domain import (
    DirectionMatchConfidence,
    DirectionMatchMethod,
    RouteDirection,
    ServiceDirection,
    ServiceDirectionMatch,
)

TERMINAL_TOKENS = ("ticen", "titri", "tican", "tirio", "tilag", "tisan", "terminal")
_KIND_PATTERN = r"(^|[^a-z]){}([^a-z]|$)"


def infer_service_direction_matches(
    service_directions: list[ServiceDirection],
    route_directions: list[RouteDirection],
) -> list[ServiceDirectionMatch]:
    ida_sequence = _find_direction_sequence(route_directions, "ida")
    volta_sequence = _find_direction_sequence(route_directions, "volta")
    services = sorted(service_directions, key=lambda service: service.sequence)

    if ida_sequence is None or volta_sequence is None or len(services) != 2:
        return [_unmatched(service.sequence) for service in services]

    first, second = services
    first_terminal = _looks_like_terminal_departure(first.departure_label)
    second_terminal = _looks_like_terminal_departure(second.departure_label)

    if first_terminal != second_terminal:
        return [
            _matched(
                first.sequence,
                volta_sequence if first_terminal else ida_sequence,
                DirectionMatchConfidence.MEDIUM,
                DirectionMatchMethod.LABEL_ORDER_IDA_VOLTA,
                {"departure_label": first.departure_label},
            ),
            _matched(
                second.sequence,
                volta_sequence if second_terminal else ida_sequence,
                DirectionMatchConfidence.MEDIUM,
                DirectionMatchMethod.LABEL_ORDER_IDA_VOLTA,
                {"departure_label": second.departure_label},
            ),
        ]

    return [
        _matched(
            first.sequence,
            ida_sequence,
            DirectionMatchConfidence.LOW,
            DirectionMatchMethod.SEQUENCE_IDA_VOLTA,
            {"reason": "first schedule group mapped to ida by observed source order"},
        ),
        _matched(
            second.sequence,
            volta_sequence,
            DirectionMatchConfidence.LOW,
            DirectionMatchMethod.SEQUENCE_IDA_VOLTA,
            {"reason": "second schedule group mapped to volta by observed source order"},
        ),
    ]


def _find_direction_sequence(route_directions: list[RouteDirection], kind: str) -> int | None:
    pattern = re.compile(_KIND_PATTERN.format(re.escape(kind)), re.IGNORECASE)
    for sequence, direction in enumerate(route_directions, start=1):
        if pattern.search(_normalize(direction.name)):
            return sequence
    return None


def _looks_like_terminal_departure(label: str) -> bool:
    normalized = _normalize(label)
    return any(token in normalized for token in TERMINAL_TOKENS)


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(char for char in decomposed if not unicodedata.combining(char))
    return ascii_value.lower()


def _matched(
    service_sequence: int,
    route_sequence: int,
    confidence: DirectionMatchConfidence,
    method: DirectionMatchMethod,
    notes: dict[str, str],
) -> ServiceDirectionMatch:
    return ServiceDirectionMatch(
        service_direction_sequence=service_sequence,
        route_direction_sequence=route_sequence,
        confidence=confidence,
        method=method,
        notes=notes,
    )


def _unmatched(service_sequence: int) -> ServiceDirectionMatch:
    return ServiceDirectionMatch(service_direction_sequence=service_sequence)
