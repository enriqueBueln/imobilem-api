"""create authorization_events

Durable, append-only audit log of every authorize/reject decision. Documents are
never persisted, but the decisions about them are — see
app/models/authorization_event.py.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "authorization_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("user_name", sa.String(length=120), nullable=False),
        sa.Column("user_email", sa.String(length=255), nullable=False),
        sa.Column("sap_user_id", sa.String(length=60), nullable=True),
        sa.Column("document_type", sa.String(length=40), nullable=False),
        sa.Column("document_id", sa.String(length=60), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("resulting_status", sa.String(length=40), nullable=False),
        sa.Column("comment", sa.String(length=500), nullable=True),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_authorization_events_created_at", "authorization_events", ["created_at"]
    )
    op.create_index("ix_authorization_events_user_id", "authorization_events", ["user_id"])
    op.create_index(
        "ix_authorization_events_document",
        "authorization_events",
        ["document_type", "document_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_authorization_events_document", table_name="authorization_events")
    op.drop_index("ix_authorization_events_user_id", table_name="authorization_events")
    op.drop_index("ix_authorization_events_created_at", table_name="authorization_events")
    op.drop_table("authorization_events")
