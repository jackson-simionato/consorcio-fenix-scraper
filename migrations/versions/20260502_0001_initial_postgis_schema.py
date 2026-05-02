"""initial postgis schema

Revision ID: 20260502_0001
Revises:
Create Date: 2026-05-02
"""

from alembic import op
import geoalchemy2
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260502_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.create_table(
        "scrape_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "routes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("fare_cents", sa.Integer(), nullable=True),
        sa.Column("last_changed", sa.Date(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index(op.f("ix_routes_code"), "routes", ["code"], unique=False)
    op.create_table(
        "route_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scrape_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("map_hash", sa.String(length=64), nullable=True),
        sa.Column("page_url", sa.Text(), nullable=False),
        sa.Column("map_url", sa.Text(), nullable=True),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["route_id"], ["routes.id"]),
        sa.ForeignKeyConstraint(["scrape_run_id"], ["scrape_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "route_id",
            "source_hash",
            "map_hash",
            name="uq_route_versions_route_source_map_hash",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(op.f("ix_route_versions_map_hash"), "route_versions", ["map_hash"], unique=False)
    op.create_index(op.f("ix_route_versions_route_id"), "route_versions", ["route_id"], unique=False)
    op.create_index(op.f("ix_route_versions_scrape_run_id"), "route_versions", ["scrape_run_id"], unique=False)
    op.create_index(op.f("ix_route_versions_source_hash"), "route_versions", ["source_hash"], unique=False)
    op.create_table(
        "route_directions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("geometry", geoalchemy2.types.Geometry(geometry_type="LINESTRING", srid=4326), nullable=False),
        sa.ForeignKeyConstraint(["route_version_id"], ["route_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_route_directions_route_version_id"), "route_directions", ["route_version_id"], unique=False)
    op.create_table(
        "service_directions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_direction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("departure_label", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=True),
        sa.Column("direction_kind", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("notes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["route_direction_id"], ["route_directions.id"]),
        sa.ForeignKeyConstraint(["route_version_id"], ["route_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("route_version_id", "departure_label", name="uq_service_directions_route_version_departure_label"),
    )
    op.create_index(op.f("ix_service_directions_route_direction_id"), "service_directions", ["route_direction_id"], unique=False)
    op.create_index(op.f("ix_service_directions_route_version_id"), "service_directions", ["route_version_id"], unique=False)
    op.create_table(
        "schedule_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("service_direction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("day_type", sa.Text(), nullable=False),
        sa.Column("departure_label", sa.Text(), nullable=False),
        sa.Column("time", sa.String(length=5), nullable=False),
        sa.Column("flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["service_direction_id"], ["service_directions.id"]),
        sa.ForeignKeyConstraint(["route_version_id"], ["route_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_schedule_entries_service_direction_id"), "schedule_entries", ["service_direction_id"], unique=False)
    op.create_index(op.f("ix_schedule_entries_route_version_id"), "schedule_entries", ["route_version_id"], unique=False)
    op.create_table(
        "itinerary_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["route_version_id"], ["route_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_itinerary_steps_route_version_id"), "itinerary_steps", ["route_version_id"], unique=False)
    op.create_table(
        "stops",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("geometry", geoalchemy2.types.Geometry(geometry_type="POINT", srid=4326), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_stops_external_id"), "stops", ["external_id"], unique=False)
    op.create_table(
        "raw_pages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scrape_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["scrape_run_id"], ["scrape_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scrape_run_id", "url", name="uq_raw_page_run_url"),
    )
    op.create_index(op.f("ix_raw_pages_scrape_run_id"), "raw_pages", ["scrape_run_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_raw_pages_scrape_run_id"), table_name="raw_pages")
    op.drop_table("raw_pages")
    op.drop_index(op.f("ix_stops_external_id"), table_name="stops")
    op.drop_table("stops")
    op.drop_index(op.f("ix_itinerary_steps_route_version_id"), table_name="itinerary_steps")
    op.drop_table("itinerary_steps")
    op.drop_index(op.f("ix_schedule_entries_service_direction_id"), table_name="schedule_entries")
    op.drop_index(op.f("ix_schedule_entries_route_version_id"), table_name="schedule_entries")
    op.drop_table("schedule_entries")
    op.drop_index(op.f("ix_service_directions_route_version_id"), table_name="service_directions")
    op.drop_index(op.f("ix_service_directions_route_direction_id"), table_name="service_directions")
    op.drop_table("service_directions")
    op.drop_index(op.f("ix_route_directions_route_version_id"), table_name="route_directions")
    op.drop_table("route_directions")
    op.drop_index(op.f("ix_route_versions_source_hash"), table_name="route_versions")
    op.drop_index(op.f("ix_route_versions_scrape_run_id"), table_name="route_versions")
    op.drop_index(op.f("ix_route_versions_route_id"), table_name="route_versions")
    op.drop_index(op.f("ix_route_versions_map_hash"), table_name="route_versions")
    op.drop_table("route_versions")
    op.drop_index(op.f("ix_routes_code"), table_name="routes")
    op.drop_table("routes")
    op.drop_table("scrape_runs")
