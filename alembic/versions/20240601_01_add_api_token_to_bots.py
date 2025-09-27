"""Dodanie kolumny api_token do tabeli bots."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20240601_01"
down_revision = "20240521_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bots", sa.Column("api_token", sa.String(length=255), nullable=True))
    op.create_unique_constraint("uq_bots_api_token", "bots", ["api_token"])
    op.create_index("ix_bots_api_token", "bots", ["api_token"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_bots_api_token", table_name="bots")
    op.drop_constraint("uq_bots_api_token", "bots", type_="unique")
    op.drop_column("bots", "api_token")
