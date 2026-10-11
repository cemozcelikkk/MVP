"""service point verification: moderatör onayı + topluluk teyidi

Revision ID: a4c8e2f6b1d9
Revises: f1b7d3a9c2e5
Create Date: 2026-10-10 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a4c8e2f6b1d9"
down_revision: Union[str, None] = "f1b7d3a9c2e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("service_points", sa.Column("is_verified", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("service_points", sa.Column("confirmation_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("service_points", sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "service_point_confirmations",
        sa.Column("service_point_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["service_point_id"], ["service_points.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_service_point_confirmations_user_id", "service_point_confirmations", ["user_id"])
    op.create_index(
        "uq_service_point_confirmations_user", "service_point_confirmations", ["service_point_id", "user_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_service_point_confirmations_user", table_name="service_point_confirmations")
    op.drop_index("ix_service_point_confirmations_user_id", table_name="service_point_confirmations")
    op.drop_table("service_point_confirmations")
    op.drop_column("service_points", "last_confirmed_at")
    op.drop_column("service_points", "confirmation_count")
    op.drop_column("service_points", "is_verified")
