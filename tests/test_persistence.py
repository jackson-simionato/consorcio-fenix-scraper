from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from consorcio_fenix_scraper.db import (
    Base,
    RouteDirectionRecord,
    RouteRecord,
    RouteVersionRecord,
    ScheduleEntryRecord,
    ScrapeRunRecord,
    ServiceDirectionRecord,
    _linestring_wkt,
    _persist_snapshot,
)
from consorcio_fenix_scraper.domain import (
    DirectionMatchConfidence,
    DirectionMatchMethod,
    ParsedRoutePage,
    RouteDirection,
    RouteSnapshot,
    ScheduleEntry,
    ServiceDirection,
    ServiceDirectionMatch,
)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            ScrapeRunRecord.__table__,
            RouteRecord.__table__,
            RouteVersionRecord.__table__,
            RouteDirectionRecord.__table__,
            ServiceDirectionRecord.__table__,
            ScheduleEntryRecord.__table__,
        ],
    )
    session_factory = sessionmaker(engine, expire_on_commit=False)
    with session_factory.begin() as session:
        yield session


def _snapshot(source_hash: str = "source-a", map_hash: str | None = "map-a") -> RouteSnapshot:
    return RouteSnapshot(
        route=ParsedRoutePage(
            code="110",
            name="TICEN - TITRI",
            slug="ticen-titri",
            page_url="https://www.consorciofenix.com.br/horarios/ticen-titri,110",
            map_url="https://www.consorciofenix.com.br/mapa/110",
            category="convencional",
            fare_cents=600,
            last_changed=date(2026, 5, 2),
        ),
        source_hash=source_hash,
        map_hash=map_hash,
    )


def test_uuid_pk_generates_uuid_values(db_session: Session):
    run = ScrapeRunRecord(source_url="https://www.consorciofenix.com.br/horarios")

    db_session.add(run)
    db_session.flush()

    assert isinstance(run.id, UUID)


def test_reuses_existing_route_version_when_source_and_map_hash_match(db_session: Session):
    first, first_created = _persist_snapshot(db_session, uuid4(), _snapshot())
    second, second_created = _persist_snapshot(db_session, uuid4(), _snapshot())

    versions = db_session.query(RouteVersionRecord).all()

    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    assert len(versions) == 1
    assert versions[0].is_current is True


def test_creates_new_route_version_when_source_hash_changes(db_session: Session):
    first, first_created = _persist_snapshot(db_session, uuid4(), _snapshot(source_hash="source-a"))
    second, second_created = _persist_snapshot(db_session, uuid4(), _snapshot(source_hash="source-b"))

    versions = db_session.query(RouteVersionRecord).all()

    assert first_created is True
    assert second_created is True
    assert first.id != second.id
    assert len(versions) == 2
    assert first.is_current is False
    assert second.is_current is True


def test_creates_new_route_version_when_map_hash_changes(db_session: Session):
    first, first_created = _persist_snapshot(db_session, uuid4(), _snapshot(map_hash="map-a"))
    second, second_created = _persist_snapshot(db_session, uuid4(), _snapshot(map_hash="map-b"))

    versions = db_session.query(RouteVersionRecord).all()

    assert first_created is True
    assert second_created is True
    assert first.id != second.id
    assert len(versions) == 2
    assert first.is_current is False
    assert second.is_current is True


def test_linestring_wkt_uses_srid_4326_and_lon_lat_order():
    direction = RouteDirection(name="Ida", coordinates=[(-48.548, -27.5969), (-48.544, -27.59)])

    assert _linestring_wkt(direction) == "SRID=4326;LINESTRING(-48.548 -27.5969, -48.544 -27.59)"


def test_persists_service_directions_and_links_schedules_through_matches(db_session: Session):
    snapshot = RouteSnapshot(
        route=ParsedRoutePage(
            code="110",
            name="TICEN - TITRI",
            slug="ticen-titri",
            page_url="https://www.consorciofenix.com.br/horarios/ticen-titri,110",
            map_url="https://www.consorciofenix.com.br/mapa/110",
            category="convencional",
            fare_cents=600,
            last_changed=date(2026, 5, 2),
            service_directions=[
                ServiceDirection(
                    sequence=1,
                    departure_label="TICEN",
                    normalized_name="TICEN",
                    direction_kind="ida",
                    schedules=[
                        ScheduleEntry(day_type="Dias uteis", departure_label="TICEN", time="06:00"),
                    ],
                ),
                ServiceDirection(
                    sequence=2,
                    departure_label="TITRI",
                    normalized_name="TITRI",
                    direction_kind="volta",
                    schedules=[
                        ScheduleEntry(day_type="Dias uteis", departure_label="TITRI", time="07:00"),
                    ],
                ),
            ],
            schedules=[
                ScheduleEntry(day_type="Dias uteis", departure_label="TICEN", time="06:00"),
                ScheduleEntry(day_type="Dias uteis", departure_label="TITRI", time="07:00"),
            ],
        ),
        directions=[
            RouteDirection(name="Ida", coordinates=[(-48.548, -27.5969), (-48.544, -27.59)]),
            RouteDirection(name="Volta", coordinates=[(-48.544, -27.59), (-48.548, -27.5969)]),
        ],
        direction_matches=[
            ServiceDirectionMatch(
                service_direction_sequence=1,
                route_direction_sequence=1,
                confidence=DirectionMatchConfidence.MEDIUM,
                method=DirectionMatchMethod.LABEL_ORDER_IDA_VOLTA,
                notes={"departure_label": "TICEN"},
            ),
            ServiceDirectionMatch(
                service_direction_sequence=2,
                route_direction_sequence=2,
                confidence=DirectionMatchConfidence.MEDIUM,
                method=DirectionMatchMethod.LABEL_ORDER_IDA_VOLTA,
                notes={"departure_label": "TITRI"},
            ),
        ],
        source_hash="source-a",
        map_hash="map-a",
    )

    version, created = _persist_snapshot(db_session, uuid4(), snapshot)
    assert created is True

    from consorcio_fenix_scraper.db import _persist_children

    _persist_children(db_session, version.id, snapshot)
    db_session.flush()

    route_directions = db_session.query(RouteDirectionRecord).order_by(RouteDirectionRecord.sequence).all()
    service_directions = db_session.query(ServiceDirectionRecord).order_by(ServiceDirectionRecord.sequence).all()
    schedule_entries = db_session.query(ScheduleEntryRecord).order_by(ScheduleEntryRecord.time).all()

    assert [service.route_direction_id for service in service_directions] == [route_directions[0].id, route_directions[1].id]
    assert [service.confidence for service in service_directions] == [
        DirectionMatchConfidence.MEDIUM.value,
        DirectionMatchConfidence.MEDIUM.value,
    ]
    assert [service.method for service in service_directions] == [
        DirectionMatchMethod.LABEL_ORDER_IDA_VOLTA.value,
        DirectionMatchMethod.LABEL_ORDER_IDA_VOLTA.value,
    ]
    assert [schedule.service_direction_id for schedule in schedule_entries] == [service_directions[0].id, service_directions[1].id]
