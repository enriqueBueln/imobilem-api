"""User model.

Lives in OUR database (Postgres), not in SAP. The `sap_user_id` is a PARAMETER
used to filter SAP data per user — never a credential. SAP is always reached with
the single technical user. This is the Retool-style identity model.

What a user CAN DO comes from their roles (see app/models/role.py); WHICH
documents reach them is decided by SAP's authorization chain via `sap_user_id`.

Django equivalent: a `models.py` class.
"""

import datetime as dt
import uuid

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.role import Role, user_roles


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    sap_user_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    roles: Mapped[list[Role]] = relationship(secondary=user_roles, lazy="selectin")

    @property
    def permissions(self) -> list[str]:
        """Flattened union of all role permissions — the shape the app consumes."""
        return sorted({code for role in self.roles for code in role.permission_codes})
