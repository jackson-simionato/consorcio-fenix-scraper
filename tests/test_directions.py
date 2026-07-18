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
        RouteDirection(name="VOLTA", direction_kind="volta", coordinates=[(-48.55, -27.59), (-48.59, -27.58)]),
        RouteDirection(name="IDA", direction_kind="ida", coordinates=[(-48.59, -27.58), (-48.55, -27.59)]),
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
        RouteDirection(name="VOLTA", direction_kind="volta", coordinates=[(-48.55, -27.59), (-48.59, -27.58)]),
        RouteDirection(name="IDA", direction_kind="ida", coordinates=[(-48.59, -27.58), (-48.55, -27.59)]),
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


def test_matching_uses_parsed_kinds_instead_of_rescanning_raw_names():
    from consorcio_fenix_scraper.directions import infer_service_direction_matches

    services = [_service(1, "Saída Bairro"), _service(2, "Saída Terminal")]
    directions = [
        RouteDirection(name="Ida", coordinates=[(-48.55, -27.59), (-48.59, -27.58)]),
        RouteDirection(name="Volta", coordinates=[(-48.59, -27.58), (-48.55, -27.59)]),
    ]

    matches = infer_service_direction_matches(services, directions)

    assert [match.route_direction_sequence for match in matches] == [None, None]


def test_matching_uses_kinds_from_a_clean_parsed_pair():
    from consorcio_fenix_scraper.directions import infer_service_direction_matches
    from consorcio_fenix_scraper.parsers.kml import parse_kml_directions

    kml = '''<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
      <Placemark><name>294 Ida T.SAN - T.FOR</name><LineString><coordinates>-48.1,-27.1 -48.2,-27.2</coordinates></LineString></Placemark>
      <Placemark><name>294 Volta T.FOR - T.SAN</name><LineString><coordinates>-48.2,-27.2 -48.1,-27.1</coordinates></LineString></Placemark>
    </Document></kml>'''

    matches = infer_service_direction_matches(
        [_service(1, "Saída Bairro"), _service(2, "Saída Terminal")],
        parse_kml_directions(kml),
    )

    assert [match.route_direction_sequence for match in matches] == [1, 2]


def test_matching_leaves_an_ambiguous_parsed_pair_unmatched():
    from consorcio_fenix_scraper.directions import infer_service_direction_matches
    from consorcio_fenix_scraper.parsers.kml import parse_kml_directions

    kml = '''<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
      <Placemark><name>181-ida-volta</name><LineString><coordinates>-48.1,-27.1 -48.2,-27.2</coordinates></LineString></Placemark>
      <Placemark><name>181 Volta</name><LineString><coordinates>-48.2,-27.2 -48.1,-27.1</coordinates></LineString></Placemark>
    </Document></kml>'''

    matches = infer_service_direction_matches(
        [_service(1, "Saída Bairro"), _service(2, "Saída Terminal")],
        parse_kml_directions(kml),
    )

    assert [match.route_direction_sequence for match in matches] == [None, None]


def test_route_direction_without_archived_kind_deserializes_as_unclassified():
    direction = RouteDirection.model_validate(
        {
            "name": "Ida",
            "coordinates": [[-48.55, -27.59], [-48.59, -27.58]],
            "geometry_type": "LineString",
        }
    )

    assert direction.direction_kind is None
