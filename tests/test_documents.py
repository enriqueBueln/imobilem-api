"""Contract tests for the document endpoints (list/detail/authorize/reject).

These freeze the wire contract the Expo app depends on: camelCase keys, money
as strings, Spanish error details, and the permission requirements per route.
"""

import pytest

from app.core.security import hash_password
from app.models.role import Role, RolePermission
from app.models.user import User
from app.services.documents import reset_documents

DOMAINS = [
    pytest.param("/pre-estimates", "pre_estimates", "PE-001", id="pre_estimates"),
    pytest.param("/estimates", "estimates", "EST-001", id="estimates"),
    pytest.param("/payments", "payments", "PAG-001", id="payments"),
    pytest.param("/payment-orders", "payment_orders", "OP-001", id="payment_orders"),
]


@pytest.fixture(autouse=True)
def _pristine_documents():
    reset_documents()
    yield
    reset_documents()


async def _login_user_with_permissions(client, session, permissions: list[str]) -> dict[str, str]:
    email = "docs@imobilem.com"
    role = Role(
        code="rol-docs",
        label="Rol Documentos",
        permissions=[RolePermission(permission=code) for code in permissions],
    )
    session.add(
        User(
            email=email,
            name="Laura Treviño",
            password_hash=hash_password("secret123"),
            is_active=True,
            roles=[role],
        )
    )
    await session.commit()
    response = await client.post("/auth/login", json={"email": email, "password": "secret123"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


@pytest.mark.parametrize(("prefix", "resource", "pending_id"), DOMAINS)
async def test_list_requires_token(client, prefix, resource, pending_id):
    response = await client.get(prefix)
    assert response.status_code == 401


@pytest.mark.parametrize(("prefix", "resource", "pending_id"), DOMAINS)
async def test_list_requires_view_permission(client, session, prefix, resource, pending_id):
    headers = await _login_user_with_permissions(client, session, ["users:manage"])
    response = await client.get(prefix, headers=headers)
    assert response.status_code == 403


@pytest.mark.parametrize(("prefix", "resource", "pending_id"), DOMAINS)
async def test_list_and_detail_with_view_permission(client, session, prefix, resource, pending_id):
    headers = await _login_user_with_permissions(client, session, [f"{resource}:view"])

    listing = await client.get(prefix, headers=headers)
    assert listing.status_code == 200
    documents = listing.json()
    assert len(documents) > 0
    # Wire contract: camelCase keys, money as strings.
    first = documents[0]
    assert "authorizationSteps" in first
    amount_field = "amount" if "amount" in first else "netAmount"
    assert isinstance(first[amount_field], str)

    detail = await client.get(f"{prefix}/{pending_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == pending_id

    missing = await client.get(f"{prefix}/NO-EXISTE", headers=headers)
    assert missing.status_code == 404


@pytest.mark.parametrize(("prefix", "resource", "pending_id"), DOMAINS)
async def test_authorize_requires_authorize_permission(
    client, session, prefix, resource, pending_id
):
    headers = await _login_user_with_permissions(client, session, [f"{resource}:view"])
    response = await client.post(f"{prefix}/{pending_id}/authorize", headers=headers)
    assert response.status_code == 403


@pytest.mark.parametrize(("prefix", "resource", "pending_id"), DOMAINS)
async def test_authorize_advances_the_chain(client, session, prefix, resource, pending_id):
    headers = await _login_user_with_permissions(
        client, session, [f"{resource}:view", f"{resource}:authorize"]
    )

    first = await client.post(f"{prefix}/{pending_id}/authorize", headers=headers)
    assert first.status_code == 200
    body = first.json()
    steps = body["authorizationSteps"]
    # The acting user fills the first pending chain slot with their real name.
    acted = [s for s in steps if s["userName"] == "Laura Treviño"]
    assert len(acted) == 1
    assert acted[0]["status"] == "autorizada"
    assert acted[0]["date"] is not None
    expected = (
        "autorizada"
        if all(s["status"] != "sin_autorizacion" for s in steps)
        else "autorizada_parcialmente"
    )
    assert body["status"] == expected


@pytest.mark.parametrize(("prefix", "resource", "pending_id"), DOMAINS)
async def test_reject_requires_comment_and_rejects(client, session, prefix, resource, pending_id):
    headers = await _login_user_with_permissions(
        client, session, [f"{resource}:view", f"{resource}:authorize"]
    )

    no_comment = await client.post(f"{prefix}/{pending_id}/reject", json={}, headers=headers)
    assert no_comment.status_code == 422

    rejected = await client.post(
        f"{prefix}/{pending_id}/reject",
        json={"comment": "Monto fuera de presupuesto."},
        headers=headers,
    )
    assert rejected.status_code == 200
    body = rejected.json()
    assert body["status"] == "rechazada"
    acted = [s for s in body["authorizationSteps"] if s["userName"] == "Laura Treviño"]
    assert acted[0]["comment"] == "Monto fuera de presupuesto."

    # Already decided: further mutations conflict.
    again = await client.post(f"{prefix}/{pending_id}/authorize", headers=headers)
    assert again.status_code == 409
    assert again.json()["detail"] == "El documento ya fue procesado y no admite cambios."


async def test_full_chain_authorization_reaches_authorized(client, session):
    headers = await _login_user_with_permissions(
        client, session, ["pre_estimates:view", "pre_estimates:authorize"]
    )
    # PE-001 has two pending steps: first authorize -> partial, second -> authorized.
    first = await client.post("/pre-estimates/PE-001/authorize", headers=headers)
    assert first.json()["status"] == "autorizada_parcialmente"
    second = await client.post("/pre-estimates/PE-001/authorize", headers=headers)
    assert second.json()["status"] == "autorizada"
