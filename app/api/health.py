"""Health endpoints.

- GET /health      liveness: the app is up (no dependencies checked).
- GET /health/db   readiness: can we reach Postgres?
- GET /health/sap  readiness: can we reach SAP? (today this will report unreachable
                   until the firewall to TLALOC:1080 is opened — that is expected).
"""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import DbSession
from app.core.sap.client import get_sap_client

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger(__name__)


@router.get("")
async def liveness() -> dict:
    return {"status": "ok"}


@router.get("/db")
async def db_health(session: DbSession) -> JSONResponse:
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        # Log the real error server-side; do NOT leak DB internals to the client.
        logger.exception("Database health check failed")
        return JSONResponse(
            status_code=503,
            content={"status": "error", "dependency": "database"},
        )
    return JSONResponse(content={"status": "ok", "dependency": "database"})


@router.get("/sap")
async def sap_health() -> JSONResponse:
    reachable = await get_sap_client().check_connectivity()
    if not reachable:
        return JSONResponse(
            status_code=503,
            content={"status": "unreachable", "dependency": "sap"},
        )
    return JSONResponse(content={"status": "ok", "dependency": "sap"})
