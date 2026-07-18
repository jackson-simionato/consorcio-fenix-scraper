"""add route direction kind

Revision ID: 20260718_0004
Revises: 20260504_0003
Create Date: 2026-07-18
"""

from alembic import op
import sqlalchemy as sa


revision = "20260718_0004"
down_revision = "20260504_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("route_directions", sa.Column("direction_kind", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("route_directions", "direction_kind")
