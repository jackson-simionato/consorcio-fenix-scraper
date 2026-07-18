import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from consorcio_fenix_scraper.db import (
    Base,
    RouteDirectionRecord,
    RouteRecord,
    RouteSegmentRecord,
    RouteVersionRecord,
    ScheduleEntryRecord,
    ScrapeRunRecord,
    ServiceDirectionRecord,
    ItineraryStepRecord,
    make_session_factory,
    persist_snapshots,
)
from consorcio_fenix_scraper.domain import ScrapeStatus


POSTGRES_TEST_DATABASE_URL = os.environ.get("POSTGRES_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    POSTGRES_TEST_DATABASE_URL is None,
    reason="POSTGRES_TEST_DATABASE_URL is required for PostgreSQL persistence verification",
)


@pytest.fixture
def postgres_session_factory() -> Iterator[sessionmaker[Session]]:
    assert POSTGRES_TEST_DATABASE_URL is not None
    database_name = make_url(POSTGRES_TEST_DATABASE_URL).database or ""
    if not database_name.endswith(("_test", "_verification")):
        pytest.fail("POSTGRES_TEST_DATABASE_URL must name a database ending in _test or _verification")

    alembic_config = Config("alembic.ini")
    alembic_config.set_main_option("sqlalchemy.url", POSTGRES_TEST_DATABASE_URL)
    command.upgrade(alembic_config, "head")

    factory = make_session_factory(POSTGRES_TEST_DATABASE_URL)
    _clear_database(factory)
    try:
        yield factory
    finally:
        _clear_database(factory)


def _clear_database(factory: sessionmaker[Session]) -> None:
    with factory.begin() as session:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())


