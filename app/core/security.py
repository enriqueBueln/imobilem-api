"""Password hashing and JWT creation/validation.

This is the piece Django gives you for free in its `auth` app; here we build it.
- Passwords are hashed with Argon2 (via pwdlib) — never stored in plain text.
- Access tokens are signed JWTs (HS256) carrying the user id in `sub`.

Note on logout: a JWT is stateless, so a real server-side logout needs a token
denylist or short-lived access + refresh tokens. That is a documented next step,
not implemented here on purpose (a half-built version would be technical debt).
"""

import datetime as dt
import hashlib
import secrets

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings

settings = get_settings()

_password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _password_hash.verify(password, password_hash)


# Pre-computed hash used to keep authentication constant-time even when the email
# does not exist, so response timing cannot be used to enumerate valid accounts.
_DUMMY_PASSWORD_HASH = hash_password("constant-time-placeholder")


def verify_password_constant_time(password: str, password_hash: str | None) -> bool:
    """Verify a password. When password_hash is None (user not found / inactive) a dummy
    verification still runs, so the response time does not reveal whether the account exists."""
    candidate = password_hash if password_hash is not None else _DUMMY_PASSWORD_HASH
    is_match = verify_password(password, candidate)
    return is_match and password_hash is not None


def create_access_token(subject: str) -> str:
    now = dt.datetime.now(dt.UTC)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + dt.timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"verify_exp": True},
        leeway=10,  # tolerate small clock skew between machines
    )


def generate_refresh_token() -> str:
    """Opaque, high-entropy refresh token. Returned to the client once; only its hash
    is stored (see app/models/refresh_token.py)."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw_token: str) -> str:
    """SHA-256 hex digest used to look up / store a refresh token. A fast hash is correct
    here (the input is already high-entropy random), unlike for user passwords."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
