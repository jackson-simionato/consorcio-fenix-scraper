from datetime import date
from uuid import UUID

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from consorcio_fenix_scraper.db import (
    Base,
    FareVersionRecord,
    RouteDirectionRecord,
    RouteSegmentRecord,
    RouteRecord,
    RouteVersionRecord,
    ScheduleEntryRecord,
    ScrapeRunRecord,
    ServiceDirectionRecord,
    _linestring_wkt,
    _postgresql_fare_version_upsert,
    _postgresql_route_upsert,
    _postgresql_route_version_insert,
    persist_snapshots,
)
from consorcio_fenix_scraper.domain import (
    DirectionMatchConfidence,
    DirectionMatchMethod,
    FarePolicy,
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
            FareVersionRecord.__table__,
            RouteRecord.__table__,
            RouteVersionRecord.__table__,
            RouteDirectionRecord.__table__,
            RouteSegmentRecord.__table__,
            ServiceDirectionRecord.__table__,
            ScheduleEntryRecord.__table__,
        ],
    )
    session_factory = sessionmaker(engine, expire_on_commit=False)
    with session_factory.begin() as session:
        yield session


def _snapshot(
    source_hash: str = "source-a",
    map_hash: str | None = "map-a",
    cash_qrcode_pix_cents: int = 770,
    code: str = "110",
) -> RouteSnapshot:
    name = "TICEN - TITRI" if code == "110" else f"Route {code}"
    slug = "ticen-titri" if code == "110" else f"route-{code}"
    return RouteSnapshot(
        route=ParsedRoutePage(
            code=code,
            name=name,
            slug=slug,
            page_url=f"https://www.consorciofenix.com.br/horarios/{slug},{code}",
            map_url=f"https://www.consorciofenix.com.br/mapa/{code}",
            category="convencional",
            fare_region="Região Única",
            fare_policy=FarePolicy(
                region="Região Única",
                citizen_card_cents=620,
                vt_tourist_card_cents=720,
                cash_qrcode_pix_cents=cash_qrcode_pix_cents,
            ),
            last_changed=date(2026, 5, 2),
        ),
        source_hash=source_hash,
        map_hash=map_hash,
    )


