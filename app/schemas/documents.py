"""Document schemas — the FROZEN wire contract with the Expo app.

These shapes mirror the app's TypeScript types one-to-one (types/<domain>/ in
imobilem-app); changing a field here breaks the app. Money travels as a string
("2975000.00") so the app can feed it to Decimal.js without float loss; dates
travel as ISO-8601 UTC strings. When SAP lands, its payloads get MAPPED to these
schemas inside the services layer — the wire contract does not change.
"""

import enum
from decimal import Decimal
from typing import Annotated

from pydantic import Field, PlainSerializer

from app.schemas.base import CamelModel


class AuthorizationStatus(enum.StrEnum):
    none = "sin_autorizacion"
    partial = "autorizada_parcialmente"
    authorized = "autorizada"
    rejected = "rechazada"
    received = "recepcionada"


#: Serialized as a plain decimal string (no exponent, scale preserved).
Money = Annotated[Decimal, PlainSerializer(lambda value: format(value, "f"), return_type=str)]


class AuthorizationStep(CamelModel):
    user_id: str
    user_name: str
    status: AuthorizationStatus
    date: str | None
    comment: str | None = None


class PreEstimate(CamelModel):
    id: str
    project_id: str
    project_name: str
    supplier_id: str
    supplier_name: str
    amount: Money
    date: str
    status: AuthorizationStatus
    authorization_steps: list[AuthorizationStep]


class ContractProgress(CamelModel):
    total_amount: Money
    exercised_amount: Money
    remaining_amount: Money
    percentage: int


class Estimate(CamelModel):
    id: str
    project_id: str
    project_name: str
    supplier_id: str
    supplier_name: str
    concept: str
    gross_amount: Money
    amortization: Money
    guarantee_fund: Money
    net_amount: Money
    date: str
    status: AuthorizationStatus
    contract_progress: ContractProgress
    authorization_steps: list[AuthorizationStep]


class Payment(CamelModel):
    id: str
    description: str
    amount: Money
    date: str
    status: AuthorizationStatus
    project_id: str
    project_name: str
    supplier_id: str
    supplier_name: str
    authorization_steps: list[AuthorizationStep]


class PaymentMethod(enum.StrEnum):
    transfer = "transfer"
    check = "check"


class PaymentOrder(CamelModel):
    id: str
    concept: str
    amount: Money
    date: str
    due_date: str
    payment_method: PaymentMethod
    related_estimate_id: str | None
    status: AuthorizationStatus
    project_id: str
    project_name: str
    supplier_id: str
    supplier_name: str
    authorization_steps: list[AuthorizationStep]


class AuthorizeDocumentRequest(CamelModel):
    comment: str | None = Field(default=None, max_length=500)


class RejectDocumentRequest(CamelModel):
    comment: str = Field(min_length=1, max_length=500)
