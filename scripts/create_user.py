"""Create a user in the database.

Use it to create your first user so you can actually log in. Run
scripts/seed_roles.py first so role codes exist.

Example:
  uv run python scripts/create_user.py \
      --email staff@imobilem.com --name "Staff Demo" \
      --password "una-contrasena-segura" --roles gerente --sap-user-id CMENDOZA
"""

import argparse
import asyncio

from app.core.database import SessionFactory
from app.core.security import hash_password
from app.models.user import User
from app.services.auth import get_user_by_email
from app.services.roles import get_roles_by_codes


async def main() -> None:
    parser = argparse.ArgumentParser(description="Crea un usuario en la base de datos.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument(
        "--roles",
        default="",
        help=(
            "Códigos de rol separados por coma (ej. gerente,consulta). "
            "Sin roles, el usuario inicia sesión pero no ve módulos."
        ),
    )
    parser.add_argument("--sap-user-id", default=None)
    args = parser.parse_args()

    # Minimum password policy (the only place a password is set today). Pairs with the
    # login rate limiting: weak passwords + no throttle = online-guessable.
    if len(args.password) < 12:
        print("La contraseña debe tener al menos 12 caracteres.")
        return

    # Canonicalize the email so it matches what login normalizes to (avoids case-variant
    # duplicates and "correct password but 401" lockouts).
    email = args.email.strip().lower()
    role_codes = [code.strip() for code in args.roles.split(",") if code.strip()]

    async with SessionFactory() as session:
        if await get_user_by_email(session, email) is not None:
            print(f"Ya existe un usuario con el correo {email}.")
            return
        roles = await get_roles_by_codes(session, role_codes)
        found = {role.code for role in roles}
        missing = [code for code in role_codes if code not in found]
        if missing:
            print(f"Roles inexistentes: {', '.join(missing)}. Corre scripts/seed_roles.py.")
            return
        session.add(
            User(
                email=email,
                name=args.name,
                password_hash=hash_password(args.password),
                sap_user_id=args.sap_user_id,
                roles=roles,
            )
        )
        await session.commit()
        labels = ", ".join(role.code for role in roles) or "sin roles"
        print(f"Usuario creado: {email} ({labels}).")


if __name__ == "__main__":
    asyncio.run(main())
