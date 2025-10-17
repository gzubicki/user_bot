from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20240702_04"
down_revision = "20240620_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "submissions",
        sa.Column("quoted_user_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "submissions",
        sa.Column("quoted_username", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "submissions",
        sa.Column("quoted_name", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("submissions", "quoted_name")
    op.drop_column("submissions", "quoted_username")
    op.drop_column("submissions", "quoted_user_id")
