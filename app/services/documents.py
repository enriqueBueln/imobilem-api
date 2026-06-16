"""Document domain logic over an in-memory SAP stand-in.

The PUBLIC functions here (list/get/authorize/reject) are the seam the routers
depend on. When the real SAP connection lands, replace their internals with
SapClient calls and map SAP payloads to the schemas in app/schemas/documents.py
— routers, permissions and the app do not change.

Stub semantics (a simplification of the SAP authorization chain): acting on a
document fills its FIRST pending chain step with the acting user. Authorizing
moves the document to `partial` (steps remain) or `authorized` (chain done);
rejecting moves it straight to `rejected`. Documents already decided return a
conflict. SAP data is NEVER persisted locally — this store lives in process
memory and resets on restart, exactly like a cache of remote state.
"""

import datetime as dt

from app.models.user import User
from app.schemas.documents import (
    AuthorizationStatus,
    Estimate,
    Payment,
    PaymentOrder,
    PreEstimate,
)
from app.services.sap_mock_data import (
    RAW_ESTIMATES,
    RAW_PAYMENT_ORDERS,
    RAW_PAYMENTS,
    RAW_PRE_ESTIMATES,
)

Document = PreEstimate | Estimate | Payment | PaymentOrder

PENDING_STATUSES = {AuthorizationStatus.none, AuthorizationStatus.partial}


class DocumentNotFoundError(Exception):
    pass


class DocumentNotPendingError(Exception):
    pass


def _build_store() -> dict[str, dict[str, Document]]:
    return {
        "pre_estimates": {raw["id"]: PreEstimate.model_validate(raw) for raw in RAW_PRE_ESTIMATES},
        "estimates": {raw["id"]: Estimate.model_validate(raw) for raw in RAW_ESTIMATES},
        "payments": {raw["id"]: Payment.model_validate(raw) for raw in RAW_PAYMENTS},
        "payment_orders": {
            raw["id"]: PaymentOrder.model_validate(raw) for raw in RAW_PAYMENT_ORDERS
        },
    }


_store: dict[str, dict[str, Document]] = _build_store()


def reset_documents() -> None:
    """Restore the pristine seed. Test helper, mirroring reset_login_rate_limit."""
    global _store
    _store = _build_store()


def list_documents(domain: str) -> list[Document]:
    return list(_store[domain].values())


def get_document(domain: str, document_id: str) -> Document:
    document = _store[domain].get(document_id)
    if document is None:
        raise DocumentNotFoundError(document_id)
    return document


def _now_iso() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fill_next_pending_step(
    document: Document, user: User, status: AuthorizationStatus, comment: str | None
) -> None:
    step = next(
        (s for s in document.authorization_steps if s.status == AuthorizationStatus.none),
        None,
    )
    if step is None:
        return
    step.user_id = str(user.id)
    step.user_name = user.name
    step.status = status
    step.date = _now_iso()
    step.comment = comment


def _require_pending(document: Document) -> None:
    if document.status not in PENDING_STATUSES:
        raise DocumentNotPendingError(document.id)


def authorize_document(
    domain: str, document_id: str, user: User, comment: str | None = None
) -> Document:
    document = get_document(domain, document_id)
    _require_pending(document)
    _fill_next_pending_step(document, user, AuthorizationStatus.authorized, comment)
    chain_done = all(
        step.status != AuthorizationStatus.none for step in document.authorization_steps
    )
    document.status = AuthorizationStatus.authorized if chain_done else AuthorizationStatus.partial
    return document


def reject_document(domain: str, document_id: str, user: User, comment: str) -> Document:
    document = get_document(domain, document_id)
    _require_pending(document)
    _fill_next_pending_step(document, user, AuthorizationStatus.rejected, comment)
    document.status = AuthorizationStatus.rejected
    return document
