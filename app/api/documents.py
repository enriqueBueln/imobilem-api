"""Document routers — one per domain, all built from the same factory.

Contract per domain (FROZEN — the Expo app consumes exactly this):
  GET  /<domain>                      list          requires <resource>:view
  GET  /<domain>/{id}                 detail        requires <resource>:view
  POST /<domain>/{id}/authorize       authorize     requires <resource>:authorize
  POST /<domain>/{id}/reject          reject        requires <resource>:authorize

`authorize` covers rejecting too (single faculty, see app/models/permissions.py),
which is why both mutations require the same permission.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import DbSession, require_permission
from app.models.authorization_event import AuthorizationAction
from app.models.permissions import Action, Resource, permission_code
from app.models.user import User
from app.schemas.documents import (
    AuthorizeDocumentRequest,
    Estimate,
    Payment,
    PaymentOrder,
    PreEstimate,
    RejectDocumentRequest,
)
from app.services.audit import record_authorization
from app.services.documents import (
    Document,
    DocumentNotFoundError,
    DocumentNotPendingError,
    authorize_document,
    get_document,
    list_documents,
    reject_document,
)

ALREADY_PROCESSED_DETAIL = "El documento ya fue procesado y no admite cambios."


@dataclass(frozen=True)
class DocumentDomainConfig:
    prefix: str
    store_key: str
    resource: Resource
    model: type[Document]
    not_found_detail: str


DOCUMENT_DOMAINS = [
    DocumentDomainConfig(
        prefix="/pre-estimates",
        store_key="pre_estimates",
        resource=Resource.pre_estimates,
        model=PreEstimate,
        not_found_detail="Preestimación no encontrada.",
    ),
    DocumentDomainConfig(
        prefix="/estimates",
        store_key="estimates",
        resource=Resource.estimates,
        model=Estimate,
        not_found_detail="Estimación no encontrada.",
    ),
    DocumentDomainConfig(
        prefix="/payments",
        store_key="payments",
        resource=Resource.payments,
        model=Payment,
        not_found_detail="Pago no encontrado.",
    ),
    DocumentDomainConfig(
        prefix="/payment-orders",
        store_key="payment_orders",
        resource=Resource.payment_orders,
        model=PaymentOrder,
        not_found_detail="Orden de pago no encontrada.",
    ),
]


def build_document_router(config: DocumentDomainConfig) -> APIRouter:
    router = APIRouter(prefix=config.prefix, tags=[config.store_key])

    ViewUser = Annotated[
        User, Depends(require_permission(permission_code(config.resource, Action.view)))
    ]
    AuthorizeUser = Annotated[
        User, Depends(require_permission(permission_code(config.resource, Action.authorize)))
    ]

    def _get_or_404(document_id: str) -> Document:
        try:
            return get_document(config.store_key, document_id)
        except DocumentNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=config.not_found_detail
            ) from exc

    @router.get("", response_model=list[config.model])
    async def list_endpoint(_user: ViewUser) -> list[Document]:
        return list_documents(config.store_key)

    @router.get("/{document_id}", response_model=config.model)
    async def detail_endpoint(document_id: str, _user: ViewUser) -> Document:
        return _get_or_404(document_id)

    @router.post("/{document_id}/authorize", response_model=config.model)
    async def authorize_endpoint(
        document_id: str,
        current_user: AuthorizeUser,
        session: DbSession,
        payload: AuthorizeDocumentRequest | None = None,
    ) -> Document:
        _get_or_404(document_id)
        comment = payload.comment if payload else None
        try:
            document = authorize_document(config.store_key, document_id, current_user, comment)
        except DocumentNotPendingError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=ALREADY_PROCESSED_DETAIL
            ) from exc
        # Audit only AFTER a successful decision — a 409 must leave no row. When SAP lands
        # and the write is no longer in-memory, revisit the ordering/failure handling here
        # (audit-first or two-phase) so the trail can never drift from SAP's state.
        await record_authorization(
            session,
            user=current_user,
            document_type=config.store_key,
            document=document,
            action=AuthorizationAction.authorize,
            comment=comment,
        )
        return document

    @router.post("/{document_id}/reject", response_model=config.model)
    async def reject_endpoint(
        document_id: str,
        payload: RejectDocumentRequest,
        current_user: AuthorizeUser,
        session: DbSession,
    ) -> Document:
        _get_or_404(document_id)
        try:
            document = reject_document(config.store_key, document_id, current_user, payload.comment)
        except DocumentNotPendingError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=ALREADY_PROCESSED_DETAIL
            ) from exc
        # Audit only after success — see authorize_endpoint for the SAP-era ordering note.
        await record_authorization(
            session,
            user=current_user,
            document_type=config.store_key,
            document=document,
            action=AuthorizationAction.reject,
            comment=payload.comment,
        )
        return document

    return router


def get_document_routers() -> list[APIRouter]:
    return [build_document_router(config) for config in DOCUMENT_DOMAINS]
