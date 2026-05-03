from pytest import approx

from consorcio_fenix_scraper.domain import RouteDirection
from consorcio_fenix_scraper.segments import materialize_route_segments


def test_materializes_short_two_point_route_direction_as_one_segment():
    direction = RouteDirection(name="IDA", coordinates=[(-48.55, -27.59), (-48.55, -27.589)])

    segments = materialize_route_segments(direction)

    assert len(segments) == 1
    segment = segments[0]
    assert segment.sequence == 1
    assert segment.source_segment_sequence == 1
    assert segment.source_fraction_start == 0
    assert segment.source_fraction_end == 1
    assert segment.coordinates == [(-48.55, -27.59), (-48.55, -27.589)]
    assert segment.bearing_degrees == approx(0, abs=0.1)
    assert segment.distance_meters == approx(111, rel=0.01)
    assert segment.cumulative_distance_meters == approx(segment.distance_meters)


def test_materializes_multi_point_route_direction_in_source_order_with_cumulative_distance():
    direction = RouteDirection(
        name="IDA",
        coordinates=[
            (-48.55, -27.59),
            (-48.55, -27.589),
            (-48.549, -27.589),
        ],
    )

    segments = materialize_route_segments(direction)

    assert [segment.sequence for segment in segments] == [1, 2]
    assert [segment.source_segment_sequence for segment in segments] == [1, 2]
    assert segments[0].coordinates == [(-48.55, -27.59), (-48.55, -27.589)]
    assert segments[1].coordinates == [(-48.55, -27.589), (-48.549, -27.589)]
    assert segments[0].bearing_degrees == approx(0, abs=0.1)
    assert segments[1].bearing_degrees == approx(90, abs=0.1)
    assert segments[1].cumulative_distance_meters == approx(
        segments[0].distance_meters + segments[1].distance_meters
    )


def test_splits_source_segments_longer_than_max_length_with_lineage():
    direction = RouteDirection(name="IDA", coordinates=[(-48.55, -27.59), (-48.55, -27.58)])

    segments = materialize_route_segments(direction, max_segment_length_meters=400)

    assert len(segments) == 3
    assert [segment.sequence for segment in segments] == [1, 2, 3]
    assert [segment.source_segment_sequence for segment in segments] == [1, 1, 1]
    assert [segment.source_fraction_start for segment in segments] == approx([0, 1 / 3, 2 / 3])
    assert [segment.source_fraction_end for segment in segments] == approx([1 / 3, 2 / 3, 1])
    assert segments[0].coordinates[0] == (-48.55, -27.59)
    assert segments[-1].coordinates[-1] == (-48.55, -27.58)
    assert [segment.bearing_degrees for segment in segments] == approx([0, 0, 0], abs=0.1)
    assert sum(segment.distance_meters for segment in segments) == approx(1112, rel=0.01)
    assert segments[-1].cumulative_distance_meters == approx(sum(segment.distance_meters for segment in segments))


def test_route_direction_with_fewer_than_two_coordinates_has_no_segments():
    direction = RouteDirection(name="IDA", coordinates=[(-48.55, -27.59)])

    assert materialize_route_segments(direction) == []
