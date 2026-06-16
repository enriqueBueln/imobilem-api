"""FastAPI application factory.

Creates the app, configures CORS for the Expo app, and registers the domain routers.
Run it with:  uv run uvicorn app.main:app --reload

Django equivalent: the ASGI entrypoint + the root urls.py wiring.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, health
from app.api.documents import get_document_routers
from app.core.config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup/shutdown hook — for future shared resources (pools, caches, etc.).
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Imobilem API",
        version="0.1.0",
        description="Backend intermediario entre la app de autorizaciones y SAP S/4HANA.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(auth.router)
    for document_router in get_document_routers():
        app.include_router(document_router)
    return app


app = create_app()
