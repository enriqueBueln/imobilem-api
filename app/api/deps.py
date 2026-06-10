"""Shared route dependencies.

`DbSession` injects a database session; `CurrentUser` validates the Bearer JWT and
loads the user (roles and permissions included, via selectin relationships).
`require_permission` builds on top of it for per-capability route protection.

Django equivalent: the mix of middleware + DRF permissions, but composable per route.
"""

import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.security import decode_access_token
from app.models.permissions import ALL_PERMISSIONS
from app.models.user import User
from app.services.auth import get_user_by_id

# tokenUrl is metadata for Swagger's "Authorize" button. Login itself is JSON-based.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

DbSession = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: DbSession,
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No autorizado. Inicia sesión de nuevo.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        subject = payload.get("sub")
        if subject is None:
            raise credentials_error
        user = await get_user_by_id(session, uuid.UUID(subject))
    except (jwt.PyJWTError, ValueError) as exc:
        raise credentials_error from exc
    if user is None or not user.is_active:
        raise credentials_error
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_permission(permission: str) -> Callable[..., Coroutine[None, None, User]]:
    """Dependency factory: 403 unless the current user holds `permission`.

    Usage:
        user: Annotated[User, Depends(require_permission("estimates:authorize"))]
    """
    # Fail at import time, not at request time: a typo here would otherwise deny
    # every caller and read as a permissions misconfiguration.
    if permission not in ALL_PERMISSIONS:
        msg = f"Permiso desconocido: {permission!r}. Revisa app/models/permissions.py."
        raise ValueError(msg)

    async def dependency(current_user: CurrentUser) -> User:
        if permission not in current_user.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Sin permisos para esta acción. Contacta al administrador.",
            )
        return current_user

    return dependency
