"""Refresh token model — lives in OUR database (Postgres).

Access tokens are stateless JWTs (short-lived, not stored). Refresh tokens are the
opposite: opaque, long-lived, and tracked here so they can be ROTATED on each use and
REVOKED on logout. We store only a SHA-256 hash of the raw token, never the token
itself — same principle as password hashes: a database leak must not yield usable
credentials. A fast hash (not Argon2) is correct here because the raw token is already
high-entropy random, so brute-forcing the hash is infeasible without the slow KDF.

Rotation + a `revoked_at` marker also gives us theft detection: if an already-rotated
(revoked) token is presented again, every token for that user is revoked (see
app/services/auth.py).
"""

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # SHA-256 hex digest of the raw token (64 chars). The raw token is returned to the
    # client once and never persisted.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Set when the token is rotated (single-use) or explicitly revoked (logout). A non-null
    # value means the token can no longer be exchanged.
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
