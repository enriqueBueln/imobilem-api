"""Replace a user's roles.

Sets the user's role list to exactly the codes given (empty --roles clears all).

Example:
  uv run python scripts/assign_roles.py --email staff@imobilem.com --roles gerente,consulta
"""

import argparse
import asyncio

from app.core.database import SessionFactory
from app.services.auth import get_user_by_email
from app.services.roles import get_roles_by_codes


async def main() -> None:
    parser = argparse.ArgumentParser(description="Reemplaza los roles de un usuario.")
    parser.add_argument("--email", required=True)
    parser.add_argument(
        "--roles",
        default="",
        help="Códigos de rol separados por coma (vacío para quitar todos).",
    )
    args = parser.parse_args()

    role_codes = [code.strip() for code in args.roles.split(",") if code.strip()]

    async with SessionFactory() as session:
        user = await get_user_by_email(session, args.email)
        if user is None:
            print(f"No existe un usuario con el correo {args.email.strip().lower()}.")
            return
        roles = await get_roles_by_codes(session, role_codes)
        found = {role.code for role in roles}
        missing = [code for code in role_codes if code not in found]
        if missing:
            print(f"Roles inexistentes: {', '.join(missing)}. Corre scripts/seed_roles.py.")
            return
        user.roles = roles
        await session.commit()
        labels = ", ".join(role.code for role in roles) or "sin roles"
        print(f"Roles de {user.email}: {labels}.")


if __name__ == "__main__":
    asyncio.run(main())
