import datetime as dt

import jwt

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.role import Role, RolePermission
from app.models.user import User


async def _seed_user(session) -> None:
    gerente = Role(
        code="gerente",
        label="Gerente",
        permissions=[
            RolePermission(permission="estimates:view"),
            RolePermission(permission="estimates:authorize"),
        ],
    )
    session.add(
        User(
            email="staff@imobilem.com",
            name="Staff Demo",
            password_hash=hash_password("secret123"),
            sap_user_id="CMENDOZA",
            is_active=True,
            roles=[gerente],
        )
    )
    await session.commit()


async def test_login_and_me(client, session):
    await _seed_user(session)

    login = await client.post(
        "/auth/login", json={"email": "staff@imobilem.com", "password": "secret123"}
    )
    assert login.status_code == 200
    # The wire contract is camelCase (CamelModel), matching what the Expo app expects.
    token = login.json()["accessToken"]

    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "staff@imobilem.com"
    assert body["sapUserId"] == "CMENDOZA"
    # Roles travel for display; permissions travel flattened for UI gating.
    assert body["roles"] == [{"code": "gerente", "label": "Gerente"}]
    assert body["permissions"] == ["estimates:authorize", "estimates:view"]


async def test_login_wrong_password(client, session):
    await _seed_user(session)
    response = await client.post(
        "/auth/login", json={"email": "staff@imobilem.com", "password": "wrong"}
    )
    assert response.status_code == 401


async def test_login_email_is_case_insensitive(client, session):
    # The user is stored lowercased; logging in with different case + whitespace must work.
    await _seed_user(session)
    response = await client.post(
        "/auth/login", json={"email": "  STAFF@Imobilem.com ", "password": "secret123"}
    )
    assert response.status_code == 200
    assert "accessToken" in response.json()


async def test_login_is_rate_limited(client, session):
    await _seed_user(session)
    # First attempts are allowed (wrong password -> 401), then the per-IP window trips 429.
    statuses = []
    for _ in range(12):
        response = await client.post(
            "/auth/login", json={"email": "staff@imobilem.com", "password": "wrong"}
        )
        statuses.append(response.status_code)
    assert 429 in statuses
    assert statuses.count(401) <= 10


async def test_me_requires_token(client):
    response = await client.get("/auth/me")
    assert response.status_code == 401


async def test_me_rejects_expired_token(client, session):
    await _seed_user(session)
    settings = get_settings()
    past = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
    expired = jwt.encode(
        {"sub": "00000000-0000-0000-0000-000000000000", "iat": past, "exp": past},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


async def _login(client) -> dict:
    response = await client.post(
        "/auth/login", json={"email": "staff@imobilem.com", "password": "secret123"}
    )
    assert response.status_code == 200
    return response.json()


async def test_login_returns_refresh_token(client, session):
    await _seed_user(session)
    body = await _login(client)
    assert body["accessToken"]
    assert body["refreshToken"]


async def test_refresh_rotates_tokens(client, session):
    await _seed_user(session)
    first = await _login(client)

    refreshed = await client.post(
        "/auth/refresh", json={"refreshToken": first["refreshToken"]}
    )
    assert refreshed.status_code == 200
    new_tokens = refreshed.json()
    # A new, usable access token comes back...
    me = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {new_tokens['accessToken']}"}
    )
    assert me.status_code == 200
    # ...and the refresh token rotated (single-use).
    assert new_tokens["refreshToken"] != first["refreshToken"]

    # The original refresh token is now revoked and cannot be exchanged again.
    replay = await client.post(
        "/auth/refresh", json={"refreshToken": first["refreshToken"]}
    )
    assert replay.status_code == 401


async def test_refresh_reuse_revokes_whole_chain(client, session):
    await _seed_user(session)
    first = await _login(client)

    second = await client.post(
        "/auth/refresh", json={"refreshToken": first["refreshToken"]}
    )
    second_refresh = second.json()["refreshToken"]

    # Replaying the already-rotated token is treated as theft: the whole chain is revoked,
    # so even the legitimately-issued second token stops working.
    replay = await client.post(
        "/auth/refresh", json={"refreshToken": first["refreshToken"]}
    )
    assert replay.status_code == 401

    after_theft = await client.post(
        "/auth/refresh", json={"refreshToken": second_refresh}
    )
    assert after_theft.status_code == 401


async def test_refresh_rejects_unknown_token(client, session):
    await _seed_user(session)
    response = await client.post("/auth/refresh", json={"refreshToken": "not-a-real-token"})
    assert response.status_code == 401


async def test_logout_revokes_refresh_token(client, session):
    await _seed_user(session)
    tokens = await _login(client)

    logout = await client.post("/auth/logout", json={"refreshToken": tokens["refreshToken"]})
    assert logout.status_code == 204

    # After logout the refresh token is dead.
    response = await client.post(
        "/auth/refresh", json={"refreshToken": tokens["refreshToken"]}
    )
    assert response.status_code == 401
