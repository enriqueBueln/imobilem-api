"""Audit-trail tests: every authorize/reject leaves exactly one durable, correct
AuthorizationEvent row, and a conflicted (409) attempt leaves none.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.models.authorization_event import AuthorizationEvent
from app.models.role import Role, RolePermission
from app.models.user import User
from app.services.documents import reset_documents

USER_NAME = "Laura Treviño"
USER_EMAIL = "docs@imobilem.com"
USER_SAP_ID = "CMENDOZA"


@pytest.fixture(autouse=True)
def _pristine_documents():
    reset_documents()
    yield
    reset_documents()


async def _login(client, session, permissions: list[str]) -> dict[str, str]:
    role = Role(
        code="rol-docs",
        label="Rol Documentos",
        permissions=[RolePermission(permission=code) for code in permissions],
    )
    session.add(
        User(
            email=USER_EMAIL,
            name=USER_NAME,
            password_hash=hash_password("secret123"),
            sap_user_id=USER_SAP_ID,
            is_active=True,
            roles=[role],
        )
    )
    await session.commit()
    response = await client.post("/auth/login", json={"email": USER_EMAIL, "password": "secret123"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


async def _events(session) -> list[AuthorizationEvent]:
    result = await session.execute(select(AuthorizationEvent))
    return list(result.scalars().all())


async def test_authorize_records_event_with_actor_snapshot(client, session):
    headers = await _login(client, session, ["pre_estimates:view", "pre_estimates:authorize"])
    response = await client.post("/pre-estimates/PE-001/authorize", headers=headers)
    assert response.status_code == 200

    events = await _events(session)
    assert len(events) == 1
    event = events[0]
    assert event.action == "authorize"
    assert event.document_type == "pre_estimates"
    assert event.document_id == "PE-001"
    # PE-001 has two steps, so a single authorization leaves it partial.
    assert event.resulting_status == "autorizada_parcialmente"
    assert event.comment is None
    # Denormalized actor snapshot — must survive a later rename of the user.
    assert event.user_name == USER_NAME
    assert event.user_email == USER_EMAIL
    assert event.sap_user_id == USER_SAP_ID
    assert event.amount is not None


async def test_authorize_captures_optional_comment(client, session):
    headers = await _login(client, session, ["payments:view", "payments:authorize"])
    response = await client.post(
        "/payments/PAG-001/authorize",
        json={"comment": "Visto bueno."},
        headers=headers,
    )
    assert response.status_code == 200

    events = await _events(session)
    assert len(events) == 1
    assert events[0].comment == "Visto bueno."


async def test_reject_records_event_with_comment_and_amount(client, session):
    headers = await _login(client, session, ["estimates:view", "estimates:authorize"])
    detail = await client.get("/estimates/EST-001", headers=headers)
    net_amount = Decimal(detail.json()["netAmount"])

    response = await client.post(
        "/estimates/EST-001/reject",
        json={"comment": "Falta soporte."},
        headers=headers,
    )
    assert response.status_code == 200

    events = await _events(session)
    assert len(events) == 1
    event = events[0]
    assert event.action == "reject"
    assert event.resulting_status == "rechazada"
    assert event.comment == "Falta soporte."
    # An estimate's audited figure is its NET amount, not gross.
    assert event.amount == net_amount


async def test_full_chain_records_one_event_per_decision(client, session):
    headers = await _login(client, session, ["pre_estimates:view", "pre_estimates:authorize"])
    first = await client.post("/pre-estimates/PE-001/authorize", headers=headers)
    assert first.json()["status"] == "autorizada_parcialmente"
    second = await client.post("/pre-estimates/PE-001/authorize", headers=headers)
    assert second.json()["status"] == "autorizada"

    events = await _events(session)
    assert len(events) == 2
    assert {e.resulting_status for e in events} == {
        "autorizada_parcialmente",
        "autorizada",
    }


async def test_conflict_leaves_no_event(client, session):
    headers = await _login(client, session, ["pre_estimates:view", "pre_estimates:authorize"])
    rejected = await client.post(
        "/pre-estimates/PE-001/reject",
        json={"comment": "No procede."},
        headers=headers,
    )
    assert rejected.status_code == 200

    conflict = await client.post("/pre-estimates/PE-001/authorize", headers=headers)
    assert conflict.status_code == 409

    events = await _events(session)
    # Only the reject was recorded; the conflicted authorize left nothing behind.
    assert len(events) == 1
    assert events[0].action == "reject"