def test_persist_snapshots_batches_metadata_lookups_across_routes(db_session: Session):
    select_statements: list[str] = []

    def record_selects(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            select_statements.append(statement)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", record_selects)
    try:
        persist_snapshots(
            db_session,
            "https://www.consorciofenix.com.br/horarios",
            [
                _snapshot(code="110", source_hash="source-110"),
                _snapshot(code="111", source_hash="source-111"),
                _snapshot(code="112", source_hash="source-112"),
            ],
        )
    finally:
        event.remove(engine, "before_cursor_execute", record_selects)

    assert len(select_statements) == 3
    assert db_session.query(RouteRecord).count() == 3
    assert db_session.query(FareVersionRecord).count() == 1
    assert db_session.query(RouteVersionRecord).count() == 3


def test_postgresql_reconciliation_statements_return_canonical_identities():
    route_id = UUID("00000000-0000-0000-0000-000000000001")
    fare_version_id = UUID("00000000-0000-0000-0000-000000000002")
    route_version_id = UUID("00000000-0000-0000-0000-000000000003")
    scrape_run_id = UUID("00000000-0000-0000-0000-000000000004")
    dialect = postgresql.dialect()

    route_sql = str(
        _postgresql_route_upsert(
            [
                {
                    "id": route_id,
                    "code": "110",
                    "name": "TICEN - TITRI",
                    "slug": "ticen-titri",
                    "category": "convencional",
                    "fare_region": "Região Única",
                    "last_changed": date(2026, 5, 2),
                    "is_current": True,
                }
            ]
        ).compile(dialect=dialect)
    )
    fare_sql = str(
        _postgresql_fare_version_upsert(
            [
                {
                    "id": fare_version_id,
                    "region": "Região Única",
                    "citizen_card_cents": 620,
                    "vt_tourist_card_cents": 720,
                    "cash_qrcode_pix_cents": 770,
                    "source_hash": "fare-hash",
                    "source_url": "https://example.test/110",
                    "is_current": True,
                }
            ]
        ).compile(dialect=dialect)
    )
    route_version_sql = str(
        _postgresql_route_version_insert(
            [
                {
                    "id": route_version_id,
                    "route_id": route_id,
                    "scrape_run_id": scrape_run_id,
                    "fare_version_id": fare_version_id,
                    "source_hash": "source-hash",
                    "map_hash": None,
                    "page_url": "https://example.test/110",
                    "map_url": None,
                    "snapshot": {},
                    "is_current": True,
                }
            ]
        ).compile(dialect=dialect)
    )

    assert "ON CONFLICT (code) DO UPDATE" in route_sql
    assert "RETURNING routes.code, routes.id" in route_sql
    assert "ON CONFLICT ON CONSTRAINT uq_fare_versions_region_source_hash DO UPDATE" in fare_sql
    assert "RETURNING fare_versions.region, fare_versions.source_hash, fare_versions.id" in fare_sql
    assert "ON CONFLICT ON CONSTRAINT uq_route_versions_route_source_map_hash DO NOTHING" in route_version_sql
    assert "RETURNING route_versions.route_id, route_versions.source_hash, route_versions.map_hash" in route_version_sql


def test_unchanged_batch_reuses_canonical_stored_ids_and_updates_route_metadata(db_session: Session):
    first_snapshot = _snapshot()
    persist_snapshots(db_session, "https://www.consorciofenix.com.br/horarios", [first_snapshot])
    stored_route = db_session.query(RouteRecord).one()
    stored_fare = db_session.query(FareVersionRecord).one()
    stored_version = db_session.query(RouteVersionRecord).one()

    unchanged_snapshot = _snapshot()
    unchanged_snapshot.route.name = "Updated route name"
    persist_snapshots(db_session, "https://www.consorciofenix.com.br/horarios", [unchanged_snapshot])

    route = db_session.query(RouteRecord).one()
    fare = db_session.query(FareVersionRecord).one()
    version = db_session.query(RouteVersionRecord).one()
    assert route.id == stored_route.id
    assert route.name == "Updated route name"
    assert fare.id == stored_fare.id
    assert version.id == stored_version.id
    assert version.fare_version_id == fare.id


def _snapshot_with_directions(source_hash: str = "source-a", map_hash: str | None = "map-a") -> RouteSnapshot:
    snapshot = _snapshot(source_hash=source_hash, map_hash=map_hash)
    snapshot.directions = [
        RouteDirection(name="Ida", coordinates=[(-48.548, -27.5969), (-48.547, -27.5969)]),
        RouteDirection(name="Volta", coordinates=[(-48.547, -27.5969), (-48.548, -27.5969)]),
    ]
    return snapshot


def test_uuid_pk_generates_uuid_values(db_session: Session):
    run = ScrapeRunRecord(source_url="https://www.consorciofenix.com.br/horarios")

    db_session.add(run)
    db_session.flush()

    assert isinstance(run.id, UUID)


def test_reuses_existing_route_version_when_source_and_map_hash_match(db_session: Session):
    persist_snapshots(db_session, "https://www.consorciofenix.com.br/horarios", [_snapshot()])
    first_id = db_session.query(RouteVersionRecord).one().id
    persist_snapshots(db_session, "https://www.consorciofenix.com.br/horarios", [_snapshot()])

    versions = db_session.query(RouteVersionRecord).all()

    assert len(versions) == 1
    assert versions[0].id == first_id
    assert versions[0].is_current is True


def test_creates_new_route_version_when_source_hash_changes(db_session: Session):
    persist_snapshots(db_session, "https://www.consorciofenix.com.br/horarios", [_snapshot(source_hash="source-a")])
    persist_snapshots(db_session, "https://www.consorciofenix.com.br/horarios", [_snapshot(source_hash="source-b")])

    versions = db_session.query(RouteVersionRecord).order_by(RouteVersionRecord.source_hash).all()

    assert len(versions) == 2
    assert versions[0].id != versions[1].id
    assert versions[0].is_current is False
    assert versions[1].is_current is True


def test_creates_new_route_version_when_map_hash_changes(db_session: Session):
    persist_snapshots(db_session, "https://www.consorciofenix.com.br/horarios", [_snapshot(map_hash="map-a")])
    persist_snapshots(db_session, "https://www.consorciofenix.com.br/horarios", [_snapshot(map_hash="map-b")])

    versions = db_session.query(RouteVersionRecord).order_by(RouteVersionRecord.map_hash).all()

    assert len(versions) == 2
    assert versions[0].id != versions[1].id
    assert versions[0].is_current is False
    assert versions[1].is_current is True


def test_persists_route_segments_for_new_route_versions(db_session: Session):
    snapshot = _snapshot_with_directions()

    persist_snapshots(db_session, "https://www.consorciofenix.com.br/horarios", [snapshot])

    version = db_session.query(RouteVersionRecord).one()
    route_directions = db_session.query(RouteDirectionRecord).order_by(RouteDirectionRecord.sequence).all()
    route_segments = db_session.query(RouteSegmentRecord).order_by(
        RouteSegmentRecord.route_direction_id,
        RouteSegmentRecord.sequence,
    ).all()

    assert len(route_segments) == 2
    assert {segment.route_version_id for segment in route_segments} == {version.id}
    assert {segment.route_direction_id for segment in route_segments} == {direction.id for direction in route_directions}
    assert [segment.sequence for segment in route_segments] == [1, 1]
    assert [segment.source_segment_sequence for segment in route_segments] == [1, 1]
    assert [segment.source_fraction_start for segment in route_segments] == [0.0, 0.0]
    assert [segment.source_fraction_end for segment in route_segments] == [1.0, 1.0]
    assert all(segment.geometry.startswith("SRID=4326;LINESTRING(") for segment in route_segments)
    assert all(segment.distance_meters > 0 for segment in route_segments)
    assert all(segment.cumulative_distance_meters == segment.distance_meters for segment in route_segments)
    assert all(0 <= segment.bearing_degrees < 360 for segment in route_segments)


def test_reused_route_version_does_not_duplicate_route_segments(db_session: Session):
    snapshot = _snapshot_with_directions(map_hash=None)

    persist_snapshots(db_session, "https://www.consorciofenix.com.br/horarios", [snapshot])
    persist_snapshots(db_session, "https://www.consorciofenix.com.br/horarios", [snapshot])

    assert db_session.query(RouteVersionRecord).count() == 1
    assert db_session.query(RouteDirectionRecord).count() == 2
    assert db_session.query(RouteSegmentRecord).count() == 2


def test_changed_source_hash_creates_route_version_with_own_route_segments(db_session: Session):
    persist_snapshots(db_session, "https://www.consorciofenix.com.br/horarios", [_snapshot_with_directions(source_hash="source-a")])
    persist_snapshots(db_session, "https://www.consorciofenix.com.br/horarios", [_snapshot_with_directions(source_hash="source-b")])

    versions = db_session.query(RouteVersionRecord).order_by(RouteVersionRecord.created_at).all()
    route_segments = db_session.query(RouteSegmentRecord).all()

    assert len(versions) == 2
    assert len(route_segments) == 4
    assert {segment.route_version_id for segment in route_segments} == {version.id for version in versions}


def test_changed_map_hash_creates_route_version_with_own_route_segments(db_session: Session):
    persist_snapshots(db_session, "https://www.consorciofenix.com.br/horarios", [_snapshot_with_directions(map_hash="map-a")])
    persist_snapshots(db_session, "https://www.consorciofenix.com.br/horarios", [_snapshot_with_directions(map_hash="map-b")])

    versions = db_session.query(RouteVersionRecord).order_by(RouteVersionRecord.created_at).all()
    route_segments = db_session.query(RouteSegmentRecord).all()

    assert len(versions) == 2
    assert len(route_segments) == 4
    assert {segment.route_version_id for segment in route_segments} == {version.id for version in versions}


def test_route_segments_schema_supports_nearby_route_discovery():
    table = RouteSegmentRecord.__table__
    geometry_type = table.c.geometry.type._variant_mapping["postgresql"]
    index_by_name = {index.name: index for index in table.indexes}

    assert set(table.c) >= {
        table.c.route_version_id,
        table.c.route_direction_id,
        table.c.sequence,
        table.c.source_segment_sequence,
        table.c.source_fraction_start,
        table.c.source_fraction_end,
        table.c.geometry,
        table.c.bearing_degrees,
        table.c.distance_meters,
        table.c.cumulative_distance_meters,
    }
    assert geometry_type.geometry_type == "LINESTRING"
    assert geometry_type.srid == 4326
    assert index_by_name["ix_route_segments_geometry"].dialect_options["postgresql"]["using"] == "gist"
    assert [column.name for column in index_by_name["ix_route_segments_geometry"].columns] == ["geometry"]
    assert [column.name for column in index_by_name["ix_route_segments_route_version_direction_sequence"].columns] == [
        "route_version_id",
        "route_direction_id",
        "sequence",
    ]


def test_persists_route_metadata_and_links_route_version_to_fare_version(db_session: Session):
    persist_snapshots(db_session, "https://www.consorciofenix.com.br/horarios", [_snapshot()])

    route = db_session.query(RouteRecord).one()
    fare_version = db_session.query(FareVersionRecord).one()
    version = db_session.query(RouteVersionRecord).one()

    assert route.category == "convencional"
    assert route.fare_region == "Região Única"
    assert route.last_changed == date(2026, 5, 2)
    assert fare_version.region == "Região Única"
    assert fare_version.citizen_card_cents == 620
    assert fare_version.vt_tourist_card_cents == 720
    assert fare_version.cash_qrcode_pix_cents == 770
    assert len(fare_version.source_hash) == 64
    assert fare_version.source_url == "https://www.consorciofenix.com.br/horarios/ticen-titri,110"
    assert fare_version.is_current is True
    assert version.fare_version_id == fare_version.id


def test_reuses_existing_fare_version_for_same_policy_when_route_source_hash_changes(db_session: Session):
    persist_snapshots(db_session, "https://www.consorciofenix.com.br/horarios", [_snapshot(source_hash="source-a")])
    persist_snapshots(db_session, "https://www.consorciofenix.com.br/horarios", [_snapshot(source_hash="source-b")])

    fare_versions = db_session.query(FareVersionRecord).all()

    assert len(fare_versions) == 1


def test_marks_previous_fare_version_non_current_when_fare_policy_changes(db_session: Session):
    persist_snapshots(
        db_session,
        "https://www.consorciofenix.com.br/horarios",
        [_snapshot(source_hash="source-a")],
    )
    persist_snapshots(
        db_session,
        "https://www.consorciofenix.com.br/horarios",
        [_snapshot(source_hash="source-b", cash_qrcode_pix_cents=790)],
    )

    fare_versions = db_session.query(FareVersionRecord).order_by(FareVersionRecord.cash_qrcode_pix_cents).all()
    route_versions = db_session.query(RouteVersionRecord).order_by(RouteVersionRecord.source_hash).all()

    assert route_versions[0].fare_version_id == fare_versions[0].id
    assert route_versions[1].fare_version_id == fare_versions[1].id
    assert {fare.cash_qrcode_pix_cents for fare in fare_versions} == {770, 790}
    assert [fare.is_current for fare in fare_versions] == [False, True]


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
            fare_region="Região Única",
            fare_policy=FarePolicy(
                region="Região Única",
                citizen_card_cents=620,
                vt_tourist_card_cents=720,
                cash_qrcode_pix_cents=770,
            ),
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

    persist_snapshots(db_session, "https://www.consorciofenix.com.br/horarios", [snapshot])

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
