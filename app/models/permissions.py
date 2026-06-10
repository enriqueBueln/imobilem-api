"""Permission catalog — the set of capabilities the code actually implements.

Permissions are CODE-owned, not data: a row in the database cannot grant a
capability no endpoint implements. Roles (business-owned, they change with the
client) live in the database and map to entries of this catalog. A permission
string is "<resource>:<action>", e.g. "estimates:authorize".

`authorize` covers both authorizing and rejecting a document — in the B2B flow
they are a single faculty ("this document is yours to decide on").
"""

import enum


class Resource(enum.StrEnum):
    pre_estimates = "pre_estimates"
    estimates = "estimates"
    expenses = "expenses"
    purchase_orders = "purchase_orders"
    change_orders = "change_orders"
    payments = "payments"
    payment_orders = "payment_orders"
    users = "users"


class Action(enum.StrEnum):
    view = "view"
    authorize = "authorize"
    manage = "manage"


#: Resources that represent SAP documents flowing through authorization chains.
DOCUMENT_RESOURCES: tuple[Resource, ...] = (
    Resource.pre_estimates,
    Resource.estimates,
    Resource.expenses,
    Resource.purchase_orders,
    Resource.change_orders,
    Resource.payments,
    Resource.payment_orders,
)


def permission_code(resource: Resource, action: Action) -> str:
    return f"{resource}:{action}"


#: Every permission the API recognizes. `require_permission` and the role seeds
#: validate against this set, so a typo fails fast instead of silently denying.
ALL_PERMISSIONS: frozenset[str] = frozenset(
    permission_code(resource, action)
    for resource in DOCUMENT_RESOURCES
    for action in (Action.view, Action.authorize)
) | {permission_code(Resource.users, Action.manage)}
