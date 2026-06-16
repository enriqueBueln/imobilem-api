"""Persistence of the authorization audit trail.

Kept separate from documents.py (the SAP seam) on purpose: that layer stays a pure
stand-in for remote state, while WHO decided WHAT is ours and lives in Postgres. The
router calls record_authorization() AFTER a decision succeeds, so a rejected (409)
attempt never leaves a row.
"""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.authorization_event import AuthorizationAction, AuthorizationEvent
from app.models.user import User
from app.schemas.documents import Estimate
from app.services.documents import Document


def _primary_amount(document: Document) -> Decimal:
    """The estimate's authoritative figure is its NET amount; every other type
    exposes a single `amount`."""
    if isinstance(document, Estimate):
        return document.net_amount
    return document.amount


async def record_authorization(
    session: AsyncSession,
    *,
    user: User,
    document_type: str,
    document: Document,
    action: AuthorizationAction,
    comment: str | None,
) -> None:
    session.add(
        AuthorizationEvent(
            user_id=user.id,
            user_name=user.name,
            user_email=user.email,
            sap_user_id=user.sap_user_id,
            document_type=document_type,
            document_id=document.id,
            action=action.value,
            resulting_status=document.status.value,
            comment=comment,
            amount=_primary_amount(document),
        )
    )
    await session.commit()
