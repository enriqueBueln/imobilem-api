"""Tests for the RBAC layer: require_permission and role seeding/sync."""

from typing import Annotated

import pytest
from fastapi import APIRouter, Depends

from app.api.deps import require_permission
from app.core.security import hash_password
from app.main import app
from app.models.role import Role, RolePermission
from app.models.user import User
from app.services.roles import RoleDefinition, sync_roles

# Test-only protected route: the RBAC contract is exercised end-to-end (token ->
# user -> roles -> permission check) without depending on business endpoints
# that do not exist yet.
_router = APIRouter()


@_router.get("/_test/authorize-estimates")
async def _protected(
    current_user: Annotated[User, Depends(require_permission("estimates:authorize"))],
) -> dict[str, str]:
    return {"email": current_user.email}


app.include_router(_router)


async def _seed_user_with_permissions(session, email: str, permissions: list[str]) -> None:
    role = Role(
        code=f"rol-{email.split('@')[0]}",
        label="Rol de prueba",
        permissions=[RolePermission(permission=code) for code in permissions],
    )
    session.add(
        User(
            email=email,
            name="Usuario Prueba",
            password_hash=hash_password("secret123"),
            is_active=True,
            roles=[role],
        )
    )
    await session.commit()


async def _login(client, email: str) -> dict[str, str]:
    response = await client.post("/auth/login", json={"email": email, "password": "secret123"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


def test_require_permission_rejects_unknown_permission():
    with pytest.raises(ValueError, match="Permiso desconocido"):
        require_permission("estimates:fly")


async def test_user_with_permission_passes(client, session):
    await _seed_user_with_permissions(
        session, "gerente@imobilem.com", ["estimates:view", "estimates:authorize"]
    )
    headers = await _login(client, "gerente@imobilem.com")
    response = await client.get("/_test/authorize-estimates", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"email": "gerente@imobilem.com"}


async def test_user_without_permission_gets_403(client, session):
    await _seed_user_with_permissions(session, "consulta@imobilem.com", ["estimates:view"])
    headers = await _login(client, "consulta@imobilem.com")
    response = await client.get("/_test/authorize-estimates", headers=headers)
    assert response.status_code == 403


async def test_user_with_no_roles_gets_403(client, session):
    session.add(
        User(
            email="sinrol@imobilem.com",
            name="Sin Rol",
            password_hash=hash_password("secret123"),
            is_active=True,
        )
    )
    await session.commit()
    headers = await _login(client, "sinrol@imobilem.com")
    response = await client.get("/_test/authorize-estimates", headers=headers)
    assert response.status_code == 403


async def test_me_flattens_permissions_across_roles(client, session):
    role_a = Role(
        code="rol-a",
        label="Rol A",
        permissions=[RolePermission(permission="estimates:view")],
    )
    role_b = Role(
        code="rol-b",
        label="Rol B",
        permissions=[
            RolePermission(permission="estimates:view"),
            RolePermission(permission="expenses:authorize"),
        ],
    )
    session.add(
        User(
            email="multirol@imobilem.com",
            name="Multi Rol",
            password_hash=hash_password("secret123"),
            is_active=True,
            roles=[role_a, role_b],
        )
    )
    await session.commit()
    headers = await _login(client, "multirol@imobilem.com")
    response = await client.get("/auth/me", headers=headers)
    body = response.json()
    # Union without duplicates, sorted.
    assert body["permissions"] == ["estimates:view", "expenses:authorize"]
    assert [role["code"] for role in body["roles"]] == ["rol-a", "rol-b"]


async def test_sync_roles_is_idempotent_and_reconciles(session):
    definition = RoleDefinition(
        code="gerente",
        label="Gerente",
        description=None,
        permissions=frozenset({"estimates:view", "estimates:authorize"}),
    )
    changes = await sync_roles(session, [definition])
    assert changes == ["creado: gerente"]

    changes = await sync_roles(session, [definition])
    assert changes == []

    reduced = RoleDefinition(
        code="gerente",
        label="Gerente",
        description=None,
        permissions=frozenset({"estimates:view"}),
    )
    changes = await sync_roles(session, [reduced])
    assert changes == ["actualizado: gerente (+0/-1 permisos)"]


def test_role_definition_rejects_unknown_permission():
    with pytest.raises(ValueError, match="Permisos desconocidos"):
        RoleDefinition(
            code="x",
            label="X",
            description=None,
            permissions=frozenset({"estimates:teleport"}),
        )
