"""Role domain business logic.

`sync_roles` is the engine behind scripts/seed_roles.py: it upserts role
definitions and reconciles their permissions (add missing, remove extra).
Running it twice is a no-op; roles not present in the definitions are left
untouched, so a re-seed never deletes roles created by hand.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.permissions import ALL_PERMISSIONS
from app.models.role import Role, RolePermission


@dataclass(frozen=True)
class RoleDefinition:
    code: str
    label: str
    description: str | None
    permissions: frozenset[str]

    def __post_init__(self) -> None:
        unknown = self.permissions - ALL_PERMISSIONS
        if unknown:
            msg = (
                f"Permisos desconocidos en el rol {self.code!r}: {sorted(unknown)}. "
                "Revisa app/models/permissions.py."
            )
            raise ValueError(msg)


async def get_role_by_code(session: AsyncSession, code: str) -> Role | None:
    result = await session.execute(select(Role).where(Role.code == code))
    return result.scalar_one_or_none()


async def get_roles_by_codes(session: AsyncSession, codes: list[str]) -> list[Role]:
    result = await session.execute(select(Role).where(Role.code.in_(codes)))
    return list(result.scalars().all())


async def sync_roles(session: AsyncSession, definitions: list[RoleDefinition]) -> list[str]:
    """Upsert each definition and reconcile its permissions. Returns a change log."""
    changes: list[str] = []
    for definition in definitions:
        role = await get_role_by_code(session, definition.code)
        if role is None:
            role = Role(
                id=uuid.uuid4(),
                code=definition.code,
                label=definition.label,
                description=definition.description,
                permissions=[
                    RolePermission(permission=code) for code in sorted(definition.permissions)
                ],
            )
            session.add(role)
            changes.append(f"creado: {definition.code}")
            continue

        if (role.label, role.description) != (definition.label, definition.description):
            role.label = definition.label
            role.description = definition.description
            changes.append(f"actualizado: {definition.code} (etiqueta/descripción)")

        current = {entry.permission for entry in role.permissions}
        missing = definition.permissions - current
        extra = current - definition.permissions
        if missing or extra:
            role.permissions = [
                entry for entry in role.permissions if entry.permission not in extra
            ] + [RolePermission(permission=code) for code in sorted(missing)]
            changes.append(
                f"actualizado: {definition.code} (+{len(missing)}/-{len(extra)} permisos)"
            )
    await session.commit()
    return changes
