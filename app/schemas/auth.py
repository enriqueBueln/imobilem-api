"""Pydantic schemas for the auth domain.

Schemas define the shape of what comes IN (requests) and goes OUT (responses).
FastAPI uses them to validate, document (Swagger) and serialize automatically.
Field names are snake_case here but travel as camelCase over the wire (see CamelModel).

Django equivalent: DRF serializers.
"""

import uuid

from pydantic import EmailStr, field_validator

from app.schemas.base import CamelModel


class LoginRequest(CamelModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        # Canonicalize so case/whitespace differences never lock a user out. Must match
        # the normalization applied when the user is created (scripts/create_user.py).
        return value.strip().lower()


class TokenResponse(CamelModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 — OAuth2 token type label, not a secret


class RefreshRequest(CamelModel):
    refresh_token: str


class LogoutRequest(CamelModel):
    # Optional: a client may log out without a stored refresh token (e.g. it was already
    # cleared). When present, the token is revoked server-side.
    refresh_token: str | None = None


class RoleResponse(CamelModel):
    code: str
    label: str


class UserResponse(CamelModel):
    id: uuid.UUID
    email: EmailStr
    name: str
    sap_user_id: str | None
    is_active: bool
    roles: list[RoleResponse]
    # Flattened union across roles, already resolved server-side — the app gates UI
    # with these strings and never re-derives permissions from roles.
    permissions: list[str]
