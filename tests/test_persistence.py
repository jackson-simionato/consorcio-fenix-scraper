from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from consorcio_fenix_scraper.db import Base, RouteRecord, RouteVersionRecord, ScrapeRunRecord, _linestring_wkt, _persist_snapshot
from consorcio_fenix_scraper.domain import ParsedRoutePage, RouteDirection, RouteSnapshot


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
        tables=[ScrapeRunRecord.__table__, RouteRecord.__table__, RouteVersionRecord.__table__],
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
