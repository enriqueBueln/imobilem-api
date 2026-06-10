"""Seed (or re-sync) the role catalog.

Idempotent: run it as many times as you want. When Imobilem sends the real role
list, edit SEED_ROLES below and re-run — no other code changes.

  uv run python scripts/seed_roles.py
"""

import asyncio

from app.core.database import SessionFactory
from app.models.permissions import (
    ALL_PERMISSIONS,
    DOCUMENT_RESOURCES,
    Action,
    Resource,
    permission_code,
)
from app.services.roles import RoleDefinition, sync_roles

_ALL_VIEWS = frozenset(permission_code(resource, Action.view) for resource in DOCUMENT_RESOURCES)

# PLACEHOLDERS until Fede sends the real B2B role list (committed for the week
# of 2026-06-08). Replace these definitions with the real ones and re-run.
SEED_ROLES = [
    RoleDefinition(
        code="admin",
        label="Administrador",
        description="Acceso total, incluida la administración de usuarios.",
        permissions=frozenset(ALL_PERMISSIONS),
    ),
    RoleDefinition(
        code="gerente",
        label="Gerente",
        description="Autoriza estimaciones, preestimaciones y órdenes de compra.",
        permissions=_ALL_VIEWS
        | frozenset(
            permission_code(resource, Action.authorize)
            for resource in (Resource.pre_estimates, Resource.estimates, Resource.purchase_orders)
        ),
    ),
    RoleDefinition(
        code="consulta",
        label="Consulta",
        description="Solo lectura de todos los documentos.",
        permissions=_ALL_VIEWS,
    ),
]


async def main() -> None:
    async with SessionFactory() as session:
        changes = await sync_roles(session, SEED_ROLES)
    if not changes:
        print("Roles ya sincronizados, sin cambios.")
        return
    for change in changes:
        print(change)


if __name__ == "__main__":
    asyncio.run(main())