def test_postgres_cold_unchanged_and_changed_persistence_preserves_schema_and_normalized_rows(
    postgres_session_factory: sessionmaker[Session],
    complete_snapshot_factory,
):
    source_url = "https://example.test/horarios"
    initial = complete_snapshot_factory(map_hash="map-a")

    persist_snapshots(postgres_session_factory, source_url, [initial])
    persist_snapshots(postgres_session_factory, source_url, [initial])
    persist_snapshots(postgres_session_factory, source_url, [complete_snapshot_factory(map_hash="map-b")])

    with postgres_session_factory() as session:
        normalized_versions = list(
            session.execute(
                select(
                    RouteRecord.code,
                    RouteVersionRecord.source_hash,
                    RouteVersionRecord.map_hash,
                    RouteVersionRecord.is_current,
                )
                .join(RouteVersionRecord, RouteVersionRecord.route_id == RouteRecord.id)
                .order_by(RouteVersionRecord.map_hash)
            )
        )
        assert normalized_versions == [
            ("110", "source-a", "map-a", False),
            ("110", "source-a", "map-b", True),
        ]
        assert session.query(RouteDirectionRecord).count() == 2
        assert session.query(RouteSegmentRecord).count() == 2
        assert session.query(ServiceDirectionRecord).count() == 2
        assert session.query(ScheduleEntryRecord).count() == 2
        assert session.query(ItineraryStepRecord).count() == 2
        assert [run.status for run in session.query(ScrapeRunRecord).order_by(ScrapeRunRecord.started_at)] == [
            ScrapeStatus.SUCCESS.value,
            ScrapeStatus.SUCCESS.value,
            ScrapeStatus.SUCCESS.value,
        ]

        constraints = {
            (table_name, constraint_name): (constraint_type, definition)
            for table_name, constraint_name, constraint_type, definition in session.execute(
                text(
                    "SELECT relation.relname, constraint.conname, constraint.contype, "
                    "pg_get_constraintdef(constraint.oid) "
                    "FROM pg_constraint AS constraint "
                    "JOIN pg_class AS relation ON relation.oid = constraint.conrelid "
                    "WHERE constraint.connamespace = current_schema()::regnamespace"
                )
            )
        }
        indexes = dict(
            session.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE schemaname = current_schema()"
                )
            )
        )

    expected_unique_constraints = {
        ("routes", "routes_code_key"): "UNIQUE (code)",
        ("fare_versions", "uq_fare_versions_region_source_hash"): "UNIQUE (region, source_hash)",
        (
            "route_versions",
            "uq_route_versions_route_source_map_hash",
        ): "UNIQUE NULLS NOT DISTINCT (route_id, source_hash, map_hash)",
        (
            "service_directions",
            "uq_service_directions_route_version_departure_label",
        ): "UNIQUE (route_version_id, departure_label)",
        (
            "route_segments",
            "uq_route_segments_route_version_direction_sequence",
        ): "UNIQUE (route_version_id, route_direction_id, sequence)",
        ("raw_pages", "uq_raw_page_run_url"): "UNIQUE (scrape_run_id, url)",
    }
    for key, definition in expected_unique_constraints.items():
        assert constraints[key] == ("u", definition)

    expected_primary_key_tables = set(Base.metadata.tables) | {"alembic_version"}
    actual_primary_key_tables = {table for (table, _), (kind, _) in constraints.items() if kind == "p"}
    assert actual_primary_key_tables == expected_primary_key_tables

    expected_foreign_keys = {
        ("route_versions", "route_id", "routes(id)"),
        ("route_versions", "scrape_run_id", "scrape_runs(id)"),
        ("route_versions", "fare_version_id", "fare_versions(id)"),
        ("route_directions", "route_version_id", "route_versions(id)"),
        ("route_segments", "route_version_id", "route_versions(id)"),
        ("route_segments", "route_direction_id", "route_directions(id)"),
        ("service_directions", "route_version_id", "route_versions(id)"),
        ("service_directions", "route_direction_id", "route_directions(id)"),
        ("schedule_entries", "route_version_id", "route_versions(id)"),
        ("schedule_entries", "service_direction_id", "service_directions(id)"),
        ("itinerary_steps", "route_version_id", "route_versions(id)"),
        ("raw_pages", "scrape_run_id", "scrape_runs(id)"),
    }
    actual_foreign_keys = {
        (table, definition.split("(", 1)[1].split(")", 1)[0], definition.rsplit("REFERENCES ", 1)[1])
        for (table, _), (kind, definition) in constraints.items()
        if kind == "f"
    }
    assert actual_foreign_keys == expected_foreign_keys

    expected_indexes = {
        "ix_routes_code": "USING btree (code)",
        "ix_fare_versions_region": "USING btree (region)",
        "ix_fare_versions_is_current": "USING btree (is_current)",
        "ix_fare_versions_region_is_current": "USING btree (region, is_current)",
        "ix_route_versions_map_hash": "USING btree (map_hash)",
        "ix_route_versions_route_id": "USING btree (route_id)",
        "ix_route_versions_scrape_run_id": "USING btree (scrape_run_id)",
        "ix_route_versions_source_hash": "USING btree (source_hash)",
        "ix_route_versions_fare_version_id": "USING btree (fare_version_id)",
        "ix_route_directions_route_version_id": "USING btree (route_version_id)",
        "ix_route_segments_route_version_id": "USING btree (route_version_id)",
        "ix_route_segments_route_direction_id": "USING btree (route_direction_id)",
        "ix_route_segments_route_version_direction_sequence": (
            "USING btree (route_version_id, route_direction_id, sequence)"
        ),
        "ix_route_segments_geometry": "USING gist (geometry)",
        "ix_service_directions_route_direction_id": "USING btree (route_direction_id)",
        "ix_service_directions_route_version_id": "USING btree (route_version_id)",
        "ix_schedule_entries_service_direction_id": "USING btree (service_direction_id)",
        "ix_schedule_entries_route_version_id": "USING btree (route_version_id)",
        "ix_itinerary_steps_route_version_id": "USING btree (route_version_id)",
        "ix_stops_external_id": "USING btree (external_id)",
        "ix_raw_pages_scrape_run_id": "USING btree (scrape_run_id)",
    }
    for index_name, definition_fragment in expected_indexes.items():
        assert definition_fragment in indexes[index_name]


def test_route_direction_kind_migration_preserves_existing_rows(
    postgres_session_factory: sessionmaker[Session],
    complete_snapshot_factory,
):
    assert POSTGRES_TEST_DATABASE_URL is not None
    persist_snapshots(
        postgres_session_factory,
        "https://example.test/horarios",
        [complete_snapshot_factory()],
    )
    with postgres_session_factory() as session:
        existing = session.execute(
            text("SELECT id, name FROM route_directions")
        ).one()

    alembic_config = Config("alembic.ini")
    alembic_config.set_main_option("sqlalchemy.url", POSTGRES_TEST_DATABASE_URL)
    command.downgrade(alembic_config, "20260504_0003")
    try:
        with postgres_session_factory() as session:
            after_downgrade = session.execute(
                text("SELECT id, name FROM route_directions")
            ).one()
            column_count = session.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema = current_schema() "
                    "AND table_name = 'route_directions' "
                    "AND column_name = 'direction_kind'"
                )
            )
        assert after_downgrade == existing
        assert column_count == 0
    finally:
        command.upgrade(alembic_config, "head")

    with postgres_session_factory() as session:
        after_upgrade = session.execute(
            text("SELECT id, name, direction_kind FROM route_directions")
        ).one()
    assert after_upgrade[:2] == existing
    assert after_upgrade.direction_kind is None
