"""Authorization event log — the durable audit trail of every authorize/reject.

Documents themselves are NEVER persisted (they live in SAP, today an in-memory
stand-in), but our DECISIONS about them must outlive a process restart and a user
rename. Each row is one immutable decision: who acted, on which document, what they
did, the comment, the resulting chain state, and the amount AT THE MOMENT of the
decision.

Two deliberate choices:
- The actor identity is DENORMALIZED (name/email/sap_user_id snapshot) so the record
  stays truthful even if the user is later renamed; the FK is RESTRICT so an actor
  with history cannot be deleted out from under the audit.
- `document_type`, `action` and `resulting_status` are plain strings (not native DB
  enums) so new document types or statuses never require a migration — same reasoning
  that moved roles off the enum column in migration 0002.

Append-only: nothing here is ever updated or deleted by application code.
"""

import datetime as dt
import enum
import uuid
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuthorizationAction(enum.StrEnum):
    authorize = "authorize"
    reject = "reject"


class AuthorizationEvent(Base):
    __tablename__ = "authorization_events"
    __table_args__ = (
        # The full history of one document, in one indexed lookup.
        Index("ix_authorization_events_document", "document_type", "document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    # Actor: FK for joins + a denormalized snapshot that survives renames/deletion.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    user_name: Mapped[str] = mapped_column(String(120), nullable=False)
    user_email: Mapped[str] = mapped_column(String(255), nullable=False)
    sap_user_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # Target document — never persisted itself, only its identity is recorded.
    document_type: Mapped[str] = mapped_column(String(40), nullable=False)
    document_id: Mapped[str] = mapped_column(String(60), nullable=False)
    # The decision.
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    resulting_status: Mapped[str] = mapped_column(String(40), nullable=False)
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Snapshot of the document's authoritative amount at decision time — the figure in
    # SAP may change later, but the audit must reflect what was actually approved.
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
