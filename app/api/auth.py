"""Auth endpoints (the Retool-style own-auth, independent of SAP).

- POST /auth/login    email + password -> access + refresh tokens
- POST /auth/refresh  refresh token   -> a new access + refresh pair (old refresh revoked)
- GET  /auth/me       returns the current user's profile (protected)
- POST /auth/logout   revokes the presented refresh token (best-effort)
"""

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import CurrentUser, DbSession
from app.core.rate_limit import enforce_login_rate_limit
from app.core.security import create_access_token
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    TokenResponse,
    UserResponse,
)
from app.services.auth import (
    authenticate_user,
    issue_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(request: Request, credentials: LoginRequest, session: DbSession) -> TokenResponse:
    # Throttle by client IP before doing any work (also caps server-side Argon2 cost).
    enforce_login_rate_limit(request)
    user = await authenticate_user(session, credentials.email, credentials.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o contraseña incorrectos.",
        )
    return TokenResponse(
        access_token=create_access_token(subject=str(user.id)),
        refresh_token=await issue_refresh_token(session, user.id),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, session: DbSession) -> TokenResponse:
    # No access-token dependency on purpose: the whole point of refresh is to recover when
    # the access token has already expired.
    result = await rotate_refresh_token(session, body.refresh_token)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesión expirada. Inicia sesión de nuevo.",
        )
    user, new_refresh_token = result
    return TokenResponse(
        access_token=create_access_token(subject=str(user.id)),
        refresh_token=new_refresh_token,
    )


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: LogoutRequest, session: DbSession) -> None:
    # Revoke the refresh token so it can never be exchanged again. No auth dependency: the
    # access token may already be expired, and possession of the refresh token is enough.
    if body.refresh_token:
        await revoke_refresh_token(session, body.refresh_token)
    return None
