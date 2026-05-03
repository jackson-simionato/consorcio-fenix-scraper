"""add fare version history

Revision ID: 20260503_0002
Revises: 20260502_0001
Create Date: 2026-05-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260503_0002"
down_revision = "20260502_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fare_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("region", sa.Text(), nullable=False),
        sa.Column("citizen_card_cents", sa.Integer(), nullable=True),
        sa.Column("vt_tourist_card_cents", sa.Integer(), nullable=True),
        sa.Column("cash_qrcode_pix_cents", sa.Integer(), nullable=True),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("is_current", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("region", "source_hash", name="uq_fare_versions_region_source_hash"),
    )
    op.create_index(op.f("ix_fare_versions_region"), "fare_versions", ["region"], unique=False)
    op.create_index(op.f("ix_fare_versions_is_current"), "fare_versions", ["is_current"], unique=False)
    op.create_index("ix_fare_versions_region_is_current", "fare_versions", ["region", "is_current"], unique=False)

    op.add_column("routes", sa.Column("fare_region", sa.Text(), nullable=True))
    op.drop_column("routes", "fare_cents")

    op.add_column("route_versions", sa.Column("fare_version_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index(op.f("ix_route_versions_fare_version_id"), "route_versions", ["fare_version_id"], unique=False)
    op.create_foreign_key(
        "fk_route_versions_fare_version_id_fare_versions",
        "route_versions",
        "fare_versions",
        ["fare_version_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_route_versions_fare_version_id_fare_versions", "route_versions", type_="foreignkey")
    op.drop_index(op.f("ix_route_versions_fare_version_id"), table_name="route_versions")
    op.drop_column("route_versions", "fare_version_id")

    op.add_column("routes", sa.Column("fare_cents", sa.Integer(), nullable=True))
    op.drop_column("routes", "fare_region")

    op.drop_index("ix_fare_versions_region_is_current", table_name="fare_versions")
    op.drop_index(op.f("ix_fare_versions_is_current"), table_name="fare_versions")
    op.drop_index(op.f("ix_fare_versions_region"), table_name="fare_versions")
    op.drop_table("fare_versions")
