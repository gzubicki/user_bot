"""Początkowa struktura bazy danych."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic.
revision = "20240521_01"
down_revision = None
branch_labels = None
depends_on = None


media_type_enum = postgresql.ENUM(
    "text", "image", "audio", name="mediatype", create_type=False
)
moderation_status_enum = postgresql.ENUM(
    "pending", "approved", "rejected", name="moderationstatus", create_type=False
)
subscription_plan_enum = postgresql.ENUM(
    "monthly", "yearly", "free", name="subscriptionplan", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    media_type_enum.create(bind, checkfirst=True)
    moderation_status_enum.create(bind, checkfirst=True)
    subscription_plan_enum.create(bind, checkfirst=True)

    op.create_table(
        "personas",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("name", name="uq_personas_name"),
    )

    op.create_table(
        "admin_chats",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("chat_id", name="uq_admin_chats_chat_id"),
    )
    op.create_index(
        "ix_admin_chats_chat_id", "admin_chats", ["chat_id"], unique=False
    )

    op.create_table(
        "bots",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("persona_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["persona_id"], ["personas.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("token_hash", name="uq_bots_token_hash"),
    )

    op.create_index(
        "ix_bots_token_hash", "bots", ["token_hash"], unique=False
    )

    op.create_table(
        "persona_aliases",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("persona_id", sa.Integer(), nullable=False),
        sa.Column("alias", sa.String(length=255), nullable=False),
        sa.Column("added_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("added_in_chat_id", sa.Integer(), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("removed_in_chat_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["persona_id"], ["personas.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["added_in_chat_id"], ["admin_chats.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["removed_in_chat_id"], ["admin_chats.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("persona_id", "alias", name="uq_alias_per_persona"),
    )
    op.create_index("ix_alias_lookup", "persona_aliases", ["alias"], unique=False)

    op.create_table(
        "submissions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("persona_id", sa.Integer(), nullable=False),
        sa.Column("submitted_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("submitted_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("media_type", media_type_enum, nullable=False),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column("file_id", sa.String(length=255), nullable=True),
        sa.Column("file_hash", sa.LargeBinary(), nullable=True),
        sa.Column("status", moderation_status_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("decided_in_chat_id", sa.Integer(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["persona_id"], ["personas.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["decided_in_chat_id"], ["admin_chats.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_submission_status", "submissions", ["status"], unique=False
    )
    op.create_index(
        "ix_submission_persona", "submissions", ["persona_id"], unique=False
    )

    op.create_table(
        "quotes",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("persona_id", sa.Integer(), nullable=False),
        sa.Column("media_type", media_type_enum, nullable=False),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column("file_id", sa.String(length=255), nullable=True),
        sa.Column("file_hash", sa.LargeBinary(), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_submission_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["persona_id"], ["personas.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_submission_id"], ["submissions.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_quote_persona", "quotes", ["persona_id"], unique=False)
    op.create_index("ix_quote_language", "quotes", ["language"], unique=False)

    op.create_table(
        "moderation_actions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("submission_id", sa.Integer(), nullable=False),
        sa.Column("performed_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("admin_chat_id", sa.Integer(), nullable=True),
        sa.Column("action", moderation_status_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["submission_id"], ["submissions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["admin_chat_id"], ["admin_chats.id"], ondelete="SET NULL"
        ),
    )

    op.create_table(
        "bot_chat_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("bot_id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("plan", subscription_plan_enum, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("granted_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("granted_in_chat_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["granted_in_chat_id"], ["admin_chats.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("bot_id", "chat_id", name="uq_bot_chat"),
    )
    op.create_index(
        "ix_bot_subscription_status",
        "bot_chat_subscriptions",
        ["is_active"],
        unique=False,
    )

    op.create_table(
        "subscription_ledger",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("bot_id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("plan", subscription_plan_enum, nullable=False),
        sa.Column("amount_stars", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.String(length=255), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_subscription_ledger_bot",
        "subscription_ledger",
        ["bot_id"],
        unique=False,
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("actor_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "length(event_type) > 0", name="ck_event_type_not_empty"
        ),
    )
    op.create_index(
        "ix_audit_event_type", "audit_logs", ["event_type"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_audit_event_type", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("ix_subscription_ledger_bot", table_name="subscription_ledger")
    op.drop_table("subscription_ledger")

    op.drop_index(
        "ix_bot_subscription_status", table_name="bot_chat_subscriptions"
    )
    op.drop_table("bot_chat_subscriptions")

    op.drop_table("moderation_actions")

    op.drop_index("ix_quote_language", table_name="quotes")
    op.drop_index("ix_quote_persona", table_name="quotes")
    op.drop_table("quotes")

    op.drop_index("ix_submission_persona", table_name="submissions")
    op.drop_index("ix_submission_status", table_name="submissions")
    op.drop_table("submissions")

    op.drop_index("ix_alias_lookup", table_name="persona_aliases")
    op.drop_table("persona_aliases")

    op.drop_index("ix_bots_token_hash", table_name="bots")
    op.drop_table("bots")

    op.drop_index("ix_admin_chats_chat_id", table_name="admin_chats")
    op.drop_table("admin_chats")

    op.drop_table("personas")

    bind = op.get_bind()
    subscription_plan_enum.drop(bind, checkfirst=True)
    moderation_status_enum.drop(bind, checkfirst=True)
    media_type_enum.drop(bind, checkfirst=True)
