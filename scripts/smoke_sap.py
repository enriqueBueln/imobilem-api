"""SAP connectivity smoke test (read-only).

Reuses the seeded SapClient and the SAP_* values from your .env. Does a single
read-only GET — it never writes anything to SAP.

Run:  uv run python scripts/smoke_sap.py
"""

import asyncio

from app.core.config import get_settings
from app.core.sap.client import get_sap_client


async def main() -> None:
    settings = get_settings()
    print(f"Probing SAP at {settings.sap_base_url} (read-only GET)...")
    reachable = await get_sap_client().check_connectivity()
    if reachable:
        print(
            "OK: SAP responded and issued a CSRF token. Network + credentials + service are valid."
        )
    else:
        print("UNREACHABLE. Most likely the firewall to TLALOC:1080 is not open for your IP.")
        print("For detailed triage use the curl one-liner in the README (timeout vs 401 vs 404).")


if __name__ == "__main__":
    asyncio.run(main())
