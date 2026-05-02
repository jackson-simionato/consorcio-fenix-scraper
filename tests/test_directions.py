from consorcio_fenix_scraper.domain import (
    DirectionMatchConfidence,
    DirectionMatchMethod,
    RouteDirection,
    ScheduleEntry,
    ServiceDirection,
)


def _service(sequence: int, label: str) -> ServiceDirection:
    return ServiceDirection(
        sequence=sequence,
        departure_label=label,
        schedules=[ScheduleEntry(day_type="Sábado", departure_label=label, time="06:00")],
    )


def test_infers_terminal_volta_and_neighborhood_ida_with_medium_confidence():
    from consorcio_fenix_scraper.directions import infer_service_direction_matches

    services = [
        _service(1, "Saída Bairro de Fátima"),
        _service(2, "Saída TICEN - Plataforma B - Box 6"),
    ]
    directions = [
        RouteDirection(name="VOLTA", coordinates=[(-48.55, -27.59), (-48.59, -27.58)]),
        RouteDirection(name="IDA", coordinates=[(-48.59, -27.58), (-48.55, -27.59)]),
    ]

    matches = infer_service_direction_matches(services, directions)

    assert [(match.service_direction_sequence, match.route_direction_sequence) for match in matches] == [
        (1, 2),
        (2, 1),
    ]
    assert [match.confidence for match in matches] == [
        DirectionMatchConfidence.MEDIUM,
        DirectionMatchConfidence.MEDIUM,
    ]
    assert [match.method for match in matches] == [
        DirectionMatchMethod.LABEL_ORDER_IDA_VOLTA,
        DirectionMatchMethod.LABEL_ORDER_IDA_VOLTA,
    ]


def test_uses_low_confidence_sequence_match_when_labels_do_not_identify_terminal_side():
    from consorcio_fenix_scraper.directions import infer_service_direction_matches

    services = [_service(1, "Saída Ponto A"), _service(2, "Saída Ponto B")]
    directions = [
        RouteDirection(name="VOLTA", coordinates=[(-48.55, -27.59), (-48.59, -27.58)]),
        RouteDirection(name="IDA", coordinates=[(-48.59, -27.58), (-48.55, -27.59)]),
    ]

    matches = infer_service_direction_matches(services, directions)

    assert [(match.service_direction_sequence, match.route_direction_sequence) for match in matches] == [
        (1, 2),
        (2, 1),
    ]
    assert [match.confidence for match in matches] == [
        DirectionMatchConfidence.LOW,
        DirectionMatchConfidence.LOW,
    ]
    assert [match.method for match in matches] == [
        DirectionMatchMethod.SEQUENCE_IDA_VOLTA,
        DirectionMatchMethod.SEQUENCE_IDA_VOLTA,
    ]


def test_unmatched_when_ida_volta_pair_is_not_available():
    from consorcio_fenix_scraper.directions import infer_service_direction_matches

    services = [_service(1, "Saída Bairro"), _service(2, "Saída Terminal")]
    directions = [RouteDirection(name="Circular", coordinates=[(-48.55, -27.59), (-48.59, -27.58)])]

    matches = infer_service_direction_matches(services, directions)

    assert [(match.service_direction_sequence, match.route_direction_sequence) for match in matches] == [
        (1, None),
        (2, None),
    ]
    assert [match.confidence for match in matches] == [
        DirectionMatchConfidence.NONE,
        DirectionMatchConfidence.NONE,
    ]
    assert [match.method for match in matches] == [
        DirectionMatchMethod.UNMATCHED,
        DirectionMatchMethod.UNMATCHED,
    ]
