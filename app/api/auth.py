"""Auth endpoints (the Retool-style own-auth, independent of SAP).

- POST /auth/login   email + password -> JWT Bearer token
- GET  /auth/me      returns the current user's profile (protected)
- POST /auth/logout  stateless: the client discards the token (see note in security.py)
"""

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import CurrentUser, DbSession
from app.core.rate_limit import enforce_login_rate_limit
from app.core.security import create_access_token
from app.schemas.auth import LoginRequest, TokenResponse, UserResponse
from app.services.auth import authenticate_user

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
    return TokenResponse(access_token=create_access_token(subject=str(user.id)))


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(current_user: CurrentUser) -> None:
    # JWT is stateless: real logout = client drops the token. Server-side revocation
    # (denylist / refresh tokens) is the documented next step, not built here.
    return None
