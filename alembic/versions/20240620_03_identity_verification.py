"""Introduce persona identity table and submission metadata."""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20240620_03"
down_revision = "20240601_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "persona_identities",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("persona_id", sa.Integer(), sa.ForeignKey("personas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_username", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("added_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("added_in_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("removed_in_chat_id", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "telegram_user_id IS NOT NULL OR telegram_username IS NOT NULL OR display_name IS NOT NULL",
            name="ck_persona_identity_has_any_identifier",
        ),
    )
    op.create_index(
        "ix_persona_identity_user_id",
        "persona_identities",
        ["telegram_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_persona_identity_username",
        "persona_identities",
        ["telegram_username"],
        unique=False,
    )

    op.add_column(
        "submissions",
        sa.Column("submitted_by_username", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "submissions",
        sa.Column("submitted_by_name", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("submissions", "submitted_by_name")
    op.drop_column("submissions", "submitted_by_username")

    op.drop_index("ix_persona_identity_username", table_name="persona_identities")
    op.drop_index("ix_persona_identity_user_id", table_name="persona_identities")
    op.drop_table("persona_identities")
