"""Usunięcie tabeli admin_chats i użycie surowych identyfikatorów czatu."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20240601_02"
down_revision = "20240601_01"
branch_labels = None
depends_on = None


_TABLE_COLUMN_MAP = [
    ("persona_aliases", "added_in_chat_id"),
    ("persona_aliases", "removed_in_chat_id"),
    ("submissions", "decided_in_chat_id"),
    ("moderation_actions", "admin_chat_id"),
    ("bot_chat_subscriptions", "granted_in_chat_id"),
]


def upgrade() -> None:
    for table, column in _TABLE_COLUMN_MAP:
        tmp_column = f"{column}_raw"
        op.add_column(table, sa.Column(tmp_column, sa.BigInteger(), nullable=True))
        op.execute(
            sa.text(
                f"""
                UPDATE {table} AS t
                SET {tmp_column} = ac.chat_id
                FROM admin_chats AS ac
                WHERE t.{column} = ac.id
                """
            )
        )
        constraint_name = f"{table}_{column}_fkey"
        op.drop_constraint(constraint_name, table, type_="foreignkey")
        op.drop_column(table, column)
        op.alter_column(table, tmp_column, new_column_name=column, existing_type=sa.BigInteger())

    op.drop_index("ix_admin_chats_chat_id", table_name="admin_chats")
    op.drop_table("admin_chats")


def downgrade() -> None:
    op.create_table(
        "admin_chats",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("chat_id", name="uq_admin_chats_chat_id"),
    )
    op.create_index("ix_admin_chats_chat_id", "admin_chats", ["chat_id"], unique=False)

    op.execute(
        sa.text(
            """
            INSERT INTO admin_chats (chat_id, title, created_at, is_active)
            SELECT DISTINCT chat_id, NULL, NOW(), TRUE
            FROM (
                SELECT added_in_chat_id AS chat_id FROM persona_aliases
                UNION SELECT removed_in_chat_id FROM persona_aliases
                UNION SELECT decided_in_chat_id FROM submissions
                UNION SELECT admin_chat_id FROM moderation_actions
                UNION SELECT granted_in_chat_id FROM bot_chat_subscriptions
            ) AS chats
            WHERE chat_id IS NOT NULL
            """
        )
    )

    for table, column in _TABLE_COLUMN_MAP:
        tmp_column = f"{column}_fk"
        op.add_column(table, sa.Column(tmp_column, sa.Integer(), nullable=True))
        op.execute(
            sa.text(
                f"""
                UPDATE {table} AS t
                SET {tmp_column} = ac.id
                FROM admin_chats AS ac
                WHERE t.{column} = ac.chat_id
                """
            )
        )
        op.drop_column(table, column)
        op.alter_column(table, tmp_column, new_column_name=column, existing_type=sa.Integer())
        op.create_foreign_key(
            f"{table}_{column}_fkey",
            table,
            "admin_chats",
            [column],
            ["id"],
            ondelete="SET NULL",
        )
