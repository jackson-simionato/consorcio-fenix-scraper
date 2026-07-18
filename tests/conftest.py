import pytest

from consorcio_fenix_scraper.domain import (
    DirectionMatchConfidence,
    DirectionMatchMethod,
    FarePolicy,
    ItineraryStep,
    ParsedRoutePage,
    RouteDirection,
    RouteSnapshot,
    ScheduleEntry,
    ServiceDirection,
    ServiceDirectionMatch,
)


@pytest.fixture
def complete_snapshot_factory():
    def build(
        code: str = "110",
        *,
        source_hash: str = "source-a",
        map_hash: str | None = "map-a",
        fare_cents: int = 770,
    ) -> RouteSnapshot:
        departure_label = f"Terminal {code}"
        schedule = ScheduleEntry(
            day_type="Dias uteis",
            departure_label=departure_label,
            time="06:00",
            flags=("E",),
        )
        return RouteSnapshot(
            route=ParsedRoutePage(
                code=code,
                name=f"Route {code}",
                slug=f"route-{code}",
                page_url=f"https://example.test/horarios/route-{code},{code}",
                map_url=f"https://example.test/mapa/{code}",
                fare_region=f"Region {code}",
                fare_policy=FarePolicy(region=f"Region {code}", cash_qrcode_pix_cents=fare_cents),
                service_directions=[
                    ServiceDirection(
                        sequence=1,
                        departure_label=departure_label,
                        normalized_name=departure_label,
                        direction_kind="ida",
                        schedules=[schedule],
                    )
                ],
                schedules=[schedule],
                itinerary_steps=[ItineraryStep(sequence=1, name=departure_label)],
            ),
            directions=[
                RouteDirection(
                    name="Ida",
                    coordinates=[(-48.50, -27.50), (-48.499, -27.50)],
                )
            ],
            direction_matches=[
                ServiceDirectionMatch(
                    service_direction_sequence=1,
                    route_direction_sequence=1,
                    confidence=DirectionMatchConfidence.MEDIUM,
                    method=DirectionMatchMethod.LABEL_ORDER_IDA_VOLTA,
                )
            ],
            source_hash=source_hash,
            map_hash=map_hash,
        )

    return build
