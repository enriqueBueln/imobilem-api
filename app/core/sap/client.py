"""SAP Gateway OData V2 client (TLALOC system).

Resolves the standard SAP Gateway pattern once, so every future service reuses it:

  - HTTP Basic Auth with the single technical user (from .env).
  - Reads (GET): only Basic Auth. OData V2 does NOT require a CSRF token to read.
  - Writes (POST/PUT/DELETE): the CSRF dance — a GET with `X-CSRF-Token: Fetch`
    returns a token AND a session cookie; both must travel together in the write.
    If SAP answers 403 (token expired/invalid) we re-fetch once and retry.

Status: SEEDED. Real read services (estimates, etc.) are added once Federico
delivers the `$metadata` and the entity-set names — not invented here.

A fresh httpx.AsyncClient is used per operation so its cookie-jar keeps the token
and session cookie together with no cross-request interference. Connection pooling
and token caching are a later optimization, intentionally out of scope for now.
"""

import asyncio
import logging
from functools import lru_cache
from typing import Any

import httpx
from fastapi import HTTPException, status

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class SapClient:
    def __init__(self, base_url: str, user: str, password: str, timeout: float) -> None:
        self._base_url = base_url if base_url.endswith("/") else base_url + "/"
        self._auth = httpx.BasicAuth(user, password)
        self._timeout = timeout

    def _new_client(self) -> httpx.AsyncClient:
        # Granular timeout: a short connect budget, the configured read/write budget.
        timeout = httpx.Timeout(self._timeout, connect=min(5.0, self._timeout))
        return httpx.AsyncClient(base_url=self._base_url, auth=self._auth, timeout=timeout)

    async def check_connectivity(self) -> bool:
        """Read-only GET of the service document. True if SAP answers and issues a CSRF token.

        This is the programmatic version of the network smoke test.
        """
        try:
            async with self._new_client() as client:
                response = await client.get(
                    "", headers={"X-CSRF-Token": "Fetch", "Accept": "application/json"}
                )
        except httpx.HTTPError:
            return False
        return response.status_code == 200 and "x-csrf-token" in response.headers

    async def read(self, entity_set: str, params: dict[str, Any] | None = None) -> Any:
        """GET an entity set. Reads need only Basic Auth (no CSRF)."""
        async with self._new_client() as client:
            response = await client.get(
                entity_set, params=params, headers={"Accept": "application/json"}
            )
        if response.status_code >= 400:
            raise _to_http_exception(response)
        return _unwrap_odata(response)

    async def create(self, entity_set: str, payload: dict[str, Any]) -> Any:
        """POST to an entity set using the CSRF dance, with one re-fetch on 403."""
        # One aggregate deadline for the whole CSRF + retry sequence, so a degraded SAP
        # cannot pin a worker for up to 4x the per-request timeout.
        try:
            async with asyncio.timeout(self._timeout):
                async with self._new_client() as client:
                    token = await self._fetch_csrf(client)
                    response = await self._post(client, entity_set, payload, token)
                    if response.status_code == 403:  # token invalid/expired -> retry once
                        token = await self._fetch_csrf(client)
                        response = await self._post(client, entity_set, payload, token)
        except TimeoutError as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="SAP no respondió a tiempo.",
            ) from exc
        if response.status_code >= 400:
            raise _to_http_exception(response)
        return _unwrap_odata(response)

    async def _fetch_csrf(self, client: httpx.AsyncClient) -> str:
        response = await client.get(
            "", headers={"X-CSRF-Token": "Fetch", "Accept": "application/json"}
        )
        # Route failures through the same sanitized mapping as read/create (not a raw
        # raise_for_status, which would bubble up as an unhandled 500 with a traceback).
        if response.status_code >= 400:
            raise _to_http_exception(response)
        token = response.headers.get("x-csrf-token")
        if not token:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="SAP no devolvió un token CSRF.",
            )
        return token

    @staticmethod
    async def _post(
        client: httpx.AsyncClient, entity_set: str, payload: dict[str, Any], token: str
    ) -> httpx.Response:
        return await client.post(
            entity_set,
            json=payload,
            headers={
                "X-CSRF-Token": token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )


def _unwrap_odata(response: httpx.Response) -> Any:
    """Unwrap an OData V2 body.

    Entity reads return {"d": {...}}; collection reads return {"d": {"results": [...]}}.
    Returns the list for collections and the object for single entities. A successful
    empty response (204 / no body, common for OData writes) yields None instead of
    crashing on json() of an empty payload.
    """
    if response.status_code == 204 or not response.content:
        return None
    try:
        body = response.json()
    except ValueError as exc:
        logger.warning("SAP returned a non-JSON success body (status %s)", response.status_code)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Respuesta inesperada de SAP.",
        ) from exc
    data = body.get("d") if isinstance(body, dict) else None
    if isinstance(data, dict) and "results" in data:
        return data["results"]
    return data


def _to_http_exception(response: httpx.Response) -> HTTPException:
    """Map a SAP/OData error to a clean, sanitized HTTP error.

    SAP internals (entity-set names, ABAP classes, system ids in the OData message) are
    logged server-side, never forwarded to the app. SAP auth failures (401/403) concern
    OUR technical user, and SAP 5xx are upstream faults — both surface as 502 so the app
    never mistakes them for the end user's session expiring (which would force a spurious,
    looping logout of every valid user).
    """
    logger.warning("SAP error %s: %s", response.status_code, response.text[:500])
    if response.status_code in (401, 403) or response.status_code >= 500:
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Error al comunicarse con SAP. Intenta de nuevo.",
        )
    return HTTPException(
        status_code=response.status_code,
        detail="Error al comunicarse con SAP.",
    )


@lru_cache
def get_sap_client() -> SapClient:
    settings = get_settings()
    return SapClient(
        base_url=settings.sap_base_url,
        user=settings.sap_user,
        password=settings.sap_password,
        timeout=settings.sap_timeout_seconds,
    )
