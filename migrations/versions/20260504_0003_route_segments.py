"""add materialized route segments

Revision ID: 20260504_0003
Revises: 20260503_0002
Create Date: 2026-05-04
"""

from alembic import op
import geoalchemy2
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260504_0003"
down_revision = "20260503_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "route_segments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_direction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("source_segment_sequence", sa.Integer(), nullable=False),
        sa.Column("source_fraction_start", sa.Float(), nullable=False),
        sa.Column("source_fraction_end", sa.Float(), nullable=False),
        sa.Column("geometry", geoalchemy2.types.Geometry(geometry_type="LINESTRING", srid=4326), nullable=False),
        sa.Column("bearing_degrees", sa.Float(), nullable=False),
        sa.Column("distance_meters", sa.Float(), nullable=False),
        sa.Column("cumulative_distance_meters", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["route_direction_id"], ["route_directions.id"]),
        sa.ForeignKeyConstraint(["route_version_id"], ["route_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "route_version_id",
            "route_direction_id",
            "sequence",
            name="uq_route_segments_route_version_direction_sequence",
        ),
    )
    op.create_index(op.f("ix_route_segments_route_version_id"), "route_segments", ["route_version_id"], unique=False)
    op.create_index(op.f("ix_route_segments_route_direction_id"), "route_segments", ["route_direction_id"], unique=False)
    op.create_index(
        "ix_route_segments_route_version_direction_sequence",
        "route_segments",
        ["route_version_id", "route_direction_id", "sequence"],
        unique=False,
    )
    op.create_index("ix_route_segments_geometry", "route_segments", ["geometry"], unique=False, postgresql_using="gist")


def downgrade() -> None:
    op.drop_index("ix_route_segments_geometry", table_name="route_segments", postgresql_using="gist")
    op.drop_index("ix_route_segments_route_version_direction_sequence", table_name="route_segments")
    op.drop_index(op.f("ix_route_segments_route_direction_id"), table_name="route_segments")
    op.drop_index(op.f("ix_route_segments_route_version_id"), table_name="route_segments")
    op.drop_table("route_segments")
