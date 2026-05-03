from __future__ import annotations

import math

from consorcio_fenix_scraper.domain import MaterializedRouteSegment, RouteDirection

EARTH_RADIUS_METERS = 6_371_000


def materialize_route_segments(
    direction: RouteDirection,
    max_segment_length_meters: float = 250.0,
) -> list[MaterializedRouteSegment]:
    coordinates = direction.coordinates
    if len(coordinates) < 2:
        return []

    segments: list[MaterializedRouteSegment] = []
    cumulative_distance = 0.0
    for source_index, (start, end) in enumerate(zip(coordinates, coordinates[1:]), start=1):
        source_distance = _distance_meters(start, end)
        split_count = max(1, math.ceil(source_distance / max_segment_length_meters))
        for split_index in range(split_count):
            fraction_start = split_index / split_count
            fraction_end = (split_index + 1) / split_count
            segment_start = _interpolate(start, end, fraction_start)
            segment_end = _interpolate(start, end, fraction_end)
            distance = _distance_meters(segment_start, segment_end)
            cumulative_distance += distance
            segments.append(
                MaterializedRouteSegment(
                    sequence=len(segments) + 1,
                    source_segment_sequence=source_index,
                    source_fraction_start=fraction_start,
                    source_fraction_end=fraction_end,
                    coordinates=[segment_start, segment_end],
                    bearing_degrees=_bearing_degrees(segment_start, segment_end),
                    distance_meters=distance,
                    cumulative_distance_meters=cumulative_distance,
                )
            )
    return segments


def _distance_meters(start: tuple[float, float], end: tuple[float, float]) -> float:
    lon1, lat1 = map(math.radians, start)
    lon2, lat2 = map(math.radians, end)
    delta_lon = lon2 - lon1
    delta_lat = lat2 - lat1
    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return EARTH_RADIUS_METERS * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _bearing_degrees(start: tuple[float, float], end: tuple[float, float]) -> float:
    lon1, lat1 = map(math.radians, start)
    lon2, lat2 = map(math.radians, end)
    delta_lon = lon2 - lon1
    y = math.sin(delta_lon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _interpolate(start: tuple[float, float], end: tuple[float, float], fraction: float) -> tuple[float, float]:
    start_lon, start_lat = start
    end_lon, end_lat = end
    return (
        start_lon + (end_lon - start_lon) * fraction,
        start_lat + (end_lat - start_lat) * fraction,
    )
